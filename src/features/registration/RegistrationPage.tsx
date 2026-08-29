import { useEffect, useRef, useState } from 'react';
import type { ChangeEvent } from 'react';
import { CheckCircle2, ClipboardCheck, FileCheck2, Upload } from 'lucide-react';
import { listDatasets } from '../../api/datasets';
import { attachRawFiles, createRegistration, listWelds } from '../../api/welds';
import { presignUpload, putFileDirect } from '../../api/files';
import type { Dataset, RegistrationForm } from '../../api/types';
import { mockWeldRows, toWeldRow } from '../datasets/weldRows';
import type { WeldRow } from '../datasets/weldRows';
import { PageIntro } from '../../shared/components/PageIntro';
import { StatusPill } from '../../shared/components/StatusPill';

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

export function RegistrationPage() {
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
  const setField = (key: keyof RegistrationForm) => (event: ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setForm((prev) => ({ ...prev, [key]: event.target.value }));
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
  const handleFile = (key: UploadZoneKey, event: ChangeEvent<HTMLInputElement>) => {
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

  return <div className="page-wrap"><PageIntro eyebrow="标准化台账" title="数据登记" description="为每批焊接多模态数据建立统一身份、来源和工艺参数档案。" action={<span className="workflow-chip"><CheckCircle2 size={14} />登记数据即进入数据流程</span>} /><div className="registration-layout"><section className="panel form-panel"><div className="panel-heading"><div><h2>登记数据</h2><p>带 * 的字段为必填项</p></div><span className="draft-tag">登记草稿</span></div><div className="form-section-title"><span>基础信息</span><i /></div><div className="form-grid"><label className={flash.dataset ? 'field-flash' : undefined}><span>所属数据集<span className="required-mark"> *</span></span><select value={form.dataset_id || ''} onChange={(event) => setForm((prev) => ({ ...prev, dataset_id: Number(event.target.value) }))}><option value="">请选择数据集</option>{datasets.map((dataset) => <option value={dataset.id} key={dataset.id}>{dataset.name} · {dataset.dataset_no}</option>)}</select></label><label className={flash.source ? 'field-flash' : undefined}><span>数据来源<span className="required-mark"> *</span></span><input placeholder="例如：产线相机 · 03号" value={form.source} onChange={setField('source')} /></label><label className={flash.collected_at ? 'field-flash' : undefined}><span>采集时间<span className="required-mark"> *</span></span><input type="datetime-local" value={form.collected_at ?? ''} onChange={setField('collected_at')} /></label><label className={flash.weld_name ? 'field-flash' : undefined}><span>焊缝 / 批次名称<span className="required-mark"> *</span></span><input placeholder="输入焊缝或批次名称" value={form.weld_name ?? ''} onChange={setField('weld_name')} /></label><label>关联产品信息<input placeholder="产品型号、零件编号" value={form.product ?? ''} onChange={setField('product')} /></label></div><div className="form-section-title"><span>采集与工艺参数</span><i /></div><div className="form-grid"><label>焊机型号<select value={form.machine ?? ''} onChange={setField('machine')}><option>Fronius CMT</option><option>OTC FD-V8</option><option>Panasonic YD-500</option></select></label><label>焊接方法<select value={form.weld_method ?? ''} onChange={setField('weld_method')}><option>MAG焊</option><option>MIG焊</option><option>TIG焊</option></select></label><label>板材材质<input placeholder="例如：Q235B" value={form.material ?? ''} onChange={setField('material')} /></label><label>板材厚度<input placeholder="例如：6 mm" value={form.thickness ?? ''} onChange={setField('thickness')} /></label><label>电流 / 电压<input placeholder="180 A / 22 V" value={form.current_voltage ?? ''} onChange={setField('current_voltage')} /></label><label>采样频率<input placeholder="10 kHz" value={form.sample_rate ?? ''} onChange={setField('sample_rate')} /></label></div><div className="form-section-title"><span>登记数据文件</span><i /></div><div className={`upload-zones${flash.file ? ' field-flash' : ''}`}>{UPLOAD_ZONES.map((zone) => { const st = uploads[zone.key]; return <div className="upload-zone" key={zone.key}><Upload size={16} /><strong>{zone.label}</strong><span>{zone.hint}</span>{st && <span className={st.status === 'error' ? 'toolbar-error' : 'accent-text'} role={st.status === 'error' ? 'alert' : undefined}>{st.status === 'uploading' ? `上传中：${st.fileName} ${st.progress ?? 0}%` : st.status === 'pending' ? `已选择：${st.fileName}（待上传）` : st.status === 'error' ? (st.errorMsg ?? `${st.fileName} 上传失败，请重试`) : `${st.fileName} 已上传`}</span>}<button className="outline-button" onClick={() => fileRefs.current[zone.key]?.click()}>{st?.status === 'pending' || st?.status === 'done' ? '更换文件' : '选择文件'}</button><input ref={(el) => { fileRefs.current[zone.key] = el; }} type="file" accept={zone.accept} style={{ display: 'none' }} onChange={(event) => handleFile(zone.key, event)} onClick={(e) => { e.currentTarget.value = ''; }} /></div>; })}</div><button className={`full-button${missingFields.length || submitting ? ' full-button--disabled' : ''}`} aria-disabled={missingFields.length > 0 || submitting} onClick={() => { if (submitting) return; if (missingFields.length) handleMissingClick(); else handleSubmit(); }}>{registered ? <><CheckCircle2 size={16} />登记成功：{regNo}</> : submitting ? <><FileCheck2 size={16} />登记中…</> : <><FileCheck2 size={16} />登记数据</>}</button>{(missingHint || regError) && <span className="toolbar-error" role="alert">{missingHint ?? regError}</span>}</section><aside className="registration-aside"><section className="panel"><div className="panel-heading"><div><h2>登记规则</h2><p>平台数据使用约束</p></div><ClipboardCheck size={18} className="accent-text" /></div>{['自动生成唯一编号', '原始文件与后续版本自动关联', '上传后触发入库前数据核验', '所有操作写入审计日志'].map((item) => <div className="rule-row" key={item}><CheckCircle2 size={15} />{item}</div>)}</section><section className="panel"><div className="panel-heading"><div><h2>最近登记</h2><p>最近 24 小时新增数据</p></div></div>{recentLoading ? <p className="dataset-empty-state" role="status">最近登记加载中…</p> : recentRows.map((row) => <div className="recent-row" key={row.id}><span className="recent-dot" /><div><strong>{row.id}</strong><small>{row.source} · {row.time.slice(11)}</small></div><StatusPill>已登记</StatusPill></div>)}</section></aside></div></div>;
}
