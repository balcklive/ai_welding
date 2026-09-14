import { useEffect, useRef, useState } from 'react';
import type { ChangeEvent } from 'react';
import { CheckCircle2, ClipboardCheck, FileCheck2, Upload } from 'lucide-react';
import { listDatasetOptions } from '../../api/datasets';
import { listOptionGroups } from '../../api/settings';
import { attachRawFiles, createRegistration, listWelds } from '../../api/welds';
import { presignUpload, putFileDirect } from '../../api/files';
import type { DatasetOption, Registration, RegistrationForm } from '../../api/types';
import type { Route } from '../../app/navigation';
import { toWeldRow } from '../datasets/weldRows';
import type { WeldRow } from '../datasets/weldRows';
import { ConfirmDialog } from '../../shared/components/ConfirmDialog';
import { ErrorState } from '../../shared/components/ErrorState';
import { PageIntro } from '../../shared/components/PageIntro';
import { StatusPill } from '../../shared/components/StatusPill';
import { TERMS } from '../../shared/lib/terms';
import { useJob } from '../../hooks/useJob';

type UploadZoneKey = 'csv' | 'image' | 'video' | 'audio';

// T3.2/T3.3：`FALLBACK_OPTIONS` 已删除——可选项字典（系统设置）是唯一来源，
// 拉取失败就走错误态 + 重试并禁止提交，不再用硬编码值顶替（顶替会写入现场不存在的型号）。

//: 数据来源 / 产品信息的候选值走 <datalist>（保留自由填写），id 需全局唯一。
const SOURCE_LIST_ID = 'registration-source-options';
const PRODUCT_LIST_ID = 'registration-product-options';

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

/** 表单字段 → 中文名（弹窗与提示共用）。 */
const FIELD_LABELS: Record<string, string> = {
  source: '数据来源', collected_at: '采集时间', weld_name: '样本名称（焊缝 / 批次）',
  product: '关联产品信息', machine: '焊机型号', weld_method: '焊接方法', material: '板材材质',
  thickness: '板材厚度', current_voltage: '电流 / 电压', sample_rate: '采样频率',
  wire_feed_speed: '送丝速度', welding_speed: '焊接速度',
};

/**
 * T4.2.1 默认值来源 3「该用户最近一次成功登记的值」：按登录用户分键存在**本地**（不上传服务器），
 * 同一条产线连续登记多条时只需改差异项。取不到用户 id（未登录/裁剪过的 localStorage）回落 anonymous。
 */
const LAST_VALUES_PREFIX = 'ai-welding:last-registration:';
/** 允许"上次登记的值"默认化的字段：样本名称是标识性字段，必须人工填。 */
const DEFAULTABLE_FIELDS = ['source', 'machine', 'weld_method', 'material', 'thickness', 'current_voltage', 'sample_rate', 'product'] as const;

/** 可以走默认值的**字符串**字段（`dataset_id` 由数据集锁定、`collected_at` 用当前时间，都不在其中）。 */
type DefaultableField = Exclude<keyof RegistrationForm, 'dataset_id' | 'collected_at'>;

function currentUserKey(): string {
  try {
    const user = JSON.parse(localStorage.getItem('user') ?? '{}') as { id?: number | string };
    return String(user.id ?? 'anonymous');
  } catch {
    return 'anonymous';
  }
}

function loadLastValues(): Partial<RegistrationForm> {
  try {
    return JSON.parse(localStorage.getItem(LAST_VALUES_PREFIX + currentUserKey()) ?? '{}') as Partial<RegistrationForm>;
  } catch {
    return {};
  }
}

function saveLastValues(form: RegistrationForm): void {
  const picked: Record<string, string> = {};
  for (const field of DEFAULTABLE_FIELDS) {
    const value = form[field];
    if (value) picked[field] = value;
  }
  try {
    localStorage.setItem(LAST_VALUES_PREFIX + currentUserKey(), JSON.stringify(picked));
  } catch {
    // 隐私模式/配额满：默认值只是便利功能，失败不影响登记
  }
}

/**
 * 从 CSV 文本推导采样率（T4.2.1 默认值来源 2）：表头找时间列 → 相邻差分取**中位数**（抗丢点）→ 倒数。
 *
 * 只用于**预填**，最终以后端导入时的推导为准（`signal_ingest._time_column_to_seconds` + R6）；
 * 两者规则不同（后端还认 ISO 时间戳），所以这里只处理数值时间列，解析不出就留空。
 */
function sampleRateFromCsv(text: string): string {
  const lines = text.split(/\r?\n/).filter((line) => line.trim()).slice(0, 500);
  if (lines.length < 20) return '';
  const header = lines[0].split(',').map((cell) => cell.trim().toLowerCase());
  const timeIndex = header.findIndex((cell) => ['time', 't', 'timestamp', '时间', '时刻'].includes(cell) || cell.includes('时间'));
  if (timeIndex < 0) return '';
  const times: number[] = [];
  for (const line of lines.slice(1)) {
    const value = Number(line.split(',')[timeIndex]);
    if (Number.isFinite(value)) times.push(value);
  }
  const deltas = times.slice(1).map((value, index) => value - times[index]).filter((delta) => delta > 0).sort((a, b) => a - b);
  if (deltas.length < 10) return '';
  const step = deltas[Math.floor(deltas.length / 2)];
  const fs = step > 0 ? Math.round(1 / step) : 0;
  if (fs <= 0) return '';
  return fs % 1000 === 0 ? `${fs / 1000} kHz` : `${fs} Hz`;
}

export function RegistrationPage({ navigate, lockedDatasetId: inheritedDatasetId, setSelectedDatasetId, setSelectedDataId }: {
  navigate?: (route: Route) => void;
  /** T4.1：从数据集上下文进入时带下来的所属数据集（不可修改）。 */
  lockedDatasetId?: number | null;
  setSelectedDatasetId?: (id: number | null) => void;
  setSelectedDataId?: (id: string | null) => void;
}) {
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
  const [datasets, setDatasets] = useState<DatasetOption[]>([]);
  // T4.1：所属数据集继承自上下文并锁定；无上下文时先走"选择数据集"步骤（pendingDatasetId → 确认后锁定）。
  const [lockedDatasetId, setLockedDatasetId] = useState<number | null>(inheritedDatasetId ?? null);
  const [pendingDatasetId, setPendingDatasetId] = useState<number | null>(null);
  // machine/weld_method 默认值改为「字典中第一个启用项」（加载后回填），不再硬编码品牌。
  const [form, setForm] = useState<RegistrationForm>({ dataset_id: inheritedDatasetId ?? 0, source: '', collected_at: toLocalInputValue(new Date()), weld_name: '', product: '', machine: '', weld_method: '', material: '', thickness: '', current_voltage: '', sample_rate: '', wire_feed_speed: '', welding_speed: '' });
  // 系统设置维护的可选项（只取启用项）。初始为空：加载期不闪现兜底值；
  // 拉取失败置 optionsError（页面内错误态 + 禁止提交），不再回落到硬编码值。
  const [optionValues, setOptionValues] = useState<Record<'machine' | 'weld_method' | 'source' | 'product', string[]>>({ machine: [], weld_method: [], source: [], product: [] });
  // T4.2.1：哪些字段当前"仍是默认值"（供"默认"标记、提交前汇总确认、一键清除）。
  const [defaultValues, setDefaultValues] = useState<Partial<Record<DefaultableField, string>>>({});
  const [showDefaults, setShowDefaults] = useState(false);
  // T4.3：登记结果（成功后不再卡死在表单里，给出三个出口）。
  const [result, setResult] = useState<{ registration_no: string; weld_id: string; id: number | string } | null>(null);
  // T8：挂载响应会带出自动构建任务（`dataset_build`）——登记完即可看到数据集版本构建状态，
  // 刷新后也能在数据集页面由 `build_status` 恢复（上下文不入 URL，故登记页本身不持久化它）。
  const [buildJobId, setBuildJobId] = useState<string | null>(null);
  const { status: buildStatus } = useJob(buildJobId);
  // 下拉候选 = 字典启用项；当前值若已被停用/改名，仍补进候选，保证老数据可正常回显与提交。
  const withCurrent = (values: string[], current?: string | null) => (current && !values.includes(current) ? [current, ...values] : values);
  // 各上传区的 file input 引用（ref 回调写进同一对象）。
  const fileRefs = useRef<Partial<Record<UploadZoneKey, HTMLInputElement | null>>>({});
  // 部分失败重试时复用已生成的登记，避免重复登记：登记成功即记入 regRef。
  const regRef = useRef<Registration | null>(null);
  // T3.2/T3.3：两块附属数据（可选项字典 / 最近登记）的失败态；字典失败时禁止提交。
  const [optionsError, setOptionsError] = useState<unknown>(null);
  const [recentError, setRecentError] = useState<unknown>(null);
  const [datasetsError, setDatasetsError] = useState<unknown>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const retry = () => setReloadKey((n) => n + 1);
  // 是否已锚定至少一个文件（派生值，驱动按钮启用）。
  const hasFile = Object.values(files).some(Boolean);
  const setField = (key: keyof RegistrationForm) => (event: ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
    const value = event.target.value;
    setForm((prev) => ({ ...prev, [key]: value }));
    // 用户改过的字段不再算"默认值"
    setDefaultValues((prev) => {
      const field = key as DefaultableField;
      if (!(field in prev)) return prev;
      const next = { ...prev };
      delete next[field];
      return next;
    });
  };
  // form 的即时镜像：默认值回填需要读"当前表单"，用 ref 免得把 effect 挂到 form 上反复重跑。
  const formRef = useRef(form);
  useEffect(() => { formRef.current = form; }, [form]);

  /**
   * 按来源链回填默认值（T4.2.1）：**只在字段为空时**写入，并记录"哪些字段仍是默认值"。
   * 优先级由调用方决定：上下文 > 本次上传的 CSV 解析 > 上次登记的值 > 字典首项。
   */
  const applyDefaults = (patch: Partial<Record<DefaultableField, string | null>>) => {
    const next = { ...formRef.current };
    const applied: DefaultableField[] = [];
    for (const [key, value] of Object.entries(patch)) {
      const field = key as DefaultableField;
      if (!value || next[field]) continue;
      next[field] = String(value);
      applied.push(field);
    }
    if (!applied.length) return;
    formRef.current = next;
    setForm(next);
    setDefaultValues((prev) => ({ ...prev, ...Object.fromEntries(applied.map((field) => [field, next[field]])) }));
  };

  /** 一键清除默认值：把默认填进去的字段清空，交回用户填写（样本名称本来就不在默认值里）。 */
  const clearDefaults = () => {
    const cleared = { ...formRef.current };
    for (const field of Object.keys(defaultValues) as DefaultableField[]) cleared[field] = '';
    formRef.current = cleared;
    setForm(cleared);
    setDefaultValues({});
  };

  useEffect(() => {
    let cancelled = false;
    setDatasetsError(null);
    listDatasetOptions().then((datasetList) => {
      if (cancelled) return;
      setDatasets(datasetList);
    }).catch((err) => {
      if (cancelled) return;
      console.warn('[registration] listDatasets failed', err);
      setDatasets([]);
      setDatasetsError(err);
    });
    return () => { cancelled = true; };
  }, [reloadKey]);
  useEffect(() => {
    let cancelled = false;
    setRecentLoading(true);
    setRecentError(null);
    listWelds({ tab: 'recent' }).then((res) => {
      if (cancelled) return;
      setRecentRows(res.items.slice(0, 5).map((r) => ({ ...toWeldRow(r), time: (r.collected_at ?? r.created_at ?? '').replace('T', ' ').slice(0, 16) })));
    }).catch((err) => {
      if (cancelled) return;
      console.warn('[registration] recent welds failed', err);
      setRecentRows([]);
      setRecentError(err);
    }).finally(() => { if (!cancelled) setRecentLoading(false); });
    return () => { cancelled = true; };
  }, [reloadKey]);
  // 可选项字典：与数据集/最近登记分开发请求——字典失败不能影响登记页其余数据的加载。
  useEffect(() => {
    let cancelled = false;
    setOptionsError(null);
    listOptionGroups().then((groups) => {
      if (cancelled) return;
      const pick = (key: string) => groups.find((group) => group.key === key)?.items.filter((item) => item.active).map((item) => item.value) ?? [];
      const next = { machine: pick('machine'), weld_method: pick('weld_method'), source: pick('source'), product: pick('product') };
      setOptionValues(next);
      // T4.2.1 来源链：上次登记的值（来源 3）优先于字典首项（来源 4）；两者都只在字段为空时回填。
      applyDefaults({ ...loadLastValues(), machine: loadLastValues().machine || next.machine[0], weld_method: loadLastValues().weld_method || next.weld_method[0] });
    }).catch((err) => {
      if (cancelled) return;
      console.warn('[registration] option dictionary failed', err);
      setOptionValues({ machine: [], weld_method: [], source: [], product: [] });
      setOptionsError(err);
    });
    return () => { cancelled = true; };
  }, [reloadKey]);
  // T4.1：上下文里的所属数据集变化时跟随锁定（例如从数据集概览切到登记页）。
  useEffect(() => {
    if (inheritedDatasetId == null || inheritedDatasetId === lockedDatasetId) return;
    setLockedDatasetId(inheritedDatasetId);
    setPendingDatasetId(null);
    setForm((prev) => ({ ...prev, dataset_id: inheritedDatasetId }));
  }, [inheritedDatasetId, lockedDatasetId]);
  // T4.2.1 来源 1：上下文（所属数据集、采集时间）——采集时间已由初始 state 给当前时间。
  const lockedDataset = datasets.find((item) => item.id === lockedDatasetId) ?? null;

  const confirmDataset = () => {
    if (pendingDatasetId == null) return;
    setLockedDatasetId(pendingDatasetId);
    setForm((prev) => ({ ...prev, dataset_id: pendingDatasetId }));
  };

  // 提交：登记（部分失败重试时复用 regRef）→ 逐文件预签名直传 MinIO（进度按区回显）→ 统一挂载。
  const handleSubmit = async () => {
    if (result || submitting) return;
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
        const attached = keys.length ? await attachRawFiles(String(reg.id), keys) : null;
        if (attached?.dataset_build?.job_id) setBuildJobId(attached.dataset_build.job_id);
      } catch (err) {
        console.warn('[registration] attachRawFiles failed', err);
        throw new Error('文件已上传但关联失败，请重新提交');
      }
      // T4.2.1：记下这次成功登记的值，供"继续登记下一条"与下次进入登记页做默认值。
      saveLastValues(form);
      setResult({ registration_no: reg.registration_no, weld_id: reg.weld_id, id: reg.id });
    } catch (err) {
      // T3.2：写操作失败**保留用户已填内容**（不清表单），只置错误态。
      setRegError(err instanceof Error && err.message ? err.message : '上传失败，请检查必填项后重试');
    } finally {
      setSubmitting(false);
    }
  };

  /** T4.3「继续登记下一条」：清空表单与上传区，保留数据集上下文与上次的工艺参数作为默认。 */
  const startNext = () => {
    const fresh: RegistrationForm = { dataset_id: lockedDatasetId ?? 0, source: '', collected_at: toLocalInputValue(new Date()), weld_name: '', product: '', machine: '', weld_method: '', material: '', thickness: '', current_voltage: '', sample_rate: '', wire_feed_speed: '', welding_speed: '' };
    formRef.current = fresh;
    setForm(fresh);
    setDefaultValues({});
    setFiles({});
    setUploads({});
    setRegError(null);
    setMissingHint(null);
    setResult(null);
    setBuildJobId(null);
    regRef.current = null;
    applyDefaults({ ...loadLastValues(), machine: loadLastValues().machine || optionValues.machine[0], weld_method: loadLastValues().weld_method || optionValues.weld_method[0] });
  };

  // 缺失必填项清单（顺序即表单顺序）：dataset/source/collected_at/weld_name 对应必填输入，file 要求至少选择一个文件。
  const missingFields = [
    { key: 'dataset', label: `所属${TERMS.dataset}`, ok: lockedDatasetId != null },
    { key: 'source', label: '数据来源', ok: !!form.source.trim() },
    { key: 'collected_at', label: '采集时间', ok: !!form.collected_at },
    { key: 'weld_name', label: '样本名称（焊缝 / 批次）', ok: !!form.weld_name?.trim() },
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
    // 选择即锚定：不发起上传，等点"登记数据"统一提交（避免选错文件已白白占用带宽）。
    // S9：重新选中合法文件即覆盖上一轮的 error 状态（错误信息不残留）。
    setFiles((prev) => ({ ...prev, [key]: file }));
    setUploads((prev) => ({ ...prev, [key]: { status: 'pending', fileName: file.name } }));
    // T4.2.1 来源 2：从本次上传的 CSV 推导采样率（解析不出就留空，不猜默认值）。
    if (key === 'csv') {
      file.text().then((text) => {
        const parsed = sampleRateFromCsv(text);
        if (parsed) applyDefaults({ sample_rate: parsed });
      }).catch((err) => console.warn('[registration] csv sample-rate parse failed', err));
    }
  };
  /** 点「登记数据」：先挡错，再按 T4.2.1 第 3 条做默认值汇总确认，最后才真正提交。 */
  const handleSubmitClick = () => {
    if (submitting || result) return;
    if (datasetsError || optionsError) { setMissingHint('基础数据未加载（数据集或可选项字典），请先重试'); return; }
    if (!lockedDatasetId) { setMissingHint(`请先选择所属${TERMS.dataset}`); return; }
    if (missingFields.length) { handleMissingClick(); return; }
    if (Object.keys(defaultValues).length) { setShowDefaults(true); return; }
    void handleSubmit();
  };
  /** T4.3 出口 1/3：带上该条数据的数据集上下文再跳转（数据上下文不入 URL，只能这样带）。 */
  const openWithContext = (route: Route) => {
    if (lockedDatasetId != null) setSelectedDatasetId?.(lockedDatasetId);
    if (result?.weld_id) setSelectedDataId?.(result.weld_id);
    navigate?.(route);
  };

  return <div className="page-wrap">
    <PageIntro eyebrow="标准化台账" title="数据登记" description="为每批焊接多模态数据建立统一身份、来源和工艺参数档案。" action={<span className="workflow-chip"><CheckCircle2 size={14} />登记数据即进入数据流程</span>} />
    <div className="registration-layout">
      {result && <section className="panel registration-result">
        <CheckCircle2 size={34} className="accent-text" />
        <h2>登记成功 {result.registration_no}</h2>
        <p>{form.weld_name || '样本'} 已归档到「{lockedDataset?.name ?? TERMS.dataset}」。文件挂载后会自动触发导入与数据集版本构建。</p>{buildJobId && <p className="registration-build" role="status">数据集版本构建：{buildStatus === 'succeeded' ? '已完成' : buildStatus === 'failed' ? '构建失败，可在数据集页面点「重新构建」' : '构建中…'}</p>}
        <div className="registration-result-actions">
          <button className="outline-button" onClick={() => openWithContext('data-center/datasets')}>查看这条数据</button>
          <button className="primary-button" onClick={startNext}>继续登记下一条</button>
          <button className="ghost-button" onClick={() => openWithContext('data-center/validation')}>去数据核验</button>
        </div>
      </section>}
      {!result && <section className="panel form-panel">
        <div className="panel-heading"><div><h2>登记数据</h2><p>带 * 的字段为必填项</p></div><span className="draft-tag">{lockedDatasetId == null ? '第 1 步 / 共 2 步' : '登记草稿'}</span></div>
        {datasetsError ? <ErrorState scene={`加载${TERMS.dataset}`} error={datasetsError} onRetry={retry} /> : null}
        {optionsError ? <ErrorState scene="加载可选项字典" error={optionsError} onRetry={retry} /> : null}
        {lockedDatasetId == null ? <div className="registration-step">
          <h2>选择所属{TERMS.dataset}</h2>
          <p>登记的数据会归到这个{TERMS.dataset}下；选定后不可修改（要换{TERMS.dataset}请从该{TERMS.dataset}的页面进入登记）。</p>
          <select value={pendingDatasetId ?? ''} onChange={(event) => setPendingDatasetId(event.target.value ? Number(event.target.value) : null)} disabled={!!datasetsError}>
            <option value="">请选择{TERMS.dataset}</option>
            {datasets.map((item) => <option value={item.id} key={item.id}>{item.name} · {item.dataset_no}</option>)}
          </select>
          <button className="primary-button" disabled={pendingDatasetId == null || !!datasetsError} onClick={confirmDataset}>确认并填写登记信息</button>
        </div> : <>
        <div className="locked-dataset"><CheckCircle2 size={14} />所属{TERMS.dataset}：<strong>{lockedDataset?.name ?? `#${lockedDatasetId}`}</strong>（继承自当前上下文，不可修改）</div>
        {Object.keys(defaultValues).length > 0 && <button className="default-clear" type="button" onClick={clearDefaults}>清除默认值（{Object.keys(defaultValues).length} 项）</button>}
        <div className="form-section-title"><span>基础信息</span><i /></div>
        <div className="form-grid">
          <label className={flash.source ? 'field-flash' : undefined}><span>数据来源<span className="required-mark"> *</span>{defaultValues.source && <em className="default-mark">默认</em>}</span><input list={SOURCE_LIST_ID} placeholder="例如：产线相机 · 03号" value={form.source} onChange={setField('source')} /><datalist id={SOURCE_LIST_ID}>{optionValues.source.map((value) => <option key={value} value={value} />)}</datalist></label>
          <label className={flash.collected_at ? 'field-flash' : undefined}><span>采集时间<span className="required-mark"> *</span></span><input type="datetime-local" value={form.collected_at ?? ''} onChange={setField('collected_at')} /></label>
          <label className={flash.weld_name ? 'field-flash' : undefined}><span>样本名称（焊缝 / 批次）<span className="required-mark"> *</span></span><input placeholder="输入样本名称（焊缝 / 批次）" value={form.weld_name ?? ''} onChange={setField('weld_name')} /></label>
          <label>关联产品信息{defaultValues.product && <em className="default-mark">默认</em>}<input list={PRODUCT_LIST_ID} placeholder="产品型号、零件编号" value={form.product ?? ''} onChange={setField('product')} /><datalist id={PRODUCT_LIST_ID}>{optionValues.product.map((value) => <option key={value} value={value} />)}</datalist></label>
        </div>
        <div className="form-section-title"><span>采集与工艺参数</span><i /></div>
        <div className="form-grid">
          <label>焊机型号{defaultValues.machine && <em className="default-mark">默认</em>}<select value={form.machine ?? ''} onChange={setField('machine')}><option value="">请选择焊机型号</option>{withCurrent(optionValues.machine, form.machine).map((value) => <option key={value} value={value}>{value}</option>)}</select></label>
          <label>焊接方法{defaultValues.weld_method && <em className="default-mark">默认</em>}<select value={form.weld_method ?? ''} onChange={setField('weld_method')}><option value="">请选择焊接方法</option>{withCurrent(optionValues.weld_method, form.weld_method).map((value) => <option key={value} value={value}>{value}</option>)}</select></label>
          <label>板材材质{defaultValues.material && <em className="default-mark">默认</em>}<input placeholder="例如：Q235B" value={form.material ?? ''} onChange={setField('material')} /></label>
          <label>板材厚度{defaultValues.thickness && <em className="default-mark">默认</em>}<input placeholder="例如：6 mm" value={form.thickness ?? ''} onChange={setField('thickness')} /></label>
          <label>电流 / 电压{defaultValues.current_voltage && <em className="default-mark">默认</em>}<input placeholder="180 A / 22 V" value={form.current_voltage ?? ''} onChange={setField('current_voltage')} /></label>
          <label>采样频率{defaultValues.sample_rate && <em className="default-mark">默认</em>}<input placeholder="10 kHz" value={form.sample_rate ?? ''} onChange={setField('sample_rate')} /></label>
          <label>送丝速度<input placeholder="例如：15.8" value={form.wire_feed_speed ?? ''} onChange={setField('wire_feed_speed')} /></label>
          <label>焊接速度<input placeholder="例如：70.0" value={form.welding_speed ?? ''} onChange={setField('welding_speed')} /></label>
        </div>
        <div className="form-section-title"><span>登记数据文件</span><i /></div>
        <div className={`upload-zones${flash.file ? ' field-flash' : ''}`}>{UPLOAD_ZONES.map((zone) => {
          const st = uploads[zone.key];
          return <div className="upload-zone" key={zone.key}><Upload size={16} /><strong>{zone.label}</strong><span>{zone.hint}</span>{st && <span className={st.status === 'error' ? 'toolbar-error' : 'accent-text'} role={st.status === 'error' ? 'alert' : undefined}>{st.status === 'uploading' ? `上传中：${st.fileName} ${st.progress ?? 0}%` : st.status === 'pending' ? `已选择：${st.fileName}（待上传）` : st.status === 'error' ? (st.errorMsg ?? `${st.fileName} 上传失败，请重试`) : `${st.fileName} 已上传`}</span>}<button className="outline-button" onClick={() => fileRefs.current[zone.key]?.click()}>{st?.status === 'pending' || st?.status === 'done' ? '更换文件' : '选择文件'}</button><input ref={(el) => { fileRefs.current[zone.key] = el; }} type="file" accept={zone.accept} style={{ display: 'none' }} onChange={(event) => handleFile(zone.key, event)} onClick={(e) => { e.currentTarget.value = ''; }} /></div>;
        })}</div>
        <button className={`full-button${missingFields.length || submitting || datasetsError || optionsError ? ' full-button--disabled' : ''}`} aria-disabled={missingFields.length > 0 || submitting || Boolean(datasetsError) || Boolean(optionsError)} onClick={handleSubmitClick}>{submitting ? <><FileCheck2 size={16} />登记中…</> : <><FileCheck2 size={16} />登记数据</>}</button>
        {(missingHint || regError) && <span className="toolbar-error" role="alert">{missingHint ?? regError}</span>}
        </>}
      </section>}
      <aside className="registration-aside">
        <section className="panel"><div className="panel-heading"><div><h2>登记规则</h2><p>平台数据使用约束</p></div><ClipboardCheck size={18} className="accent-text" /></div>{['自动生成唯一编号', '原始文件与后续版本自动关联', '上传后触发入库前数据核验', '所有操作写入审计日志', '挂载标准多模态 CSV 后自动回填送丝速度、焊接速度与采集字段概览'].map((item) => <div className="rule-row" key={item}><CheckCircle2 size={15} />{item}</div>)}</section>
        <section className="panel"><div className="panel-heading"><div><h2>最近登记</h2><p>按登记时间倒序，显示真实核验状态</p></div></div>{recentLoading ? <p className="dataset-empty-state" role="status">最近登记加载中…</p> : recentError ? <ErrorState scene="加载最近登记" error={recentError} onRetry={retry} /> : recentRows.length === 0 ? <p className="dataset-empty-state" role="status">暂无登记数据</p> : recentRows.map((row) => <div className="recent-row" key={row.id}><span className="recent-dot" /><div><strong>{row.id}</strong><small>{row.source} · {row.time.slice(11)}</small></div><StatusPill tone={row.quality === '异常' ? 'red' : row.quality === '待复核' ? 'orange' : 'green'}>{row.quality === '通过' ? '核验通过' : row.quality}</StatusPill></div>)}</section>
      </aside>
    </div>
    {showDefaults && <ConfirmDialog
      title="以下字段使用了默认值，请确认无误"
      description="这些值来自上次登记 / 上传的 CSV / 系统字典，提交前请核对一遍。"
      items={Object.entries(defaultValues).map(([field, value]) => ({ label: FIELD_LABELS[field] ?? field, value }))}
      confirmLabel="确认无误，提交"
      cancelLabel="去修改"
      onCancel={() => setShowDefaults(false)}
      onConfirm={() => { setShowDefaults(false); void handleSubmit(); }}
    />}
  </div>;
}
