import { useEffect, useState } from 'react';
import {
  Activity, ArrowUpRight, BarChart3, Box, Database, Factory, FileCheck2,
  Filter, Gauge, Layers3, MoreHorizontal, WandSparkles, Waves, Boxes,
} from 'lucide-react';
import { getDashboardData } from '../../api/dashboard';
import type { DashboardData } from '../../api/dashboard';
import type { Project } from '../../api/types';
import type { Route } from '../../app/navigation';
import { PageIntro } from '../../shared/components/PageIntro';

const fmtDT = (iso: string | null | undefined): string =>
  iso ? iso.replace('T', ' ').slice(0, 16) : '—';

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

export function OverviewPage({ navigate }: { navigate: (route: Route) => void }) {
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
