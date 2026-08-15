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

type Workspace = 'overview' | 'data-center' | 'analysis' | 'model-center';
const navItems: { id: Workspace; label: string; icon: typeof BarChart3 }[] = [
  { id: 'overview', label: '数据总览', icon: BarChart3 },
  { id: 'data-center', label: '数据中心', icon: Database },
  { id: 'analysis', label: '分析与标注', icon: Waves },
  { id: 'model-center', label: '模型中心', icon: TrainFront },
];
const projects = [
  { name: '焊接缺陷检测 · 主数据集', count: '1,209', status: '已完成', tone: 'green' },
  { name: '表面质量巡检数据', count: '842', status: '标注中', tone: 'blue' },
  { name: '红外热成像样本', count: '367', status: '待处理', tone: 'orange' },
];
const bars = [46, 58, 52, 67, 61, 78, 74, 92, 81, 88, 72, 96];

function App() {
  const [workspace, setWorkspace] = useState<Workspace>('overview');
  const [selectedDataId, setSelectedDataId] = useState<string | null>(null);
  const [activeProject, setActiveProject] = useState(0);
  const [query, setQuery] = useState('');
  const [isTraining, setIsTraining] = useState(false);
  const [saved, setSaved] = useState(false);
  const [selectedLabels, setSelectedLabels] = useState(['焊瘤', '气孔']);
  const filteredProjects = useMemo(() => projects.filter((project) => project.name.includes(query)), [query]);
  const toggleLabel = (label: string) => setSelectedLabels((current) => current.includes(label) ? current.filter((item) => item !== label) : [...current, label]);

  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand-mark"><Sparkles size={18} strokeWidth={2.5} /></div><div className="brand-copy"><strong>ForgeLab</strong><span>工业智能实验室</span></div>
      <div className="workspace-label">工作空间</div><nav className="main-nav">{navItems.map((item) => { const Icon = item.icon; return <button key={item.id} className={`nav-item ${workspace === item.id ? 'active' : ''}`} onClick={() => setWorkspace(item.id)}><Icon size={18} /><span>{item.label}</span>{workspace === item.id && <span className="nav-pip" />}</button>; })}</nav>
      <div className="sidebar-bottom"><button className="nav-item"><Settings2 size={18} /><span>系统设置</span></button><div className="user-card"><div className="avatar">林</div><div><strong>林工</strong><span>管理员</span></div><MoreHorizontal size={16} /></div></div>
    </aside>
    <main className="main-content">
      {workspace === 'overview' && <Overview activeProject={activeProject} filteredProjects={filteredProjects} setWorkspace={setWorkspace} />}
      {workspace === 'data-center' && <DataCenter setWorkspace={setWorkspace} selectedDataId={selectedDataId} setSelectedDataId={setSelectedDataId} />}
      {workspace === 'analysis' && <AnalysisWorkspace selectedDataId={selectedDataId} setSelectedDataId={setSelectedDataId} />}
      {workspace === 'model-center' && <ModelCenter />}
    </main>
  </div>;
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

function Overview({ activeProject, filteredProjects, setWorkspace }: { activeProject: number; filteredProjects: typeof projects; setWorkspace: (workspace: Workspace) => void }) {
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

    <div className="section-title"><div><h2>数据项目</h2><p>共 {filteredProjects.length} 个项目正在协作</p></div><button className="ghost-button"><Filter size={15} />筛选</button></div><div className="dataset-grid">{filteredProjects.map((project, index) => <div className={`dataset-card ${index === activeProject ? 'current' : ''}`} key={project.name}><div className="dataset-top"><div className={`dataset-icon ${project.tone}`}><Box size={18} /></div><span className={`status ${project.tone}`}>{project.status}</span><MoreHorizontal size={17} className="muted-icon" /></div><h3>{project.name}</h3><p>最近更新于今天 09:42 · 多模态数据</p><div className="progress-meta"><span>标注进度</span><strong>{index === 0 ? '100%' : index === 1 ? '68%' : '24%'}</strong></div><div className="progress"><span style={{ width: `${index === 0 ? 100 : index === 1 ? 68 : 24}%` }} /></div><div className="dataset-footer"><span><Layers3 size={14} />{project.count} 条样本</span><button onClick={() => setWorkspace('analysis')}>查看详情 <ArrowUpRight size={14} /></button></div></div>)}</div>
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

function Annotation({ saved, setSaved, selectedLabels, toggleLabel, embedded = false }: { saved: boolean; setSaved: (saved: boolean) => void; selectedLabels: string[]; toggleLabel: (label: string) => void; embedded?: boolean }) {
  return <div className={embedded ? 'embedded-page' : 'page-wrap'}><PageIntro eyebrow="数据生产线" title="数据标注" description="为模型准备高质量训练样本，支持多模态协同标注。" action={<><button className="outline-button"><Upload size={16} />导入数据</button><button className="primary-button" onClick={() => setSaved(true)}>{saved ? <Check size={16} /> : <Plus size={16} />}{saved ? '已保存' : '保存标注'}</button></>} /><div className="annotation-layout"><section className="panel annotation-board"><div className="board-toolbar"><div><span className="file-badge"><Archive size={15} />样本 0248 / 1209</span><h2>焊接件 · 视觉质检样本</h2></div><div className="toolbar-actions"><button className="icon-button"><SlidersHorizontal size={17} /></button><button className="select-button">图像标注 <ChevronDown size={14} /></button></div></div><div className="image-stage"><img src={labelImage} alt="待标注焊接样本" /><div className="annotation-box box-one"><span>焊瘤 <b>0.94</b></span></div><div className="annotation-box box-two"><span>气孔 <b>0.88</b></span></div><div className="stage-tip"><Sparkles size={14} />AI 已预标注 2 个区域</div></div><div className="board-footer"><div className="thumb-strip"><img src={detailImage} alt="样本缩略图" /><img className="thumb-active" src={labelImage} alt="当前样本缩略图" /><img src={modelImage} alt="样本缩略图" /><span>+ 9</span></div><div className="pagination"><button>‹</button><span>1 / 12</span><button>›</button></div></div></section><aside className="annotation-side"><section className="panel label-panel"><div className="panel-heading"><div><h2>标签类别</h2><p>选择需要应用的缺陷标签</p></div><button className="more-button"><MoreHorizontal size={18} /></button></div><div className="label-options">{['焊瘤', '气孔', '未熔合', '咬边', '正常'].map((label, index) => <button className={`label-chip ${selectedLabels.includes(label) ? 'chosen' : ''}`} onClick={() => toggleLabel(label)} key={label}><i className={`chip-dot chip-${index}`} />{label}<span>{selectedLabels.includes(label) ? <Check size={14} /> : '+'}</span></button>)}</div></section><section className="panel annotation-info"><div className="panel-heading"><div><h2>标注信息</h2><p>当前样本的详细信息</p></div></div><InfoRow label="数据来源" value="产线相机 · 03 号" /><InfoRow label="采集时间" value="2026-08-14 18:32" /><InfoRow label="标注人员" value="林工（我）" /><InfoRow label="置信度" value="94.2%" accent /></section><div className="ai-card"><div className="ai-card-icon"><Zap size={17} /></div><div><strong>智能标注建议</strong><p>已为你识别 2 个疑似缺陷区域，建议确认后提交。</p></div></div></aside></div></div>;
}
type DataCenterTab = 'list' | 'registration' | 'validation' | 'versions';
type AnalysisTab = 'select' | 'alignment' | 'analysis' | 'split' | 'annotation';
type ModelCenterTab = 'repository' | 'training' | 'testing' | 'inference';

function WorkspaceTabs<T extends string>({ items, active, onChange }: { items: { id: T; label: string; disabled?: boolean }[]; active: T; onChange: (id: T) => void }) {
  return <div className="workspace-tabs">{items.map((item) => <button className={active === item.id ? 'active' : ''} disabled={item.disabled} onClick={() => onChange(item.id)} key={item.id}>{item.label}</button>)}</div>;
}

function SelectionContext({ dataId }: { dataId: string }) {
  const row = weldRows.find((item) => item.id === dataId) ?? weldRows[0];
  return <div className="selection-context"><div><span>当前选中数据</span><strong>{row.id}</strong></div><div><span>数据来源</span><strong>{row.source}</strong></div><div><span>焊机</span><strong>{row.machine}</strong></div><div><span>当前版本</span><strong>{row.version}</strong></div><StatusPill tone={row.quality === '异常' ? 'red' : row.quality === '待复核' ? 'orange' : 'green'}>{row.quality}</StatusPill></div>;
}

function SelectionRequired({ onBack }: { onBack: () => void }) {
  return <div className="selection-required"><div className="selection-icon"><Database size={23} /></div><h2>请先选择一条数据</h2><p>该功能需要基于具体焊缝数据执行，请返回数据列表选择后继续。</p><button className="outline-button" onClick={onBack}><ChevronLeft size={14} />返回数据列表</button></div>;
}

function DataCenter({ setWorkspace, selectedDataId, setSelectedDataId }: { setWorkspace: (workspace: Workspace) => void; selectedDataId: string | null; setSelectedDataId: (id: string) => void }) {
  const [tab, setTab] = useState<DataCenterTab>('list');
  const items = [{ id: 'list' as const, label: '数据列表' }, { id: 'registration' as const, label: '数据登记', disabled: !selectedDataId }, { id: 'validation' as const, label: '数据核验', disabled: !selectedDataId }, { id: 'versions' as const, label: '数据版本', disabled: !selectedDataId }];
  const content = tab === 'list' ? <ManagementFiltered setWorkspace={setWorkspace} selectedDataId={selectedDataId} setSelectedDataId={setSelectedDataId} /> : selectedDataId ? <>{tab === 'registration' && <Registration embedded />}{tab === 'validation' && <Validation embedded />}{tab === 'versions' && <VersionPanel />}</> : <SelectionRequired onBack={() => setTab('list')} />;
  return <div className="workspace-page"><div className="workspace-page-head"><div><div className="eyebrow"><span />数据资产中心</div><h1>数据中心</h1><p>以单条焊缝数据为单位，管理登记信息、质量核验和版本链路。</p></div><Toolbar action="上传数据" /></div><WorkspaceTabs items={items} active={tab} onChange={setTab} />{selectedDataId && <SelectionContext dataId={selectedDataId} />}{content}</div>;
}

function AnalysisWorkspace({ selectedDataId, setSelectedDataId }: { selectedDataId: string | null; setSelectedDataId: (id: string) => void }) {
  const [tab, setTab] = useState<AnalysisTab>('select');
  const [saved, setSaved] = useState(false);
  const [selectedLabels, setSelectedLabels] = useState(['焊瘤', '气孔']);
  const toggleLabel = (label: string) => setSelectedLabels((current) => current.includes(label) ? current.filter((item) => item !== label) : [...current, label]);
  const items = [{ id: 'select' as const, label: '选择数据' }, { id: 'alignment' as const, label: '多模态对齐', disabled: !selectedDataId }, { id: 'analysis' as const, label: '信号分析', disabled: !selectedDataId }, { id: 'split' as const, label: '数据切分', disabled: !selectedDataId }, { id: 'annotation' as const, label: '数据标注', disabled: !selectedDataId }];
  return <div className="workspace-page"><div className="workspace-page-head"><div><div className="eyebrow"><span />多模态数据生产线</div><h1>分析与标注</h1><p>选择一条焊缝后，完成对齐、信号分析、切分与标注。</p></div><Toolbar action={tab === 'annotation' ? '保存标注' : '开始处理'} secondary="导出结果" /></div><WorkspaceTabs items={items} active={tab} onChange={setTab} />{selectedDataId && <SelectionContext dataId={selectedDataId} />}{tab === 'select' && <AnalysisSelect onContinue={(id) => { setSelectedDataId(id); setTab('alignment'); }} />}{!selectedDataId && tab !== 'select' && <SelectionRequired onBack={() => setTab('select')} />}{selectedDataId && tab === 'alignment' && <Alignment embedded />}{selectedDataId && tab === 'analysis' && <WeldAnalysis embedded />}{selectedDataId && tab === 'split' && <Alignment embedded splitOnly />}{selectedDataId && tab === 'annotation' && <Annotation saved={saved} setSaved={setSaved} selectedLabels={selectedLabels} toggleLabel={toggleLabel} embedded />}</div>;
}

function ModelCenter() {
  const [tab, setTab] = useState<ModelCenterTab>('repository');
  const [isTraining, setIsTraining] = useState(false);
  const items = [{ id: 'repository' as const, label: '模型仓库' }, { id: 'training' as const, label: '新建训练' }, { id: 'testing' as const, label: '测试评估' }, { id: 'inference' as const, label: '推理验证' }];
  return <div className="workspace-page"><div className="workspace-page-head"><div><div className="eyebrow"><span />模型研发中心</div><h1>模型中心</h1><p>统一管理模型版本、训练任务、测试评估与推理验证。</p></div><Toolbar action={tab === 'training' ? '开始训练' : '新建模型'} secondary="导出报告" /></div><WorkspaceTabs items={items} active={tab} onChange={setTab} />{tab === 'repository' && <ModelRepository />}{tab === 'training' && <Training isTraining={isTraining} setIsTraining={setIsTraining} embedded />}{tab === 'testing' && <ModelTest embedded />}{tab === 'inference' && <InferencePanel />}</div>;
}

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

function Management({ setWorkspace, selectedDataId, setSelectedDataId, embedded = false }: { setWorkspace: (workspace: Workspace) => void; selectedDataId: string | null; setSelectedDataId: (id: string) => void; embedded?: boolean }) {
  const [selected, setSelected] = useState<string[]>([]);
  const [query, setQuery] = useState('');
  const [source, setSource] = useState('全部来源');
  const [brand, setBrand] = useState('全部品牌');
  const toggle = (id: string) => setSelected((items) => items.includes(id) ? items.filter((item) => item !== id) : [...items, id]);
  const filteredRows = useMemo(() => weldRows.filter((row) => {
    const normalizedQuery = query.trim().toLowerCase();
    const matchesQuery = !normalizedQuery || `${row.id} ${row.source} ${row.machine}`.toLowerCase().includes(normalizedQuery);
    const matchesSource = source === '全部来源' || row.source.includes(source);
    const matchesBrand = brand === '全部品牌' || row.machine.startsWith(brand);
    return matchesQuery && matchesSource && matchesBrand;
  }), [query, source, brand]);
  return <div className={embedded ? 'embedded-page' : 'page-wrap'}><PageIntro eyebrow="数据资产中心" title="数据管理" description="统一管理焊缝原始数据、处理版本与标注资产，保持每一条数据可追溯。" action={<Toolbar action="上传数据" />} />
    <div className="stat-grid compact-stats"><StatCard icon={Database} label="登记数据" value="12,847" sub="较上月 +8.4%" /><StatCard icon={CheckCircle2} label="质量通过" value="11,362" sub="通过率 88.4%" /><StatCard icon={GitBranch} label="数据版本" value="38,219" sub="原始与加工数据" /><StatCard icon={AlertTriangle} label="待处理异常" value="126" sub="需要人工复核" /></div>
    <section className="panel table-panel"><div className="table-toolbar"><div className="filter-tabs"><button className="active">全部数据 <b>12,847</b></button><button>待核验 <b>126</b></button><button>已归档 <b>8,204</b></button></div><div className="table-actions"><div className="inline-search"><Search size={14} /><input placeholder="搜索焊缝ID、设备、来源" /></div><button className="select-button">更多筛选 <ChevronDown size={14} /></button></div></div><div className="selection-bar">已选 {selected.length} 条<span>支持批量导出、归档与删除</span><button className="ghost-button">批量操作 <ChevronDown size={14} /></button></div><div className="data-table"><div className="table-row table-head"><span><input type="checkbox" aria-label="全选" /></span><span>焊缝 / 登记编号</span><span>采集时间</span><span>数据来源</span><span>焊机型号</span><span>数据模态</span><span>核验状态</span><span>版本</span><span>操作</span></div>{weldRows.map((row) => <div className="table-row" key={row.id}><span><input type="checkbox" checked={selected.includes(row.id)} onChange={() => toggle(row.id)} aria-label={`选择 ${row.id}`} /></span><span className="id-cell"><strong>{row.id}</strong><small>登记台账 · 自动生成</small></span><span>{row.time}</span><span>{row.source}</span><span>{row.machine}</span><span>{row.types}</span><span><StatusPill tone={row.quality === '异常' ? 'red' : row.quality === '待复核' ? 'orange' : 'green'}>{row.quality}</StatusPill></span><span className="mono">{row.version}</span><span><button className="table-icon" onClick={() => setWorkspace('analysis')} aria-label="查看详情"><Eye size={15} /></button><button className="table-icon" aria-label="更多操作"><MoreHorizontal size={15} /></button></span></div>)}</div><div className="table-footer"><span>显示 1-4 条，共 12,847 条数据</span><div className="pagination"><button><ChevronLeft size={14} /></button><span>1 / 3212</span><button><ChevronRight size={14} /></button></div></div></section>
  </div>;
}

function ManagementFiltered({ setWorkspace, selectedDataId, setSelectedDataId }: { setWorkspace: (workspace: Workspace) => void; selectedDataId: string | null; setSelectedDataId: (id: string) => void }) {
  const [query, setQuery] = useState('');
  const [source, setSource] = useState('全部来源');
  const [brand, setBrand] = useState('全部品牌');
  const filteredRows = useMemo(() => weldRows.filter((row) => {
    const search = query.trim().toLowerCase();
    return (!search || `${row.id} ${row.source} ${row.machine}`.toLowerCase().includes(search)) && (source === '全部来源' || row.source.includes(source)) && (brand === '全部品牌' || row.machine.startsWith(brand));
  }), [query, source, brand]);
  return <section className="panel table-panel"><div className="data-filter-strip"><label className="filter-field keyword">关键词<div className="inline-search"><Search size={14} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="焊缝ID、登记编号" /></div></label><label className="filter-field">数据来源<select value={source} onChange={(event) => setSource(event.target.value)}><option>全部来源</option><option>产线相机</option><option>实训线</option></select></label><label className="filter-field">焊机品牌<select value={brand} onChange={(event) => setBrand(event.target.value)}><option>全部品牌</option><option>Fronius</option><option>OTC</option><option>Kemppi</option><option>Panasonic</option></select></label><button className="outline-button filter-reset" onClick={() => { setQuery(''); setSource('全部来源'); setBrand('全部品牌'); }}><RefreshCw size={13} />重置</button></div><div className="latest-version-note"><GitBranch size={14} />列表按焊缝 ID 去重，仅显示每条数据的最新版本</div><div className="table-toolbar"><div className="filter-tabs"><button className="active">全部最新数据 <b>{filteredRows.length}</b></button><button>待核验 <b>126</b></button><button>已归档 <b>8,204</b></button></div><div className="table-actions"><button className="select-button" onClick={() => { setQuery(''); setSource('全部来源'); setBrand('全部品牌'); }}><RefreshCw size={14} />重置筛选</button></div></div><div className="selection-bar">{selectedDataId ? <>当前选中：<strong>{selectedDataId}</strong><span>登记、核验、版本和分析操作将基于此数据</span></> : <>尚未选择数据<span>点击任意数据行即可选择</span></>}<button className="ghost-button" onClick={() => selectedDataId && setWorkspace('analysis')}>进入分析与标注 <ArrowUpRight size={14} /></button></div><div className="data-table"><div className="table-row table-head"><span>状态</span><span>焊缝 / 登记编号</span><span>采集时间</span><span>数据来源</span><span>焊机品牌 / 型号</span><span>数据模态</span><span>核验状态</span><span>最新版本</span><span>操作</span></div>{filteredRows.map((row) => <div className={`table-row ${selectedDataId === row.id ? 'selected-row' : ''}`} onClick={() => setSelectedDataId(row.id)} key={row.id}><span><input type="radio" checked={selectedDataId === row.id} onChange={() => setSelectedDataId(row.id)} aria-label={`选择 ${row.id}`} /></span><span className="id-cell"><strong>{row.id}</strong><small>登记台账 · 最新版本</small></span><span>{row.time}</span><span>{row.source}</span><span>{row.machine}</span><span>{row.types}</span><span><StatusPill tone={row.quality === '异常' ? 'red' : row.quality === '待复核' ? 'orange' : 'green'}>{row.quality}</StatusPill></span><span className="mono">{row.version}</span><span><button className="table-icon" onClick={(event) => { event.stopPropagation(); setSelectedDataId(row.id); setWorkspace('analysis'); }} aria-label="进入分析"><Eye size={15} /></button></span></div>)}</div><div className="table-footer"><span>显示 {filteredRows.length} 条最新数据，共 12,847 条数据</span><div className="pagination"><button><ChevronLeft size={14} /></button><span>1 / 3212</span><button><ChevronRight size={14} /></button></div></div></section>;
}

function Registration({ embedded = false }: { embedded?: boolean }) {
  const [registered, setRegistered] = useState(false);
  return <div className="page-wrap"><PageIntro eyebrow="标准化台账" title="数据登记" description="为每批焊接多模态数据建立统一身份、来源和工艺参数档案。" action={<span className="workflow-chip"><CheckCircle2 size={14} />登记即进入数据流程</span>} /><div className="registration-layout"><section className="panel form-panel"><div className="panel-heading"><div><h2>新建数据登记</h2><p>带 * 的字段为必填项</p></div><span className="draft-tag">登记草稿</span></div><div className="form-section-title"><span>基础信息</span><i /></div><div className="form-grid"><label>数据来源 *<input placeholder="例如：产线相机 · 03号" /></label><label>采集时间 *<input value="2026-08-15 09:42" readOnly /></label><label>焊缝 / 批次名称 *<input placeholder="输入焊缝或批次名称" /></label><label>关联产品信息<input placeholder="产品型号、零件编号" /></label></div><div className="form-section-title"><span>采集与工艺参数</span><i /></div><div className="form-grid"><label>焊机型号<select defaultValue="Fronius CMT"><option>Fronius CMT</option><option>OTC FD-V8</option><option>Panasonic YD-500</option></select></label><label>焊接方法<select defaultValue="MAG焊"><option>MAG焊</option><option>MIG焊</option><option>TIG焊</option></select></label><label>板材材质<input placeholder="例如：Q235B" /></label><label>板材厚度<input placeholder="例如：6 mm" /></label><label>电流 / 电压<input placeholder="180 A / 22 V" /></label><label>采样频率<input placeholder="10 kHz" /></label></div><div className="upload-zone"><Upload size={20} /><strong>拖入或选择原始数据文件</strong><span>支持视频、CSV、WAV、JSON、图片 · 单文件不超过 2 GB</span><button className="outline-button">选择文件</button></div><button className="full-button" onClick={() => setRegistered(true)}>{registered ? <><CheckCircle2 size={16} />登记已生成：REG-20260815-00249</> : <><FileCheck2 size={16} />生成登记编号</>}</button></section><aside className="registration-aside"><section className="panel"><div className="panel-heading"><div><h2>登记规则</h2><p>平台数据使用约束</p></div><ClipboardCheck size={18} className="accent-text" /></div>{['自动生成唯一登记编号', '原始文件与后续版本自动关联', '登记后触发入库前数据核验', '所有操作写入审计日志'].map((item) => <div className="rule-row" key={item}><CheckCircle2 size={15} />{item}</div>)}</section><section className="panel"><div className="panel-heading"><div><h2>最近登记</h2><p>最近 24 小时新增数据</p></div></div>{weldRows.slice(0, 3).map((row) => <div className="recent-row" key={row.id}><span className="recent-dot" /><div><strong>{row.id}</strong><small>{row.source} · {row.time.slice(11)}</small></div><StatusPill>已登记</StatusPill></div>)}</section></aside></div></div>;
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

function Training({ isTraining, setIsTraining, embedded = false }: { isTraining: boolean; setIsTraining: (isTraining: boolean) => void; embedded?: boolean }) {
  return <div className="page-wrap"><PageIntro eyebrow="模型工坊" title="模型训练" description="配置训练任务，快速迭代你的工业视觉模型。" action={<button className={`primary-button ${isTraining ? 'training-button' : ''}`} onClick={() => setIsTraining(!isTraining)}>{isTraining ? <Activity size={16} /> : <Play size={16} />}{isTraining ? '训练进行中' : '开始新训练'}</button>} /><div className="training-layout"><section className="panel config-panel"><div className="panel-heading"><div><h2>训练配置</h2><p>从数据集到模型参数，一站式配置</p></div><span className="draft-tag">草稿</span></div><div className="form-block"><label>训练数据集</label><div className="select-field"><Database size={16} />主数据集 · 焊接缺陷检测 <ChevronDown size={15} /></div></div><div className="form-block"><label>选择基础模型</label><div className="model-select"><div className="model-logo">V</div><div><strong>VisionForge v2.1</strong><span>通用视觉检测模型 · 推荐</span></div><Check size={17} className="selected-check" /></div></div><div className="parameter-grid"><div className="form-block"><label>训练轮数 <CircleHelp size={13} /></label><div className="input-field">50 <span>epochs</span></div></div><div className="form-block"><label>批次大小 <CircleHelp size={13} /></label><div className="input-field">16 <span>batch</span></div></div><div className="form-block"><label>学习率</label><div className="input-field">0.001</div></div><div className="form-block"><label>验证集比例</label><div className="input-field">20%</div></div></div><div className="advanced-row"><SlidersHorizontal size={15} />高级参数<span>已配置 4 项</span><ChevronDown size={15} /></div><button className="full-button" onClick={() => setIsTraining(true)}>{isTraining ? <><Activity size={16} />训练任务运行中</> : <><Play size={16} />开始训练任务</>}</button></section><section className="panel training-chart-panel"><div className="panel-heading"><div><h2>训练表现</h2><p>{isTraining ? '任务 #TR-20260815-09 · 实时更新' : '最近一次训练任务 · #TR-20260814-07'}</p></div><span className={`run-status ${isTraining ? 'running' : ''}`}><i />{isTraining ? '运行中' : '已完成'}</span></div><div className="metric-row"><div><span>mAP@50</span><strong>{isTraining ? '—' : '94.6%'}</strong></div><div><span>精确率</span><strong>{isTraining ? '—' : '96.2%'}</strong></div><div><span>召回率</span><strong>{isTraining ? '—' : '92.8%'}</strong></div></div><div className="line-chart"><div className="chart-y"><span>1.0</span><span>0.8</span><span>0.6</span><span>0.4</span><span>0.2</span><span>0</span></div><svg viewBox="0 0 600 250" preserveAspectRatio="none" role="img" aria-label="训练指标曲线"><path d="M0 212 C55 190 68 174 112 164 S170 128 208 132 S260 103 300 97 S355 80 387 76 S438 63 474 50 S530 34 600 23" fill="none" stroke="#1d8fa5" strokeWidth="4" /><path d="M0 232 C60 220 72 210 125 194 S175 177 215 167 S270 150 312 143 S370 126 402 121 S450 111 492 92 S548 83 600 72" fill="none" stroke="#f0a34a" strokeWidth="3" strokeDasharray="7 7" /></svg><div className="chart-x"><span>0</span><span>10</span><span>20</span><span>30</span><span>40</span><span>50 epochs</span></div></div><div className="chart-key"><span><i className="legend-blue" />训练损失</span><span><i className="legend-orange" />验证损失</span></div></section></div><div className="training-note"><Terminal size={17} /><div><strong>训练日志</strong><p>{isTraining ? '正在准备数据增强策略... 预计 18 分钟后完成。' : '任务已完成，模型已自动保存至模型仓库。'}</p></div><button className="ghost-button">查看完整日志 <ArrowUpRight size={14} /></button></div></div>;
}
export default App;
