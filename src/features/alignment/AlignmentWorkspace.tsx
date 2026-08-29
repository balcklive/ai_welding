import { useEffect, useMemo, useRef, useState } from 'react';
import {
  Activity, AlertTriangle, AudioWaveform, BarChart3, Check, CheckCircle2,
  FileText, Image as ImageIcon, Play, RefreshCw, ScanLine, SlidersHorizontal, Waves,
} from 'lucide-react';
import {
  createAlignmentTask, createSplitTask, getLatestAlignmentTask, getSignals, previewSplitTask,
} from '../../api/analysis';
import { getFileUrl } from '../../api/files';
import { getWeld, listVersions } from '../../api/welds';
import type { AlignmentResult, AlignmentTrack, DataRecord, SignalData, SplitPreview, SplitResult } from '../../api/types';
import { useJob } from '../../hooks/useJob';
import { PageIntro } from '../../shared/components/PageIntro';
import { StatusPill } from '../../shared/components/StatusPill';
import { Toolbar } from '../../shared/components/Toolbar';
import { SampleWaveThumb } from '../analysis/AnalysisWorkspace';
import type { SplitPreviewSample } from '../analysis/AnalysisWorkspace';
import { buildPath, chanColor, fmt } from '../analysis/signals/chartData';

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

/** 模型中心 · 训练数据准备：从数据管理的数据集筛选样本，生成可用于训练的固定版本快照。 */
export function AlignmentWorkspace({ splitOnly = false, dataId }: { embedded?: boolean; splitOnly?: boolean; dataId?: string }) {
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
  const [splitPreview, setSplitPreview] = useState<SplitPreview | null>(null);
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
