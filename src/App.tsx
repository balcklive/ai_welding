import { useEffect, useRef, useState } from 'react';
import {
  Activity, Archive, ArrowUpRight, BarChart3, Bell, Box, Check, ChevronDown,
  CircleHelp, Database, Factory, FileCheck2, Filter, Gauge, Layers3,
  MoreHorizontal, Play, Plus, Search, Settings2, SlidersHorizontal, Sparkles,
  Tag, Terminal, TrainFront, Upload, Users, WandSparkles, Waves, Zap,
  ClipboardCheck, FileText, GitBranch, ScanLine, Download, CheckCircle2,
  AlertTriangle, Eye, RefreshCw, ChevronLeft, ChevronRight, Cpu,
  Filter as FilterIcon, Sigma, Image as ImageIcon, AudioWaveform, Boxes,
} from 'lucide-react';
import { getToken } from './api/client';
import {
  getAttributes,
  getDistributions,
  getProjects,
  getStats,
} from './api/dashboard';
import {
  attachRawFiles,
  createRegistration,
  getValidation,
  getWeld,
  listVersions,
  listWelds,
  runValidation,
} from './api/welds';
import {
  createDataset,
  createDatasetVersion,
  getDataset,
  getDimensions,
  getLineage,
  getReadiness,
  listDatasetVersions,
  listDatasets,
} from './api/datasets';
import {
  aiPretag,
  createAlignmentTask,
  createAnnotationTask,
  createSplitTask,
  extractFeatures,
  getAnalysisMode,
  getAnalysisResult,
  getAnnotationSample,
  getSignals,
  listAnnotationSamples,
  listCandidates,
  listLabelCategories,
  saveAnnotation,
} from './api/analysis';
import { getFileUrl, presignUpload, uploadFile } from './api/files';
import {
  createInferenceTask,
  createModel,
  createTestTask,
  createTrainingTask,
  getTrainingLogs,
  listModels,
} from './api/models';
import { exportReport } from './api/reports';
import { useJob } from './hooks/useJob';
import type {
  AlignmentResult,
  AnalysisResult,
  Annotation as AnnotationLabel,
  DashboardAttributes,
  DashboardDistributions,
  DashboardStats,
  DataRecord,
  Dataset,
  DatasetVersion,
  DataVersion,
  DimensionStatus,
  DwtData,
  FeatureExtraction,
  InferenceResult,
  LabelCategory,
  LabelItem,
  LineageNode,
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
const overviewImage = 'https://images.pexels.com/photos/14804699/pexels-photo-14804699.jpeg?auto=compress&cs=tinysrgb&h=650&w=940';
const labelImage = 'https://images.pexels.com/photos/13296053/pexels-photo-13296053.jpeg?auto=compress&cs=tinysrgb&h=650&w=940';
const modelImage = 'https://images.pexels.com/photos/11951215/pexels-photo-11951215.jpeg?auto=compress&cs=tinysrgb&h=650&w=940';
const detailImage = 'https://images.pexels.com/photos/36522029/pexels-photo-36522029.jpeg?auto=compress&cs=tinysrgb&h=650&w=940';

type Route = 'overview' | 'data-center/list' | 'data-center/datasets' | 'data-center/registration' | 'data-center/validation' | 'data-center/versions' | 'analysis/select' | 'analysis/alignment' | 'analysis/analysis' | 'analysis/split' | 'analysis/annotation' | 'analysis/features' | 'model-center/repository' | 'model-center/training' | 'model-center/testing' | 'model-center/inference';

const workspaceHeaders: Record<string, { eyebrow: string; title: string; description: string }> = {
  'data-center': { eyebrow: '数据资产中心', title: '数据中心', description: '以单条焊缝数据为单位，管理登记信息、质量核验和版本链路。' },
  'analysis': { eyebrow: '多模态数据生产线', title: '分析与标注', description: '选择一条焊缝后，完成对齐、信号分析、切分与标注。' },
  'model-center': { eyebrow: '模型研发中心', title: '模型中心', description: '统一管理模型版本、训练任务、测试评估与推理验证。' },
};

const navStructure: { id: string; label: string; icon: typeof BarChart3; route?: Route; children?: { route: Route; label: string }[] }[] = [
  { id: 'overview', label: '数据总览', icon: BarChart3, route: 'overview' },
  { id: 'data-center', label: '数据中心', icon: Database, children: [
    { route: 'data-center/list', label: '数据列表' },
    { route: 'data-center/datasets', label: '数据集' },
    { route: 'data-center/registration', label: '数据登记' },
    { route: 'data-center/validation', label: '数据核验' },
    { route: 'data-center/versions', label: '数据版本' },
  ] },
  { id: 'analysis', label: '分析与标注', icon: Waves, children: [
    { route: 'analysis/select', label: '选择数据' },
    { route: 'analysis/alignment', label: '多模态对齐' },
    { route: 'analysis/analysis', label: '信号分析' },
    { route: 'analysis/split', label: '数据切分' },
    { route: 'analysis/annotation', label: '数据标注' },
    { route: 'analysis/features', label: '特征提取' },
  ] },
  { id: 'model-center', label: '模型中心', icon: TrainFront, children: [
    { route: 'model-center/repository', label: '模型仓库' },
    { route: 'model-center/training', label: '新建训练' },
    { route: 'model-center/testing', label: '测试评估' },
    { route: 'model-center/inference', label: '推理验证' },
  ] },
];

const routesRequiringData: Route[] = ['data-center/registration', 'data-center/validation', 'data-center/versions', 'analysis/alignment', 'analysis/analysis', 'analysis/split', 'analysis/annotation', 'analysis/features'];
const mockProjects: ProjectCard[] = [
  { name: '焊接缺陷检测 · 主数据集', count: '1,209', status: '已完成', tone: 'green', progress: '100%' },
  { name: '表面质量巡检数据', count: '842', status: '标注中', tone: 'blue', progress: '68%' },
  { name: '红外热成像样本', count: '367', status: '待处理', tone: 'orange', progress: '24%' },
];
const bars = [46, 58, 52, 67, 61, 78, 74, 92, 81, 88, 72, 96];

function AppShell() {
  const [route, setRoute] = useState<Route>('overview');
  const [selectedDataId, setSelectedDataId] = useState<string | null>(null);
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set());
  const workspace = route.split('/')[0];
  const navigate = (r: Route) => {
    setRoute(r);
    setExpandedGroups((prev) => new Set(prev).add(r.split('/')[0]));
  };
  const toggleGroup = (id: string) => setExpandedGroups((prev) => {
    const next = new Set(prev);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });
  const isRouteDisabled = (r: Route) => routesRequiringData.includes(r) && !selectedDataId;

  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand-mark"><Sparkles size={18} strokeWidth={2.5} /></div><div className="brand-copy"><strong>ForgeLab</strong><span>工业智能实验室</span></div>
      <div className="workspace-label">工作空间</div><nav className="main-nav">{navStructure.map((group) => {
        const Icon = group.icon;
        if (group.route) {
          return <button key={group.id} className={`nav-item ${route === group.route ? 'active' : ''}`} onClick={() => navigate(group.route!)}><Icon size={18} /><span>{group.label}</span>{route === group.route && <span className="nav-pip" />}</button>;
        }
        const isExpanded = expandedGroups.has(group.id) || workspace === group.id;
        return <div key={group.id} className="nav-group">
          <button className={`nav-item ${workspace === group.id ? 'active' : ''}`} onClick={() => toggleGroup(group.id)}><Icon size={18} /><span>{group.label}</span><ChevronDown size={15} className={`nav-chevron ${isExpanded ? 'expanded' : ''}`} /></button>
          {isExpanded && <div className="nav-submenu">{group.children!.map((child) => <button key={child.route} className={`nav-subitem ${route === child.route ? 'active' : ''}`} disabled={isRouteDisabled(child.route)} onClick={() => navigate(child.route)}><span className="nav-sub-dot" />{child.label}</button>)}</div>}
        </div>;
      })}</nav>
      <div className="sidebar-bottom"><button className="nav-item"><Settings2 size={18} /><span>系统设置</span></button><div className="user-card"><div className="avatar">林</div><div><strong>林工</strong><span>管理员</span></div><MoreHorizontal size={16} /></div></div>
    </aside>
    <main className="main-content">
      {route === 'overview' && <Overview navigate={navigate} />}
      {route !== 'overview' && <WorkspaceFrame route={route} selectedDataId={selectedDataId} setSelectedDataId={setSelectedDataId} navigate={navigate} />}
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

function WorkspaceFrame({ route, selectedDataId, setSelectedDataId, navigate }: { route: Route; selectedDataId: string | null; setSelectedDataId: (id: string) => void; navigate: (r: Route) => void }) {
  const ws = route.split('/')[0];
  const header = workspaceHeaders[ws];
  // 模型仓库刷新计数（「新建模型」成功后自增，触发 ModelRepository 重新拉取）。
  const [repoRefresh, setRepoRefresh] = useState(0);
  const toolbarConfig = ws === 'data-center' ? { action: '上传数据', secondary: '导出报告' }
    : route === 'analysis/annotation' ? { action: '保存标注', secondary: '导出结果' }
    : ws === 'analysis' ? { action: '开始处理', secondary: '导出结果' }
    : route === 'model-center/training' ? { action: '开始训练', secondary: '导出报告' }
    : { action: '新建模型', secondary: '导出报告' };
  // 当前页/工作区 → 报告导出 type（§3.7）：data-list/validation/analysis/annotation/features/test。
  const exportType = ws === 'data-center' ? 'data-list'
    : route === 'analysis/annotation' ? 'annotation'
    : route === 'analysis/features' ? 'features'
    : ws === 'analysis' ? 'analysis'
    : ws === 'model-center' ? 'test'
    : undefined;
  const handleRepoCreate = () => {
    createModel({ name: `新模型-${new Date().toISOString().slice(0, 16).replace(/[T:]/g, '')}`, type: '目标检测' })
      .then(() => setRepoRefresh((v) => v + 1))
      .catch((err) => console.warn('[model-center] createModel failed', err));
  };
  const showContext = selectedDataId && (ws === 'data-center' || ws === 'analysis');

  let content: React.ReactNode = null;
  if (route === 'data-center/list') content = <ManagementFiltered navigate={navigate} selectedDataId={selectedDataId} setSelectedDataId={setSelectedDataId} />;
  else if (route === 'data-center/datasets') content = <DatasetWorkspace navigate={navigate} />;
  else if (route === 'data-center/registration') content = selectedDataId ? <Registration embedded /> : <SelectionRequired onBack={() => navigate('data-center/list')} />;
  else if (route === 'data-center/validation') content = selectedDataId ? <Validation embedded dataId={selectedDataId!} /> : <SelectionRequired onBack={() => navigate('data-center/list')} />;
  else if (route === 'data-center/versions') content = selectedDataId ? <VersionPanel dataId={selectedDataId!} /> : <SelectionRequired onBack={() => navigate('data-center/list')} />;
  else if (route === 'analysis/select') content = <AnalysisSelect onContinue={(id: string) => { setSelectedDataId(id); navigate('analysis/alignment'); }} />;
  else if (route === 'analysis/alignment') content = selectedDataId ? <Alignment embedded dataId={selectedDataId!} /> : <SelectionRequired onBack={() => navigate('analysis/select')} />;
  else if (route === 'analysis/analysis') content = selectedDataId ? <AdvancedWeldAnalysis embedded dataId={selectedDataId!} /> : <SelectionRequired onBack={() => navigate('analysis/select')} />;
  else if (route === 'analysis/split') content = selectedDataId ? <Alignment embedded splitOnly dataId={selectedDataId!} /> : <SelectionRequired onBack={() => navigate('analysis/select')} />;
  else if (route === 'analysis/annotation') content = selectedDataId ? <Annotation embedded /> : <SelectionRequired onBack={() => navigate('analysis/select')} />;
  else if (route === 'analysis/features') content = selectedDataId ? <FeatureExtraction embedded dataId={selectedDataId!} /> : <SelectionRequired onBack={() => navigate('analysis/select')} />;
  else if (route === 'model-center/repository') content = <ModelRepository refreshKey={repoRefresh} />;
  else if (route === 'model-center/training') content = <><DatasetTrainingContext /><Training embedded /></>;
  else if (route === 'model-center/testing') content = <><DatasetTestingContext /><ModelTest embedded /></>;
  else if (route === 'model-center/inference') content = <InferencePanel />;

  return <div className="workspace-page"><div className="workspace-page-head"><div><div className="eyebrow"><span />{header.eyebrow}</div><h1>{header.title}</h1><p>{header.description}</p></div><Toolbar action={toolbarConfig.action} secondary={toolbarConfig.secondary} exportType={exportType} onAction={route === 'model-center/repository' ? handleRepoCreate : undefined} /></div>{showContext && <SelectionContext dataId={selectedDataId!} />}{content}</div>;
}

function PageIntro({ eyebrow, title, description, action }: { eyebrow: string; title: string; description: string; action?: React.ReactNode }) { return <div className="page-intro"><div><div className="eyebrow"><span />{eyebrow}</div><h1>{title}</h1><p>{description}</p></div>{action}</div>; }
const mockManufacturers = [
  { name: '中车四方', value: 28, tone: '#2c9caf' },
  { name: '中船重工', value: 22, tone: '#5fb8a6' },
  { name: '中集集团', value: 16, tone: '#f0a34a' },
  { name: '三一重工', value: 12, tone: '#e88d6c' },
  { name: '徐工集团', value: 9, tone: '#7ba7c4' },
  { name: '其他厂商', value: 13, tone: '#b0c4b8' },
];
const mockTransitionTypes = [
  { name: '短路过渡', value: 32, tone: '#2c9caf' },
  { name: '射流过渡', value: 26, tone: '#5fb8a6' },
  { name: '混合过渡', value: 22, tone: '#f0a34a' },
  { name: 'CMT', value: 14, tone: '#e88d6c' },
  { name: '脉冲过渡', value: 6, tone: '#7ba7c4' },
];
const mockDefectTypes = [
  { name: '气孔', count: 1086, tone: '#2c9caf' },
  { name: '焊瘤', count: 842, tone: '#5fb8a6' },
  { name: '未焊透', count: 624, tone: '#f0a34a' },
  { name: '焊穿', count: 467, tone: '#e88d6c' },
  { name: '咬边', count: 312, tone: '#7ba7c4' },
  { name: '夹渣', count: 293, tone: '#b0c4b8' },
];
const mockWeldingTypes = [
  { name: 'MAG焊', value: 30, tone: '#2c9caf' },
  { name: 'MIG焊', value: 24, tone: '#5fb8a6' },
  { name: 'TIG焊', value: 18, tone: '#f0a34a' },
  { name: '埋弧焊', value: 14, tone: '#e88d6c' },
  { name: '等离子焊', value: 9, tone: '#7ba7c4' },
  { name: '激光焊', value: 5, tone: '#b0c4b8' },
];
const mockWordCloud = [
  { name: '中车四方', size: 34 },
  { name: '中船重工', size: 29 },
  { name: '中集集团', size: 24 },
  { name: '三一重工', size: 20 },
  { name: '徐工集团', size: 17 },
  { name: '宝武钢铁', size: 15 },
  { name: '振华重工', size: 13 },
  { name: '大连船舶', size: 12 },
  { name: '沪东中华', size: 11 },
  { name: '江南造船', size: 10 },
  { name: '中冶集团', size: 9 },
  { name: '长城汽车', size: 9 },
  { name: '比亚迪', size: 8 },
  { name: '格力电器', size: 8 },
  { name: '中核集团', size: 7 },
  { name: '东方电气', size: 7 },
  { name: '哈电集团', size: 6 },
  { name: '上海电气', size: 6 },
];
const mockWeldingMachines = ['Fronius CMT', 'Kemppi Minarc', 'OTC FD-V8', 'Panasonic YD-500', 'Lincoln Power Wave', 'ESAB Aristo', '唐山松下', '奥太 NBC-350'];

// ── 总览/数据列表 API 接线辅助（Task 21） ─────────────────────────────
/** 分布/缺陷统一色调板（复用 mock 常量 tone，API 数据按序取色）。 */
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

/** 总览统计卡：getStats 的 mock 初始值（对齐原硬编码展示）。 */
const mockStats: DashboardStats = {
  data_total: 12847,
  manufacturer_total: 18,
  max_storage_bytes: 2.4 * 1024 * 1024 * 1024,
  annotated_samples: 10038,
  annotation_completion: 78.1,
};

/** 总览属性面板：getAttributes 的 mock 初始值（数据形状对齐响应）。 */
const mockAttributes: DashboardAttributes = {
  weld_methods: mockWeldingMachines,
  defect_types: mockDefectTypes.map((d) => ({ name: d.name, count: d.count })),
  modalities: ['video', 'timeseries', 'audio', 'infrared'],
  sample_rate_tiers: ['1 kHz', '5 kHz', '10 kHz', '20 kHz', '50 kHz'],
};

/** 数据项目卡片展示形状（progress 已字符串化为 "68%"）。 */
interface ProjectCard {
  name: string;
  count: string;
  status: string;
  tone: string;
  progress: string;
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
  const [stats, setStats] = useState<DashboardStats>(mockStats);
  const [attrs, setAttrs] = useState<DashboardAttributes>(mockAttributes);
  const [dist, setDist] = useState<DashboardDistributions>({
    manufacturers: mockManufacturers.map((m) => ({ name: m.name, value: m.value })),
    transition_types: mockTransitionTypes.map((t) => ({ name: t.name, value: t.value })),
    welding_types: mockWeldingTypes.map((t) => ({ name: t.name, value: t.value })),
    defects: mockDefectTypes.map((d) => ({ name: d.name, count: d.count })),
    wordcloud: mockWordCloud,
  });
  const [projects, setProjects] = useState<ProjectCard[]>(mockProjects);
  const filteredProjects = projects;

  useEffect(() => {
    getStats().then(setStats).catch((err) => console.warn('[overview] getStats failed', err));
    getAttributes().then(setAttrs).catch((err) => console.warn('[overview] getAttributes failed', err));
    getDistributions().then(setDist).catch((err) => console.warn('[overview] getDistributions failed', err));
    getProjects().then((list) => setProjects(list.map(mapProject))).catch((err) => console.warn('[overview] getProjects failed', err));
  }, []);

  const freqValues = attrs.sample_rate_tiers.map(parseFreq).filter((n) => n > 0);
  const freqMin = freqValues.length ? Math.min(...freqValues) : 1;
  const freqMax = freqValues.length ? Math.max(...freqValues) : 50;
  const maxDefectCount = Math.max(1, ...dist.defects.map((d) => d.count));

  return <div className="page-wrap"><PageIntro eyebrow="数据资产中心" title="数据总览" description="全面掌握焊接数据资产的规模、来源与质量分布。" />
    <div className="stat-grid"><StatCard icon={Database} label="数据总量" value={stats.data_total.toLocaleString()} sub="条焊缝数据" /><StatCard icon={Factory} label="厂商总量" value={String(stats.manufacturer_total)} sub="家合作厂商" /><StatCard icon={Box} label="单条焊缝最大容量" value={`${(stats.max_storage_bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`} sub={`含缺陷样本 ${stats.annotated_samples.toLocaleString()} 条`} /><StatCard icon={FileCheck2} label="已标注样本" value={stats.annotated_samples.toLocaleString()} sub={`完成度 ${stats.annotation_completion}%`} /></div>

    <div className="attr-grid">
      <section className="panel attr-panel"><div className="attr-head"><Factory size={16} /><h2>焊机种类</h2><span className="attr-count">{attrs.weld_methods.length} 种</span></div><div className="attr-tags">{attrs.weld_methods.map((machine) => <span className="attr-tag" key={machine}>{machine}</span>)}</div></section>
      <section className="panel attr-panel"><div className="attr-head"><WandSparkles size={16} /><h2>缺陷种类</h2><span className="attr-count">{attrs.defect_types.length} 种</span></div><div className="attr-tags">{attrs.defect_types.map((defect, index) => <span className="attr-tag attr-tag-defect" key={defect.name}><i style={{ background: donutPalette[index % donutPalette.length] }} />{defect.name}</span>)}</div></section>
      <section className="panel attr-panel"><div className="attr-head"><Layers3 size={16} /><h2>多模态种类</h2><span className="attr-count">{attrs.modalities.length} 种</span></div><div className="modality-list">{attrs.modalities.map((token) => { const m = modalityMeta[token] ?? { name: token, icon: Boxes, desc: '多模态数据' }; const Icon = m.icon; return <div className="modality-item" key={token}><Icon size={15} /><div><strong>{m.name}</strong><span>{m.desc}</span></div></div>; })}</div></section>
      <section className="panel attr-panel"><div className="attr-head"><Gauge size={16} /><h2>时序数据采集频率</h2></div><div className="freq-display"><div className="freq-item"><span>最低频率</span><strong>{freqMin} kHz</strong></div><div className="freq-bar"><div className="freq-fill" /><div className="freq-dot" /><div className="freq-dot freq-dot-max" /></div><div className="freq-item"><span>最高频率</span><strong>{freqMax} kHz</strong></div></div><p className="freq-note">覆盖 {attrs.sample_rate_tiers.length} 个采样档位，支持多速率同步采集</p></section>
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

    <div className="section-title"><div><h2>数据项目</h2><p>共 {filteredProjects.length} 个项目正在协作</p></div><button className="ghost-button"><Filter size={15} />筛选</button></div><div className="dataset-grid">{filteredProjects.map((project, index) => <div className={`dataset-card ${index === activeProject ? 'current' : ''}`} key={project.name}><div className="dataset-top"><div className={`dataset-icon ${project.tone}`}><Box size={18} /></div><span className={`status ${project.tone}`}>{project.status}</span><MoreHorizontal size={17} className="muted-icon" /></div><h3>{project.name}</h3><p>最近更新于今天 09:42 · 多模态数据</p><div className="progress-meta"><span>标注进度</span><strong>{project.progress}</strong></div><div className="progress"><span style={{ width: project.progress }} /></div><div className="dataset-footer"><span><Layers3 size={14} />{project.count} 条样本</span><button onClick={() => navigate('analysis/select')}>查看详情 <ArrowUpRight size={14} /></button></div></div>)}</div>
    <img className="hidden-reference" src={overviewImage} alt="" />
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
function Annotation({ embedded = false }: { embedded?: boolean }) {
  const [saved, setSaved] = useState(false);
  const [selectedLabels, setSelectedLabels] = useState(['焊瘤', '气孔']);
  const [labels, setLabels] = useState<LabelCategory[]>(mockLabelCategories);
  const [taskId, setTaskId] = useState<string | null>(null);
  const [sample, setSample] = useState<Sample | null>(null);
  const [sampleImg, setSampleImg] = useState(labelImage);
  const [aiBoxes, setAiBoxes] = useState<AnnotationLabel[]>([]);
  const [totalSamples, setTotalSamples] = useState(1209);
  const creatingRef = useRef(false);
  const { status: jobStatus } = useJob<unknown>(taskId);
  const toggleLabel = (label: string) => setSelectedLabels((current) => current.includes(label) ? current.filter((item) => item !== label) : [...current, label]);
  useEffect(() => {
    let cancelled = false;
    listLabelCategories().then((list) => { if (!cancelled && list.length) setLabels(list); }).catch((err) => { if (!cancelled) console.warn('[annotation] listLabelCategories failed', err); });
    return () => { cancelled = true; };
  }, []);
  // 挂载时创建标注任务（best-effort：手动选样源），任务成功后拉取首个样本
  useEffect(() => {
    if (creatingRef.current) return;
    creatingRef.current = true;
    let cancelled = false;
    createAnnotationTask({ source: 'manual', name: 'AN-演示' }).then((res) => { if (!cancelled) setTaskId(res.job_id); }).catch((err) => { if (!cancelled) console.warn('[annotation] createAnnotationTask failed', err); });
    return () => { cancelled = true; };
  }, []);
  useEffect(() => {
    if (!taskId || jobStatus !== 'succeeded') return;
    let cancelled = false;
    listAnnotationSamples(taskId, 1).then((page) => {
      if (cancelled) return;
      setTotalSamples(page.total || 1209);
      const first = page.items[0];
      if (!first) return;
      getAnnotationSample(taskId, String(first.id)).then((s) => {
        if (cancelled) return;
        setSample(s);
        setAiBoxes(s.annotations ?? []);
        if (s.object_keys && s.object_keys.length) {
          getFileUrl(s.object_keys[0]).then((r) => { if (!cancelled) setSampleImg(r.url); }).catch((err) => { if (!cancelled) console.warn('[annotation] getFileUrl failed', err); });
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
    const fallbackBoxes: { category: string; box: number[]; confidence: number | null }[] = [
      { category: '焊瘤', box: [128, 182, 186, 106], confidence: 0.94 },
      { category: '气孔', box: [378, 250, 109, 77], confidence: 0.88 },
    ];
    const boxes = aiBoxes.length ? aiBoxes.map((b) => ({ category: b.category, box: b.box, confidence: b.confidence })) : fallbackBoxes;
    const labelsToSave: LabelItem[] = selectedLabels.length
      ? selectedLabels.map((cat) => { const ex = boxes.find((b) => b.category === cat); return { category: cat, box: ex && ex.box.length === 4 ? ex.box : [128, 182, 186, 106], confidence: ex?.confidence ?? null }; })
      : boxes.map((b) => ({ category: b.category, box: b.box }));
    saveAnnotation(taskId, String(sample.id), labelsToSave).then(() => setSaved(true)).catch((err) => { console.warn('[annotation] saveAnnotation failed', err); setSaved(true); });
  };
  const frameLabel = sample?.frame_no != null ? String(sample.frame_no).padStart(4, '0') : '0248';
  const confidence = sample?.confidence != null ? `${(sample.confidence * 100).toFixed(1)}%` : '94.2%';
  return <div className={embedded ? 'embedded-page' : 'page-wrap'}><PageIntro eyebrow="数据生产线" title="数据标注" description="为模型准备高质量训练样本，支持多模态协同标注。" action={<><button className="outline-button"><Upload size={16} />导入数据</button><button className="primary-button" onClick={handleSave}>{saved ? <Check size={16} /> : <Plus size={16} />}{saved ? '已保存' : '保存标注'}</button></>} /><div className="annotation-layout"><section className="panel annotation-board"><div className="board-toolbar"><div><span className="file-badge"><Archive size={15} />样本 {frameLabel} / {totalSamples.toLocaleString()}</span><h2>焊接件 · 视觉质检样本</h2></div><div className="toolbar-actions"><button className="icon-button" onClick={handleAiPretag} title="AI 预标注"><SlidersHorizontal size={17} /></button><button className="select-button">图像标注 <ChevronDown size={14} /></button></div></div><div className="image-stage"><img src={sampleImg} alt="待标注焊接样本" />{aiBoxes.length ? aiBoxes.map((a, i) => { const [bx, by, bw, bh] = a.box.length === 4 ? a.box : [128, 182, 186, 106]; return <div key={a.id ?? i} className="annotation-box" style={{ left: `${(bx / 640) * 100}%`, top: `${(by / 480) * 100}%`, width: `${(bw / 640) * 100}%`, height: `${(bh / 480) * 100}%` }}><span>{a.category} {a.confidence != null ? <b>{a.confidence.toFixed(2)}</b> : null}</span></div>; }) : <><div className="annotation-box box-one"><span>焊瘤 <b>0.94</b></span></div><div className="annotation-box box-two"><span>气孔 <b>0.88</b></span></div></>}<div className="stage-tip"><Sparkles size={14} />AI 已预标注 {aiBoxes.length || 2} 个区域</div></div><div className="board-footer"><div className="thumb-strip"><img src={detailImage} alt="样本缩略图" /><img className="thumb-active" src={sampleImg} alt="当前样本缩略图" /><img src={modelImage} alt="样本缩略图" /><span>+ 9</span></div><div className="pagination"><button>‹</button><span>1 / 12</span><button>›</button></div></div></section><aside className="annotation-side"><section className="panel label-panel"><div className="panel-heading"><div><h2>标签类别</h2><p>选择需要应用的缺陷标签</p></div><button className="more-button"><MoreHorizontal size={18} /></button></div><div className="label-options">{labels.map((label, index) => <button className={`label-chip ${selectedLabels.includes(label.name) ? 'chosen' : ''}`} onClick={() => toggleLabel(label.name)} key={label.name}><i className={`chip-dot chip-${index % 5}`} />{label.name}<span>{selectedLabels.includes(label.name) ? <Check size={14} /> : '+'}</span></button>)}</div></section><section className="panel annotation-info"><div className="panel-heading"><div><h2>标注信息</h2><p>当前样本的详细信息</p></div></div><InfoRow label="数据来源" value="产线相机 · 03 号" /><InfoRow label="采集时间" value="2026-08-14 18:32" /><InfoRow label="标注人员" value="林工（我）" /><InfoRow label="置信度" value={confidence} accent /></section><div className="ai-card"><div className="ai-card-icon"><Zap size={17} /></div><div><strong>智能标注建议</strong><p>已为你识别 {aiBoxes.length || 2} 个疑似缺陷区域，建议确认后提交。</p></div></div></aside></div></div>;
}
function SelectionContext({ dataId }: { dataId: string }) {
  const [row, setRow] = useState<WeldRow>(() => mockWeldRows.find((item) => item.id === dataId) ?? mockWeldRows[0]);
  useEffect(() => {
    let cancelled = false;
    getWeld(dataId)
      .then((r) => { if (!cancelled) setRow(toWeldRow(r)); })
      .catch((err) => { if (!cancelled) console.warn('[selection] getWeld failed', err); });
    return () => { cancelled = true; };
  }, [dataId]);
  return <div className="selection-context"><div><span>当前选中数据</span><strong>{row.id}</strong></div><div><span>数据来源</span><strong>{row.source}</strong></div><div><span>焊机</span><strong>{row.machine}</strong></div><div><span>当前版本</span><strong>{row.version}</strong></div><StatusPill tone={row.quality === '异常' ? 'red' : row.quality === '待复核' ? 'orange' : 'green'}>{row.quality}</StatusPill></div>;
}

function SelectionRequired({ onBack }: { onBack: () => void }) {
  return <div className="selection-required"><div className="selection-icon"><Database size={23} /></div><h2>请先选择一条数据</h2><p>该功能需要基于具体焊缝数据执行，请返回数据列表选择后继续。</p><button className="outline-button" onClick={onBack}><ChevronLeft size={14} />返回数据列表</button></div>;
}

/** 数据集列表/详情行展示形状（table/detail 期望的字段）。 */
interface DatasetRow {
  id: string;
  name: string;
  task: string;
  samples: string;
  source: string;
  progress: string;
  version: string;
  status: string;
  tone: 'green' | 'orange';
  split: string;
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
    name: d.name,
    task: d.task,
    samples: d.sample_count.toLocaleString(),
    source: '多模态数据',
    progress: `${d.progress ?? 0}%`,
    version: d.version ?? '—',
    status: d.status,
    tone: d.status === '可训练' ? 'green' : 'orange',
    split,
  };
}
const mockDatasetRows: DatasetRow[] = [
  { id: 'DS-DEFECT-001', name: '焊接缺陷检测集', task: '目标检测', samples: '8,420', source: '产线相机 · 多品牌', progress: '96.8%', version: 'v1.3', status: '可训练', tone: 'green', split: '6,736 / 842 / 842' },
  { id: 'DS-POOL-002', name: '熔池分割数据集', task: '语义分割', samples: '5,680', source: '高速相机 · Fronius', progress: '91.2%', version: 'v0.8', status: '标注中', tone: 'orange', split: '4,544 / 568 / 568' },
  { id: 'DS-QUALITY-003', name: '工艺质量预测集', task: '多模态回归', samples: '2,140', source: '产线相机 · 多模态', progress: '100%', version: 'v2.0', status: '可训练', tone: 'green', split: '1,712 / 214 / 214' },
];
const inputDimensions = ['Voltage', 'GasSpeed', 'Current', 'Molten_feature', 'Sound_feature', '焊缝照片', '熔池视频'];
const requiredByTask: Record<string, string[]> = { '目标检测': ['Current', 'Voltage', 'GasSpeed'], '语义分割': ['熔池视频'], '多模态回归': ['Current', 'Voltage'] };
const mockDimensions: DimensionStatus[] = inputDimensions.map((dim) => {
  const isRequired = requiredByTask['目标检测']?.includes(dim) ?? false;
  const isAvailable = ['Current', 'Voltage', 'GasSpeed', 'Molten_feature', 'Sound_feature'].includes(dim);
  return { name: dim, status: isAvailable ? '已具备' : isRequired ? '必需' : '缺失', required: isRequired };
});
const mockDatasetVersions: DatasetVersion[] = [
  { id: 2, dataset_id: 1, version_no: 'v1.3', split: { train: 6736, val: 842, test: 842 }, item_count: 8420, snapshot_id: null, quality: null, created_at: '2026-08-15 10:06:00' },
  { id: 1, dataset_id: 1, version_no: 'v1.2', split: { train: 6483, val: 811, test: 810 }, item_count: 8104, snapshot_id: null, quality: null, created_at: '2026-08-14 18:20:00' },
];
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

function DatasetWorkspace({ navigate }: { navigate: (route: Route) => void }) {
  const [rows, setRows] = useState<DatasetRow[]>(mockDatasetRows);
  const [selectedId, setSelectedId] = useState(mockDatasetRows[0].id);
  const [view, setView] = useState<'list' | 'detail'>('list');
  const dataset = rows.find((item) => item.id === selectedId) ?? rows[0];
  useEffect(() => {
    let cancelled = false;
    listDatasets().then((list) => {
      if (cancelled) return;
      const mapped = list.map(toDatasetRow);
      setRows(mapped);
      setSelectedId((prev) => (mapped.some((r) => r.id === prev) ? prev : mapped[0]?.id ?? prev));
    }).catch((err) => { if (!cancelled) console.warn('[datasets] listDatasets failed', err); });
    return () => { cancelled = true; };
  }, []);
  const reload = () => listDatasets().then((list) => { const mapped = list.map(toDatasetRow); setRows(mapped); setSelectedId((prev) => (mapped.some((r) => r.id === prev) ? prev : mapped[0]?.id ?? prev)); });
  const handleCreate = () => {
    const name = window.prompt('新建数据集名称', '新建数据集');
    createDataset({ name: name?.trim() || '新建数据集', task: '目标检测' }).then(reload).catch((err) => console.warn('[datasets] createDataset failed', err));
  };
  return <div className="dataset-workspace"><div className="dataset-toolbar"><div><h2>数据集维护</h2><p>将已切分、已标注的样本固化为可复现的数据集版本，供训练和测试使用。</p></div><button className="primary-button" onClick={handleCreate}><Plus size={15} />新建数据集</button></div><div className="dataset-subtabs"><button className={view === 'list' ? 'active' : ''} onClick={() => setView('list')}>数据集列表 <b>{rows.length}</b></button><button className={view === 'detail' ? 'active' : ''} onClick={() => setView('detail')}>数据集详情</button></div>{view === 'list' ? <><div className="dataset-rule"><GitBranch size={14} /><span>数据集以版本快照形式保存，不直接读取会持续变化的原始数据。</span><span className="dataset-rule-count">可训练 {rows.filter((item) => item.status === '可训练').length} 个</span></div><div className="dataset-table">{rows.map((item) => <button className={`dataset-list-row ${selectedId === item.id ? 'selected' : ''}`} onClick={() => { setSelectedId(item.id); setView('detail'); }} key={item.id}><span className="dataset-row-icon"><Box size={17} /></span><span className="dataset-row-main"><strong>{item.name}</strong><small>{item.id} · {item.task}</small></span><span><small>样本数</small><strong className="mono">{item.samples}</strong></span><span><small>标注完成度</small><strong className="mono">{item.progress}</strong></span><span><small>当前版本</small><strong className="mono">{item.version}</strong></span><StatusPill tone={item.tone as 'green' | 'orange'}>{item.status}</StatusPill><ArrowUpRight size={15} className="muted-icon" /></button>)}</div></> : <DatasetDetail dataset={dataset} navigate={navigate} />}</div>;
}

function DatasetDetail({ dataset, navigate }: { dataset: DatasetRow; navigate: (route: Route) => void }) {
  const [detail, setDetail] = useState<Dataset | null>(null);
  const [dims, setDims] = useState<DimensionStatus[]>(mockDimensions);
  const [readiness, setReadiness] = useState<ReadinessCheck | null>(null);
  const [versions, setVersions] = useState<DatasetVersion[]>(mockDatasetVersions);
  const [lineage, setLineage] = useState<LineageNode[]>(mockLineage);
  useEffect(() => {
    let cancelled = false;
    getDataset(dataset.id).then((d) => { if (!cancelled) setDetail(d); }).catch((err) => { if (!cancelled) console.warn('[datasets] getDataset failed', err); });
    getDimensions(dataset.id).then((list) => { if (!cancelled) setDims(list); }).catch((err) => { if (!cancelled) console.warn('[datasets] getDimensions failed', err); });
    getReadiness(dataset.id).then((r) => { if (!cancelled) setReadiness(r); }).catch((err) => { if (!cancelled) console.warn('[datasets] getReadiness failed', err); });
    listDatasetVersions(dataset.id).then((list) => { if (!cancelled) setVersions(list); }).catch((err) => { if (!cancelled) console.warn('[datasets] listDatasetVersions failed', err); });
    getLineage(dataset.id).then((list) => { if (!cancelled) setLineage(list); }).catch((err) => { if (!cancelled) console.warn('[datasets] getLineage failed', err); });
    return () => { cancelled = true; };
  }, [dataset.id]);
  const handleNewVersion = () => {
    const name = window.prompt('新版本名称', '');
    createDatasetVersion(dataset.id, { name: name?.trim() || undefined })
      .then(() => listDatasetVersions(dataset.id))
      .then((list) => setVersions(list))
      .catch((err) => console.warn('[datasets] createDatasetVersion failed', err));
  };
  const quality = detail?.quality;
  const qualityPct = quality ? `${((1 - quality.repeat_rate - quality.empty_label_rate - quality.dimension_missing_rate) * 100).toFixed(1)}%` : '98.4%';
  const updated = detail?.updated_at ? fmtDT(detail.updated_at) : '今天 10:06';
  const currentVersionId = detail?.current_version_id ?? versions[0]?.id ?? null;
  const lineageIcon: Record<string, typeof Database> = { records: Database, annotation_tasks: Tag, dataset_versions: Box, training_tasks: TrainFront };
  const lineageSuffix: Record<string, string> = { records: '条', training_tasks: '次', annotation_tasks: '个', dataset_versions: '个' };
  return <div className="dataset-detail"><div className="dataset-detail-head"><div><span className="file-badge"><Box size={14} />{dataset.id}</span><h2>{dataset.name} <em>{dataset.version}</em></h2><p>{dataset.task} · {dataset.source} · 最近更新 {updated}</p></div><div className="dataset-detail-actions"><StatusPill tone={dataset.tone as 'green' | 'orange'}>{dataset.status}</StatusPill><button className="primary-button" disabled={dataset.status !== '可训练'} onClick={() => navigate('model-center/training')}><Play size={14} />进入模型训练</button></div></div><div className="dataset-detail-grid"><div className="dataset-detail-stat"><span>样本总数</span><strong>{detail ? detail.sample_count.toLocaleString() : dataset.samples}</strong><small>已生成切分样本</small></div><div className="dataset-detail-stat"><span>标注完成度</span><strong>{dataset.progress}</strong><small>通过质检的标注</small></div><div className="dataset-detail-stat"><span>训练 / 验证 / 测试</span><strong>{dataset.split}</strong><small>按焊缝 ID 固定划分</small></div><div className="dataset-detail-stat"><span>数据质量</span><strong>{qualityPct}</strong><small>重复与空标注已检查</small></div></div><DatasetInputPanel task={dataset.task} dims={dims} /><ModelReadiness task={dataset.task} status={dataset.status} readiness={readiness} /><div className="dataset-detail-columns"><section className="panel"><div className="panel-heading"><div><h2>数据集版本</h2><p>每个版本对应一份固定样本清单</p></div><button className="outline-button" onClick={handleNewVersion}><GitBranch size={14} />新建版本</button></div><div className="dataset-version-list">{versions.map((v) => <div className={`dataset-version ${v.id === currentVersionId ? 'current' : ''}`} key={v.version_no}><span>{v.version_no}</span><div><strong>数据快照 · {v.item_count.toLocaleString()} 条样本</strong><small>{fmtDT(v.created_at)}</small></div>{v.id === currentVersionId ? <StatusPill>当前版本</StatusPill> : <button className="ghost-button">查看</button>}</div>)}</div></section><section className="panel"><div className="panel-heading"><div><h2>数据血缘</h2><p>从原始数据到训练任务的关联</p></div></div><div className="lineage">{lineage.flatMap((node, i) => { const Icon = lineageIcon[node.type] ?? Database; const sep = i === 0 ? [] : [<i key={`sep-${i}`}>↓</i>]; return [...sep, <span key={node.type}><Icon size={14} />{node.label} <b>{node.count} {lineageSuffix[node.type] ?? '个'}</b></span>]; })}</div></section></div></div>;
}

function DatasetInputPanel({ task, dims }: { task: string; dims: DimensionStatus[] }) {
  return <section className="panel dataset-input-panel"><div className="panel-heading"><div><h2>输入数据维度</h2><p>字段是否存在由采集情况决定，训练资格按当前任务动态判断。</p></div><span className="dataset-task-tag">{task}</span></div><div className="dimension-grid">{dims.map((dim) => { const isRequired = dim.required; const isAvailable = dim.status === '已具备'; return <div className={`dimension-item ${isRequired ? 'required' : ''}`} key={dim.name}><span className="dimension-status">{isAvailable ? <CheckCircle2 size={14} /> : <AlertTriangle size={14} />}</span><div><strong>{dim.name}</strong><small>{isRequired ? '当前任务必需' : isAvailable ? '已具备 · 可选输入' : '缺失 · 不影响当前任务'}</small></div><StatusPill tone={isAvailable ? 'green' : 'orange'}>{isAvailable ? '已具备' : '缺失'}</StatusPill></div>; })}</div></section>;
}

function ModelReadiness({ task, status, readiness }: { task: string; status: string; readiness: ReadinessCheck | null }) {
  const ready = readiness?.readiness ?? (status === '可训练' ? '可训练' : '暂不可训练');
  const isTrainable = ready === '可训练';
  const checks = readiness?.checks ?? mockReadinessChecks(task);
  return <section className="panel readiness-panel"><div className="panel-heading"><div><h2>模型适配检查</h2><p>当前数据集按照“{task}”的最低训练要求检查。</p></div><StatusPill tone={isTrainable ? 'green' : 'orange'}>{isTrainable ? '可训练' : '暂不可训练'}</StatusPill></div><div className="readiness-grid">{checks.map((check) => <div key={check.name}>{check.passed ? <CheckCircle2 size={14} /> : <AlertTriangle size={14} />}<span>{check.name}</span></div>)}</div><div className="split-policy"><GitBranch size={14} /><span>划分策略：按焊缝 ID 分组，避免同一焊缝的视频帧同时出现在训练集和测试集。</span></div></section>;
}

function DatasetTrainingContext() {
  const [ds, setDs] = useState<Dataset | null>(null);
  useEffect(() => {
    let cancelled = false;
    listDatasets().then((list) => { if (!cancelled && list.length) setDs(list.find((d) => d.status === '可训练') ?? list[0]); }).catch((err) => { if (!cancelled) console.warn('[datasets] training context failed', err); });
    return () => { cancelled = true; };
  }, []);
  const name = ds ? `${ds.name} · ${ds.version ?? '—'}` : '焊接缺陷检测集 · v1.3';
  const split = ds?.split && ds.split.train !== undefined ? `${ds.split.train.toLocaleString()} / ${(ds.split.val ?? 0).toLocaleString()} / ${(ds.split.test ?? 0).toLocaleString()}` : '6,736 / 842 / 842';
  return <div className="model-dataset-context"><div className="dataset-row-icon"><Box size={16} /></div><div><span>当前训练数据集</span><strong>{name}</strong></div><div><span>训练 / 验证 / 测试</span><strong>{split}</strong></div><StatusPill>{ds?.status ?? '可训练'}</StatusPill><button className="ghost-button">更换数据集 <ChevronDown size={13} /></button></div>;
}
function DatasetTestingContext() {
  const [ds, setDs] = useState<Dataset | null>(null);
  useEffect(() => {
    let cancelled = false;
    listDatasets().then((list) => { if (!cancelled && list.length) setDs(list[0]); }).catch((err) => { if (!cancelled) console.warn('[datasets] testing context failed', err); });
    return () => { cancelled = true; };
  }, []);
  const name = ds ? `${ds.name} · ${ds.version ?? '—'}` : '焊接缺陷检测集 · v1.3';
  const testCount = ds?.split && ds.split.test !== undefined ? ds.split.test.toLocaleString() : '842';
  return <div className="model-dataset-context"><div className="dataset-row-icon"><Box size={16} /></div><div><span>当前测试数据集</span><strong>{name}</strong></div><div><span>固定测试集</span><strong>{testCount} 条样本</strong></div><StatusPill>固定快照</StatusPill><button className="ghost-button">更换数据集 <ChevronDown size={13} /></button></div>;
}

/** 选择数据卡片展示形状（selection-card 期望的字段，由 DataRecord 派生）。 */
interface SelectCard { id: string; machine: string | null; types: string; quality: string; title: string | null; }
function toSelectCard(r: DataRecord): SelectCard {
  return { id: r.weld_id, machine: r.machine, types: (r.modalities ?? []).join(' / ') || '多模态', quality: r.quality, title: r.weld_name };
}
function AnalysisSelect({ onContinue }: { onContinue: (id: string) => void }) {
  const [candidates, setCandidates] = useState<SelectCard[]>([]);
  useEffect(() => {
    let cancelled = false;
    listCandidates().then((list) => { if (!cancelled) setCandidates(list.map(toSelectCard)); }).catch((err) => { if (!cancelled) console.warn('[analysis] listCandidates failed', err); });
    return () => { cancelled = true; };
  }, []);
  const rows = candidates.length ? candidates : mockWeldRows.map((r) => ({ id: r.id, machine: r.machine, types: r.types, quality: r.quality, title: null }));
  return <div className="selection-workspace"><div className="selection-hero"><div className="selection-icon"><Waves size={25} /></div><div><h2>选择一条焊缝开始分析</h2><p>选择已登记且核验通过的数据，进入多模态分析流程。</p></div></div><div className="selection-grid">{rows.slice(0, 3).map((row, index) => <button className={`selection-card ${index === 0 ? 'selected' : ''}`} onClick={() => onContinue(row.id)} key={row.id}><div><span className="file-badge"><Archive size={14} />{row.id}</span><h3>{row.title ?? (index === 0 ? 'MAG 短路过渡 · 典型稳定样本' : index === 1 ? '熔池异常 · 待复核样本' : '红外多模态 · 工艺验证样本')}</h3><p>{row.machine} · {row.types}</p></div><StatusPill tone={row.quality === '通过' ? 'green' : 'orange'}>{row.quality === '通过' ? '核验通过' : '待复核'}</StatusPill></button>)}</div></div>;
}

function VersionPanel({ dataId }: { dataId?: string }) {
  const mockVersions: DataVersion[] = [
    { id: 1, record_id: 1, version_no: 'v1.0', action: '原始数据', operator: '系统导入', note: null, object_keys: [], created_at: '2026-08-15 09:42:00' },
    { id: 2, record_id: 1, version_no: 'v1.1', action: '去噪处理', operator: '林工', note: null, object_keys: [], created_at: '2026-08-15 09:45:00' },
    { id: 3, record_id: 1, version_no: 'v1.2', action: '时间对齐', operator: '算法任务', note: null, object_keys: [], created_at: '2026-08-15 09:48:00' },
    { id: 4, record_id: 1, version_no: 'v1.3', action: '人工修正', operator: '林工', note: null, object_keys: [], created_at: '2026-08-15 10:06:00' },
  ];
  const [versions, setVersions] = useState<DataVersion[]>(mockVersions);
  useEffect(() => {
    if (!dataId) return;
    let cancelled = false;
    listVersions(dataId).then((list) => { if (!cancelled) setVersions(list); }).catch((err) => { if (!cancelled) console.warn('[versions] listVersions failed', err); });
    return () => { cancelled = true; };
  }, [dataId]);
  const last = versions[versions.length - 1];
  return <section className="panel version-panel"><div className="panel-heading"><div><h2>数据版本</h2><p>原始数据与加工结果的版本链路</p></div><StatusPill>当前版本 {last?.version_no ?? '—'}</StatusPill></div><div className="version-line">{versions.map((version, index) => <div className={index === versions.length - 1 ? 'current' : ''} key={`${version.version_no}-${version.id}`}><i /><span>{`${version.version_no} ${version.action}`}<small>{fmtDT(version.created_at)} · {version.operator ?? '—'}</small></span><button className="ghost-button">查看</button></div>)}</div></section>;
}

const mockModelSummary = { total: 18, prod_candidates: 6, recent_training: '今天 09:42', gpu_usage: 42 };
const mockModelCards = [
  { name: '焊接异常检测模型', version: 'v1.8', type: '时序分类', metric: 'F1 95.5%', status: '生产候选' },
  { name: '熔池分割模型', version: 'v2.1', type: '语义分割', metric: 'mIoU 91.2%', status: '训练中' },
  { name: '质量预测模型', version: 'v0.9', type: '多模态回归', metric: 'R² 0.93', status: '实验版本' },
];
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
function ModelRepository({ refreshKey = 0 }: { refreshKey?: number }) {
  const [summary, setSummary] = useState(mockModelSummary);
  const [models, setModels] = useState(mockModelCards);
  useEffect(() => {
    let cancelled = false;
    listModels().then((res) => {
      if (cancelled) return;
      if (res.models?.length) {
        setModels(res.models.map((m) => ({ name: m.name, version: m.version ?? '—', type: m.type, metric: modelMetricText(m.metric), status: m.status ?? '—' })));
      }
      setSummary({
        total: res.summary.total,
        prod_candidates: res.summary.prod_candidates,
        recent_training: res.summary.recent_training ? fmtDT(res.summary.recent_training) : mockModelSummary.recent_training,
        gpu_usage: res.summary.gpu_usage,
      });
    }).catch((err) => { if (!cancelled) console.warn('[model-center] listModels failed', err); });
    return () => { cancelled = true; };
  }, [refreshKey]);
  return <div className="model-repository"><div className="repository-summary"><div><span>模型总数</span><strong>{summary.total}</strong></div><div><span>生产候选</span><strong>{summary.prod_candidates}</strong></div><div><span>最近训练</span><strong>{summary.recent_training}</strong></div><div><span>GPU 资源</span><strong>{summary.gpu_usage}%</strong></div></div><div className="model-card-grid">{models.map((model) => <section className="panel model-card" key={model.name}><div className="model-card-top"><div className="model-logo"><Cpu size={17} /></div><StatusPill tone={model.status === '训练中' ? 'orange' : 'green'}>{model.status}</StatusPill><MoreHorizontal size={16} className="muted-icon" /></div><h2>{model.name}</h2><p>{model.type} · {model.version}</p><div className="model-metric"><span>核心指标</span><strong>{model.metric}</strong></div><div className="model-card-footer"><span>最近更新 2 小时前</span><button className="ghost-button">查看详情 <ArrowUpRight size={13} /></button></div></section>)}</div></div>;
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
    if (modelVersionId == null) { console.warn('[inference] 模型版本未就绪，请稍后再试'); return; }
    const upload = file.size < 100 * 1024 * 1024
      ? uploadFile(file).then((r) => r.object_key)
      : presignUpload({ size: file.size, content_type: file.type || 'application/octet-stream', prefix: 'inference' }).then(async (r) => {
          const res = await fetch(r.upload_url, { method: 'PUT', body: file });
          if (!res.ok) throw new Error(`[inference] presign PUT failed: ${res.status}`);
          return r.object_key;
        });
    upload
      .then((objectKey) => {
        const inputType = file.type.startsWith('image/') ? '图像' : file.type.startsWith('video/') ? '视频帧' : '时序';
        return createInferenceTask({ model_version_id: modelVersionId, input: objectKey, input_type: inputType });
      })
      .then((res) => setJobId(res.job_id))
      .catch((err) => console.warn('[inference] 推理提交失败', err));
  };
  const statusText = jobStatus === 'running' ? '运行中' : jobStatus === 'failed' ? '失败' : jobStatus === 'succeeded' ? '已完成' : '就绪';
  const statusTone = (jobStatus === 'running' ? 'orange' : jobStatus === 'failed' ? 'red' : 'green') as 'green' | 'orange' | 'red';
  const inferSummary = inferRes && inferRes.categories.length ? `${inferRes.categories.length} 个目标 · ${inferRes.categories.join(' / ')}` : '推理结果将在这里展示';
  const confText = inferRes?.confidence?.length ? `${(Math.max(...inferRes.confidence) * 100).toFixed(1)}%` : '—';
  return <section className="panel inference-panel"><div className="panel-heading"><div><h2>推理验证</h2><p>选择模型和样本，预览模型输出结果</p></div><StatusPill tone={statusTone}>{statusText}</StatusPill></div><input ref={fileRef} type="file" accept="image/*,video/*" hidden onChange={handleFile} /><div className="inference-layout"><div className="inference-drop"><Upload size={23} /><strong>选择测试样本</strong><span>支持图像、视频帧或时序信号</span><button className="outline-button" onClick={() => fileRef.current?.click()}>选择样本</button></div><div className="inference-result"><div className="result-placeholder"><ScanLine size={28} /><span>{inferSummary}</span></div><div className="result-row"><span>模型置信度</span><strong>{confText}</strong></div><div className="result-row"><span>推理耗时</span><strong>{inferRes ? `${inferRes.latency_ms}ms` : '—'}</strong></div></div></div></section>;
}

function Toolbar({ action, secondary = '导出报告', onAction, exportType, exportRefIds }: { action: string; secondary?: string; onAction?: () => void; exportType?: string; exportRefIds?: unknown[] }) {
  const handleExport = () => {
    if (!exportType) { console.warn('[export] 当前页面未配置导出类型'); return; }
    exportReport({ type: exportType, ref_ids: exportRefIds ?? [], format: 'pdf' })
      .then((res) => {
        const url = res.urls?.[0]?.url;
        if (url) window.open(url, '_blank');
        else console.warn('[export] 未返回下载 URL（ref_ids 可能为空）');
      })
      .catch((err) => console.warn('[export] exportReport failed', err));
  };
  return <div className="page-toolbar"><button className="ghost-button"><RefreshCw size={14} />刷新</button><button className="outline-button" onClick={handleExport}><Download size={14} />{secondary}</button><button className="primary-button" onClick={onAction}><Plus size={15} />{action}</button></div>;
}

function StatusPill({ children, tone = 'green' }: { children: React.ReactNode; tone?: 'green' | 'orange' | 'red' | 'blue' }) {
  return <span className={`status ${tone}`}>{children}</span>;
}

const mockWeldRows: WeldRow[] = [
  { id: 'WLD-20260815-0248', time: '2026-08-15 09:42', source: '产线相机 · 03号', machine: 'Fronius CMT', types: '视频 / 时序 / 声音', quality: '通过', version: 'v1.3' },
  { id: 'WLD-20260815-0247', time: '2026-08-15 09:18', source: '实训线 · 02号', machine: 'OTC FD-V8', types: '视频 / 时序', quality: '待复核', version: 'v2.0' },
  { id: 'WLD-20260814-0246', time: '2026-08-14 18:32', source: '产线相机 · 03号', machine: 'Kemppi Minarc', types: '视频 / 时序 / 红外', quality: '通过', version: 'v1.1' },
  { id: 'WLD-20260814-0245', time: '2026-08-14 16:07', source: '实训线 · 01号', machine: 'Panasonic YD-500', types: '视频 / 声音', quality: '异常', version: 'v1.0' },
];

/** 数据列表：每页条数 + tab 演示计数（API 返回后 active tab 显示响应 total）。 */
const PAGE_SIZE = 10;
const mockTabCounts: Record<string, number> = { '全部最新数据': 12847, '待核验': 126, '已归档': 8204 };
const DATA_TABS = ['全部最新数据', '待核验', '已归档'] as const;

function ManagementFiltered({ navigate, selectedDataId, setSelectedDataId }: { navigate: (route: Route) => void; selectedDataId: string | null; setSelectedDataId: (id: string) => void }) {
  const [query, setQuery] = useState('');
  const [source, setSource] = useState('全部来源');
  const [brand, setBrand] = useState('全部品牌');
  const [tab, setTab] = useState('全部最新数据');
  const [page, setPage] = useState(1);
  const [rows, setRows] = useState<WeldRow[]>(mockWeldRows);
  const [total, setTotal] = useState(12847);

  useEffect(() => { setPage(1); }, [query, source, brand, tab]);

  useEffect(() => {
    let cancelled = false;
    listWelds({
      q: query.trim() || undefined,
      source: source === '全部来源' ? undefined : source,
      brand: brand === '全部品牌' ? undefined : brand,
      tab,
      page,
      page_size: PAGE_SIZE,
    }).then((res) => {
      if (cancelled) return;
      setRows(res.items.map(toWeldRow));
      setTotal(res.total);
    }).catch((err) => {
      if (!cancelled) console.warn('[data-list] listWelds failed', err);
    });
    return () => { cancelled = true; };
  }, [query, source, brand, tab, page]);

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  return <section className="panel table-panel"><div className="data-filter-strip"><label className="filter-field keyword">关键词<div className="inline-search"><Search size={14} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="焊缝ID、登记编号" /></div></label><label className="filter-field">数据来源<select value={source} onChange={(event) => setSource(event.target.value)}><option>全部来源</option><option>产线相机</option><option>实训线</option></select></label><label className="filter-field">焊机品牌<select value={brand} onChange={(event) => setBrand(event.target.value)}><option>全部品牌</option><option>Fronius</option><option>OTC</option><option>Kemppi</option><option>Panasonic</option></select></label><button className="outline-button filter-reset" onClick={() => { setQuery(''); setSource('全部来源'); setBrand('全部品牌'); setTab('全部最新数据'); setPage(1); }}><RefreshCw size={13} />重置</button></div><div className="latest-version-note"><GitBranch size={14} />列表按焊缝 ID 去重，仅显示每条数据的最新版本</div><div className="table-toolbar"><div className="filter-tabs">{DATA_TABS.map((label) => <button key={label} className={tab === label ? 'active' : ''} onClick={() => setTab(label)}>{label} <b>{tab === label ? total.toLocaleString() : mockTabCounts[label].toLocaleString()}</b></button>)}</div><div className="table-actions"><button className="select-button" onClick={() => { setQuery(''); setSource('全部来源'); setBrand('全部品牌'); setTab('全部最新数据'); setPage(1); }}><RefreshCw size={14} />重置筛选</button></div></div><div className="selection-bar">{selectedDataId ? <>当前选中：<strong>{selectedDataId}</strong><span>登记、核验、版本和分析操作将基于此数据</span></> : <>尚未选择数据<span>点击任意数据行即可选择</span></>}<button className="ghost-button" onClick={() => selectedDataId && navigate('analysis/select')}>进入分析与标注 <ArrowUpRight size={14} /></button></div><div className="data-table"><div className="table-row table-head"><span>状态</span><span>焊缝 / 登记编号</span><span>采集时间</span><span>数据来源</span><span>焊机品牌 / 型号</span><span>数据模态</span><span>核验状态</span><span>最新版本</span><span>操作</span></div>{rows.map((row) => <div className={`table-row ${selectedDataId === row.id ? 'selected-row' : ''}`} onClick={() => setSelectedDataId(row.id)} key={row.id}><span><input type="radio" checked={selectedDataId === row.id} onChange={() => setSelectedDataId(row.id)} aria-label={`选择 ${row.id}`} /></span><span className="id-cell"><strong>{row.id}</strong><small>登记台账 · 最新版本</small></span><span>{row.time}</span><span>{row.source}</span><span>{row.machine}</span><span>{row.types}</span><span><StatusPill tone={row.quality === '异常' ? 'red' : row.quality === '待复核' ? 'orange' : 'green'}>{row.quality}</StatusPill></span><span className="mono">{row.version}</span><span><button className="table-icon" onClick={(event) => { event.stopPropagation(); setSelectedDataId(row.id); navigate('analysis/select'); }} aria-label="进入分析"><Eye size={15} /></button></span></div>)}</div><div className="table-footer"><span>显示 {rows.length} 条最新数据，共 {total.toLocaleString()} 条数据</span><div className="pagination"><button onClick={() => setPage((p) => Math.max(1, p - 1))}><ChevronLeft size={14} /></button><span>{page} / {totalPages}</span><button onClick={() => setPage((p) => Math.min(totalPages, p + 1))}><ChevronRight size={14} /></button></div></div></section>;
}

function Registration({ embedded = false }: { embedded?: boolean }) {
  const [registered, setRegistered] = useState(false);
  const [regNo, setRegNo] = useState('REG-20260815-00249');
  const [regId, setRegId] = useState<number | null>(null);
  const [recentRows, setRecentRows] = useState<WeldRow[]>(mockWeldRows.slice(0, 3));
  const [form, setForm] = useState<RegistrationForm>({ source: '', collected_at: '2026-08-15 09:42', weld_name: '', product: '', machine: 'Fronius CMT', weld_method: 'MAG焊', material: '', thickness: '', current_voltage: '', sample_rate: '' });
  const fileRef = useRef<HTMLInputElement>(null);
  const setField = (key: keyof RegistrationForm) => (event: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setForm((prev) => ({ ...prev, [key]: event.target.value }));
  useEffect(() => {
    let cancelled = false;
    listWelds({ tab: 'recent' }).then((res) => {
      if (cancelled) return;
      setRecentRows(res.items.slice(0, 5).map((r) => ({ ...toWeldRow(r), time: (r.collected_at ?? r.created_at ?? '').replace('T', ' ').slice(0, 16) })));
    }).catch((err) => { if (!cancelled) console.warn('[registration] listWelds recent failed', err); });
    return () => { cancelled = true; };
  }, []);
  const handleSubmit = () => {
    createRegistration(form).then((reg) => { setRegId(reg.id); setRegNo(reg.registration_no); setRegistered(true); }).catch((err) => { console.warn('[registration] createRegistration failed', err); setRegistered(true); });
  };
  const handleFile = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    const upload = file.size < 100 * 1024 * 1024
      ? uploadFile(file).then((r) => r.object_key)
      : presignUpload({ size: file.size, content_type: file.type || 'application/octet-stream', prefix: 'raw' }).then(async (r) => {
          const res = await fetch(r.upload_url, { method: 'PUT', body: file });
          if (!res.ok) throw new Error(`[registration] presign PUT failed: ${res.status}`);
          return r.object_key;
        });
    upload
      .then((objectKey) => {
        if (regId == null) { console.warn('[registration] no registration id yet, skip attachRawFiles'); return; }
        return attachRawFiles(String(regId), [objectKey]);
      })
      .catch((err) => console.warn('[registration] upload failed', err));
  };
  return <div className="page-wrap"><PageIntro eyebrow="标准化台账" title="数据登记" description="为每批焊接多模态数据建立统一身份、来源和工艺参数档案。" action={<span className="workflow-chip"><CheckCircle2 size={14} />登记即进入数据流程</span>} /><div className="registration-layout"><section className="panel form-panel"><div className="panel-heading"><div><h2>新建数据登记</h2><p>带 * 的字段为必填项</p></div><span className="draft-tag">登记草稿</span></div><div className="form-section-title"><span>基础信息</span><i /></div><div className="form-grid"><label>数据来源 *<input placeholder="例如：产线相机 · 03号" value={form.source} onChange={setField('source')} /></label><label>采集时间 *<input value={form.collected_at ?? ''} onChange={setField('collected_at')} readOnly /></label><label>焊缝 / 批次名称 *<input placeholder="输入焊缝或批次名称" value={form.weld_name ?? ''} onChange={setField('weld_name')} /></label><label>关联产品信息<input placeholder="产品型号、零件编号" value={form.product ?? ''} onChange={setField('product')} /></label></div><div className="form-section-title"><span>采集与工艺参数</span><i /></div><div className="form-grid"><label>焊机型号<select value={form.machine ?? ''} onChange={setField('machine')}><option>Fronius CMT</option><option>OTC FD-V8</option><option>Panasonic YD-500</option></select></label><label>焊接方法<select value={form.weld_method ?? ''} onChange={setField('weld_method')}><option>MAG焊</option><option>MIG焊</option><option>TIG焊</option></select></label><label>板材材质<input placeholder="例如：Q235B" value={form.material ?? ''} onChange={setField('material')} /></label><label>板材厚度<input placeholder="例如：6 mm" value={form.thickness ?? ''} onChange={setField('thickness')} /></label><label>电流 / 电压<input placeholder="180 A / 22 V" value={form.current_voltage ?? ''} onChange={setField('current_voltage')} /></label><label>采样频率<input placeholder="10 kHz" value={form.sample_rate ?? ''} onChange={setField('sample_rate')} /></label></div><div className="upload-zone"><Upload size={20} /><strong>拖入或选择原始数据文件</strong><span>支持视频、CSV、WAV、JSON、图片 · 单文件不超过 2 GB</span><button className="outline-button" onClick={() => fileRef.current?.click()}>选择文件</button><input ref={fileRef} type="file" style={{ display: 'none' }} onChange={handleFile} /></div><button className="full-button" onClick={handleSubmit}>{registered ? <><CheckCircle2 size={16} />登记已生成：{regNo}</> : <><FileCheck2 size={16} />生成登记编号</>}</button></section><aside className="registration-aside"><section className="panel"><div className="panel-heading"><div><h2>登记规则</h2><p>平台数据使用约束</p></div><ClipboardCheck size={18} className="accent-text" /></div>{['自动生成唯一登记编号', '原始文件与后续版本自动关联', '登记后触发入库前数据核验', '所有操作写入审计日志'].map((item) => <div className="rule-row" key={item}><CheckCircle2 size={15} />{item}</div>)}</section><section className="panel"><div className="panel-heading"><div><h2>最近登记</h2><p>最近 24 小时新增数据</p></div></div>{recentRows.map((row) => <div className="recent-row" key={row.id}><span className="recent-dot" /><div><strong>{row.id}</strong><small>{row.source} · {row.time.slice(11)}</small></div><StatusPill>已登记</StatusPill></div>)}</section></aside></div></div>;
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

function fmt(s: number) {
  const m = Math.floor(s / 60);
  const r = (s - m * 60).toFixed(2).padStart(5, '0');
  return `${String(m).padStart(2, '0')}:${r}`;
}

function toPath(values: number[], lo: number, hi: number): string {
  const range = hi - lo || 1;
  const n = Math.max(values.length - 1, 1);
  return values.map((v, i) => {
    const px = AXIS_L + (i / n) * PLOT_W;
    const py = (PLOT_H * (1 - (v - lo) / range));
    return `${i === 0 ? 'M' : 'L'}${px.toFixed(1)} ${py.toFixed(1)}`;
  }).join(' ');
}


function PhasePlot({ cursor, onCursor, data }: { cursor: number; onCursor: (s: number) => void; data?: PhaseData }) {
  const w = 260; const h = 230; const pad = 26; const pw = w - pad * 2; const ph = h - pad * 2;
  const cxLo = 140; const cxHi = 230; const cvLo = 15; const cvHi = 30;
  const toX = (c: number) => pad + ((c - cxLo) / (cxHi - cxLo)) * pw;
  const toY = (v: number) => pad + (1 - (v - cvLo) / (cvHi - cvLo)) * ph;
  const curArr = data && data.current.length ? data.current : sigCur;
  const volArr = data && data.voltage.length ? data.voltage : sigVol;
  const n = Math.min(curArr.length, volArr.length);
  const points = Array.from({ length: n }, (_, i) => {
    const ts = (i / Math.max(n - 1, 1)) * dur;
    return { x: toX(curArr[i]), y: toY(volArr[i]), ts, i, anom: isAnom(ts) };
  });
  const path = points.map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(' ');
  const cursorIdx = Math.min(points.length - 1, Math.max(0, Math.round((cursor / dur) * (points.length - 1))));
  const cp = points[cursorIdx];
  const x = (e: React.MouseEvent<SVGSVGElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const relX = (e.clientX - rect.left) / rect.width * w;
    const c = cxLo + ((relX - pad) / pw) * (cxHi - cxLo);
    let best = 0; let bd = Infinity;
    for (let i = 0; i < points.length; i++) { const d = Math.abs(curArr[i] - c); if (d < bd) { bd = d; best = i; } }
    onCursor(points[best].ts);
  };
  return <svg viewBox={`0 0 ${w} ${h}`} className="phase-svg" onMouseMove={x} onMouseLeave={() => {}}>
    <line x1={pad} y1={pad} x2={pad} y2={pad + ph} stroke="#e8efef" />
    <line x1={pad} y1={pad + ph} x2={pad + pw} y2={pad + ph} stroke="#e8efef" />
    <text x={pad + pw / 2} y={h - 6} textAnchor="middle" className="phase-axis-label">电流 (A)</text>
    <text x={8} y={pad + ph / 2} textAnchor="middle" className="phase-axis-label" transform={`rotate(-90 8 ${pad + ph / 2})`}>电压 (V)</text>
    <path d={path} fill="none" stroke="#2c9caf" strokeWidth="1.4" opacity="0.55" />
    {points.filter((p) => p.anom).map((p) => <circle key={p.i} cx={p.x} cy={p.y} r="2.4" fill="#e88d6c" opacity="0.7" />)}
    <circle cx={cp.x} cy={cp.y} r="5" fill="#fff" stroke="#e88d6c" strokeWidth="2.5" />
  </svg>;
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

function PsdChart({ values, color, lo, hi, freqs, psd }: { values: number[]; color: string; lo: number; hi: number; freqs?: number[]; psd?: number[] }) {
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



function AdvancedWeldAnalysis({ embedded = false, dataId }: { embedded?: boolean; dataId?: string }) {
  const [mode, setMode] = useState('时域');
  const [active, setActive] = useState<Set<string>>(new Set(['cur', 'vol', 'gas']));
  const [cursor, setCursor] = useState(2.1);
  const [pddChan, setPddChan] = useState('cur');
  const [filterOn, setFilterOn] = useState(false);
  const [filterType, setFilterType] = useState<FilterType>('低通');
  const [cutoff, setCutoff] = useState(0.3);
  const [cutoff2, setCutoff2] = useState(0.6);
  const [filterChan, setFilterChan] = useState('cur');
  const [channels, setChannels] = useState<Chan[]>(mockChannels);
  const [versionId, setVersionId] = useState<number | null>(null);
  const [psdData, setPsdData] = useState<PsdData | null>(null);
  const [stftData, setStftData] = useState<StftData | null>(null);
  const [dwtData, setDwtData] = useState<DwtData | null>(null);
  const [waveletData, setWaveletData] = useState<WaveletData | null>(null);
  const [phaseData, setPhaseData] = useState<PhaseData | null>(null);
  const [pddData, setPddData] = useState<PddData | null>(null);
  const [result, setResult] = useState<AnalysisResult | null>(null);
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
    const opts: SignalQuery = { channels: ['cur', 'vol', 'gas', 'wir'] };
    if (filterOn) { opts.filter_type = filterType; opts.cutoff = cutoff; if (filterType === '带通') opts.cutoff2 = cutoff2; }
    getSignals(dataId, String(versionId), opts).then((data: SignalData) => { if (!cancelled) setChannels(data.channels.map(toChan)); }).catch((err) => { if (!cancelled) console.warn('[analysis] getSignals failed', err); });
    return () => { cancelled = true; };
  }, [dataId, versionId, filterOn, filterType, cutoff, cutoff2]);
  // 主视图 mode（PSD/STFT/DWT/小波分解）：mode / 目标通道 / 滤波变化 → 后端计算
  useEffect(() => {
    if (!dataId || versionId == null) return;
    if (mode !== 'PSD' && mode !== 'STFT' && mode !== 'DWT' && mode !== '小波分解') return;
    let cancelled = false;
    const apiMode = mode === 'PSD' ? 'psd' : mode === 'STFT' ? 'stft' : mode === 'DWT' ? 'dwt' : 'wavelet';
    const filter = filterOn ? { type: filterType, cutoff, cutoff2: filterType === '带通' ? cutoff2 : undefined } : undefined;
    getAnalysisMode(dataId, String(versionId), apiMode, filterChan, filter).then((data) => {
      if (cancelled) return;
      if (mode === 'PSD') setPsdData(data as PsdData);
      else if (mode === 'STFT') setStftData(data as StftData);
      else if (mode === 'DWT') setDwtData(data as DwtData);
      else setWaveletData(data as WaveletData);
    }).catch((err) => { if (!cancelled) console.warn(`[analysis] getAnalysisMode ${mode} failed`, err); });
    return () => { cancelled = true; };
  }, [dataId, versionId, mode, filterChan, filterOn, filterType, cutoff, cutoff2]);
  // 侧边 UI 相图（current/voltage，cur+vol 两通道）
  useEffect(() => {
    if (!dataId || versionId == null) return;
    let cancelled = false;
    const filter = filterOn ? { type: filterType, cutoff, cutoff2: filterType === '带通' ? cutoff2 : undefined } : undefined;
    getAnalysisMode(dataId, String(versionId), 'phase', 'cur', filter).then((data) => { if (!cancelled) setPhaseData(data as PhaseData); }).catch((err) => { if (!cancelled) console.warn('[analysis] phase failed', err); });
    return () => { cancelled = true; };
  }, [dataId, versionId, filterOn, filterType, cutoff, cutoff2]);
  // 侧边 PDD 分布（按所选通道）
  useEffect(() => {
    if (!dataId || versionId == null) return;
    let cancelled = false;
    const filter = filterOn ? { type: filterType, cutoff, cutoff2: filterType === '带通' ? cutoff2 : undefined } : undefined;
    getAnalysisMode(dataId, String(versionId), 'pdd', pddChan, filter).then((data) => { if (!cancelled) setPddData(data as PddData); }).catch((err) => { if (!cancelled) console.warn('[analysis] pdd failed', err); });
    return () => { cancelled = true; };
  }, [dataId, versionId, pddChan, filterOn, filterType, cutoff, cutoff2]);
  // 分析结果：稳定度 / 三类占比 / 异常区段
  useEffect(() => {
    if (!dataId || versionId == null) return;
    let cancelled = false;
    getAnalysisResult(dataId, String(versionId)).then((data) => { if (!cancelled) setResult(data); }).catch((err) => { if (!cancelled) console.warn('[analysis] getAnalysisResult failed', err); });
    return () => { cancelled = true; };
  }, [dataId, versionId]);
  const anomalies = result && result.anomalies.length
    ? result.anomalies.map((a) => ({ range: [a.start, a.end] as [number, number], type: a.type, sev: (a.type.includes('电弧') ? 'orange' : 'red') as 'orange' | 'red' }))
    : [{ range: anomalA, type: '电弧不稳', sev: 'orange' as const }, { range: anomalB, type: '飞溅倾向', sev: 'red' as const }];
  const filterChanObj = channels.find((c) => c.id === filterChan) ?? channels[0];
  // 信号已由后端按滤波参数计算（getSignals 带 filter 时返回滤波后值），此处直接用
  const filteredValues = filterChanObj.values;
  const seg = result?.segments ?? { normal: 92.4, arc_instability: 5.1, sputter: 2.5 };
  const modes = ['时域', 'PSD', 'STFT', 'DWT', '小波分解'];
  return <div className="page-wrap"><PageIntro eyebrow="焊缝级分析" title="焊缝深度分析" description="在同一时间轴上查看多模态信号、焊接事件和质量特征。" action={<Toolbar action="开始分析" secondary="导出分析报告" exportType="analysis" exportRefIds={versionId != null ? [versionId] : undefined} />} /><div className="analysis-meta panel"><div><span className="file-badge"><Archive size={15} />REG-20260815-00248</span><h2>焊缝 · MAG 短路过渡样本</h2><p>Fronius CMT · Q235B · 6 mm · 2026-08-15 09:42</p></div><div className="analysis-kpis"><div><span>核验状态</span><strong className="accent-text">通过</strong></div><div><span>有效焊接段</span><strong>3.86 s</strong></div><div><span>异常区段</span><strong className="warning-text">{anomalies.length} 个</strong></div></div></div>
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
      <div className="explore-legend">{channels.filter((c) => active.has(c.id)).map((c) => <span key={c.id}><i style={{ background: c.color }} />{c.name} ({c.unit})</span>)}{active.size === 0 && <span className="explore-legend-empty">请至少开启一个通道</span>}<span className="explore-legend-anom"><i className="legend-orange" />异常区段</span><span className="explore-legend-cursor"><i className="result-dot red" />时间游标 {fmt(cursor)}</span></div>
      {mode === '时域' && <><ExploreWaveform active={active} cursor={cursor} onCursor={setCursor} channels={channels} />{filterOn && <div className="filter-compare"><span className="fc-label">滤波后 {filterChanObj.name}（{filterType} · {cutoff.toFixed(2)}）</span><svg viewBox={`0 0 ${CH} 70`} className="filter-compare-svg" preserveAspectRatio="none"><path d={toPath(filterChanObj.values, filterChanObj.lo, filterChanObj.hi)} fill="none" stroke={filterChanObj.color} strokeWidth="1.8" opacity="0.7" /></svg></div>}
      <div className="event-track"><span>起弧 <b>00:00.42</b></span><i /><span>稳态焊接 <b>00:00.78 - 00:04.28</b></span><i /><span>收弧 <b>00:04.86</b></span></div>
      <div className="anomaly-summary"><div className="anomaly-summary-head"><AlertTriangle size={14} /><span>已检出异常区段 {anomalies.length} 个 · 点击可定位</span></div>{anomalies.map((a, i) => <button key={i} className={`anomaly-chip ${a.sev}`} onClick={() => setCursor((a.range[0] + a.range[1]) / 2)}><i /><strong>{a.type}</strong><small>{fmt(a.range[0])} – {fmt(a.range[1])}</small><span>定位 <ArrowUpRight size={12} /></span></button>)}</div>
      <div className="signal-cards">{channels.map((c) => <div key={c.id} className={active.has(c.id) ? '' : 'dim'}><Waves size={16} /><span>{c.name}波形<strong>{c.mean}</strong></span></div>)}</div></>}
      {mode === 'PSD' && <div className="spectrum-view"><div className="spectrum-head"><span><FilterIcon size={14} />功率谱密度 · Welch 法</span><small>目标通道：{filterChanObj.name}（{filterOn ? `已滤波 ${filterType}` : '原始信号'}）</small></div><PsdChart values={filteredValues} color={filterChanObj.color} lo={filterChanObj.lo} hi={filterChanObj.hi} freqs={psdData?.freqs} psd={psdData?.psd} /><div className="spectrum-note"><BarChart3 size={13} /><span>主峰集中在低频段（短路过渡频率），异常区段在 2-5 kHz 存在次峰。</span></div></div>}
      {mode === 'STFT' && <div className="spectrum-view"><div className="spectrum-head"><span><Activity size={14} />短时傅里叶变换时频图</span><small>目标通道：{filterChanObj.name}</small></div><StftHeatmap values={filteredValues} color={filterChanObj.color} magnitude={stftData?.magnitude} /><div className="spectrum-note"><Waves size={13} /><span>时频图可观察到 1.9-2.3s 和 3.6-3.9s 两个异常区段的高频能量抬升。</span></div></div>}
      {mode === 'DWT' && <div className="spectrum-view"><div className="spectrum-head"><span><Layers3 size={14} />离散小波分解（4 层 · db4）</span><small>目标通道：{filterChanObj.name}</small></div><DwtChart values={filteredValues} color={filterChanObj.color} bands={dwtData?.bands} approx={dwtData?.approx} /><div className="spectrum-note"><Gauge size={13} /><span>D1-D4 为细节系数、A4 为近似系数，异常在 D1-D2 高频层最明显。</span></div></div>}
      {mode === '小波分解' && <div className="spectrum-view"><div className="spectrum-head"><span><Waves size={14} />小波多层分量分解</span><small>目标通道：{filterChanObj.name} · 5 层</small></div><WaveletDecomp values={filteredValues} color={filterChanObj.color} bands={waveletData?.bands} /><div className="spectrum-note"><Layers3 size={13} /><span>L1-L5 由低到高展示不同尺度的小波分量，低层捕捉高频瞬变。</span></div></div>}
    </section>
    <aside className="explore-aside">
      <section className="panel explore-phase-panel">
        <div className="panel-heading"><div><h2>UI 相图</h2><p>电流–电压轨迹，颜色越亮越接近当前时刻</p></div><span className="explore-hint">悬停联动</span></div>
        <PhasePlot cursor={cursor} onCursor={setCursor} data={phaseData ?? undefined} />
        <div className="phase-legend"><span><i className="legend-blue" />稳态轨迹</span><span><i className="legend-orange" />异常发散</span><span><i className="result-dot red" />游标 {fmt(cursor)}</span></div>
      </section>
      <section className="panel explore-pdd-panel">
        <div className="panel-heading"><div><h2>PDD 概率密度分布</h2><p>评估信号值的集中度与双峰特征</p></div><div className="pdd-chan-select">{channels.map((c) => <button key={c.id} className={pddChan === c.id ? 'active' : ''} onClick={() => setPddChan(c.id)}><i style={{ background: c.color }} />{c.name}</button>)}</div></div>
        <PddChart chanId={pddChan} channels={channels} data={pddData ?? undefined} />
        <div className="pdd-note"><BarChart3 size={13} /><span>当前通道分布近似单峰、集中度高；异常区段会使分布尾部抬升。</span></div>
      </section>
      <section className="panel explore-result-panel">
        <div className="panel-heading"><div><h2>分析结果</h2><p>AI 异常检测模型 v1.8</p></div><Sparkles size={16} className="accent-text" /></div>
        <div className="result-score"><strong>{result ? result.stability.toFixed(1) : 96.8}%</strong><span>焊接稳定度</span></div>
        <div className="result-row"><span><i className="result-dot green" />正常区段</span><strong>{seg.normal.toFixed(1)}%</strong></div>
        <div className="result-row"><span><i className="result-dot orange" />电弧不稳</span><strong>{seg.arc_instability.toFixed(1)}%</strong></div>
        <div className="result-row"><span><i className="result-dot red" />飞溅倾向</span><strong>{seg.sputter.toFixed(1)}%</strong></div>
        <button className="full-button small-button">查看异常详情 <ArrowUpRight size={14} /></button>
      </section>
    </aside>
  </div></div>;
}
function SignalChart({ accent = '#2c9caf', secondary = '#f0a34a' }: { accent?: string; secondary?: string }) {
  return <div className="signal-chart"><div className="chart-grid-lines" /><svg viewBox="0 0 700 180" preserveAspectRatio="none"><path d="M0 106 C26 82 39 127 65 101 S103 62 128 100 S158 138 188 94 S221 84 249 101 S280 42 307 93 S339 132 370 88 S399 73 428 95 S463 144 493 88 S531 60 558 84 S594 121 620 75 S664 98 700 58" fill="none" stroke={accent} strokeWidth="2.5" /><path d="M0 135 C32 126 46 137 76 125 S123 119 152 130 S188 108 218 126 S257 135 287 119 S325 128 354 116 S391 128 420 110 S458 131 489 118 S530 121 561 104 S600 120 632 108 S672 114 700 102" fill="none" stroke={secondary} strokeWidth="1.8" strokeDasharray="5 5" /></svg><div className="chart-axis"><span>0s</span><span>1s</span><span>2s</span><span>3s</span><span>4s</span><span>5s</span></div></div>;
}

function WeldAnalysis({ embedded = false }: { embedded?: boolean }) {
  const [mode, setMode] = useState('时域');
  return <div className="page-wrap"><PageIntro eyebrow="焊缝级分析" title="焊缝深度分析" description="在同一时间轴上查看多模态信号、焊接事件和质量特征。" action={<Toolbar action="开始分析" secondary="导出分析报告" />} /><div className="analysis-meta panel"><div><span className="file-badge"><Archive size={15} />REG-20260815-00248</span><h2>焊缝 · MAG 短路过渡样本</h2><p>Fronius CMT · Q235B · 6 mm · 2026-08-15 09:42</p></div><div className="analysis-kpis"><div><span>核验状态</span><strong className="accent-text">通过</strong></div><div><span>有效焊接段</span><strong>3.86 s</strong></div><div><span>异常区段</span><strong className="warning-text">2 个</strong></div></div></div><div className="analysis-grid"><section className="panel signal-panel"><div className="panel-heading"><div><h2>多模态信号联动</h2><p>拖动时间轴查看对应视频帧和信号片段</p></div><div className="mode-tabs">{['时域', '频域', 'STFT', 'DWT'].map((item) => <button className={mode === item ? 'active' : ''} onClick={() => setMode(item)} key={item}>{item}</button>)}</div></div><div className="signal-legend"><span><i className="legend-blue" />电流 (A)</span><span><i className="legend-mint" />电压 (V)</span><span><i className="legend-orange" />异常区段</span></div><SignalChart /><div className="event-track"><span>起弧 <b>00:00.42</b></span><i /><span>稳态焊接 <b>00:00.78 - 00:04.28</b></span><i /><span>收弧 <b>00:04.86</b></span></div><div className="signal-cards"><div><Waves size={16} /><span>电流波形<strong>180 ± 12 A</strong></span></div><div><Activity size={16} /><span>电压波形<strong>22.4 ± 1.8 V</strong></span></div><div><Gauge size={16} /><span>气体流量<strong>18 L/min</strong></span></div></div></section><aside className="analysis-aside"><section className="panel"><div className="panel-heading"><div><h2>分析结果</h2><p>AI 异常检测模型 v1.8</p></div><Sparkles size={17} className="accent-text" /></div><div className="result-score"><strong>96.8%</strong><span>焊接稳定度</span></div><div className="result-row"><span><i className="result-dot green" />正常区段</span><strong>92.4%</strong></div><div className="result-row"><span><i className="result-dot orange" />电弧不稳</span><strong>5.1%</strong></div><div className="result-row"><span><i className="result-dot red" />飞溅倾向</span><strong>2.5%</strong></div><button className="full-button small-button">查看异常详情 <ArrowUpRight size={14} /></button></section><section className="panel"><div className="panel-heading"><div><h2>快捷分析</h2><p>一键生成专业视图</p></div></div><button className="quick-action"><Gauge size={15} />生成 UI 相图 <ArrowUpRight size={14} /></button><button className="quick-action"><BarChart3 size={15} />查看 PDD 分布 <ArrowUpRight size={14} /></button><button className="quick-action"><Zap size={15} />自动提取特征 <ArrowUpRight size={14} /></button></section></aside></div></div>;
}

function Validation({ embedded = false, dataId }: { embedded?: boolean; dataId?: string }) {
  const mockRules = ['图像文件完整性', '时序信号连续性', '采样频率一致性', '起收弧事件完整', '电流范围合理性', '电压范围合理性', '送丝速度缺失值', '多模态时间戳', '视频帧率稳定性', '文件命名规范', '焊缝ID唯一性', '工艺参数完整性', '音频信号质量', '红外数据完整性', '元数据关联关系'];
  const [report, setReport] = useState<ValidationReport | null>(null);
  const [versionId, setVersionId] = useState<number | null>(null);
  useEffect(() => {
    if (!dataId) return;
    let cancelled = false;
    getWeld(dataId).then((r) => {
      if (cancelled) return;
      const vid = r.latest_version_id ?? r.latest_version?.id ?? null;
      if (vid == null) return;
      setVersionId(vid);
      getValidation(dataId, String(vid)).then((rep) => { if (!cancelled) setReport(rep); }).catch((err) => { if (!cancelled) console.warn('[validation] getValidation failed', err); });
    }).catch((err) => { if (!cancelled) console.warn('[validation] getWeld failed', err); });
    return () => { cancelled = true; };
  }, [dataId]);
  const runNow = () => {
    if (!dataId || versionId == null) return;
    runValidation(dataId, String(versionId)).then(setReport).catch((err) => console.warn('[validation] runValidation failed', err));
  };
  const rules: ValidationRuleResult[] = report?.rules ?? mockRules.map((name, index) => ({ rule_name: name, status: index === 8 ? 'warning' : 'passed', message: index === 8 ? '视频帧率存在轻微波动，建议复核' : '检查通过 · 结果已记录' }));
  const passed = report?.passed ?? 14;
  const warning = report?.warning ?? 1;
  const failed = report?.failed ?? 0;
  const statusText = report ? (failed > 0 ? '异常' : warning > 0 ? '待复核' : '核验通过') : '核验通过';
  const statusTone = report ? (failed > 0 ? 'red' : warning > 0 ? 'orange' : 'green') : 'green';
  const lastRun = report && report.created_at ? `最近核验：${fmtDT(report.created_at)} · 核验耗时 ${report.duration != null ? report.duration : '—'}s` : '最近核验：2026-08-15 09:45 · 核验耗时 2.8s';
  return <div className="page-wrap"><PageIntro eyebrow="数据质量中心" title="数据核验" description="通过标准化规则检查数据完整性、连续性与多模态一致性。" action={<Toolbar action="执行核验" secondary="下载核验报告" onAction={runNow} exportType="validation" exportRefIds={report ? [report.id] : undefined} />} /><div className="validation-summary"><div className="validation-score"><div className="score-ring small"><div><strong>{report ? report.score : 93.3}</strong><span>质量评分</span></div></div><div><h2>{dataId ?? 'REG-20260815-00248'}</h2><p>{lastRun}</p><StatusPill tone={statusTone as 'green' | 'orange' | 'red'}>{statusText}</StatusPill></div></div><div className="validation-count"><div><strong>{passed}</strong><span>通过规则</span></div><div><strong className="warning-text">{warning}</strong><span>警告</span></div><div><strong className="danger-text">{failed}</strong><span>失败</span></div></div></div><section className="panel validation-panel"><div className="panel-heading"><div><h2>核验规则明细 <span className="inline-count">{rules.length} 项</span></h2><p>已覆盖图像、时序、视频、元数据与跨模态一致性检查</p></div><button className="select-button">全部状态 <ChevronDown size={14} /></button></div><div className="rule-grid">{rules.map((rule, index) => { const isWarn = rule.status === 'warning'; const isFail = rule.status === 'failed'; const tone = isFail ? 'red' : isWarn ? 'orange' : 'green'; const label = isFail ? '失败' : isWarn ? '警告' : '通过'; const msg = rule.message ?? (isWarn ? '存在警告，建议复核' : '检查通过 · 结果已记录'); return <div className="validation-rule" key={rule.rule_name || index}><div className={`validation-icon ${isWarn ? 'warning' : isFail ? 'failed' : ''}`}>{isFail || isWarn ? <AlertTriangle size={15} /> : <CheckCircle2 size={15} />}</div><div><strong>{rule.rule_name}</strong><span>{msg}</span></div><StatusPill tone={tone as 'green' | 'orange' | 'red'}>{label}</StatusPill></div>; })}</div></section></div>;
}

function Alignment({ embedded = false, splitOnly = false, dataId }: { embedded?: boolean; splitOnly?: boolean; dataId?: string }) {
  const [jobId, setJobId] = useState<string | null>(null);
  const [versionId, setVersionId] = useState<number | null>(null);
  const { status: jobStatus, progress, result } = useJob<SplitResult | AlignmentResult>(jobId);
  const splitRes = result && 'sample_count' in result ? (result as SplitResult) : null;
  const alignRes = result && 'events' in result ? (result as AlignmentResult) : null;
  useEffect(() => {
    if (!dataId) return;
    let cancelled = false;
    getWeld(dataId).then((r) => { if (!cancelled) setVersionId(r.latest_version_id ?? r.latest_version?.id ?? null); }).catch((err) => { if (!cancelled) console.warn('[alignment] getWeld failed', err); });
    return () => { cancelled = true; };
  }, [dataId]);
  const handleRun = () => {
    if (!dataId || versionId == null) { console.warn('[alignment] 尚未解析版本，请稍后再试'); return; }
    const run = splitOnly
      ? createSplitTask(dataId, String(versionId), { fixed_rate: 10, keep_event_buffer: 0.2, task_format: '目标检测' })
      : createAlignmentTask(dataId, String(versionId), ['video', 'timeseries', 'audio']);
    run.then((res) => setJobId(res.job_id)).catch((err) => console.warn('[alignment] 任务创建失败', err));
  };
  const tone = jobStatus === 'running' ? 'orange' : jobStatus === 'failed' ? 'red' : 'green';
  const statusText = jobStatus === 'succeeded' ? '已完成' : jobStatus === 'running' ? `处理中 ${progress}%` : jobStatus === 'failed' ? '失败' : (splitOnly ? '待切分' : '已对齐');
  const done = jobStatus === 'succeeded';
  const running = jobStatus === 'running';
  const events = alignRes?.events ?? null;
  return <div className="page-wrap"><PageIntro eyebrow="多模态数据生产线" title="对齐与切分" description="自动识别起收弧事件，完成视频、波形和音频的时间同步与样本切分。" action={<Toolbar action="生成切分样本" secondary="导出标注集" exportType="annotation" />} /><div className="alignment-layout"><section className="panel alignment-board"><div className="board-toolbar"><div><span className="file-badge"><GitBranch size={15} />多模态对齐任务 · ALIGN-0248</span><h2>熔池视频 / 电流电压 / 音频</h2></div><StatusPill tone={tone as 'green' | 'orange' | 'red'}>{statusText}</StatusPill></div><div className="video-placeholder"><div className="video-grid" /><div className="play-orb"><Play size={22} /></div><div className="video-label">熔池视频 · Frame 0248</div><span className="video-time">00:02.18 / 00:05.42</span></div><div className="timeline-stack"><Track label="视频帧" tone="blue" /><Track label="电流" tone="mint" /><Track label="电压" tone="orange" /><Track label="音频" tone="purple" /></div><div className="alignment-events"><span><i className="event-start" />起弧 <b>{events ? fmt(events.arc) : '00:00.42'}</b></span><span><i className="event-active" />有效焊接段 <b>{events ? `${fmt(events.weld_segment[0])} - ${fmt(events.weld_segment[1])}` : '00:00.78 - 00:04.28'}</b></span><span><i className="event-end" />收弧 <b>{events ? fmt(events.tail) : '00:04.86'}</b></span></div></section><aside className="alignment-aside"><section className="panel"><div className="panel-heading"><div><h2>切分规则</h2><p>配置样本生成策略</p></div><SlidersHorizontal size={17} /></div><label className="switch-row"><span>按固定频率切分</span><input type="checkbox" defaultChecked /></label><div className="select-field">10 帧 / 样本 <ChevronDown size={14} /></div><label className="switch-row"><span>保留事件点前后缓冲</span><input type="checkbox" defaultChecked /></label><div className="select-field">± 0.20 秒 <ChevronDown size={14} /></div><button className="full-button" onClick={handleRun}>{splitOnly ? (done ? <><Check size={16} />已生成 {splitRes?.sample_count ?? 248} 个样本</> : running ? <><Activity size={16} />切分处理中…</> : <><ScissorsIcon />预览切分结果</>) : (done ? <><Check size={16} />已完成时间对齐</> : running ? <><Activity size={16} />对齐处理中…</> : <><Play size={16} />开始多模态对齐</>)}</button></section><section className="panel"><div className="panel-heading"><div><h2>输出任务格式</h2><p>兼容主流视觉任务</p></div></div><div className="format-chips"><span className="chosen">目标检测</span><span>图像分类</span><span>语义分割</span><span>时序分类</span></div><div className="export-note"><FileText size={15} /><span>将生成图像、信号片段及 JSON 标注文件</span></div></section></aside></div></div>;
}

function Track({ label, tone }: { label: string; tone: string }) { return <div className="timeline-row"><span>{label}</span><div className={`timeline-track ${tone}`}><i /><b /></div><small>0s</small><small>5.42s</small></div>; }
function ScissorsIcon() { return <span className="scissors-icon">✂</span>; }

function ModelTest({ embedded = false }: { embedded?: boolean }) {
  const [modelVersionId, setModelVersionId] = useState<number | null>(null);
  const [modelName, setModelName] = useState<string | null>(null);
  const [datasetVersionId, setDatasetVersionId] = useState<number | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const { status: jobStatus, result: testRes } = useJob<TestResult>(jobId);
  useEffect(() => {
    let cancelled = false;
    Promise.all([listModels(), listDatasets()]).then(([modelRes, datasets]) => {
      if (cancelled) return;
      const withVersion = modelRes.models.filter((m) => m.latest_version_id != null);
      const prod = withVersion.find((m) => m.status === '生产候选') ?? withVersion[0];
      if (prod?.latest_version_id != null) {
        setModelVersionId(prod.latest_version_id);
        setModelName(prod.version ? `${prod.name} ${prod.version}` : prod.name);
      }
      if (datasets.length) setDatasetVersionId(datasets[0].current_version_id ?? datasets[0].id);
    }).catch((err) => { if (!cancelled) console.warn('[model-test] 模型/数据集解析失败', err); });
    return () => { cancelled = true; };
  }, []);
  const handleStart = () => {
    if (modelVersionId == null || datasetVersionId == null) { console.warn('[model-test] 模型/数据集版本未就绪，请稍后再试'); return; }
    createTestTask({ model_version_id: modelVersionId, dataset_version_id: datasetVersionId, tasks: ['异常分类'] })
      .then((res) => setJobId(res.job_id))
      .catch((err) => console.warn('[model-test] createTestTask failed', err));
  };
  const pct = (v: number | undefined | null) => (v != null ? `${(v * 100).toFixed(1)}%` : null);
  const acc = pct(testRes?.metrics?.accuracy) ?? '96.8%';
  const recall = pct(testRes?.metrics?.recall) ?? '94.2%';
  const f1 = pct(testRes?.metrics?.f1) ?? '95.5%';
  const latency = testRes?.metrics?.latency_ms != null ? `${testRes.metrics.latency_ms}ms` : '18ms';
  const cm = testRes?.confusion_matrix ?? [[612, 18], [22, 596]];
  const cm00 = cm[0]?.[0] ?? 612;
  const cm01 = cm[0]?.[1] ?? 18;
  const cm10 = cm[1]?.[0] ?? 22;
  const cm11 = cm[1]?.[1] ?? 596;
  const cmTotal = cm00 + cm01 + cm10 + cm11;
  const testStatus = jobStatus === 'running' ? '运行中' : jobStatus === 'failed' ? '失败' : jobStatus === 'succeeded' ? '已完成' : '待测试';
  const testTone = (jobStatus === 'running' ? 'orange' : jobStatus === 'failed' ? 'red' : 'green') as 'green' | 'orange' | 'red';
  return <div className="page-wrap"><PageIntro eyebrow="模型评估中心" title="模型测试" description="在独立测试集上验证异常检测、分割与质量预测模型的表现。" action={<Toolbar action="新建测试任务" secondary="导出测试报告" exportType="test" />} /><div className="model-test-layout"><section className="panel test-config"><div className="panel-heading"><div><h2>测试配置</h2><p>选择模型、数据集与评估任务</p></div><span className="draft-tag">待执行</span></div><div className="form-block"><label>模型类型</label><div className="model-select"><div className="model-logo"><Cpu size={16} /></div><div><strong>{modelName ?? '焊接异常检测模型 v1.8'}</strong><span>多源时序信号 · 异常分类</span></div><Check size={17} className="selected-check" /></div></div><div className="form-block"><label>独立测试集</label><div className="select-field"><Database size={16} />测试集 · 2026Q3 工艺扰动样本 <ChevronDown size={15} /></div></div><div className="form-block"><label>评估任务</label><div className="test-task-list"><button className="chosen"><Check size={14} />异常分类</button><button><span />质量预测</button><button><span />推理延迟</button></div></div><button className="full-button" onClick={handleStart}>{jobStatus === 'running' ? <><Activity size={16} />测试进行中…</> : <><Play size={16} />开始测试</>}</button></section><section className="panel test-result"><div className="panel-heading"><div><h2>测试结果</h2><p>{jobId ? `测试任务 · ${jobId}` : '最近测试任务 · TEST-20260815-03'}</p></div><StatusPill tone={testTone}>{testStatus}</StatusPill></div><div className="metric-row four"><div><span>准确率</span><strong>{acc}</strong></div><div><span>召回率</span><strong>{recall}</strong></div><div><span>F1 值</span><strong>{f1}</strong></div><div><span>推理时延</span><strong>{latency}</strong></div></div><div className="confusion-matrix"><div className="matrix-title"><h3>混淆矩阵</h3><span>测试样本 {cmTotal.toLocaleString()} 条</span></div><div className="matrix"><div /><strong>预测正常</strong><strong>预测异常</strong><strong>实际正常</strong><b className="matrix-good">{cm00}</b><b className="matrix-warn">{cm01}</b><strong>实际异常</strong><b className="matrix-warn">{cm10}</b><b className="matrix-good">{cm11}</b></div></div><div className="test-result-note"><CheckCircle2 size={16} /><span>模型在当前工况下满足验收阈值，建议继续进行跨板材厚度验证。</span></div></section></div></div>;
}

function InfoRow({ label, value, accent }: { label: string; value: string; accent?: boolean }) { return <div className="info-row"><span>{label}</span><strong className={accent ? 'accent-text' : ''}>{value}</strong></div>; }

const mockTsFeatures = [
  { name: '均值', cur: '180.2', vol: '22.4', gas: '18.0', wir: '7.0' },
  { name: '方差', cur: '142.8', vol: '3.2', gas: '0.8', wir: '0.4' },
  { name: '峰值', cur: '246.1', vol: '28.3', gas: '21.2', wir: '8.6' },
  { name: '偏度', cur: '0.12', vol: '-0.08', gas: '0.31', wir: '0.05' },
  { name: '峰度', cur: '2.94', vol: '3.12', gas: '2.67', wir: '2.81' },
  { name: 'RMS', cur: '182.1', vol: '22.5', gas: '18.0', wir: '7.0' },
  { name: 'FFT 主频', cur: '39.2 Hz', vol: '37.8 Hz', gas: '12.4 Hz', wir: '11.1 Hz' },
  { name: '小波能量', cur: '8.42', vol: '1.86', gas: '0.72', wir: '0.38' },
];
const mockVisionFeatures = [
  { name: '熔池面积', value: '1,284 px²', desc: '分割掩膜像素统计' },
  { name: '熔池周长', value: '186 px', desc: '边缘轮廓长度' },
  { name: '长宽比', value: '2.34', desc: '外接矩形长/宽' },
  { name: '圆形度', value: '0.72', desc: '4πA/P²' },
  { name: '灰度均值', value: '128.4', desc: '熔池区域平均灰度' },
  { name: '纹理对比度', value: '0.46', desc: 'GLCM 对比度' },
  { name: '纹理能量', value: '0.82', desc: 'GLCM 角二阶矩' },
  { name: '边缘梯度', value: '34.2', desc: 'Sobel 梯度均值' },
];
const mockAudioFeatures = [
  { name: '频带能量 (0-1kHz)', value: '24.6 dB' },
  { name: '频带功率 (1-5kHz)', value: '18.3 dB' },
  { name: '总功率谱密度', value: '0.042' },
  { name: '质心频率', value: '2.14 kHz' },
  { name: '频谱滚降', value: '4.2 kHz' },
  { name: '过零率', value: '0.038' },
];
const mockUnifiedVector = [
  { group: '时序·电流', dims: 8, range: '[0:8]', tone: '#2c9caf' },
  { group: '时序·电压', dims: 8, range: '[8:16]', tone: '#67cdb0' },
  { group: '时序·气体', dims: 6, range: '[16:22]', tone: '#f0a34a' },
  { group: '时序·送丝', dims: 6, range: '[22:28]', tone: '#75add1' },
  { group: '视觉·几何', dims: 4, range: '[28:32]', tone: '#b89ac4' },
  { group: '视觉·纹理', dims: 4, range: '[32:36]', tone: '#b89ac4' },
  { group: '声音·频带', dims: 6, range: '[36:42]', tone: '#d4a05a' },
];
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
  const [tsRows, setTsRows] = useState(mockTsFeatures);
  const [visionRows, setVisionRows] = useState(mockVisionFeatures);
  const [audioRows, setAudioRows] = useState(mockAudioFeatures);
  const [unified, setUnified] = useState(mockUnifiedVector);
  const [totalDims, setTotalDims] = useState(mockUnifiedVector.reduce((s, v) => s + v.dims, 0));
  useEffect(() => {
    if (!dataId) return;
    let cancelled = false;
    getWeld(dataId).then((r) => { if (!cancelled) setVersionId(r.latest_version_id ?? r.latest_version?.id ?? null); }).catch((err) => { if (!cancelled) console.warn('[features] getWeld failed', err); });
    return () => { cancelled = true; };
  }, [dataId]);
  const handleExtract = () => {
    if (!dataId || versionId == null) { console.warn('[features] 尚未解析版本，请稍后再试'); return; }
    extractFeatures({ weld_id: dataId, version_id: versionId, normalization: normMethod === 'L2 范数' ? 'L2' : normMethod, format: exportFmt })
      .then((res) => {
        setExtractionId(res.id);
        setTsRows(mapTsRows(res));
        setVisionRows(mapVisionRows(res));
        setAudioRows(mapAudioRows(res));
        const mapped = mapUnifiedGroups(res.unified_vector);
        if (mapped.length) { setUnified(mapped); setTotalDims(res.unified_vector.total_dims); }
        setNormMethod(res.normalization === 'L2' ? 'L2 范数' : res.normalization);
      })
      .catch((err) => console.warn('[features] extractFeatures failed', err));
  };
  return <div className="page-wrap"><PageIntro eyebrow="多模态特征工程" title="特征提取" description="从时序、视觉、声音模态提取代表性特征，输出统一特征向量供融合层使用。" action={<Toolbar action="执行提取" secondary="导出特征集" onAction={handleExtract} exportType="features" exportRefIds={extractionId != null ? [extractionId] : undefined} />} />
    <div className="feature-layout">
      <section className="panel feature-modality-panel">
        <div className="panel-heading"><div><h2>时序信号特征</h2><p>电流 / 电压 / 气体流量 / 送丝速度 · 统计 + 频域 + 时频</p></div><Waves size={17} className="accent-text" /></div>
        <div className="feature-table-wrap">
          <div className="feature-table">
            <div className="ft-row ft-head"><span>特征</span><span style={{ color: '#2c9caf' }}>电流</span><span style={{ color: '#67cdb0' }}>电压</span><span style={{ color: '#f0a34a' }}>气体</span><span style={{ color: '#75add1' }}>送丝</span></div>
            {tsRows.map((f) => <div className="ft-row" key={f.name}><span>{f.name}</span><span className="mono">{f.cur}</span><span className="mono">{f.vol}</span><span className="mono">{f.gas}</span><span className="mono">{f.wir}</span></div>)}
          </div>
        </div>
        <div className="feature-tags"><span>统计特征</span><span>FFT 频域</span><span>小波时频</span><span>28 维 / 通道</span></div>
      </section>

      <section className="panel feature-modality-panel">
        <div className="panel-heading"><div><h2>熔池视觉特征</h2><p>熔池视觉模型提取几何与纹理特征</p></div><ImageIcon size={17} className="accent-text" /></div>
        <div className="vision-feature-grid">
          {visionRows.map((f) => <div className="vf-item" key={f.name}><div><strong>{f.name}</strong><small>{f.desc}</small></div><span className="mono">{f.value}</span></div>)}
        </div>
        <div className="feature-tags"><span>几何特征</span><span>GLCM 纹理</span><span>Sobel 边缘</span><span>8 维</span></div>
      </section>

      <section className="panel feature-modality-panel">
        <div className="panel-heading"><div><h2>声音 / 光谱特征</h2><p>频带能量、功率谱密度与声学统计</p></div><AudioWaveform size={17} className="accent-text" /></div>
        <div className="audio-feature-list">
          {audioRows.map((f) => <div className="af-item" key={f.name}><Sigma size={13} /><span>{f.name}</span><strong className="mono">{f.value}</strong></div>)}
        </div>
        <div className="feature-tags"><span>频带能量</span><span>PSD</span><span>声学统计</span><span>6 维</span></div>
      </section>

      <section className="panel feature-unified-panel">
        <div className="panel-heading"><div><h2>统一特征向量</h2><p>多模态特征拼接后输出，供后续融合层使用</p></div><Boxes size={17} className="accent-text" /></div>
        <div className="unified-summary"><div><span>总维度</span><strong>{totalDims} 维</strong></div><div><span>模态数</span><strong>3</strong></div><div><span>归一化</span><strong>{normMethod}</strong></div><div><span>输出格式</span><strong>.{exportFmt.toLowerCase()}</strong></div></div>
        <div className="unified-vector-bar">
          {unified.map((seg, i) => <div className="uv-seg" key={i} style={{ flexGrow: seg.dims, background: seg.tone }} title={`${seg.group} · ${seg.dims} 维`}><span>{seg.dims}</span></div>)}
        </div>
        <div className="unified-legend">{unified.map((seg, i) => <span key={i}><i style={{ background: seg.tone }} />{seg.group}<small>{seg.range}</small></span>)}</div>
        <div className="unified-config">
          <div className="form-block"><label>归一化方式</label><div className="pp-chips">{['Z-Score', 'Min-Max', 'L2 范数', '无'].map((m) => <button key={m} className={normMethod === m ? 'on' : ''} onClick={() => setNormMethod(m)}>{m}</button>)}</div></div>
          <div className="form-block"><label>输出格式</label><div className="pp-chips">{['NPY', 'CSV', 'JSON', 'PT'].map((f) => <button key={f} className={exportFmt === f ? 'on' : ''} onClick={() => setExportFmt(f)}>{f}</button>)}</div></div>
        </div>
        <button className="full-button"><Download size={15} />导出统一特征向量</button>
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
        <div className="pipeline-note"><FileText size={14} /><span>当前为演示数据，接入后端后特征值由对应模型实时计算。</span></div>
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
function Training({ embedded = false }: { embedded?: boolean }) {
  const [isTraining, setIsTraining] = useState(false);
  const [datasetVersionId, setDatasetVersionId] = useState<number | null>(null);
  const [baseModelVersionId, setBaseModelVersionId] = useState<number | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [logs, setLogs] = useState<string | null>(null);
  const { status: jobStatus, progress, result: trainRes } = useJob<TrainingResult>(jobId);
  // 训练超参（表单展示值即初始值；保持 JSX 不动，仅作为 createTrainingTask 数据源）。
  const [config] = useState({ epochs: 50, batch_size: 16, learning_rate: 0.001, val_ratio: 0.2 });
  useEffect(() => {
    let cancelled = false;
    listDatasets().then((list) => {
      if (cancelled || !list.length) return;
      const first = list[0];
      setDatasetVersionId(first.current_version_id ?? first.id);
    }).catch((err) => { if (!cancelled) console.warn('[training] listDatasets failed', err); });
    // 基础模型（best-effort）：生产候选版本优先，否则取首个有版本的模型，作为训练产出版本的挂靠。
    listModels().then((res) => {
      if (cancelled) return;
      const withVersion = res.models.filter((m) => m.latest_version_id != null);
      const base = withVersion.find((m) => m.status === '生产候选') ?? withVersion[0];
      if (base?.latest_version_id != null) setBaseModelVersionId(base.latest_version_id);
    }).catch((err) => { if (!cancelled) console.warn('[training] listModels failed', err); });
    return () => { cancelled = true; };
  }, []);
  const handleStart = () => {
    if (datasetVersionId == null) { console.warn('[training] 尚未解析数据集版本，请稍后再试'); return; }
    createTrainingTask({
      dataset_version_id: datasetVersionId,
      base_model_id: baseModelVersionId ?? undefined,
      epochs: config.epochs,
      batch_size: config.batch_size,
      learning_rate: config.learning_rate,
      val_ratio: config.val_ratio,
    })
      .then((res) => { setJobId(res.job_id); setIsTraining(true); })
      .catch((err) => { console.warn('[training] createTrainingTask failed', err); });
  };
  const handleLogs = () => {
    if (!jobId) return;
    getTrainingLogs(jobId).then((text) => setLogs(text)).catch((err) => console.warn('[training] getTrainingLogs failed', err));
  };
  const pct = (v: number | undefined | null) => (v != null ? `${(v * 100).toFixed(1)}%` : null);
  const mAP = pct(trainRes?.metrics?.mAP50) ?? (isTraining ? '—' : '94.6%');
  const precision = pct(trainRes?.metrics?.precision) ?? (isTraining ? '—' : '96.2%');
  const recall = pct(trainRes?.metrics?.recall) ?? (isTraining ? '—' : '92.8%');
  const loss = trainRes?.loss_curve ?? null;
  const trainPath = loss && loss.train.length > 1 ? lossToPath(loss.train) : 'M0 212 C55 190 68 174 112 164 S170 128 208 132 S260 103 300 97 S355 80 387 76 S438 63 474 50 S530 34 600 23';
  const valPath = loss && loss.val.length > 1 ? lossToPath(loss.val) : 'M0 232 C60 220 72 210 125 194 S175 177 215 167 S270 150 312 143 S370 126 402 121 S450 111 492 92 S548 83 600 72';
  return <div className="page-wrap"><PageIntro eyebrow="模型工坊" title="模型训练" description="配置训练任务，快速迭代你的工业视觉模型。" action={<button className={`primary-button ${isTraining ? 'training-button' : ''}`} onClick={() => { if (isTraining) { setIsTraining(false); setJobId(null); } else handleStart(); }}>{isTraining ? <Activity size={16} /> : <Play size={16} />}{isTraining ? '训练进行中' : '开始新训练'}</button>} /><div className="training-layout"><section className="panel config-panel"><div className="panel-heading"><div><h2>训练配置</h2><p>从数据集到模型参数，一站式配置</p></div><span className="draft-tag">草稿</span></div><div className="form-block"><label>训练数据集</label><div className="select-field"><Database size={16} />主数据集 · 焊接缺陷检测 <ChevronDown size={15} /></div></div><div className="form-block"><label>选择基础模型</label><div className="model-select"><div className="model-logo">V</div><div><strong>VisionForge v2.1</strong><span>通用视觉检测模型 · 推荐</span></div><Check size={17} className="selected-check" /></div></div><div className="parameter-grid"><div className="form-block"><label>训练轮数 <CircleHelp size={13} /></label><div className="input-field">50 <span>epochs</span></div></div><div className="form-block"><label>批次大小 <CircleHelp size={13} /></label><div className="input-field">16 <span>batch</span></div></div><div className="form-block"><label>学习率</label><div className="input-field">0.001</div></div><div className="form-block"><label>验证集比例</label><div className="input-field">20%</div></div></div><div className="advanced-row"><SlidersHorizontal size={15} />高级参数<span>已配置 4 项</span><ChevronDown size={15} /></div><button className="full-button" onClick={handleStart}>{isTraining ? <><Activity size={16} />训练任务运行中</> : <><Play size={16} />开始训练任务</>}</button></section><section className="panel training-chart-panel"><div className="panel-heading"><div><h2>训练表现</h2><p>{jobId ? `任务 #${jobId} · 实时更新` : '最近一次训练任务 · #TR-20260814-07'}</p></div><span className={`run-status ${isTraining ? 'running' : ''}`}><i />{jobStatus === 'succeeded' ? '已完成' : jobStatus === 'failed' ? '失败' : isTraining ? `运行中 ${progress}%` : '已完成'}</span></div><div className="metric-row"><div><span>mAP@50</span><strong>{mAP}</strong></div><div><span>精确率</span><strong>{precision}</strong></div><div><span>召回率</span><strong>{recall}</strong></div></div><div className="line-chart"><div className="chart-y"><span>1.0</span><span>0.8</span><span>0.6</span><span>0.4</span><span>0.2</span><span>0</span></div><svg viewBox="0 0 600 250" preserveAspectRatio="none" role="img" aria-label="训练指标曲线"><path d={trainPath} fill="none" stroke="#1d8fa5" strokeWidth="4" /><path d={valPath} fill="none" stroke="#f0a34a" strokeWidth="3" strokeDasharray="7 7" /></svg><div className="chart-x"><span>0</span><span>10</span><span>20</span><span>30</span><span>40</span><span>50 epochs</span></div></div><div className="chart-key"><span><i className="legend-blue" />训练损失</span><span><i className="legend-orange" />验证损失</span></div></section></div><div className="training-note"><Terminal size={17} /><div><strong>训练日志</strong><p>{logs ?? (isTraining ? '正在准备数据增强策略... 预计 18 分钟后完成。' : '任务已完成，模型已自动保存至模型仓库。')}</p></div><button className="ghost-button" onClick={handleLogs}>查看完整日志 <ArrowUpRight size={14} /></button></div></div>;
}
export default App;
