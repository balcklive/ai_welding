import { useEffect, useMemo, useRef, useState } from 'react';
import {
  ArrowUpRight, BarChart3, Box, Check, CheckCircle2,
  ChevronLeft, ClipboardCheck, Database, GitBranch, Image as ImageIcon,
  Plus, RefreshCw, Search, Tag, TrainFront, Waves, AlertTriangle,
} from 'lucide-react';
import {
  createDataset, deleteDataset, getDataset, getDatasetVersion, getDimensions,
  getLineage, getReadiness, listDatasetVersions, listDatasetVersionItems,
  listDatasets,
} from '../../api/datasets';
import { deleteWeld, getWeld, listWelds } from '../../api/welds';
import { getSignals } from '../../api/analysis';
import { getFileUrl } from '../../api/files';
import type {
  DataRecord, Dataset, DatasetItemRow, DatasetVersion,
  DimensionStatus, LineageNode, ReadinessCheck,
} from '../../api/types';
import type { Route } from '../../app/navigation';
import {
  CH, CW, AXIS_L, PLOT_W, PLOT_H, dur, clamp, toChan, toPath, fmt,
} from '../analysis/signals/chartData';
import type { Chan } from '../analysis/signals/chartData';
import { InfoRow } from '../../shared/components/InfoRow';
import { StatusPill } from '../../shared/components/StatusPill';
import { TextDialog } from '../../shared/components/TextDialog';
import { formatDateTime } from '../../shared/lib/formatting';
import { VersionDetailDrawer } from '../versions/VersionDetailDrawer';

const PAGE_SIZE = 10;

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

export function DatasetWorkspace({ navigate, selectedDatasetId, datasetHomeKey, onDetailChange, setSelectedDataId, setSelectedDatasetId }: { navigate: (route: Route) => void; selectedDatasetId: number | null; datasetHomeKey: number; onDetailChange?: (isDetail: boolean) => void; setSelectedDataId: (id: string | null) => void; setSelectedDatasetId: (id: number | null) => void }) {
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
  return <div className="dataset-workspace">{view === 'list' && <><div className="dataset-list-heading"><div><div className="dataset-breadcrumb">数据管理 / 数据集列表</div><h2>数据集列表</h2><p>管理和浏览平台中的全部数据集，查看快照、成员数据与训练状态。</p></div><button className="primary-button" onClick={() => setCreateDialog(true)}><Plus size={15} />新建数据集</button></div><div className="dataset-rule"><GitBranch size={14} /><span>数据集以固定快照保存；焊缝版本记录单条数据的处理历史。</span><span className="dataset-rule-count">可训练 {rows.filter((item) => item.status === '可训练').length} 个</span></div>{listLoading ? <p className="dataset-empty-state" role="status">数据集列表加载中…</p> : <div className="dataset-table">{rows.map((item) => <button className="dataset-list-row" onClick={() => selectDataset(item)} key={item.id}><span className="dataset-row-icon"><Box size={17} /></span><span className="dataset-row-main"><strong>{item.name}</strong><small>{item.id} · {item.task}</small></span><span><small>样本数</small><strong className="mono">{item.samples}</strong></span><span><small>标注完成度</small><strong className="mono">{item.progress}</strong></span><span><small>当前快照</small><strong className="mono">{item.version ? `快照 ${item.version}` : '未生成'}</strong></span><StatusPill tone={item.tone}>{item.status}</StatusPill><ArrowUpRight size={15} className="muted-icon" /></button>)}</div>}{createDialog && <TextDialog title="新建数据集" label="数据集名称" initialValue="新建数据集" onCancel={() => setCreateDialog(false)} onConfirm={handleCreate} />}</>}{view === 'overview' && dataset && <DatasetDetail dataset={dataset} versionId={selectedVersionId} onShowRecords={() => setView('records')} onShowAllRecords={() => setView('dataset-records')} onVersionChange={selectVersion} />}{view === 'dataset-records' && dataset && <DatasetSourceRecords dataset={dataset} onBack={() => setView('overview')} onSelectRecord={(record) => { setRecordBackView('dataset-records'); setSelectedRecordId(record.weld_id); setSelectedDataId(record.weld_id); setSelectedVersionId(record.latest_version_id ?? selectedVersionId); setSelectedRecordSplit(null); setView('record-detail'); }} />}{view === 'records' && dataset && selectedVersionId != null && <DatasetRecords dataset={dataset} versionId={selectedVersionId} onBack={() => setView('overview')} onVersionChange={(versionId) => { selectVersion(versionId); setView('records'); }} onSelectRecord={(row) => { if (!row.weld_id) return; setRecordBackView('records'); setSelectedRecordId(row.weld_id); setSelectedRecordSplit(row.split); setSelectedDataId(row.weld_id); setView('record-detail'); }} />}{view === 'record-detail' && dataset && selectedVersionId != null && selectedRecordId && <DatasetRecordDetail weldId={selectedRecordId} dataset={dataset} versionId={selectedVersionId} split={selectedRecordSplit} onBack={() => setView(recordBackView)} setSelectedDataId={setSelectedDataId} navigate={navigate} />}</div>;
}

function DatasetDetail(props: { dataset: DatasetRow; versionId: number | null; onShowRecords: () => void; onShowAllRecords: () => void; onVersionChange: (versionId: number) => void }) {
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const handleDelete = () => {
    if (!window.confirm(`确定删除数据集“${props.dataset.name}”吗？该操作不可撤销。`)) return;
    setDeleting(true);
    deleteDataset(String(props.dataset.numericId ?? props.dataset.id))
      .then(() => window.location.reload())
      .catch((err) => setError(err instanceof Error ? err.message : '删除数据集失败'))
      .finally(() => setDeleting(false));
  };
  return <><DatasetDetailContent {...props} /><div className="dataset-delete-bar">{error && <span role="alert">{error}</span>}<button className="danger-button" onClick={handleDelete} disabled={deleting}>{deleting ? '删除中…' : '删除数据集'}</button></div></>;
}

function DatasetDetailContent({ dataset, versionId, onShowRecords, onShowAllRecords, onVersionChange }: { dataset: DatasetRow; versionId: number | null; onShowRecords: () => void; onShowAllRecords: () => void; onVersionChange: (versionId: number) => void }) {
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
  const updated = detail?.updated_at ? formatDateTime(detail.updated_at) : '…';
  const currentVersionId = versionId;
  const currentVersion = currentVersionId == null ? null : versions.find((version) => version.id === currentVersionId) ?? null;
  const visibleVersions = versions;
  const lineageIcon: Record<string, typeof Database> = { records: Database, annotation_tasks: Tag, dataset_versions: Box, training_tasks: TrainFront };
  const lineageSuffix: Record<string, string> = { records: '条', training_tasks: '次', annotation_tasks: '个', dataset_versions: '个' };
  return <><div className="dataset-detail"><div className="dataset-breadcrumb">数据管理 / 数据集 / {dataset.name} / 数据集概览</div><div className="dataset-detail-head"><div><span className="file-badge"><Box size={14} />{dataset.id}</span><h2>{dataset.name} <em>{dataset.version ? `快照 ${dataset.version}` : '未生成快照'}</em></h2><p>{dataset.task} · {dataset.source} · 最近更新 {updated}</p></div><div className="dataset-detail-actions"><StatusPill tone={dataset.tone as 'green' | 'orange'}>{dataset.status}</StatusPill><button className="primary-button dataset-primary-entry" onClick={onShowAllRecords}><Database size={14} />查看全部焊缝 · {dataset.weldCount} 条</button>{currentVersionId != null && <button className="outline-button" onClick={onShowRecords}><GitBranch size={14} />查看当前快照 · {currentVersion?.item_count ?? detail?.sample_count ?? 0} 条</button>}</div></div>{currentVersionId == null && <div className="dataset-empty-state">当前数据集还没有固定快照；新数据登记完成后系统会自动生成快照。</div>}<div className="dataset-detail-grid"><div className="dataset-detail-stat"><span>数据集数据</span><strong>{detail ? detail.sample_count.toLocaleString() : dataset.samples}</strong><small>固定快照中的样本总数</small></div><div className="dataset-detail-stat"><span>标注完成度</span><strong>{dataset.progress}</strong><small>通过质检的标注</small></div><div className="dataset-detail-stat"><span>训练 / 验证 / 测试</span><strong>{dataset.split}</strong><small>按数据集快照固定划分</small></div><div className="dataset-detail-stat"><span>数据质量</span><strong>{qualityPct}</strong><small>重复与空标注已检查</small></div></div><DatasetInputPanel task={dataset.task} dims={dims} /><ModelReadiness task={dataset.task} status={dataset.status} readiness={readiness} loading={readinessLoading} /><div className="dataset-detail-columns"><section className="panel"><div className="panel-heading"><div><h2>数据集快照</h2><p>固定训练样本清单；不随单条焊缝后续处理自动变化</p></div></div><div className="dataset-version-list">{visibleVersions.length ? visibleVersions.map((v) => <div className={`dataset-version ${v.id === currentVersionId ? 'current' : ''}`} key={v.version_no} onClick={() => onVersionChange(v.id)}><span>{v.version_no}</span><div><strong>固定快照 · {v.item_count.toLocaleString()} 条样本</strong><small>{formatDateTime(v.created_at)}</small></div>{v.id === currentVersionId ? <StatusPill>当前快照</StatusPill> : <button className="ghost-button" onClick={() => setSelectedVersion(v)}>查看详情</button>}</div>) : <p className="dataset-empty-state">还没有生成数据集快照。</p>}</div></section><section className="panel"><div className="panel-heading"><div><h2>数据血缘</h2><p>从焊缝版本到训练任务的关联</p></div></div>{lineage.length ? <div className="lineage">{lineage.flatMap((node, i) => { const Icon = lineageIcon[node.type] ?? Database; const sep = i === 0 ? [] : [<i key={`sep-${i}`}>↓</i>]; return [...sep, <span key={node.type}><Icon size={14} />{node.label} <b>{node.count} {lineageSuffix[node.type] ?? '个'}</b></span>]; })}</div> : <p className="dataset-empty-state" role="status">数据血缘加载中…</p>}</section></div></div>{selectedVersion && <VersionDetailDrawer mode="dataset" datasetId={dataset.id} version={selectedVersion} onClose={() => setSelectedVersion(null)} />}</>;
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
  return <section className="dataset-records"><div className="dataset-breadcrumb">数据管理 / 数据集 / {dataset.name} / 当前版本数据</div><div className="dataset-context-card"><div><span>数据集</span><strong>{dataset.name}</strong><small>{dataset.task} · 版本 #{versionId}</small></div><div><span>样本数</span><strong>{versionSummary?.item_count != null ? versionSummary.item_count.toLocaleString() : loading && !versionSummaryUnavailable ? '…' : total.toLocaleString()}</strong></div><div><span>训练 / 验证 / 测试</span><strong>{splitTotals ? `${splitTotals.train?.toLocaleString() ?? '—'} / ${splitTotals.val?.toLocaleString() ?? '—'} / ${splitTotals.test?.toLocaleString() ?? '—'}` : versionSummaryUnavailable ? '版本切分信息暂不可用' : '加载中…'}</strong></div><div><span>版本摘要</span><strong>{summaryState}</strong></div><div className="dataset-summary-links"><button className="ghost-button" onClick={onBack}><ChevronLeft size={14} />返回概览</button><label className="filter-field">切换版本<select value={versionId} onChange={(event) => onVersionChange(Number(event.target.value))}>{(versionChoices.length ? versionChoices : [{ id: versionId, version_no: `#${versionId}` } as DatasetVersion]).map((version) => <option value={version.id} key={version.id}>{version.version_no}</option>)}</select></label></div></div><div className="dataset-records-header"><div><h2>当前版本数据</h2><p>固定快照成员，筛选与分页由服务端执行。</p></div><div className="data-filter-strip"><div className="filter-field keyword"><label>关键词</label><div className="inline-search"><Search size={14} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="焊缝 ID、名称或登记编号" /></div></div><label className="filter-field">核验状态<select value={quality} onChange={(event) => setQuality(event.target.value)}><option value="">全部</option><option value="通过">通过</option><option value="待复核">待复核</option><option value="异常">异常</option></select></label><label className="filter-field">数据划分<select value={split} onChange={(event) => setSplit(event.target.value as DatasetItemRow['split'] | '')}><option value="">全部</option><option value="train">训练集</option><option value="val">验证集</option><option value="test">测试集</option></select></label></div></div>{notice && <p className="dataset-empty-state" role="status">{notice}</p>}{rows.length ? <div className="dataset-records-table"><div className="dataset-record-row dataset-record-head"><span>样本 ID / 焊缝</span><span>登记编号</span><span>来源 / 焊机</span><span>模态</span><span>核验状态</span><span>数据划分</span><span>采集时间</span></div>{rows.map((row) => <button className="dataset-record-row" key={row.sample_id} disabled={!row.weld_id} title={row.weld_id ? undefined : '该成员未关联焊缝，无法打开数据详情'} onClick={() => onSelectRecord(row)}><span><strong>样本 #{row.sample_id}</strong><small>{row.weld_id ?? '未关联焊缝'} · 帧 {row.frame_no ?? '—'}</small></span><span>{row.registration_no ?? '—'}</span><span>{row.source ?? '—'}<small>{row.machine ?? '—'}</small></span><span>{row.modalities.join(' / ') || '—'}</span><StatusPill tone={row.quality === '异常' ? 'red' : row.quality === '待复核' ? 'orange' : 'green'}>{row.quality ?? '未核验'}</StatusPill><span>{splitLabel[row.split]}</span><span>{formatDateTime(row.created_at)}</span></button>)}</div> : loading ? <p className="dataset-empty-state" role="status">成员列表加载中…</p> : <p className="dataset-empty-state">当前版本没有符合筛选条件的成员样本。</p>}<div className="table-footer"><span>共 {total} 条</span><div className="pagination"><button disabled={page === 1} onClick={() => setPage((value) => value - 1)}>‹</button><span>{page} / {totalPages}</span><button disabled={page === totalPages} onClick={() => setPage((value) => value + 1)}>›</button></div></div></section>;
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
  return <section className="dataset-records"><div className="dataset-breadcrumb">数据管理 / 数据集 / {dataset.name} / 全部数据</div><div className="dataset-context-card"><div><span>数据集</span><strong>{dataset.name}</strong><small>{dataset.task} · {dataset.id}</small></div><div><span>全部数据</span><strong>{total.toLocaleString()}</strong></div><div><span>版本策略</span><strong>新数据自动生成版本</strong></div><div className="dataset-summary-links"><button className="ghost-button" onClick={onBack}><ChevronLeft size={14} />返回概览</button></div></div><div className="dataset-records-header"><div><h2>全部数据样本</h2><p>这里展示该数据集下所有已登记数据，不要求先创建数据集版本。</p></div><div className="data-filter-strip"><div className="filter-field keyword"><label>关键词</label><div className="inline-search"><Search size={14} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="焊缝 ID、名称或登记编号" /></div></div></div></div>{error && <p className="dataset-empty-state" role="alert">{error}，请刷新后重试。</p>}{rows.length ? <div className="dataset-records-table"><div className="dataset-record-row dataset-record-head"><span>焊缝 / 登记编号</span><span>来源 / 焊机</span><span>数据模态</span><span>核验状态</span><span>当前数据版本</span><span>采集时间</span></div>{rows.map((row) => <button className="dataset-record-row" key={row.weld_id} onClick={() => onSelectRecord(row)}><span><strong>{row.weld_id}</strong><small>{row.weld_name ?? '未命名'} · {row.registration_no}</small></span><span>{row.source ?? '—'}<small>{row.machine ?? '—'}</small></span><span>{(row.modalities ?? []).join(' / ') || '—'}</span><StatusPill tone={row.quality === '异常' ? 'red' : row.quality === '待复核' ? 'orange' : 'green'}>{row.quality ?? '未核验'}</StatusPill><span>{row.latest_version?.version_no ?? '—'}</span><span>{formatDateTime(row.created_at)}</span></button>)}</div> : loading ? <p className="dataset-empty-state" role="status">数据样本加载中…</p> : <p className="dataset-empty-state">该数据集下暂无登记数据。</p>}<div className="table-footer"><span>共 {total} 条</span><div className="pagination"><button disabled={page === 1} onClick={() => setPage((value) => value - 1)}>‹</button><span>{page} / {totalPages}</span><button disabled={page === totalPages} onClick={() => setPage((value) => value + 1)}>›</button></div></div></section>;
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
  return <section className="panel raw-signal-preview"><div className="panel-heading"><div><h2>原始数据预览</h2><p>基于当前数据版本的多通道时域波形，可用于快速确认数据是否正常。</p></div><div className="raw-signal-meta"><span>{loading ? '信号加载中' : signalError ? '信号不可用' : '真实信号'}</span><small>版本 #{versionId}</small></div></div><div className="raw-channel-toggles">{channels.map((channel) => <button key={channel.id} className={active.has(channel.id) ? 'active' : ''} onClick={() => toggle(channel.id)}><i style={{ background: channel.color }} />{channel.name}<small>{channel.unit}</small>{active.has(channel.id) && <Check size={12} />}</button>)}</div><div className="raw-signal-chart" onMouseLeave={() => setHover(null)}>{loading && !channels.length ? <p className="dataset-empty-state" role="status">波形加载中…</p> : signalError ? <p className="dataset-empty-state" role="alert">{signalError}</p> : <><svg viewBox={`0 0 ${CH} ${CW}`} preserveAspectRatio="none" role="img" aria-label="原始多通道信号波形" onMouseMove={handleHover}>{[0, .25, .5, .75, 1].map((position) => <line key={position} x1={AXIS_L} y1={PLOT_H * position} x2={CH} y2={PLOT_H * position} stroke="#edf2f2" />)}{visibleChannels.map((channel) => <path key={channel.id} d={toPath(channel.values, channel.lo, channel.hi)} fill="none" stroke={channel.color} strokeWidth={channel.id === 'cur' ? 2 : 1.6} />)}{hover && <line x1={cursorX} y1={0} x2={cursorX} y2={PLOT_H} stroke="#d16f69" strokeWidth="1.5" strokeDasharray="4 3" />}</svg>{hover && <div className="raw-signal-tooltip" style={{ left: hover.left, top: hover.top }}><strong>{fmt(hover.time)}</strong>{visibleChannels.map((channel) => { const i = Math.min(channel.values.length - 1, Math.max(0, Math.round((hover.time / signalDuration) * Math.max(channel.values.length - 1, 0)))); return <span key={channel.id}><i style={{ background: channel.color }} />{channel.name}<b>{channel.values[i]?.toFixed(3)} {channel.unit}</b></span>; })}</div>}<div className="raw-signal-axis"><span>0s</span><span>1s</span><span>2s</span><span>3s</span><span>4s</span><span>{signalDuration.toFixed(2)}s</span></div></>}</div><div className="raw-signal-footer"><span><Waves size={14} />电流 / 电压 / 气体流量 / 送丝速度</span><button className="outline-button" onClick={() => { setSelectedDataId(weldId); navigate('analysis/analysis'); }}>进入完整起收弧识别 <ArrowUpRight size={14} /></button></div></section>;
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

function DatasetRecordDetail(props: { weldId: string; dataset: DatasetRow; versionId: number; split: 'train' | 'val' | 'test' | null; onBack: () => void; setSelectedDataId: (id: string | null) => void; navigate: (route: Route) => void }) {
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const handleDelete = () => {
    if (!window.confirm(`确定删除焊缝“${props.weldId}”及其全部数据版本吗？该操作不可撤销。`)) return;
    setDeleting(true);
    deleteWeld(props.weldId)
      .then(() => window.location.reload())
      .catch((err) => setError(err instanceof Error ? err.message : '删除焊缝失败'))
      .finally(() => setDeleting(false));
  };
  return <><DatasetRecordDetailContent {...props} /><div className="dataset-delete-bar">{error && <span role="alert">{error}</span>}<button className="danger-button" onClick={handleDelete} disabled={deleting}>{deleting ? '删除中…' : '删除焊缝'}</button></div></>;
}

function DatasetRecordDetailContent({ weldId, dataset, versionId, split, onBack, setSelectedDataId, navigate }: { weldId: string; dataset: DatasetRow; versionId: number; split: 'train' | 'val' | 'test' | null; onBack: () => void; setSelectedDataId: (id: string | null) => void; navigate: (route: Route) => void }) {
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
  return <section className="dataset-record-detail"><div className="dataset-breadcrumb">数据管理 / 数据集列表 / {dataset.name} / 数据详情 / {weldId}</div><button className="ghost-button" onClick={onBack}><ChevronLeft size={14} />返回数据列表</button><div className="dataset-context-card"><div><span>焊缝 ID</span><strong>{weldId}</strong></div><div><span>所属数据集</span><strong>{dataset.name}</strong></div><div><span>所属版本</span><strong>#{versionId}</strong></div><div><span>数据划分</span><strong>{splitText}</strong></div></div>{error && <p className="dataset-empty-state" role="alert">{error}</p>}<RawMediaPreview objectKeys={record?.latest_version?.object_keys ?? EMPTY_OBJECT_KEYS} loading={!record && !error} /><RawSignalPreview weldId={weldId} versionId={record?.latest_version_id ?? record?.latest_version?.id ?? versionId} navigate={navigate} setSelectedDataId={setSelectedDataId} /><div className="dataset-detail-columns"><section className="panel"><h2>数据详情</h2><InfoRow label="所属数据集" value={dataset.name} /><InfoRow label="所属版本" value={`版本 #${versionId}`} /><InfoRow label="数据划分" value={splitText} /><InfoRow label="焊缝 ID" value={record?.weld_id ?? weldId} /><InfoRow label="登记编号" value={record?.registration_no ?? '加载中…'} /><InfoRow label="当前版本" value={record?.latest_version?.version_no ?? '加载中…'} /><InfoRow label="核验状态" value={record?.quality ?? '加载中…'} accent={!!record} />{record && <><InfoRow label="数据来源" value={record.source} /><InfoRow label="焊机" value={record.machine ?? '—'} /><InfoRow label="数据模态" value={record.modalities.join(' / ') || '—'} /></>}</section><section className="panel"><h2>继续处理</h2><StatusPill tone={qualityTone}>{record?.quality ?? '加载中'}</StatusPill><button className="quick-action" onClick={() => navigate('data-center/validation')}><ClipboardCheck size={15} />数据核验 <ArrowUpRight size={14} /></button><button className="quick-action" onClick={() => navigate('data-center/versions')}><GitBranch size={14} />数据版本 <ArrowUpRight size={14} /></button><button className="quick-action" onClick={() => navigate('analysis/analysis')}><BarChart3 size={15} />起收弧识别 <ArrowUpRight size={14} /></button></section></div></section>;
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
