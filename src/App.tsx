import { useEffect, useMemo, useRef, useState } from 'react';
import {
  Activity, ArrowUpRight, BarChart3, Box, Check, ChevronDown,
  CircleHelp, Database,
  MoreHorizontal, Play, Plus, Settings2, SlidersHorizontal, Sparkles,
  Terminal, Upload, Waves,
  FileText, GitBranch, ScanLine, Download, CheckCircle2,
  AlertTriangle, RefreshCw, Cpu,
  Filter as FilterIcon, Sigma, Image as ImageIcon, AudioWaveform, Boxes,
} from 'lucide-react';
import { getToken } from './api/client';
import {
  getValidation,
  getWeld,
  listVersions,
  runValidation,
} from './api/welds';
import {
  createBuildTask,
  createDatasetVersion,
  getDatasetVersion,
  getReadiness,
  listDatasets,
} from './api/datasets';
import {
  createAlignmentTask,
  getLatestAlignmentTask,
  createSplitTask,
  createFeatureExtractionTask,
  getFeatureExtraction,
  downloadFeatureExtraction,
  getLatestFeatureExtraction,
  getSignals,
  previewSplitTask,
} from './api/analysis';
import { getFileUrl, presignUpload, uploadFile } from './api/files';
import {
  createInferenceTask,
  createModel,
  createTestTask,
  createTrainingTask,
  exportModelVersion,
  getModel,
  getTrainingLogs,
  listModels,
  updateModelVersionStatus,
} from './api/models';
import { useJob } from './hooks/useJob';
import type {
  AlignmentResult,
  AlignmentTrack,
  DataRecord,
  Dataset,
  DatasetQuality,
  DatasetSplit,
  FeatureExtraction,
  InferenceResult,
  Model,
  ModelSummary,
  ModelVersion,
  SignalData,
  SplitResult,
  TestResult,
  TrainingResult,
  ValidationReport,
  ValidationRuleResult,
} from './api/types';
import Login from './pages/Login';
import { OverviewPage } from './features/overview/OverviewPage';
import { PageIntro } from './shared/components/PageIntro';
import { StatusPill } from './shared/components/StatusPill';
import { Toolbar } from './shared/components/Toolbar';
import { formatDateTime } from './shared/lib/formatting';
import { DatasetWorkspace } from './features/datasets/DatasetWorkspace';
import {
  AnalysisSelect, DatasetTestingContext, SelectionRequired, SelectionSwitcher, VersionPanel,
} from './features/data-context/DataContext';
import { RegistrationPage } from './features/registration/RegistrationPage';
import { AnnotationWorkspace } from './features/annotation/AnnotationWorkspace';
import { AdvancedWeldAnalysis, SampleWaveThumb } from './features/analysis/AnalysisWorkspace';
import type { SplitPreviewSample } from './features/analysis/AnalysisWorkspace';
import { navStructure, workspaceHeaders } from './app/navigation';
import type { Route } from './app/navigation';
import {
  chanColor, fmt, buildPath,
} from './features/analysis/signals/chartData';

function AppShell() {
  const [route, setRoute] = useState<Route>('overview');
  const [datasetHomeKey, setDatasetHomeKey] = useState(0);
  const [selectedDatasetId, setSelectedDatasetId] = useState<number | null>(null);
  const [selectedDataId, setSelectedDataId] = useState<string | null>(null);
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set());
  const workspace = route.split('/')[0];
  const navigate = (r: Route) => {
    setRoute(r);
    if (r === 'data-center/datasets') setDatasetHomeKey((value) => value + 1);
    setExpandedGroups((prev) => new Set(prev).add(r.split('/')[0]));
  };
  const toggleGroup = (id: string) => setExpandedGroups((prev) => {
    const next = new Set(prev);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });
  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand-mark"><Sparkles size={18} strokeWidth={2.5} /></div><div className="brand-copy"><strong>ForgeLab</strong><span>工业智能实验室</span></div>
      <div className="workspace-label">工作空间</div><nav className="main-nav">{navStructure.map((group) => {
        const Icon = group.icon;
        if (group.route && !group.children) {
          return <button key={group.id} className={`nav-item ${route === group.route ? 'active' : ''}`} onClick={() => navigate(group.route!)}><Icon size={18} /><span>{group.label}</span>{route === group.route && <span className="nav-pip" />}</button>;
        }
        const isExpanded = expandedGroups.has(group.id);
        return <div key={group.id} className="nav-group">
          <button className={`nav-item ${workspace === group.id ? 'active' : ''}`} onClick={() => { if (group.id === 'data-center') { if (workspace === group.id) toggleGroup(group.id); else navigate('data-center/datasets'); } else if (group.route) navigate(group.route); else toggleGroup(group.id); }}><Icon size={18} /><span>{group.label}</span><ChevronDown size={15} className={`nav-chevron ${isExpanded ? 'expanded' : ''}`} /></button>
          {isExpanded && <div className="nav-submenu">{group.children!.map((child) => <button key={child.route} className={`nav-subitem ${route === child.route ? 'active' : ''}`} onClick={() => navigate(child.route)}><span className="nav-sub-dot" />{child.label}</button>)}</div>}
        </div>;
      })}</nav>
      <div className="sidebar-bottom"><button className="nav-item"><Settings2 size={18} /><span>系统设置</span></button><div className="user-card"><div className="avatar">林</div><div><strong>林工</strong><span>管理员</span></div><MoreHorizontal size={16} /></div></div>
    </aside>
    <main className="main-content">
      {route === 'overview' && <OverviewPage navigate={navigate} />}
      {route !== 'overview' && <WorkspaceFrame route={route} selectedDatasetId={selectedDatasetId} setSelectedDatasetId={setSelectedDatasetId} selectedDataId={selectedDataId} setSelectedDataId={setSelectedDataId} datasetHomeKey={datasetHomeKey} navigate={navigate} />}
    </main>
  </div>;
}

/**
 * 登录闸门（§4.3）：无 token → 渲染最小登录页；登录成功后 AppShell 才挂载。
 * 仅包一层，不改动 AppShell 及其内部所有 UI 组件。
 */
function App() {
  const [token, setToken] = useState(() => getToken());
  if (!token) {
    return <Login onSuccess={() => setToken(getToken())} />;
  }
  return <AppShell />;
}

function WorkspaceFrame({ route, selectedDatasetId, setSelectedDatasetId, selectedDataId, setSelectedDataId, datasetHomeKey, navigate }: { route: Route; selectedDatasetId: number | null; setSelectedDatasetId: (id: number | null) => void; selectedDataId: string | null; setSelectedDataId: (id: string | null) => void; datasetHomeKey: number; navigate: (r: Route) => void }) {
  const ws = route.split('/')[0];
  const header = route === 'model-center/dataset-build'
    ? { eyebrow: '模型研发中心', title: '训练数据准备', description: '基于数据中心的数据集，筛选可用于模型训练的样本并生成固定版本。' }
    : workspaceHeaders[ws];
  // 模型资产刷新计数（「新建模型」成功后自增，触发 ModelRepository 重新拉取）。
  const [repoRefresh, setRepoRefresh] = useState(0);
  const [isDatasetDetail, setIsDatasetDetail] = useState(false);
  useEffect(() => { if (route !== 'data-center/datasets') setIsDatasetDetail(false); }, [route]);
  // 工作区工具栏只承载 WorkspaceFrame 自己拥有回调的操作；各业务页的操作由页面内部负责。
  const toolbarConfig = ws === 'data-center' && route === 'data-center/datasets' && isDatasetDetail
    ? { action: '上传数据', secondary: undefined }
    : route === 'model-center/repository'
      ? { action: '新建模型', secondary: undefined }
      : { action: undefined, secondary: undefined };
  // 当前页/工作区 → 报告导出 type（§3.7）：data-list/validation/analysis/annotation/features/test。
  const exportType = ws === 'data-center' ? 'data-list'
    : route === 'analysis/annotation' ? 'annotation'
    : route === 'analysis/features' ? 'features'
    : ws === 'analysis' ? 'analysis'
    : route === 'model-center/dataset-build' ? undefined
    : ws === 'model-center' ? 'test'
    : undefined;
  const handleRepoCreate = () => {
    createModel({ name: `新模型-${new Date().toISOString().slice(0, 16).replace(/[T:]/g, '')}`, type: '目标检测' })
      .then(() => setRepoRefresh((v) => v + 1))
      .catch((err) => console.warn('[model-center] createModel failed', err));
  };
  // 数据上传是新建数据操作，不依赖当前焊缝上下文；核验/版本页则展示当前上下文。
  const showContext = selectedDataId && (ws === 'analysis' || (ws === 'data-center' && route !== 'data-center/datasets' && route !== 'data-center/registration'));
  const showDataSwitcher = ws === 'analysis' || route === 'data-center/validation' || route === 'data-center/versions';

  let content: React.ReactNode = null;
  if (route === 'data-center/datasets') content = <DatasetWorkspace navigate={navigate} onDetailChange={setIsDatasetDetail} datasetHomeKey={datasetHomeKey} selectedDatasetId={selectedDatasetId} setSelectedDataId={setSelectedDataId} setSelectedDatasetId={setSelectedDatasetId} />;
  else if (route === 'data-center/registration') content = <RegistrationPage />;
  else if (route === 'data-center/validation') content = selectedDataId ? <Validation embedded dataId={selectedDataId!} /> : <SelectionRequired onBack={() => navigate('data-center/datasets')} />;
  else if (route === 'data-center/versions') content = selectedDataId ? <VersionPanel dataId={selectedDataId!} /> : <SelectionRequired onBack={() => navigate('data-center/datasets')} />;
  else if (route === 'analysis/select') content = <AnalysisSelect selectedDatasetId={selectedDatasetId} setSelectedDatasetId={setSelectedDatasetId} onContinue={(id: string) => { setSelectedDataId(id); navigate('analysis/alignment'); }} />;
  else if (route === 'analysis/alignment') content = selectedDatasetId != null && selectedDataId ? <Alignment embedded dataId={selectedDataId} /> : <SelectionRequired onBack={() => navigate('analysis/select')} />;
  else if (route === 'analysis/analysis') content = selectedDatasetId != null && selectedDataId ? <AdvancedWeldAnalysis embedded dataId={selectedDataId} /> : <SelectionRequired onBack={() => navigate('analysis/select')} />;
  else if (route === 'analysis/split') content = selectedDatasetId != null && selectedDataId ? <Alignment embedded splitOnly dataId={selectedDataId} /> : <SelectionRequired onBack={() => navigate('analysis/select')} />;
  else if (route === 'analysis/annotation') content = selectedDatasetId != null && selectedDataId ? <AnnotationWorkspace embedded dataId={selectedDataId} /> : <SelectionRequired onBack={() => navigate('analysis/select')} />;
  else if (route === 'analysis/features') content = selectedDatasetId != null && selectedDataId ? <FeatureExtraction embedded dataId={selectedDataId} /> : <SelectionRequired onBack={() => navigate('analysis/select')} />;
  else if (route === 'model-center/dataset-build') content = <TrainingDataPreparation />;
  else if (route === 'model-center/repository') content = <ModelRepository refreshKey={repoRefresh} navigate={navigate} />;
  else if (route === 'model-center/training') content = <Training />;
  else if (route === 'model-center/testing') content = <><DatasetTestingContext /><ModelTestLive /></>;
  else if (route === 'model-center/inference') content = <InferencePanel />;

  const frameAction = ws === 'data-center' && route === 'data-center/datasets' ? () => navigate('data-center/registration') : route === 'model-center/repository' ? handleRepoCreate : undefined;
  return <div className={`workspace-page ${route === 'model-center/repository' ? 'model-repository-page' : ''}`}><div className="workspace-page-head"><div><div className="eyebrow"><span />{header.eyebrow}</div><h1>{header.title}</h1><p>{header.description}</p></div>{(toolbarConfig.action || toolbarConfig.secondary) && <Toolbar action={toolbarConfig.action} secondary={toolbarConfig.secondary} exportType={exportType} onAction={frameAction} />}</div>{showDataSwitcher && <SelectionSwitcher selectedDatasetId={selectedDatasetId} setSelectedDatasetId={setSelectedDatasetId} selectedDataId={selectedDataId} setSelectedDataId={setSelectedDataId} showContext={Boolean(showContext)} onChange={ws === 'data-center' ? () => navigate('data-center/datasets') : undefined} />}{content}</div>;
}

/** 模型核心指标（后端 metric 为 dict）→ 卡片展示文案（F1/mAP50/mIoU/R²/Acc）。 */
function modelMetricText(metric: Record<string, unknown> | null | undefined): string {
  const val = (k: string) => (metric && typeof metric[k] === 'number' ? (metric[k] as number) : null);
  const f1 = val('f1');
  if (f1 != null) return `F1 ${(f1 * 100).toFixed(1)}%`;
  const mAP = val('mAP50');
  if (mAP != null) return `mAP50 ${(mAP * 100).toFixed(1)}%`;
  const miou = val('miou');
  if (miou != null) return `mIoU ${(miou * 100).toFixed(1)}%`;
  const r2 = val('r2');
  if (r2 != null) return `R² ${r2}`;
  const acc = val('accuracy');
  if (acc != null) return `Acc ${(acc * 100).toFixed(1)}%`;
  return '—';
}
const modelCatalog = [
  { name: '熔池分割模型', type: '语义分割', description: '从视频帧中提取熔池区域，服务于熔池形态分析。', icon: ScanLine },
  { name: '焊接异常检测模型', type: '时序分类', description: '融合电流、电压和送丝信号，识别焊接过程异常。', icon: Activity },
  { name: '质量预测模型', type: '多模态回归', description: '结合时序、视觉与声音特征，预测焊接质量。', icon: BarChart3 },
];
function ModelRepository({ refreshKey = 0, navigate }: { refreshKey?: number; navigate: (route: Route) => void }) {
  const [summary, setSummary] = useState<ModelSummary | null>(null);
  const [models, setModels] = useState<Model[]>([]);
  const [repoLoading, setRepoLoading] = useState(true);
  const [selectedModel, setSelectedModel] = useState<Model | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [exporting, setExporting] = useState<number | null>(null);
  const [updatingStatus, setUpdatingStatus] = useState<number | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    setRepoLoading(true);
    listModels().then((res) => {
      if (cancelled) return;
      setModels(res.models ?? []);
      setSummary(res.summary);
    }).catch((err) => {
      if (cancelled) return;
      setSummary(null);
      setModels([]);
      setNotice('模型资产暂时无法读取，请稍后重试。');
      console.warn('[model-center] listModels failed', err);
    }).finally(() => { if (!cancelled) setRepoLoading(false); });
    return () => { cancelled = true; };
  }, [refreshKey]);
  const openDetail = (model: Model) => { setDetailLoading(true); setSelectedModel(model); getModel(String(model.id)).then(setSelectedModel).catch(() => setNotice('模型详情暂时无法读取。')).finally(() => setDetailLoading(false)); };
  const handleExport = (version: ModelVersion) => { if (!selectedModel || exporting != null) return; setExporting(version.id); setNotice(null); exportModelVersion(selectedModel.id, version.id).then(() => setNotice(`已提交 ${version.version_no} 的 ONNX 导出任务。`)).catch(() => setNotice('模型导出暂时不可用，请稍后重试。')).finally(() => setExporting(null)); };
  const handleStatus = (version: ModelVersion, status: string) => { if (!selectedModel || updatingStatus != null) return; setUpdatingStatus(version.id); setNotice(null); updateModelVersionStatus(String(selectedModel.id), String(version.id), { status }).then((updated) => { setSelectedModel((current) => current ? { ...current, versions: current.versions?.map((item) => item.id === updated.id ? updated : item), status: updated.status, version: updated.version_no, metric: updated.metric, latest_version_id: updated.id } : current); return listModels(); }).then((res) => { setModels(res.models ?? []); setSummary(res.summary); }).catch(() => setNotice('模型状态更新失败，请稍后重试。')).finally(() => setUpdatingStatus(null)); };
  return <div className="model-repository"><section className="model-repository-hero"><div className="model-repository-hero-icon"><Cpu size={25} /></div><div className="model-repository-hero-copy"><span className="eyebrow"><i />模型资产管理</span><h2>让每个模型版本都可追踪、可评估、可发布</h2><p>模型资产统一承接模型登记、版本管理、指标评估、权重导出和推理验证。</p></div><button className="primary-button" onClick={() => navigate('model-center/training')}><Play size={15} />开始一次训练</button></section><div className="repository-summary"><div><span>模型总数</span><strong>{summary?.total ?? '—'}</strong></div><div><span>生产候选</span><strong>{summary?.prod_candidates ?? '—'}</strong></div><div><span>最近训练</span><strong>{summary?.recent_training ? formatDateTime(summary.recent_training) : '—'}</strong></div></div>{notice && <p className="toolbar-error" role="status">{notice}</p>}{repoLoading ? <p className="dataset-empty-state" role="status">模型资产加载中…</p> : models.length ? <div className="model-card-grid">{models.map((model) => <section className="panel model-card" key={model.id}><div className="model-card-top"><div className="model-logo"><Cpu size={17} /></div><StatusPill tone={model.status === '训练中' ? 'orange' : 'green'}>{model.status ?? '无版本'}</StatusPill><MoreHorizontal size={16} className="muted-icon" /></div><h2>{model.name}</h2><p>{model.type} · {model.version ?? '暂无版本'}</p><div className="model-metric"><span>核心指标</span><strong>{modelMetricText(model.metric)}</strong></div><div className="model-card-footer"><span>{model.description ?? '暂无模型描述'}</span><button className="ghost-button" onClick={() => openDetail(model)}>查看详情 <ArrowUpRight size={13} /></button></div></section>)}</div> : <><div className="model-catalog-heading"><div><h2>标准模型目录</h2><p>平台预留的三类模型能力入口，训练完成后会在这里生成版本。</p></div><button className="outline-button" onClick={() => navigate('model-center/training')}><Plus size={14} />新建训练任务</button></div><div className="model-catalog-grid">{modelCatalog.map(({ name, type, description, icon: Icon }) => <section className="panel model-catalog-card" key={name}><div className="model-catalog-icon"><Icon size={20} /></div><StatusPill tone="blue">待接入版本</StatusPill><h3>{name}</h3><span>{type}</span><p>{description}</p><button className="ghost-button" onClick={() => navigate('model-center/training')}>去创建版本 <ArrowUpRight size={13} /></button></section>)}</div></>}{selectedModel && <div className="app-dialog-backdrop" role="presentation" onClick={() => setSelectedModel(null)}><section className="app-dialog model-detail-dialog" role="dialog" aria-modal="true" aria-label="模型详情" onClick={(event) => event.stopPropagation()}><div className="app-dialog-head"><div><h2>{selectedModel.name}</h2><p>{selectedModel.type} · {selectedModel.description ?? '暂无描述'}</p></div><button className="icon-button" onClick={() => setSelectedModel(null)} aria-label="关闭">×</button></div>{detailLoading ? <p className="dataset-empty-state">详情加载中…</p> : <div className="model-version-list">{selectedModel.versions?.length ? selectedModel.versions.map((version) => <div className="model-version-row" key={version.id}><div><strong>{version.version_no}</strong><span>{version.status} · {modelMetricText(version.metric)}</span><small>{version.created_at ? formatDateTime(version.created_at) : '暂无创建时间'}</small></div><div className="model-version-actions"><button className="outline-button" disabled={!version.file_key || exporting === version.id} onClick={() => handleExport(version)}><Download size={14} />{exporting === version.id ? '导出中…' : '导出 ONNX'}</button>{version.status === '生产候选' ? <button className="ghost-button" disabled={updatingStatus === version.id} onClick={() => handleStatus(version, '实验版本')}>{updatingStatus === version.id ? '更新中…' : '退回实验版'}</button> : <button className="ghost-button" disabled={updatingStatus === version.id} onClick={() => handleStatus(version, '生产候选')}>{updatingStatus === version.id ? '更新中…' : '设为生产候选'}</button>}</div></div>) : <p className="dataset-empty-state">该模型暂无版本。</p>}</div>}</section></div>}</div>;
}

function InferencePanel() {
  const [modelVersionId, setModelVersionId] = useState<number | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const { status: jobStatus, result: inferRes } = useJob<InferenceResult>(jobId);
  useEffect(() => {
    let cancelled = false;
    listModels().then((res) => {
      if (cancelled) return;
      const withVersion = res.models.filter((m) => m.latest_version_id != null);
      const prod = withVersion.find((m) => m.status === '生产候选') ?? withVersion[0];
      if (prod?.latest_version_id != null) setModelVersionId(prod.latest_version_id);
    }).catch((err) => { if (!cancelled) console.warn('[inference] listModels failed', err); });
    return () => { cancelled = true; };
  }, []);
  const handleFile = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    if (modelVersionId == null) { console.warn('[inference] Model version is not ready; please try again later'); return; }
    const upload = file.size < 100 * 1024 * 1024
      ? uploadFile(file).then((r) => r.object_key)
      : presignUpload({ size: file.size, content_type: file.type || 'application/octet-stream', prefix: 'inference' }).then(async (r) => {
          const res = await fetch(r.upload_url, { method: 'PUT', body: file });
          if (!res.ok) throw new Error(`[inference] presign PUT failed: ${res.status}`);
          return r.object_key;
        });
    upload
      .then((objectKey) => {
        const fileName = file.name.toLowerCase();
        const isImage = file.type.startsWith('image/') || /\.(png|jpe?g|webp|bmp)$/.test(fileName);
        const isVideo = file.type.startsWith('video/') || /\.(mp4|mov|avi|mkv|webm)$/.test(fileName);
        // 后端契约使用 image/video；页面展示文案仍可使用中文。
        const inputType = isImage ? 'image' : isVideo ? 'video' : 'image';
        return createInferenceTask({ model_version_id: modelVersionId, input: objectKey, input_type: inputType });
      })
      .then((res) => setJobId(res.job_id))
      .catch((err) => console.warn('[inference] Inference submission failed', err));
  };
  const statusText = jobStatus === 'running' ? '运行中' : jobStatus === 'failed' ? '失败' : jobStatus === 'succeeded' ? '已完成' : modelVersionId == null ? '待配置' : '就绪';
  const statusTone = (jobStatus === 'running' || modelVersionId == null ? 'orange' : jobStatus === 'failed' ? 'red' : 'green') as 'green' | 'orange' | 'red';
  const inferSummary = inferRes && inferRes.categories.length ? `${inferRes.categories.length} 个目标 · ${inferRes.categories.join(' / ')}` : '推理结果将在这里展示';
  const confText = inferRes?.confidence?.length ? `${(Math.max(...inferRes.confidence) * 100).toFixed(1)}%` : '—';
  return <section className="panel inference-panel"><div className="panel-heading"><div><h2>推理验证</h2><p>选择模型和样本，预览模型输出结果</p></div><StatusPill tone={statusTone}>{statusText}</StatusPill></div><input ref={fileRef} type="file" accept="image/*,video/*" hidden onChange={handleFile} /><div className="inference-layout"><div className="inference-drop"><Upload size={23} /><strong>选择测试样本</strong><span>{modelVersionId == null ? '请先完成模型训练并生成可用版本' : '支持图像、视频帧或时序信号'}</span><button className="outline-button" disabled={modelVersionId == null || jobStatus === 'running'} onClick={() => fileRef.current?.click()}>选择样本</button></div><div className="inference-result"><div className="result-placeholder"><ScanLine size={28} /><span>{inferSummary}</span></div><div className="result-row"><span>模型置信度</span><strong>{confText}</strong></div><div className="result-row"><span>推理耗时</span><strong>{inferRes ? `${inferRes.latency_ms}ms` : '—'}</strong></div></div></div></section>;
}

/** 数据列表：每页条数 + tab 演示计数（API 返回后 active tab 显示响应 total）。 */
/** 上传数据：分类型上传区配置（CSV / 图片 / 视频 / WAV 各自独立）。 */
/** 核验规则演示名单（仅接口失败/无版本可查时兜底，不得在加载期显示）。 */
const mockValidationRuleNames = ['图像文件完整性', '时序信号连续性', '采样频率一致性', '起收弧事件完整', '电流范围合理性', '电压范围合理性', '送丝速度缺失值', '多模态时间戳', '视频帧率稳定性', '文件命名规范', '焊缝ID唯一性', '工艺参数完整性', '音频信号质量', '红外数据完整性', '元数据关联关系'];

function Validation({ dataId }: { embedded?: boolean; dataId?: string }) {
  // 初始为空 + 加载中：mock 报告仅在接口失败/无版本可查时兜底，不得在加载期闪现假核验结论
  const [report, setReport] = useState<ValidationReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState<string | null>(null);
  const [versionId, setVersionId] = useState<number | null>(null);
  const [running, setRunning] = useState(false);
  const [statusFilter, setStatusFilter] = useState<'all' | 'passed' | 'warning' | 'failed'>('all');
  useEffect(() => {
    let cancelled = false;
    const fallback = () => {
      setLoading(false);
      setNotice('核验结果暂时无法加载，请点击“执行核验”或稍后重试。');
      setReport((prev) => prev ?? {
        id: 0,
        version_id: 0,
        score: 93.3,
        passed: 14,
        warning: 1,
        failed: 0,
        duration: 2.8,
        created_at: '2026-08-15T09:45:00',
        rules: mockValidationRuleNames.map((name, index) => ({ rule_name: name, status: index === 8 ? 'warning' : 'passed', message: index === 8 ? '视频帧率存在轻微波动，建议复核' : '检查通过 · 结果已记录' })),
      });
    };
    if (!dataId) { fallback(); return; }
    getWeld(dataId).then((r) => {
      if (cancelled) return;
      const vid = r.latest_version_id ?? r.latest_version?.id ?? null;
      if (vid == null) { fallback(); return; }
      setVersionId(vid);
      getValidation(dataId, String(vid)).then((rep) => { if (!cancelled) { setReport(rep); setLoading(false); } }).catch((err) => { if (!cancelled) { fallback(); console.warn('[validation] getValidation failed', err); } });
    }).catch((err) => { if (!cancelled) { fallback(); console.warn('[validation] getWeld failed', err); } });
    return () => { cancelled = true; };
  }, [dataId]);
  const loadReport = () => {
    if (!dataId || versionId == null) return;
    setLoading(true);
    setNotice(null);
    getValidation(dataId, String(versionId))
      .then(setReport)
      .catch(() => setNotice('该版本尚未执行核验，请点击“执行核验”。'))
      .finally(() => setLoading(false));
  };
  const runNow = () => {
    if (!dataId || versionId == null) return;
    setRunning(true);
    setNotice(null);
    runValidation(dataId, String(versionId))
      .then((next) => { setReport(next); setNotice('核验完成，结果已保存并已回写数据质量状态。'); })
      .catch((err) => { setNotice('执行核验失败，请稍后重试。'); console.warn('[validation] runValidation failed', err); })
      .finally(() => setRunning(false));
  };
  const rules: ValidationRuleResult[] = report?.rules ?? [];
  const passed = report?.passed ?? 0;
  const warning = report?.warning ?? 0;
  const failed = report?.failed ?? 0;
  const statusText = report ? (failed > 0 ? '异常' : warning > 0 ? '待复核' : '核验通过') : '加载中';
  const statusTone = report ? (failed > 0 ? 'red' : warning > 0 ? 'orange' : 'green') : 'blue';
  const lastRun = report && report.created_at ? `最近核验：${formatDateTime(report.created_at)} · 核验耗时 ${report.duration != null ? report.duration : '—'}s` : '正在加载核验结果…';
  const visibleRules = statusFilter === 'all' ? rules : rules.filter((rule) => rule.status === statusFilter);
  return <div className="page-wrap"><PageIntro eyebrow="数据质量中心" title="数据核验" description="通过标准化规则检查数据完整性、连续性与多模态一致性。支持自动规则核验，也支持人工点击重新核验并复核结果。" action={<Toolbar action={running ? '核验中…' : '执行核验'} secondary="下载核验报告" onAction={runNow} onRefresh={loadReport} exportType="validation" exportRefIds={report ? [report.id] : undefined} actionDisabled={running || !dataId || versionId == null} />} /><div className="validation-summary"><div className="validation-score"><div className="score-ring small"><div><strong>{report ? report.score : '—'}</strong><span>质量评分</span></div></div><div><h2>{dataId ?? '—'}</h2><p>{lastRun}</p><StatusPill tone={statusTone as 'green' | 'orange' | 'red' | 'blue'}>{statusText}</StatusPill></div></div><div className="validation-count"><div><strong>{passed}</strong><span>通过规则</span></div><div><strong className="warning-text">{warning}</strong><span>警告</span></div><div><strong className="danger-text">{failed}</strong><span>失败</span></div></div></div>{notice && <p className="dataset-empty-state" role="status">{notice}</p>}<section className="panel validation-panel"><div className="panel-heading"><div><h2>核验规则明细 <span className="inline-count">{visibleRules.length}/{rules.length} 项</span></h2><p>已覆盖图像、时序、视频、元数据与跨模态一致性检查</p></div><label className="filter-field">状态<select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value as typeof statusFilter)}><option value="all">全部状态</option><option value="passed">通过</option><option value="warning">警告</option><option value="failed">失败</option></select></label></div><div className="rule-grid">{visibleRules.length ? visibleRules.map((rule, index) => { const isWarn = rule.status === 'warning'; const isFail = rule.status === 'failed'; const tone = isFail ? 'red' : isWarn ? 'orange' : 'green'; const label = isFail ? '失败' : isWarn ? '警告' : '通过'; const msg = rule.message ?? (isWarn ? '存在警告，建议复核' : '检查通过 · 结果已记录'); return <div className="validation-rule" key={rule.rule_name || index}><div className={`validation-icon ${isWarn ? 'warning' : isFail ? 'failed' : ''}`}>{isFail || isWarn ? <AlertTriangle size={15} /> : <CheckCircle2 size={15} />}</div><div><strong>{rule.rule_name}</strong><span>{msg}</span></div><StatusPill tone={tone as 'green' | 'orange' | 'red'}>{label}</StatusPill></div>; }) : <p className="dataset-empty-state" role="status">{loading ? '核验规则加载中…' : statusFilter === 'all' ? '暂无核验规则' : '没有符合该状态的规则'}</p>}</div></section></div>;
}

const VIDEO_EXTS = ['.mp4', '.avi', '.mkv', '.mov', '.webm'];
const ALIGN_CHANNEL_MAP: Record<string, string> = { current: 'cur', voltage: 'vol' };
const ALIGN_TRACK_META: Record<string, { label: string; tone: string }> = {
  video: { label: '视频帧', tone: 'blue' },
  current: { label: '电流', tone: 'mint' },
  voltage: { label: '电压', tone: 'orange' },
  audio: { label: '音频', tone: 'purple' },
  infrared: { label: '红外', tone: 'blue' },
};

function jobErrorMessage(error: unknown): string {
  if (error && typeof error === 'object' && 'message' in error) {
    const msg = (error as { message?: unknown }).message;
    if (typeof msg === 'string' && msg) return msg;
  }
  return '未知错误';
}

function AvailabilityTag({ track }: { track: AlignmentTrack }) {
  const pair = ({ available: ['真实', 'ok'], generated: ['生成', 'warn'], unavailable: ['缺失', 'bad'] } as Record<string, [string, string]>)[track.availability] ?? ['未知', 'warn'];
  return <span className={`track-availability ${pair[1]}`} title={track.reason ?? undefined}>{pair[0]}</span>;
}

/** 模型中心 · 训练数据准备：从数据中心的数据集筛选样本，生成可用于训练的固定版本快照。 */
function DatasetBuild() {
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [datasetId, setDatasetId] = useState<number | null>(null);
  const [source, setSource] = useState<'manual' | 'split_task' | 'annotation_task'>('manual');
  const [buildJobId, setBuildJobId] = useState<string | null>(null);
  const [buildError, setBuildError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const { status: buildStatus, progress, result: buildResult } = useJob<{ item_count: number; split: Partial<DatasetSplit>; quality: DatasetQuality | null; snapshot_id: string | null }>(buildJobId);
  useEffect(() => {
    let cancelled = false;
    listDatasets().then((list) => { if (cancelled) return; setDatasets(list); setDatasetId((prev) => prev ?? list[0]?.id ?? null); }).catch((err) => console.warn('[dataset-build] listDatasets failed', err)).finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);
  const dataset = datasets.find((d) => d.id === datasetId) ?? null;
  void dataset;
  const handleBuild = () => {
    if (datasetId == null) return;
    setBuildError(null);
    createDatasetVersion(String(datasetId), { name: `构建-${new Date().toISOString().slice(0, 10)}` })
      .then((version) => createBuildTask(String(datasetId), String(version.id), { type: source }))
      .then((res) => setBuildJobId(res.job_id))
      .catch((err) => { setBuildError(err instanceof Error ? err.message : '创建版本/构建失败'); console.warn('[dataset-build] build failed', err); });
  };
  useEffect(() => {
    if (buildStatus === 'succeeded') setBuildJobId(null);
    else if (buildStatus === 'failed') { setBuildJobId(null); setBuildError('数据集构建失败，请重试或检查来源样本'); }
  }, [buildStatus]);
  const split = buildResult?.split;
  const total = split ? (split.train ?? 0) + (split.val ?? 0) + (split.test ?? 0) : 0;
  const slicePct = (v: number | undefined) => (total > 0 && v != null ? `${((v / total) * 100).toFixed(0)}%` : '0%');
  const qualityPct = buildResult?.quality ? `${Math.max(0, Math.min(100, (1 - buildResult.quality.repeat_rate - buildResult.quality.empty_label_rate - buildResult.quality.dimension_missing_rate) * 100)).toFixed(1)}%` : null;
  const sourceMeta: Record<string, { label: string; desc: string }> = {
    manual: { label: '全部样本', desc: '纳入数据集中的全部焊缝样本' },
    split_task: { label: '已切分样本', desc: '仅纳入已完成切分的样本' },
    annotation_task: { label: '已标注样本', desc: '仅纳入已完成标注的样本' },
  };
  return <div className="page-wrap"><PageIntro eyebrow="模型研发中心" title="训练数据准备" description="基于数据中心的数据集，筛选可用于模型训练的样本并生成固定版本。" action={<Toolbar secondary="导出报告" />} /><div className="build-steps" aria-label="训练数据准备流程"><span className="current"><b>1</b>选择数据集</span><i /> <span><b>2</b>设定样本范围</span><i /> <span><b>3</b>生成训练数据集</span></div><div className="build-layout"><section className="panel build-config"><div className="panel-heading"><div><h2>准备条件</h2><p>配置完成后生成一份新的训练数据版本</p></div><Box size={17} /></div>{loading ? <p className="dataset-empty-state" role="status">正在读取数据中心的数据集…</p> : <><div className="form-block"><label className="form-label">1. 选择数据集</label><p className="form-help build-form-intro">选择数据中心中已有的数据集，准备动作不会修改原始数据。</p><select className="native-select" value={datasetId ?? ''} onChange={(e) => setDatasetId(e.target.value ? Number(e.target.value) : null)}><option value="">请选择数据集</option>{datasets.map((d) => <option key={d.id} value={d.id}>{d.name} · {d.version ?? '未建版本'}</option>)}</select></div><div className="form-block"><label className="form-label">2. 选择样本范围</label><div className="build-source">{(['manual', 'split_task', 'annotation_task'] as const).map((key) => <label className={source === key ? 'chosen' : ''} key={key}><input type="radio" name="build-source" checked={source === key} onChange={() => setSource(key)} /><span><strong>{sourceMeta[key].label}</strong><small>{sourceMeta[key].desc}</small></span>{source === key && <Check size={15} />}</label>)}</div></div></>}<div className="split-ratio-note"><div className="rule-title"><GitBranch size={15} />自动划分规则</div><b>训练 80% <em>/</em> 验证 10% <em>/</em> 测试 10%</b><small>按焊缝 ID 分组，同一焊缝不会同时进入训练集和测试集，避免数据泄漏。</small></div><button className="full-button" onClick={handleBuild} disabled={datasetId == null || buildJobId != null}>{buildJobId != null ? <><Activity size={16} />正在生成 · {progress}%</> : <><GitBranch size={16} />生成训练数据集</>}</button>{buildError && <p className="dataset-empty-state" role="alert">生成失败：{buildError} 请检查样本范围后重试。</p>}</section><section className="panel build-result"><div className="panel-heading"><div><h2>生成结果</h2><p>{buildJobId != null ? '正在生成训练数据版本…' : buildResult ? '最近一次生成结果' : '完成左侧配置后，这里会显示数据划分结果'}</p></div><StatusPill tone={buildStatus === 'failed' ? 'red' : buildStatus === 'running' ? 'orange' : buildResult ? 'green' : 'muted'}>{buildStatus === 'succeeded' ? '已生成' : buildStatus === 'failed' ? '生成失败' : buildStatus === 'running' ? '生成中' : '未开始'}</StatusPill></div>{buildResult && split ? <><div className="result-context"><CheckCircle2 size={16} /><span>训练数据集已生成，可在“新建训练”中使用</span></div><div className="build-splitbar"><i className="train" style={{ width: slicePct(split.train) }} /><i className="val" style={{ width: slicePct(split.val) }} /><i className="test" style={{ width: slicePct(split.test) }} /></div><div className="build-split-legend"><span><i className="train" />训练集 <b>{split.train ?? 0}</b></span><span><i className="val" />验证集 <b>{split.val ?? 0}</b></span><span><i className="test" />测试集 <b>{split.test ?? 0}</b></span></div><div className="build-stat-row"><div><span>样本总数</span><strong>{buildResult.item_count.toLocaleString()}</strong></div><div><span>质量评分</span><strong>{qualityPct ?? '—'}</strong></div><div><span>版本快照</span><strong>{buildResult.snapshot_id ? buildResult.snapshot_id.slice(0, 8) : '—'}</strong></div></div></> : <div className="build-state"><div className="empty-steps"><span><Database size={17} />选择数据集</span><span><SlidersHorizontal size={17} />选择样本范围</span><span><GitBranch size={17} />生成版本</span></div><strong>{buildJobId != null ? '正在生成训练数据版本' : '还没有训练数据版本'}</strong><p>{buildJobId != null ? `系统正在按焊缝分组生成，当前进度 ${progress}%` : '配置左侧两项条件后，点击“生成训练数据集”即可开始。'}</p></div>}</section></div></div>;
}

// 保留旧名称以兼容外部链接；当前路由使用 TrainingDataPreparation。
void DatasetBuild;

function TrainingDataPreparation() {
  type BuildResult = {
    item_count: number;
    split: Partial<DatasetSplit>;
    quality: DatasetQuality | null;
    snapshot_id: string | null;
  };
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [datasetId, setDatasetId] = useState<number | null>(null);
  const [source, setSource] = useState<'manual' | 'split_task' | 'annotation_task'>('manual');
  const [buildJobId, setBuildJobId] = useState<string | null>(null);
  const [completedBuildResult, setCompletedBuildResult] = useState<BuildResult | null>(null);
  const [buildError, setBuildError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const { status: buildStatus, progress, result: buildResult } = useJob<BuildResult>(buildJobId);
  useEffect(() => {
    let cancelled = false;
    listDatasets().then((list) => { if (cancelled) return; setDatasets(list); setDatasetId((prev) => prev ?? list[0]?.id ?? null); }).catch((err) => console.warn('[training-data] listDatasets failed', err)).finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);
  const dataset = datasets.find((item) => item.id === datasetId) ?? null;
  const selectedDatasetNumericId = dataset?.id;
  const selectedDatasetVersionId = dataset?.current_version_id;
  const isTrainable = dataset?.status === '可训练';
  const previewResult = buildResult ?? completedBuildResult;
  useEffect(() => {
    let cancelled = false;
    if (selectedDatasetNumericId == null || selectedDatasetVersionId == null) {
      setCompletedBuildResult(null);
      return () => { cancelled = true; };
    }
    getDatasetVersion(String(selectedDatasetNumericId), String(selectedDatasetVersionId)).then((version) => {
      if (cancelled || version.item_count <= 0) return;
      setCompletedBuildResult({
        item_count: version.item_count,
        split: version.split,
        quality: version.quality,
        snapshot_id: version.snapshot_id,
      });
    }).catch((err) => {
      if (!cancelled) console.warn('[training-data] current version restore failed', err);
    });
    return () => { cancelled = true; };
  }, [selectedDatasetNumericId, selectedDatasetVersionId]);
  const handleBuild = () => {
    if (datasetId == null || !isTrainable || buildJobId != null) return;
    setCompletedBuildResult(null);
    setBuildError(null);
    createDatasetVersion(String(datasetId), { name: `训练版本-${new Date().toISOString().slice(0, 10)}` })
      .then((version) => createBuildTask(String(datasetId), String(version.id), { type: source }))
      .then((res) => setBuildJobId(res.job_id))
      .catch((err) => setBuildError(err instanceof Error ? err.message : '生成训练数据版本失败'));
  };
  useEffect(() => {
    if (buildStatus === 'succeeded' && buildResult) {
      setCompletedBuildResult(buildResult);
      setBuildJobId(null);
    }
    if (buildStatus === 'failed') setBuildJobId(null);
    if (buildStatus === 'failed') setBuildError('请检查样本范围和数据质量后重试');
  }, [buildStatus, buildResult]);
  const split = previewResult?.split;
  const total = split ? (split.train ?? 0) + (split.val ?? 0) + (split.test ?? 0) : 0;
  const slicePct = (value: number | undefined) => total > 0 && value != null ? `${((value / total) * 100).toFixed(0)}%` : '0%';
  const qualityPct = previewResult?.quality ? `${Math.max(0, Math.min(100, (1 - previewResult.quality.repeat_rate - previewResult.quality.empty_label_rate - previewResult.quality.dimension_missing_rate) * 100)).toFixed(1)}%` : null;
  const sourceMeta: Record<string, { label: string; desc: string }> = {
    manual: { label: '全部样本', desc: '纳入输入数据集中的全部有效样本' },
    split_task: { label: '已切分样本', desc: '仅纳入已完成切分的样本' },
    annotation_task: { label: '已标注样本', desc: '仅纳入已完成标注的样本' },
  };
  return <div className="page-wrap">
    <PageIntro eyebrow="模型研发中心" title="生成训练数据版本" description="从数据中心选择一个已有数据集，筛选样本并生成供模型训练使用的固定版本。" action={<Toolbar secondary="导出报告" />} />
    <div className="build-steps" aria-label="训练数据准备流程"><span className="current"><b>1</b>选择输入数据集</span><i /><span><b>2</b>筛选样本范围</span><i /><span><b>3</b>生成训练版本</span></div>
    <div className="build-layout">
      <section className="panel build-config"><div className="panel-heading"><div><h2>生成条件</h2><p>创建一份新的固定训练数据版本</p></div><Box size={17} /></div>
        {loading ? <p className="dataset-empty-state" role="status">正在读取数据中心的数据集…</p> : datasets.length === 0 ? <div className="build-no-dataset"><Database size={22} /><strong>暂无可用输入数据集</strong><p>请先在数据中心创建数据集并生成版本。</p></div> : <>
          <div className="form-block"><label className="form-label">1. 输入数据集</label><p className="form-help build-form-intro">来源于数据中心，不会修改原始数据。</p><select className="native-select" value={datasetId ?? ''} onChange={(e) => { setDatasetId(e.target.value ? Number(e.target.value) : null); setCompletedBuildResult(null); setBuildError(null); }}><option value="">请选择输入数据集</option>{datasets.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.version ?? '未生成版本'}</option>)}</select>{dataset && <div className="selected-dataset-card"><div className="selected-dataset-head"><span className="dataset-row-icon"><Box size={16} /></span><div><strong>{dataset.name}</strong><small>{dataset.dataset_no} · 当前版本 {dataset.version ?? '未生成'}</small></div><StatusPill tone={dataset.status === '可训练' ? 'green' : 'orange'}>{dataset.status}</StatusPill></div><div className="selected-dataset-meta"><span>样本数 <b>{dataset.sample_count.toLocaleString()}</b></span><span>标注完成度 <b>{dataset.progress != null ? `${dataset.progress}%` : '—'}</b></span></div></div>}</div>
          {isTrainable ? <div className="form-block"><label className="form-label">2. 样本纳入范围</label><div className="build-source">{(['manual', 'split_task', 'annotation_task'] as const).map((key) => <label className={source === key ? 'chosen' : ''} key={key}><input type="radio" name="training-source" checked={source === key} onChange={() => setSource(key)} /><span><strong>{sourceMeta[key].label}</strong><small>{sourceMeta[key].desc}</small></span>{source === key && <Check size={15} />}</label>)}</div></div> : dataset && <div className="build-blocked" role="alert"><AlertTriangle size={18} /><div><strong>当前数据集暂不可训练</strong><p>数据集仍在标注中或尚未通过训练条件检查，请完成标注并通过质量检查后再生成训练数据版本。</p></div></div>}
        </>}
        {isTrainable && <div className="split-ratio-note"><div className="rule-title"><GitBranch size={15} />3. 训练数据划分</div><b>训练 80% <em>/</em> 验证 10% <em>/</em> 测试 10%</b><small>按焊缝 ID 分组，同一焊缝不会同时进入训练集和测试集，避免数据泄漏。</small></div>}
        <button className="full-button" onClick={handleBuild} disabled={datasetId == null || !isTrainable || buildJobId != null}>{buildJobId != null ? <><Activity size={16} />正在生成 · {progress}%</> : <><GitBranch size={16} />生成训练数据版本</>}</button>{buildError && <p className="dataset-empty-state" role="alert">生成失败：{buildError}</p>}
      </section>
      <section className="panel build-result"><div className="panel-heading"><div><h2>训练版本预览</h2><p>{buildJobId != null ? '正在生成训练数据版本…' : previewResult ? '最近一次生成结果' : dataset ? '根据当前配置预览生成结果' : '选择输入数据集后开始预览'}</p></div><StatusPill tone={buildStatus === 'failed' ? 'red' : buildStatus === 'running' ? 'orange' : previewResult ? 'green' : 'muted'}>{buildStatus === 'succeeded' || previewResult ? '已生成' : buildStatus === 'failed' ? '生成失败' : buildStatus === 'running' ? '生成中' : '未开始'}</StatusPill></div>
        {previewResult && split ? <><div className="result-context"><CheckCircle2 size={16} /><span>训练数据版本已生成，可在“新建训练”中使用</span></div><div className="build-splitbar"><i className="train" style={{ width: slicePct(split.train) }} /><i className="val" style={{ width: slicePct(split.val) }} /><i className="test" style={{ width: slicePct(split.test) }} /></div><div className="build-split-legend"><span><i className="train" />训练集 <b>{split.train ?? 0}</b></span><span><i className="val" />验证集 <b>{split.val ?? 0}</b></span><span><i className="test" />测试集 <b>{split.test ?? 0}</b></span></div><div className="build-stat-row"><div><span>样本总数</span><strong>{previewResult.item_count.toLocaleString()}</strong></div><div><span>质量评分</span><strong>{qualityPct ?? '—'}</strong></div><div><span>版本快照</span><strong>{previewResult.snapshot_id ? previewResult.snapshot_id.slice(0, 8) : '—'}</strong></div></div></> : <div className="build-state">{dataset && !isTrainable ? <><strong>当前数据集不符合训练要求</strong><p>完成标注并通过训练条件检查后，才可以生成训练数据版本。</p></> : <><div className="empty-steps"><span><Database size={17} />输入数据集</span><span><SlidersHorizontal size={17} />样本范围</span><span><GitBranch size={17} />训练版本</span></div><strong>{buildJobId != null ? '正在生成训练数据版本' : '还没有训练数据版本'}</strong><p>{buildJobId != null ? `系统正在按焊缝分组生成，当前进度 ${progress}%` : dataset ? `预计纳入 ${dataset.sample_count.toLocaleString()} 条样本，生成后将显示实际划分结果。` : '配置左侧条件后，点击“生成训练数据版本”即可开始。'}</p></>}</div>}
      </section>
    </div>
  </div>;
}

function Alignment({ splitOnly = false, dataId }: { embedded?: boolean; splitOnly?: boolean; dataId?: string }) {
  const [jobId, setJobId] = useState<string | null>(null);
  const [versionId, setVersionId] = useState<number | null>(null);
  const [inputReady, setInputReady] = useState(false);
  const [inputError, setInputError] = useState<string | null>(null);
  const [createError, setCreateError] = useState<string | null>(null);
  const [artifactError, setArtifactError] = useState<string | null>(null);
  const [record, setRecord] = useState<DataRecord | null>(null);
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const [signals, setSignals] = useState<SignalData | null>(null);
  const [playhead, setPlayhead] = useState(0);
  // 对齐任务：纳入对齐的模态（默认取自登记模态，未登记则视频+时序）
  const [modalities, setModalities] = useState<string[]>(['video', 'timeseries']);

  const [fixedRate, setFixedRate] = useState(10);
  const [stride, setStride] = useState(10);
  const [taskFormat, setTaskFormat] = useState('目标检测');
  const [keepEventBuffer, setKeepEventBuffer] = useState(true);
  const [bufferSeconds, setBufferSeconds] = useState(0.2);
  const [previewed, setPreviewed] = useState(false);
  const [eventStart, setEventStart] = useState<number | null>(null);
  const [eventEnd, setEventEnd] = useState<number | null>(null);
  const [splitPreview, setSplitPreview] = useState<import('./api/types').SplitPreview | null>(null);
  const [splitPreviewError, setSplitPreviewError] = useState<string | null>(null);
  const [splitPreviewLoading, setSplitPreviewLoading] = useState(false);
  const hydratedRef = useRef(false);
  const { job, status: jobStatus, progress, result, error: jobError } = useJob<SplitResult | AlignmentResult>(jobId);
  const splitRes = result && 'sample_count' in result ? (result as SplitResult) : null;
  const alignRes = result && 'events' in result ? (result as AlignmentResult) : null;
  // 焊缝详情：最新版本号（handleRun 目标）+ 登记模态（不再硬编码模态表）
  useEffect(() => {
    if (!dataId) return;
    hydratedRef.current = false;
    setJobId(null);
    setInputReady(false);
    setInputError(null);
    setCreateError(null);
    let cancelled = false;
    getWeld(dataId).then((r) => {
      if (cancelled) return;
      setRecord(r);
      setVersionId(r.latest_version_id ?? r.latest_version?.id ?? null);
      setModalities(r.modalities?.length ? r.modalities : ['video', 'timeseries']);
      setInputReady(true);
    }).catch((err) => { if (!cancelled) setInputError(`焊缝信息读取失败：${err instanceof Error ? err.message : '请重试'}`); });
    return () => { cancelled = true; };
  }, [dataId]);
  useEffect(() => {
    if (!dataId || versionId == null || splitOnly || hydratedRef.current) return;
    let cancelled = false;
    getLatestAlignmentTask(dataId, String(versionId)).then((latest) => {
      if (cancelled) return;
      hydratedRef.current = true;
      if (latest) setJobId(latest.id);
    }).catch((err) => {
      if (!cancelled) {
        hydratedRef.current = true;
        setInputError(`历史对齐任务读取失败：${err instanceof Error ? err.message : '请重试'}`);
      }
    });
    return () => { cancelled = true; };
  }, [dataId, versionId, splitOnly]);
  // 当前版本原始数据 → 真实视频预签名 URL + 真实信号波形
  useEffect(() => {
    if (!dataId) return;
    let cancelled = false;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    setVideoUrl(null);
    listVersions(dataId).then((versions) => {
      if (cancelled) return;
      const sourceVersion = versions.find((v) => v.id === versionId) ?? versions[versions.length - 1];
      if (!sourceVersion) return;
      // 兼容旧的对齐版本：当前版本可能只有处理产物，回溯同一焊缝最近含视频的版本。
      const orderedVersions = [sourceVersion, ...[...versions].reverse().filter((v) => v.id !== sourceVersion.id)];
      const videoKey = orderedVersions
        .flatMap((v) => v.object_keys ?? [])
        .find((k) => VIDEO_EXTS.some((e) => k.toLowerCase().endsWith(e)));
      const loadPlayableVideo = (attempt = 0) => {
        if (!videoKey || cancelled) return;
        getFileUrl(videoKey, 86400).then((r) => {
          if (cancelled) return;
          if (r.processing && attempt < 40) {
            retryTimer = setTimeout(() => loadPlayableVideo(attempt + 1), 3000);
            return;
          }
          if (r.processing) {
            setInputError('视频正在生成浏览器预览版，请稍后刷新页面。');
            return;
          }
          setVideoUrl(r.url);
        }).catch((err) => { if (!cancelled) setInputError(`视频读取失败：${err instanceof Error ? err.message : '请检查文件'}`); });
      };
      loadPlayableVideo();
       getSignals(dataId, String(sourceVersion.id)).then((s) => { if (!cancelled) setSignals(s); }).catch((err) => { if (!cancelled) setInputError(`信号读取失败：${err instanceof Error ? err.message : '请检查导入状态'}`); });
    }).catch((err) => { if (!cancelled) setInputError(`数据版本读取失败：${err instanceof Error ? err.message : '请重试'}`); });
    return () => { cancelled = true; if (retryTimer) clearTimeout(retryTimer); };
  }, [dataId, versionId, splitOnly]);
  // 对齐成功：时间轴切到新版本；视频轨道有源对象 → 用内核实际使用的视频刷新播放器
  useEffect(() => {
    if (!alignRes) return;
    setVersionId(alignRes.version.id);
  }, [alignRes]);
  const handleRun = () => {
    if (!dataId || versionId == null) { setCreateError('当前焊缝版本尚未准备好，请稍后重试。'); return; }
    setCreateError(null);
    const unsupported = !splitOnly ? modalities.filter((item) => item === 'audio' || item === 'infrared') : [];
    const names: Record<string, string> = { video: '视频', timeseries: '时序', audio: '音频', infrared: '红外' };
    const warning = unsupported.length ? `\n${unsupported.map((item) => names[item]).join('、')}当前仅登记元数据，暂不会执行真正的时间对齐。` : '';
    if (!window.confirm(`确认${splitOnly ? '创建切分任务' : '开始多模态对齐'}？\n输入版本：v${versionId}\n参与模态：${modalities.map((item) => names[item] ?? item).join('、') || '无'}${warning}`)) return;
    const run = splitOnly
      ? createSplitTask(dataId, String(versionId), { fixed_rate: fixedRate, stride, keep_event_buffer: keepEventBuffer ? bufferSeconds : 0, task_format: taskFormat, event_start: eventStart ?? undefined, event_end: eventEnd ?? undefined })
      : createAlignmentTask(dataId, String(versionId), modalities.length ? modalities : ['video', 'timeseries']);
    run.then((res) => setJobId(res.job_id)).catch((err) => setCreateError(`任务创建失败：${err instanceof Error ? err.message : '请检查输入后重试'}`));
  };
  const tone = inputError || createError || artifactError || jobError || jobStatus === 'failed' ? 'red' : jobStatus === 'running' || jobStatus === 'pending' ? 'orange' : jobStatus === 'succeeded' ? 'green' : 'muted';
  const statusText = inputError ?? createError ?? artifactError ?? (jobError ? '任务状态读取失败' : !inputReady ? '正在读取输入' : jobStatus === 'succeeded' ? (splitOnly ? '切分完成' : '对齐完成') : jobStatus === 'running' ? `处理中 ${progress}%` : jobStatus === 'pending' ? '排队中' : jobStatus === 'failed' ? '执行失败' : (splitOnly ? '待切分' : '待对齐'));
  const done = jobStatus === 'succeeded';
  const running = jobStatus === 'running';
  // 生产时间轴只来自真实输入；没有真实时长时保持不可操作状态。
  const events = alignRes?.events ?? signals?.events ?? null;
  const timelineDur = signals?.duration ?? 0;
  useEffect(() => {
    const segment = signals?.events?.weld_segment;
    if (segment) { setEventStart(segment[0]); setEventEnd(segment[1]); }
    else { setEventStart(null); setEventEnd(null); }
  }, [signals?.events]);
  const splitStart = eventStart ?? events?.weld_segment[0] ?? 0;
  const splitEnd = eventEnd ?? events?.weld_segment[1] ?? 0;
  const previewSampleCount = splitPreviewLoading || splitPreviewError ? 0 : (splitPreview?.summary.sample_count ?? 0);
  const previewSamples: SplitPreviewSample[] = useMemo(() => (splitPreview?.windows ?? []).slice(0, 8).map((window) => ({ index: window.index, start: window.start, end: window.end })), [splitPreview]);
  const handleSplitPreview = () => {
    if (!dataId || versionId == null || signals?.source !== 'real' || eventStart == null || eventEnd == null) return;
    setSplitPreviewLoading(true); setSplitPreviewError(null);
    previewSplitTask(dataId, String(versionId), { fixed_rate: fixedRate, stride, keep_event_buffer: keepEventBuffer ? bufferSeconds : 0, task_format: taskFormat, event_start: eventStart, event_end: eventEnd })
      .then((value) => { setSplitPreview(value); setPreviewed(true); })
      .catch((error) => { setSplitPreview(null); setPreviewed(false); setSplitPreviewError(error instanceof Error ? error.message : '预览失败，请检查真实输入和事件边界'); })
      .finally(() => setSplitPreviewLoading(false));
  };
  const trackRows: { channel: string; label: string; tone: string; track?: AlignmentTrack; values?: number[]; lo?: number; hi?: number; color?: string }[] = (() => {
    const rows = (splitOnly || !alignRes)
      ? ['video', 'current', 'voltage', 'audio'].map((ch) => ({ channel: ch, label: ALIGN_TRACK_META[ch].label, tone: ALIGN_TRACK_META[ch].tone }))
      : alignRes.tracks.map((tr) => ({ channel: tr.channel, label: ALIGN_TRACK_META[tr.channel]?.label ?? tr.channel, tone: ALIGN_TRACK_META[tr.channel]?.tone ?? 'blue', track: tr }));
    return rows.map((row) => {
      const chanId = ALIGN_CHANNEL_MAP[row.channel];
      const chan = chanId ? signals?.channels.find((c) => c.id === chanId) : undefined;
      return { ...row, values: chan?.values, lo: chan?.lo, hi: chan?.hi, color: chanId ? chanColor[chanId] : undefined };
    });
  })();
  const errMsg = jobErrorMessage(job?.error);
  const pct = (s: number) => `${Math.min(100, Math.max(0, (s / (timelineDur || 1)) * 100)).toFixed(2)}%`;
  // 时间标尺刻度：对齐页 ruler 与切分页 cut-axis 共用同一时间轴
  const rulerTicks = useMemo(() => {
    const dur = Math.max(timelineDur, 1);
    const step = dur <= 6 ? 1 : dur <= 15 ? 2 : dur <= 30 ? 5 : 10;
    const ticks: number[] = [];
    for (let t = 0; t <= dur + 1e-9; t += step) ticks.push(t);
    if (ticks[ticks.length - 1] < dur) ticks.push(dur);
    return ticks;
  }, [timelineDur]);
  // 切分条带上的切割边界（每个样本起点，上限 400 防极端配置卡渲染）
  const cutTicks = useMemo(() => {
    const step = Math.max(1, stride) / (signals?.sample_rate ?? 1000);
    const ticks: number[] = [];
    for (let t = splitStart; t <= splitEnd + 1e-9 && ticks.length < 400; t += step) ticks.push(t);
    return ticks;
  }, [splitStart, splitEnd, stride, signals?.sample_rate]);
  const cutStartPct = (splitStart / (timelineDur || 1)) * 100;
  const cutEndPct = (splitEnd / (timelineDur || 1)) * 100;
  const modalOptions: { id: string; label: string; desc: string; icon: React.ReactNode }[] = [
    { id: 'video', label: '视频', desc: '熔池相机画面', icon: <ImageIcon size={14} /> },
    { id: 'timeseries', label: '时序', desc: '电流 / 电压 / 气体 / 送丝', icon: <Waves size={14} /> },
    { id: 'audio', label: '音频', desc: '弧声信号', icon: <AudioWaveform size={14} /> },
    { id: 'infrared', label: '红外', desc: '热成像', icon: <ScanLine size={14} /> },
  ];
  const downloadArtifact = (key: string) => {
    setArtifactError(null);
    getFileUrl(key, 86400).then((res) => window.open(res.url, '_blank', 'noopener,noreferrer')).catch((err) => setArtifactError(`产物打开失败：${err instanceof Error ? err.message : '请稍后重试'}`));
  };
  useEffect(() => {
    if (splitOnly || !dataId) return;
    const root = document.querySelector('.alignment-board');
    if (!root) return;
    const seek = (event: Event) => {
      const target = event.target as HTMLElement;
      const surface = target.closest('.studio-ruler, .lane-track:not(.lane-track-video)');
      if (!surface || timelineDur <= 0) return;
      const rect = surface.getBoundingClientRect();
      const next = Math.min(timelineDur, Math.max(0, ((event as MouseEvent).clientX - rect.left) / Math.max(1, rect.width) * timelineDur));
      setPlayhead(next);
      const video = root.querySelector('video') as HTMLVideoElement | null;
      if (video) video.currentTime = next;
    };
    const openArtifact = (event: Event) => {
      const row = (event.target as HTMLElement).closest('.artifact-row') as HTMLElement | null;
      const key = row?.dataset.objectKey ?? row?.querySelector('small')?.textContent?.trim();
      if (key) downloadArtifact(key);
    };
    const activateArtifact = (event: Event) => {
      const keyboardEvent = event as KeyboardEvent;
      if (keyboardEvent.key !== 'Enter' && keyboardEvent.key !== ' ') return;
      const row = (event.target as HTMLElement).closest('.artifact-row') as HTMLElement | null;
      if (!row) return;
      keyboardEvent.preventDefault();
      const key = row.dataset.objectKey ?? row.querySelector('small')?.textContent?.trim();
      if (key) downloadArtifact(key);
    };
    root.addEventListener('click', seek);
    root.addEventListener('click', openArtifact);
    root.addEventListener('keydown', activateArtifact);
    root.querySelectorAll('.studio-ruler, .lane-track:not(.lane-track-video)').forEach((el) => {
      el.setAttribute('tabindex', '0');
      el.setAttribute('role', 'slider');
      el.setAttribute('aria-label', '点击定位多模态时间轴');
    });
    root.querySelectorAll('.artifact-row').forEach((el) => {
      el.setAttribute('tabindex', '0');
      el.setAttribute('role', 'button');
      el.setAttribute('aria-label', '打开对齐产物');
    });
    return () => { root.removeEventListener('click', seek); root.removeEventListener('click', openArtifact); root.removeEventListener('keydown', activateArtifact); };
  }, [dataId, splitOnly, timelineDur, videoUrl, alignRes]);
  if (splitOnly) {
  return <div className="page-wrap"><PageIntro eyebrow="多模态数据生产线" title="样本分段" description="基于真实时序信号和系统检测事件，调整有效边界并生成可追溯的单流焊缝样本。" action={<Toolbar secondary="导出标注集" exportType="annotation" />} /><div className="split-steps"><span className="active">1 数据检查</span><i>→</i><span className={previewed ? 'active' : ''}>2 规则配置</span><i>→</i><span className={done ? 'active' : ''}>3 结果确认</span></div><div className="split-source-banner"><div><strong>{record?.weld_id ?? dataId ?? '正在读取焊缝…'}</strong><span>版本 v{versionId ?? '—'} · {record?.source ?? '数据来源读取中'}</span></div><div className="source-status"><span className={signals?.source === 'real' ? 'real' : 'generated'}>{signals?.source === 'real' ? '真实信号' : '真实输入不可用'}</span><span>{videoUrl ? '视频已加载' : '视频未加载'}</span><span>{signals ? `${signals.duration.toFixed(2)} 秒 · ${signals.sample_rate} Hz` : '信号加载中…'}</span></div></div><div className="alignment-layout"><section className="panel alignment-board">{signals?.source !== 'real' && <div className="alignment-banner warn" role="status"><AlertTriangle size={15} />当前版本没有可用于生产的真实时序信号或事件，暂不能分段。</div>}{jobStatus === 'failed' && <div className="alignment-banner bad" role="alert"><AlertTriangle size={15} />切分任务失败：{errMsg}</div>}<div className="board-toolbar"><div><span className="file-badge"><ScissorsIcon />切分输入{record ? ` · ${record.weld_id}` : ''}</span><h2>熔池视频 / 电流电压 / 音频</h2></div><StatusPill tone={tone as 'green' | 'orange' | 'red'}>{statusText}</StatusPill></div><div className="cut-wrap"><div className="cut-strip"><div className="cut-band"><div className="cut-seg" style={{ left: 0, width: `${cutStartPct}%` }} /><div className="cut-seg cut-effective" style={{ left: `${cutStartPct}%`, width: `${Math.max(0, cutEndPct - cutStartPct)}%` }} /><div className="cut-seg" style={{ left: `${cutEndPct}%`, width: `${Math.max(0, 100 - cutEndPct)}%` }} />{cutTicks.map((t) => <span key={t.toFixed(3)} className="cut-bound" style={{ left: pct(t) }} />)}{events && <i className="cut-evt cut-evt-arc" style={{ left: pct(events.arc) }} title="起弧" />}{events && <b className="cut-evt cut-evt-tail" style={{ left: pct(events.tail) }} title="收弧" />}</div><div className="cut-axis">{rulerTicks.map((t) => <span key={t} style={{ left: pct(t) }}>{fmt(t)}</span>)}</div></div><div className="cut-wave">{(() => { const row = trackRows.find((r) => r.channel === 'current'); return row?.values && row.values.length > 1 && row.lo != null && row.hi != null ? <svg viewBox="0 0 100 20" preserveAspectRatio="none"><path d={buildPath(row.values, row.lo, row.hi, 100, 20)} fill="none" stroke={row.color ?? '#2c9caf'} strokeWidth="1.1" vectorEffect="non-scaling-stroke" /></svg> : null; })()}{events && <i className="lane-marker" style={{ left: pct(events.arc) }} />}{events && <b className="lane-marker lane-marker-end" style={{ left: pct(events.tail) }} />}{playhead > 0 && <span className="lane-playhead" style={{ left: pct(playhead) }} />}</div></div><div className="cut-summary"><div><span>切分区间</span><strong>{fmt(splitStart)} – {fmt(splitEnd)}</strong><small>起收弧 ± 缓冲</small></div><div><span>样本长度</span><strong>{fixedRate} 帧</strong><small>≈ {fmt(fixedRate / (signals?.sample_rate ?? 1000))}</small></div><div><span>样本步长</span><strong>{stride} 帧</strong><small>重叠 {Math.max(0, fixedRate - stride)} 帧</small></div><div><span>预计样本</span><strong>{previewSampleCount.toLocaleString()}</strong><small>{taskFormat}</small></div></div><div className="split-action-row"><button className="full-button" onClick={() => { handleSplitPreview(); if (done) setJobId(null); }}>{previewed ? <><Check size={16} />已更新预览</> : <><ScissorsIcon />预览切分结果</>}</button>{previewed && <button className="full-button split-create-button" onClick={handleRun} disabled={running || !dataId || versionId == null}>{done ? <><Check size={16} />已创建 {splitRes?.sample_count ?? previewSampleCount} 个样本</> : running ? <><Activity size={16} />切分处理中 {progress}%</> : <><Play size={16} />确认并创建切分任务</>}</button>}</div></section><aside className="alignment-aside"><section className="panel"><div className="panel-heading"><div><h2>切分规则</h2><p>修改配置后先预览，再创建任务</p></div><SlidersHorizontal size={17} /></div><label className="switch-row"><span>按固定帧数切分</span><input type="checkbox" checked readOnly /></label><label className="split-field-label">每个样本</label><select className="split-control" value={fixedRate} onChange={(e) => { setFixedRate(Number(e.target.value)); setPreviewed(false); }}><option value={5}>5 帧 / 样本</option><option value={10}>10 帧 / 样本</option><option value={20}>20 帧 / 样本</option><option value={50}>50 帧 / 样本</option></select><label className="split-field-label">样本步长</label><select className="split-control" value={stride} onChange={(e) => { setStride(Number(e.target.value)); setPreviewed(false); }}><option value={5}>5 帧</option><option value={10}>10 帧</option><option value={20}>20 帧</option></select><div className="event-boundary-controls"><div className="event-boundary-heading"><strong>有效事件边界</strong><small>系统检测结果，可拖动修正；以真实持续时长为范围</small></div><label className="range-row"><span>开始 {eventStart == null ? "" : fmt(eventStart)}</span><input aria-label="有效事件开始时间" type="range" min={0} max={timelineDur} step={0.001} value={eventStart ?? 0} onChange={(e) => { const next = Number(e.target.value); setEventStart(Math.min(next, (eventEnd ?? timelineDur) - 0.001)); setPreviewed(false); }} disabled={!signals || timelineDur <= 0} /></label><label className="range-row"><span>结束 {eventEnd == null ? "" : fmt(eventEnd)}</span><input aria-label="有效事件结束时间" type="range" min={0} max={timelineDur} step={0.001} value={eventEnd ?? 0} onChange={(e) => { const next = Number(e.target.value); setEventEnd(Math.max(next, (eventStart ?? 0) + 0.001)); setPreviewed(false); }} disabled={!signals || timelineDur <= 0} /></label></div><label className="switch-row"><span>保留事件点前后缓冲</span><input type="checkbox" checked={keepEventBuffer} onChange={(e) => { setKeepEventBuffer(e.target.checked); setPreviewed(false); }} /></label><div className="select-field" style={{ gap: 8, justifyContent: 'space-between' }}><span>± {bufferSeconds.toFixed(2)} 秒</span><input aria-label="事件缓冲秒数" type="number" min={0} step={0.1} value={bufferSeconds} disabled={!keepEventBuffer} onChange={(e) => { const next = Number.parseFloat(e.target.value); setBufferSeconds(Number.isFinite(next) && next >= 0 ? next : 0); setPreviewed(false); }} style={{ width: 96, background: 'transparent', border: 'none', color: 'inherit', textAlign: 'right' }} /></div><div className="split-estimate"><strong>{previewSampleCount.toLocaleString()}</strong><span>预计样本</span><small>{fmt(splitStart)} – {fmt(splitEnd)} · {signals?.source === 'real' ? '真实信号' : '真实输入不可用'}</small></div></section><section className="panel"><div className="panel-heading"><div><h2>输出任务格式</h2><p>选择后会影响后续标注方式</p></div></div><div className="format-chips">{['目标检测', '时序分类'].map((format) => <button type="button" className={taskFormat === format ? 'chosen' : ''} key={format} onClick={() => { setTaskFormat(format); setPreviewed(false); }}>{format}</button>)}</div><div className="export-note"><FileText size={15} /><span>{taskFormat === '目标检测' ? '真实视频帧 + 缺陷框 JSON' : '真实时序信号 CSV + 窗口元数据'}</span></div></section></aside></div>{previewed && <section className="panel split-preview-panel"><div className="panel-heading"><div><h2>样本预览 <span className="inline-count">前 {Math.min(8, previewSampleCount)} 个</span></h2><p>点击样本可定位到对应时间窗口</p></div><span className="preview-summary">共 {previewSampleCount.toLocaleString()} 个 · {taskFormat}</span></div><div className="sample-preview-grid">{previewSamples.map((sample) => <button type="button" key={sample.index} className="sample-preview-card" onClick={() => setPlayhead(sample.start)}><SampleWaveThumb sample={sample} signals={signals} duration={timelineDur} /><strong>样本 {String(sample.index).padStart(3, '0')}</strong><small>{fmt(sample.start)} – {fmt(sample.end)}</small></button>)}</div></section>}</div>;
  }
  return <div className="page-wrap"><PageIntro eyebrow="多模态数据生产线" title="多模态对齐" description="将单条焊缝的视频、时序、音频与红外统一到同一时间轴，自动识别起收弧事件并生成对齐版本。" action={<Toolbar secondary="导出标注集" exportType="analysis" />} /><div className="split-source-banner"><div><strong>{record?.weld_id ?? dataId ?? '正在读取焊缝…'}</strong><span>版本 v{versionId ?? '—'} · {record?.source ?? '数据来源读取中'}</span></div><div className="source-status"><span className={signals?.source === 'real' ? 'real' : 'generated'}>{signals?.source === 'real' ? '真实信号' : '真实输入不可用'}</span><span>{videoUrl ? '视频已加载' : '视频未加载'}</span><span>{signals ? `${signals.duration.toFixed(2)} 秒 · ${signals.sample_rate} Hz` : '信号加载中…'}</span></div></div><div className="alignment-layout"><section className="panel alignment-board">{alignRes?.version && <div className="alignment-banner ok" role="status"><CheckCircle2 size={15} />已生成「时间对齐」版本 {alignRes.version.version_no}（{alignRes.version.object_keys.length} 个产物 · 事件来源 {alignRes.event_source === 'real' ? '真实信号' : '生成回退'}）</div>}{jobStatus === 'failed' && <div className="alignment-banner bad" role="alert"><AlertTriangle size={15} />对齐任务失败：{errMsg}</div>}<div className="studio-head"><div><span className="file-badge"><Waves size={15} />多模态时间轴</span><h2>熔池视频 / 电流电压 / 音频 / 红外</h2></div><StatusPill tone={tone as 'green' | 'orange' | 'red'}>{statusText}</StatusPill></div><div className="studio-ruler"><div className="ruler-tickbar">{rulerTicks.map((t) => <span key={t} style={{ left: pct(t) }}>{fmt(t)}</span>)}</div><div className="ruler-events">{events && <i className="ruler-arc" style={{ left: pct(events.arc) }} title="起弧" />}{events && <b className="ruler-tail" style={{ left: pct(events.tail) }} title="收弧" />}</div>{playhead > 0 && <span className="ruler-playhead" style={{ left: pct(playhead) }} />}</div>{trackRows.map((row) => { const isVideo = row.channel === 'video'; return <div className="lane" key={row.channel}><div className="lane-label"><span className="lane-dot" style={{ background: isVideo ? '#4fa9c2' : (row.color ?? '#2c9caf') }} />{row.label}{row.track && <AvailabilityTag track={row.track} />}</div><div className={`lane-track ${isVideo ? 'lane-track-video' : ''}`}>{isVideo ? (videoUrl ? <video className="studio-video" src={videoUrl} controls onTimeUpdate={(e) => setPlayhead(e.currentTarget.currentTime)} /> : <div className="lane-video-empty"><Play size={18} /><span>等待真实视频</span></div>) : (row.values && row.values.length > 1 && row.lo != null && row.hi != null && <svg className="lane-wave" viewBox="0 0 100 18" preserveAspectRatio="none"><path d={buildPath(row.values, row.lo, row.hi, 100, 18)} fill="none" stroke={row.color ?? '#2c9caf'} strokeWidth="1.1" vectorEffect="non-scaling-stroke" /></svg>)}{events && <i className="lane-marker" style={{ left: pct(events.arc) }} />}{events && <b className="lane-marker lane-marker-end" style={{ left: pct(events.tail) }} />}{playhead > 0 && <span className="lane-playhead" style={{ left: pct(playhead) }} />}</div></div>; })}<div className="studio-events"><span><i className="studio-evt arc" />起弧 <b>{events ? fmt(events.arc) : '—'}</b></span><span><i className="studio-evt seg" />有效焊接段 <b>{events ? `${fmt(events.weld_segment[0])} – ${fmt(events.weld_segment[1])}` : '—'}</b></span><span><i className="studio-evt tail" />收弧 <b>{events ? fmt(events.tail) : '—'}</b></span><span className="studio-dur">总时长 {fmt(timelineDur)}</span></div></section><aside className="alignment-aside"><section className="panel"><div className="panel-heading"><div><h2>对齐任务</h2><p>选择要纳入对齐的模态</p></div><Waves size={17} /></div><div className="modal-checklist">{modalOptions.map((m) => <label className="modal-check" key={m.id}><input type="checkbox" checked={modalities.includes(m.id)} onChange={(e) => { setModalities((prev) => (e.target.checked ? [...prev, m.id] : prev.filter((x) => x !== m.id))); }} /><span className="modal-check-box">{m.icon}</span><b>{m.label}</b><small>{m.desc}</small></label>)}</div><div className="split-estimate studio-estimate"><strong>{modalities.length}</strong><span>种模态纳入对齐</span><small>{signals?.source === 'real' ? '真实信号' : '真实输入不可用'} · 起收弧事件将自动识别</small></div><button className="full-button" onClick={handleRun} disabled={running || !dataId || versionId == null || modalities.length === 0}>{done ? <><Check size={16} />已完成对齐</> : running ? <><Activity size={16} />对齐处理中 {progress}%</> : <><Waves size={16} />开始多模态对齐</>}</button>{done && <button className="full-button studio-reset" onClick={() => setJobId(null)}><RefreshCw size={15} />重新对齐</button>}</section>{alignRes && <section className="panel"><div className="panel-heading"><div><h2>对齐产物</h2><p>写入「时间对齐」版本</p></div><FileText size={17} /></div><div className="artifact-list">{alignRes.assets.map((a, i) => <div className="artifact-row" key={`${a}-${i}`}><span className="artifact-icon">{a.toLowerCase().endsWith('.csv') ? <BarChart3 size={13} /> : a.toLowerCase().endsWith('.jpg') ? <ImageIcon size={13} /> : <FileText size={13} />}</span><div><strong>{a.split('/').pop()}</strong><small>{a}</small></div></div>)}</div></section>}</aside></div></div>;
}

function ScissorsIcon() { return <span className="scissors-icon">✂</span>; }

function ModelTestLive() {
  const [models, setModels] = useState<Model[]>([]);
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [modelVersionId, setModelVersionId] = useState<number | null>(null);
  const [datasetVersionId, setDatasetVersionId] = useState<number | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [testError, setTestError] = useState<string | null>(null);
  const { status, result } = useJob<TestResult>(jobId);
  useEffect(() => { Promise.all([listModels(), listDatasets()]).then(([modelRes, datasetRes]) => { setModels(modelRes.models); setDatasets(datasetRes); }).catch(() => {}); }, []);
  const run = () => { if (modelVersionId == null || datasetVersionId == null) return; setTestError(null); createTestTask({ model_version_id: modelVersionId, dataset_version_id: datasetVersionId, tasks: ['异常分类'] }).then((res) => setJobId(res.job_id)).catch((err) => setTestError(err instanceof Error ? err.message : '测试任务创建失败，请检查模型版本和独立测试快照后重试')); };
  const pct = (v: number | undefined) => v == null ? '—' : `${(v * 100).toFixed(1)}%`;
  const metrics = result?.metrics;
  return <div className="page-wrap"><PageIntro eyebrow="模型评估中心" title="模型测试" description="选择模型版本和测试数据集，执行一次可追踪的评估任务。" /><div className="model-test-layout"><section className="panel test-config"><div className="panel-heading"><div><h2>测试配置</h2><p>所有选项均来自模型资产和数据集版本</p></div><span className="draft-tag">{status === 'running' ? '执行中' : '待执行'}</span></div><div className="form-block"><label>模型版本</label><select className="native-select" value={modelVersionId ?? ''} onChange={(e) => setModelVersionId(e.target.value ? Number(e.target.value) : null)}><option value="">请选择模型版本</option>{models.flatMap((m) => m.latest_version_id != null ? [<option key={m.latest_version_id} value={m.latest_version_id}>{m.name} {m.version ?? ''}</option>] : [])}</select></div><div className="form-block"><label>独立测试集</label><select className="native-select" value={datasetVersionId ?? ''} onChange={(e) => setDatasetVersionId(e.target.value ? Number(e.target.value) : null)}><option value="">请选择数据集版本</option>{datasets.flatMap((d) => d.current_version_id != null ? [<option key={d.current_version_id} value={d.current_version_id}>{d.name} {d.version ?? ''}</option>] : [])}</select></div><button className="full-button" disabled={status === 'running' || modelVersionId == null || datasetVersionId == null} onClick={run}>{status === 'running' ? <><Activity size={16} />测试进行中…</> : <><Play size={16} />开始测试</>}</button>{testError && <p className="dataset-empty-state" role="alert">{testError}</p>}</section><section className="panel test-result"><div className="panel-heading"><div><h2>测试结果</h2><p>{jobId ? `测试任务 · ${jobId}` : '开始测试后，这里将展示真实评估结果'}</p></div><StatusPill tone={status === 'failed' ? 'red' : status === 'running' ? 'orange' : 'green'}>{status === 'succeeded' ? '已完成' : status === 'failed' ? '失败' : status === 'running' ? '运行中' : '未开始'}</StatusPill></div>{result && metrics ? <><div className="metric-row four"><div><span>准确率</span><strong>{pct(metrics.accuracy)}</strong></div><div><span>召回率</span><strong>{pct(metrics.recall)}</strong></div><div><span>F1 值</span><strong>{pct(metrics.f1)}</strong></div><div><span>推理时延</span><strong>{metrics.latency_ms}ms</strong></div></div><div className="confusion-matrix"><div className="matrix-title"><h3>混淆矩阵</h3><span>真实结果</span></div><div className="matrix">{result.confusion_matrix.flatMap((row, i) => row.map((value, j) => <b className={i === j ? 'matrix-good' : 'matrix-warn'} key={`${i}-${j}`}>{value}</b>))}</div></div></> : <div className="training-empty-state"><BarChart3 size={30} /><span>暂无测试结果</span></div>}</section></div></div>;
}


type FeatureTableRow = { name: string; cur: string; vol: string; gas: string; wir: string };
type VisionFeatureRow = { name: string; value: string; desc: string };
type AudioFeatureRow = { name: string; value: string };
type UnifiedFeatureRow = { group: string; dims: number; range: string; tone: string };
const TS_ROWS: [string, string][] = [
  ['mean', '均值'], ['variance', '方差'], ['peak', '峰值'], ['skewness', '偏度'],
  ['kurtosis', '峰度'], ['rms', 'RMS'], ['fft_dominant_freq', 'FFT 主频'], ['wavelet_energy', '小波能量'],
];
function mapTsRows(res: FeatureExtraction) {
  const ts = res.ts_features ?? {};
  return TS_ROWS.map(([key, name]) => {
    const cell = (ch: string) => {
      const v = ts[ch]?.[key];
      if (v == null) return '—';
      return key === 'fft_dominant_freq' ? `${v.toFixed(1)} Hz` : String(Number(v.toFixed(2)));
    };
    return { name, cur: cell('cur'), vol: cell('vol'), gas: cell('gas'), wir: cell('wir') };
  });
}
const VISION_ROWS: [string, string, string][] = [
  ['area', '熔池面积', 'px²'], ['perimeter', '熔池周长', 'px'], ['aspect_ratio', '长宽比', ''],
  ['circularity', '圆形度', ''], ['gray_mean', '灰度均值', ''], ['glcm_contrast', '纹理对比度', ''],
  ['glcm_energy', '纹理能量', ''], ['sobel_gradient', '边缘梯度', ''],
];
const VISION_DESC: Record<string, string> = {
  area: '分割掩膜像素统计', perimeter: '边缘轮廓长度', aspect_ratio: '外接矩形长/宽', circularity: '4πA/P²',
  gray_mean: '熔池区域平均灰度', glcm_contrast: 'GLCM 对比度', glcm_energy: 'GLCM 角二阶矩', sobel_gradient: 'Sobel 梯度均值',
};
function mapVisionRows(res: FeatureExtraction) {
  const v = res.vision_features ?? {};
  return VISION_ROWS.map(([key, name, unit]) => {
    const val = v[key];
    let text = '—';
    if (val != null) text = `${key === 'area' ? Math.round(val).toLocaleString() : String(Number(val.toFixed(2)))}${unit ? ` ${unit}` : ''}`;
    return { name, value: text, desc: VISION_DESC[key] ?? '' };
  });
}
const AUDIO_ROWS: [string, string][] = [
  ['band_energy_low', '频带能量 (0-1kHz)'], ['band_power_high', '频带功率 (1-5kHz)'], ['total_psd', '总功率谱密度'],
  ['spectral_centroid', '质心频率'], ['spectral_rolloff', '频谱滚降'], ['zero_crossing_rate', '过零率'],
];
function mapAudioRows(res: FeatureExtraction) {
  const a = res.audio_features ?? {};
  return AUDIO_ROWS.map(([key, name]) => {
    const val = a[key];
    let text = '—';
    if (val != null) {
      if (key === 'band_energy_low' || key === 'band_power_high') text = `${val.toFixed(1)} dB`;
      else if (key === 'spectral_centroid' || key === 'spectral_rolloff') text = `${(val / 1000).toFixed(2)} kHz`;
      else text = String(Number(val.toFixed(3)));
    }
    return { name, value: text };
  });
}
const unifiedPalette = ['#2c9caf', '#67cdb0', '#f0a34a', '#75add1', '#b89ac4', '#b89ac4', '#d4a05a'];
function mapUnifiedGroups(uv: FeatureExtraction['unified_vector'] | null | undefined) {
  return (uv?.groups ?? []).map((g, i) => ({ group: g.name, dims: g.dims, range: `[${g.range[0]}:${g.range[1]}]`, tone: unifiedPalette[i % unifiedPalette.length] }));
}

function FeatureExtraction({ embedded = false, dataId }: { embedded?: boolean; dataId?: string }) {
  const [normMethod, setNormMethod] = useState('Z-Score');
  const [exportFmt, setExportFmt] = useState('NPY');
  const [versionId, setVersionId] = useState<number | null>(null);
  const [extractionId, setExtractionId] = useState<number | null>(null);
  const [tsRows, setTsRows] = useState<FeatureTableRow[]>([]);
  const [visionRows, setVisionRows] = useState<VisionFeatureRow[]>([]);
  const [audioRows, setAudioRows] = useState<AudioFeatureRow[]>([]);
  const [unified, setUnified] = useState<UnifiedFeatureRow[]>([]);
  const [totalDims, setTotalDims] = useState(0);
  const [extracting, setExtracting] = useState(false);
  const [featureJobId, setFeatureJobId] = useState<string | null>(null);
  const [extractError, setExtractError] = useState<string | null>(null);
  const [modalityStatus, setModalityStatus] = useState<FeatureExtraction['modality_status'] | null>(null);
  const { status: featureJobStatus, result: featureJobResult, error: featureJobError } = useJob<{ extraction_id: number; status: string }>(featureJobId);
  useEffect(() => {
    if (!dataId) return;
    let cancelled = false;
    setFeatureJobId(null);
    setExtracting(false);
    setExtractionId(null); setModalityStatus(null); setTsRows([]); setVisionRows([]); setAudioRows([]); setUnified([]); setTotalDims(0);
    getWeld(dataId).then(async (r) => {
      if (cancelled) return;
      const resolved = r.latest_version_id ?? r.latest_version?.id ?? null;
      setVersionId(resolved);
      if (resolved == null) return;
      const latest = await getLatestFeatureExtraction(resolved);
      if (!cancelled && latest) {
        setExtractionId(latest.id); setTsRows(mapTsRows(latest)); setVisionRows(mapVisionRows(latest)); setAudioRows(mapAudioRows(latest));
        setModalityStatus(latest.modality_status ?? null);
        const mapped = mapUnifiedGroups(latest.unified_vector);
        setUnified(mapped); setTotalDims(latest.unified_vector?.total_dims ?? 0);
        setNormMethod(latest.normalization === 'L2' ? 'L2 范数' : latest.normalization);
      }
    }).catch((err) => { if (!cancelled) { setExtractError('无法加载当前数据或历史提取结果'); console.warn('[features] load failed', err); } });
    return () => { cancelled = true; };
  }, [dataId]);
  useEffect(() => {
    if (featureJobStatus === 'failed') {
      setExtracting(false);
      setExtractError(featureJobError instanceof Error ? featureJobError.message : '特征提取任务失败，请检查真实输入和模态文件后重试。');
      return;
    }
    if (featureJobStatus !== 'succeeded' || featureJobResult?.extraction_id == null) return;
    let cancelled = false;
    getFeatureExtraction(String(featureJobResult.extraction_id)).then((res) => {
      if (cancelled) return;
      setExtractionId(res.id);
      setTsRows(mapTsRows(res));
      setVisionRows(mapVisionRows(res));
      setAudioRows(mapAudioRows(res));
      setModalityStatus(res.modality_status ?? null);
      const mapped = mapUnifiedGroups(res.unified_vector);
      setUnified(mapped);
      setTotalDims(res.unified_vector?.total_dims ?? 0);
      setNormMethod(res.normalization === 'L2' ? 'L2 范数' : res.normalization);
      setExtracting(false);
    }).catch((err) => {
      if (!cancelled) {
        setExtracting(false);
        setExtractError(err instanceof Error ? err.message : '特征提取结果读取失败，请稍后重试。');
      }
    });
    return () => { cancelled = true; };
  }, [featureJobError, featureJobResult, featureJobStatus]);
  const handleExtract = () => {
    if (!dataId || versionId == null) { console.warn('[features] Version has not been resolved; please try again later'); return; }
    setExtracting(true);
    setExtractError(null);
    createFeatureExtractionTask({ weld_id: dataId, version_id: versionId, normalization: normMethod === 'L2 范数' ? 'L2' : normMethod, format: exportFmt })
      .then((res) => setFeatureJobId(res.job_id))
      .catch((err) => { setExtracting(false); setExtractError('特征提取任务创建失败，请检查数据版本和模态文件后重试。'); console.warn('[features] createFeatureExtractionTask failed', err); });
  };
  const modalityLabels: Record<string, string> = { timeseries: '时序', vision: '视觉', audio: '声音' };
  const modalityStatusLabels: Record<string, string> = { generated: '模拟', heuristic: '启发式', missing: '缺失' };
  const fallbackModalities = modalityStatus ? Object.entries(modalityStatus).filter(([, status]) => status !== 'real').map(([name, status]) => `${modalityLabels[name] ?? name}（${modalityStatusLabels[status] ?? status}）`) : [];
  const exportUnified = () => {
    if (extractionId == null) return;
    downloadFeatureExtraction(extractionId, exportFmt).then((res) => {
      if (res.url) window.open(res.url, '_blank', 'noopener,noreferrer');
    }).catch(() => setExtractError('统一特征向量导出失败，请稍后重试'));
  };
  return <div className={embedded ? 'embedded-page feature-extraction-page' : 'page-wrap'}><PageIntro eyebrow="多模态特征工程" title="特征提取" description="从真实输入提取可追溯特征；缺失模态不会被静默当作真实数据。" action={<Toolbar action={extracting ? '提取中…' : '执行提取'} secondary="导出特征集" onAction={handleExtract} exportType="features" exportRefIds={extractionId != null ? [extractionId] : undefined} actionDisabled={extracting || !dataId || versionId == null} />} />{extractError && <div className="alignment-banner bad" role="alert"><AlertTriangle size={15} />{extractError}</div>}{fallbackModalities.length > 0 && <div className="alignment-banner warn" role="status"><AlertTriangle size={15} />{fallbackModalities.join('、')}模态非真实输入，本次结果不可直接用于生产判定。</div>}
    <div className="feature-layout">
      <section className="panel feature-modality-panel">
        <div className="panel-heading"><div><h2>时序信号特征</h2><p>电流 / 电压 / 气体流量 / 送丝速度 · 统计 + 频域 + 时频</p></div><Waves size={17} className="accent-text" /></div>
        {extracting && <p className="dataset-empty-state" role="status">正在计算时序、视觉和声音特征…</p>}<div className="feature-table-wrap">
          <div className="feature-table">
            <div className="ft-row ft-head"><span>特征</span><span style={{ color: '#2c9caf' }}>电流</span><span style={{ color: '#67cdb0' }}>电压</span><span style={{ color: '#f0a34a' }}>气体</span><span style={{ color: '#75add1' }}>送丝</span></div>
            {tsRows.length ? tsRows.map((f) => <div className="ft-row" key={f.name}><span>{f.name}</span><span className="mono">{f.cur}</span><span className="mono">{f.vol}</span><span className="mono">{f.gas}</span><span className="mono">{f.wir}</span></div>) : <div className="feature-empty">执行提取后展示结果</div>}
          </div>
        </div>
        <div className="feature-tags"><span>统计特征</span><span>FFT 频域</span><span>小波时频</span><span>28 维 / 通道</span></div>
      </section>

      <section className="panel feature-modality-panel">
        <div className="panel-heading"><div><h2>熔池视觉特征</h2><p>从图片或视频关键帧提取几何与纹理特征</p></div><ImageIcon size={17} className="accent-text" /></div>
        <div className="vision-feature-grid">
          {visionRows.length ? visionRows.map((f) => <div className="vf-item" key={f.name}><div><strong>{f.name}</strong><small>{f.desc}</small></div><span className="mono">{f.value}</span></div>) : <div className="feature-empty">需要真实图片或视频输入</div>}
        </div>
        <div className="feature-tags"><span>几何特征</span><span>GLCM 纹理</span><span>Sobel 边缘</span><span>8 维</span></div>
      </section>

      <section className="panel feature-modality-panel">
        <div className="panel-heading"><div><h2>声音特征</h2><p>读取 WAV 后计算频带能量、功率谱密度与声学统计</p></div><AudioWaveform size={17} className="accent-text" /></div>
        <div className="audio-feature-list">
          {audioRows.length ? audioRows.map((f) => <div className="af-item" key={f.name}><Sigma size={13} /><span>{f.name}</span><strong className="mono">{f.value}</strong></div>) : <div className="feature-empty">需要真实 WAV 音频输入</div>}
        </div>
        <div className="feature-tags"><span>频带能量</span><span>PSD</span><span>声学统计</span><span>6 维</span></div>
      </section>

      <section className="panel feature-unified-panel">
        <div className="panel-heading"><div><h2>统一特征向量</h2><p>多模态特征拼接后输出，供后续融合层使用</p></div><Boxes size={17} className="accent-text" /></div>
        <div className="unified-summary"><div><span>总维度</span><strong>{totalDims} 维</strong></div><div><span>模态数</span><strong>3</strong></div><div><span>归一化</span><strong>{normMethod}</strong></div><div><span>输出格式</span><strong>.{exportFmt.toLowerCase()}</strong></div></div>
        <div className="unified-vector-bar">
          {unified.length ? unified.map((seg, i) => <div className="uv-seg" key={i} style={{ flexGrow: seg.dims, background: seg.tone }} title={`${seg.group} · ${seg.dims} 维`}><span>{seg.dims}</span></div>) : <div className="feature-empty">暂无统一向量</div>}
        </div>
        <div className="unified-legend">{unified.map((seg, i) => <span key={i}><i style={{ background: seg.tone }} />{seg.group}<small>{seg.range}</small></span>)}</div>
        <div className="unified-config">
          <div className="form-block"><label>归一化方式</label><div className="pp-chips">{['Z-Score', 'Min-Max', 'L2 范数', '无'].map((m) => <button key={m} className={normMethod === m ? 'on' : ''} onClick={() => setNormMethod(m)}>{m}</button>)}</div></div>
          <div className="form-block"><label>输出格式</label><div className="pp-chips">{['NPY', 'CSV', 'JSON', 'PT'].map((f) => <button key={f} className={exportFmt === f ? 'on' : ''} onClick={() => setExportFmt(f)}>{f}</button>)}</div></div>
        </div>
        <button className="full-button" disabled={extractionId == null || extracting} onClick={exportUnified}><Download size={15} />{extractionId == null ? '完成提取后可导出' : '导出统一特征向量'}</button>
      </section>

      <section className="panel feature-pipeline-panel">
        <div className="panel-heading"><div><h2>提取流水线</h2><p>从原始信号到融合向量的处理链路</p></div></div>
        <div className="feature-pipeline">
          <div className="fp-step"><Database size={15} /><span>原始多模态数据</span></div><i>↓</i>
          <div className="fp-step"><FilterIcon size={15} /><span>信号预处理 / 滤波</span></div><i>↓</i>
          <div className="fp-step"><Waves size={15} /><span>分模态特征提取</span></div><i>↓</i>
          <div className="fp-step"><Boxes size={15} /><span>特征拼接 · {totalDims} 维</span></div><i>↓</i>
          <div className="fp-step"><Check size={15} /><span>归一化 · 输出向量</span></div>
        </div>
        <div className="pipeline-note"><FileText size={14} /><span>{extractionId ? '结果已由后端计算并保存，可从当前数据版本追溯。' : '尚未执行提取。执行后才会展示真实计算结果，不使用演示数值。'}</span></div>
      </section>
    </div>
  </div>;
}
/** 训练/验证损失数组 → SVG polyline path（viewBox 0 0 600 250；min→底、max→顶）。 */
function lossToPath(values: number[], width = 600, height = 250): string {
  const len = values.length;
  if (len < 2) return '';
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const range = hi - lo || 1;
  const pts = values.map((v, i) => {
    const x = (i / (len - 1)) * width;
    const y = 10 + (1 - (v - lo) / range) * (height - 20);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  return `M${pts[0]} L${pts.slice(1).join(' L')}`;
}
function Training() {
  const [isTraining, setIsTraining] = useState(false);
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [datasetReadiness, setDatasetReadiness] = useState<Record<number, string>>({});
  const [selectedDatasetIds, setSelectedDatasetIds] = useState<number[]>([]);
  const [models, setModels] = useState<Model[]>([]);
  const [modelType, setModelType] = useState('');
  const [baseModelVersionId, setBaseModelVersionId] = useState<number | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [trainingError, setTrainingError] = useState<string | null>(null);
  const [logs, setLogs] = useState<string | null>(null);
  const { status: jobStatus, progress, result: trainRes } = useJob<TrainingResult>(jobId);
  useEffect(() => {
    if (jobStatus === 'succeeded' || jobStatus === 'failed') setIsTraining(false);
  }, [jobStatus]);
  // 训练超参（表单展示值即初始值；保持 JSX 不动，仅作为 createTrainingTask 数据源）。
  const [config] = useState({ epochs: 50, batch_size: 16, learning_rate: 0.001, val_ratio: 0.2 });
  useEffect(() => {
    let cancelled = false;
    listDatasets().then((list) => {
      if (cancelled) return;
      setDatasets(list);
      Promise.all(list.map(async (dataset) => {
        try {
          const result = await getReadiness(String(dataset.id));
          return [dataset.id, result.readiness] as const;
        } catch (err) {
          console.warn(`[training] readiness check failed for dataset ${dataset.id}`, err);
          return [dataset.id, '暂不可训练'] as const;
        }
      })).then((entries) => {
        if (!cancelled) setDatasetReadiness(Object.fromEntries(entries));
      });
    }).catch((err) => { if (!cancelled) console.warn('[training] listDatasets failed', err); });
    // 基础模型（best-effort）：生产候选版本优先，否则取首个有版本的模型，作为训练产出版本的挂靠。
    listModels().then((res) => {
      if (cancelled) return;
      setModels(res.models);
    }).catch((err) => { if (!cancelled) console.warn('[training] listModels failed', err); });
    return () => { cancelled = true; };
  }, []);
  const selectedDatasets = datasets.filter((dataset) => dataset.current_version_id != null && selectedDatasetIds.includes(dataset.current_version_id));
  const availableModels = models.filter((model) => !modelType || model.type === modelType);
  const handleStart = () => {
    if (!selectedDatasetIds.length || !modelType) { console.warn('[training] Select a model type and at least one dataset version'); return; }
    setTrainingError(null);
    createTrainingTask({
      dataset_version_ids: selectedDatasetIds,
      model_type: modelType,
      base_model_id: baseModelVersionId ?? undefined,
      epochs: config.epochs,
      batch_size: config.batch_size,
      learning_rate: config.learning_rate,
      val_ratio: config.val_ratio,
    })
      .then((res) => { setJobId(res.job_id); setIsTraining(true); })
      .catch((err) => { setTrainingError(err instanceof Error ? err.message : '训练任务创建失败，请检查数据集快照后重试'); console.warn('[training] createTrainingTask failed', err); });
  };
  const handleLogs = () => {
    if (!jobId) return;
    getTrainingLogs(jobId).then((text) => setLogs(text)).catch((err) => console.warn('[training] getTrainingLogs failed', err));
  };
  const pct = (v: number | undefined | null) => (v != null ? `${(v * 100).toFixed(1)}%` : null);
  const mAP = pct(trainRes?.metrics?.mAP50) ?? '—';
  const precision = pct(trainRes?.metrics?.precision) ?? '—';
  const recall = pct(trainRes?.metrics?.recall) ?? '—';
  const loss = trainRes?.loss_curve ?? null;
  const trainPath = loss && loss.train.length > 1 ? lossToPath(loss.train) : '';
  const valPath = loss && loss.val.length > 1 ? lossToPath(loss.val) : '';
  return <div className="page-wrap"><PageIntro eyebrow="模型工坊" title="模型训练" description="选择模型与数据集，创建可追踪的训练任务。" action={<button className={`primary-button ${isTraining ? 'training-button' : ''}`} onClick={() => { if (isTraining) { setIsTraining(false); setJobId(null); } else handleStart(); }}>{isTraining ? <Activity size={16} /> : <Play size={16} />}{isTraining ? '训练进行中' : '开始新训练'}</button>} /><div className="training-layout"><section className="panel config-panel"><div className="panel-heading"><div><h2>训练配置</h2><p>先选择要训练的模型，再选择一个或多个数据集版本</p></div><span className="draft-tag">{isTraining ? '执行中' : '草稿'}</span></div><div className="form-block"><label>模型类型</label><select className="native-select" value={modelType} onChange={(event) => { setModelType(event.target.value); setBaseModelVersionId(null); }}><option value="">请选择模型类型</option>{[...new Set(models.map((model) => model.type))].map((type) => <option key={type} value={type}>{type}</option>)}</select></div><div className="form-block"><label>基础模型 / 已训练模型（可选）</label><select className="native-select" value={baseModelVersionId ?? ''} onChange={(event) => setBaseModelVersionId(event.target.value ? Number(event.target.value) : null)} disabled={!modelType}><option value="">从零开始训练</option>{availableModels.flatMap((model) => model.latest_version_id ? [<option key={model.latest_version_id} value={model.latest_version_id}>{model.name} {model.version ?? ''} · {modelMetricText(model.metric)}</option>] : [])}</select></div><div className="form-block"><label>训练数据集（可多选）</label><div className="training-dataset-options">{datasets.length ? datasets.map((dataset) => { const versionId = dataset.current_version_id; const selected = versionId != null && selectedDatasetIds.includes(versionId); const readiness = datasetReadiness[dataset.id]; const hasTrainingVersion = versionId != null && dataset.sample_count > 0 && dataset.split != null && (dataset.split.train ?? 0) > 0; const statusText = hasTrainingVersion ? (readiness === '可训练' ? '可训练' : readiness ? `${readiness}（版本可用）` : '检查中…') : '暂无可用训练版本'; return <label className={`training-dataset-option ${selected ? 'selected' : ''}`} key={dataset.id}><input type="checkbox" disabled={!hasTrainingVersion} checked={selected} onChange={() => { if (!hasTrainingVersion || versionId == null) return; setSelectedDatasetIds((ids) => ids.includes(versionId) ? ids.filter((id) => id !== versionId) : [...ids, versionId]); }} /><span><strong>{dataset.name}</strong><small>{dataset.version ?? '暂无版本'} · {dataset.sample_count.toLocaleString()} 条样本 · {statusText}</small></span></label>; }) : <p className="dataset-empty-state">暂无可用数据集。</p>}</div>{selectedDatasets.length > 0 && <small className="form-help">已选择 {selectedDatasets.length} 个数据集版本，共 {selectedDatasets.reduce((sum, dataset) => sum + dataset.sample_count, 0).toLocaleString()} 条样本</small>}</div><div className="parameter-grid"><div className="form-block"><label>训练轮数 <CircleHelp size={13} /></label><input className="input-field" type="number" min="1" value={config.epochs} readOnly /></div><div className="form-block"><label>批次大小 <CircleHelp size={16} /></label><input className="input-field" type="number" min="1" value={config.batch_size} readOnly /></div><div className="form-block"><label>学习率</label><input className="input-field" value={config.learning_rate} readOnly /></div><div className="form-block"><label>验证集比例</label><input className="input-field" value={`${config.val_ratio * 100}%`} readOnly /></div></div><button className="full-button" disabled={isTraining || !modelType || !selectedDatasetIds.length} onClick={handleStart}>{isTraining ? <><Activity size={16} />训练任务运行中</> : <><Play size={16} />开始训练任务</>}</button>{trainingError && <p className="dataset-empty-state" role="alert">{trainingError}</p>}</section><section className="panel training-chart-panel"><div className="panel-heading"><div><h2>训练表现</h2><p>{jobId ? `任务 #${jobId} · 实时更新` : '开始训练后，这里将展示训练表现'}</p></div><span className={`run-status ${isTraining ? 'running' : ''}`}><i />{jobStatus === 'succeeded' ? '已完成' : jobStatus === 'failed' ? '失败' : isTraining ? `运行中 ${progress}%` : '未开始'}</span></div><div className="metric-row"><div><span>mAP@50</span><strong>{mAP}</strong></div><div><span>精确率</span><strong>{precision}</strong></div><div><span>召回率</span><strong>{recall}</strong></div></div>{loss ? <><div className="line-chart"><div className="chart-y"><span>1.0</span><span>0.8</span><span>0.6</span><span>0.4</span><span>0.2</span><span>0</span></div><svg viewBox="0 0 600 250" preserveAspectRatio="none" role="img" aria-label="训练指标曲线"><path d={trainPath} fill="none" stroke="#1d8fa5" strokeWidth="4" /><path d={valPath} fill="none" stroke="#f0a34a" strokeWidth="3" strokeDasharray="7 7" /></svg><div className="chart-x"><span>0</span><span>10</span><span>20</span><span>30</span><span>40</span><span>{config.epochs} epochs</span></div></div><div className="chart-key"><span><i className="legend-blue" />训练损失</span><span><i className="legend-orange" />验证损失</span></div></> : <div className="training-empty-state"><BarChart3 size={30} /><span>训练开始后显示指标和损失曲线</span></div>}</section></div><div className="training-note"><Terminal size={17} /><div><strong>训练日志</strong><p>{logs ?? (jobId ? '等待训练任务日志…' : '暂无训练日志')}</p></div><button className="ghost-button" disabled={!jobId} onClick={handleLogs}>查看完整日志 <ArrowUpRight size={14} /></button></div></div>;
}
export default App;
