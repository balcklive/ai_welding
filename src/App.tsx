import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Activity, Archive, ArrowUpRight, BarChart3, Box, Check, ChevronDown,
  CircleHelp, Database, Factory, FileCheck2, Filter, Gauge, Layers3,
  MoreHorizontal, Play, Plus, Minus, Search, Settings2, SlidersHorizontal, Sparkles,
  Tag, Terminal, TrainFront, Upload, WandSparkles, Waves, Zap,
  ClipboardCheck, FileText, GitBranch, ScanLine, Download, CheckCircle2,
  AlertTriangle, RefreshCw, ChevronLeft, Cpu,
  Filter as FilterIcon, Sigma, Image as ImageIcon, AudioWaveform, Boxes,
} from 'lucide-react';
import * as echarts from 'echarts';
import ImageAnnotate from 'react-image-annotate';
import { getToken } from './api/client';
import { getDashboardData } from './api/dashboard';
import type { DashboardData } from './api/dashboard';
import {
  attachRawFiles,
  createVersion,
  createRegistration,
  getValidation,
  getVersion,
  getWeld,
  listVersions,
  listWelds,
  runValidation,
} from './api/welds';
import {
  createBuildTask,
  createDataset,
  createDatasetVersion,
  getDataset,
  getDatasetVersion,
  getDimensions,
  getLineage,
  getReadiness,
  listDatasetVersions,
  listDatasetVersionItems,
  listDatasets,
} from './api/datasets';
import {
  aiPretag,
  createAlignmentTask,
  getLatestAlignmentTask,
  createAnnotationFrame,
  createAnnotationTask,
  createSplitTask,
  createFeatureExtractionTask,
  getFeatureExtraction,
  downloadFeatureExtraction,
  getLatestFeatureExtraction,
  getAnalysisMode,
  getAnalysisResult,
  getAnnotationSample,
  getSignals,
  previewSplitTask,
  importAnnotationSamples,
  listAnnotationSamples,
  listLabelCategories,
  saveAnnotation,
} from './api/analysis';
import { getFileUrl, presignUpload, putFileDirect, uploadFile } from './api/files';
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
import { exportReport } from './api/reports';
import { useJob } from './hooks/useJob';
import type {
  AlignmentResult,
  AlignmentTrack,
  AnalysisResult,
  Annotation as AnnotationLabel,
  DataRecord,
  Dataset,
  DatasetItemRow,
  DatasetQuality,
  DatasetSplit,
  DatasetVersion,
  DataVersion,
  DimensionStatus,
  DwtData,
  FeatureExtraction,
  InferenceResult,
  LabelCategory,
  LabelItem,
  LineageNode,
  Model,
  ModelSummary,
  ModelVersion,
  PddData,
  PhaseData,
  Project,
  PsdData,
  ReadinessCheck,
  RegistrationForm,
  Sample,
  SignalChannel,
  SignalData,
  SignalQuery,
  SplitResult,
  StftData,
  TestResult,
  TrainingResult,
  ValidationReport,
  ValidationRuleResult,
  WaveletBand,
  WaveletData,
} from './api/types';
import Login from './pages/Login';

type Route = 'overview' | 'data-center/datasets' | 'data-center/registration' | 'data-center/validation' | 'data-center/versions' | 'analysis/select' | 'analysis/alignment' | 'analysis/analysis' | 'analysis/split' | 'analysis/annotation' | 'analysis/features' | 'model-center/dataset-build' | 'model-center/repository' | 'model-center/training' | 'model-center/testing' | 'model-center/inference';

const workspaceHeaders: Record<string, { eyebrow: string; title: string; description: string }> = {
  'data-center': { eyebrow: '数据资产中心', title: '数据中心', description: '以单条焊缝数据为单位，管理数据上传、质量核验和版本链路。' },
  'analysis': { eyebrow: '多模态数据生产线', title: '分析与标注', description: '选择一条焊缝后，完成对齐、信号分析、切分与标注。' },
  'model-center': { eyebrow: '模型研发中心', title: '模型中心', description: '从数据到模型：准备训练数据，统一管理模型版本、训练任务、测试评估与推理验证。' },
};

const navStructure: { id: string; label: string; icon: typeof BarChart3; route?: Route; children?: { route: Route; label: string }[] }[] = [
  { id: 'overview', label: '数据总览', icon: BarChart3, route: 'overview' },
  { id: 'data-center', label: '数据中心', icon: Database, route: 'data-center/datasets', children: [
    { route: 'data-center/datasets', label: '数据集' },
    { route: 'data-center/registration', label: '数据上传' },
    { route: 'data-center/validation', label: '数据核验' },
    { route: 'data-center/versions', label: '焊缝版本' },
  ] },
  { id: 'analysis', label: '分析与标注', icon: Waves, children: [
    { route: 'analysis/select', label: '选择数据' },
    { route: 'analysis/alignment', label: '多模态对齐' },
    { route: 'analysis/analysis', label: '信号分析' },
    { route: 'analysis/split', label: '样本分段' },
    { route: 'analysis/annotation', label: '数据标注' },
    { route: 'analysis/features', label: '特征提取' },
  ] },
  { id: 'model-center', label: '模型中心', icon: TrainFront, children: [
    { route: 'model-center/dataset-build', label: '训练数据准备' },
    { route: 'model-center/repository', label: '模型资产' },
    { route: 'model-center/training', label: '新建训练' },
    { route: 'model-center/testing', label: '测试评估' },
    { route: 'model-center/inference', label: '推理验证' },
  ] },
];

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
      {route === 'overview' && <Overview navigate={navigate} />}
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
  const toolbarConfig = ws === 'data-center' ? { action: route === 'data-center/datasets' && isDatasetDetail ? '上传数据' : undefined, secondary: undefined }
    : route === 'analysis/annotation' ? { action: '保存标注', secondary: '导出结果' }
    : ws === 'analysis' ? { action: '开始处理', secondary: '导出结果' }
    : route === 'model-center/training' ? { action: '开始训练', secondary: '导出报告' }
    : route === 'model-center/dataset-build' ? { action: undefined, secondary: '导出报告' }
    : { action: '新建模型', secondary: '导出报告' };
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
  else if (route === 'data-center/registration') content = <Registration />;
  else if (route === 'data-center/validation') content = selectedDataId ? <Validation embedded dataId={selectedDataId!} /> : <SelectionRequired onBack={() => navigate('data-center/datasets')} />;
  else if (route === 'data-center/versions') content = selectedDataId ? <VersionPanel dataId={selectedDataId!} /> : <SelectionRequired onBack={() => navigate('data-center/datasets')} />;
  else if (route === 'analysis/select') content = <AnalysisSelect selectedDatasetId={selectedDatasetId} setSelectedDatasetId={setSelectedDatasetId} onContinue={(id: string) => { setSelectedDataId(id); navigate('analysis/alignment'); }} />;
  else if (route === 'analysis/alignment') content = selectedDatasetId != null && selectedDataId ? <Alignment embedded dataId={selectedDataId} /> : <SelectionRequired onBack={() => navigate('analysis/select')} />;
  else if (route === 'analysis/analysis') content = selectedDatasetId != null && selectedDataId ? <AdvancedWeldAnalysis embedded dataId={selectedDataId} /> : <SelectionRequired onBack={() => navigate('analysis/select')} />;
  else if (route === 'analysis/split') content = selectedDatasetId != null && selectedDataId ? <Alignment embedded splitOnly dataId={selectedDataId} /> : <SelectionRequired onBack={() => navigate('analysis/select')} />;
  else if (route === 'analysis/annotation') content = selectedDatasetId != null && selectedDataId ? <Annotation embedded dataId={selectedDataId} /> : <SelectionRequired onBack={() => navigate('analysis/select')} />;
  else if (route === 'analysis/features') content = selectedDatasetId != null && selectedDataId ? <FeatureExtraction embedded dataId={selectedDataId} /> : <SelectionRequired onBack={() => navigate('analysis/select')} />;
  else if (route === 'model-center/dataset-build') content = <TrainingDataPreparation />;
  else if (route === 'model-center/repository') content = <ModelRepository refreshKey={repoRefresh} navigate={navigate} />;
  else if (route === 'model-center/training') content = <><DatasetTrainingContext /><Training /></>;
  else if (route === 'model-center/testing') content = <><DatasetTestingContext /><ModelTestLive /></>;
  else if (route === 'model-center/inference') content = <InferencePanel />;

  return <div className="workspace-page"><div className="workspace-page-head"><div><div className="eyebrow"><span />{header.eyebrow}</div><h1>{header.title}</h1><p>{header.description}</p></div><Toolbar action={toolbarConfig.action} secondary={toolbarConfig.secondary} exportType={exportType} onAction={ws === 'data-center' ? () => navigate('data-center/registration') : route === 'model-center/repository' ? handleRepoCreate : undefined} /></div>{showDataSwitcher && <SelectionSwitcher selectedDatasetId={selectedDatasetId} setSelectedDatasetId={setSelectedDatasetId} selectedDataId={selectedDataId} setSelectedDataId={setSelectedDataId} showContext={Boolean(showContext)} onChange={ws === 'data-center' ? () => navigate('data-center/datasets') : undefined} />}{content}</div>;
}

function PageIntro({ eyebrow, title, description, action }: { eyebrow: string; title: string; description: string; action?: React.ReactNode }) { return <div className="page-intro"><div><div className="eyebrow"><span />{eyebrow}</div><h1>{title}</h1><p>{description}</p></div>{action}</div>; }
// ── 总览/数据列表 API 接线辅助（Task 21） ─────────────────────────────
/** 分布/缺陷统一色调板（API 不输出颜色，按数据顺序取色）。 */
const donutPalette = ['#2c9caf', '#5fb8a6', '#f0a34a', '#e88d6c', '#7ba7c4', '#b0c4b8'];
/**
 * 把后端返回的原始记录数归一化为百分比（和恒为 100，DonutChart 中心/图例带 %）。
 * 用最大余数法分配取整误差，避免 round 后总和漂移（如 33/33/33=99）。
 */
function toDonut(items: { name: string; value: number }[]): { name: string; value: number; tone: string }[] {
  const total = items.reduce((sum, item) => sum + item.value, 0) || 1;
  const floored = items.map((item) => Math.floor((item.value / total) * 100));
  let remainder = 100 - floored.reduce((sum, v) => sum + v, 0);
  const byFraction = items
    .map((item, i) => ({ i, frac: (item.value / total) * 100 - Math.floor((item.value / total) * 100) }))
    .sort((a, b) => b.frac - a.frac);
  for (let k = 0; k < byFraction.length && remainder > 0; k += 1, remainder -= 1) {
    floored[byFraction[k].i] += 1;
  }
  return items.map((item, index) => ({
    ...item,
    value: floored[index],
    tone: donutPalette[index % donutPalette.length],
  }));
}

/** 多模态 token → 中文 label + icon + desc（契约 §3.2 modalities 原始 token）。 */
const modalityMeta: Record<string, { name: string; icon: typeof Waves; desc: string }> = {
  video: { name: '视频数据', icon: Activity, desc: '熔池/焊缝视频' },
  timeseries: { name: '时序数据', icon: Waves, desc: '电流/电压波形' },
  image: { name: '图像数据', icon: BarChart3, desc: '焊缝视觉照片' },
  audio: { name: '音频数据', icon: Activity, desc: '焊接声纹信号' },
  sound: { name: '音频数据', icon: Activity, desc: '焊接声纹信号' },
  infrared: { name: '红外热像', icon: Gauge, desc: '温度场分布' },
};

/** 采集频率档位字符串（如 "10 kHz"）→ 数值。 */
function parseFreq(tier: string): number {
  const m = /^[\d.]+/.exec(tier);
  return m ? parseFloat(m[0]) : 0;
}

/** 数据项目卡片展示形状（progress 已字符串化为 "68%"）。 */
interface ProjectCard {
  name: string;
  count: string;
  status: string;
  tone: string;
  progress: string;
  updatedAt: string | null;
}
const projectTone = (status: string): string => {
  if (status === '标注中') return 'blue';
  if (status === '可训练' || status === '已完成') return 'green';
  return 'orange';
};
function mapProject(p: Project): ProjectCard {
  return {
    name: p.name,
    count: p.sample_count.toLocaleString(),
    status: p.status,
    tone: projectTone(p.status),
    progress: `${p.progress}%`,
    updatedAt: p.updated_at,
  };
}

/** 数据列表行展示形状（table 期望的字段）。 */
interface WeldRow {
  id: string;
  time: string;
  source: string;
  machine: string;
  types: string;
  quality: string;
  version: string;
}
function toWeldRow(r: DataRecord): WeldRow {
  return {
    id: r.weld_id,
    time: r.collected_at ?? r.created_at ?? '—',
    source: r.source,
    machine: r.machine ?? '—',
    types: (r.modalities ?? []).join(' / ') || '—',
    quality: r.quality,
    version: r.latest_version?.version_no ?? '—',
  };
}

function Overview({ navigate }: { navigate: (route: Route) => void }) {
  const [activeProject] = useState(0);
  const [dashboard, setDashboard] = useState<DashboardData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getDashboardData()
      .then((data) => { if (!cancelled) setDashboard(data); })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : '数据总览接口请求失败');
      });
    return () => { cancelled = true; };
  }, []);

  if (!dashboard) {
    return <div className="page-wrap"><PageIntro eyebrow="数据资产中心" title="数据总览" description="全面掌握焊接数据资产的规模、来源与质量分布。" /><section className="panel"><p>{error ? `数据加载失败：${error}` : '正在加载数据总览…'}</p></section></div>;
  }

  const { stats, attributes: attrs, distributions: dist, projects: apiProjects } = dashboard;
  const projects = apiProjects.map(mapProject);
  const filteredProjects = projects;
  const displayedDatasets = filteredProjects.slice(0, 6);
  const freqValues = attrs.sample_rate_tiers.map(parseFreq).filter((n) => n > 0);
  const freqMin = freqValues.length ? Math.min(...freqValues) : null;
  const freqMax = freqValues.length ? Math.max(...freqValues) : null;
  const maxDefectCount = Math.max(1, ...dist.defects.map((d) => d.count));

  return <div className="page-wrap"><PageIntro eyebrow="数据资产中心" title="数据总览" description="全面掌握焊接数据资产的规模、来源与质量分布。" />
    <div className="stat-grid"><StatCard icon={Database} label="数据总量" value={stats.data_total.toLocaleString()} sub="条焊缝数据" /><StatCard icon={Factory} label="厂商总量" value={String(stats.manufacturer_total)} sub="家合作厂商" /><StatCard icon={Box} label="单条焊缝最大容量" value={`${(stats.max_storage_bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`} sub={`含缺陷样本 ${stats.annotated_samples.toLocaleString()} 条`} /><StatCard icon={FileCheck2} label="已标注样本" value={stats.annotated_samples.toLocaleString()} sub={`完成度 ${stats.annotation_completion}%`} /></div>

    <div className="attr-grid">
      <section className="panel attr-panel"><div className="attr-head"><Factory size={16} /><h2>焊机种类</h2><span className="attr-count">{attrs.weld_methods.length} 种</span></div><div className="attr-tags">{attrs.weld_methods.map((machine) => <span className="attr-tag" key={machine}>{machine}</span>)}</div></section>
      <section className="panel attr-panel"><div className="attr-head"><WandSparkles size={16} /><h2>缺陷种类</h2><span className="attr-count">{attrs.defect_types.length} 种</span></div><div className="attr-tags">{attrs.defect_types.map((defect, index) => <span className="attr-tag attr-tag-defect" key={defect.name}><i style={{ background: donutPalette[index % donutPalette.length] }} />{defect.name}</span>)}</div></section>
      <section className="panel attr-panel"><div className="attr-head"><Layers3 size={16} /><h2>多模态种类</h2><span className="attr-count">{attrs.modalities.length} 种</span></div><div className="modality-list">{attrs.modalities.map((token) => { const m = modalityMeta[token] ?? { name: token, icon: Boxes, desc: '多模态数据' }; const Icon = m.icon; return <div className="modality-item" key={token}><Icon size={15} /><div><strong>{m.name}</strong><span>{m.desc}</span></div></div>; })}</div></section>
      <section className="panel attr-panel"><div className="attr-head"><Gauge size={16} /><h2>时序数据采集频率</h2></div><div className="freq-display"><div className="freq-item"><span>最低频率</span><strong>{freqMin === null ? '—' : `${freqMin} kHz`}</strong></div><div className="freq-bar"><div className="freq-fill" /><div className="freq-dot" /><div className="freq-dot freq-dot-max" /></div><div className="freq-item"><span>最高频率</span><strong>{freqMax === null ? '—' : `${freqMax} kHz`}</strong></div></div><p className="freq-note">覆盖 {attrs.sample_rate_tiers.length} 个采样档位，支持多速率同步采集</p></section>
    </div>

    <div className="chart-row">
      <section className="panel donut-panel"><div className="panel-heading"><div><h2>厂商数据比重</h2><p>各厂商焊接数据占比分布</p></div></div><DonutChart data={toDonut(dist.manufacturers)} /></section>
      <section className="panel donut-panel"><div className="panel-heading"><div><h2>过渡类型比重</h2><p>熔滴过渡方式分布</p></div></div><DonutChart data={toDonut(dist.transition_types)} /></section>
      <section className="panel donut-panel"><div className="panel-heading"><div><h2>焊接类型比例</h2><p>不同焊接工艺占比</p></div></div><DonutChart data={toDonut(dist.welding_types)} /></section>
    </div>

    <div className="chart-row-two">
      <section className="panel defect-panel"><div className="panel-heading"><div><h2>缺陷类型分布</h2><p>各类缺陷样本数量统计</p></div></div><div className="defect-chart">{dist.defects.map((defect, index) => <div className="defect-bar-row" key={defect.name}><span className="defect-label">{defect.name}</span><div className="defect-bar-track"><span style={{ width: `${(defect.count / maxDefectCount) * 100}%`, background: donutPalette[index % donutPalette.length] }} /></div><span className="defect-count">{defect.count.toLocaleString()}</span></div>)}</div></section>
      <section className="panel wordcloud-panel"><div className="panel-heading"><div><h2>焊接厂商词云</h2><p>按数据量大小排列厂商名称</p></div></div><div className="wordcloud">{dist.wordcloud.map((word, index) => <span className="wordcloud-item" style={{ fontSize: `${word.size}px`, opacity: 0.45 + word.size / 50, color: index < 3 ? '#2c9caf' : index < 6 ? '#5fb8a6' : '#7a9b9d' }} key={word.name}>{word.name}</span>)}</div></section>
    </div>

    <div className="section-title"><div><h2>数据集</h2><p>共 {filteredProjects.length} 个数据集</p></div><div><button className="ghost-button" onClick={() => navigate('data-center/datasets')}>查看全部数据集 <ArrowUpRight size={14} /></button><button className="ghost-button"><Filter size={15} />筛选</button></div></div><div className="dataset-grid">{displayedDatasets.map((project, index) => <div className={`dataset-card ${index === activeProject ? 'current' : ''}`} key={project.name}><div className="dataset-top"><div className={`dataset-icon ${project.tone}`}><Box size={18} /></div><span className={`status ${project.tone}`}>{project.status}</span><MoreHorizontal size={17} className="muted-icon" /></div><h3>{project.name}</h3><p>{project.updatedAt ? `最近更新于 ${fmtDT(project.updatedAt)}` : '暂无更新时间'}</p><div className="progress-meta"><span>标注进度</span><strong>{project.progress}</strong></div><div className="progress"><span style={{ width: project.progress }} /></div><div className="dataset-footer"><span><Layers3 size={14} />{project.count} 条样本</span><button onClick={() => navigate('analysis/select')}>查看详情 <ArrowUpRight size={14} /></button></div></div>)}</div>
  </div>;
}
function StatCard({ icon: Icon, label, value, sub }: { icon: typeof Database; label: string; value: string; sub: string }) { return <div className="stat-card"><div className="stat-icon"><Icon size={18} /></div><span className="stat-label">{label}</span><strong>{value}</strong><span className="stat-sub">{sub}</span></div>; }

function DonutChart({ data }: { data: { name: string; value: number; tone: string }[] }) {
  const total = data.reduce((sum, item) => sum + item.value, 0);
  let offset = 0;
  const radius = 72; const circumference = 2 * Math.PI * radius;
  return <div className="donut-wrap"><div className="donut-chart"><svg viewBox="0 0 180 180" role="img" aria-label="占比图">{data.map((item) => { const dash = (item.value / total) * circumference; const seg = <circle key={item.name} cx="90" cy="90" r={radius} fill="none" stroke={item.tone} strokeWidth="22" strokeDasharray={`${dash} ${circumference - dash}`} strokeDashoffset={-offset} transform="rotate(-90 90 90)" style={{ transition: 'stroke-dasharray .6s' }} />; offset += dash; return seg; })}<text x="90" y="86" textAnchor="middle" className="donut-total">{total}%</text><text x="90" y="102" textAnchor="middle" className="donut-label">总计</text></svg></div><div className="donut-legend">{data.map((item) => <div className="donut-legend-row" key={item.name}><span><i style={{ background: item.tone }} />{item.name}</span><strong>{item.value}%</strong></div>)}</div></div>;
}

const mockLabelCategories: LabelCategory[] = [
  { id: 1, name: '焊瘤', color: null },
  { id: 2, name: '气孔', color: null },
  { id: 3, name: '未熔合', color: null },
  { id: 4, name: '咬边', color: null },
  { id: 5, name: '正常', color: null },
];
function Annotation({ embedded = false, dataId }: { embedded?: boolean; dataId?: string }) {
  const [mode, setMode] = useState<'image' | 'signal' | 'video'>('image');
  const [saved, setSaved] = useState(false);
  const [selectedLabels, setSelectedLabels] = useState(['焊瘤', '气孔']);
  // 初始为空：标签类别加载完成前不闪现 mock 类别，mock 仅作失败兜底
  const [labels, setLabels] = useState<LabelCategory[]>([]);
  const [taskId, setTaskId] = useState<string | null>(null);
  const [sample, setSample] = useState<Sample | null>(null);
  const [sampleImg, setSampleImg] = useState('');
  const [sampleImgError, setSampleImgError] = useState(false);
  const [aiBoxes, setAiBoxes] = useState<AnnotationLabel[]>([]);
  // 初始为 0：样本总数在接口返回前不得显示 mock 值 1209
  const [totalSamples, setTotalSamples] = useState(0);
  const creatingRef = useRef(false);
  const { status: jobStatus } = useJob<unknown>(taskId);
  const toggleLabel = (label: string) => setSelectedLabels((current) => current.includes(label) ? current.filter((item) => item !== label) : [...current, label]);
  useEffect(() => {
    let cancelled = false;
    listLabelCategories().then((list) => { if (!cancelled && list.length) setLabels(list); }).catch((err) => { if (!cancelled) { setLabels(mockLabelCategories); console.warn('[annotation] listLabelCategories failed', err); } });
    return () => { cancelled = true; };
  }, []);
  // 只从当前焊缝版本导入真实图片对象，禁止创建无样本的演示任务。
  useEffect(() => {
    if (!dataId || creatingRef.current) return;
    let cancelled = false;
    setSample(null); setSampleImg(''); setSampleImgError(false); setAiBoxes([]); setTotalSamples(0); setTaskId(null);
    getWeld(dataId).then((weld) => {
      const imageKey = (weld.latest_version?.object_keys ?? []).find((key) => /\.(jpe?g|png|webp|bmp)$/i.test(key));
      if (!imageKey) throw new Error('当前版本没有真实图片对象');
      creatingRef.current = true;
      return createAnnotationTask({ source: 'manual', name: `真实图像标注 · ${weld.weld_id}` }).then((res) => importAnnotationSamples(res.job_id, { source: 'files', object_keys: [imageKey] }).then(() => res));
    }).then((res) => { if (!cancelled) setTaskId(res.job_id); }).catch((err) => { if (!cancelled) console.warn('[annotation] real image sample unavailable', err); });
    return () => { cancelled = true; creatingRef.current = false; };
  }, [dataId]);
  useEffect(() => {
    if (!taskId || jobStatus !== 'succeeded') return;
    let cancelled = false;
    listAnnotationSamples(taskId, 1).then((page) => {
      if (cancelled) return;
      setTotalSamples(page.total || 0);
      const first = page.items[0];
      if (!first) return;
      getAnnotationSample(taskId, String(first.id)).then((s) => {
        if (cancelled) return;
      setSample(s);
      setAiBoxes(s.annotations ?? []);
        if (s.object_keys && s.object_keys.length) {
          getFileUrl(s.object_keys[0]).then((r) => { if (!cancelled) setSampleImg(r.url); }).catch((err) => { if (!cancelled) { setSampleImgError(true); console.warn('[annotation] getFileUrl failed', err); } });
        }
      }).catch((err) => { if (!cancelled) console.warn('[annotation] getAnnotationSample failed', err); });
    }).catch((err) => { if (!cancelled) console.warn('[annotation] listAnnotationSamples failed', err); });
    return () => { cancelled = true; };
  }, [taskId, jobStatus]);
  const handleAiPretag = () => {
    if (!taskId || !sample) return;
    aiPretag(taskId, String(sample.id)).then((anns) => { setAiBoxes(anns); setSaved(false); }).catch((err) => console.warn('[annotation] aiPretag failed', err));
  };
  const handleSave = () => {
    if (!taskId || !sample) { setSaved(true); return; }
    const boxes = aiBoxes.map((b) => ({ category: b.category, box: b.box, confidence: b.confidence }));
    const labelsToSave: LabelItem[] = selectedLabels.length
      ? selectedLabels.map((cat) => { const ex = boxes.find((b) => b.category === cat); return { category: cat, box: ex && ex.box.length === 4 ? ex.box : [128, 182, 186, 106], confidence: ex?.confidence ?? null }; })
        : boxes.map((b) => ({ category: b.category, box: b.box }));
    saveAnnotation(taskId, String(sample.id), labelsToSave).then(() => setSaved(true)).catch((err) => { console.warn('[annotation] saveAnnotation failed', err); setSaved(true); });
  };
  const frameLabel = sample?.frame_no != null ? String(sample.frame_no).padStart(4, '0') : '—';
  const confidence = sample?.confidence != null ? `${(sample.confidence * 100).toFixed(1)}%` : '—';
  return <div className={embedded ? 'embedded-page' : 'page-wrap'}><PageIntro eyebrow="数据生产线" title="数据标注" description="为模型准备高质量训练样本，支持多模态协同标注。" action={<><button className="outline-button"><Upload size={16} />导入数据</button><button className="primary-button" onClick={handleSave}>{saved ? <Check size={16} /> : <Plus size={16} />}{saved ? '已保存' : '保存标注'}</button></>} /><div className="annotation-mode-bar"><button className={mode === 'signal' ? 'selected' : ''} onClick={() => setMode('signal')}><Waves size={14} />时序标注</button><button className={mode === 'video' ? 'selected' : ''} onClick={() => setMode('video')}><Play size={14} />视频标注</button><button className={mode === 'image' ? 'selected' : ''} onClick={() => setMode('image')}><ImageIcon size={14} />图像标注</button></div>{mode === 'signal' ? <AnnotationSignal dataId={dataId} embedded={embedded} onBack={() => setMode('image')} /> : mode === 'video' ? <AnnotationVideo dataId={dataId} embedded={embedded} onBack={() => setMode('image')} /> : <div className="annotation-layout"><section className="panel annotation-board"><div className="board-toolbar"><div><span className="file-badge"><Archive size={15} />{sample ? <>样本 {frameLabel} / {totalSamples.toLocaleString()}</> : '样本加载中…'}</span><h2>焊接件 · 视觉质检样本</h2></div><div className="toolbar-actions"><button className="icon-button" onClick={handleAiPretag} title="AI 预标注" disabled={!sample}><SlidersHorizontal size={17} /></button><button className="select-button">图像标注 <ChevronDown size={14} /></button></div></div><div className="image-stage">{sampleImg && !sampleImgError ? <img src={sampleImg} alt="真实待标注焊接样本" onError={() => setSampleImgError(true)} /> : <div className="selection-required"><ImageIcon size={23} /><h2>{sampleImgError ? '图片暂时无法预览' : '真实图片加载中'}</h2><p>{sampleImgError ? '请检查对象存储连接后重试。' : '当前版本没有可用的真实图片样本。'}</p></div>}{aiBoxes.length ? aiBoxes.map((a, i) => { const [bx, by, bw, bh] = a.box.length === 4 ? a.box : [128, 182, 186, 106]; return <div key={a.id ?? i} className="annotation-box" style={{ left: `${(bx / 640) * 100}%`, top: `${(by / 480) * 100}%`, width: `${(bw / 640) * 100}%`, height: `${(bh / 480) * 100}%` }}><span>{a.category} {a.confidence != null ? <b>{a.confidence.toFixed(2)}</b> : null}</span></div>; }) : null}<div className="stage-tip">{aiBoxes.length ? <><Sparkles size={14} />AI 已预标注 {aiBoxes.length} 个区域</> : '暂无标注数据'}</div></div><div className="board-footer"><div className="thumb-strip"><>{sampleImg && !sampleImgError && <img className="thumb-active" src={sampleImg} alt="当前样本缩略图" onError={() => setSampleImgError(true)} />}</></div><div className="pagination">{sample ? <span>当前样本</span> : null}</div></div></section><aside className="annotation-side"><section className="panel label-panel"><div className="panel-heading"><div><h2>标签类别</h2><p>选择需要应用的缺陷标签</p></div><button className="more-button"><MoreHorizontal size={18} /></button></div><div className="label-options">{labels.map((label, index) => <button className={`label-chip ${selectedLabels.includes(label.name) ? 'chosen' : ''}`} onClick={() => toggleLabel(label.name)} key={label.name}><i className={`chip-dot chip-${index % 5}`} />{label.name}<span>{selectedLabels.includes(label.name) ? <Check size={14} /> : '+'}</span></button>)}</div></section><section className="panel annotation-info"><div className="panel-heading"><div><h2>标注信息</h2><p>当前样本的详细信息</p></div></div><InfoRow label="数据来源" value={sample ? '真实对象存储图片' : '—'} /><InfoRow label="采集时间" value={sample ? '真实数据记录' : '—'} /><InfoRow label="标注人员" value={sample ? '当前用户' : '—'} /><InfoRow label="置信度" value={sample ? confidence : '—'} accent /></section><div className="ai-card"><div className="ai-card-icon"><Zap size={17} /></div><div><strong>智能标注建议</strong><p>{aiBoxes.length ? `已为你识别 ${aiBoxes.length} 个疑似缺陷区域，建议确认后提交。` : '暂无 AI 标注建议'}</p></div></div></aside></div>}</div>;
}
/** 时序标注模式：ECharts 波形 + 点击设起点/终点选缺陷区间（kind=segment）+ 区间列表 + 保存。
 *
 * 流程：选中焊缝 → getWeld 取最新版本 → createAnnotationTask(source='signal', version_id)
 * → useJob 轮询成功 → listAnnotationSamples 取信号锚点样本 → getSignals 拉四通道波形 →
 * 波形上点击设起点/终点 → 选缺陷类别生成区间 → saveAnnotation(kind='segment') 覆盖写保存。
 */
function AnnotationSignal({ dataId, onBack }: { embedded?: boolean; dataId?: string; onBack: () => void }) {
  // 初始为空：mock 类别仅作失败兜底（见下方 catch），不闪现
  const [labels, setLabels] = useState<LabelCategory[]>([]);
  const [taskId, setTaskId] = useState<string | null>(null);
  const [sample, setSample] = useState<Sample | null>(null);
  const [versionId, setVersionId] = useState<number | null>(null);
  const [signal, setSignal] = useState<SignalData | null>(null);
  const [segments, setSegments] = useState<AnnotationLabel[]>([]);
  const [draft, setDraft] = useState<{ start: number | null; end: number | null }>({ start: null, end: null });
  // dataZoom 视口（百分比）：窗口请求重渲染时保持用户当前缩放位置
  const [zoomPct, setZoomPct] = useState({ start: 0, end: 100 });
  const [saved, setSaved] = useState(false);
  const [weldImg, setWeldImg] = useState('');
  const taskCreatedRef = useRef(false);
  const { status: jobStatus } = useJob<unknown>(taskId);
  const chartElRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    let cancelled = false;
    listLabelCategories().then((list) => { if (!cancelled && list.length) setLabels(list); }).catch((err) => { setLabels(mockLabelCategories); console.warn('[annotation.signal] listLabelCategories failed', err); });
    return () => { cancelled = true; };
  }, []);

  // 解析选中焊缝最新版本并创建 signal 标注任务（best-effort）
  // StrictMode 开发模式会「挂载→cleanup→再挂载」跑两次 effect：一次性闸门必须放在异步
  // resolve 之后（而非同步开头），否则第 1 次置 true → 第 2 次提前 return → 任务永不创建。
  useEffect(() => {
    if (!dataId) return;
    let cancelled = false;
    getWeld(dataId).then((w) => {
      if (cancelled) return;
      const vid = w.latest_version_id;
      if (vid == null) return;
      setVersionId(vid);
      if (taskCreatedRef.current) return;
      taskCreatedRef.current = true;
      createAnnotationTask({ source: 'signal', version_id: vid, name: 'AN-时序' }).then((res) => { if (!cancelled) setTaskId(res.job_id); }).catch((err) => console.warn('[annotation.signal] createAnnotationTask failed', err));
    }).catch((err) => console.warn('[annotation.signal] getWeld failed', err));
    return () => { cancelled = true; };
  }, [dataId]);

  // 任务成功后加载信号锚点样本与既有区间标注
  useEffect(() => {
    if (!taskId || jobStatus !== 'succeeded') return;
    let cancelled = false;
    listAnnotationSamples(taskId, 1).then((page) => {
      if (cancelled) return;
      const first = page.items[0];
      if (!first) return;
      getAnnotationSample(taskId, String(first.id)).then((s) => {
        if (cancelled) return;
        setSample(s);
        setSegments(s.annotations ?? []);
      }).catch((err) => console.warn('[annotation.signal] getAnnotationSample failed', err));
    }).catch((err) => console.warn('[annotation.signal] listAnnotationSamples failed', err));
    return () => { cancelled = true; };
  }, [taskId, jobStatus]);

  // 拉取多通道信号：Overview/Detail 两级加载——首屏全程概览（服务端 min-max 抽稀
  // 2048 点，防 910k 点全量 ~26MB 响应在公网拖 50s+）；dataZoom 缩放停止后按可见
  // 时间窗增量请求高分辨率细节（start/end + 4096 点）。stale 响应用递增 token 丢弃。
  const fetchTokenRef = useRef(0);
  const fetchSignalWindow = (start: number | null, end: number | null) => {
    if (!dataId || versionId == null) return;
    const token = ++fetchTokenRef.current;
    const query = start != null && end != null
      ? { max_points: 4096, start: Math.max(0, start), end }
      : { max_points: 2048 };
    getSignals(dataId, String(versionId), query)
      .then((sig) => { if (token === fetchTokenRef.current) setSignal(sig); })
      .catch((err) => console.warn('[annotation.signal] getSignals failed', err));
  };
  useEffect(() => {
    fetchTokenRef.current += 1; // 焊缝/版本切换：作废在途窗口请求
    setZoomPct({ start: 0, end: 100 });
    fetchSignalWindow(null, null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dataId, versionId]);

  // 焊缝图片参考（版本原始文件里取一张图像）
  useEffect(() => {
    if (!dataId || versionId == null) return;
    let cancelled = false;
    getVersion(dataId, String(versionId)).then((v) => {
      if (cancelled) return;
      const img = (v.object_keys ?? []).find((k) => /\.(jpe?g|png|webp|bmp)$/i.test(k));
      if (!img) return;
      getFileUrl(img).then((r) => { if (!cancelled) setWeldImg(r.url); }).catch(() => {});
    }).catch(() => {});
    return () => { cancelled = true; };
  }, [dataId, versionId]);

  const dur = signal?.source === 'real' ? signal.duration : 0;
  const channels = useMemo(() => signal?.source === 'real' ? signal.channels : [], [signal]);
  const anomalies = useMemo(() => signal?.source === 'real' ? signal.anomalies : [], [signal]);
  const fmtT = (t: number | null | undefined) => (t == null ? '—' : `${t.toFixed(2)}s`);

  // ECharts 渲染 + 点击选段（起点 → 终点）+ 缩放增量取数
  useEffect(() => {
    const el = chartElRef.current;
    if (!el || !channels.length) return;
    const chart = echarts.init(el);
    const gridHeight = 96;
    const segData = [
      ...anomalies.map((a) => [{ xAxis: a.start, itemStyle: { color: '#e88d6c', opacity: 0.1 } }, { xAxis: a.end }]),
      ...segments.map((s) => [{ xAxis: s.start_time ?? 0, itemStyle: { color: '#2c9caf', opacity: 0.18 } }, { xAxis: s.end_time ?? 0 }]),
      ...(draft.start != null && draft.end != null ? [{ xAxis: draft.start, itemStyle: { color: '#f0a34a', opacity: 0.28 } }, { xAxis: draft.end }] : []),
    ];
    // 服务端抽稀（max_points）时带 times 坐标（min-max 选点非均匀）→ 按 [t,v] 画点；
    // 全量响应（旧路径）退回序号均分。x 轴恒为绝对时间 [0, dur]，窗口数据只覆盖
    // 可视区间，dataZoom 视口保持不动。
    const seriesData = (c: { values: number[]; times?: number[] }) => c.times && c.times.length === c.values.length
      ? c.times.map((t, j) => [t, c.values[j]])
      : c.values.map((v, j) => [j / Math.max(c.values.length - 1, 1) * dur, v]);
    const option: echarts.EChartsOption = {
      animation: false,
      tooltip: { trigger: 'axis' },
      legend: { data: channels.map((c) => c.name), top: 0 },
      dataZoom: [
        { type: 'inside', start: zoomPct.start, end: zoomPct.end },
        { type: 'slider', bottom: 6, height: 16, start: zoomPct.start, end: zoomPct.end },
      ],
      grid: channels.map((_, i) => ({ left: 64, right: 28, top: 30 + i * (gridHeight + 14), height: gridHeight })),
      xAxis: channels.map((_, i) => ({ type: 'value', gridIndex: i, min: 0, max: dur, boundaryGap: [0, 0], axisLabel: { show: i === channels.length - 1 } })),
      yAxis: channels.map((c, i) => ({ type: 'value', gridIndex: i, name: `${c.name} (${c.unit})`, min: c.lo, max: c.hi, axisLabel: { fontSize: 10 } })),
      series: channels.map((c, i) => ({
        name: c.name,
        type: 'line',
        xAxisIndex: i,
        yAxisIndex: i,
        showSymbol: false,
        lineStyle: { width: 1.2 },
        data: seriesData(c),
        markArea: { silent: true, data: segData as never },
      })),
    };
    chart.setOption(option, true);
    chart.on('click', (params) => {
      const raw = params.value;
      const t = Array.isArray(raw) ? Number(raw[0]) : Number.NaN;
      if (!Number.isFinite(t)) return;
      setDraft((d) => {
        if (d.start == null) return { start: t, end: null };
        if (d.end == null) return t > d.start ? { start: d.start, end: t } : { start: t, end: null };
        return { start: t, end: null };
      });
    });
    // 缩放停止（300ms 防抖）后按可见窗口增量取细节；拉回全程则取回概览
    let zoomTimer: number | undefined;
    chart.on('datazoom', () => {
      window.clearTimeout(zoomTimer);
      zoomTimer = window.setTimeout(() => {
        const dz = (chart.getOption() as { dataZoom?: { start?: number; end?: number }[] }).dataZoom?.[0];
        if (!dz || dur <= 0) return;
        const startPct = dz.start ?? 0;
        const endPct = dz.end ?? 100;
        setZoomPct({ start: startPct, end: endPct });
        if (endPct - startPct >= 98) {
          fetchSignalWindow(null, null);
        } else {
          fetchSignalWindow((startPct / 100) * dur, (endPct / 100) * dur);
        }
      }, 300);
    });
    return () => { window.clearTimeout(zoomTimer); chart.dispose(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [channels, dur, anomalies, segments, draft, zoomPct]);

  const commitSegment = (cat: string) => {
    if (draft.start == null || draft.end == null) return;
    const now = Date.now();
    setSegments((cur) => [...cur, {
      id: -now,
      sample_id: sample?.id ?? 0,
      category: cat,
      kind: 'segment',
      box: [],
      points: [],
      start_time: draft.start,
      end_time: draft.end,
      confidence: null,
      annotator: '我',
      created_at: null,
      updated_at: null,
    }]);
    setDraft({ start: null, end: null });
  };
  const removeSegment = (id: number) => setSegments((cur) => cur.filter((s) => s.id !== id));
  const handleSave = () => {
    if (!taskId || !sample) return;
    const labelsToSave: LabelItem[] = segments.map((s) => ({
      category: s.category,
      kind: 'segment',
      start_time: s.start_time,
      end_time: s.end_time,
      confidence: s.confidence ?? undefined,
    }));
    saveAnnotation(taskId, String(sample.id), labelsToSave).then(() => setSaved(true)).catch((err) => { console.warn('[annotation.signal] saveAnnotation failed', err); });
  };

  return (
    <div className="annotation-signal-layout">
      <section className="panel annotation-signal-board">
        <div className="board-toolbar">
          <div><span className="file-badge"><Waves size={15} />时序标注 · {dataId ?? '未选择'}</span><h2>{channels.length ? '四通道焊接信号（电流/电压/气体/送丝）' : '加载信号中…'}</h2></div>
          <div className="toolbar-actions"><button className="outline-button" onClick={onBack}><ImageIcon size={14} />图像标注</button><button className="primary-button" onClick={handleSave} disabled={!segments.length || !sample}>{saved ? <Check size={16} /> : <Plus size={16} />}{saved ? '已保存' : '保存标注'}</button></div>
        </div>
        <div className="signal-legend"><span><i style={{ background: '#2c9caf' }} />已标区间</span><span><i style={{ background: '#f0a34a' }} />待确认</span><span><i style={{ background: '#e88d6c' }} />AI 异常提示</span></div>
        <div className="signal-stage">{signal?.source === 'generated' ? <div className="selection-required"><Waves size={23} /><h2>真实时序数据不可用</h2><p>当前版本的 CSV 导入校验未通过，已阻止展示模拟波形。</p></div> : <div ref={chartElRef} className="annotation-signal-chart" style={{ width: '100%', height: 440 }} />}</div>
        <div className="signal-stage-tip">{signal?.source === 'real' ? '点击真实波形设起点 → 再点设终点 → 选择缺陷类型；拖动底部滑块缩放时间轴，放大后自动加载高分辨率细节。' : '正在加载真实时序数据，模拟波形不会用于标注。'}</div>
        {draft.start != null && draft.end != null && (
          <div className="label-options signal-cat-options"><span className="signal-cat-hint">为 {fmtT(draft.start)}–{fmtT(draft.end)} 选择缺陷类型：</span>{labels.map((label, index) => <button key={label.name} className={`label-chip ${index % 5}`} onClick={() => commitSegment(label.name)}><i className={`chip-dot chip-${index % 5}`} />{label.name}</button>)}<button className="ghost-button" onClick={() => setDraft({ start: null, end: null })}>取消</button></div>
        )}
      </section>
      <aside className="annotation-signal-side">
        <section className="panel label-panel"><div className="panel-heading"><div><h2>焊缝图片参考</h2><p>当前版本视觉样本</p></div></div>{weldImg ? <img src={weldImg} alt="真实焊缝图片参考" className="signal-weld-img" /> : <p className="signal-empty">当前版本没有真实图片对象。</p>}</section>
        <section className="panel annotation-info"><div className="panel-heading"><div><h2>缺陷区间</h2><p>{segments.length} 段</p></div></div>{segments.length === 0 ? <p className="signal-empty">尚无区间标注。在波形上点击起点与终点添加。</p> : segments.map((s) => <div className="signal-seg-row" key={s.id}><span className="signal-seg-cat">{s.category}</span><span className="signal-seg-time">{fmtT(s.start_time)}–{fmtT(s.end_time)}</span><button className="ghost-button" onClick={() => removeSegment(s.id)}>删</button></div>)}</section>
      </aside>
    </div>
  );
}
/** 视频标注模式：熔池视频播放器 + 帧捕获 → react-image-annotate 画多边形（kind='polygon'）。
 *
 * 流程：选中焊缝 → getWeld 取最新版本 → createAnnotationTask(source='video', version_id)
 * → useJob 成功 → 取视频锚点样本（meta.video_key → getFileUrl 播放）→ 播放/定位 → 捕获当前帧
 * （canvas 按视频自然分辨率取帧）→ react-image-annotate 画多边形（归一化坐标，`key` 变化重挂载
 * 重置每帧）→ 点标注器自带保存（onExit）→ 归一化 × 帧宽高转像素 → createAnnotationFrame 建帧样本
 * → saveAnnotation(kind='polygon', category='熔池')。已标注帧在侧栏展示。
 */
function AnnotationVideo({ dataId, onBack }: { embedded?: boolean; dataId?: string; onBack: () => void }) {
  const [taskId, setTaskId] = useState<string | null>(null);
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const [frameImage, setFrameImage] = useState<string | null>(null);
  const [frameW, setFrameW] = useState(1280);
  const [frameH, setFrameH] = useState(720);
  const [currentTime, setCurrentTime] = useState(0);
  const [saved, setSaved] = useState(false);
  const [savedFrames, setSavedFrames] = useState<{ timestamp: number; sample_id: number; count: number }[]>([]);
  const [captureKey, setCaptureKey] = useState(0);
  const [videoError, setVideoError] = useState<string | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const taskDataIdRef = useRef<string | null>(null);
  const sampleByTime = useRef<Map<number, number>>(new Map());
  const { status: jobStatus } = useJob<unknown>(taskId);

  // 选择版本链中最新的含视频版本并创建任务；信号处理等最新版本可能不再携带视频对象。
  useEffect(() => {
    if (!dataId) return;
    if (taskDataIdRef.current !== dataId) {
      setTaskId(null);
      setVideoUrl(null);
      setFrameImage(null);
      setSaved(false);
      setSavedFrames([]);
      setVideoError(null);
      sampleByTime.current.clear();
    }
    let cancelled = false;
    listVersions(dataId).then((versions) => {
      if (cancelled) return;
      const version = [...versions].reverse().find((v) =>
        (v.object_keys ?? []).some((key) => /\.(mp4|avi|mkv|mov|webm)$/i.test(key)),
      );
      if (!version) return;
      if (taskDataIdRef.current === dataId) return;
      taskDataIdRef.current = dataId;
      createAnnotationTask({ source: 'video', version_id: version.id, name: 'AN-视频' })
        .then((res) => { if (!cancelled) setTaskId(res.job_id); })
        .catch((err) => {
          if (taskDataIdRef.current === dataId) taskDataIdRef.current = null;
          console.warn('[annotation.video] createAnnotationTask failed', err);
        });
    }).catch((err) => console.warn('[annotation.video] listVersions failed', err));
    return () => { cancelled = true; };
  }, [dataId]);

  // 任务成功后：加载视频锚点样本（video_url）+ 已标注帧
  useEffect(() => {
    if (!taskId || jobStatus !== 'succeeded') return;
    let cancelled = false;
    listAnnotationSamples(taskId, 1, 100).then((page) => {
      if (cancelled) return;
      const anchor = page.items.find((s) => s.meta?.mode === 'video');
      if (anchor) {
        const key = anchor.meta?.video_key;
        if (typeof key === 'string' && key) getFileUrl(key).then((r) => { if (!cancelled) { setVideoUrl(r.url); setVideoError(null); } }).catch((err) => console.warn('[annotation.video] getFileUrl failed', err));
      }
      const frames = page.items.filter((s) => s.meta?.mode === 'frame');
      if (frames.length) {
        const done = frames.map((f) => ({
          timestamp: (f.meta?.timestamp as number) ?? 0,
          sample_id: f.id,
          count: (f.annotations ?? []).length,
        }));
        setSavedFrames(done);
        done.forEach((d) => sampleByTime.current.set(d.timestamp, d.sample_id));
      }
    }).catch((err) => console.warn('[annotation.video] listAnnotationSamples failed', err));
    return () => { cancelled = true; };
  }, [taskId, jobStatus]);

  // 捕获当前帧：canvas 按视频自然分辨率取帧 → dataURL 喂标注器
  const handleCapture = () => {
    const video = videoRef.current;
    const canvas = canvasRef.current;
    if (!video || !canvas) return;
    if (video.readyState < 2) { console.warn('[annotation.video] Video is not ready for decoding'); return; }
    const w = video.videoWidth || 1280;
    const h = video.videoHeight || 720;
    canvas.width = w; canvas.height = h;
    canvas.getContext('2d')?.drawImage(video, 0, 0, w, h);
    setFrameW(w); setFrameH(h);
    setCurrentTime(Math.round(video.currentTime * 1000) / 1000);
    setFrameImage(canvas.toDataURL('image/jpeg', 0.9));
    setSaved(false);
    setCaptureKey((k) => k + 1);
  };
  const stepFrame = (delta: number) => {
    const video = videoRef.current;
    if (!video || !video.duration) return;
    video.currentTime = Math.min(video.duration, Math.max(0, video.currentTime + delta));
  };

  // 播放失败兜底：原始视频常为浏览器不支持的编码（如工业相机 MPEG-4 Part 2），
  // 或转码预览版尚未生成（登记后 media_prep 异步处理）。给出明确原因与建议，
  // 不再静默黑屏。MEDIA_ERR_SRC_NOT_SUPPORTED(4) = 编码/容器浏览器解不了。
  const handleVideoError = () => {
    const code = videoRef.current?.error?.code;
    setVideoError(
      code === 4
        ? '该视频编码格式浏览器不支持解码（常见为工业相机的 MPEG-4 Part 2）。系统已在上传后自动转码 H.264 预览版，请稍后重试；若持续失败请将原始视频转码为 H.264 MP4 后重新上传。'
        : '视频加载失败，请检查网络后重试。',
    );
  };

  // react-image-annotate 保存（onExit）：把归一化多边形转像素 → 建帧样本 → 保存 kind='polygon'
  // 库的 onExit 把 regions 类型标成 unknown[]，先按宽松签名接参、内部收窄（TS 逆变要求）
  const handleExit = (state: { images?: Array<{ regions?: unknown[] }> }) => {
    const regions = (state.images?.[0]?.regions ?? []) as Array<{ type?: string; points?: number[][]; cls?: string; open?: boolean }>;
    // 全部闭合多边形都保存（单类熔池，可一帧多区域），空画布不误报已保存
    const polys = regions.filter((r) => (r.points?.length ?? 0) >= 3 && r.open !== true);
    if (!polys.length || !taskId || !frameImage) return;
    const labels: LabelItem[] = polys.map((p) => ({
      category: p.cls ?? '熔池',
      kind: 'polygon',
      points: (p.points ?? []).map(([nx, ny]) => [Math.round(nx * frameW), Math.round(ny * frameH)]),
    }));
    const existing = sampleByTime.current.get(currentTime);
    const create = existing != null
      ? Promise.resolve(existing)
      : createAnnotationFrame(taskId, currentTime, frameW, frameH).then((r) => { sampleByTime.current.set(currentTime, r.sample_id); return r.sample_id; });
    create
      .then((sid) => saveAnnotation(taskId, String(sid), labels))
      .then(() => {
        setSaved(true);
        const realSid = sampleByTime.current.get(currentTime) ?? 0;
        setSavedFrames((cur) => [...cur.filter((f) => Math.abs(f.timestamp - currentTime) > 0.001), { timestamp: currentTime, sample_id: realSid, count: labels.length }]);
      })
      .catch((err) => console.warn('[annotation.video] saveAnnotation failed', err));
  };

  return (
    <div className="annotation-signal-layout">
      <section className="panel annotation-signal-board">
        <div className="board-toolbar">
          <div><span className="file-badge"><ImageIcon size={15} />视频标注 · {dataId ?? '未选择'}</span><h2>{videoUrl ? '熔池视频 · 播放/定位后捕获帧画多边形' : '加载视频中…'}</h2></div>
          <div className="toolbar-actions"><button className="outline-button" onClick={onBack}><ImageIcon size={14} />图像标注</button><button className="primary-button" onClick={handleCapture} disabled={!videoUrl}><Play size={14} />捕获当前帧</button></div>
        </div>
        <div className="signal-stage">
          {videoError ? (
            <div className="selection-required"><Play size={23} /><h2>视频无法在浏览器中播放</h2><p>{videoError}</p></div>
          ) : (
            <video ref={videoRef} src={videoUrl ?? undefined} controls className="video-annotate-player" onPause={handleCapture} onError={handleVideoError} />
          )}
          <canvas ref={canvasRef} style={{ display: 'none' }} />
        </div>
        <div className="video-annotate-controls">
          <button className="ghost-button" onClick={() => stepFrame(-1 / 30)}>‹ 上一帧</button>
          <span className="signal-seg-time">{fmt(currentTime)}</span>
          <button className="ghost-button" onClick={() => stepFrame(1 / 30)}>下一帧 ›</button>
        </div>
        {frameImage ? (
          <div className="video-annotate-editor">
            <ImageAnnotate
              key={captureKey}
              images={[{ src: frameImage, regions: [] }]}
              enabledTools={['create-polygon']}
              selectedTool="create-polygon"
              regionClsList={['熔池']}
              onExit={handleExit}
            />
          </div>
        ) : <div className="signal-stage-tip">播放/定位到要标注的时间点，点「捕获当前帧」后画多边形（点若干顶点、双击闭合），再点标注器自带的保存按钮。</div>}
        <div className="signal-stage-tip">{saved ? <><Check size={14} />已保存 </> : null}已标注 {savedFrames.length} 帧</div>
      </section>
      <aside className="annotation-signal-side">
        <section className="panel annotation-info">
          <div className="panel-heading"><div><h2>已标注帧</h2><p>{savedFrames.length} 帧 · 熔池区域</p></div></div>
          {savedFrames.length === 0 ? <p className="signal-empty">尚无标注。捕获帧 → 画多边形 → 保存。</p> : savedFrames.map((f) => (
            <div className="signal-seg-row" key={f.timestamp}>
              <span className="signal-seg-cat">熔池</span>
              <span className="signal-seg-time">{fmt(f.timestamp)}</span>
              <span className="signal-seg-count">×{f.count}</span>
            </div>
          ))}
        </section>
      </aside>
    </div>
  );
}
function SelectionSwitcher({ selectedDatasetId, setSelectedDatasetId, selectedDataId, setSelectedDataId, showContext, onChange }: { selectedDatasetId: number | null; setSelectedDatasetId: (id: number | null) => void; selectedDataId: string | null; setSelectedDataId: (id: string | null) => void; showContext: boolean; onChange?: () => void }) {
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [welds, setWelds] = useState<DataRecord[]>([]);
  const [loadingWelds, setLoadingWelds] = useState(false);
  const [row, setRow] = useState<WeldRow | null>(null);
  useEffect(() => {
    let cancelled = false;
    listDatasets().then((list) => {
      if (cancelled) return;
      setDatasets(list);
      if (selectedDatasetId == null && list.length) setSelectedDatasetId(list[0].id);
    }).catch((err) => console.warn('[selection-switcher] datasets failed', err));
    return () => { cancelled = true; };
  }, [selectedDatasetId, setSelectedDatasetId]);
  useEffect(() => {
    if (selectedDatasetId == null) { setWelds([]); return; }
    let cancelled = false;
    setLoadingWelds(true);
    listWelds({ dataset_id: selectedDatasetId, page_size: 100 }).then((page) => {
      if (!cancelled) setWelds(page.items);
    }).catch((err) => console.warn('[selection-switcher] welds failed', err)).finally(() => {
      if (!cancelled) setLoadingWelds(false);
    });
    return () => { cancelled = true; };
  }, [selectedDatasetId]);
  useEffect(() => {
    if (!selectedDataId) { setRow(null); return; }
    let cancelled = false;
    setRow(null);
    getWeld(selectedDataId)
      .then((weld) => { if (!cancelled) setRow(toWeldRow(weld)); })
      .catch((err) => {
        if (!cancelled) {
          setRow(mockWeldRows.find((item) => item.id === selectedDataId) ?? mockWeldRows[0]);
          console.warn('[selection] getWeld failed', err);
        }
      });
    return () => { cancelled = true; };
  }, [selectedDataId]);
  return <div className="selection-switcher" role="region" aria-label="当前数据上下文">
    <div className="selection-switcher-title"><Database size={15} /><span>当前处理数据</span></div>
    <label className="filter-field">数据集<select value={selectedDatasetId ?? ''} onChange={(event) => { const id = event.target.value ? Number(event.target.value) : null; setSelectedDatasetId(id); setSelectedDataId(null); }}><option value="">请选择数据集</option>{datasets.map((d) => <option value={d.id} key={d.id}>{d.name}</option>)}</select></label>
    <label className="filter-field">焊缝数据<select value={selectedDataId ?? ''} disabled={selectedDatasetId == null || loadingWelds} onChange={(event) => setSelectedDataId(event.target.value || null)}><option value="">{loadingWelds ? '数据加载中…' : '请选择一条焊缝数据'}</option>{welds.map((weld) => <option value={weld.weld_id} key={weld.weld_id}>{weld.weld_id} · {weld.weld_name ?? '未命名'}</option>)}</select></label>
    {showContext && selectedDataId ? <div className="selection-switcher-details"><div><span>焊缝</span><strong>{row?.id ?? '加载中…'}</strong></div><div><span>来源</span><strong>{row?.source ?? '—'}</strong></div><div><span>焊机</span><strong>{row?.machine ?? '—'}</strong></div><div><span>焊缝版本</span><strong>{row?.version ?? '—'}</strong></div>{row && <StatusPill tone={row.quality === '异常' ? 'red' : row.quality === '待复核' ? 'orange' : 'green'}>{row.quality}</StatusPill>}{onChange && <button className="ghost-button selection-context-change" onClick={onChange}>更换数据 <ArrowUpRight size={13} /></button>}</div> : <span className="selection-switcher-hint">选择数据集和焊缝后，分析与标注功能可用</span>}
  </div>;
}

function SelectionRequired({ onBack }: { onBack: () => void }) {
  return <div className="selection-required"><div className="selection-icon"><Database size={23} /></div><h2>请先选择数据集和焊缝数据</h2><p>当前功能必须绑定真实数据后才能执行，请在页面上方选择数据集和一条焊缝。</p><button className="outline-button" onClick={onBack}><ChevronLeft size={14} />前往选择数据</button></div>;
}

type VersionDetailDrawerProps =
  | { mode: 'weld'; weldId: string; versionId: string; onClose: () => void }
  | { mode: 'dataset'; datasetId: string; version: DatasetVersion; onClose: () => void };

function VersionDetailDrawer(props: VersionDetailDrawerProps) {
  const { onClose } = props;
  const ownerId = props.mode === 'weld' ? props.weldId : props.datasetId;
  const versionId = props.mode === 'weld' ? props.versionId : String(props.version.id);
  const [weldVersion, setWeldVersion] = useState<DataVersion | null>(null);
  const [validation, setValidation] = useState<ValidationReport | null>(null);
  const [datasetVersion, setDatasetVersion] = useState<DatasetVersion | null>(props.mode === 'dataset' ? props.version : null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose(); };
    document.addEventListener('keydown', onKeyDown);
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => { document.removeEventListener('keydown', onKeyDown); document.body.style.overflow = previousOverflow; };
  }, [onClose]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    if (props.mode === 'weld') {
      Promise.all([
        getVersion(ownerId, versionId),
        getValidation(ownerId, versionId).catch(() => null),
      ]).then(([version, report]) => {
        if (cancelled) return;
        setWeldVersion(version);
        setValidation(report);
        setLoading(false);
      }).catch((err) => { if (!cancelled) { setError(err instanceof Error ? err.message : '版本详情加载失败'); setLoading(false); } });
    } else {
      getDatasetVersion(ownerId, versionId)
        .then((version) => { if (!cancelled) { setDatasetVersion(version); setLoading(false); } })
        .catch((err) => { if (!cancelled) { setError(err instanceof Error ? err.message : '快照详情加载失败'); setLoading(false); } });
    }
    return () => { cancelled = true; };
  }, [props.mode, ownerId, versionId]);

  const version = props.mode === 'weld' ? weldVersion : datasetVersion;
  const split = version && 'split' in version
    ? `${version.split.train?.toLocaleString() ?? '—'} / ${version.split.val?.toLocaleString() ?? '—'} / ${version.split.test?.toLocaleString() ?? '—'}`
    : null;
  const quality = version && 'quality' in version && version.quality
    ? `${((1 - version.quality.repeat_rate - version.quality.empty_label_rate - version.quality.dimension_missing_rate) * 100).toFixed(1)}%`
    : '—';

  const versionKind = props.mode === 'weld' ? '焊缝版本' : '数据集快照';
  return <div className="version-drawer-backdrop" role="presentation" onClick={onClose}><aside className="version-drawer" role="dialog" aria-modal="true" aria-label={`${versionKind}详情`} onClick={(event) => event.stopPropagation()}><div className="version-drawer-head"><div><span className="eyebrow"><span />{versionKind}详情</span><h2>{version?.version_no ?? '加载中…'}</h2></div><button className="icon-button" onClick={onClose} aria-label={`关闭${versionKind}详情`}>×</button></div>{loading && <div className="version-drawer-state">正在加载{versionKind}详情…</div>}{error && <div className="version-drawer-state error">{error}</div>}{!loading && !error && version && props.mode === 'weld' && <><div className="version-drawer-summary"><StatusPill>{weldVersion?.action}</StatusPill><span>{weldVersion?.operator ?? '—'} · {fmtDT(weldVersion?.created_at)}</span></div><div className="version-drawer-section"><h3>焊缝版本信息</h3><InfoRow label="处理动作" value={weldVersion?.action ?? '—'} /><InfoRow label="操作人" value={weldVersion?.operator ?? '—'} /><InfoRow label="备注" value={weldVersion?.note ?? '暂无备注'} /><InfoRow label="数据文件" value={weldVersion?.object_keys.length ? `${weldVersion.object_keys.length} 个文件` : '暂无关联文件'} /></div><div className="version-drawer-section"><h3>核验结果</h3>{validation ? <><InfoRow label="质量分数" value={`${validation.score.toFixed(1)} 分`} accent /><InfoRow label="规则统计" value={`通过 ${validation.passed} · 警告 ${validation.warning} · 失败 ${validation.failed}`} /></> : <p className="version-drawer-muted">尚未执行核验</p>}</div></>}{!loading && !error && version && props.mode === 'dataset' && <><div className="version-drawer-summary"><StatusPill>固定快照</StatusPill><span>创建于 {fmtDT(datasetVersion?.created_at)}</span></div><div className="version-drawer-section"><h3>数据集快照信息</h3><InfoRow label="样本总数" value={`${datasetVersion?.item_count.toLocaleString() ?? '—'} 条`} /><InfoRow label="训练 / 验证 / 测试" value={split ?? '—'} /><InfoRow label="数据质量" value={quality} accent /><InfoRow label="快照 ID" value={datasetVersion?.snapshot_id ?? '尚未生成'} /></div><div className="version-drawer-section"><h3>使用说明</h3><p className="version-drawer-muted">该快照是固定样本清单，不会随单条焊缝后续处理自动变化。</p></div></>}</aside></div>;
}

/** 数据集列表/详情行展示形状（table/detail 期望的字段）。 */
interface DatasetRow {
  id: string;
  numericId?: number;
  name: string;
  task: string;
  samples: string;
  weldCount?: number;
  source: string;
  progress: string;
  version: string;
  status: string;
  tone: 'green' | 'orange';
  split: string;
  currentVersionId: number | null;
}
/** ISO 时间 → "YYYY-MM-DD HH:MM"。 */
const fmtDT = (iso: string | null | undefined): string => (iso ? iso.replace('T', ' ').slice(0, 16) : '—');
/** 数据集 → 展示行（split 空/未构建 → '—'，status→tone，progress→"96.8%"）。 */
function toDatasetRow(d: Dataset): DatasetRow {
  const s = d.split;
  const split = s && s.train !== undefined
    ? `${s.train.toLocaleString()} / ${(s.val ?? 0).toLocaleString()} / ${(s.test ?? 0).toLocaleString()}`
    : '—';
  return {
    id: d.dataset_no || String(d.id),
    numericId: d.id,
    name: d.name,
    task: d.task,
    samples: d.sample_count.toLocaleString(),
    weldCount: d.weld_count ?? 0,
    source: '多模态数据',
    progress: `${d.progress ?? 0}%`,
    version: d.version ?? '—',
    status: d.status,
    tone: d.status === '可训练' ? 'green' : 'orange',
    split,
    currentVersionId: d.current_version_id,
  };
}
const mockDatasetRows: DatasetRow[] = [
  { id: 'DS-DEFECT-001', name: '焊接缺陷检测集', task: '目标检测', samples: '8,420', source: '产线相机 · 多品牌', progress: '96.8%', version: 'v1.3', status: '可训练', tone: 'green', split: '6,736 / 842 / 842', currentVersionId: 2 },
  { id: 'DS-POOL-002', name: '熔池分割数据集', task: '语义分割', samples: '5,680', source: '高速相机 · Fronius', progress: '91.2%', version: 'v0.8', status: '标注中', tone: 'orange', split: '4,544 / 568 / 568', currentVersionId: 1 },
  { id: 'DS-QUALITY-003', name: '工艺质量预测集', task: '多模态回归', samples: '2,140', source: '产线相机 · 多模态', progress: '100%', version: 'v2.0', status: '可训练', tone: 'green', split: '1,712 / 214 / 214', currentVersionId: 1 }
];
const inputDimensions = ['Voltage', 'GasSpeed', 'Current', 'Molten_feature', 'Sound_feature', '焊缝照片', '熔池视频'];
const requiredByTask: Record<string, string[]> = { '目标检测': ['Current', 'Voltage', 'GasSpeed'], '语义分割': ['熔池视频'], '多模态回归': ['Current', 'Voltage'] };
const mockDimensions: DimensionStatus[] = inputDimensions.map((dim) => {
  const isRequired = requiredByTask['目标检测']?.includes(dim) ?? false;
  const isAvailable = ['Current', 'Voltage', 'GasSpeed', 'Molten_feature', 'Sound_feature'].includes(dim);
  return { name: dim, status: isAvailable ? '已具备' : isRequired ? '必需' : '缺失', required: isRequired };
});
const mockLineage: LineageNode[] = [
  { type: 'records', label: '原始焊缝数据', count: 1086, items: [] },
  { type: 'annotation_tasks', label: '标注任务', count: 1, items: [{ name: 'AN-0248' }] },
  { type: 'dataset_versions', label: '数据集版本', count: 2, items: ['v1.2', 'v1.3'] },
  { type: 'training_tasks', label: '模型训练', count: 3, items: [] },
];
function mockReadinessChecks(task: string): { name: string; passed: boolean }[] {
  const names = task === '语义分割' ? ['熔池视频已切分为图像帧', '图像与像素级掩膜数量一致', '标注审核通过率 ≥ 90%', '按焊缝 ID 完成数据划分'] : task === '多模态回归' ? ['Current 与 Voltage 时间轴已对齐', '至少具备两种输入模态', '质量标签完整且无空值', '按焊缝 ID 完成数据划分'] : ['Current、Voltage、GasSpeed 均完整', '异常区段标签已审核', '信号采样率与时间轴一致', '按焊缝 ID 完成数据划分'];
  return names.map((name) => ({ name, passed: true }));
}

type DatasetView = 'list' | 'overview' | 'dataset-records' | 'records' | 'record-detail';

function DatasetWorkspace({ navigate, selectedDatasetId, datasetHomeKey, onDetailChange, setSelectedDataId, setSelectedDatasetId }: { navigate: (route: Route) => void; selectedDatasetId: number | null; datasetHomeKey: number; onDetailChange?: (isDetail: boolean) => void; setSelectedDataId: (id: string | null) => void; setSelectedDatasetId: (id: number | null) => void }) {
  // 初始为空 + 加载中：不得让 mock 数据集行在接口响应到达前闪现，mock 仅作失败兜底
  const [rows, setRows] = useState<DatasetRow[]>([]);
  const [listLoading, setListLoading] = useState(true);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedVersionId, setSelectedVersionId] = useState<number | null>(null);
  const [selectedRecordId, setSelectedRecordId] = useState<string | null>(null);
  const [selectedRecordSplit, setSelectedRecordSplit] = useState<DatasetItemRow['split'] | null>('train');
  const [recordBackView, setRecordBackView] = useState<'dataset-records' | 'records'>('records');
  const [view, setView] = useState<DatasetView>('list');
  const [createDialog, setCreateDialog] = useState(false);
  const selectedIdRef = useRef<string | null>(null);
  const dataset = rows.find((item) => item.id === selectedId);
  useEffect(() => {
    if (datasetHomeKey === 0) return;
    selectedIdRef.current = null;
    setSelectedId(null);
    setSelectedVersionId(null);
    setSelectedRecordId(null);
    setSelectedDataId(null);
    setSelectedDatasetId(null);
    setView('list');
  }, [datasetHomeKey, setSelectedDataId, setSelectedDatasetId]);
  useEffect(() => { onDetailChange?.(view === 'overview'); return () => onDetailChange?.(false); }, [view, onDetailChange]);
  // 顶部 SelectionSwitcher 与本页原有的内部选择必须保持同一数据集。
  // 仅在外部选择确实发生变化时进入该数据集概览，避免首次加载时从列表页意外跳转。
  useEffect(() => {
    if (selectedDatasetId == null || !rows.length) return;
    const target = rows.find((item) => item.numericId === selectedDatasetId);
    if (!target || selectedIdRef.current === target.id) return;
    selectedIdRef.current = target.id;
    setSelectedId(target.id);
    setSelectedVersionId(target.currentVersionId);
    setSelectedRecordId(null);
    setSelectedDataId(null);
    setView('overview');
  }, [selectedDatasetId, rows, setSelectedDataId]);
  const applyRows = (nextRows: DatasetRow[]) => {
    const selected = nextRows.find((item) => item.id === selectedIdRef.current) ?? nextRows[0];
    setRows(nextRows);
    selectedIdRef.current = selected?.id ?? null;
    setSelectedId(selected?.id ?? null);
    setSelectedVersionId(selected?.currentVersionId ?? null);
  };
  useEffect(() => {
    let cancelled = false;
    setListLoading(true);
    listDatasets().then((list) => { if (!cancelled) { applyRows(list.map(toDatasetRow)); setListLoading(false); } })
      .catch((err) => { if (!cancelled) { setRows(mockDatasetRows); setListLoading(false); console.warn('[datasets] listDatasets failed', err); } });
    return () => { cancelled = true; };
  }, []);
  const reload = () => listDatasets().then((list) => applyRows(list.map(toDatasetRow)));
  const handleCreate = (name: string) => {
    setCreateDialog(false);
    createDataset({ name, task: '目标检测' }).then(reload).catch((err) => console.warn('[datasets] createDataset failed', err));
  };
  const selectDataset = (item: DatasetRow) => {
    selectedIdRef.current = item.id;
    setSelectedId(item.id);
    setSelectedDatasetId(item.numericId ?? null);
    setSelectedVersionId(item.currentVersionId);
    setSelectedRecordId(null);
    setSelectedDataId(null);
    setView('overview');
  };
  const selectVersion = (versionId: number) => { setSelectedVersionId(versionId); setSelectedRecordId(null); setSelectedDataId(null); };
  return <div className="dataset-workspace">{view === 'list' && <><div className="dataset-list-heading"><div><div className="dataset-breadcrumb">数据中心 / 数据集列表</div><h2>数据集列表</h2><p>管理和浏览平台中的全部数据集，查看快照、成员数据与训练状态。</p></div><button className="primary-button" onClick={() => setCreateDialog(true)}><Plus size={15} />新建数据集</button></div><div className="dataset-rule"><GitBranch size={14} /><span>数据集以固定快照保存；焊缝版本记录单条数据的处理历史。</span><span className="dataset-rule-count">可训练 {rows.filter((item) => item.status === '可训练').length} 个</span></div>{listLoading ? <p className="dataset-empty-state" role="status">数据集列表加载中…</p> : <div className="dataset-table">{rows.map((item) => <button className="dataset-list-row" onClick={() => selectDataset(item)} key={item.id}><span className="dataset-row-icon"><Box size={17} /></span><span className="dataset-row-main"><strong>{item.name}</strong><small>{item.id} · {item.task}</small></span><span><small>样本数</small><strong className="mono">{item.samples}</strong></span><span><small>标注完成度</small><strong className="mono">{item.progress}</strong></span><span><small>当前快照</small><strong className="mono">{item.version ? `快照 ${item.version}` : '未生成'}</strong></span><StatusPill tone={item.tone}>{item.status}</StatusPill><ArrowUpRight size={15} className="muted-icon" /></button>)}</div>}{createDialog && <TextDialog title="新建数据集" label="数据集名称" initialValue="新建数据集" onCancel={() => setCreateDialog(false)} onConfirm={handleCreate} />}</>}{view === 'overview' && dataset && <DatasetDetail dataset={dataset} versionId={selectedVersionId} onShowRecords={() => setView('records')} onShowAllRecords={() => setView('dataset-records')} onVersionChange={selectVersion} />}{view === 'dataset-records' && dataset && <DatasetSourceRecords dataset={dataset} onBack={() => setView('overview')} onSelectRecord={(record) => { setRecordBackView('dataset-records'); setSelectedRecordId(record.weld_id); setSelectedDataId(record.weld_id); setSelectedVersionId(record.latest_version_id ?? selectedVersionId); setSelectedRecordSplit(null); setView('record-detail'); }} />}{view === 'records' && dataset && selectedVersionId != null && <DatasetRecords dataset={dataset} versionId={selectedVersionId} onBack={() => setView('overview')} onVersionChange={(versionId) => { selectVersion(versionId); setView('records'); }} onSelectRecord={(row) => { if (!row.weld_id) return; setRecordBackView('records'); setSelectedRecordId(row.weld_id); setSelectedRecordSplit(row.split); setSelectedDataId(row.weld_id); setView('record-detail'); }} />}{view === 'record-detail' && dataset && selectedVersionId != null && selectedRecordId && <DatasetRecordDetail weldId={selectedRecordId} dataset={dataset} versionId={selectedVersionId} split={selectedRecordSplit} onBack={() => setView(recordBackView)} setSelectedDataId={setSelectedDataId} navigate={navigate} />}</div>;
}

function DatasetDetail({ dataset, versionId, onShowRecords, onShowAllRecords, onVersionChange }: { dataset: DatasetRow; versionId: number | null; onShowRecords: () => void; onShowAllRecords: () => void; onVersionChange: (versionId: number) => void }) {
  const [detail, setDetail] = useState<Dataset | null>(null);
  // 初始为空：mock 仅作接口失败兜底（见下方 catch），不得在加载期闪现演示维度/血缘
  const [dims, setDims] = useState<DimensionStatus[]>([]);
  const [readiness, setReadiness] = useState<ReadinessCheck | null>(null);
  const [readinessLoading, setReadinessLoading] = useState(true);
  const [versions, setVersions] = useState<DatasetVersion[]>([]);
  const [selectedVersion, setSelectedVersion] = useState<DatasetVersion | null>(null);
  const [lineage, setLineage] = useState<LineageNode[]>([]);
  useEffect(() => {
    let cancelled = false;
    setDetail(null);
    setDims(mockDimensions);
    setReadiness(null);
    setReadinessLoading(true);
    setVersions([]);
    setSelectedVersion(null);
    setLineage(mockLineage);
    getDataset(dataset.id).then((d) => { if (!cancelled) setDetail(d); }).catch((err) => { if (!cancelled) console.warn('[datasets] getDataset failed', err); });
    getDimensions(dataset.id).then((list) => { if (!cancelled) setDims(list); }).catch((err) => { if (!cancelled) { setDims(mockDimensions); console.warn('[datasets] getDimensions failed', err); } });
    getReadiness(dataset.id).then((r) => { if (!cancelled) setReadiness(r); }).catch((err) => { if (!cancelled) console.warn('[datasets] getReadiness failed', err); }).finally(() => { if (!cancelled) setReadinessLoading(false); });
    listDatasetVersions(dataset.id).then((list) => { if (!cancelled) setVersions(list); }).catch((err) => { if (!cancelled) console.warn('[datasets] listDatasetVersions failed', err); });
    getLineage(dataset.id).then((list) => { if (!cancelled) setLineage(list); }).catch((err) => { if (!cancelled) { setLineage(mockLineage); console.warn('[datasets] getLineage failed', err); } });
    return () => { cancelled = true; };
  }, [dataset.id]);
  const quality = detail?.quality;
  // 这些质量风险率可能来自不同规则，允许重叠，不能直接相加后展示负质量。
  // 页面指标表达“剩余质量”时始终限制在 0%–100%，避免误导用户做出错误准入判断。
  const qualityPct = quality ? `${Math.max(0, Math.min(100, (1 - quality.repeat_rate - quality.empty_label_rate - quality.dimension_missing_rate) * 100)).toFixed(1)}%` : '…';
  const updated = detail?.updated_at ? fmtDT(detail.updated_at) : '…';
  const currentVersionId = versionId;
  const currentVersion = currentVersionId == null ? null : versions.find((version) => version.id === currentVersionId) ?? null;
  const visibleVersions = versions;
  const lineageIcon: Record<string, typeof Database> = { records: Database, annotation_tasks: Tag, dataset_versions: Box, training_tasks: TrainFront };
  const lineageSuffix: Record<string, string> = { records: '条', training_tasks: '次', annotation_tasks: '个', dataset_versions: '个' };
  return <><div className="dataset-detail"><div className="dataset-breadcrumb">数据中心 / 数据集 / {dataset.name} / 数据集概览</div><div className="dataset-detail-head"><div><span className="file-badge"><Box size={14} />{dataset.id}</span><h2>{dataset.name} <em>{dataset.version ? `快照 ${dataset.version}` : '未生成快照'}</em></h2><p>{dataset.task} · {dataset.source} · 最近更新 {updated}</p></div><div className="dataset-detail-actions"><StatusPill tone={dataset.tone as 'green' | 'orange'}>{dataset.status}</StatusPill><button className="primary-button dataset-primary-entry" onClick={onShowAllRecords}><Database size={14} />查看全部焊缝 · {dataset.weldCount} 条</button>{currentVersionId != null && <button className="outline-button" onClick={onShowRecords}><GitBranch size={14} />查看当前快照 · {currentVersion?.item_count ?? detail?.sample_count ?? 0} 条</button>}</div></div>{currentVersionId == null && <div className="dataset-empty-state">当前数据集还没有固定快照；新数据上传完成后系统会自动生成快照。</div>}<div className="dataset-detail-grid"><div className="dataset-detail-stat"><span>数据集数据</span><strong>{detail ? detail.sample_count.toLocaleString() : dataset.samples}</strong><small>固定快照中的样本总数</small></div><div className="dataset-detail-stat"><span>标注完成度</span><strong>{dataset.progress}</strong><small>通过质检的标注</small></div><div className="dataset-detail-stat"><span>训练 / 验证 / 测试</span><strong>{dataset.split}</strong><small>按数据集快照固定划分</small></div><div className="dataset-detail-stat"><span>数据质量</span><strong>{qualityPct}</strong><small>重复与空标注已检查</small></div></div><DatasetInputPanel task={dataset.task} dims={dims} /><ModelReadiness task={dataset.task} status={dataset.status} readiness={readiness} loading={readinessLoading} /><div className="dataset-detail-columns"><section className="panel"><div className="panel-heading"><div><h2>数据集快照</h2><p>固定训练样本清单；不随单条焊缝后续处理自动变化</p></div></div><div className="dataset-version-list">{visibleVersions.length ? visibleVersions.map((v) => <div className={`dataset-version ${v.id === currentVersionId ? 'current' : ''}`} key={v.version_no} onClick={() => onVersionChange(v.id)}><span>{v.version_no}</span><div><strong>固定快照 · {v.item_count.toLocaleString()} 条样本</strong><small>{fmtDT(v.created_at)}</small></div>{v.id === currentVersionId ? <StatusPill>当前快照</StatusPill> : <button className="ghost-button" onClick={() => setSelectedVersion(v)}>查看详情</button>}</div>) : <p className="dataset-empty-state">还没有生成数据集快照。</p>}</div></section><section className="panel"><div className="panel-heading"><div><h2>数据血缘</h2><p>从焊缝版本到训练任务的关联</p></div></div>{lineage.length ? <div className="lineage">{lineage.flatMap((node, i) => { const Icon = lineageIcon[node.type] ?? Database; const sep = i === 0 ? [] : [<i key={`sep-${i}`}>↓</i>]; return [...sep, <span key={node.type}><Icon size={14} />{node.label} <b>{node.count} {lineageSuffix[node.type] ?? '个'}</b></span>]; })}</div> : <p className="dataset-empty-state" role="status">数据血缘加载中…</p>}</section></div></div>{selectedVersion && <VersionDetailDrawer mode="dataset" datasetId={dataset.id} version={selectedVersion} onClose={() => setSelectedVersion(null)} />}</>;
}

const mockDatasetItemRows: DatasetItemRow[] = [
  { sample_id: 1, weld_id: 'WLD-20260815-0248', weld_name: 'MAG 短路过渡样本', registration_no: 'REG-202608-001', source: '产线相机 · 03号', machine: 'Fronius CMT', modalities: ['视频', '时序', '声音'], quality: '通过', split: 'train', frame_no: 248, created_at: '2026-08-15 09:42' },
  { sample_id: 2, weld_id: 'WLD-20260815-0247', weld_name: '熔池异常样本', registration_no: 'REG-202608-002', source: '实训线 · 02号', machine: 'OTC FD-V8', modalities: ['视频', '时序'], quality: '待复核', split: 'val', frame_no: 249, created_at: '2026-08-15 09:18' },
  { sample_id: 3, weld_id: 'WLD-20260814-0246', weld_name: '红外多模态样本', registration_no: 'REG-202608-003', source: '产线相机 · 03号', machine: 'Kemppi Minarc', modalities: ['视频', '时序', '红外'], quality: '通过', split: 'test', frame_no: 250, created_at: '2026-08-14 18:32' },
];
const splitLabel: Record<DatasetItemRow['split'], string> = { train: '训练集', val: '验证集', test: '测试集' };

function DatasetRecords({ dataset, versionId, onBack, onVersionChange, onSelectRecord }: { dataset: DatasetRow; versionId: number; onBack: () => void; onVersionChange: (versionId: number) => void; onSelectRecord: (row: DatasetItemRow) => void }) {
  const [query, setQuery] = useState('');
  const [quality, setQuality] = useState('');
  const [split, setSplit] = useState<DatasetItemRow['split'] | ''>('');
  const [page, setPage] = useState(1);
  // 初始为空 + 加载中：不得让 mock 演示行在接口响应到达前闪现，mock 仅作失败兜底
  const [rows, setRows] = useState<DatasetItemRow[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState<string | null>(null);
  const [versionChoices, setVersionChoices] = useState<DatasetVersion[]>([]);
  const [versionSummary, setVersionSummary] = useState<DatasetVersion | null>(null);
  const [versionSummaryUnavailable, setVersionSummaryUnavailable] = useState(false);
  useEffect(() => { listDatasetVersions(dataset.id).then(setVersionChoices).catch((err) => console.warn('[datasets] listDatasetVersions failed', err)); }, [dataset.id]);
  useEffect(() => {
    let cancelled = false;
    setVersionSummary(null);
    setVersionSummaryUnavailable(false);
    getDatasetVersion(dataset.id, String(versionId)).then((version) => { if (!cancelled) setVersionSummary(version); })
      .catch((err) => { if (!cancelled) { setVersionSummary(null); setVersionSummaryUnavailable(true); console.warn('[datasets] getDatasetVersion failed', err); } });
    return () => { cancelled = true; };
  }, [dataset.id, versionId]);
  useEffect(() => { setPage(1); }, [query, quality, split, versionId]);
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    listDatasetVersionItems(dataset.id, versionId, { q: query.trim() || undefined, quality: quality || undefined, split: split || undefined, page, page_size: PAGE_SIZE })
      .then((result) => { if (!cancelled) { setRows(result.items); setTotal(result.total); setNotice(null); } })
      .catch((err) => { if (!cancelled) { setRows(mockDatasetItemRows); setTotal(mockDatasetItemRows.length); setNotice('成员列表暂时无法同步，请刷新后重试。'); console.warn('[datasets] listDatasetVersionItems failed', err); } })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [dataset.id, versionId, query, quality, split, page]);
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const splitTotals = versionSummary?.split ?? null;
  const summaryState = versionSummary ? `数据集快照 · ${versionSummary.version_no}` : versionSummaryUnavailable ? '快照信息暂不可用' : '快照信息加载中…';
  return <section className="dataset-records"><div className="dataset-breadcrumb">数据中心 / 数据集 / {dataset.name} / 当前版本数据</div><div className="dataset-context-card"><div><span>数据集</span><strong>{dataset.name}</strong><small>{dataset.task} · 版本 #{versionId}</small></div><div><span>样本数</span><strong>{versionSummary?.item_count != null ? versionSummary.item_count.toLocaleString() : loading && !versionSummaryUnavailable ? '…' : total.toLocaleString()}</strong></div><div><span>训练 / 验证 / 测试</span><strong>{splitTotals ? `${splitTotals.train?.toLocaleString() ?? '—'} / ${splitTotals.val?.toLocaleString() ?? '—'} / ${splitTotals.test?.toLocaleString() ?? '—'}` : versionSummaryUnavailable ? '版本切分信息暂不可用' : '加载中…'}</strong></div><div><span>版本摘要</span><strong>{summaryState}</strong></div><div className="dataset-summary-links"><button className="ghost-button" onClick={onBack}><ChevronLeft size={14} />返回概览</button><label className="filter-field">切换版本<select value={versionId} onChange={(event) => onVersionChange(Number(event.target.value))}>{(versionChoices.length ? versionChoices : [{ id: versionId, version_no: `#${versionId}` } as DatasetVersion]).map((version) => <option value={version.id} key={version.id}>{version.version_no}</option>)}</select></label></div></div><div className="dataset-records-header"><div><h2>当前版本数据</h2><p>固定快照成员，筛选与分页由服务端执行。</p></div><div className="data-filter-strip"><div className="filter-field keyword"><label>关键词</label><div className="inline-search"><Search size={14} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="焊缝 ID、名称或登记编号" /></div></div><label className="filter-field">核验状态<select value={quality} onChange={(event) => setQuality(event.target.value)}><option value="">全部</option><option value="通过">通过</option><option value="待复核">待复核</option><option value="异常">异常</option></select></label><label className="filter-field">数据划分<select value={split} onChange={(event) => setSplit(event.target.value as DatasetItemRow['split'] | '')}><option value="">全部</option><option value="train">训练集</option><option value="val">验证集</option><option value="test">测试集</option></select></label></div></div>{notice && <p className="dataset-empty-state" role="status">{notice}</p>}{rows.length ? <div className="dataset-records-table"><div className="dataset-record-row dataset-record-head"><span>样本 ID / 焊缝</span><span>登记编号</span><span>来源 / 焊机</span><span>模态</span><span>核验状态</span><span>数据划分</span><span>采集时间</span></div>{rows.map((row) => <button className="dataset-record-row" key={row.sample_id} disabled={!row.weld_id} title={row.weld_id ? undefined : '该成员未关联焊缝，无法打开数据详情'} onClick={() => onSelectRecord(row)}><span><strong>样本 #{row.sample_id}</strong><small>{row.weld_id ?? '未关联焊缝'} · 帧 {row.frame_no ?? '—'}</small></span><span>{row.registration_no ?? '—'}</span><span>{row.source ?? '—'}<small>{row.machine ?? '—'}</small></span><span>{row.modalities.join(' / ') || '—'}</span><StatusPill tone={row.quality === '异常' ? 'red' : row.quality === '待复核' ? 'orange' : 'green'}>{row.quality ?? '未核验'}</StatusPill><span>{splitLabel[row.split]}</span><span>{fmtDT(row.created_at)}</span></button>)}</div> : loading ? <p className="dataset-empty-state" role="status">成员列表加载中…</p> : <p className="dataset-empty-state">当前版本没有符合筛选条件的成员样本。</p>}<div className="table-footer"><span>共 {total} 条</span><div className="pagination"><button disabled={page === 1} onClick={() => setPage((value) => value - 1)}>‹</button><span>{page} / {totalPages}</span><button disabled={page === totalPages} onClick={() => setPage((value) => value + 1)}>›</button></div></div></section>;
}

function DatasetSourceRecords({ dataset, onBack, onSelectRecord }: { dataset: DatasetRow; onBack: () => void; onSelectRecord: (record: DataRecord) => void }) {
  const [rows, setRows] = useState<DataRecord[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const pageSize = 20;
  useEffect(() => { setPage(1); }, [query]);
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    listWelds({ dataset_id: dataset.numericId, q: query.trim() || undefined, page, page_size: pageSize })
      .then((result) => { if (!cancelled) { setRows(result.items); setTotal(result.total); setError(null); } })
      .catch((err) => { if (!cancelled) { setError(err instanceof Error ? err.message : '数据列表加载失败'); setRows([]); setTotal(0); } })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [dataset.numericId, page, query]);
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  return <section className="dataset-records"><div className="dataset-breadcrumb">数据中心 / 数据集 / {dataset.name} / 全部数据</div><div className="dataset-context-card"><div><span>数据集</span><strong>{dataset.name}</strong><small>{dataset.task} · {dataset.id}</small></div><div><span>全部数据</span><strong>{total.toLocaleString()}</strong></div><div><span>版本策略</span><strong>新数据自动生成版本</strong></div><div className="dataset-summary-links"><button className="ghost-button" onClick={onBack}><ChevronLeft size={14} />返回概览</button></div></div><div className="dataset-records-header"><div><h2>全部数据样本</h2><p>这里展示该数据集下所有已登记数据，不要求先创建数据集版本。</p></div><div className="data-filter-strip"><div className="filter-field keyword"><label>关键词</label><div className="inline-search"><Search size={14} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="焊缝 ID、名称或登记编号" /></div></div></div></div>{error && <p className="dataset-empty-state" role="alert">{error}，请刷新后重试。</p>}{rows.length ? <div className="dataset-records-table"><div className="dataset-record-row dataset-record-head"><span>焊缝 / 登记编号</span><span>来源 / 焊机</span><span>数据模态</span><span>核验状态</span><span>当前数据版本</span><span>采集时间</span></div>{rows.map((row) => <button className="dataset-record-row" key={row.weld_id} onClick={() => onSelectRecord(row)}><span><strong>{row.weld_id}</strong><small>{row.weld_name ?? '未命名'} · {row.registration_no}</small></span><span>{row.source ?? '—'}<small>{row.machine ?? '—'}</small></span><span>{(row.modalities ?? []).join(' / ') || '—'}</span><StatusPill tone={row.quality === '异常' ? 'red' : row.quality === '待复核' ? 'orange' : 'green'}>{row.quality ?? '未核验'}</StatusPill><span>{row.latest_version?.version_no ?? '—'}</span><span>{fmtDT(row.created_at)}</span></button>)}</div> : loading ? <p className="dataset-empty-state" role="status">数据样本加载中…</p> : <p className="dataset-empty-state">该数据集下暂无登记数据。</p>}<div className="table-footer"><span>共 {total} 条</span><div className="pagination"><button disabled={page === 1} onClick={() => setPage((value) => value - 1)}>‹</button><span>{page} / {totalPages}</span><button disabled={page === totalPages} onClick={() => setPage((value) => value + 1)}>›</button></div></div></section>;
}

function RawSignalPreview({ weldId, versionId, navigate, setSelectedDataId }: { weldId: string; versionId: number; navigate: (route: Route) => void; setSelectedDataId: (id: string | null) => void }) {
  // 初始为空；真实信号加载失败时不再回落到合成波形，避免误导用户。
  const [channels, setChannels] = useState<Chan[]>([]);
  const [signalDuration, setSignalDuration] = useState(dur);
  const [hover, setHover] = useState<{ left: number; top: number; time: number } | null>(null);
  const [active, setActive] = useState<Set<string>>(new Set(['cur', 'vol', 'gas']));
  const [signalError, setSignalError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const toggle = (id: string) => setActive((prev) => { const next = new Set(prev); if (next.has(id)) next.delete(id); else next.add(id); return next; });
  useEffect(() => {
    let cancelled = false;
    // 换焊缝/换版本先清空旧波形再拉取：否则旧数据会一直渲染到新响应返回，造成"闪一下旧图"
    setChannels([]);
    setSignalDuration(dur);
    setHover(null);
    setSignalError(null);
    setLoading(true);
    getSignals(weldId, String(versionId), { channels: ['cur', 'vol', 'gas', 'wir'] })
      .then((data) => { if (!cancelled) { setSignalDuration(data.duration || dur); setChannels(data.channels.map(toChan)); } })
      .catch((err) => { if (!cancelled) { setChannels([]); setSignalError('信号暂时无法读取，请稍后重试。'); console.warn('[datasets] raw signal preview failed', err); } })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [weldId, versionId]);
  const visibleChannels = channels.filter((channel) => active.has(channel.id));
  const handleHover = (event: React.MouseEvent<SVGSVGElement>) => {
    if (!channels.length) return;
    const svgRect = event.currentTarget.getBoundingClientRect();
    const chartRect = event.currentTarget.parentElement?.getBoundingClientRect() ?? svgRect;
    const svgX = clamp(((event.clientX - svgRect.left) / svgRect.width) * CH, AXIS_L, CH);
    const time = ((svgX - AXIS_L) / PLOT_W) * signalDuration;
    setHover({ left: event.clientX - chartRect.left, top: event.clientY - chartRect.top, time });
  };
  const cursorX = hover ? AXIS_L + (hover.time / signalDuration) * PLOT_W : 0;
  return <section className="panel raw-signal-preview"><div className="panel-heading"><div><h2>原始数据预览</h2><p>基于当前数据版本的多通道时域波形，可用于快速确认数据是否正常。</p></div><div className="raw-signal-meta"><span>{loading ? '信号加载中' : signalError ? '信号不可用' : '真实信号'}</span><small>版本 #{versionId}</small></div></div><div className="raw-channel-toggles">{channels.map((channel) => <button key={channel.id} className={active.has(channel.id) ? 'active' : ''} onClick={() => toggle(channel.id)}><i style={{ background: channel.color }} />{channel.name}<small>{channel.unit}</small>{active.has(channel.id) && <Check size={12} />}</button>)}</div><div className="raw-signal-chart" onMouseLeave={() => setHover(null)}>{loading && !channels.length ? <p className="dataset-empty-state" role="status">波形加载中…</p> : signalError ? <p className="dataset-empty-state" role="alert">{signalError}</p> : <><svg viewBox={`0 0 ${CH} ${CW}`} preserveAspectRatio="none" role="img" aria-label="原始多通道信号波形" onMouseMove={handleHover}>{[0, .25, .5, .75, 1].map((position) => <line key={position} x1={AXIS_L} y1={PLOT_H * position} x2={CH} y2={PLOT_H * position} stroke="#edf2f2" />)}{visibleChannels.map((channel) => <path key={channel.id} d={toPath(channel.values, channel.lo, channel.hi)} fill="none" stroke={channel.color} strokeWidth={channel.id === 'cur' ? 2 : 1.6} />)}{hover && <line x1={cursorX} y1={0} x2={cursorX} y2={PLOT_H} stroke="#d16f69" strokeWidth="1.5" strokeDasharray="4 3" />}</svg>{hover && <div className="raw-signal-tooltip" style={{ left: hover.left, top: hover.top }}><strong>{fmt(hover.time)}</strong>{visibleChannels.map((channel) => { const i = Math.min(channel.values.length - 1, Math.max(0, Math.round((hover.time / signalDuration) * Math.max(channel.values.length - 1, 0)))); return <span key={channel.id}><i style={{ background: channel.color }} />{channel.name}<b>{channel.values[i]?.toFixed(3)} {channel.unit}</b></span>; })}</div>}<div className="raw-signal-axis"><span>0s</span><span>1s</span><span>2s</span><span>3s</span><span>4s</span><span>{signalDuration.toFixed(2)}s</span></div></>}</div><div className="raw-signal-footer"><span><Waves size={14} />电流 / 电压 / 气体流量 / 送丝速度</span><button className="outline-button" onClick={() => { setSelectedDataId(weldId); navigate('analysis/analysis'); }}>进入完整信号分析 <ArrowUpRight size={14} /></button></div></section>;
}

const EMPTY_OBJECT_KEYS: string[] = [];

function RawMediaPreview({ objectKeys, loading = false }: { objectKeys: string[]; loading?: boolean }) {
  const [urls, setUrls] = useState<{ key: string; sourceKey: string; url: string; preview?: boolean }[]>([]);
  const [processing, setProcessing] = useState(false);
  const [mediaError, setMediaError] = useState<string | null>(null);
  const [brokenKeys, setBrokenKeys] = useState<Set<string>>(new Set());
  const [refresh, setRefresh] = useState(0);
  const mediaKeys = useMemo(() => objectKeys.filter((key) => /\.(mp4|avi|mkv|mov|webm|jpg|jpeg|png|webp|bmp|gif)$/i.test(key)), [objectKeys]);
  useEffect(() => {
    let cancelled = false;
    let retry: ReturnType<typeof setTimeout> | undefined;
    let isProcessing = false;
    setUrls([]);
    setProcessing(false);
    setMediaError(null);
    setBrokenKeys(new Set());
    Promise.all(mediaKeys.map(async (key) => {
      try {
        const result = await getFileUrl(key);
        if (result.processing) isProcessing = true;
        // The URL endpoint may transparently resolve a raw video to a generated
        // browser preview. Keep the source key so the raw video can be hidden
        // when a playable preview is available.
        return { key: result.object_key ?? key, sourceKey: key, url: result.url, preview: result.preview };
      }
      catch (err) { console.warn('[datasets] media file url failed', key, err); return null; }
    }))
      .then((results) => results.filter((item): item is NonNullable<typeof item> => item !== null))
      .then((next) => {
        if (cancelled) return;
        const isVideo = (key: string) => /\.(mp4|avi|mkv|mov|webm)$/i.test(key);
        const isPreview = (item: { key: string; sourceKey: string; preview?: boolean }) =>
          item.preview === true || item.key !== item.sourceKey || /(?:^|[./_-])preview(?:[./_-])/i.test(item.key);
        const hasBrowserPreview = next.some((item) => isVideo(item.key) && isPreview(item));
        const visible = hasBrowserPreview
          ? next.filter((item) => !isVideo(item.key) || isPreview(item))
          : next;
        // A raw request can resolve to the same preview key as an explicit
        // *.preview.mp4 object. Avoid rendering the preview twice.
        const deduped = visible.filter((item, index, all) =>
          all.findIndex((candidate) => candidate.key === item.key && candidate.url === item.url) === index,
        );
        setUrls(deduped);
        setProcessing(isProcessing);
        if (!deduped.length && mediaKeys.length && !isProcessing) setMediaError('图片或视频地址暂时无法读取');
        if (isProcessing) retry = setTimeout(() => { if (!cancelled) setRefresh((value) => value + 1); }, 2000);
      })
      .catch((err) => { if (!cancelled) { setMediaError('图片或视频地址暂时无法读取'); console.warn('[datasets] media preview failed', err); } });
    return () => { cancelled = true; if (retry) clearTimeout(retry); };
  }, [objectKeys, mediaKeys, refresh]);
  const visibleUrls = urls.filter(({ key }) => !brokenKeys.has(key));
  const mediaLoading = loading || processing;
  if (mediaLoading) return <section className="panel raw-media-preview"><div className="panel-heading"><div><h2>视频 / 图片预览</h2><p>正在读取当前焊缝的真实媒体文件…</p></div></div><div className="raw-media-empty" role="status"><ImageIcon size={28} /><strong>媒体加载中</strong><span>请稍候</span></div></section>;
  if (!visibleUrls.length) return <section className="panel raw-media-preview"><div className="panel-heading"><div><h2>视频 / 图片预览</h2><p>{mediaError ?? '当前焊缝没有已关联的图片或视频文件。'}</p></div></div><div className="raw-media-empty" role={mediaError ? 'alert' : undefined}><ImageIcon size={28} /><strong>{mediaError ? '媒体暂时无法预览' : '暂无图片或视频'}</strong><span>{mediaError ? '请检查对象存储连接后点击重试。' : '该焊缝仍可查看时序信号和其他数据详情。'}</span>{mediaError && <button className="outline-button" onClick={() => setRefresh((value) => value + 1)}><RefreshCw size={14} />重试</button>}</div></section>;
  return <section className="panel raw-media-preview"><div className="panel-heading"><div><h2>视频 / 图片预览</h2><p>使用当前焊缝版本中的真实文件。</p></div></div><div className="raw-media-grid">{visibleUrls.map(({ key, url }) => /\.(mp4|avi|mkv|mov|webm)$/i.test(key) ? <video key={key} src={url} controls preload="metadata" onError={() => { setMediaError('媒体文件加载失败'); setBrokenKeys((prev) => new Set(prev).add(key)); }} /> : <img key={key} src={url} alt={`真实数据 ${key}`} onError={() => { setMediaError('媒体文件加载失败'); setBrokenKeys((prev) => new Set(prev).add(key)); }} />)}</div></section>;
}

function DatasetRecordDetail({ weldId, dataset, versionId, split, onBack, setSelectedDataId, navigate }: { weldId: string; dataset: DatasetRow; versionId: number; split: 'train' | 'val' | 'test' | null; onBack: () => void; setSelectedDataId: (id: string | null) => void; navigate: (route: Route) => void }) {
  const [record, setRecord] = useState<DataRecord | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    setSelectedDataId(weldId);
    setRecord(null);
    setError(null);
    getWeld(weldId).then((value) => { if (!cancelled) setRecord(value); })
      .catch((err) => { if (!cancelled) { setError('焊缝详情加载失败，请返回成员列表后重试。'); console.warn('[datasets] getWeld failed', err); } });
    return () => { cancelled = true; };
  }, [weldId, setSelectedDataId]);
  const qualityTone = record?.quality === '异常' ? 'red' : record?.quality === '待复核' ? 'orange' : 'green';
  const splitText = split ? splitLabel[split] : '尚未进入版本切分';
  return <section className="dataset-record-detail"><div className="dataset-breadcrumb">数据中心 / 数据集列表 / {dataset.name} / 数据详情 / {weldId}</div><button className="ghost-button" onClick={onBack}><ChevronLeft size={14} />返回数据列表</button><div className="dataset-context-card"><div><span>焊缝 ID</span><strong>{weldId}</strong></div><div><span>所属数据集</span><strong>{dataset.name}</strong></div><div><span>所属版本</span><strong>#{versionId}</strong></div><div><span>数据划分</span><strong>{splitText}</strong></div></div>{error && <p className="dataset-empty-state" role="alert">{error}</p>}<RawMediaPreview objectKeys={record?.latest_version?.object_keys ?? EMPTY_OBJECT_KEYS} loading={!record && !error} /><RawSignalPreview weldId={weldId} versionId={record?.latest_version_id ?? record?.latest_version?.id ?? versionId} navigate={navigate} setSelectedDataId={setSelectedDataId} /><div className="dataset-detail-columns"><section className="panel"><h2>数据详情</h2><InfoRow label="所属数据集" value={dataset.name} /><InfoRow label="所属版本" value={`版本 #${versionId}`} /><InfoRow label="数据划分" value={splitText} /><InfoRow label="焊缝 ID" value={record?.weld_id ?? weldId} /><InfoRow label="登记编号" value={record?.registration_no ?? '加载中…'} /><InfoRow label="当前版本" value={record?.latest_version?.version_no ?? '加载中…'} /><InfoRow label="核验状态" value={record?.quality ?? '加载中…'} accent={!!record} />{record && <><InfoRow label="数据来源" value={record.source} /><InfoRow label="焊机" value={record.machine ?? '—'} /><InfoRow label="数据模态" value={record.modalities.join(' / ') || '—'} /></>}</section><section className="panel"><h2>继续处理</h2><StatusPill tone={qualityTone}>{record?.quality ?? '加载中'}</StatusPill><button className="quick-action" onClick={() => navigate('data-center/validation')}><ClipboardCheck size={15} />数据核验 <ArrowUpRight size={14} /></button><button className="quick-action" onClick={() => navigate('data-center/versions')}><GitBranch size={14} />数据版本 <ArrowUpRight size={14} /></button><button className="quick-action" onClick={() => navigate('analysis/analysis')}><BarChart3 size={15} />信号分析 <ArrowUpRight size={14} /></button></section></div></section>;
}

function DatasetInputPanel({ task, dims }: { task: string; dims: DimensionStatus[] }) {
  return <section className="panel dataset-input-panel"><div className="panel-heading"><div><h2>输入数据维度</h2><p>字段是否存在由采集情况决定，训练资格按当前任务动态判断。</p></div><span className="dataset-task-tag">{task}</span></div>{dims.length ? <div className="dimension-grid">{dims.map((dim) => { const isRequired = dim.required; const isAvailable = dim.status === '已具备'; return <div className={`dimension-item ${isRequired ? 'required' : ''}`} key={dim.name}><span className="dimension-status">{isAvailable ? <CheckCircle2 size={14} /> : <AlertTriangle size={14} />}</span><div><strong>{dim.name}</strong><small>{isRequired ? '当前任务必需' : isAvailable ? '已具备 · 可选输入' : '缺失 · 不影响当前任务'}</small></div><StatusPill tone={isAvailable ? 'green' : 'orange'}>{isAvailable ? '已具备' : '缺失'}</StatusPill></div>; })}</div> : <p className="dataset-empty-state" role="status">输入维度加载中…</p>}</section>;
}

function ModelReadiness({ task, status, readiness, loading = false }: { task: string; status: string; readiness: ReadinessCheck | null; loading?: boolean }) {
  const ready = readiness?.readiness ?? (status === '可训练' ? '可训练' : '暂不可训练');
  const isTrainable = ready === '可训练';
  // 初始为空：readiness 接口返回前显示加载中，mock 检查项仅作失败兜底（loading=false 且无数据）
  const checks = readiness?.checks ?? (loading ? [] : mockReadinessChecks(task));
  return <section className="panel readiness-panel"><div className="panel-heading"><div><h2>模型适配检查</h2><p>当前数据集按照“{task}”的最低训练要求检查。</p></div><StatusPill tone={isTrainable ? 'green' : 'orange'}>{isTrainable ? '可训练' : '暂不可训练'}</StatusPill></div><div className="readiness-grid">{checks.length ? checks.map((check) => <div key={check.name}>{check.passed ? <CheckCircle2 size={14} /> : <AlertTriangle size={14} />}<span>{check.name}</span></div>) : <p className="dataset-empty-state" role="status">模型适配检查加载中…</p>}</div><div className="split-policy"><GitBranch size={14} /><span>划分策略：按焊缝 ID 分组，避免同一焊缝的视频帧同时出现在训练集和测试集。</span></div></section>;
}

function DatasetTrainingContext() {
  const [ds, setDs] = useState<Dataset | null>(null);
  useEffect(() => {
    let cancelled = false;
    listDatasets().then((list) => { if (!cancelled && list.length) setDs(list.find((d) => d.status === '可训练') ?? list[0]); }).catch((err) => { if (!cancelled) console.warn('[datasets] training context failed', err); });
    return () => { cancelled = true; };
  }, []);
  const name = ds ? `${ds.name} · 快照 ${ds.version ?? '—'}` : '焊接缺陷检测集 · 快照 v1.3';
  const split = ds?.split && ds.split.train !== undefined ? `${ds.split.train.toLocaleString()} / ${(ds.split.val ?? 0).toLocaleString()} / ${(ds.split.test ?? 0).toLocaleString()}` : '6,736 / 842 / 842';
  return <div className="model-dataset-context"><div className="dataset-row-icon"><Box size={16} /></div><div><span>当前训练数据集快照</span><strong>{name}</strong></div><div><span>训练 / 验证 / 测试</span><strong>{split}</strong></div><StatusPill>{ds?.status ?? '可训练'}</StatusPill><button className="ghost-button">更换数据集 <ChevronDown size={13} /></button></div>;
}
function DatasetTestingContext() {
  const [ds, setDs] = useState<Dataset | null>(null);
  useEffect(() => {
    let cancelled = false;
    listDatasets().then((list) => { if (!cancelled) setDs(list.find((item) => item.current_version_id != null) ?? null); }).catch((err) => { if (!cancelled) console.warn('[datasets] testing context failed', err); });
    return () => { cancelled = true; };
  }, []);
  const name = ds ? `${ds.name} · 快照 ${ds.version ?? '—'}` : '尚未选择数据集快照';
  const testCount = ds?.split?.test !== undefined ? ds.split.test.toLocaleString() : '—';
  return <div className="model-dataset-context"><div className="dataset-row-icon"><Box size={16} /></div><div><span>当前测试数据集快照</span><strong>{name}</strong></div><div><span>固定测试集</span><strong>{testCount === '—' ? '—' : `${testCount} 条样本`}</strong></div>{ds?.current_version_id != null ? <StatusPill>固定快照</StatusPill> : <StatusPill tone="orange">待选择</StatusPill>}<span className="form-help">请在下方测试配置中选择</span></div>;
}

/** 选择数据卡片展示形状（selection-card 期望的字段，由 DataRecord 派生）。 */
interface SelectCard { id: string; machine: string | null; types: string; quality: string; title: string | null; }
function toSelectCard(r: DataRecord): SelectCard {
  return { id: r.weld_id, machine: r.machine, types: (r.modalities ?? []).join(' / ') || '多模态', quality: r.quality, title: r.weld_name };
}
function AnalysisSelect({ onContinue, selectedDatasetId, setSelectedDatasetId }: { onContinue: (id: string) => void; selectedDatasetId: number | null; setSelectedDatasetId: (id: number | null) => void }) {
  const [datasetOptions, setDatasetOptions] = useState<{ id: number; label: string }[]>([]);
  const [weldRows, setWeldRows] = useState<SelectCard[]>([]);
  const [loadingWeld, setLoadingWeld] = useState(false);
  // 第一级：数据集下拉（数据集为登记时的归属容器，分析以其为入口）。
  useEffect(() => {
    let cancelled = false;
    const fallback = () => mockDatasetRows.map((row, index) => ({ id: index + 1, label: row.name }));
    listDatasets()
      .then((list) => {
        if (cancelled) return;
        const options = list.map((d) => ({ id: d.id, label: d.name }));
        setDatasetOptions(options.length ? options : fallback());
        setSelectedDatasetId(selectedDatasetId ?? options[0]?.id ?? fallback()[0]?.id ?? null);
      })
      .catch((err) => {
        if (cancelled) return;
        console.warn('[analysis] listDatasets failed', err);
        const options = fallback();
        setDatasetOptions(options);
        setSelectedDatasetId(selectedDatasetId ?? options[0]?.id ?? null);
      });
    return () => { cancelled = true; };
  }, [selectedDatasetId, setSelectedDatasetId]);
  // 第二级：选定数据集后拉该数据集下全部焊缝，未核验通过置灰不可选。
  useEffect(() => {
    if (selectedDatasetId == null) { setWeldRows([]); return; }
    let cancelled = false;
    setLoadingWeld(true);
    listWelds({ dataset_id: selectedDatasetId, page_size: 50 })
      .then((res) => { if (!cancelled) setWeldRows(res.items.map(toSelectCard)); })
      .catch((err) => {
        if (cancelled) return;
        console.warn('[analysis] listWelds by dataset failed', err);
        setWeldRows(mockWeldRows.map((r) => ({ id: r.id, machine: r.machine, types: r.types, quality: r.quality, title: null })));
      })
      .finally(() => { if (!cancelled) setLoadingWeld(false); });
    return () => { cancelled = true; };
  }, [selectedDatasetId]);
  return <div className="selection-workspace"><div className="selection-hero"><div className="selection-icon"><Waves size={25} /></div><div><h2>选择数据集，再选择一条焊缝开始分析</h2><p>先选定数据集，再在数据集内选择焊缝进入多模态分析流程；核验异常的焊缝置灰不可选，待复核焊缝可直接进入。</p></div></div><div className="selection-dataset-bar"><label className="filter-field">所属数据集<select value={selectedDatasetId ?? ''} onChange={(event) => setSelectedDatasetId(Number(event.target.value))}>{datasetOptions.map((option) => <option value={option.id} key={option.id}>{option.label}</option>)}</select></label></div>{selectedDatasetId == null ? <p className="selection-empty">正在加载数据集…</p> : loadingWeld ? <p className="selection-empty">正在加载该数据集的焊缝…</p> : weldRows.length ? <div className="selection-grid">{weldRows.map((row) => <button className={`selection-card ${row.quality === '异常' ? 'disabled' : ''}`} disabled={row.quality === '异常'} onClick={() => onContinue(row.id)} key={row.id} title={row.quality === '异常' ? '该焊缝核验异常，不可进入分析' : undefined}><div><span className="file-badge"><Archive size={14} />{row.id}</span><h3>{row.title ?? '未命名焊缝'}</h3><p>{row.machine ?? '—'} · {row.types}</p></div><StatusPill tone={row.quality === '通过' ? 'green' : row.quality === '异常' ? 'red' : 'orange'}>{row.quality === '通过' ? '核验通过' : row.quality}</StatusPill></button>)}</div> : <p className="selection-empty">该数据集暂无数据，请先在数据中心上传数据。</p>}</div>;
}

function VersionPanel({ dataId }: { dataId?: string }) {
  // 初始为空 + 加载中：不得闪现 mock 版本链（v1.0-v1.3），失败时显示明确不可用状态
  const [versions, setVersions] = useState<DataVersion[]>([]);
  const [versionsLoading, setVersionsLoading] = useState(true);
  const [versionsUnavailable, setVersionsUnavailable] = useState(false);
  const [selectedVersionId, setSelectedVersionId] = useState<string | null>(null);
  const [currentVersionId, setCurrentVersionId] = useState<number | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [validating, setValidating] = useState<number | null>(null);
  const reload = useCallback(() => {
    if (!dataId) return Promise.resolve();
    setVersionsLoading(true);
    setVersionsUnavailable(false);
    return Promise.all([listVersions(dataId), getWeld(dataId)]).then(([list, weld]) => {
      setVersions(list);
      setCurrentVersionId(weld.latest_version_id ?? weld.latest_version?.id ?? null);
    }).catch((err) => {
      setVersionsUnavailable(true);
      console.warn('[versions] listVersions failed', err);
    }).finally(() => setVersionsLoading(false));
  }, [dataId]);
  useEffect(() => {
    if (!dataId) { setVersionsLoading(false); return; }
    reload().catch(() => undefined);
  }, [dataId, reload]);
  const currentVersion = versions.find((version) => version.id === currentVersionId) ?? versions[versions.length - 1];
  const handleCreate = async (payload: { action: '去噪处理' | '人工修正'; note?: string; file?: File }) => {
    if (!dataId || creating) return;
    setCreating(true);
    setNotice(null);
    try {
      let object_keys: string[] | undefined;
      if (payload.file) {
        const uploaded = await presignUpload({
          size: payload.file.size,
          content_type: payload.file.type || 'application/octet-stream',
          prefix: `processed/${dataId}`,
          filename: payload.file.name,
        });
        await putFileDirect(uploaded.upload_url, payload.file);
        object_keys = [uploaded.object_key];
      }
      await createVersion(dataId, { action: payload.action, note: payload.note, object_keys });
      setShowCreate(false);
      setNotice('新版本已创建，请执行核验后再用于分析或训练。');
      await reload();
    } catch (err) {
      setNotice(err instanceof Error ? err.message : '新建数据版本失败，请重试。');
    } finally {
      setCreating(false);
    }
  };
  const handleValidation = async (versionId: number) => {
    if (!dataId || validating != null) return;
    setValidating(versionId);
    setNotice(null);
    try {
      const report = await runValidation(dataId, String(versionId));
      setNotice(`${versions.find((v) => v.id === versionId)?.version_no ?? '该版本'}核验完成：${report.score.toFixed(1)} 分。`);
      await reload();
    } catch (err) {
      setNotice(err instanceof Error ? err.message : '版本核验失败，请重试。');
    } finally {
      setValidating(null);
    }
  };
  return <><section className="panel version-panel"><div className="panel-heading"><div><h2>数据版本</h2><p>原始数据与加工结果的不可覆盖版本链路</p></div><div className="toolbar-actions"><StatusPill>当前版本 {currentVersion?.version_no ?? '—'}</StatusPill><button className="primary-button" onClick={() => setShowCreate(true)} disabled={!dataId || creating}><Plus size={14} />新建数据版本</button></div></div>{notice && <p className="toolbar-error" role="status">{notice}</p>}{versionsLoading ? <p className="dataset-empty-state" role="status">版本链路加载中…</p> : versionsUnavailable ? <p className="dataset-empty-state" role="alert">版本信息暂时无法读取，请稍后重试。</p> : versions.length ? <div className="version-line">{versions.map((version) => <div className={version.id === currentVersionId ? 'current' : ''} key={`${version.version_no}-${version.id}`}><i /><span>{`${version.version_no} ${version.action}`}<small>{fmtDT(version.created_at)} · {version.operator ?? '—'}</small></span><div className="toolbar-actions"><button className="ghost-button" onClick={() => setSelectedVersionId(String(version.id))}>查看</button><button className="outline-button" disabled={validating === version.id} onClick={() => handleValidation(version.id)}>{validating === version.id ? '核验中…' : '执行核验'}</button></div></div>)}</div> : <p className="dataset-empty-state">该焊缝暂无版本数据。</p>}</section>{showCreate && <VersionCreateDialog baseVersion={currentVersion?.version_no} creating={creating} onCancel={() => setShowCreate(false)} onConfirm={handleCreate} />}{selectedVersionId && <VersionDetailDrawer mode="weld" weldId={dataId ?? ''} versionId={selectedVersionId} onClose={() => setSelectedVersionId(null)} />}</>;
}

function VersionCreateDialog({ baseVersion, creating, onCancel, onConfirm }: { baseVersion?: string; creating: boolean; onCancel: () => void; onConfirm: (payload: { action: '去噪处理' | '人工修正'; note?: string; file?: File }) => void }) {
  const [action, setAction] = useState<'去噪处理' | '人工修正'>('去噪处理');
  const [note, setNote] = useState('');
  const [file, setFile] = useState<File | undefined>();
  return <div className="app-dialog-backdrop" role="presentation" onClick={onCancel}><section className="app-dialog" role="dialog" aria-modal="true" aria-label="新建数据版本" onClick={(event) => event.stopPropagation()}><div className="app-dialog-head"><div><h2>新建数据版本</h2><p>基于 {baseVersion ?? '当前版本'} 创建，不会覆盖历史版本。</p></div><button className="icon-button" onClick={onCancel} aria-label="关闭">×</button></div><div className="form-block"><label>处理动作</label><select className="native-select" value={action} onChange={(event) => setAction(event.target.value as '去噪处理' | '人工修正')}><option value="去噪处理">去噪处理</option><option value="人工修正">人工修正</option></select></div><div className="form-block"><label>版本说明</label><textarea className="input-field" rows={3} placeholder="说明本次处理内容、参数或修正原因" value={note} onChange={(event) => setNote(event.target.value)} /></div><div className="form-block"><label>加工后文件（可选）</label><input type="file" onChange={(event) => setFile(event.target.files?.[0])} /><small className="form-help">文件将保存到 processed/{'{焊缝ID}'}，并挂载到新版本。</small></div><div className="dialog-actions"><button className="ghost-button" onClick={onCancel} disabled={creating}>取消</button><button className="primary-button" onClick={() => onConfirm({ action, note: note.trim() || undefined, file })} disabled={creating}>{creating ? '创建中…' : '创建版本'}</button></div></section></div>;
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
  return <div className="model-repository"><section className="model-repository-hero"><div className="model-repository-hero-icon"><Cpu size={25} /></div><div className="model-repository-hero-copy"><span className="eyebrow"><i />模型资产管理</span><h2>让每个模型版本都可追踪、可评估、可发布</h2><p>模型资产统一承接模型登记、版本管理、指标评估、权重导出和推理验证。</p></div><button className="primary-button" onClick={() => navigate('model-center/training')}><Play size={15} />开始一次训练</button></section><div className="model-workflow"><div><span>01</span><strong>登记模型</strong><small>建立模型条目</small></div><i>→</i><div><span>02</span><strong>训练版本</strong><small>关联数据集快照</small></div><i>→</i><div><span>03</span><strong>测试评估</strong><small>查看指标与混淆矩阵</small></div><i>→</i><div><span>04</span><strong>发布推理</strong><small>晋级生产并验证样本</small></div></div><div className="repository-summary"><div><span>模型总数</span><strong>{summary?.total ?? '—'}</strong></div><div><span>生产候选</span><strong>{summary?.prod_candidates ?? '—'}</strong></div><div><span>最近训练</span><strong>{summary?.recent_training ? fmtDT(summary.recent_training) : '—'}</strong></div></div>{notice && <p className="toolbar-error" role="status">{notice}</p>}{repoLoading ? <p className="dataset-empty-state" role="status">模型资产加载中…</p> : models.length ? <div className="model-card-grid">{models.map((model) => <section className="panel model-card" key={model.id}><div className="model-card-top"><div className="model-logo"><Cpu size={17} /></div><StatusPill tone={model.status === '训练中' ? 'orange' : 'green'}>{model.status ?? '无版本'}</StatusPill><MoreHorizontal size={16} className="muted-icon" /></div><h2>{model.name}</h2><p>{model.type} · {model.version ?? '暂无版本'}</p><div className="model-metric"><span>核心指标</span><strong>{modelMetricText(model.metric)}</strong></div><div className="model-card-footer"><span>{model.description ?? '暂无模型描述'}</span><button className="ghost-button" onClick={() => openDetail(model)}>查看详情 <ArrowUpRight size={13} /></button></div></section>)}</div> : <><div className="model-catalog-heading"><div><h2>标准模型目录</h2><p>平台预留的三类模型能力入口，训练完成后会在这里生成版本。</p></div><button className="outline-button" onClick={() => navigate('model-center/training')}><Plus size={14} />新建训练任务</button></div><div className="model-catalog-grid">{modelCatalog.map(({ name, type, description, icon: Icon }) => <section className="panel model-catalog-card" key={name}><div className="model-catalog-icon"><Icon size={20} /></div><StatusPill tone="blue">待接入版本</StatusPill><h3>{name}</h3><span>{type}</span><p>{description}</p><button className="ghost-button" onClick={() => navigate('model-center/training')}>去创建版本 <ArrowUpRight size={13} /></button></section>)}</div></>}{selectedModel && <div className="app-dialog-backdrop" role="presentation" onClick={() => setSelectedModel(null)}><section className="app-dialog model-detail-dialog" role="dialog" aria-modal="true" aria-label="模型详情" onClick={(event) => event.stopPropagation()}><div className="app-dialog-head"><div><h2>{selectedModel.name}</h2><p>{selectedModel.type} · {selectedModel.description ?? '暂无描述'}</p></div><button className="icon-button" onClick={() => setSelectedModel(null)} aria-label="关闭">×</button></div>{detailLoading ? <p className="dataset-empty-state">详情加载中…</p> : <div className="model-version-list">{selectedModel.versions?.length ? selectedModel.versions.map((version) => <div className="model-version-row" key={version.id}><div><strong>{version.version_no}</strong><span>{version.status} · {modelMetricText(version.metric)}</span><small>{version.created_at ? fmtDT(version.created_at) : '暂无创建时间'}</small></div><div className="model-version-actions"><button className="outline-button" disabled={!version.file_key || exporting === version.id} onClick={() => handleExport(version)}><Download size={14} />{exporting === version.id ? '导出中…' : '导出 ONNX'}</button>{version.status === '生产候选' ? <button className="ghost-button" disabled={updatingStatus === version.id} onClick={() => handleStatus(version, '实验版本')}>{updatingStatus === version.id ? '更新中…' : '退回实验版'}</button> : <button className="ghost-button" disabled={updatingStatus === version.id} onClick={() => handleStatus(version, '生产候选')}>{updatingStatus === version.id ? '更新中…' : '设为生产候选'}</button>}</div></div>) : <p className="dataset-empty-state">该模型暂无版本。</p>}</div>}</section></div>}</div>;
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

function Toolbar({ action, secondary, onAction, onRefresh, actionDisabled = false, exportType, exportRefIds }: { action?: string; secondary?: string; onAction?: () => void; onRefresh?: () => void; actionDisabled?: boolean; exportType?: string; exportRefIds?: unknown[] }) {
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  const handleExport = () => {
    if (!exportType || exporting) return;
    setExportError(null);
    const popup = window.open('', '_blank');
    setExporting(true);
    exportReport({ type: exportType, ref_ids: exportRefIds ?? [], format: 'pdf' })
      .then((res) => {
        const url = res.urls?.[0]?.url;
        if (!url) throw new Error('empty export URL');
        if (popup && !popup.closed) popup.location.href = url;
        else window.location.href = url;
      })
      .catch((err) => {
        if (popup && !popup.closed) popup.close();
        setExportError('报告导出失败，请稍后重试');
        console.warn('[export] exportReport failed', err);
      })
      .finally(() => setExporting(false));
  };
  return <div className="page-toolbar"><button className="ghost-button" onClick={onRefresh} disabled={!onRefresh}><RefreshCw size={14} />刷新</button>{secondary && <button className="outline-button" onClick={handleExport} disabled={exporting}><Download size={14} />{exporting ? '导出中…' : secondary}</button>}{action && <button className="primary-button" onClick={onAction} disabled={actionDisabled || !onAction}><Plus size={15} />{action}</button>}{exportError && <span className="toolbar-error" role="alert">{exportError}</span>}</div>;
}

function StatusPill({ children, tone = 'green' }: { children: React.ReactNode; tone?: 'green' | 'orange' | 'red' | 'blue' | 'muted' }) {
  return <span className={`status ${tone}`}>{children}</span>;
}

function TextDialog({ title, label, initialValue = '', onCancel, onConfirm }: { title: string; label: string; initialValue?: string; onCancel: () => void; onConfirm: (value: string) => void }) {
  const [value, setValue] = useState(initialValue);
  return <div className="app-dialog-backdrop" role="presentation" onClick={onCancel}><div className="app-dialog" role="dialog" aria-modal="true" aria-label={title} onClick={(event) => event.stopPropagation()}><div className="app-dialog-head"><h2>{title}</h2><button className="icon-button" onClick={onCancel} aria-label="关闭">×</button></div><label>{label}<input autoFocus value={value} onChange={(event) => setValue(event.target.value)} onKeyDown={(event) => { if (event.key === 'Escape') onCancel(); if (event.key === 'Enter' && value.trim()) onConfirm(value.trim()); }} /></label><div className="app-dialog-actions"><button className="outline-button" onClick={onCancel}>取消</button><button className="primary-button" disabled={!value.trim()} onClick={() => onConfirm(value.trim())}>确认</button></div></div></div>;
}

const mockWeldRows: WeldRow[] = [
  { id: 'WLD-20260815-0248', time: '2026-08-15 09:42', source: '产线相机 · 03号', machine: 'Fronius CMT', types: '视频 / 时序 / 声音', quality: '通过', version: 'v1.3' },
  { id: 'WLD-20260815-0247', time: '2026-08-15 09:18', source: '实训线 · 02号', machine: 'OTC FD-V8', types: '视频 / 时序', quality: '待复核', version: 'v2.0' },
  { id: 'WLD-20260814-0246', time: '2026-08-14 18:32', source: '产线相机 · 03号', machine: 'Kemppi Minarc', types: '视频 / 时序 / 红外', quality: '通过', version: 'v1.1' },
  { id: 'WLD-20260814-0245', time: '2026-08-14 16:07', source: '实训线 · 01号', machine: 'Panasonic YD-500', types: '视频 / 声音', quality: '异常', version: 'v1.0' },
];

/** 数据列表：每页条数 + tab 演示计数（API 返回后 active tab 显示响应 total）。 */
const PAGE_SIZE = 10;

/** 上传数据：分类型上传区配置（CSV / 图片 / 视频 / WAV 各自独立）。 */
type UploadZoneKey = 'csv' | 'image' | 'video' | 'audio';
const UPLOAD_ZONES: { key: UploadZoneKey; label: string; accept: string; hint: string }[] = [
  { key: 'csv', label: '时序数据（CSV）', accept: '.csv', hint: '支持 .csv 时序信号' },
  { key: 'image', label: '图片', accept: 'image/png,image/jpeg,image/webp,image/bmp', hint: '支持 png / jpg / webp / bmp' },
  { key: 'video', label: '视频', accept: 'video/*', hint: '支持 mp4 / mov / avi 等' },
  { key: 'audio', label: '音频（WAV）', accept: '.wav,audio/wav', hint: '支持 .wav 音频' },
];

/** 当前本地时间 → datetime-local 输入值（YYYY-MM-DDTHH:mm），用于采集时间默认值。 */
const toLocalInputValue = (d: Date) => {
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
};

function Registration() {
  const [registered, setRegistered] = useState(false);
  const [regNo, setRegNo] = useState('REG-20260815-00249');
  const [regError, setRegError] = useState<string | null>(null);
  // 提交中（登记 + 逐文件直传 + 挂载）标志：期间按钮呈禁用态且忽略点击。
  const [submitting, setSubmitting] = useState(false);
  // 各上传区锚定的 File（选择即锚定，不发起网络请求；点"上传数据"才统一直传）。
  const [files, setFiles] = useState<Partial<Record<UploadZoneKey, File>>>({});
  // 各上传区状态：pending（已锚定待上传）/ uploading（带进度%）/ done / error。
  const [uploads, setUploads] = useState<Partial<Record<UploadZoneKey, { status: 'pending' | 'uploading' | 'done' | 'error'; fileName: string; progress?: number; errorMsg?: string } | null>>>({});
  // 缺失必填项提示：点禁用态按钮时列出缺失项（missingHint）并让对应区域红色闪烁（flash）。
  const [missingHint, setMissingHint] = useState<string | null>(null);
  const [flash, setFlash] = useState<Record<string, boolean>>({});
  const flashTimer = useRef<number | undefined>(undefined);
  // 初始为空 + 加载中：mock 行仅在接口失败时兜底，不得在加载期闪现
  const [recentRows, setRecentRows] = useState<WeldRow[]>([]);
  const [recentLoading, setRecentLoading] = useState(true);
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [form, setForm] = useState<RegistrationForm>({ dataset_id: 0, source: '', collected_at: toLocalInputValue(new Date()), weld_name: '', product: '', machine: 'Fronius CMT', weld_method: 'MAG焊', material: '', thickness: '', current_voltage: '', sample_rate: '' });
  // 各上传区的 file input 引用（ref 回调写进同一对象）。
  const fileRefs = useRef<Partial<Record<UploadZoneKey, HTMLInputElement | null>>>({});
  // 部分失败重试时复用已生成的登记，避免重复登记：登记成功即记入 regRef。
  const regRef = useRef<{ id: number | string; registration_no: string } | null>(null);
  // 是否已锚定至少一个文件（派生值，驱动按钮启用）。
  const hasFile = Object.values(files).some(Boolean);
  const setField = (key: keyof RegistrationForm) => (event: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setForm((prev) => ({ ...prev, [key]: event.target.value }));
  useEffect(() => {
    let cancelled = false;
    Promise.all([listDatasets(), listWelds({ tab: 'recent' })]).then(([datasetList, res]) => {
      if (cancelled) return;
      setDatasets(datasetList);
      // 上传是有副作用的新建操作，不应在用户未确认归属前自动选中第一个数据集。
      // 保持占位项，强制用户明确选择目标数据集，避免误归属。
      setRecentRows(res.items.slice(0, 5).map((r) => ({ ...toWeldRow(r), time: (r.collected_at ?? r.created_at ?? '').replace('T', ' ').slice(0, 16) })));
    }).catch((err) => { if (!cancelled) { setRecentRows(mockWeldRows.slice(0, 3)); console.warn('[registration] registration context failed', err); } })
      .finally(() => { if (!cancelled) setRecentLoading(false); });
    return () => { cancelled = true; };
  }, []);
  // 提交：登记（部分失败重试时复用 regRef）→ 逐文件预签名直传 MinIO（进度按区回显）→ 统一挂载。
  const handleSubmit = async () => {
    if (registered || submitting) return;
    setRegError(null);
    setSubmitting(true);
    try {
      const reg = regRef.current ?? await createRegistration(form);
      regRef.current = reg;
      const keys: string[] = [];
      for (const zone of UPLOAD_ZONES) {
        const file = files[zone.key];
        if (!file) continue;
        setUploads((prev) => ({ ...prev, [zone.key]: { status: 'uploading', fileName: file.name, progress: 0 } }));
        try {
          // 统一预签名直传（跳过后端代理：实测吞吐 ~2×，XHR 可回显进度）。
          // prefix 用 raw/（业务原始文件区）——不要用 uploads/（有 30 天生命周期清理）。
          const { object_key, upload_url } = await presignUpload({ size: file.size, content_type: file.type || 'application/octet-stream', prefix: 'raw', filename: file.name });
          await putFileDirect(upload_url, file, (percent) => setUploads((prev) => ({ ...prev, [zone.key]: { status: 'uploading', fileName: file.name, progress: percent } })));
          keys.push(object_key);
          setUploads((prev) => ({ ...prev, [zone.key]: { status: 'done', fileName: file.name } }));
        } catch (err) {
          console.warn('[registration] file upload failed', err);
          setUploads((prev) => ({ ...prev, [zone.key]: { status: 'error', fileName: file.name } }));
          throw new Error(`文件 ${file.name} 上传失败，请重试`);
        }
      }
      try {
        await attachRawFiles(String(reg.id), keys);
      } catch (err) {
        console.warn('[registration] attachRawFiles failed', err);
        throw new Error('文件已上传但关联失败，请重新提交');
      }
      setRegNo(reg.registration_no);
      setRegistered(true);
    } catch (err) {
      setRegError(err instanceof Error && err.message ? err.message : '上传失败，请检查必填项后重试');
    } finally {
      setSubmitting(false);
    }
  };
  // 缺失必填项清单（顺序即表单顺序）：dataset/source/collected_at/weld_name 对应必填输入，file 要求至少选择一个文件。
  const missingFields = [
    { key: 'dataset', label: '所属数据集', ok: !!form.dataset_id },
    { key: 'source', label: '数据来源', ok: !!form.source.trim() },
    { key: 'collected_at', label: '采集时间', ok: !!form.collected_at },
    { key: 'weld_name', label: '焊缝 / 批次名称', ok: !!form.weld_name?.trim() },
    { key: 'file', label: '数据文件（至少选择一个）', ok: hasFile },
  ].filter((item) => !item.ok);
  // 按钮禁用态被点击：提示缺失项 + 对应输入区域红色闪烁约 1.2s。
  const handleMissingClick = () => {
    if (!missingFields.length) return;
    setMissingHint(`请先完善必填信息：${missingFields.map((item) => item.label).join('、')}`);
    setFlash(Object.fromEntries(missingFields.map((item) => [item.key, true])));
    window.clearTimeout(flashTimer.current);
    flashTimer.current = window.setTimeout(() => { setFlash({}); setMissingHint(null); }, 1200);
  };
  useEffect(() => () => window.clearTimeout(flashTimer.current), []);
  const zoneAccepts = (key: UploadZoneKey, file: File): boolean => {
    const name = file.name.toLowerCase();
    switch (key) {
      case 'csv': return name.endsWith('.csv');
      case 'image': return file.type.startsWith('image/') || /\.(png|jpe?g|webp|bmp)$/.test(name);
      case 'video': return file.type.startsWith('video/') || /\.(mp4|mov|avi|mkv|webm)$/.test(name);
      case 'audio': return name.endsWith('.wav') || file.type === 'audio/wav' || file.type === 'audio/x-wav';
    }
  };
  const handleFile = (key: UploadZoneKey, event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    const zone = UPLOAD_ZONES.find((z) => z.key === key);
    if (!zoneAccepts(key, file)) {
      setUploads((prev) => ({ ...prev, [key]: { status: 'error', fileName: file.name, errorMsg: `仅支持 ${zone?.label ?? '该区'}格式` } }));
      return;
    }
    // 选择即锚定：不发起上传，等点"上传数据"统一提交（避免选错文件已白白占用带宽）。
    setFiles((prev) => ({ ...prev, [key]: file }));
    setUploads((prev) => ({ ...prev, [key]: { status: 'pending', fileName: file.name } }));
  };

  return <div className="page-wrap"><PageIntro eyebrow="标准化台账" title="数据上传" description="为每批焊接多模态数据建立统一身份、来源和工艺参数档案。" action={<span className="workflow-chip"><CheckCircle2 size={14} />上传数据即进入数据流程</span>} /><div className="registration-layout"><section className="panel form-panel"><div className="panel-heading"><div><h2>上传数据</h2><p>带 * 的字段为必填项</p></div><span className="draft-tag">上传草稿</span></div><div className="form-section-title"><span>基础信息</span><i /></div><div className="form-grid"><label className={flash.dataset ? 'field-flash' : undefined}><span>所属数据集<span className="required-mark"> *</span></span><select value={form.dataset_id || ''} onChange={(event) => setForm((prev) => ({ ...prev, dataset_id: Number(event.target.value) }))}><option value="">请选择数据集</option>{datasets.map((dataset) => <option value={dataset.id} key={dataset.id}>{dataset.name} · {dataset.dataset_no}</option>)}</select></label><label className={flash.source ? 'field-flash' : undefined}><span>数据来源<span className="required-mark"> *</span></span><input placeholder="例如：产线相机 · 03号" value={form.source} onChange={setField('source')} /></label><label className={flash.collected_at ? 'field-flash' : undefined}><span>采集时间<span className="required-mark"> *</span></span><input type="datetime-local" value={form.collected_at ?? ''} onChange={setField('collected_at')} /></label><label className={flash.weld_name ? 'field-flash' : undefined}><span>焊缝 / 批次名称<span className="required-mark"> *</span></span><input placeholder="输入焊缝或批次名称" value={form.weld_name ?? ''} onChange={setField('weld_name')} /></label><label>关联产品信息<input placeholder="产品型号、零件编号" value={form.product ?? ''} onChange={setField('product')} /></label></div><div className="form-section-title"><span>采集与工艺参数</span><i /></div><div className="form-grid"><label>焊机型号<select value={form.machine ?? ''} onChange={setField('machine')}><option>Fronius CMT</option><option>OTC FD-V8</option><option>Panasonic YD-500</option></select></label><label>焊接方法<select value={form.weld_method ?? ''} onChange={setField('weld_method')}><option>MAG焊</option><option>MIG焊</option><option>TIG焊</option></select></label><label>板材材质<input placeholder="例如：Q235B" value={form.material ?? ''} onChange={setField('material')} /></label><label>板材厚度<input placeholder="例如：6 mm" value={form.thickness ?? ''} onChange={setField('thickness')} /></label><label>电流 / 电压<input placeholder="180 A / 22 V" value={form.current_voltage ?? ''} onChange={setField('current_voltage')} /></label><label>采样频率<input placeholder="10 kHz" value={form.sample_rate ?? ''} onChange={setField('sample_rate')} /></label></div><div className="form-section-title"><span>上传数据文件</span><i /></div><div className={`upload-zones${flash.file ? ' field-flash' : ''}`}>{UPLOAD_ZONES.map((zone) => { const st = uploads[zone.key]; return <div className="upload-zone" key={zone.key}><Upload size={16} /><strong>{zone.label}</strong><span>{zone.hint}</span>{st && <span className={st.status === 'error' ? 'toolbar-error' : 'accent-text'} role={st.status === 'error' ? 'alert' : undefined}>{st.status === 'uploading' ? `上传中：${st.fileName} ${st.progress ?? 0}%` : st.status === 'pending' ? `已选择：${st.fileName}（待上传）` : st.status === 'error' ? (st.errorMsg ?? `${st.fileName} 上传失败，请重试`) : `${st.fileName} 已上传`}</span>}<button className="outline-button" onClick={() => fileRefs.current[zone.key]?.click()}>{st?.status === 'pending' || st?.status === 'done' ? '更换文件' : '选择文件'}</button><input ref={(el) => { fileRefs.current[zone.key] = el; }} type="file" accept={zone.accept} style={{ display: 'none' }} onChange={(event) => handleFile(zone.key, event)} onClick={(e) => { e.currentTarget.value = ''; }} /></div>; })}</div><button className={`full-button${missingFields.length || submitting ? ' full-button--disabled' : ''}`} aria-disabled={missingFields.length > 0 || submitting} onClick={() => { if (submitting) return; if (missingFields.length) handleMissingClick(); else handleSubmit(); }}>{registered ? <><CheckCircle2 size={16} />上传成功：{regNo}</> : submitting ? <><FileCheck2 size={16} />上传中…</> : <><FileCheck2 size={16} />上传数据</>}</button>{(missingHint || regError) && <span className="toolbar-error" role="alert">{missingHint ?? regError}</span>}</section><aside className="registration-aside"><section className="panel"><div className="panel-heading"><div><h2>上传规则</h2><p>平台数据使用约束</p></div><ClipboardCheck size={18} className="accent-text" /></div>{['自动生成唯一编号', '原始文件与后续版本自动关联', '上传后触发入库前数据核验', '所有操作写入审计日志'].map((item) => <div className="rule-row" key={item}><CheckCircle2 size={15} />{item}</div>)}</section><section className="panel"><div className="panel-heading"><div><h2>最近上传</h2><p>最近 24 小时新增数据</p></div></div>{recentLoading ? <p className="dataset-empty-state" role="status">最近上传加载中…</p> : recentRows.map((row) => <div className="recent-row" key={row.id}><span className="recent-dot" /><div><strong>{row.id}</strong><small>{row.source} · {row.time.slice(11)}</small></div><StatusPill>已上传</StatusPill></div>)}</section></aside></div></div>;
}

const CH = 720; const CW = 220; const AXIS_L = 44; const AXIS_B = 22; const PLOT_W = CH - AXIS_L; const PLOT_H = CW - AXIS_B;
const dur = 5.42;
const SAMPLES = 216;
const t = Array.from({ length: SAMPLES }, (_, i) => (i / (SAMPLES - 1)) * dur);
function seg(s: number, e: number) { return s <= t[0] ? 0 : e >= dur ? 1 : s / dur; }
const arc = 0.42; const weldS = 0.78; const weldE = 4.28; const ext = 4.86;
const isArc = (x: number) => x < arc;
const isWeld = (x: number) => x >= weldS && x <= weldE;
const isTail = (x: number) => x > ext;
const anomalA: [number, number] = [1.92, 2.34];
const anomalB: [number, number] = [3.58, 3.86];
const isAnomA = (x: number) => x >= anomalA[0] && x <= anomalA[1];
const isAnomB = (x: number) => x >= anomalB[0] && x <= anomalB[1];
const isAnom = (x: number) => isAnomA(x) || isAnomB(x);
const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));

function currentAmp(x: number): number {
  let b = 180;
  if (isArc(x)) b = 60 + (x / arc) * 130;
  else if (isTail(x)) b = 150 - (x - ext) * 90;
  else if (isWeld(x)) b = 180;
  const noise = isAnom(x) ? (Math.sin(x * 47) * 22 + Math.cos(x * 31) * 16) : (Math.sin(x * 25) * 7 + Math.cos(x * 18) * 4);
  const drip = Math.sin(x * 38) * (isWeld(x) ? 11 : 0);
  return clamp(b + noise + drip, 0, 300);
}
function voltVal(x: number): number {
  let b = 22.4;
  if (isArc(x)) b = 14 + (x / arc) * 9;
  else if (isTail(x)) b = 22 - (x - ext) * 12;
  else if (isWeld(x)) b = 22.4;
  const noise = isAnom(x) ? (Math.sin(x * 53) * 3.4 + Math.cos(x * 29) * 2.6) : (Math.sin(x * 22) * 0.9 + Math.cos(x * 16) * 0.6);
  return clamp(b + noise, 0, 40);
}
function gasVal(x: number): number {
  if (isArc(x)) return clamp(12 + (x / arc) * 6, 0, 30);
  if (isTail(x)) return clamp(18 - (x - ext) * 5, 0, 30);
  const noise = isAnom(x) ? (Math.sin(x * 13) * 2.4) : (Math.cos(x * 7) * 0.6);
  return clamp(18 + noise, 0, 30);
}
function wireVal(x: number): number {
  if (isArc(x)) return clamp(3 + (x / arc) * 4, 0, 12);
  if (isTail(x)) return clamp(7 - (x - ext) * 5, 0, 12);
  const noise = isAnom(x) ? (Math.sin(x * 19) * 1.6) : (Math.cos(x * 11) * 0.4);
  return clamp(7 + noise, 0, 12);
}

const sigCur = t.map(currentAmp);
const sigVol = t.map(voltVal);
const sigGas = t.map(gasVal);
const sigWir = t.map(wireVal);

type Chan = { id: string; name: string; unit: string; color: string; values: number[]; lo: number; hi: number; mean: string };
/** 通道配色（后端不输出颜色，前端按通道 id 映射，与 mock 常量一致）。 */
const chanColor: Record<string, string> = { cur: '#2c9caf', vol: '#67cdb0', gas: '#f0a34a', wir: '#75add1' };
/** 后端信号通道 → 前端 Chan（values 已由 api 层降采样 ≤512 点）。 */
function toChan(c: SignalChannel): Chan {
  return { id: c.id, name: c.name, unit: c.unit, color: chanColor[c.id] ?? '#2c9caf', values: c.values, lo: c.lo, hi: c.hi, mean: `${c.mean} ${c.unit}` };
}
const mockChannels: Chan[] = [
  { id: 'cur', name: '电流', unit: 'A', color: '#2c9caf', values: sigCur, lo: 0, hi: 300, mean: '180 ± 12 A' },
  { id: 'vol', name: '电压', unit: 'V', color: '#67cdb0', values: sigVol, lo: 0, hi: 40, mean: '22.4 ± 1.8 V' },
  { id: 'gas', name: '气体流量', unit: 'L/min', color: '#f0a34a', values: sigGas, lo: 0, hi: 30, mean: '18 L/min' },
  { id: 'wir', name: '送丝速度', unit: 'm/min', color: '#75add1', values: sigWir, lo: 0, hi: 12, mean: '7 m/min' },
];
/** 加载期占位通道：保留通道骨架（名称/配色）但波形为空，避免 mock 波形闪现且不产生 undefined 取值。 */
const emptyChannels: Chan[] = mockChannels.map((c) => ({ ...c, values: [], mean: '—' }));

function fmt(s: number) {
  const m = Math.floor(s / 60);
  const r = (s - m * 60).toFixed(2).padStart(5, '0');
  return `${String(m).padStart(2, '0')}:${r}`;
}

/** 通用波形 path 构建（对齐页轨道/原始波形共用）；toPath 为分析页固定视口的委托。 */
function buildPath(values: number[], lo: number, hi: number, plotW: number, plotH: number, axisL = 0): string {
  const range = hi - lo || 1;
  const n = Math.max(values.length - 1, 1);
  return values.map((v, i) => {
    const px = axisL + (i / n) * plotW;
    const py = (plotH * (1 - (v - lo) / range));
    return `${i === 0 ? 'M' : 'L'}${px.toFixed(1)} ${py.toFixed(1)}`;
  }).join(' ');
}

function toPath(values: number[], lo: number, hi: number): string {
  return buildPath(values, lo, hi, PLOT_W, PLOT_H, AXIS_L);
}

type SplitPreviewSample = { index: number; start: number; end: number };
const emptyPhaseValues: number[] = [];

/** 按时间窗口从当前信号中取出样本缩略图数据。信号接口返回的点已抽稀，适合做小卡片预览。 */
function sliceSignalWindow(channel: SignalChannel | undefined, start: number, end: number, duration: number): number[] {
  if (!channel?.values?.length || duration <= 0) return [];
  const last = channel.values.length - 1;
  const from = Math.max(0, Math.min(last, Math.floor((start / duration) * last)));
  const to = Math.max(from, Math.min(last, Math.ceil((end / duration) * last)));
  const values = channel.values.slice(from, to + 1);
  return values.length > 1 ? values : channel.values.slice(Math.max(0, from - 1), Math.min(last + 1, from + 2));
}

function SampleWaveThumb({ sample, signals, duration }: { sample: SplitPreviewSample; signals: SignalData | null; duration: number }) {
  const current = signals?.channels.find((channel) => channel.id === 'cur');
  const voltage = signals?.channels.find((channel) => channel.id === 'vol');
  const currentValues = sliceSignalWindow(current, sample.start, sample.end, duration);
  const voltageValues = sliceSignalWindow(voltage, sample.start, sample.end, duration);
  if (!currentValues.length && !voltageValues.length) {
    return <div className="sample-thumb sample-thumb-empty"><Waves size={16} /><span>波形加载中</span></div>;
  }
  return <div className="sample-thumb sample-wave-thumb" aria-label="电流电压波形缩略图">
    <svg viewBox="0 0 100 42" preserveAspectRatio="none" role="img">
      {currentValues.length > 1 && current && <path d={buildPath(currentValues, current.lo, current.hi, 100, 18)} fill="none" stroke={chanColor.cur} strokeWidth="1.25" vectorEffect="non-scaling-stroke" />}
      {voltageValues.length > 1 && voltage && <path d={buildPath(voltageValues, voltage.lo, voltage.hi, 100, 18, 24)} fill="none" stroke={chanColor.vol} strokeWidth="1.25" vectorEffect="non-scaling-stroke" />}
    </svg>
    <span className="sample-wave-legend"><i style={{ background: chanColor.cur }} />电流 <i style={{ background: chanColor.vol }} />电压</span>
  </div>;
}


function PhasePlot({ cursor, onCursor, data, loading }: { cursor: number; onCursor: (s: number) => void; data?: PhaseData; loading?: boolean }) {
  const w = 520; const h = 300; const pad = 42; const pw = w - pad * 2; const ph = h - pad * 2;
  const domain = (values: number[], fallback: { lo: number; hi: number }, minimumSpan: number) => {
    let min = Infinity; let max = -Infinity;
    for (const value of values) { if (Number.isFinite(value)) { min = Math.min(min, value); max = Math.max(max, value); } }
    if (!Number.isFinite(min) || !Number.isFinite(max)) return fallback;
    const span = Math.max(max - min, minimumSpan);
    const margin = Math.max(span * 0.06, minimumSpan * 0.08);
    const center = (min + max) / 2;
    return { lo: center - span / 2 - margin, hi: center + span / 2 + margin };
  };
  const rawCurrent = data?.current ?? emptyPhaseValues;
  const rawVoltage = data?.voltage ?? emptyPhaseValues;
  const fullX = useMemo(() => domain(data?.current ?? emptyPhaseValues, { lo: 140, hi: 230 }, 10), [data]);
  const fullY = useMemo(() => domain(data?.voltage ?? emptyPhaseValues, { lo: 15, hi: 30 }, 2), [data]);
  const [xRange, setXRange] = useState(fullX);
  const [yRange, setYRange] = useState(fullY);
  useEffect(() => { setXRange(fullX); setYRange(fullY); }, [fullX, fullY]);
  const cxLo = xRange.lo; const cxHi = xRange.hi; const cvLo = yRange.lo; const cvHi = yRange.hi;
  const toX = (c: number) => pad + ((c - cxLo) / (cxHi - cxLo)) * pw;
  const toY = (v: number) => pad + (1 - (v - cvLo) / (cvHi - cvLo)) * ph;
  const n = Math.min(rawCurrent.length, rawVoltage.length);
  const step = Math.max(1, Math.ceil(n / 1800));
  const points = Array.from({ length: Math.ceil(n / step) }, (_, bucket) => {
    const i = Math.min(bucket * step, n - 1);
    const ts = (i / Math.max(n - 1, 1)) * dur;
    return { x: toX(rawCurrent[i]), y: toY(rawVoltage[i]), ts, i, anom: isAnom(ts) };
  }).filter((p) => Number.isFinite(p.x) && Number.isFinite(p.y));
  const path = points.map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(' ');
  const cursorIdx = Math.min(Math.max(points.length - 1, 0), Math.max(0, Math.round((cursor / dur) * (points.length - 1))));
  const cp = points[cursorIdx];
  const x = (e: React.MouseEvent<SVGSVGElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const relX = (e.clientX - rect.left) / rect.width * w;
    const c = cxLo + ((relX - pad) / pw) * (cxHi - cxLo);
    let best = 0; let bd = Infinity;
    for (let i = 0; i < n; i++) { const d = Math.abs(rawCurrent[i] - c); if (d < bd) { bd = d; best = i; } }
    onCursor((best / Math.max(n - 1, 1)) * dur);
  };
  const zoomAt = (factor: number, focalX = (cxLo + cxHi) / 2, focalY = (cvLo + cvHi) / 2) => {
    const nextXSpan = Math.max((fullX.hi - fullX.lo) * 0.08, Math.min(fullX.hi - fullX.lo, (cxHi - cxLo) * factor));
    const nextYSpan = Math.max((fullY.hi - fullY.lo) * 0.08, Math.min(fullY.hi - fullY.lo, (cvHi - cvLo) * factor));
    const xRatio = (focalX - cxLo) / Math.max(cxHi - cxLo, 1);
    const yRatio = (focalY - cvLo) / Math.max(cvHi - cvLo, 1);
    const nextXLo = Math.max(fullX.lo, Math.min(fullX.hi - nextXSpan, focalX - xRatio * nextXSpan));
    const nextYLo = Math.max(fullY.lo, Math.min(fullY.hi - nextYSpan, focalY - yRatio * nextYSpan));
    setXRange({ lo: nextXLo, hi: nextXLo + nextXSpan });
    setYRange({ lo: nextYLo, hi: nextYLo + nextYSpan });
  };
  const onWheel = (e: React.WheelEvent<SVGSVGElement>) => {
    e.preventDefault();
    const rect = e.currentTarget.getBoundingClientRect();
    const relX = (e.clientX - rect.left) / rect.width * w;
    const relY = (e.clientY - rect.top) / rect.height * h;
    const focalX = cxLo + ((relX - pad) / pw) * (cxHi - cxLo);
    const focalY = cvLo + (1 - (relY - pad) / ph) * (cvHi - cvLo);
    zoomAt(e.deltaY > 0 ? 1.15 : 1 / 1.15, focalX, focalY);
  };
  const reset = () => { setXRange(fullX); setYRange(fullY); };
  return <div className="phase-plot-wrap">
    {points.length > 0 && <div className="phase-zoom-tools" role="group" aria-label="相图缩放控制">
      <button type="button" onClick={() => zoomAt(1 / 1.15)} aria-label="放大相图" title="放大"><Plus size={13} /></button>
      <button type="button" onClick={() => zoomAt(1.15)} aria-label="缩小相图" title="缩小"><Minus size={13} /></button>
      <button type="button" onClick={reset} aria-label="重置相图缩放" title="重置">1:1</button>
    </div>}
    {!points.length ? <div className="phase-empty" role="status">{loading ? '真实 UI 相图加载中…' : '暂无真实 UI 相图数据'}</div> : <svg viewBox={`0 0 ${w} ${h}`} className="phase-svg" onMouseMove={x} onWheel={onWheel} onMouseLeave={() => {}}>
    <defs><clipPath id="phase-plot-clip"><rect x={pad} y={pad} width={pw} height={ph} /></clipPath></defs>
    <line x1={pad} y1={pad} x2={pad} y2={pad + ph} stroke="#e8efef" />
    <line x1={pad} y1={pad + ph} x2={pad + pw} y2={pad + ph} stroke="#e8efef" />
    <text x={pad + pw / 2} y={h - 6} textAnchor="middle" className="phase-axis-label">电流 (A) · {cxLo.toFixed(0)}–{cxHi.toFixed(0)}</text>
    <text x={8} y={pad + ph / 2} textAnchor="middle" className="phase-axis-label" transform={`rotate(-90 8 ${pad + ph / 2})`}>电压 (V) · {cvLo.toFixed(0)}–{cvHi.toFixed(0)}</text>
    <g clipPath="url(#phase-plot-clip)"><path d={path} fill="none" stroke="#2c9caf" strokeWidth="1.4" opacity="0.55" />
    {points.filter((p) => p.anom).map((p) => <circle key={p.i} cx={p.x} cy={p.y} r="2.4" fill="#e88d6c" opacity="0.7" />)}
    </g>
    {cp && <circle cx={cp.x} cy={cp.y} r="5" fill="#fff" stroke="#e88d6c" strokeWidth="2.5" />}
    </svg>}<span className="phase-zoom-hint">滚轮缩放 · 指针定位 · 自动适配数据范围</span>
  </div>;
}

function PddChart({ chanId, channels, data }: { chanId: string; channels: Chan[]; data?: PddData }) {
  const chan = channels.find((c) => c.id === chanId) ?? channels[0];
  const hasApi = !!data && data.counts.length > 0;
  const bins = hasApi ? data!.counts.length : 28;
  let counts: number[];
  let kde: number[];
  let lo: number;
  let hi: number;
  if (hasApi) {
    counts = data!.counts;
    kde = data!.kde;
    lo = data!.bins.length ? data!.bins[0] : chan.lo;
    hi = data!.bins.length ? data!.bins[data!.bins.length - 1] : chan.hi;
  } else {
    const vals = chan.values;
    lo = chan.lo; hi = chan.hi;
    const c = new Array(bins).fill(0);
    vals.forEach((v) => { const b = clamp(Math.floor(((v - lo) / (hi - lo)) * bins), 0, bins - 1); c[b]++; });
    counts = c;
    const k: number[] = [];
    for (let i = 0; i < bins; i++) {
      let sum = 0;
      for (let j = 0; j < bins; j++) { const d = (i - j) / 3.5; sum += counts[j] * Math.exp(-d * d); }
      k.push(sum);
    }
    kde = k;
  }
  const max = Math.max(...counts) || 1;
  const w = 260; const h = 200; const pad = 28; const pw = w - pad - 12; const ph = h - pad - 16;
  const bw = pw / bins;
  const kdeMax = Math.max(...kde) || 1;
  const kdePath = kde.map((k, i) => { const px = pad + i * bw + bw / 2; const py = pad + ph * (1 - k / kdeMax); return `${i === 0 ? 'M' : 'L'}${px.toFixed(1)} ${py.toFixed(1)}`; }).join(' ');
  return <svg viewBox={`0 0 ${w} ${h}`} className="pdd-svg">
    <line x1={pad} y1={pad} x2={pad} y2={pad + ph} stroke="#e8efef" />
    <line x1={pad} y1={pad + ph} x2={pad + pw} y2={pad + ph} stroke="#e8efef" />
    {counts.map((c, i) => <rect key={i} x={pad + i * bw + 1} y={pad + ph * (1 - c / max)} width={bw - 2} height={ph * (c / max)} fill={chan.color} opacity="0.32" rx="1" />)}
    <path d={kdePath} fill="none" stroke={chan.color} strokeWidth="2.2" />
    <text x={pad} y={h - 4} className="pdd-axis" textAnchor="start">{lo}</text>
    <text x={pad + pw} y={h - 4} className="pdd-axis" textAnchor="end">{hi} {chan.unit}</text>
    <text x={6} y={pad + 8} className="pdd-axis">密度</text>
  </svg>;
}

function ExploreWaveform({ active, cursor, onCursor, channels: chanList }: { active: Set<string>; cursor: number; onCursor: (s: number) => void; channels: Chan[] }) {
  const x = (e: React.MouseEvent<SVGSVGElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const rel = (e.clientX - rect.left) / rect.width;
    onCursor(clamp(rel * dur, 0, dur));
  };
  const cursorX = AXIS_L + (cursor / dur) * PLOT_W;
  const visible = chanList.filter((c) => active.has(c.id));
  return <div className="explore-waveform">
    <svg viewBox={`0 0 ${CH} ${CW}`} className="explore-waveform-svg" preserveAspectRatio="none" onMouseMove={x} onClick={x} onMouseLeave={() => {}}>
      {[0, 0.25, 0.5, 0.75, 1].map((p) => <line key={p} x1={AXIS_L} y1={PLOT_H * p} x2={CH} y2={PLOT_H * p} stroke="#edf2f2" />)}
      <rect x={AXIS_L + seg(anomalA[0], anomalA[1]) * PLOT_W} y1={0} y={0} width={(anomalA[1] - anomalA[0]) / dur * PLOT_W} height={PLOT_H} fill="#e88d6c" opacity="0.13" />
      <rect x={AXIS_L + seg(anomalB[0], anomalB[1]) * PLOT_W} width={(anomalB[1] - anomalB[0]) / dur * PLOT_W} height={PLOT_H} fill="#e88d6c" opacity="0.13" />
      {visible.map((c) => <path key={c.id} d={toPath(c.values, c.lo, c.hi)} fill="none" stroke={c.color} strokeWidth={c.id === 'cur' ? 2 : 1.6} opacity={0.9} />)}
      <line x1={cursorX} y1={0} x2={cursorX} y2={PLOT_H} stroke="#d16f69" strokeWidth="1.5" strokeDasharray="4 3" />
    </svg>
    <div className="explore-axis"><span>0s</span><span>1s</span><span>2s</span><span>3s</span><span>4s</span><span>5s</span></div>
  </div>;
}

function modeLabel(mode: string) {
  if (mode === '时域') return '原始时域波形';
  if (mode === 'PSD') return '功率谱密度（Welch 法）';
  if (mode === 'STFT') return '短时傅里叶时频图';
  if (mode === 'DWT') return '离散小波分解';
  if (mode === '小波分解') return '小波多层分量分解';
  return '';
}

const filterTypes = ['低通', '高通', '带通'] as const;
type FilterType = typeof filterTypes[number];

function PsdChart({ values, color, freqs, psd }: { values: number[]; color: string; lo: number; hi: number; freqs?: number[]; psd?: number[] }) {
  const hasApi = !!freqs && !!psd && freqs.length > 0 && psd.length > 0;
  const N = values.length;
  const half = Math.floor(N / 2);
  const mags: number[] = [];
  for (let k = 0; k < half; k++) {
    let re = 0; let im = 0;
    for (let n = 0; n < N; n++) {
      const ang = (2 * Math.PI * k * n) / N;
      re += values[n] * Math.cos(ang);
      im -= values[n] * Math.sin(ang);
    }
    mags.push((re * re + im * im) / N);
  }
  const welchBins = 24;
  const welch: number[] = [];
  if (hasApi) {
    // 后端已算 welch：等距抽稀到 welchBins 个点喂给原 SVG 结构
    const step = (psd!.length - 1) / (welchBins - 1 || 1);
    for (let b = 0; b < welchBins; b++) welch.push(psd![Math.round(b * step)] ?? 0);
  } else {
    const binSize = Math.floor(half / welchBins) || 1;
    for (let b = 0; b < welchBins; b++) {
      let sum = 0;
      for (let j = 0; j < binSize; j++) { sum += mags[b * binSize + j] ?? 0; }
      welch.push(sum / binSize);
    }
  }
  const wMax = Math.max(...welch) || 1;
  const W = 660; const H = 180; const pad = 30; const pw = W - pad - 12; const ph = H - pad - 18;
  const bw = pw / welchBins;
  const path = welch.map((w, i) => { const px = pad + i * bw + bw / 2; const py = pad + ph * (1 - w / wMax); return `${i === 0 ? 'M' : 'L'}${px.toFixed(1)} ${py.toFixed(1)}`; }).join(' ');
  const fmtF = (f: number) => (f >= 1000 ? `${(f / 1000).toFixed(1)}k` : `${Math.round(f)}`);
  const labelIdx = [0, 6, 12, 18, 23];
  const labels = hasApi
    ? labelIdx.map((i) => fmtF(freqs![Math.min(Math.round(i * (freqs!.length - 1) / (labelIdx.length - 1)), freqs!.length - 1)]))
    : ['0', '0.5k', '1k', '2k', '5k', '10k'];
  return <svg viewBox={`0 0 ${W} ${H}`} className="psd-svg" preserveAspectRatio="none">
    {[0, 0.25, 0.5, 0.75, 1].map((p) => <line key={p} x1={pad} y1={pad + ph * p} x2={pad + pw} y2={pad + ph * p} stroke="#edf2f2" />)}
    {welch.map((w, i) => <rect key={i} x={pad + i * bw + 1} y={pad + ph * (1 - w / wMax)} width={bw - 2} height={ph * (w / wMax)} fill={color} opacity="0.25" rx="1" />)}
    <path d={path} fill="none" stroke={color} strokeWidth="2.2" />
    <line x1={pad} y1={pad + ph} x2={pad + pw} y2={pad + ph} stroke="#d8e0e0" />
    <line x1={pad} y1={pad} x2={pad} y2={pad + ph} stroke="#d8e0e0" />
    {labels.map((l, i) => <text key={l} x={pad + (pw / (labels.length - 1)) * i} y={H - 4} className="psd-axis" textAnchor={i === 0 ? 'start' : i === labels.length - 1 ? 'end' : 'middle'}>{l}</text>)}
    <text x={6} y={pad + 8} className="psd-axis">PSD</text>
  </svg>;
}

function StftHeatmap({ values, color, magnitude }: { values: number[]; color: string; magnitude?: number[][] }) {
  const cols = 40; const rows = 16;
  const hasApi = !!magnitude && magnitude.length > 0 && magnitude[0].length > 0;
  const N = values.length;
  const heat: number[][] = [];
  let gMax = 0;
  if (hasApi) {
    // 后端已算 STFT：magnitude 形状 = (freqs × times)，等距抽稀到 cols×rows 网格
    const nT = magnitude![0].length;
    const nF = magnitude!.length;
    for (let c = 0; c < cols; c++) {
      const tIdx = c === cols - 1 ? nT - 1 : Math.round(c * (nT - 1) / (cols - 1));
      const row: number[] = [];
      for (let r = 0; r < rows; r++) {
        const fIdx = r === rows - 1 ? nF - 1 : Math.round(r * (nF - 1) / (rows - 1));
        const m = magnitude![fIdx][tIdx] ?? 0;
        row.push(m);
        if (m > gMax) gMax = m;
      }
      heat.push(row);
    }
  } else {
    const win = Math.floor(N / cols) || 1;
    for (let c = 0; c < cols; c++) {
      const frame = values.slice(c * win, c * win + win);
      const row: number[] = [];
      for (let k = 0; k < rows; k++) {
        let re = 0; let im = 0;
        for (let n = 0; n < win && n < frame.length; n++) {
          const ang = (2 * Math.PI * k * n) / win;
          re += frame[n] * Math.cos(ang);
          im -= frame[n] * Math.sin(ang);
        }
        const m = Math.sqrt(re * re + im * im);
        row.push(m);
        if (m > gMax) gMax = m;
      }
      heat.push(row);
    }
  }
  const W = 660; const H = 180; const pad = 28; const pw = W - pad - 8; const ph = H - pad - 16;
  const cw = pw / cols; const rh = ph / rows;
  const cellColor = (v: number) => {
    const r = v / (gMax || 1);
    if (r > 0.75) return color;
    if (r > 0.5) return color + 'cc';
    if (r > 0.25) return color + '88';
    if (r > 0.1) return color + '44';
    return '#f0f5f4';
  };
  return <svg viewBox={`0 0 ${W} ${H}`} className="stft-svg" preserveAspectRatio="none">
    {heat.map((col, c) => col.map((v, r) => <rect key={`${c}-${r}`} x={pad + c * cw} y={pad + (rows - 1 - r) * rh} width={cw + 0.5} height={rh + 0.5} fill={cellColor(v)} />))}
    <line x1={pad} y1={pad + ph} x2={pad + pw} y2={pad + ph} stroke="#d8e0e0" />
    <line x1={pad} y1={pad} x2={pad} y2={pad + ph} stroke="#d8e0e0" />
    <text x={pad + pw / 2} y={H - 4} className="psd-axis" textAnchor="middle">时间 (s)</text>
    <text x={8} y={pad + ph / 2} className="psd-axis" textAnchor="middle" transform={`rotate(-90 8 ${pad + ph / 2})`}>频率</text>
  </svg>;
}

function DwtChart({ values, color, bands, approx }: { values: number[]; color: string; bands?: WaveletBand[]; approx?: { name: string; values: number[] } }) {
  const levels = 4;
  const W = 660; const H = 180; const pad = 30; const pw = W - pad - 8;
  const bandH = (H - pad - 10) / (levels + 1);
  let allBands: { name: string; values: number[] }[];
  if (bands && bands.length) {
    // 后端已算 DWT：bands D1..Dn + approx A_n，标签直接用后端 name
    allBands = [...bands];
    if (approx) allBands.push(approx);
  } else {
    const approxArr = [...values];
    const detail: number[][] = [];
    for (let lv = 0; lv < levels; lv++) {
      const d: number[] = [];
      const next: number[] = [];
      for (let i = 0; i < approxArr.length - 1; i += 2) {
        const a = (approxArr[i] + approxArr[i + 1]) / 2;
        d.push((approxArr[i] - approxArr[i + 1]) / 2);
        next.push(a);
      }
      detail.push(d);
      approxArr.length = 0; approxArr.push(...next);
    }
    allBands = detail.map((b, lv) => ({ name: `D${levels - lv}`, values: b })).concat([{ name: `A${levels}`, values: approxArr }]);
  }
  const allMax = Math.max(...allBands.flatMap((b) => b.values.map(Math.abs))) || 1;
  const toBandPath = (band: number[], yOff: number) => {
    const step = pw / (band.length - 1 || 1);
    return band.map((v, i) => { const px = pad + i * step; const py = yOff + bandH / 2 - (v / allMax) * (bandH / 2 - 2); return `${i === 0 ? 'M' : 'L'}${px.toFixed(1)} ${py.toFixed(1)}`; }).join(' ');
  };
  return <svg viewBox={`0 0 ${W} ${H}`} className="dwt-svg" preserveAspectRatio="none">
    {allBands.map((band, lv) => {
      const yOff = pad + lv * bandH;
      const c = lv < allBands.length - 1 ? color : '#f0a34a';
      return <g key={band.name}>
        <line x1={pad} y1={yOff + bandH} x2={pad + pw} y2={yOff + bandH} stroke="#edf2f2" />
        <text x={6} y={yOff + bandH / 2 + 3} className="psd-axis">{band.name}</text>
        <path d={toBandPath(band.values, yOff)} fill="none" stroke={c} strokeWidth="1.4" opacity="0.85" />
      </g>;
    })}
    <text x={pad + pw / 2} y={H - 2} className="psd-axis" textAnchor="middle">样本点</text>
  </svg>;
}

function WaveletDecomp({ values, color, bands }: { values: number[]; color: string; bands?: WaveletBand[] }) {
  const levels = 5;
  const W = 660; const H = 200; const pad = 34; const pw = W - pad - 8;
  const bandH = (H - pad - 10) / levels;
  let recon: { name: string; values: number[] }[];
  if (bands && bands.length) {
    // 后端已算小波分解：bands L1..Ln，标签直接用后端 name
    recon = bands;
  } else {
    const comps: number[][] = [];
    const cur = [...values];
    for (let lv = 0; lv < levels; lv++) {
      const comp: number[] = [];
      const scale = (lv + 1) * 4;
      for (let i = 0; i < cur.length; i++) {
        const win = cur.slice(Math.max(0, i - scale), Math.min(cur.length, i + scale));
        const m = win.reduce((s, v) => s + v, 0) / win.length;
        const d = cur[i] - m;
        comp.push(d * (1 + lv * 0.3) + Math.sin(i * 0.4 + lv) * 3 * (lv / levels));
      }
      comps.push(comp);
    }
    recon = comps.map((c, lv) => ({ name: `L${lv + 1}`, values: c }));
  }
  const allMax = Math.max(...recon.flatMap((b) => b.values.map(Math.abs))) || 1;
  return <svg viewBox={`0 0 ${W} ${H}`} className="wavelet-decomp-svg" preserveAspectRatio="none">
    {recon.map((band, lv) => {
      const yOff = pad + lv * bandH;
      const step = pw / (band.values.length - 1 || 1);
      const path = band.values.map((v, i) => { const px = pad + i * step; const py = yOff + bandH / 2 - (v / allMax) * (bandH / 2 - 2); return `${i === 0 ? 'M' : 'L'}${px.toFixed(1)} ${py.toFixed(1)}`; }).join(' ');
      const opacity = 0.4 + (lv / levels) * 0.5;
      return <g key={band.name}>
        <line x1={pad} y1={yOff + bandH} x2={pad + pw} y2={yOff + bandH} stroke="#edf2f2" />
        <text x={6} y={yOff + bandH / 2 + 3} className="psd-axis">{band.name}</text>
        <path d={path} fill="none" stroke={color} strokeWidth="1.3" opacity={opacity} />
      </g>;
    })}
    <text x={pad + pw / 2} y={H - 2} className="psd-axis" textAnchor="middle">样本点</text>
  </svg>;
}



function AdvancedWeldAnalysis({ dataId }: { embedded?: boolean; dataId?: string }) {
  const [mode, setMode] = useState('时域');
  const [active, setActive] = useState<Set<string>>(new Set(['cur', 'vol', 'gas']));
  const [cursor, setCursor] = useState(2.1);
  const [pddChan, setPddChan] = useState('cur');
  const [filterOn, setFilterOn] = useState(false);
  const [filterType, setFilterType] = useState<FilterType>('低通');
  const [cutoff, setCutoff] = useState(0.3);
  const [cutoff2, setCutoff2] = useState(0.6);
  const [filterChan, setFilterChan] = useState('cur');
  // 初始为空波形占位：mock 波形仅在接口失败时兜底，不得在加载期闪现
  const [channels, setChannels] = useState<Chan[]>(emptyChannels);
  const [signalsLoading, setSignalsLoading] = useState(true);
  const [signalSource, setSignalSource] = useState<'real' | 'generated' | null>(null);
  const [signalError, setSignalError] = useState<string | null>(null);
  const [versionId, setVersionId] = useState<number | null>(null);
  const [psdData, setPsdData] = useState<PsdData | null>(null);
  const [stftData, setStftData] = useState<StftData | null>(null);
  const [dwtData, setDwtData] = useState<DwtData | null>(null);
  const [waveletData, setWaveletData] = useState<WaveletData | null>(null);
  const [phaseData, setPhaseData] = useState<PhaseData | null>(null);
  const [phaseLoading, setPhaseLoading] = useState(false);
  const [pddData, setPddData] = useState<PddData | null>(null);
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [analysisLoading, setAnalysisLoading] = useState(false);
  const [analysisError, setAnalysisError] = useState<string | null>(null);
  const [resultError, setResultError] = useState<string | null>(null);
  const toggle = (id: string) => setActive((prev) => { const n = new Set(prev); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  useEffect(() => {
    if (!dataId) return;
    let cancelled = false;
    getWeld(dataId).then((r) => { if (!cancelled) setVersionId(r.latest_version_id ?? r.latest_version?.id ?? null); }).catch((err) => { if (!cancelled) console.warn('[analysis] getWeld failed', err); });
    return () => { cancelled = true; };
  }, [dataId]);
  // 时域波形：挂载 + 滤波参数变化 → 重新拉取（始终请求全部 4 通道，勾选仅本地显示过滤）
  useEffect(() => {
    if (!dataId || versionId == null) return;
    let cancelled = false;
    setSignalsLoading(true);
    setSignalError(null);
    setSignalSource(null);
    setChannels(emptyChannels);
    const opts: SignalQuery = { channels: ['cur', 'vol', 'gas', 'wir'] };
    if (filterOn) { opts.filter_type = filterType; opts.cutoff = cutoff; if (filterType === '带通') opts.cutoff2 = cutoff2; }
    getSignals(dataId, String(versionId), opts).then((data: SignalData) => { if (!cancelled) { setSignalSource(data.source); if (data.source === 'real') setChannels(data.channels.map(toChan)); else { setChannels(emptyChannels); setSignalError('当前版本没有真实导入信号，生产分析已停止，不显示模拟波形。'); } } }).catch((err) => { if (!cancelled) { setChannels(emptyChannels); setSignalError('真实信号加载失败，未显示模拟波形。请检查数据导入状态后重试。'); console.warn('[analysis] getSignals failed', err); } }).finally(() => { if (!cancelled) setSignalsLoading(false); });
    return () => { cancelled = true; };
  }, [dataId, versionId, filterOn, filterType, cutoff, cutoff2]);
  // 主视图 mode（PSD/STFT/DWT/小波分解）：仅真实信号可进入生产分析
  useEffect(() => {
    if (!dataId || versionId == null || signalSource !== 'real') return;
    if (mode !== 'PSD' && mode !== 'STFT' && mode !== 'DWT' && mode !== '小波分解') return;
    let cancelled = false;
    setAnalysisLoading(true);
    setAnalysisError(null);
    if (mode === 'PSD') setPsdData(null);
    else if (mode === 'STFT') setStftData(null);
    else if (mode === 'DWT') setDwtData(null);
    else setWaveletData(null);
    const apiMode = mode === 'PSD' ? 'psd' : mode === 'STFT' ? 'stft' : mode === 'DWT' ? 'dwt' : 'wavelet';
    const filter = filterOn ? { type: filterType, cutoff, cutoff2: filterType === '带通' ? cutoff2 : undefined } : undefined;
    getAnalysisMode(dataId, String(versionId), apiMode, filterChan, filter).then((data) => {
      if (cancelled) return;
      if (mode === 'PSD') setPsdData(data as PsdData);
      else if (mode === 'STFT') setStftData(data as StftData);
      else if (mode === 'DWT') setDwtData(data as DwtData);
      else setWaveletData(data as WaveletData);
    }).catch((err) => { if (!cancelled) { setAnalysisError(`${mode} 分析计算失败，请重试。`); console.warn(`[analysis] getAnalysisMode ${mode} failed`, err); } }).finally(() => { if (!cancelled) setAnalysisLoading(false); });
    return () => { cancelled = true; };
  }, [dataId, versionId, signalSource, mode, filterChan, filterOn, filterType, cutoff, cutoff2]);
  // 侧边 UI 相图（current/voltage，cur+vol 两通道）
  useEffect(() => {
    if (!dataId || versionId == null || signalSource !== 'real') return;
    let cancelled = false;
    setPhaseLoading(true);
    setPhaseData(null);
    const filter = filterOn ? { type: filterType, cutoff, cutoff2: filterType === '带通' ? cutoff2 : undefined } : undefined;
    getAnalysisMode(dataId, String(versionId), 'phase', 'cur', filter).then((data) => { if (!cancelled) setPhaseData(data as PhaseData); }).catch((err) => { if (!cancelled) console.warn('[analysis] phase failed', err); }).finally(() => { if (!cancelled) setPhaseLoading(false); });
    return () => { cancelled = true; };
  }, [dataId, versionId, signalSource, filterOn, filterType, cutoff, cutoff2]);
  // 侧边 PDD 分布（按所选通道）
  useEffect(() => {
    if (!dataId || versionId == null || signalSource !== 'real') return;
    let cancelled = false;
    setPddData(null);
    const filter = filterOn ? { type: filterType, cutoff, cutoff2: filterType === '带通' ? cutoff2 : undefined } : undefined;
    getAnalysisMode(dataId, String(versionId), 'pdd', pddChan, filter).then((data) => { if (!cancelled) setPddData(data as PddData); }).catch((err) => { if (!cancelled) console.warn('[analysis] pdd failed', err); });
    return () => { cancelled = true; };
  }, [dataId, versionId, signalSource, pddChan, filterOn, filterType, cutoff, cutoff2]);
  // 分析结果：稳定度 / 三类占比 / 异常区段
  useEffect(() => {
    if (!dataId || versionId == null || signalSource !== 'real') return;
    let cancelled = false;
    setResult(null);
    setResultError(null);
    getAnalysisResult(dataId, String(versionId)).then((data) => { if (!cancelled) setResult(data); }).catch((err) => { if (!cancelled) { setResultError('异常检测结果暂不可用，页面不会显示估算值。'); console.warn('[analysis] getAnalysisResult failed', err); } });
    return () => { cancelled = true; };
  }, [dataId, versionId, signalSource]);
  const anomalies = (result?.anomalies ?? []).map((a) => ({ range: [a.start, a.end] as [number, number], type: a.type, sev: (a.type.includes('电弧') ? 'orange' : 'red') as 'orange' | 'red' }));
  const filterChanObj = channels.find((c) => c.id === filterChan) ?? channels[0];
  // 信号已由后端按滤波参数计算（getSignals 带 filter 时返回滤波后值），此处直接用
  const filteredValues = filterChanObj.values;
  const seg = result?.segments;
  const modes = ['时域', 'PSD', 'STFT', 'DWT', '小波分解'];
  return <div className="page-wrap"><PageIntro eyebrow="焊缝级分析" title="焊缝深度分析" description="在同一时间轴上查看多模态信号、焊接事件和质量特征。" action={<Toolbar action="开始分析" secondary="导出分析报告" exportType="analysis" exportRefIds={versionId != null ? [versionId] : undefined} />} /><div className="analysis-meta panel"><div><span className="file-badge"><Archive size={15} />分析概览</span><h2>当前焊缝信号分析</h2><p>分析结果基于上方“当前数据上下文”中选择的焊缝及其最新版本。</p><div className="source-status"><span className={signalSource === 'real' ? 'real' : 'generated'}>{signalsLoading ? '信号加载中…' : signalSource === 'real' ? '真实信号' : '信号不可用'}</span>{result && <span>分析结果已完成</span>}</div></div><div className="analysis-kpis"><div><span>核验状态</span><strong className="accent-text">通过</strong></div><div><span>有效焊接段</span><strong>3.86 s</strong></div><div><span>异常区段</span><strong className="warning-text">{result ? `${anomalies.length} 个` : '—'}</strong></div></div></div>{signalError && <div className="alignment-banner bad" role="alert"><AlertTriangle size={15} />{signalError}</div>}{resultError && <div className="alignment-banner warn" role="status"><AlertTriangle size={15} />{resultError}</div>}
  <div className="explore-layout">
    <section className="panel explore-main">
      <div className="panel-heading"><div><h2>多模态信号联动</h2><p>勾选通道任意组合，拖动波形同步定位 — 当前：{modeLabel(mode)}</p></div><div className="mode-tabs">{modes.map((item) => <button className={mode === item ? 'active' : ''} onClick={() => setMode(item)} key={item}>{item}</button>)}</div></div>
      <div className="preprocess-bar">
        <div className="preprocess-toggle"><label className="switch-row compact"><span><FilterIcon size={13} />信号滤波</span><input type="checkbox" checked={filterOn} onChange={(e) => setFilterOn(e.target.checked)} /></label></div>
        {filterOn && <><div className="preprocess-field"><label>滤波类型</label><div className="pp-chips">{filterTypes.map((ft) => <button key={ft} className={filterType === ft ? 'on' : ''} onClick={() => setFilterType(ft)}>{ft}</button>)}</div></div>
        <div className="preprocess-field"><label>目标通道</label><div className="pp-chans">{channels.map((c) => <button key={c.id} className={filterChan === c.id ? 'on' : ''} onClick={() => setFilterChan(c.id)}><i style={{ background: c.color }} />{c.name}</button>)}</div></div>
        <div className="preprocess-field"><label>截止频率</label><div className="pp-slider"><input type="range" min="0.05" max="0.9" step="0.05" value={cutoff} onChange={(e) => setCutoff(parseFloat(e.target.value))} /><span>{(cutoff * 1000).toFixed(0)} Hz</span></div></div>
        {filterType === '带通' && <div className="preprocess-field"><label>上限频率</label><div className="pp-slider"><input type="range" min="0.1" max="0.95" step="0.05" value={cutoff2} onChange={(e) => setCutoff2(parseFloat(e.target.value))} /><span>{(cutoff2 * 1000).toFixed(0)} Hz</span></div></div>}
        </>}
      </div>
      <div className="channel-toggles">{channels.map((c) => <button key={c.id} className={`channel-toggle ${active.has(c.id) ? 'on' : ''}`} onClick={() => toggle(c.id)}><i style={{ background: c.color }} />{c.name}<small>{c.unit}</small><span className="toggle-check">{active.has(c.id) ? <Check size={12} /> : null}</span></button>)}</div>
      <div className="explore-legend">{channels.filter((c) => active.has(c.id)).map((c) => <span key={c.id}><i style={{ background: c.color }} />{c.name} ({c.unit})</span>)}{signalsLoading && <span className="explore-legend-empty" role="status">信号加载中…</span>}{!signalsLoading && active.size === 0 && <span className="explore-legend-empty">请至少开启一个通道</span>}<span className="explore-legend-anom"><i className="legend-orange" />异常区段</span><span className="explore-legend-cursor"><i className="result-dot red" />时间游标 {fmt(cursor)}</span></div>
      {mode === '时域' && <><ExploreWaveform active={active} cursor={cursor} onCursor={setCursor} channels={channels} />{filterOn && <div className="filter-compare"><span className="fc-label">滤波后 {filterChanObj.name}（{filterType} · {cutoff.toFixed(2)}）</span><svg viewBox={`0 0 ${CH} 70`} className="filter-compare-svg" preserveAspectRatio="none"><path d={toPath(filterChanObj.values, filterChanObj.lo, filterChanObj.hi)} fill="none" stroke={filterChanObj.color} strokeWidth="1.8" opacity="0.7" /></svg></div>}
      <div className="event-track"><span>起弧 <b>00:00.42</b></span><i /><span>稳态焊接 <b>00:00.78 - 00:04.28</b></span><i /><span>收弧 <b>00:04.86</b></span></div>
      <div className="anomaly-summary"><div className="anomaly-summary-head"><AlertTriangle size={14} /><span>已检出异常区段 {anomalies.length} 个 · 点击可定位</span></div>{anomalies.map((a, i) => <button key={i} className={`anomaly-chip ${a.sev}`} onClick={() => setCursor((a.range[0] + a.range[1]) / 2)}><i /><strong>{a.type}</strong><small>{fmt(a.range[0])} – {fmt(a.range[1])}</small><span>定位 <ArrowUpRight size={12} /></span></button>)}</div>
      <div className="signal-cards">{channels.map((c) => <div key={c.id} className={active.has(c.id) ? '' : 'dim'}><Waves size={16} /><span>{c.name}波形<strong>{c.mean}</strong></span></div>)}</div></>}
      {mode === 'PSD' && <div className="spectrum-view">{analysisLoading && <p className="dataset-empty-state" role="status">PSD 正在计算…</p>}{analysisError && <p className="dataset-empty-state" role="alert">{analysisError}</p>}<div className="spectrum-head"><span><FilterIcon size={14} />功率谱密度 · Welch 法</span><small>目标通道：{filterChanObj.name}（{filterOn ? `已滤波 ${filterType}` : '原始信号'}）</small></div><PsdChart values={filteredValues} color={filterChanObj.color} lo={filterChanObj.lo} hi={filterChanObj.hi} freqs={psdData?.freqs} psd={psdData?.psd} /><div className="spectrum-note"><BarChart3 size={13} /><span>主峰集中在低频段（短路过渡频率），异常区段在 2-5 kHz 存在次峰。</span></div></div>}
      {mode === 'STFT' && <div className="spectrum-view"><div className="spectrum-head"><span><Activity size={14} />短时傅里叶变换时频图</span><small>目标通道：{filterChanObj.name}</small></div><StftHeatmap values={filteredValues} color={filterChanObj.color} magnitude={stftData?.magnitude} /><div className="spectrum-note"><Waves size={13} /><span>时频图可观察到 1.9-2.3s 和 3.6-3.9s 两个异常区段的高频能量抬升。</span></div></div>}
      {mode === 'DWT' && <div className="spectrum-view"><div className="spectrum-head"><span><Layers3 size={14} />离散小波分解（4 层 · db4）</span><small>目标通道：{filterChanObj.name}</small></div><DwtChart values={filteredValues} color={filterChanObj.color} bands={dwtData?.bands} approx={dwtData?.approx} /><div className="spectrum-note"><Gauge size={13} /><span>D1-D4 为细节系数、A4 为近似系数，异常在 D1-D2 高频层最明显。</span></div></div>}
      {mode === '小波分解' && <div className="spectrum-view"><div className="spectrum-head"><span><Waves size={14} />小波多层分量分解</span><small>目标通道：{filterChanObj.name} · 5 层</small></div><WaveletDecomp values={filteredValues} color={filterChanObj.color} bands={waveletData?.bands} /><div className="spectrum-note"><Layers3 size={13} /><span>L1-L5 由低到高展示不同尺度的小波分量，低层捕捉高频瞬变。</span></div></div>}
    </section>
    <aside className="explore-aside">
      <section className="panel explore-phase-panel">
        <div className="panel-heading"><div><h2>UI 相图</h2><p>电流–电压轨迹，颜色越亮越接近当前时刻</p></div><span className="explore-hint">悬停联动</span></div>
        <PhasePlot cursor={cursor} onCursor={setCursor} data={phaseData ?? undefined} loading={phaseLoading} />
        <div className="phase-legend"><span><i className="legend-blue" />稳态轨迹</span><span><i className="legend-orange" />异常发散</span><span><i className="result-dot red" />游标 {fmt(cursor)}</span></div>
      </section>
      <section className="panel explore-pdd-panel">
        <div className="panel-heading"><div><h2>PDD 概率密度分布</h2><p>评估信号值的集中度与双峰特征</p></div><div className="pdd-chan-select">{channels.map((c) => <button key={c.id} className={pddChan === c.id ? 'active' : ''} onClick={() => setPddChan(c.id)}><i style={{ background: c.color }} />{c.name}</button>)}</div></div>
        <PddChart chanId={pddChan} channels={channels} data={pddData ?? undefined} />
        <div className="pdd-note"><BarChart3 size={13} /><span>当前通道分布近似单峰、集中度高；异常区段会使分布尾部抬升。</span></div>
      </section>
      <section className="panel explore-result-panel">
        <div className="panel-heading"><div><h2>分析结果</h2><p>AI 异常检测模型 v1.8</p></div><Sparkles size={16} className="accent-text" /></div>
        <div className="result-score"><strong>{result ? `${result.stability.toFixed(1)}%` : '—'}</strong><span>焊接稳定度</span></div>
        <div className="result-row"><span><i className="result-dot green" />正常区段</span><strong>{seg ? `${seg.normal.toFixed(1)}%` : '—'}</strong></div>
        <div className="result-row"><span><i className="result-dot orange" />电弧不稳</span><strong>{seg ? `${seg.arc_instability.toFixed(1)}%` : '—'}</strong></div>
        <div className="result-row"><span><i className="result-dot red" />飞溅倾向</span><strong>{seg ? `${seg.sputter.toFixed(1)}%` : '—'}</strong></div>
        <button className="full-button small-button">查看异常详情 <ArrowUpRight size={14} /></button>
      </section>
    </aside>
  </div></div>;
}

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
  const lastRun = report && report.created_at ? `最近核验：${fmtDT(report.created_at)} · 核验耗时 ${report.duration != null ? report.duration : '—'}s` : '正在加载核验结果…';
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
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [datasetId, setDatasetId] = useState<number | null>(null);
  const [source, setSource] = useState<'manual' | 'split_task' | 'annotation_task'>('manual');
  const [buildJobId, setBuildJobId] = useState<string | null>(null);
  const [buildError, setBuildError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const { status: buildStatus, progress, result: buildResult } = useJob<{ item_count: number; split: Partial<DatasetSplit>; quality: DatasetQuality | null; snapshot_id: string | null }>(buildJobId);
  useEffect(() => {
    let cancelled = false;
    listDatasets().then((list) => { if (cancelled) return; setDatasets(list); setDatasetId((prev) => prev ?? list[0]?.id ?? null); }).catch((err) => console.warn('[training-data] listDatasets failed', err)).finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);
  const dataset = datasets.find((item) => item.id === datasetId) ?? null;
  const handleBuild = () => {
    if (datasetId == null) return;
    setBuildError(null);
    createDatasetVersion(String(datasetId), { name: `训练版本-${new Date().toISOString().slice(0, 10)}` })
      .then((version) => createBuildTask(String(datasetId), String(version.id), { type: source }))
      .then((res) => setBuildJobId(res.job_id))
      .catch((err) => setBuildError(err instanceof Error ? err.message : '生成训练数据版本失败'));
  };
  useEffect(() => {
    if (buildStatus === 'succeeded' || buildStatus === 'failed') setBuildJobId(null);
    if (buildStatus === 'failed') setBuildError('请检查样本范围和数据质量后重试');
  }, [buildStatus]);
  const split = buildResult?.split;
  const total = split ? (split.train ?? 0) + (split.val ?? 0) + (split.test ?? 0) : 0;
  const slicePct = (value: number | undefined) => total > 0 && value != null ? `${((value / total) * 100).toFixed(0)}%` : '0%';
  const qualityPct = buildResult?.quality ? `${Math.max(0, Math.min(100, (1 - buildResult.quality.repeat_rate - buildResult.quality.empty_label_rate - buildResult.quality.dimension_missing_rate) * 100)).toFixed(1)}%` : null;
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
          <div className="form-block"><label className="form-label">1. 输入数据集</label><p className="form-help build-form-intro">来源于数据中心，不会修改原始数据。</p><select className="native-select" value={datasetId ?? ''} onChange={(e) => setDatasetId(e.target.value ? Number(e.target.value) : null)}><option value="">请选择输入数据集</option>{datasets.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.version ?? '未生成版本'}</option>)}</select>{dataset && <div className="selected-dataset-card"><div className="selected-dataset-head"><span className="dataset-row-icon"><Box size={16} /></span><div><strong>{dataset.name}</strong><small>{dataset.dataset_no} · 当前版本 {dataset.version ?? '未生成'}</small></div><StatusPill tone={dataset.status === '可训练' ? 'green' : 'orange'}>{dataset.status}</StatusPill></div><div className="selected-dataset-meta"><span>样本数 <b>{dataset.sample_count.toLocaleString()}</b></span><span>标注完成度 <b>{dataset.progress != null ? `${dataset.progress}%` : '—'}</b></span></div></div>}</div>
          <div className="form-block"><label className="form-label">2. 样本纳入范围</label><div className="build-source">{(['manual', 'split_task', 'annotation_task'] as const).map((key) => <label className={source === key ? 'chosen' : ''} key={key}><input type="radio" name="training-source" checked={source === key} onChange={() => setSource(key)} /><span><strong>{sourceMeta[key].label}</strong><small>{sourceMeta[key].desc}</small></span>{source === key && <Check size={15} />}</label>)}</div></div>
        </>}
        <div className="split-ratio-note"><div className="rule-title"><GitBranch size={15} />3. 训练数据划分</div><b>训练 80% <em>/</em> 验证 10% <em>/</em> 测试 10%</b><small>按焊缝 ID 分组，同一焊缝不会同时进入训练集和测试集，避免数据泄漏。</small></div>
        <button className="full-button" onClick={handleBuild} disabled={datasetId == null || buildJobId != null}>{buildJobId != null ? <><Activity size={16} />正在生成 · {progress}%</> : <><GitBranch size={16} />生成训练数据版本</>}</button>{buildError && <p className="dataset-empty-state" role="alert">生成失败：{buildError}</p>}
      </section>
      <section className="panel build-result"><div className="panel-heading"><div><h2>训练版本预览</h2><p>{buildJobId != null ? '正在生成训练数据版本…' : buildResult ? '最近一次生成结果' : dataset ? '根据当前配置预览生成结果' : '选择输入数据集后开始预览'}</p></div><StatusPill tone={buildStatus === 'failed' ? 'red' : buildStatus === 'running' ? 'orange' : buildResult ? 'green' : 'muted'}>{buildStatus === 'succeeded' ? '已生成' : buildStatus === 'failed' ? '生成失败' : buildStatus === 'running' ? '生成中' : '未开始'}</StatusPill></div>
        {buildResult && split ? <><div className="result-context"><CheckCircle2 size={16} /><span>训练数据版本已生成，可在“新建训练”中使用</span></div><div className="build-splitbar"><i className="train" style={{ width: slicePct(split.train) }} /><i className="val" style={{ width: slicePct(split.val) }} /><i className="test" style={{ width: slicePct(split.test) }} /></div><div className="build-split-legend"><span><i className="train" />训练集 <b>{split.train ?? 0}</b></span><span><i className="val" />验证集 <b>{split.val ?? 0}</b></span><span><i className="test" />测试集 <b>{split.test ?? 0}</b></span></div><div className="build-stat-row"><div><span>样本总数</span><strong>{buildResult.item_count.toLocaleString()}</strong></div><div><span>质量评分</span><strong>{qualityPct ?? '—'}</strong></div><div><span>版本快照</span><strong>{buildResult.snapshot_id ? buildResult.snapshot_id.slice(0, 8) : '—'}</strong></div></div></> : <div className="build-state"><div className="empty-steps"><span><Database size={17} />输入数据集</span><span><SlidersHorizontal size={17} />样本范围</span><span><GitBranch size={17} />训练版本</span></div><strong>{buildJobId != null ? '正在生成训练数据版本' : '还没有训练数据版本'}</strong><p>{buildJobId != null ? `系统正在按焊缝分组生成，当前进度 ${progress}%` : dataset ? `预计纳入 ${dataset.sample_count.toLocaleString()} 条样本，生成后将显示实际划分结果。` : '配置左侧条件后，点击“生成训练数据版本”即可开始。'}</p></div>}
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

function InfoRow({ label, value, accent }: { label: string; value: string; accent?: boolean }) { return <div className="info-row"><span>{label}</span><strong className={accent ? 'accent-text' : ''}>{value}</strong></div>; }

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

function FeatureExtraction({ dataId }: { embedded?: boolean; dataId?: string }) {
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
  return <div className="page-wrap"><PageIntro eyebrow="多模态特征工程" title="特征提取" description="从真实输入提取可追溯特征；缺失模态不会被静默当作真实数据。" action={<Toolbar action={extracting ? '提取中…' : '执行提取'} secondary="导出特征集" onAction={handleExtract} exportType="features" exportRefIds={extractionId != null ? [extractionId] : undefined} actionDisabled={extracting || !dataId || versionId == null} />} />{extractError && <div className="alignment-banner bad" role="alert"><AlertTriangle size={15} />{extractError}</div>}{fallbackModalities.length > 0 && <div className="alignment-banner warn" role="status"><AlertTriangle size={15} />{fallbackModalities.join('、')}模态非真实输入，本次结果不可直接用于生产判定。</div>}
    <div className="feature-context panel"><div><span>当前焊缝</span><strong>{dataId ?? '—'}</strong></div><div><span>数据版本</span><strong>{versionId == null ? '—' : `v${versionId}`}</strong></div><div><span>提取结果</span><strong>{extracting ? '计算中' : extractionId != null ? `#${extractionId}` : '暂无结果'}</strong></div><div><span>数据来源</span><strong>{modalityStatus ? Object.entries(modalityStatus).map(([key, value]) => `${modalityLabels[key] ?? key}·${value === 'real' ? '真实' : modalityStatusLabels[value] ?? value}`).join(' / ') : '尚未提取'}</strong></div></div>
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
  return <div className="page-wrap"><PageIntro eyebrow="模型工坊" title="模型训练" description="选择模型与数据集，创建可追踪的训练任务。" action={<button className={`primary-button ${isTraining ? 'training-button' : ''}`} onClick={() => { if (isTraining) { setIsTraining(false); setJobId(null); } else handleStart(); }}>{isTraining ? <Activity size={16} /> : <Play size={16} />}{isTraining ? '训练进行中' : '开始新训练'}</button>} /><div className="training-layout"><section className="panel config-panel"><div className="panel-heading"><div><h2>训练配置</h2><p>先选择要训练的模型，再选择一个或多个数据集版本</p></div><span className="draft-tag">{isTraining ? '执行中' : '草稿'}</span></div><div className="form-block"><label>模型类型</label><select className="native-select" value={modelType} onChange={(event) => { setModelType(event.target.value); setBaseModelVersionId(null); }}><option value="">请选择模型类型</option>{[...new Set(models.map((model) => model.type))].map((type) => <option key={type} value={type}>{type}</option>)}</select></div><div className="form-block"><label>基础模型 / 已训练模型（可选）</label><select className="native-select" value={baseModelVersionId ?? ''} onChange={(event) => setBaseModelVersionId(event.target.value ? Number(event.target.value) : null)} disabled={!modelType}><option value="">从零开始训练</option>{availableModels.flatMap((model) => model.latest_version_id ? [<option key={model.latest_version_id} value={model.latest_version_id}>{model.name} {model.version ?? ''} · {modelMetricText(model.metric)}</option>] : [])}</select></div><div className="form-block"><label>训练数据集（可多选）</label><div className="training-dataset-options">{datasets.length ? datasets.map((dataset) => { const versionId = dataset.current_version_id; const selected = versionId != null && selectedDatasetIds.includes(versionId); const readiness = datasetReadiness[dataset.id]; const trainable = readiness === '可训练'; return <label className={`training-dataset-option ${selected ? 'selected' : ''}`} key={dataset.id}><input type="checkbox" disabled={versionId == null || readiness == null || !trainable} checked={selected} onChange={() => { if (versionId == null || !trainable) return; setSelectedDatasetIds((ids) => ids.includes(versionId) ? ids.filter((id) => id !== versionId) : [...ids, versionId]); }} /><span><strong>{dataset.name}</strong><small>{dataset.version ?? '暂无版本'} · {dataset.sample_count.toLocaleString()} 条样本 · {readiness ?? '检查中…'}</small></span></label>; }) : <p className="dataset-empty-state">暂无可用数据集。</p>}</div>{selectedDatasets.length > 0 && <small className="form-help">已选择 {selectedDatasets.length} 个数据集版本，共 {selectedDatasets.reduce((sum, dataset) => sum + dataset.sample_count, 0).toLocaleString()} 条样本</small>}</div><div className="parameter-grid"><div className="form-block"><label>训练轮数 <CircleHelp size={13} /></label><input className="input-field" type="number" min="1" value={config.epochs} readOnly /></div><div className="form-block"><label>批次大小 <CircleHelp size={16} /></label><input className="input-field" type="number" min="1" value={config.batch_size} readOnly /></div><div className="form-block"><label>学习率</label><input className="input-field" value={config.learning_rate} readOnly /></div><div className="form-block"><label>验证集比例</label><input className="input-field" value={`${config.val_ratio * 100}%`} readOnly /></div></div><button className="full-button" disabled={isTraining || !modelType || !selectedDatasetIds.length} onClick={handleStart}>{isTraining ? <><Activity size={16} />训练任务运行中</> : <><Play size={16} />开始训练任务</>}</button>{trainingError && <p className="dataset-empty-state" role="alert">{trainingError}</p>}</section><section className="panel training-chart-panel"><div className="panel-heading"><div><h2>训练表现</h2><p>{jobId ? `任务 #${jobId} · 实时更新` : '开始训练后，这里将展示训练表现'}</p></div><span className={`run-status ${isTraining ? 'running' : ''}`}><i />{jobStatus === 'succeeded' ? '已完成' : jobStatus === 'failed' ? '失败' : isTraining ? `运行中 ${progress}%` : '未开始'}</span></div><div className="metric-row"><div><span>mAP@50</span><strong>{mAP}</strong></div><div><span>精确率</span><strong>{precision}</strong></div><div><span>召回率</span><strong>{recall}</strong></div></div>{loss ? <><div className="line-chart"><div className="chart-y"><span>1.0</span><span>0.8</span><span>0.6</span><span>0.4</span><span>0.2</span><span>0</span></div><svg viewBox="0 0 600 250" preserveAspectRatio="none" role="img" aria-label="训练指标曲线"><path d={trainPath} fill="none" stroke="#1d8fa5" strokeWidth="4" /><path d={valPath} fill="none" stroke="#f0a34a" strokeWidth="3" strokeDasharray="7 7" /></svg><div className="chart-x"><span>0</span><span>10</span><span>20</span><span>30</span><span>40</span><span>{config.epochs} epochs</span></div></div><div className="chart-key"><span><i className="legend-blue" />训练损失</span><span><i className="legend-orange" />验证损失</span></div></> : <div className="training-empty-state"><BarChart3 size={30} /><span>训练开始后显示指标和损失曲线</span></div>}</section></div><div className="training-note"><Terminal size={17} /><div><strong>训练日志</strong><p>{logs ?? (jobId ? '等待训练任务日志…' : '暂无训练日志')}</p></div><button className="ghost-button" disabled={!jobId} onClick={handleLogs}>查看完整日志 <ArrowUpRight size={14} /></button></div></div>;
}
export default App;
