import { useEffect, useRef, useState } from 'react';
import type { ChangeEvent } from 'react';
import {
  Activity, AlertTriangle, ArrowUpRight, BarChart3, Box, Check, CheckCircle2,
  CircleHelp, Cpu, Database, Download, GitBranch, MoreHorizontal, Play, Plus,
  ScanLine, SlidersHorizontal, Target, Terminal, Upload,
} from 'lucide-react';
import {
  createBuildTask, createDatasetVersion, getDatasetVersion, getReadiness, listDatasets,
} from '../../api/datasets';
import { presignUpload, uploadFile } from '../../api/files';
import {
  createInferenceTask, createTestTask, createTrainingTask, exportModelVersion,
  getModel, getTrainingLogs, listModels, updateModelVersionStatus,
} from '../../api/models';
import type {
  Dataset, DatasetQuality, DatasetSplit, InferenceResult, Model, ModelSummary,
  ModelVersion, TestResult, TrainingResult,
} from '../../api/types';
import { useJob } from '../../hooks/useJob';
import type { Route } from '../../app/navigation';
import { PageIntro } from '../../shared/components/PageIntro';
import { StatusPill } from '../../shared/components/StatusPill';
import { Toolbar } from '../../shared/components/Toolbar';
import { formatDateTime } from '../../shared/lib/formatting';

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
  { name: '时序数据缺陷检测模型', type: '时序分类', description: '基于电流、电压和送丝时序信号，识别焊接过程缺陷与异常。', icon: Activity },
  { name: '目标检测模型', type: '目标检测', description: '从焊缝图像中检测气孔、焊瘤等缺陷目标，输出位置与类别。', icon: Target },
  { name: '熔池分割模型', type: '语义分割', description: '从视频帧中提取熔池区域，服务于熔池形态分析。', icon: ScanLine },
];
export function ModelRepository({ refreshKey = 0, navigate }: { refreshKey?: number; navigate: (route: Route) => void }) {
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

export function InferencePanel() {
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
  const handleFile = (event: ChangeEvent<HTMLInputElement>) => {
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

export function DatasetBuild() {
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
  return <div className="page-wrap"><PageIntro eyebrow="模型研发中心" title="训练数据准备" description="基于数据管理的数据集，筛选可用于模型训练的样本并生成固定版本。" action={<Toolbar secondary="导出报告" />} /><div className="build-steps" aria-label="训练数据准备流程"><span className="current"><b>1</b>选择数据集</span><i /> <span><b>2</b>设定样本范围</span><i /> <span><b>3</b>生成训练数据集</span></div><div className="build-layout"><section className="panel build-config"><div className="panel-heading"><div><h2>准备条件</h2><p>配置完成后生成一份新的训练数据版本</p></div><Box size={17} /></div>{loading ? <p className="dataset-empty-state" role="status">正在读取数据管理的数据集…</p> : <><div className="form-block"><label className="form-label">1. 选择数据集</label><p className="form-help build-form-intro">选择数据管理中已有的数据集，准备动作不会修改原始数据。</p><select className="native-select" value={datasetId ?? ''} onChange={(e) => setDatasetId(e.target.value ? Number(e.target.value) : null)}><option value="">请选择数据集</option>{datasets.map((d) => <option key={d.id} value={d.id}>{d.name} · {d.version ?? '未建版本'}</option>)}</select></div><div className="form-block"><label className="form-label">2. 选择样本范围</label><div className="build-source">{(['manual', 'split_task', 'annotation_task'] as const).map((key) => <label className={source === key ? 'chosen' : ''} key={key}><input type="radio" name="build-source" checked={source === key} onChange={() => setSource(key)} /><span><strong>{sourceMeta[key].label}</strong><small>{sourceMeta[key].desc}</small></span>{source === key && <Check size={15} />}</label>)}</div></div></>}<div className="split-ratio-note"><div className="rule-title"><GitBranch size={15} />自动划分规则</div><b>训练 80% <em>/</em> 验证 10% <em>/</em> 测试 10%</b><small>按焊缝 ID 分组，同一焊缝不会同时进入训练集和测试集，避免数据泄漏。</small></div><button className="full-button" onClick={handleBuild} disabled={datasetId == null || buildJobId != null}>{buildJobId != null ? <><Activity size={16} />正在生成 · {progress}%</> : <><GitBranch size={16} />生成训练数据集</>}</button>{buildError && <p className="dataset-empty-state" role="alert">生成失败：{buildError} 请检查样本范围后重试。</p>}</section><section className="panel build-result"><div className="panel-heading"><div><h2>生成结果</h2><p>{buildJobId != null ? '正在生成训练数据版本…' : buildResult ? '最近一次生成结果' : '完成左侧配置后，这里会显示数据划分结果'}</p></div><StatusPill tone={buildStatus === 'failed' ? 'red' : buildStatus === 'running' ? 'orange' : buildResult ? 'green' : 'muted'}>{buildStatus === 'succeeded' ? '已生成' : buildStatus === 'failed' ? '生成失败' : buildStatus === 'running' ? '生成中' : '未开始'}</StatusPill></div>{buildResult && split ? <><div className="result-context"><CheckCircle2 size={16} /><span>训练数据集已生成，可在“新建训练”中使用</span></div><div className="build-splitbar"><i className="train" style={{ width: slicePct(split.train) }} /><i className="val" style={{ width: slicePct(split.val) }} /><i className="test" style={{ width: slicePct(split.test) }} /></div><div className="build-split-legend"><span><i className="train" />训练集 <b>{split.train ?? 0}</b></span><span><i className="val" />验证集 <b>{split.val ?? 0}</b></span><span><i className="test" />测试集 <b>{split.test ?? 0}</b></span></div><div className="build-stat-row"><div><span>样本总数</span><strong>{buildResult.item_count.toLocaleString()}</strong></div><div><span>质量评分</span><strong>{qualityPct ?? '—'}</strong></div><div><span>版本快照</span><strong>{buildResult.snapshot_id ? buildResult.snapshot_id.slice(0, 8) : '—'}</strong></div></div></> : <div className="build-state"><div className="empty-steps"><span><Database size={17} />选择数据集</span><span><SlidersHorizontal size={17} />选择样本范围</span><span><GitBranch size={17} />生成版本</span></div><strong>{buildJobId != null ? '正在生成训练数据版本' : '还没有训练数据版本'}</strong><p>{buildJobId != null ? `系统正在按焊缝分组生成，当前进度 ${progress}%` : '配置左侧两项条件后，点击“生成训练数据集”即可开始。'}</p></div>}</section></div></div>;
}

// 保留旧名称以兼容外部链接；当前路由使用 TrainingDataPreparation。
void DatasetBuild;

export function TrainingDataPreparation() {
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
    <PageIntro eyebrow="模型研发中心" title="生成训练数据版本" description="从数据管理选择一个已有数据集，筛选样本并生成供模型训练使用的固定版本。" action={<Toolbar secondary="导出报告" />} />
    <div className="build-steps" aria-label="训练数据准备流程"><span className="current"><b>1</b>选择输入数据集</span><i /><span><b>2</b>筛选样本范围</span><i /><span><b>3</b>生成训练版本</span></div>
    <div className="build-layout">
      <section className="panel build-config"><div className="panel-heading"><div><h2>生成条件</h2><p>创建一份新的固定训练数据版本</p></div><Box size={17} /></div>
        {loading ? <p className="dataset-empty-state" role="status">正在读取数据管理的数据集…</p> : datasets.length === 0 ? <div className="build-no-dataset"><Database size={22} /><strong>暂无可用输入数据集</strong><p>请先在数据管理创建数据集并生成版本。</p></div> : <>
          <div className="form-block"><label className="form-label">1. 输入数据集</label><p className="form-help build-form-intro">来源于数据管理，不会修改原始数据。</p><select className="native-select" value={datasetId ?? ''} onChange={(e) => { setDatasetId(e.target.value ? Number(e.target.value) : null); setCompletedBuildResult(null); setBuildError(null); }}><option value="">请选择输入数据集</option>{datasets.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.version ?? '未生成版本'}</option>)}</select>{dataset && <div className="selected-dataset-card"><div className="selected-dataset-head"><span className="dataset-row-icon"><Box size={16} /></span><div><strong>{dataset.name}</strong><small>{dataset.dataset_no} · 当前版本 {dataset.version ?? '未生成'}</small></div><StatusPill tone={dataset.status === '可训练' ? 'green' : 'orange'}>{dataset.status}</StatusPill></div><div className="selected-dataset-meta"><span>样本数 <b>{dataset.sample_count.toLocaleString()}</b></span><span>标注完成度 <b>{dataset.progress != null ? `${dataset.progress}%` : '—'}</b></span></div></div>}</div>
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

export function ModelTestLive() {
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
export function Training() {
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
