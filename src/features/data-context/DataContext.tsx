import { useCallback, useEffect, useState } from 'react';
import { Archive, ArrowUpRight, Box, ChevronLeft, Database, Plus, Waves } from 'lucide-react';
import { listDatasets } from '../../api/datasets';
import { createVersion, getWeld, listVersions, listWelds, runValidation } from '../../api/welds';
import { presignUpload, putFileDirect } from '../../api/files';
import type { DataRecord, Dataset, DataVersion } from '../../api/types';
import { VersionDetailDrawer } from '../datasets/DatasetWorkspace';
import { fallbackDatasetOptions } from '../datasets/fallbacks';
import { mockWeldRows, toWeldRow } from '../datasets/weldRows';
import type { WeldRow } from '../datasets/weldRows';
import { StatusPill } from '../../shared/components/StatusPill';
import { formatDateTime } from '../../shared/lib/formatting';

export function SelectionSwitcher({ selectedDatasetId, setSelectedDatasetId, selectedDataId, setSelectedDataId, showContext, onChange }: { selectedDatasetId: number | null; setSelectedDatasetId: (id: number | null) => void; selectedDataId: string | null; setSelectedDataId: (id: string | null) => void; showContext: boolean; onChange?: () => void }) {
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

export function SelectionRequired({ onBack }: { onBack: () => void }) {
  return <div className="selection-required"><div className="selection-icon"><Database size={23} /></div><h2>请先选择数据集和焊缝数据</h2><p>当前功能必须绑定真实数据后才能执行，请在页面上方选择数据集和一条焊缝。</p><button className="outline-button" onClick={onBack}><ChevronLeft size={14} />前往选择数据</button></div>;
}

export function DatasetTestingContext() {
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
export function AnalysisSelect({ onContinue, selectedDatasetId, setSelectedDatasetId }: { onContinue: (id: string) => void; selectedDatasetId: number | null; setSelectedDatasetId: (id: number | null) => void }) {
  const [datasetOptions, setDatasetOptions] = useState<{ id: number; label: string }[]>([]);
  const [weldRows, setWeldRows] = useState<SelectCard[]>([]);
  const [loadingWeld, setLoadingWeld] = useState(false);
  // 第一级：数据集下拉（数据集为登记时的归属容器，分析以其为入口）。
  useEffect(() => {
    let cancelled = false;
    const fallback = () => fallbackDatasetOptions;
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

export function VersionPanel({ dataId }: { dataId?: string }) {
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
  return <><section className="panel version-panel"><div className="panel-heading"><div><h2>数据版本</h2><p>原始数据与加工结果的不可覆盖版本链路</p></div><div className="toolbar-actions"><StatusPill>当前版本 {currentVersion?.version_no ?? '—'}</StatusPill><button className="primary-button" onClick={() => setShowCreate(true)} disabled={!dataId || creating}><Plus size={14} />新建数据版本</button></div></div>{notice && <p className="toolbar-error" role="status">{notice}</p>}{versionsLoading ? <p className="dataset-empty-state" role="status">版本链路加载中…</p> : versionsUnavailable ? <p className="dataset-empty-state" role="alert">版本信息暂时无法读取，请稍后重试。</p> : versions.length ? <div className="version-line">{versions.map((version) => <div className={version.id === currentVersionId ? 'current' : ''} key={`${version.version_no}-${version.id}`}><i /><span>{`${version.version_no} ${version.action}`}<small>{formatDateTime(version.created_at)} · {version.operator ?? '—'}</small></span><div className="toolbar-actions"><button className="ghost-button" onClick={() => setSelectedVersionId(String(version.id))}>查看</button><button className="outline-button" disabled={validating === version.id} onClick={() => handleValidation(version.id)}>{validating === version.id ? '核验中…' : '执行核验'}</button></div></div>)}</div> : <p className="dataset-empty-state">该焊缝暂无版本数据。</p>}</section>{showCreate && <VersionCreateDialog baseVersion={currentVersion?.version_no} creating={creating} onCancel={() => setShowCreate(false)} onConfirm={handleCreate} />}{selectedVersionId && <VersionDetailDrawer mode="weld" weldId={dataId ?? ''} versionId={selectedVersionId} onClose={() => setSelectedVersionId(null)} />}</>;
}

function VersionCreateDialog({ baseVersion, creating, onCancel, onConfirm }: { baseVersion?: string; creating: boolean; onCancel: () => void; onConfirm: (payload: { action: '去噪处理' | '人工修正'; note?: string; file?: File }) => void }) {
  const [action, setAction] = useState<'去噪处理' | '人工修正'>('去噪处理');
  const [note, setNote] = useState('');
  const [file, setFile] = useState<File | undefined>();
  return <div className="app-dialog-backdrop" role="presentation" onClick={onCancel}><section className="app-dialog" role="dialog" aria-modal="true" aria-label="新建数据版本" onClick={(event) => event.stopPropagation()}><div className="app-dialog-head"><div><h2>新建数据版本</h2><p>基于 {baseVersion ?? '当前版本'} 创建，不会覆盖历史版本。</p></div><button className="icon-button" onClick={onCancel} aria-label="关闭">×</button></div><div className="form-block"><label>处理动作</label><select className="native-select" value={action} onChange={(event) => setAction(event.target.value as '去噪处理' | '人工修正')}><option value="去噪处理">去噪处理</option><option value="人工修正">人工修正</option></select></div><div className="form-block"><label>版本说明</label><textarea className="input-field" rows={3} placeholder="说明本次处理内容、参数或修正原因" value={note} onChange={(event) => setNote(event.target.value)} /></div><div className="form-block"><label>加工后文件（可选）</label><input type="file" onChange={(event) => setFile(event.target.files?.[0])} /><small className="form-help">文件将保存到 processed/{'{焊缝ID}'}，并挂载到新版本。</small></div><div className="dialog-actions"><button className="ghost-button" onClick={onCancel} disabled={creating}>取消</button><button className="primary-button" onClick={() => onConfirm({ action, note: note.trim() || undefined, file })} disabled={creating}>{creating ? '创建中…' : '创建版本'}</button></div></section></div>;
}
