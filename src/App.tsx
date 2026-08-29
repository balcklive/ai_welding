import { lazy, Suspense, useEffect, useState } from 'react';
import {
  ChevronDown, MoreHorizontal, Settings2, Sparkles,
} from 'lucide-react';
import { getToken } from './api/client';
import {
  createModel,
} from './api/models';
import Login from './pages/Login';
import { Toolbar } from './shared/components/Toolbar';
import {
  AnalysisSelect, DatasetTestingContext, SelectionRequired, SelectionSwitcher, VersionPanel,
} from './features/data-context/DataContext';
import { navStructure, workspaceHeaders } from './app/navigation';
import type { Route } from './app/navigation';

const OverviewPage = lazy(() => import('./features/overview/OverviewPage').then((module) => ({ default: module.OverviewPage })));
const DatasetWorkspace = lazy(() => import('./features/datasets/DatasetWorkspace').then((module) => ({ default: module.DatasetWorkspace })));
const RegistrationPage = lazy(() => import('./features/registration/RegistrationPage').then((module) => ({ default: module.RegistrationPage })));
const AnnotationWorkspace = lazy(() => import('./features/annotation/AnnotationWorkspace').then((module) => ({ default: module.AnnotationWorkspace })));
const AdvancedWeldAnalysis = lazy(() => import('./features/analysis/AnalysisWorkspace').then((module) => ({ default: module.AdvancedWeldAnalysis })));
const ValidationPage = lazy(() => import('./features/validation/ValidationPage').then((module) => ({ default: module.ValidationPage })));
const FeatureExtractionPage = lazy(() => import('./features/features/FeatureExtractionPage').then((module) => ({ default: module.FeatureExtractionPage })));
const AlignmentWorkspace = lazy(() => import('./features/alignment/AlignmentWorkspace').then((module) => ({ default: module.AlignmentWorkspace })));
const ModelRepository = lazy(() => import('./features/models/ModelCenter').then((module) => ({ default: module.ModelRepository })));
const TrainingDataPreparation = lazy(() => import('./features/models/ModelCenter').then((module) => ({ default: module.TrainingDataPreparation })));
const Training = lazy(() => import('./features/models/ModelCenter').then((module) => ({ default: module.Training })));
const ModelTestLive = lazy(() => import('./features/models/ModelCenter').then((module) => ({ default: module.ModelTestLive })));
const InferencePanel = lazy(() => import('./features/models/ModelCenter').then((module) => ({ default: module.InferencePanel })));

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
      <Suspense fallback={<div className="dataset-empty-state" role="status">页面加载中…</div>}>
        {route === 'overview' && <OverviewPage navigate={navigate} />}
        {route !== 'overview' && <WorkspaceFrame route={route} selectedDatasetId={selectedDatasetId} setSelectedDatasetId={setSelectedDatasetId} selectedDataId={selectedDataId} setSelectedDataId={setSelectedDataId} datasetHomeKey={datasetHomeKey} navigate={navigate} />}
      </Suspense>
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
  else if (route === 'data-center/validation') content = selectedDataId ? <ValidationPage embedded dataId={selectedDataId!} /> : <SelectionRequired onBack={() => navigate('data-center/datasets')} />;
  else if (route === 'data-center/versions') content = selectedDataId ? <VersionPanel dataId={selectedDataId!} /> : <SelectionRequired onBack={() => navigate('data-center/datasets')} />;
  else if (route === 'analysis/select') content = <AnalysisSelect selectedDatasetId={selectedDatasetId} setSelectedDatasetId={setSelectedDatasetId} onContinue={(id: string) => { setSelectedDataId(id); navigate('analysis/alignment'); }} />;
  else if (route === 'analysis/alignment') content = selectedDatasetId != null && selectedDataId ? <AlignmentWorkspace embedded dataId={selectedDataId} /> : <SelectionRequired onBack={() => navigate('analysis/select')} />;
  else if (route === 'analysis/analysis') content = selectedDatasetId != null && selectedDataId ? <AdvancedWeldAnalysis embedded dataId={selectedDataId} /> : <SelectionRequired onBack={() => navigate('analysis/select')} />;
  else if (route === 'analysis/split') content = selectedDatasetId != null && selectedDataId ? <AlignmentWorkspace embedded splitOnly dataId={selectedDataId} /> : <SelectionRequired onBack={() => navigate('analysis/select')} />;
  else if (route === 'analysis/annotation') content = selectedDatasetId != null && selectedDataId ? <AnnotationWorkspace embedded dataId={selectedDataId} /> : <SelectionRequired onBack={() => navigate('analysis/select')} />;
  else if (route === 'analysis/features') content = selectedDatasetId != null && selectedDataId ? <FeatureExtractionPage embedded dataId={selectedDataId} /> : <SelectionRequired onBack={() => navigate('analysis/select')} />;
  else if (route === 'model-center/dataset-build') content = <TrainingDataPreparation />;
  else if (route === 'model-center/repository') content = <ModelRepository refreshKey={repoRefresh} navigate={navigate} />;
  else if (route === 'model-center/training') content = <Training />;
  else if (route === 'model-center/testing') content = <><DatasetTestingContext /><ModelTestLive /></>;
  else if (route === 'model-center/inference') content = <InferencePanel />;

  const frameAction = ws === 'data-center' && route === 'data-center/datasets' ? () => navigate('data-center/registration') : route === 'model-center/repository' ? handleRepoCreate : undefined;
  return <div className={`workspace-page ${route === 'model-center/repository' ? 'model-repository-page' : ''}`}><div className="workspace-page-head"><div><div className="eyebrow"><span />{header.eyebrow}</div><h1>{header.title}</h1><p>{header.description}</p></div>{(toolbarConfig.action || toolbarConfig.secondary) && <Toolbar action={toolbarConfig.action} secondary={toolbarConfig.secondary} exportType={exportType} onAction={frameAction} />}</div>{showDataSwitcher && <SelectionSwitcher selectedDatasetId={selectedDatasetId} setSelectedDatasetId={setSelectedDatasetId} selectedDataId={selectedDataId} setSelectedDataId={setSelectedDataId} showContext={Boolean(showContext)} onChange={ws === 'data-center' ? () => navigate('data-center/datasets') : undefined} />}{content}</div>;
}

export default App;
