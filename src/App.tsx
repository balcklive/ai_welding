import { useMemo, useState } from 'react';
import {
  Activity, Archive, ArrowUpRight, BarChart3, Bell, Box, Check, ChevronDown,
  CircleHelp, Database, Factory, FileCheck2, Filter, Gauge, Layers3,
  MoreHorizontal, Play, Plus, Search, Settings2, SlidersHorizontal, Sparkles,
  Tag, Terminal, TrainFront, Upload, Users, WandSparkles, Waves, Zap,
  ClipboardCheck, FileText, GitBranch, ScanLine, Download, CheckCircle2,
  AlertTriangle, Eye, RefreshCw, ChevronLeft, ChevronRight, Cpu,
} from 'lucide-react';
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
const projects = [
  { name: '焊接缺陷检测 · 主数据集', count: '1,209', status: '已完成', tone: 'green' },
  { name: '表面质量巡检数据', count: '842', status: '标注中', tone: 'blue' },
  { name: '红外热成像样本', count: '367', status: '待处理', tone: 'orange' },
];
const bars = [46, 58, 52, 67, 61, 78, 74, 92, 81, 88, 72, 96];

function App() {
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

function WorkspaceFrame({ route, selectedDataId, setSelectedDataId, navigate }: { route: Route; selectedDataId: string | null; setSelectedDataId: (id: string) => void; navigate: (r: Route) => void }) {
  const ws = route.split('/')[0];
  const header = workspaceHeaders[ws];
  const toolbarConfig = ws === 'data-center' ? { action: '上传数据', secondary: '导出报告' }
    : route === 'analysis/annotation' ? { action: '保存标注', secondary: '导出结果' }
    : ws === 'analysis' ? { action: '开始处理', secondary: '导出结果' }
    : route === 'model-center/training' ? { action: '开始训练', secondary: '导出报告' }
    : { action: '新建模型', secondary: '导出报告' };
  const showContext = selectedDataId && (ws === 'data-center' || ws === 'analysis');

  let content: React.ReactNode = null;
  if (route === 'data-center/list') content = <ManagementFiltered navigate={navigate} selectedDataId={selectedDataId} setSelectedDataId={setSelectedDataId} />;
  else if (route === 'data-center/datasets') content = <DatasetWorkspace navigate={navigate} />;
  else if (route === 'data-center/registration') content = selectedDataId ? <Registration embedded /> : <SelectionRequired onBack={() => navigate('data-center/list')} />;
  else if (route === 'data-center/validation') content = selectedDataId ? <Validation embedded /> : <SelectionRequired onBack={() => navigate('data-center/list')} />;
  else if (route === 'data-center/versions') content = selectedDataId ? <VersionPanel /> : <SelectionRequired onBack={() => navigate('data-center/list')} />;
  else if (route === 'analysis/select') content = <AnalysisSelect onContinue={(id: string) => { setSelectedDataId(id); navigate('analysis/alignment'); }} />;
  else if (route === 'analysis/alignment') content = selectedDataId ? <Alignment embedded /> : <SelectionRequired onBack={() => navigate('analysis/select')} />;
  else if (route === 'analysis/analysis') content = selectedDataId ? <AdvancedWeldAnalysis embedded /> : <SelectionRequired onBack={() => navigate('analysis/select')} />;
  else if (route === 'analysis/split') content = selectedDataId ? <Alignment embedded splitOnly /> : <SelectionRequired onBack={() => navigate('analysis/select')} />;
  else if (route === 'analysis/annotation') content = selectedDataId ? <Annotation embedded /> : <SelectionRequired onBack={() => navigate('analysis/select')} />;
  else if (route === 'analysis/features') content = selectedDataId ? <FeatureExtraction embedded /> : <SelectionRequired onBack={() => navigate('analysis/select')} />;
  else if (route === 'model-center/repository') content = <ModelRepository />;
  else if (route === 'model-center/training') content = <><DatasetTrainingContext /><Training embedded /></>;
  else if (route === 'model-center/testing') content = <><DatasetTestingContext /><ModelTest embedded /></>;
  else if (route === 'model-center/inference') content = <InferencePanel />;

  return <div className="workspace-page"><div className="workspace-page-head"><div><div className="eyebrow"><span />{header.eyebrow}</div><h1>{header.title}</h1><p>{header.description}</p></div><Toolbar action={toolbarConfig.action} secondary={toolbarConfig.secondary} /></div>{showContext && <SelectionContext dataId={selectedDataId!} />}{content}</div>;
}

function PageIntro({ eyebrow, title, description, action }: { eyebrow: string; title: string; description: string; action?: React.ReactNode }) { return <div className="page-intro"><div><div className="eyebrow"><span />{eyebrow}</div><h1>{title}</h1><p>{description}</p></div>{action}</div>; }
const manufacturers = [
  { name: '中车四方', value: 28, tone: '#2c9caf' },
  { name: '中船重工', value: 22, tone: '#5fb8a6' },
  { name: '中集集团', value: 16, tone: '#f0a34a' },
  { name: '三一重工', value: 12, tone: '#e88d6c' },
  { name: '徐工集团', value: 9, tone: '#7ba7c4' },
  { name: '其他厂商', value: 13, tone: '#b0c4b8' },
];
const transitionTypes = [
  { name: '短路过渡', value: 32, tone: '#2c9caf' },
  { name: '射流过渡', value: 26, tone: '#5fb8a6' },
  { name: '混合过渡', value: 22, tone: '#f0a34a' },
  { name: 'CMT', value: 14, tone: '#e88d6c' },
  { name: '脉冲过渡', value: 6, tone: '#7ba7c4' },
];
const defectTypes = [
  { name: '气孔', count: 1086, tone: '#2c9caf' },
  { name: '焊瘤', count: 842, tone: '#5fb8a6' },
  { name: '未焊透', count: 624, tone: '#f0a34a' },
  { name: '焊穿', count: 467, tone: '#e88d6c' },
  { name: '咬边', count: 312, tone: '#7ba7c4' },
  { name: '夹渣', count: 293, tone: '#b0c4b8' },
];
const weldingTypes = [
  { name: 'MAG焊', value: 30, tone: '#2c9caf' },
  { name: 'MIG焊', value: 24, tone: '#5fb8a6' },
  { name: 'TIG焊', value: 18, tone: '#f0a34a' },
  { name: '埋弧焊', value: 14, tone: '#e88d6c' },
  { name: '等离子焊', value: 9, tone: '#7ba7c4' },
  { name: '激光焊', value: 5, tone: '#b0c4b8' },
];
const wordCloud = [
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
const weldingMachines = ['Fronius CMT', 'Kemppi Minarc', 'OTC FD-V8', 'Panasonic YD-500', 'Lincoln Power Wave', 'ESAB Aristo', '唐山松下', '奥太 NBC-350'];
const modalities = [
  { name: '时序数据', icon: Waves, desc: '电流/电压波形' },
  { name: '图像数据', icon: BarChart3, desc: '焊缝视觉照片' },
  { name: '音频数据', icon: Activity, desc: '焊接声纹信号' },
  { name: '红外热像', icon: Gauge, desc: '温度场分布' },
];

function Overview({ navigate }: { navigate: (route: Route) => void }) {
  const [activeProject] = useState(0);
  const filteredProjects = projects;
  return <div className="page-wrap"><PageIntro eyebrow="数据资产中心" title="数据总览" description="全面掌握焊接数据资产的规模、来源与质量分布。" />
    <div className="stat-grid"><StatCard icon={Database} label="数据总量" value="12,847" sub="条焊缝数据" /><StatCard icon={Factory} label="厂商总量" value="18" sub="家合作厂商" /><StatCard icon={Box} label="单条焊缝最大容量" value="2.4 GB" sub="含缺陷样本 3,624 条" /><StatCard icon={FileCheck2} label="已标注样本" value="10,038" sub="完成度 78.1%" /></div>

    <div className="attr-grid">
      <section className="panel attr-panel"><div className="attr-head"><Factory size={16} /><h2>焊机种类</h2><span className="attr-count">{weldingMachines.length} 种</span></div><div className="attr-tags">{weldingMachines.map((machine) => <span className="attr-tag" key={machine}>{machine}</span>)}</div></section>
      <section className="panel attr-panel"><div className="attr-head"><WandSparkles size={16} /><h2>缺陷种类</h2><span className="attr-count">{defectTypes.length} 种</span></div><div className="attr-tags">{defectTypes.map((defect, index) => <span className="attr-tag attr-tag-defect" key={defect.name}><i style={{ background: defect.tone }} />{defect.name}</span>)}</div></section>
      <section className="panel attr-panel"><div className="attr-head"><Layers3 size={16} /><h2>多模态种类</h2><span className="attr-count">{modalities.length} 种</span></div><div className="modality-list">{modalities.map((modality) => { const Icon = modality.icon; return <div className="modality-item" key={modality.name}><Icon size={15} /><div><strong>{modality.name}</strong><span>{modality.desc}</span></div></div>; })}</div></section>
      <section className="panel attr-panel"><div className="attr-head"><Gauge size={16} /><h2>时序数据采集频率</h2></div><div className="freq-display"><div className="freq-item"><span>最低频率</span><strong>1 kHz</strong></div><div className="freq-bar"><div className="freq-fill" /><div className="freq-dot" /><div className="freq-dot freq-dot-max" /></div><div className="freq-item"><span>最高频率</span><strong>50 kHz</strong></div></div><p className="freq-note">覆盖 5 个采样档位，支持多速率同步采集</p></section>
    </div>

    <div className="chart-row">
      <section className="panel donut-panel"><div className="panel-heading"><div><h2>厂商数据比重</h2><p>各厂商焊接数据占比分布</p></div></div><DonutChart data={manufacturers} /></section>
      <section className="panel donut-panel"><div className="panel-heading"><div><h2>过渡类型比重</h2><p>熔滴过渡方式分布</p></div></div><DonutChart data={transitionTypes} /></section>
      <section className="panel donut-panel"><div className="panel-heading"><div><h2>焊接类型比例</h2><p>不同焊接工艺占比</p></div></div><DonutChart data={weldingTypes} /></section>
    </div>

    <div className="chart-row-two">
      <section className="panel defect-panel"><div className="panel-heading"><div><h2>缺陷类型分布</h2><p>各类缺陷样本数量统计</p></div></div><div className="defect-chart">{defectTypes.map((defect) => <div className="defect-bar-row" key={defect.name}><span className="defect-label">{defect.name}</span><div className="defect-bar-track"><span style={{ width: `${(defect.count / 1086) * 100}%`, background: defect.tone }} /></div><span className="defect-count">{defect.count.toLocaleString()}</span></div>)}</div></section>
      <section className="panel wordcloud-panel"><div className="panel-heading"><div><h2>焊接厂商词云</h2><p>按数据量大小排列厂商名称</p></div></div><div className="wordcloud">{wordCloud.map((word, index) => <span className="wordcloud-item" style={{ fontSize: `${word.size}px`, opacity: 0.45 + word.size / 50, color: index < 3 ? '#2c9caf' : index < 6 ? '#5fb8a6' : '#7a9b9d' }} key={word.name}>{word.name}</span>)}</div></section>
    </div>

    <div className="section-title"><div><h2>数据项目</h2><p>共 {filteredProjects.length} 个项目正在协作</p></div><button className="ghost-button"><Filter size={15} />筛选</button></div><div className="dataset-grid">{filteredProjects.map((project, index) => <div className={`dataset-card ${index === activeProject ? 'current' : ''}`} key={project.name}><div className="dataset-top"><div className={`dataset-icon ${project.tone}`}><Box size={18} /></div><span className={`status ${project.tone}`}>{project.status}</span><MoreHorizontal size={17} className="muted-icon" /></div><h3>{project.name}</h3><p>最近更新于今天 09:42 · 多模态数据</p><div className="progress-meta"><span>标注进度</span><strong>{index === 0 ? '100%' : index === 1 ? '68%' : '24%'}</strong></div><div className="progress"><span style={{ width: `${index === 0 ? 100 : index === 1 ? 68 : 24}%` }} /></div><div className="dataset-footer"><span><Layers3 size={14} />{project.count} 条样本</span><button onClick={() => navigate('analysis/select')}>查看详情 <ArrowUpRight size={14} /></button></div></div>)}</div>
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

function Annotation({ embedded = false }: { embedded?: boolean }) {
  const [saved, setSaved] = useState(false);
  const [selectedLabels, setSelectedLabels] = useState(['焊瘤', '气孔']);
  const toggleLabel = (label: string) => setSelectedLabels((current) => current.includes(label) ? current.filter((item) => item !== label) : [...current, label]);
  return <div className={embedded ? 'embedded-page' : 'page-wrap'}><PageIntro eyebrow="数据生产线" title="数据标注" description="为模型准备高质量训练样本，支持多模态协同标注。" action={<><button className="outline-button"><Upload size={16} />导入数据</button><button className="primary-button" onClick={() => setSaved(true)}>{saved ? <Check size={16} /> : <Plus size={16} />}{saved ? '已保存' : '保存标注'}</button></>} /><div className="annotation-layout"><section className="panel annotation-board"><div className="board-toolbar"><div><span className="file-badge"><Archive size={15} />样本 0248 / 1209</span><h2>焊接件 · 视觉质检样本</h2></div><div className="toolbar-actions"><button className="icon-button"><SlidersHorizontal size={17} /></button><button className="select-button">图像标注 <ChevronDown size={14} /></button></div></div><div className="image-stage"><img src={labelImage} alt="待标注焊接样本" /><div className="annotation-box box-one"><span>焊瘤 <b>0.94</b></span></div><div className="annotation-box box-two"><span>气孔 <b>0.88</b></span></div><div className="stage-tip"><Sparkles size={14} />AI 已预标注 2 个区域</div></div><div className="board-footer"><div className="thumb-strip"><img src={detailImage} alt="样本缩略图" /><img className="thumb-active" src={labelImage} alt="当前样本缩略图" /><img src={modelImage} alt="样本缩略图" /><span>+ 9</span></div><div className="pagination"><button>‹</button><span>1 / 12</span><button>›</button></div></div></section><aside className="annotation-side"><section className="panel label-panel"><div className="panel-heading"><div><h2>标签类别</h2><p>选择需要应用的缺陷标签</p></div><button className="more-button"><MoreHorizontal size={18} /></button></div><div className="label-options">{['焊瘤', '气孔', '未熔合', '咬边', '正常'].map((label, index) => <button className={`label-chip ${selectedLabels.includes(label) ? 'chosen' : ''}`} onClick={() => toggleLabel(label)} key={label}><i className={`chip-dot chip-${index}`} />{label}<span>{selectedLabels.includes(label) ? <Check size={14} /> : '+'}</span></button>)}</div></section><section className="panel annotation-info"><div className="panel-heading"><div><h2>标注信息</h2><p>当前样本的详细信息</p></div></div><InfoRow label="数据来源" value="产线相机 · 03 号" /><InfoRow label="采集时间" value="2026-08-14 18:32" /><InfoRow label="标注人员" value="林工（我）" /><InfoRow label="置信度" value="94.2%" accent /></section><div className="ai-card"><div className="ai-card-icon"><Zap size={17} /></div><div><strong>智能标注建议</strong><p>已为你识别 2 个疑似缺陷区域，建议确认后提交。</p></div></div></aside></div></div>;
}
function SelectionContext({ dataId }: { dataId: string }) {
  const row = weldRows.find((item) => item.id === dataId) ?? weldRows[0];
  return <div className="selection-context"><div><span>当前选中数据</span><strong>{row.id}</strong></div><div><span>数据来源</span><strong>{row.source}</strong></div><div><span>焊机</span><strong>{row.machine}</strong></div><div><span>当前版本</span><strong>{row.version}</strong></div><StatusPill tone={row.quality === '异常' ? 'red' : row.quality === '待复核' ? 'orange' : 'green'}>{row.quality}</StatusPill></div>;
}

function SelectionRequired({ onBack }: { onBack: () => void }) {
  return <div className="selection-required"><div className="selection-icon"><Database size={23} /></div><h2>请先选择一条数据</h2><p>该功能需要基于具体焊缝数据执行，请返回数据列表选择后继续。</p><button className="outline-button" onClick={onBack}><ChevronLeft size={14} />返回数据列表</button></div>;
}

const datasetRows = [
  { id: 'DS-DEFECT-001', name: '焊接缺陷检测集', task: '目标检测', samples: '8,420', source: '产线相机 · 多品牌', progress: '96.8%', version: 'v1.3', status: '可训练', tone: 'green', split: '6,736 / 842 / 842' },
  { id: 'DS-POOL-002', name: '熔池分割数据集', task: '语义分割', samples: '5,680', source: '高速相机 · Fronius', progress: '91.2%', version: 'v0.8', status: '标注中', tone: 'orange', split: '4,544 / 568 / 568' },
  { id: 'DS-QUALITY-003', name: '工艺质量预测集', task: '多模态回归', samples: '2,140', source: '产线相机 · 多模态', progress: '100%', version: 'v2.0', status: '可训练', tone: 'green', split: '1,712 / 214 / 214' },
];

function DatasetWorkspace({ navigate }: { navigate: (route: Route) => void }) {
  const [selectedId, setSelectedId] = useState(datasetRows[0].id);
  const [view, setView] = useState<'list' | 'detail'>('list');
  const dataset = datasetRows.find((item) => item.id === selectedId) ?? datasetRows[0];
  return <div className="dataset-workspace"><div className="dataset-toolbar"><div><h2>数据集维护</h2><p>将已切分、已标注的样本固化为可复现的数据集版本，供训练和测试使用。</p></div><button className="primary-button"><Plus size={15} />新建数据集</button></div><div className="dataset-subtabs"><button className={view === 'list' ? 'active' : ''} onClick={() => setView('list')}>数据集列表 <b>{datasetRows.length}</b></button><button className={view === 'detail' ? 'active' : ''} onClick={() => setView('detail')}>数据集详情</button></div>{view === 'list' ? <><div className="dataset-rule"><GitBranch size={14} /><span>数据集以版本快照形式保存，不直接读取会持续变化的原始数据。</span><span className="dataset-rule-count">可训练 {datasetRows.filter((item) => item.status === '可训练').length} 个</span></div><div className="dataset-table">{datasetRows.map((item) => <button className={`dataset-list-row ${selectedId === item.id ? 'selected' : ''}`} onClick={() => { setSelectedId(item.id); setView('detail'); }} key={item.id}><span className="dataset-row-icon"><Box size={17} /></span><span className="dataset-row-main"><strong>{item.name}</strong><small>{item.id} · {item.task}</small></span><span><small>样本数</small><strong className="mono">{item.samples}</strong></span><span><small>标注完成度</small><strong className="mono">{item.progress}</strong></span><span><small>当前版本</small><strong className="mono">{item.version}</strong></span><StatusPill tone={item.tone as 'green' | 'orange'}>{item.status}</StatusPill><ArrowUpRight size={15} className="muted-icon" /></button>)}</div></> : <DatasetDetail dataset={dataset} navigate={navigate} />}</div>;
}

function DatasetDetail({ dataset, navigate }: { dataset: typeof datasetRows[number]; navigate: (route: Route) => void }) {
  return <div className="dataset-detail"><div className="dataset-detail-head"><div><span className="file-badge"><Box size={14} />{dataset.id}</span><h2>{dataset.name} <em>{dataset.version}</em></h2><p>{dataset.task} · {dataset.source} · 最近更新今天 10:06</p></div><div className="dataset-detail-actions"><StatusPill tone={dataset.tone as 'green' | 'orange'}>{dataset.status}</StatusPill><button className="primary-button" disabled={dataset.status !== '可训练'} onClick={() => navigate('model-center/training')}><Play size={14} />进入模型训练</button></div></div><div className="dataset-detail-grid"><div className="dataset-detail-stat"><span>样本总数</span><strong>{dataset.samples}</strong><small>已生成切分样本</small></div><div className="dataset-detail-stat"><span>标注完成度</span><strong>{dataset.progress}</strong><small>通过质检的标注</small></div><div className="dataset-detail-stat"><span>训练 / 验证 / 测试</span><strong>{dataset.split}</strong><small>按焊缝 ID 固定划分</small></div><div className="dataset-detail-stat"><span>数据质量</span><strong>98.4%</strong><small>重复与空标注已检查</small></div></div><DatasetInputPanel task={dataset.task} /><ModelReadiness task={dataset.task} status={dataset.status} /><div className="dataset-detail-columns"><section className="panel"><div className="panel-heading"><div><h2>数据集版本</h2><p>每个版本对应一份固定样本清单</p></div><button className="outline-button"><GitBranch size={14} />新建版本</button></div><div className="dataset-version-list"><div className="dataset-version current"><span>v1.3</span><div><strong>人工修正后版本</strong><small>2026-08-15 10:06 · 林工 · 8,420 条样本</small></div><StatusPill>当前版本</StatusPill></div><div className="dataset-version"><span>v1.2</span><div><strong>完成多模态对齐</strong><small>2026-08-14 18:20 · 算法任务 · 8,104 条样本</small></div><button className="ghost-button">查看</button></div></div></section><section className="panel"><div className="panel-heading"><div><h2>数据血缘</h2><p>从原始数据到训练任务的关联</p></div></div><div className="lineage"><span><Database size={14} />原始焊缝数据 <b>1,086 条</b></span><i>↓</i><span><Tag size={14} />标注任务 AN-0248 <b>已审核</b></span><i>↓</i><span><Box size={14} />当前数据集 {dataset.version} <b>固定快照</b></span><i>↓</i><span><TrainFront size={14} />关联模型训练 <b>3 次</b></span></div></section></div></div>;
}

const inputDimensions = ['Voltage', 'GasSpeed', 'Current', 'Molten_feature', 'Sound_feature', '焊缝照片', '熔池视频'];
const requiredByTask: Record<string, string[]> = { '目标检测': ['Current', 'Voltage', 'GasSpeed'], '语义分割': ['熔池视频'], '多模态回归': ['Current', 'Voltage'] };

function DatasetInputPanel({ task }: { task: string }) {
  const required = requiredByTask[task] ?? [];
  return <section className="panel dataset-input-panel"><div className="panel-heading"><div><h2>输入数据维度</h2><p>字段是否存在由采集情况决定，训练资格按当前任务动态判断。</p></div><span className="dataset-task-tag">{task}</span></div><div className="dimension-grid">{inputDimensions.map((dimension) => { const isRequired = required.includes(dimension); const isAvailable = task === '语义分割' ? ['熔池视频', '焊缝照片', 'Molten_feature'].includes(dimension) : task === '多模态回归' ? ['Current', 'Voltage', 'GasSpeed', 'Molten_feature', 'Sound_feature', '熔池视频'].includes(dimension) : ['Current', 'Voltage', 'GasSpeed', 'Molten_feature', 'Sound_feature'].includes(dimension); return <div className={`dimension-item ${isRequired ? 'required' : ''}`} key={dimension}><span className="dimension-status">{isAvailable ? <CheckCircle2 size={14} /> : <AlertTriangle size={14} />}</span><div><strong>{dimension}</strong><small>{isRequired ? '当前任务必需' : isAvailable ? '已具备 · 可选输入' : '缺失 · 不影响当前任务'}</small></div><StatusPill tone={isAvailable ? 'green' : 'orange'}>{isAvailable ? '已具备' : '缺失'}</StatusPill></div>; })}</div></section>;
}

function ModelReadiness({ task, status }: { task: string; status: string }) {
  const checks = task === '语义分割' ? ['熔池视频已切分为图像帧', '图像与像素级掩膜数量一致', '标注审核通过率 ≥ 90%', '按焊缝 ID 完成数据划分'] : task === '多模态回归' ? ['Current 与 Voltage 时间轴已对齐', '至少具备两种输入模态', '质量标签完整且无空值', '按焊缝 ID 完成数据划分'] : ['Current、Voltage、GasSpeed 均完整', '异常区段标签已审核', '信号采样率与时间轴一致', '按焊缝 ID 完成数据划分'];
  return <section className="panel readiness-panel"><div className="panel-heading"><div><h2>模型适配检查</h2><p>当前数据集按照“{task}”的最低训练要求检查。</p></div><StatusPill tone={status === '可训练' ? 'green' : 'orange'}>{status === '可训练' ? '可训练' : '暂不可训练'}</StatusPill></div><div className="readiness-grid">{checks.map((check) => <div key={check}><CheckCircle2 size={14} /><span>{check}</span></div>)}</div><div className="split-policy"><GitBranch size={14} /><span>划分策略：按焊缝 ID 分组，避免同一焊缝的视频帧同时出现在训练集和测试集。</span></div></section>;
}

function DatasetTrainingContext() { return <div className="model-dataset-context"><div className="dataset-row-icon"><Box size={16} /></div><div><span>当前训练数据集</span><strong>焊接缺陷检测集 · v1.3</strong></div><div><span>训练 / 验证 / 测试</span><strong>6,736 / 842 / 842</strong></div><StatusPill>可训练</StatusPill><button className="ghost-button">更换数据集 <ChevronDown size={13} /></button></div>; }
function DatasetTestingContext() { return <div className="model-dataset-context"><div className="dataset-row-icon"><Box size={16} /></div><div><span>当前测试数据集</span><strong>焊接缺陷检测集 · v1.3</strong></div><div><span>固定测试集</span><strong>842 条样本</strong></div><StatusPill>固定快照</StatusPill><button className="ghost-button">更换数据集 <ChevronDown size={13} /></button></div>; }

function AnalysisSelect({ onContinue }: { onContinue: (id: string) => void }) {
  return <div className="selection-workspace"><div className="selection-hero"><div className="selection-icon"><Waves size={25} /></div><div><h2>选择一条焊缝开始分析</h2><p>选择已登记且核验通过的数据，进入多模态分析流程。</p></div></div><div className="selection-grid">{weldRows.slice(0, 3).map((row, index) => <button className={`selection-card ${index === 0 ? 'selected' : ''}`} onClick={() => onContinue(row.id)} key={row.id}><div><span className="file-badge"><Archive size={14} />{row.id}</span><h3>{index === 0 ? 'MAG 短路过渡 · 典型稳定样本' : index === 1 ? '熔池异常 · 待复核样本' : '红外多模态 · 工艺验证样本'}</h3><p>{row.machine} · {row.types}</p></div><StatusPill tone={index === 1 ? 'orange' : 'green'}>{index === 1 ? '待复核' : '核验通过'}</StatusPill></button>)}</div></div>;
}

function VersionPanel() {
  return <section className="panel version-panel"><div className="panel-heading"><div><h2>数据版本</h2><p>原始数据与加工结果的版本链路</p></div><StatusPill>当前版本 v1.3</StatusPill></div><div className="version-line">{['v1.0 原始数据', 'v1.1 去噪处理', 'v1.2 时间对齐', 'v1.3 人工修正'].map((item, index) => <div className={index === 3 ? 'current' : ''} key={item}><i /><span>{item}<small>{index === 0 ? '2026-08-15 09:42 · 系统导入' : index === 1 ? '2026-08-15 09:45 · 林工' : index === 2 ? '2026-08-15 09:48 · 算法任务' : '2026-08-15 10:06 · 林工'}</small></span><button className="ghost-button">查看</button></div>)}</div></section>;
}

function ModelRepository() {
  const models = [{ name: '焊接异常检测模型', version: 'v1.8', type: '时序分类', metric: 'F1 95.5%', status: '生产候选' }, { name: '熔池分割模型', version: 'v2.1', type: '语义分割', metric: 'mIoU 91.2%', status: '训练中' }, { name: '质量预测模型', version: 'v0.9', type: '多模态回归', metric: 'R² 0.93', status: '实验版本' }];
  return <div className="model-repository"><div className="repository-summary"><div><span>模型总数</span><strong>18</strong></div><div><span>生产候选</span><strong>6</strong></div><div><span>最近训练</span><strong>今天 09:42</strong></div><div><span>GPU 资源</span><strong>42%</strong></div></div><div className="model-card-grid">{models.map((model) => <section className="panel model-card" key={model.name}><div className="model-card-top"><div className="model-logo"><Cpu size={17} /></div><StatusPill tone={model.status === '训练中' ? 'orange' : 'green'}>{model.status}</StatusPill><MoreHorizontal size={16} className="muted-icon" /></div><h2>{model.name}</h2><p>{model.type} · {model.version}</p><div className="model-metric"><span>核心指标</span><strong>{model.metric}</strong></div><div className="model-card-footer"><span>最近更新 2 小时前</span><button className="ghost-button">查看详情 <ArrowUpRight size={13} /></button></div></section>)}</div></div>;
}

function InferencePanel() {
  return <section className="panel inference-panel"><div className="panel-heading"><div><h2>推理验证</h2><p>选择模型和样本，预览模型输出结果</p></div><StatusPill>就绪</StatusPill></div><div className="inference-layout"><div className="inference-drop"><Upload size={23} /><strong>选择测试样本</strong><span>支持图像、视频帧或时序信号</span><button className="outline-button">选择样本</button></div><div className="inference-result"><div className="result-placeholder"><ScanLine size={28} /><span>推理结果将在这里展示</span></div><div className="result-row"><span>模型置信度</span><strong>—</strong></div><div className="result-row"><span>推理耗时</span><strong>—</strong></div></div></div></section>;
}

function Toolbar({ action, secondary = '导出报告' }: { action: string; secondary?: string }) {
  return <div className="page-toolbar"><button className="ghost-button"><RefreshCw size={14} />刷新</button><button className="outline-button"><Download size={14} />{secondary}</button><button className="primary-button"><Plus size={15} />{action}</button></div>;
}

function StatusPill({ children, tone = 'green' }: { children: React.ReactNode; tone?: 'green' | 'orange' | 'red' | 'blue' }) {
  return <span className={`status ${tone}`}>{children}</span>;
}

const weldRows = [
  { id: 'WLD-20260815-0248', time: '2026-08-15 09:42', source: '产线相机 · 03号', machine: 'Fronius CMT', types: '视频 / 时序 / 声音', quality: '通过', version: 'v1.3' },
  { id: 'WLD-20260815-0247', time: '2026-08-15 09:18', source: '实训线 · 02号', machine: 'OTC FD-V8', types: '视频 / 时序', quality: '待复核', version: 'v2.0' },
  { id: 'WLD-20260814-0246', time: '2026-08-14 18:32', source: '产线相机 · 03号', machine: 'Kemppi Minarc', types: '视频 / 时序 / 红外', quality: '通过', version: 'v1.1' },
  { id: 'WLD-20260814-0245', time: '2026-08-14 16:07', source: '实训线 · 01号', machine: 'Panasonic YD-500', types: '视频 / 声音', quality: '异常', version: 'v1.0' },
];

function ManagementFiltered({ navigate, selectedDataId, setSelectedDataId }: { navigate: (route: Route) => void; selectedDataId: string | null; setSelectedDataId: (id: string) => void }) {
  const [query, setQuery] = useState('');
  const [source, setSource] = useState('全部来源');
  const [brand, setBrand] = useState('全部品牌');
  const filteredRows = useMemo(() => weldRows.filter((row) => {
    const search = query.trim().toLowerCase();
    return (!search || `${row.id} ${row.source} ${row.machine}`.toLowerCase().includes(search)) && (source === '全部来源' || row.source.includes(source)) && (brand === '全部品牌' || row.machine.startsWith(brand));
  }), [query, source, brand]);
  return <section className="panel table-panel"><div className="data-filter-strip"><label className="filter-field keyword">关键词<div className="inline-search"><Search size={14} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="焊缝ID、登记编号" /></div></label><label className="filter-field">数据来源<select value={source} onChange={(event) => setSource(event.target.value)}><option>全部来源</option><option>产线相机</option><option>实训线</option></select></label><label className="filter-field">焊机品牌<select value={brand} onChange={(event) => setBrand(event.target.value)}><option>全部品牌</option><option>Fronius</option><option>OTC</option><option>Kemppi</option><option>Panasonic</option></select></label><button className="outline-button filter-reset" onClick={() => { setQuery(''); setSource('全部来源'); setBrand('全部品牌'); }}><RefreshCw size={13} />重置</button></div><div className="latest-version-note"><GitBranch size={14} />列表按焊缝 ID 去重，仅显示每条数据的最新版本</div><div className="table-toolbar"><div className="filter-tabs"><button className="active">全部最新数据 <b>{filteredRows.length}</b></button><button>待核验 <b>126</b></button><button>已归档 <b>8,204</b></button></div><div className="table-actions"><button className="select-button" onClick={() => { setQuery(''); setSource('全部来源'); setBrand('全部品牌'); }}><RefreshCw size={14} />重置筛选</button></div></div><div className="selection-bar">{selectedDataId ? <>当前选中：<strong>{selectedDataId}</strong><span>登记、核验、版本和分析操作将基于此数据</span></> : <>尚未选择数据<span>点击任意数据行即可选择</span></>}<button className="ghost-button" onClick={() => selectedDataId && navigate('analysis/select')}>进入分析与标注 <ArrowUpRight size={14} /></button></div><div className="data-table"><div className="table-row table-head"><span>状态</span><span>焊缝 / 登记编号</span><span>采集时间</span><span>数据来源</span><span>焊机品牌 / 型号</span><span>数据模态</span><span>核验状态</span><span>最新版本</span><span>操作</span></div>{filteredRows.map((row) => <div className={`table-row ${selectedDataId === row.id ? 'selected-row' : ''}`} onClick={() => setSelectedDataId(row.id)} key={row.id}><span><input type="radio" checked={selectedDataId === row.id} onChange={() => setSelectedDataId(row.id)} aria-label={`选择 ${row.id}`} /></span><span className="id-cell"><strong>{row.id}</strong><small>登记台账 · 最新版本</small></span><span>{row.time}</span><span>{row.source}</span><span>{row.machine}</span><span>{row.types}</span><span><StatusPill tone={row.quality === '异常' ? 'red' : row.quality === '待复核' ? 'orange' : 'green'}>{row.quality}</StatusPill></span><span className="mono">{row.version}</span><span><button className="table-icon" onClick={(event) => { event.stopPropagation(); setSelectedDataId(row.id); navigate('analysis/select'); }} aria-label="进入分析"><Eye size={15} /></button></span></div>)}</div><div className="table-footer"><span>显示 {filteredRows.length} 条最新数据，共 12,847 条数据</span><div className="pagination"><button><ChevronLeft size={14} /></button><span>1 / 3212</span><button><ChevronRight size={14} /></button></div></div></section>;
}

function Registration({ embedded = false }: { embedded?: boolean }) {
  const [registered, setRegistered] = useState(false);
  return <div className="page-wrap"><PageIntro eyebrow="标准化台账" title="数据登记" description="为每批焊接多模态数据建立统一身份、来源和工艺参数档案。" action={<span className="workflow-chip"><CheckCircle2 size={14} />登记即进入数据流程</span>} /><div className="registration-layout"><section className="panel form-panel"><div className="panel-heading"><div><h2>新建数据登记</h2><p>带 * 的字段为必填项</p></div><span className="draft-tag">登记草稿</span></div><div className="form-section-title"><span>基础信息</span><i /></div><div className="form-grid"><label>数据来源 *<input placeholder="例如：产线相机 · 03号" /></label><label>采集时间 *<input value="2026-08-15 09:42" readOnly /></label><label>焊缝 / 批次名称 *<input placeholder="输入焊缝或批次名称" /></label><label>关联产品信息<input placeholder="产品型号、零件编号" /></label></div><div className="form-section-title"><span>采集与工艺参数</span><i /></div><div className="form-grid"><label>焊机型号<select defaultValue="Fronius CMT"><option>Fronius CMT</option><option>OTC FD-V8</option><option>Panasonic YD-500</option></select></label><label>焊接方法<select defaultValue="MAG焊"><option>MAG焊</option><option>MIG焊</option><option>TIG焊</option></select></label><label>板材材质<input placeholder="例如：Q235B" /></label><label>板材厚度<input placeholder="例如：6 mm" /></label><label>电流 / 电压<input placeholder="180 A / 22 V" /></label><label>采样频率<input placeholder="10 kHz" /></label></div><div className="upload-zone"><Upload size={20} /><strong>拖入或选择原始数据文件</strong><span>支持视频、CSV、WAV、JSON、图片 · 单文件不超过 2 GB</span><button className="outline-button">选择文件</button></div><button className="full-button" onClick={() => setRegistered(true)}>{registered ? <><CheckCircle2 size={16} />登记已生成：REG-20260815-00249</> : <><FileCheck2 size={16} />生成登记编号</>}</button></section><aside className="registration-aside"><section className="panel"><div className="panel-heading"><div><h2>登记规则</h2><p>平台数据使用约束</p></div><ClipboardCheck size={18} className="accent-text" /></div>{['自动生成唯一登记编号', '原始文件与后续版本自动关联', '登记后触发入库前数据核验', '所有操作写入审计日志'].map((item) => <div className="rule-row" key={item}><CheckCircle2 size={15} />{item}</div>)}</section><section className="panel"><div className="panel-heading"><div><h2>最近登记</h2><p>最近 24 小时新增数据</p></div></div>{weldRows.slice(0, 3).map((row) => <div className="recent-row" key={row.id}><span className="recent-dot" /><div><strong>{row.id}</strong><small>{row.source} · {row.time.slice(11)}</small></div><StatusPill>已登记</StatusPill></div>)}</section></aside></div></div>;
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
const channels: Chan[] = [
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
  return values.map((v, i) => {
    const px = AXIS_L + (i / (SAMPLES - 1)) * PLOT_W;
    const py = (PLOT_H * (1 - (v - lo) / range));
    return `${i === 0 ? 'M' : 'L'}${px.toFixed(1)} ${py.toFixed(1)}`;
  }).join(' ');
}


function PhasePlot({ cursor, onCursor }: { cursor: number; onCursor: (s: number) => void }) {
  const w = 260; const h = 230; const pad = 26; const pw = w - pad * 2; const ph = h - pad * 2;
  const cxLo = 140; const cxHi = 230; const cvLo = 15; const cvHi = 30;
  const toX = (c: number) => pad + ((c - cxLo) / (cxHi - cxLo)) * pw;
  const toY = (v: number) => pad + (1 - (v - cvLo) / (cvHi - cvLo)) * ph;
  const points = t.map((ts, i) => ({ x: toX(sigCur[i]), y: toY(sigVol[i]), ts, i, anom: isAnom(ts) }));
  const path = points.map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(' ');
  const cursorIdx = Math.min(points.length - 1, Math.max(0, Math.round((cursor / dur) * (points.length - 1))));
  const cp = points[cursorIdx];
  const x = (e: React.MouseEvent<SVGSVGElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const relX = (e.clientX - rect.left) / rect.width * w;
    const c = cxLo + ((relX - pad) / pw) * (cxHi - cxLo);
    let best = 0; let bd = Infinity;
    for (let i = 0; i < points.length; i++) { const d = Math.abs(sigCur[i] - c); if (d < bd) { bd = d; best = i; } }
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

function PddChart({ chanId }: { chanId: string }) {
  const chan = channels.find((c) => c.id === chanId) ?? channels[0];
  const bins = 28;
  const vals = chan.values;
  const lo = chan.lo; const hi = chan.hi;
  const counts = new Array(bins).fill(0);
  vals.forEach((v) => { const b = clamp(Math.floor(((v - lo) / (hi - lo)) * bins), 0, bins - 1); counts[b]++; });
  const max = Math.max(...counts) || 1;
  const w = 260; const h = 200; const pad = 28; const pw = w - pad - 12; const ph = h - pad - 16;
  const bw = pw / bins;
  const kde: number[] = [];
  for (let i = 0; i < bins; i++) {
    let sum = 0;
    for (let j = 0; j < bins; j++) { const d = (i - j) / 3.5; sum += counts[j] * Math.exp(-d * d); }
    kde.push(sum);
  }
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

function ExploreWaveform({ active, cursor, onCursor, mode }: { active: Set<string>; cursor: number; onCursor: (s: number) => void; mode: string }) {
  const x = (e: React.MouseEvent<SVGSVGElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const rel = (e.clientX - rect.left) / rect.width;
    onCursor(clamp(rel * dur, 0, dur));
  };
  const cursorX = AXIS_L + (cursor / dur) * PLOT_W;
  const visible = channels.filter((c) => active.has(c.id));
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

function applyFilter(values: number[], type: FilterType, freq: number, freq2: number): number[] {
  const out = [...values];
  for (let pass = 0; pass < 3; pass++) {
    const tmp = [...out];
    for (let i = 2; i < tmp.length; i++) {
      const a = (tmp[i] + tmp[i - 1] + tmp[i - 2]) / 3;
      if (type === '低通') out[i] = tmp[i] * (1 - freq) + a * freq;
      else if (type === '高通') out[i] = tmp[i] - a * freq * 0.6;
      else out[i] = tmp[i] * (1 - freq2) + (tmp[i] - a) * freq;
    }
  }
  return out;
}

function PsdChart({ values, color, lo, hi }: { values: number[]; color: string; lo: number; hi: number }) {
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
  const max = Math.max(...mags) || 1;
  const welchBins = 24;
  const welch: number[] = [];
  const binSize = Math.floor(half / welchBins) || 1;
  for (let b = 0; b < welchBins; b++) {
    let sum = 0;
    for (let j = 0; j < binSize; j++) { sum += mags[b * binSize + j] ?? 0; }
    welch.push(sum / binSize);
  }
  const wMax = Math.max(...welch) || 1;
  const W = 660; const H = 180; const pad = 30; const pw = W - pad - 12; const ph = H - pad - 18;
  const bw = pw / welchBins;
  const path = welch.map((w, i) => { const px = pad + i * bw + bw / 2; const py = pad + ph * (1 - w / wMax); return `${i === 0 ? 'M' : 'L'}${px.toFixed(1)} ${py.toFixed(1)}`; }).join(' ');
  const labels = ['0', '0.5k', '1k', '2k', '5k', '10k'];
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

function StftHeatmap({ values, color }: { values: number[]; color: string }) {
  const cols = 40; const rows = 16;
  const N = values.length;
  const win = Math.floor(N / cols) || 1;
  const heat: number[][] = [];
  let gMax = 0;
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

function DwtChart({ values, color }: { values: number[]; color: string }) {
  const levels = 4;
  const W = 660; const H = 180; const pad = 30; const pw = W - pad - 8;
  const bandH = (H - pad - 10) / (levels + 1);
  const approx = [...values];
  const bands: number[][] = [];
  for (let lv = 0; lv < levels; lv++) {
    const detail: number[] = [];
    const next: number[] = [];
    for (let i = 0; i < approx.length - 1; i += 2) {
      const a = (approx[i] + approx[i + 1]) / 2;
      const d = (approx[i] - approx[i + 1]) / 2;
      next.push(a); detail.push(d);
    }
    bands.push(detail);
    approx.length = 0; approx.push(...next);
  }
  const allBands = [...bands, approx];
  const allMax = Math.max(...allBands.flatMap((b) => b.map(Math.abs))) || 1;
  const toBandPath = (band: number[], yOff: number) => {
    const step = pw / (band.length - 1 || 1);
    return band.map((v, i) => { const px = pad + i * step; const py = yOff + bandH / 2 - (v / allMax) * (bandH / 2 - 2); return `${i === 0 ? 'M' : 'L'}${px.toFixed(1)} ${py.toFixed(1)}`; }).join(' ');
  };
  return <svg viewBox={`0 0 ${W} ${H}`} className="dwt-svg" preserveAspectRatio="none">
    {allBands.map((band, lv) => {
      const yOff = pad + lv * bandH;
      const label = lv < levels ? `D${levels - lv}` : `A${levels}`;
      const c = lv < levels ? color : '#f0a34a';
      return <g key={lv}>
        <line x1={pad} y1={yOff + bandH} x2={pad + pw} y2={yOff + bandH} stroke="#edf2f2" />
        <text x={6} y={yOff + bandH / 2 + 3} className="psd-axis">{label}</text>
        <path d={toBandPath(band, yOff)} fill="none" stroke={c} strokeWidth="1.4" opacity="0.85" />
      </g>;
    })}
    <text x={pad + pw / 2} y={H - 2} className="psd-axis" textAnchor="middle">样本点</text>
  </svg>;
}

function WaveletDecomp({ values, color }: { values: number[]; color: string }) {
  const levels = 5;
  const W = 660; const H = 200; const pad = 34; const pw = W - pad - 8;
  const bandH = (H - pad - 10) / levels;
  const wavelets = ['db4', 'sym3', 'coif1', 'haar', 'bior1.3'];
  const recon: number[][] = [];
  let cur = [...values];
  for (let lv = 0; lv < levels; lv++) {
    const comp: number[] = [];
    const scale = (lv + 1) * 4;
    for (let i = 0; i < cur.length; i++) {
      const win = cur.slice(Math.max(0, i - scale), Math.min(cur.length, i + scale));
      const m = win.reduce((s, v) => s + v, 0) / win.length;
      const d = cur[i] - m;
      comp.push(d * (1 + lv * 0.3) + Math.sin(i * 0.4 + lv) * 3 * (lv / levels));
    }
    recon.push(comp);
  }
  const allMax = Math.max(...recon.flatMap((b) => b.map(Math.abs))) || 1;
  return <svg viewBox={`0 0 ${W} ${H}`} className="wavelet-decomp-svg" preserveAspectRatio="none">
    {recon.map((band, lv) => {
      const yOff = pad + lv * bandH;
      const step = pw / (band.length - 1 || 1);
      const path = band.map((v, i) => { const px = pad + i * step; const py = yOff + bandH / 2 - (v / allMax) * (bandH / 2 - 2); return `${i === 0 ? 'M' : 'L'}${px.toFixed(1)} ${py.toFixed(1)}`; }).join(' ');
      const opacity = 0.4 + (lv / levels) * 0.5;
      return <g key={lv}>
        <line x1={pad} y1={yOff + bandH} x2={pad + pw} y2={yOff + bandH} stroke="#edf2f2" />
        <text x={6} y={yOff + bandH / 2 + 3} className="psd-axis">L{lv + 1}</text>
        <path d={path} fill="none" stroke={color} strokeWidth="1.3" opacity={opacity} />
      </g>;
    })}
    <text x={pad + pw / 2} y={H - 2} className="psd-axis" textAnchor="middle">样本点</text>
  </svg>;
}



function AdvancedWeldAnalysis({ embedded = false }: { embedded?: boolean }) {
  const [mode, setMode] = useState('时域');
  const [active, setActive] = useState<Set<string>>(new Set(['cur', 'vol', 'gas']));
  const [cursor, setCursor] = useState(2.1);
  const [pddChan, setPddChan] = useState('cur');
  const [filterOn, setFilterOn] = useState(false);
  const [filterType, setFilterType] = useState<FilterType>('低通');
  const [cutoff, setCutoff] = useState(0.3);
  const [cutoff2, setCutoff2] = useState(0.6);
  const [filterChan, setFilterChan] = useState('cur');
  const toggle = (id: string) => setActive((prev) => { const n = new Set(prev); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  const anomalies = [{ range: anomalA, type: '电弧不稳', sev: 'orange' as const }, { range: anomalB, type: '飞溅倾向', sev: 'red' as const }];
  const filterChanObj = channels.find((c) => c.id === filterChan) ?? channels[0];
  const filteredValues = filterOn ? applyFilter(filterChanObj.values, filterType, cutoff, cutoff2) : filterChanObj.values;
  const modes = ['时域', 'PSD', 'STFT', 'DWT', '小波分解'];
  return <div className="page-wrap"><PageIntro eyebrow="焊缝级分析" title="焊缝深度分析" description="在同一时间轴上查看多模态信号、焊接事件和质量特征。" action={<Toolbar action="开始分析" secondary="导出分析报告" />} /><div className="analysis-meta panel"><div><span className="file-badge"><Archive size={15} />REG-20260815-00248</span><h2>焊缝 · MAG 短路过渡样本</h2><p>Fronius CMT · Q235B · 6 mm · 2026-08-15 09:42</p></div><div className="analysis-kpis"><div><span>核验状态</span><strong className="accent-text">通过</strong></div><div><span>有效焊接段</span><strong>3.86 s</strong></div><div><span>异常区段</span><strong className="warning-text">2 个</strong></div></div></div>
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
      {mode === '时域' && <><ExploreWaveform active={active} cursor={cursor} onCursor={setCursor} mode={mode} />{filterOn && <div className="filter-compare"><span className="fc-label">滤波后 {filterChanObj.name}（{filterType} · {cutoff.toFixed(2)}）</span><svg viewBox={`0 0 ${CH} 70`} className="filter-compare-svg" preserveAspectRatio="none"><path d={toPath(applyFilter(filterChanObj.values, filterType, cutoff, cutoff2), filterChanObj.lo, filterChanObj.hi).split('M').map((s) => 'M' + s).join('').replace(/^M/, '')} fill="none" stroke={filterChanObj.color} strokeWidth="1.8" opacity="0.7" /></svg></div>}
      <div className="event-track"><span>起弧 <b>00:00.42</b></span><i /><span>稳态焊接 <b>00:00.78 - 00:04.28</b></span><i /><span>收弧 <b>00:04.86</b></span></div>
      <div className="anomaly-summary"><div className="anomaly-summary-head"><AlertTriangle size={14} /><span>已检出异常区段 {anomalies.length} 个 · 点击可定位</span></div>{anomalies.map((a, i) => <button key={i} className={`anomaly-chip ${a.sev}`} onClick={() => setCursor((a.range[0] + a.range[1]) / 2)}><i /><strong>{a.type}</strong><small>{fmt(a.range[0])} – {fmt(a.range[1])}</small><span>定位 <ArrowUpRight size={12} /></span></button>)}</div>
      <div className="signal-cards">{channels.map((c) => <div key={c.id} className={active.has(c.id) ? '' : 'dim'}><Waves size={16} /><span>{c.name}波形<strong>{c.mean}</strong></span></div>)}</div></>}
      {mode === 'PSD' && <div className="spectrum-view"><div className="spectrum-head"><span><FilterIcon size={14} />功率谱密度 · Welch 法</span><small>目标通道：{filterChanObj.name}（{filterOn ? `已滤波 ${filterType}` : '原始信号'}）</small></div><PsdChart values={filteredValues} color={filterChanObj.color} lo={filterChanObj.lo} hi={filterChanObj.hi} /><div className="spectrum-note"><BarChart3 size={13} /><span>主峰集中在低频段（短路过渡频率），异常区段在 2-5 kHz 存在次峰。</span></div></div>}
      {mode === 'STFT' && <div className="spectrum-view"><div className="spectrum-head"><span><Activity size={14} />短时傅里叶变换时频图</span><small>目标通道：{filterChanObj.name}</small></div><StftHeatmap values={filteredValues} color={filterChanObj.color} /><div className="spectrum-note"><Waves size={13} /><span>时频图可观察到 1.9-2.3s 和 3.6-3.9s 两个异常区段的高频能量抬升。</span></div></div>}
      {mode === 'DWT' && <div className="spectrum-view"><div className="spectrum-head"><span><Layers3 size={14} />离散小波分解（4 层 · db4）</span><small>目标通道：{filterChanObj.name}</small></div><DwtChart values={filteredValues} color={filterChanObj.color} /><div className="spectrum-note"><Gauge size={13} /><span>D1-D4 为细节系数、A4 为近似系数，异常在 D1-D2 高频层最明显。</span></div></div>}
      {mode === '小波分解' && <div className="spectrum-view"><div className="spectrum-head"><span><Waves size={14} />小波多层分量分解</span><small>目标通道：{filterChanObj.name} · 5 层</small></div><WaveletDecomp values={filteredValues} color={filterChanObj.color} /><div className="spectrum-note"><Layers3 size={13} /><span>L1-L5 由低到高展示不同尺度的小波分量，低层捕捉高频瞬变。</span></div></div>}
    </section>
    <aside className="explore-aside">
      <section className="panel explore-phase-panel">
        <div className="panel-heading"><div><h2>UI 相图</h2><p>电流–电压轨迹，颜色越亮越接近当前时刻</p></div><span className="explore-hint">悬停联动</span></div>
        <PhasePlot cursor={cursor} onCursor={setCursor} />
        <div className="phase-legend"><span><i className="legend-blue" />稳态轨迹</span><span><i className="legend-orange" />异常发散</span><span><i className="result-dot red" />游标 {fmt(cursor)}</span></div>
      </section>
      <section className="panel explore-pdd-panel">
        <div className="panel-heading"><div><h2>PDD 概率密度分布</h2><p>评估信号值的集中度与双峰特征</p></div><div className="pdd-chan-select">{channels.map((c) => <button key={c.id} className={pddChan === c.id ? 'active' : ''} onClick={() => setPddChan(c.id)}><i style={{ background: c.color }} />{c.name}</button>)}</div></div>
        <PddChart chanId={pddChan} />
        <div className="pdd-note"><BarChart3 size={13} /><span>当前通道分布近似单峰、集中度高；异常区段会使分布尾部抬升。</span></div>
      </section>
      <section className="panel explore-result-panel">
        <div className="panel-heading"><div><h2>分析结果</h2><p>AI 异常检测模型 v1.8</p></div><Sparkles size={16} className="accent-text" /></div>
        <div className="result-score"><strong>96.8%</strong><span>焊接稳定度</span></div>
        <div className="result-row"><span><i className="result-dot green" />正常区段</span><strong>92.4%</strong></div>
        <div className="result-row"><span><i className="result-dot orange" />电弧不稳</span><strong>5.1%</strong></div>
        <div className="result-row"><span><i className="result-dot red" />飞溅倾向</span><strong>2.5%</strong></div>
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

function Validation({ embedded = false }: { embedded?: boolean }) {
  const rules = ['图像文件完整性', '时序信号连续性', '采样频率一致性', '起收弧事件完整', '电流范围合理性', '电压范围合理性', '送丝速度缺失值', '多模态时间戳', '视频帧率稳定性', '文件命名规范', '焊缝ID唯一性', '工艺参数完整性', '音频信号质量', '红外数据完整性', '元数据关联关系'];
  return <div className="page-wrap"><PageIntro eyebrow="数据质量中心" title="数据核验" description="通过标准化规则检查数据完整性、连续性与多模态一致性。" action={<Toolbar action="执行核验" secondary="下载核验报告" />} /><div className="validation-summary"><div className="validation-score"><div className="score-ring small"><div><strong>93.3</strong><span>质量评分</span></div></div><div><h2>REG-20260815-00248</h2><p>最近核验：2026-08-15 09:45 · 核验耗时 2.8s</p><StatusPill>核验通过</StatusPill></div></div><div className="validation-count"><div><strong>14</strong><span>通过规则</span></div><div><strong className="warning-text">1</strong><span>警告</span></div><div><strong className="danger-text">0</strong><span>失败</span></div></div></div><section className="panel validation-panel"><div className="panel-heading"><div><h2>核验规则明细 <span className="inline-count">15 项</span></h2><p>已覆盖图像、时序、视频、元数据与跨模态一致性检查</p></div><button className="select-button">全部状态 <ChevronDown size={14} /></button></div><div className="rule-grid">{rules.map((rule, index) => <div className="validation-rule" key={rule}><div className={`validation-icon ${index === 8 ? 'warning' : ''}`}>{index === 8 ? <AlertTriangle size={15} /> : <CheckCircle2 size={15} />}</div><div><strong>{rule}</strong><span>{index === 8 ? '视频帧率存在轻微波动，建议复核' : '检查通过 · 结果已记录'}</span></div><StatusPill tone={index === 8 ? 'orange' : 'green'}>{index === 8 ? '警告' : '通过'}</StatusPill></div>)}</div></section></div>;
}

function Alignment({ embedded = false, splitOnly = false }: { embedded?: boolean; splitOnly?: boolean }) {
  const [cut, setCut] = useState(false);
  return <div className="page-wrap"><PageIntro eyebrow="多模态数据生产线" title="对齐与切分" description="自动识别起收弧事件，完成视频、波形和音频的时间同步与样本切分。" action={<Toolbar action="生成切分样本" secondary="导出标注集" />} /><div className="alignment-layout"><section className="panel alignment-board"><div className="board-toolbar"><div><span className="file-badge"><GitBranch size={15} />多模态对齐任务 · ALIGN-0248</span><h2>熔池视频 / 电流电压 / 音频</h2></div><StatusPill>已对齐</StatusPill></div><div className="video-placeholder"><div className="video-grid" /><div className="play-orb"><Play size={22} /></div><div className="video-label">熔池视频 · Frame 0248</div><span className="video-time">00:02.18 / 00:05.42</span></div><div className="timeline-stack"><Track label="视频帧" tone="blue" /><Track label="电流" tone="mint" /><Track label="电压" tone="orange" /><Track label="音频" tone="purple" /></div><div className="alignment-events"><span><i className="event-start" />起弧 <b>00:00.42</b></span><span><i className="event-active" />有效焊接段 <b>00:00.78 - 00:04.28</b></span><span><i className="event-end" />收弧 <b>00:04.86</b></span></div></section><aside className="alignment-aside"><section className="panel"><div className="panel-heading"><div><h2>切分规则</h2><p>配置样本生成策略</p></div><SlidersHorizontal size={17} /></div><label className="switch-row"><span>按固定频率切分</span><input type="checkbox" defaultChecked /></label><div className="select-field">10 帧 / 样本 <ChevronDown size={14} /></div><label className="switch-row"><span>保留事件点前后缓冲</span><input type="checkbox" defaultChecked /></label><div className="select-field">± 0.20 秒 <ChevronDown size={14} /></div><button className="full-button" onClick={() => setCut(true)}>{cut ? <><Check size={16} />已生成 248 个样本</> : <><ScissorsIcon />预览切分结果</>}</button></section><section className="panel"><div className="panel-heading"><div><h2>输出任务格式</h2><p>兼容主流视觉任务</p></div></div><div className="format-chips"><span className="chosen">目标检测</span><span>图像分类</span><span>语义分割</span><span>时序分类</span></div><div className="export-note"><FileText size={15} /><span>将生成图像、信号片段及 JSON 标注文件</span></div></section></aside></div></div>;
}

function Track({ label, tone }: { label: string; tone: string }) { return <div className="timeline-row"><span>{label}</span><div className={`timeline-track ${tone}`}><i /><b /></div><small>0s</small><small>5.42s</small></div>; }
function ScissorsIcon() { return <span className="scissors-icon">✂</span>; }

function ModelTest({ embedded = false }: { embedded?: boolean }) {
  return <div className="page-wrap"><PageIntro eyebrow="模型评估中心" title="模型测试" description="在独立测试集上验证异常检测、分割与质量预测模型的表现。" action={<Toolbar action="新建测试任务" secondary="导出测试报告" />} /><div className="model-test-layout"><section className="panel test-config"><div className="panel-heading"><div><h2>测试配置</h2><p>选择模型、数据集与评估任务</p></div><span className="draft-tag">待执行</span></div><div className="form-block"><label>模型类型</label><div className="model-select"><div className="model-logo"><Cpu size={16} /></div><div><strong>焊接异常检测模型 v1.8</strong><span>多源时序信号 · 异常分类</span></div><Check size={17} className="selected-check" /></div></div><div className="form-block"><label>独立测试集</label><div className="select-field"><Database size={16} />测试集 · 2026Q3 工艺扰动样本 <ChevronDown size={15} /></div></div><div className="form-block"><label>评估任务</label><div className="test-task-list"><button className="chosen"><Check size={14} />异常分类</button><button><span />质量预测</button><button><span />推理延迟</button></div></div><button className="full-button"><Play size={16} />开始测试</button></section><section className="panel test-result"><div className="panel-heading"><div><h2>测试结果</h2><p>最近测试任务 · TEST-20260815-03</p></div><StatusPill>已完成</StatusPill></div><div className="metric-row four"><div><span>准确率</span><strong>96.8%</strong></div><div><span>召回率</span><strong>94.2%</strong></div><div><span>F1 值</span><strong>95.5%</strong></div><div><span>推理时延</span><strong>18ms</strong></div></div><div className="confusion-matrix"><div className="matrix-title"><h3>混淆矩阵</h3><span>测试样本 1,248 条</span></div><div className="matrix"><div /><strong>预测正常</strong><strong>预测异常</strong><strong>实际正常</strong><b className="matrix-good">612</b><b className="matrix-warn">18</b><strong>实际异常</strong><b className="matrix-warn">22</b><b className="matrix-good">596</b></div></div><div className="test-result-note"><CheckCircle2 size={16} /><span>模型在当前工况下满足验收阈值，建议继续进行跨板材厚度验证。</span></div></section></div></div>;
}

function InfoRow({ label, value, accent }: { label: string; value: string; accent?: boolean }) { return <div className="info-row"><span>{label}</span><strong className={accent ? 'accent-text' : ''}>{value}</strong></div>; }

const tsFeatures = [
  { name: '均值', cur: '180.2', vol: '22.4', gas: '18.0', wir: '7.0' },
  { name: '方差', cur: '142.8', vol: '3.2', gas: '0.8', wir: '0.4' },
  { name: '峰值', cur: '246.1', vol: '28.3', gas: '21.2', wir: '8.6' },
  { name: '偏度', cur: '0.12', vol: '-0.08', gas: '0.31', wir: '0.05' },
  { name: '峰度', cur: '2.94', vol: '3.12', gas: '2.67', wir: '2.81' },
  { name: 'RMS', cur: '182.1', vol: '22.5', gas: '18.0', wir: '7.0' },
  { name: 'FFT 主频', cur: '39.2 Hz', vol: '37.8 Hz', gas: '12.4 Hz', wir: '11.1 Hz' },
  { name: '小波能量', cur: '8.42', vol: '1.86', gas: '0.72', wir: '0.38' },
];
const visionFeatures = [
  { name: '熔池面积', value: '1,284 px²', desc: '分割掩膜像素统计' },
  { name: '熔池周长', value: '186 px', desc: '边缘轮廓长度' },
  { name: '长宽比', value: '2.34', desc: '外接矩形长/宽' },
  { name: '圆形度', value: '0.72', desc: '4πA/P²' },
  { name: '灰度均值', value: '128.4', desc: '熔池区域平均灰度' },
  { name: '纹理对比度', value: '0.46', desc: 'GLCM 对比度' },
  { name: '纹理能量', value: '0.82', desc: 'GLCM 角二阶矩' },
  { name: '边缘梯度', value: '34.2', desc: 'Sobel 梯度均值' },
];
const audioFeatures = [
  { name: '频带能量 (0-1kHz)', value: '24.6 dB' },
  { name: '频带功率 (1-5kHz)', value: '18.3 dB' },
  { name: '总功率谱密度', value: '0.042' },
  { name: '质心频率', value: '2.14 kHz' },
  { name: '频谱滚降', value: '4.2 kHz' },
  { name: '过零率', value: '0.038' },
];
const unifiedVector = [
  { group: '时序·电流', dims: 8, range: '[0:8]', tone: '#2c9caf' },
  { group: '时序·电压', dims: 8, range: '[8:16]', tone: '#67cdb0' },
  { group: '时序·气体', dims: 6, range: '[16:22]', tone: '#f0a34a' },
  { group: '时序·送丝', dims: 6, range: '[22:28]', tone: '#75add1' },
  { group: '视觉·几何', dims: 4, range: '[28:32]', tone: '#b89ac4' },
  { group: '视觉·纹理', dims: 4, range: '[32:36]', tone: '#b89ac4' },
  { group: '声音·频带', dims: 6, range: '[36:42]', tone: '#d4a05a' },
];

function FeatureExtraction({ embedded = false }: { embedded?: boolean }) {
  const [normMethod, setNormMethod] = useState('Z-Score');
  const [exportFmt, setExportFmt] = useState('NPY');
  const totalDims = unifiedVector.reduce((s, v) => s + v.dims, 0);
  return <div className="page-wrap"><PageIntro eyebrow="多模态特征工程" title="特征提取" description="从时序、视觉、声音模态提取代表性特征，输出统一特征向量供融合层使用。" action={<Toolbar action="执行提取" secondary="导出特征集" />} />
    <div className="feature-layout">
      <section className="panel feature-modality-panel">
        <div className="panel-heading"><div><h2>时序信号特征</h2><p>电流 / 电压 / 气体流量 / 送丝速度 · 统计 + 频域 + 时频</p></div><Waves size={17} className="accent-text" /></div>
        <div className="feature-table-wrap">
          <div className="feature-table">
            <div className="ft-row ft-head"><span>特征</span><span style={{ color: '#2c9caf' }}>电流</span><span style={{ color: '#67cdb0' }}>电压</span><span style={{ color: '#f0a34a' }}>气体</span><span style={{ color: '#75add1' }}>送丝</span></div>
            {tsFeatures.map((f) => <div className="ft-row" key={f.name}><span>{f.name}</span><span className="mono">{f.cur}</span><span className="mono">{f.vol}</span><span className="mono">{f.gas}</span><span className="mono">{f.wir}</span></div>)}
          </div>
        </div>
        <div className="feature-tags"><span>统计特征</span><span>FFT 频域</span><span>小波时频</span><span>28 维 / 通道</span></div>
      </section>

      <section className="panel feature-modality-panel">
        <div className="panel-heading"><div><h2>熔池视觉特征</h2><p>熔池视觉模型提取几何与纹理特征</p></div><ImageIcon size={17} className="accent-text" /></div>
        <div className="vision-feature-grid">
          {visionFeatures.map((f) => <div className="vf-item" key={f.name}><div><strong>{f.name}</strong><small>{f.desc}</small></div><span className="mono">{f.value}</span></div>)}
        </div>
        <div className="feature-tags"><span>几何特征</span><span>GLCM 纹理</span><span>Sobel 边缘</span><span>8 维</span></div>
      </section>

      <section className="panel feature-modality-panel">
        <div className="panel-heading"><div><h2>声音 / 光谱特征</h2><p>频带能量、功率谱密度与声学统计</p></div><AudioWaveform size={17} className="accent-text" /></div>
        <div className="audio-feature-list">
          {audioFeatures.map((f) => <div className="af-item" key={f.name}><Sigma size={13} /><span>{f.name}</span><strong className="mono">{f.value}</strong></div>)}
        </div>
        <div className="feature-tags"><span>频带能量</span><span>PSD</span><span>声学统计</span><span>6 维</span></div>
      </section>

      <section className="panel feature-unified-panel">
        <div className="panel-heading"><div><h2>统一特征向量</h2><p>多模态特征拼接后输出，供后续融合层使用</p></div><Boxes size={17} className="accent-text" /></div>
        <div className="unified-summary"><div><span>总维度</span><strong>{totalDims} 维</strong></div><div><span>模态数</span><strong>3</strong></div><div><span>归一化</span><strong>{normMethod}</strong></div><div><span>输出格式</span><strong>.{exportFmt.toLowerCase()}</strong></div></div>
        <div className="unified-vector-bar">
          {unifiedVector.map((seg, i) => <div className="uv-seg" key={i} style={{ flexGrow: seg.dims, background: seg.tone }} title={`${seg.group} · ${seg.dims} 维`}><span>{seg.dims}</span></div>)}
        </div>
        <div className="unified-legend">{unifiedVector.map((seg, i) => <span key={i}><i style={{ background: seg.tone }} />{seg.group}<small>{seg.range}</small></span>)}</div>
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
function Training({ embedded = false }: { embedded?: boolean }) {
  const [isTraining, setIsTraining] = useState(false);
  return <div className="page-wrap"><PageIntro eyebrow="模型工坊" title="模型训练" description="配置训练任务，快速迭代你的工业视觉模型。" action={<button className={`primary-button ${isTraining ? 'training-button' : ''}`} onClick={() => setIsTraining(!isTraining)}>{isTraining ? <Activity size={16} /> : <Play size={16} />}{isTraining ? '训练进行中' : '开始新训练'}</button>} /><div className="training-layout"><section className="panel config-panel"><div className="panel-heading"><div><h2>训练配置</h2><p>从数据集到模型参数，一站式配置</p></div><span className="draft-tag">草稿</span></div><div className="form-block"><label>训练数据集</label><div className="select-field"><Database size={16} />主数据集 · 焊接缺陷检测 <ChevronDown size={15} /></div></div><div className="form-block"><label>选择基础模型</label><div className="model-select"><div className="model-logo">V</div><div><strong>VisionForge v2.1</strong><span>通用视觉检测模型 · 推荐</span></div><Check size={17} className="selected-check" /></div></div><div className="parameter-grid"><div className="form-block"><label>训练轮数 <CircleHelp size={13} /></label><div className="input-field">50 <span>epochs</span></div></div><div className="form-block"><label>批次大小 <CircleHelp size={13} /></label><div className="input-field">16 <span>batch</span></div></div><div className="form-block"><label>学习率</label><div className="input-field">0.001</div></div><div className="form-block"><label>验证集比例</label><div className="input-field">20%</div></div></div><div className="advanced-row"><SlidersHorizontal size={15} />高级参数<span>已配置 4 项</span><ChevronDown size={15} /></div><button className="full-button" onClick={() => setIsTraining(true)}>{isTraining ? <><Activity size={16} />训练任务运行中</> : <><Play size={16} />开始训练任务</>}</button></section><section className="panel training-chart-panel"><div className="panel-heading"><div><h2>训练表现</h2><p>{isTraining ? '任务 #TR-20260815-09 · 实时更新' : '最近一次训练任务 · #TR-20260814-07'}</p></div><span className={`run-status ${isTraining ? 'running' : ''}`}><i />{isTraining ? '运行中' : '已完成'}</span></div><div className="metric-row"><div><span>mAP@50</span><strong>{isTraining ? '—' : '94.6%'}</strong></div><div><span>精确率</span><strong>{isTraining ? '—' : '96.2%'}</strong></div><div><span>召回率</span><strong>{isTraining ? '—' : '92.8%'}</strong></div></div><div className="line-chart"><div className="chart-y"><span>1.0</span><span>0.8</span><span>0.6</span><span>0.4</span><span>0.2</span><span>0</span></div><svg viewBox="0 0 600 250" preserveAspectRatio="none" role="img" aria-label="训练指标曲线"><path d="M0 212 C55 190 68 174 112 164 S170 128 208 132 S260 103 300 97 S355 80 387 76 S438 63 474 50 S530 34 600 23" fill="none" stroke="#1d8fa5" strokeWidth="4" /><path d="M0 232 C60 220 72 210 125 194 S175 177 215 167 S270 150 312 143 S370 126 402 121 S450 111 492 92 S548 83 600 72" fill="none" stroke="#f0a34a" strokeWidth="3" strokeDasharray="7 7" /></svg><div className="chart-x"><span>0</span><span>10</span><span>20</span><span>30</span><span>40</span><span>50 epochs</span></div></div><div className="chart-key"><span><i className="legend-blue" />训练损失</span><span><i className="legend-orange" />验证损失</span></div></section></div><div className="training-note"><Terminal size={17} /><div><strong>训练日志</strong><p>{isTraining ? '正在准备数据增强策略... 预计 18 分钟后完成。' : '任务已完成，模型已自动保存至模型仓库。'}</p></div><button className="ghost-button">查看完整日志 <ArrowUpRight size={14} /></button></div></div>;
}
export default App;
