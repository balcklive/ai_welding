import { useEffect, useMemo, useRef, useState } from 'react';
import {
  Activity, AlertTriangle, AudioWaveform, BarChart3, Check, CheckCircle2,
  FileText, Image as ImageIcon, Play, RefreshCw, ScanLine, Waves,
} from 'lucide-react';
import {
  createAlignmentTask, getCalibration, getLatestAlignmentTask, getSignals, getVideoFrames,
  updateCalibration,
} from '../../api/analysis';
import { getFileUrl } from '../../api/files';
import { getWeld, listVersions } from '../../api/welds';
import type {
  AlignmentResult, AlignmentTrack, Calibration, DataRecord, SeamRoi, SignalData, VideoFrames,
} from '../../api/types';
import { useJob } from '../../hooks/useJob';
import { PageIntro } from '../../shared/components/PageIntro';
import { StatusPill } from '../../shared/components/StatusPill';
import { Toolbar } from '../../shared/components/Toolbar';
import { buildPath, chanColor, fmt } from '../analysis/signals/chartData';
import { OffsetCalibrationPanel } from './OffsetCalibrationPanel';
import { SeamRoiEditor } from './SeamRoiEditor';
import { VideoFilmLane } from './VideoFilmLane';

const VIDEO_EXTS = ['.mp4', '.avi', '.mkv', '.mov', '.webm'];
const ALIGN_CHANNEL_MAP: Record<string, string> = { current: 'cur', voltage: 'vol' };
const ALIGN_TRACK_META: Record<string, { label: string; tone: string }> = {
  // 视频已拆成两条轨：胶片条（`VideoFilmLane`，统一轴上可拖）与这条播放器（看细节）。
  // 一条轨只表达一件事——播放器的原生进度条与信号轴没有几何关系，不能拿它当"时间 bar"。
  video: { label: '视频预览', tone: 'blue' },
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

/**
 * 多模态对齐 · 时间轴对齐工作室（标定层）。
 *
 * **不再有 splitOnly 形态**：v3 起样本分段是独立工作台
 * （`features/alignment/split/SplitWorkspace`，设计 §7.1/§4.3）。本页只负责"建立统一坐标系"
 * ——标定 offset / ROI 属于这里，分段页只读消费。
 */
export function AlignmentWorkspace({ dataId, selectedVersionId = null, setSelectedVersionId }: { embedded?: boolean; dataId?: string; selectedVersionId?: number | null; setSelectedVersionId?: (id: number | null) => void }) {
  const [jobId, setJobId] = useState<string | null>(null);
  //: 这条焊缝的**最新**版本；实际对齐哪一版见下面的 `versionId`（上下文条选了就用选的那版）
  const [weldVersionId, setWeldVersionId] = useState<number | null>(null);
  const [inputReady, setInputReady] = useState(false);
  const [inputError, setInputError] = useState<string | null>(null);
  const [createError, setCreateError] = useState<string | null>(null);
  const [artifactError, setArtifactError] = useState<string | null>(null);
  const [record, setRecord] = useState<DataRecord | null>(null);
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const [signals, setSignals] = useState<SignalData | null>(null);
  const [playhead, setPlayhead] = useState(0);
  // 视频零点在信号轴上的时刻（`t_video = t_signal - offset`），来自该焊缝 v1.0 的标定。
  // 未标定/读取失败时保持 0 —— 与后端 mapping 的 `calibrated=false` 同义。
  const [videoOffset, setVideoOffset] = useState(0);
  // 未保存的偏移草稿（`null` = 无改动）。滑块/反向标定只改这里——**不走网络**（设计 §4.2：
  // 标定的实时反馈在前端本地完成，保存与映射产出必须经服务端）。
  const [videoOffsetDraft, setVideoOffsetDraft] = useState<number | null>(null);
  // 时间戳对照的读数，取自 `<video>` 元素自身而不是对齐产物 metadata——未跑过对齐就没有产物，
  // 而这两个值本来就该是"用户此刻在拖的那个视频"的真值（反向标定也用同一个元素，两者自洽）。
  const [videoTime, setVideoTime] = useState(0);
  const [videoDuration, setVideoDuration] = useState<number | null>(null);
  // 胶片条帧：**与 offset 无关**（服务端 seek_offset 恒 0），所以只在换焊缝/换版本时取一次；
  // 拖动改 offset 是纯前端平移，不重新请求。
  const [videoFrames, setVideoFrames] = useState<VideoFrames | null>(null);
  const [framesLoading, setFramesLoading] = useState(false);
  // 偏移面板的错误/提示与 ROI 面板的分开，否则两个面板的横幅会互相覆盖。
  const [offsetError, setOffsetError] = useState<string | null>(null);
  const [offsetNotice, setOffsetNotice] = useState<string | null>(null);
  // 标定原文（含焊缝图片 ROI）：本页是**唯一**能改它的地方（§4.3），分段页只读消费同一份。
  const [calibration, setCalibration] = useState<Calibration | null>(null);
  const [seamImageUrl, setSeamImageUrl] = useState<string | null>(null);
  const [seamImageError, setSeamImageError] = useState<string | null>(null);
  const [calibError, setCalibError] = useState<string | null>(null);
  const [calibLoading, setCalibLoading] = useState(false);
  const [calibSaving, setCalibSaving] = useState(false);
  // 对齐任务：纳入对齐的模态（默认取自登记模态，未登记则视频+时序）
  const [modalities, setModalities] = useState<string[]>(['video', 'timeseries']);

  const hydratedRef = useRef(false);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  // 拖动时的 seek 合并（见 `scheduleSeek`）
  const pendingSeekRef = useRef<number | null>(null);
  const seekRafRef = useRef<number | null>(null);
  // 实时预览值：草稿优先，没有草稿才用服务端已保存值。
  const effectiveOffset = videoOffsetDraft ?? videoOffset;
  // seek 写入与 onTimeUpdate 回写**必须成对读同一个瞬时值**（历史上只改一处 → seek 后游标
  // 被立刻拨回）。用 ref 而不是把偏移塞进 click 委托 effect 的依赖数组：那样每拖一格滑块
  // 都会重挂一次监听器。
  const effectiveOffsetRef = useRef(effectiveOffset);
  useEffect(() => { effectiveOffsetRef.current = effectiveOffset; }, [effectiveOffset]);
  const { job, status: jobStatus, progress, result, error: jobError } = useJob<AlignmentResult>(jobId);
  const alignRes = result && 'events' in result ? result : null;
  // 帧率只用于展示视频信息；切分规则（含秒 ↔ 帧换算）已整块移到分段页
  const videoFps = useMemo(() => {
    const videoTrack = (alignRes?.tracks ?? []).find((item) => item.channel === 'video');
    const fps = (videoTrack?.metadata ?? {}).fps;
    return typeof fps === 'number' && fps > 0 ? fps : null;
  }, [alignRes]);
  // 上下文条选了版本就用它（`null` = 跟随最新）；下游 effect 只依赖 `versionId`。
  const versionId = selectedVersionId ?? weldVersionId;
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
      setWeldVersionId(r.latest_version_id ?? r.latest_version?.id ?? null);
      setModalities(r.modalities?.length ? r.modalities : ['video', 'timeseries']);
      setInputReady(true);
    }).catch((err) => { if (!cancelled) setInputError(`焊缝信息读取失败：${err instanceof Error ? err.message : '请重试'}`); });
    return () => { cancelled = true; };
  }, [dataId]);
  useEffect(() => {
    if (!dataId || versionId == null || hydratedRef.current) return;
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
  }, [dataId, versionId]);
  // 当前版本原始数据 → 真实视频预签名 URL + 真实信号波形
  useEffect(() => {
    if (!dataId) return;
    let cancelled = false;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    setVideoUrl(null);
    setSeamImageUrl(null);
    setSeamImageError(null);
    setCalibration(null);
    setCalibError(null);
    // 换版本/换焊缝时视频读数必须一起清空 —— `<video>` 元素会被重建，
    // 不清就会显示上一个视频的时长与时刻。
    setVideoOffsetDraft(null);
    setVideoTime(0);
    setVideoDuration(null);
    setOffsetError(null);
    setOffsetNotice(null);
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
      // 视频零点：时间轴上的秒是**信号时间**，播放器 seek 要按 `t_video = t_signal - offset`
      // 换算。标定归属 v1.0，任何版本读到同一份，故这里用解析出的源版本 id 取即可。
      // 同一份响应也带着焊缝图片的 ROI 与对象键（对象键由服务端挑，跳过上次对齐的产物图）。
      setCalibLoading(true);
      getCalibration(dataId, String(sourceVersion.id))
        .then((c) => {
          if (cancelled) return;
          setCalibration(c);
          setVideoOffset(c.video.calibrated ? c.video.offset_seconds : 0);
          if (!c.seam_image.object_key) return;
          getFileUrl(c.seam_image.object_key).then((r) => { if (!cancelled) setSeamImageUrl(r.url); })
            .catch((err) => { if (!cancelled) setSeamImageError(err instanceof Error ? err.message : '请稍后重试'); });
        })
        .catch((err) => {
          if (!cancelled) setCalibError(`标定读取失败：${err instanceof Error ? err.message : '请重试'}`);
          console.warn('[alignment] calibration unavailable', err);
        })
        .finally(() => { if (!cancelled) setCalibLoading(false); });
    }).catch((err) => { if (!cancelled) setInputError(`数据版本读取失败：${err instanceof Error ? err.message : '请重试'}`); });
    return () => { cancelled = true; if (retryTimer) clearTimeout(retryTimer); };
  }, [dataId, versionId]);
  // 胶片条帧：**独立 effect**——不要塞进下面挂 click 委托的那个（那个的依赖数组是刻意精简的，
  // 掺进新依赖会让监听器随拖动重挂）。
  useEffect(() => {
    if (!dataId || versionId == null) {
      setVideoFrames(null);
      return;
    }
    let cancelled = false;
    // 先清空：换版本时旧帧会按新偏移摆到错误位置，宁可直接走 loading 态
    setVideoFrames(null);
    setFramesLoading(true);
    getVideoFrames(dataId, String(versionId))
      .then((frames) => { if (!cancelled) setVideoFrames(frames); })
      // 取不到帧不算页面错误：胶片轨走空态并显示服务端原因，视频预览轨照常可用
      .catch(() => { if (!cancelled) setVideoFrames(null); })
      .finally(() => { if (!cancelled) setFramesLoading(false); });
    return () => { cancelled = true; };
  }, [dataId, versionId]);
  // 对齐成功：切到产物新版本（回写全局上下文，其他页也要看到这一版）；视频轨道有源对象 →
  // 用内核实际使用的视频刷新播放器。`setSelectedVersionId` 缺省时退化为页内跟随最新。
  useEffect(() => {
    if (!alignRes) return;
    if (setSelectedVersionId) setSelectedVersionId(alignRes.version.id);
    else setWeldVersionId(alignRes.version.id);
  }, [alignRes, setSelectedVersionId]);
  const handleRun = () => {
    if (!dataId || versionId == null) { setCreateError('当前数据版本尚未准备好，请稍后重试。'); return; }
    setCreateError(null);
    const unsupported = modalities.filter((item) => item === 'audio' || item === 'infrared');
    const names: Record<string, string> = { video: '视频', timeseries: '时序', audio: '音频', infrared: '红外' };
    const warning = unsupported.length ? `\n${unsupported.map((item) => names[item]).join('、')}当前仅登记元数据，暂不会执行真正的时间对齐。` : '';
    if (!window.confirm(`确认开始多模态对齐？\n输入版本：v${versionId}\n参与模态：${modalities.map((item) => names[item] ?? item).join('、') || '无'}${warning}`)) return;
    const run = createAlignmentTask(dataId, String(versionId), modalities.length ? modalities : ['video', 'timeseries']);
    run.then((res) => setJobId(res.job_id)).catch((err) => setCreateError(`任务创建失败：${err instanceof Error ? err.message : '请检查输入后重试'}`));
  };
  /** 保存焊缝图片标定（`{roi}` = 框选并参与分段，`{excluded:true}` = 明确不参与）；
   * 成功返回 true 供面板清掉草稿框。 */
  const handleSaveRoi = (patch: { roi: SeamRoi } | { excluded: true }): Promise<boolean> => {
    if (!dataId || versionId == null) {
      setCalibError('当前数据版本尚未准备好，请稍后重试。');
      return Promise.resolve(false);
    }
    setCalibError(null);
    setCalibSaving(true);
    return updateCalibration(dataId, String(versionId), { seam_image: patch })
      .then((c) => {
        setCalibration(c);
        setVideoOffset(c.video.calibrated ? c.video.offset_seconds : 0);
        return true;
      })
      .catch((err) => {
        setCalibError(`标定保存失败：${err instanceof Error ? err.message : '请重试'}`);
        return false;
      })
      .finally(() => setCalibSaving(false));
  };
  /** 把 `<video>` 挪到指定的**视频轴**时刻（调用方已按 `t_video = t_signal − offset` 换算好）。
   *  rAF 合并：拖动时每帧最多 seek 一次，避免 60Hz 的 pointermove 把播放器拖垮。 */
  const scheduleSeek = (videoTime: number) => {
    pendingSeekRef.current = videoTime;
    if (seekRafRef.current != null) return;
    seekRafRef.current = requestAnimationFrame(() => {
      seekRafRef.current = null;
      const element = videoRef.current;
      const target = pendingSeekRef.current;
      pendingSeekRef.current = null;
      if (!element || target == null || !Number.isFinite(element.duration) || element.readyState < 1) return;
      // 钳到 [0, duration]：越界时停在视频首/末帧（也正是"该时刻没有画面"的诚实表现）。
      element.currentTime = Math.min(element.duration, Math.max(0, target));
    });
  };
  /** 拖偏移草稿（胶片条拖动/数字框）。**不走网络**，并且按设计 §4.2 把画面同步挪到「当前游标
   * 的信号时刻」对应的新位置——游标钉在起弧处拖 offset，就能看到画面滑到起弧帧，对准即可。
   * 只改读数不动画面的话，"对比时间戳"就只剩数字，没法目视对准。 */
  const handleOffsetDraft = (value: number | null) => {
    setVideoOffsetDraft(value);
    // 拖胶片条时 pointermove 是 ~60Hz，每次都写 `currentTime` 会疯狂 seek 掉帧——
    // 合并成每帧最多一次。**只有画面的 seek 被节流**，读数（`effectiveOffset`）照旧即时更新。
    if (playhead <= 0) return;
    scheduleSeek(playhead - (value ?? videoOffset));
  };
  /** 保存视频零点偏移。只发 `video` 组——合并语义保证 ROI 不动，且**不需要图片校验**
   *（`test_put_offset_does_not_need_image` 钉住了这一点）。 */
  const handleSaveOffset = () => {
    if (videoOffsetDraft == null) return;
    if (!dataId || versionId == null) {
      setOffsetError('当前数据版本尚未准备好，请稍后重试。');
      return;
    }
    setOffsetError(null);
    setOffsetNotice(null);
    setCalibSaving(true);
    updateCalibration(dataId, String(versionId), { video: { offset_seconds: videoOffsetDraft } })
      .then((c) => {
        setCalibration(c);
        setVideoOffset(c.video.calibrated ? c.video.offset_seconds : 0);
        setVideoOffsetDraft(null);
        setOffsetNotice('已保存视频零点偏移。已生成的对齐产物仍按旧偏移计算，请重新运行「开始多模态对齐」。');
      })
      // 失败只置错误态、**保留草稿**（写操作的 catch 不清用户输入）。
      .catch((err) => setOffsetError(`偏移保存失败：${err instanceof Error ? err.message : '请重试'}`))
      .finally(() => setCalibSaving(false));
  };
  /** 反向标定：`offset = 起弧信号时刻 − 视频当前时刻`（后端语义 `t_video = t_signal − offset` 的反解）。
   * 用户把播放器停在"画面刚起弧"那一帧点一下即可，不必猜数值。 */
  const handleReverseOffset = () => {
    setOffsetError(null);
    setOffsetNotice(null);
    const video = videoRef.current;
    if (!video || !Number.isFinite(video.duration)) {
      setOffsetError('视频尚未就绪，请等播放器加载完成后再试。');
      return;
    }
    if (video.readyState < 1) {
      setOffsetError('视频元数据未就绪，当前时刻还不可靠，请稍后重试。');
      return;
    }
    if (events == null) {
      setOffsetError('尚无起收弧事件（需真实信号），无法反向标定。');
      return;
    }
    const next = Math.round((events.arc - video.currentTime) * 100) / 100;
    if (!Number.isFinite(next)) {
      setOffsetError('视频当前时刻无效，请把播放器拖到起弧帧后再试。');
      return;
    }
    if (Math.abs(next) > 3600) {
      setOffsetError('算出的偏移超过 ±3600 秒，请确认播放器停在起弧帧。');
      return;
    }
    setVideoOffsetDraft(next);
    setOffsetNotice(`已按当前视频帧（${fmt(video.currentTime)}）对齐起弧（${fmt(events.arc)}），算出偏移 ${next >= 0 ? '+' : ''}${next.toFixed(2)} s。确认后点「保存偏移量」。`);
  };
  /** 清除标定（写 `{video: null}`）——让"未标定"状态可达：否则保存过一次 0 之后永远回不去，
   * 而系统会一直声称视频已对齐（`aligned = available && calibrated`）。 */
  const handleClearOffset = () => {
    if (!dataId || versionId == null) {
      setOffsetError('当前数据版本尚未准备好，请稍后重试。');
      return;
    }
    setOffsetError(null);
    setOffsetNotice(null);
    setCalibSaving(true);
    updateCalibration(dataId, String(versionId), { video: null })
      .then((c) => {
        setCalibration(c);
        setVideoOffset(0);
        setVideoOffsetDraft(null);
        setOffsetNotice('已清除视频零点标定：换算回到 offset = 0，且不再声称已对齐。');
      })
      .catch((err) => setOffsetError(`清除标定失败：${err instanceof Error ? err.message : '请重试'}`))
      .finally(() => setCalibSaving(false));
  };
  const tone = inputError || createError || artifactError || jobError || jobStatus === 'failed' ? 'red' : jobStatus === 'running' || jobStatus === 'pending' ? 'orange' : jobStatus === 'succeeded' ? 'green' : 'muted';
  const statusText = inputError ?? createError ?? artifactError ?? (jobError ? '任务状态读取失败' : !inputReady ? '正在读取输入' : jobStatus === 'succeeded' ? '对齐完成' : jobStatus === 'running' ? `处理中 ${progress}%` : jobStatus === 'pending' ? '排队中' : jobStatus === 'failed' ? '执行失败' : '待对齐');
  const done = jobStatus === 'succeeded';
  const running = jobStatus === 'running';
  // 生产时间轴只来自真实输入；没有真实时长时保持不可操作状态。
  const events = alignRes?.events ?? signals?.events ?? null;
  const timelineDur = signals?.duration ?? 0;
  // 条几何用**后端 ffmpeg 探测**的时长（帧时刻由它派生，自洽）；播放器放的是 media_prep 转码
  // 预览件、抽帧用的是原始对象——差一两帧属预期。差得多就如实说一句，别当 bug 修。
  const durationNote = (() => {
    const probe = videoFrames?.duration;
    if (probe == null || videoDuration == null) return null;
    return Math.abs(probe - videoDuration) > 0.5
      ? `探测 ${probe.toFixed(1)}s / 播放器 ${videoDuration.toFixed(1)}s`
      : null;
  })();
  // 反向标定此刻能不能点：不能就把原因交给面板当说明（按钮禁用 + title），而不是点了才报错。
  const reverseHint = !videoUrl ? '视频未加载，无法反向标定'
    : events == null ? '尚无可用的起收弧事件（需真实信号）'
      : videoDuration == null ? '视频元数据未就绪，请稍候'
        : null;
  const trackRows: { channel: string; label: string; tone: string; track?: AlignmentTrack; values?: number[]; lo?: number; hi?: number; color?: string }[] = (() => {
    const rows = !alignRes
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
    if (!dataId) return;
    const root = document.querySelector('.alignment-board');
    if (!root) return;
    const seek = (event: Event) => {
      const target = event.target as HTMLElement;
      // **必须同时排除视频预览轨与胶片条**：前者是播放器（点它是操作播放器），
      // 后者上挂着拖动改 offset——不排除的话点一下胶片条会**既改 offset 又 seek**。
      const surface = target.closest('.studio-ruler, .lane-track:not(.lane-track-video):not(.lane-track-film)');
      if (!surface || timelineDur <= 0) return;
      const rect = surface.getBoundingClientRect();
      const next = Math.min(timelineDur, Math.max(0, ((event as MouseEvent).clientX - rect.left) / Math.max(1, rect.width) * timelineDur));
      setPlayhead(next);
      const video = videoRef.current;
      // 统一坐标：`next` 是**信号时间**，视频轴时刻 = 信号时间 - offset（钳到 0，
      // 该时刻早于视频开头时停在首帧，而不是给 currentTime 一个负值）。
      // 读 ref 而非 state：与 `<video onTimeUpdate>` 的回写成对，且在途草稿也能立即生效。
      if (video) video.currentTime = Math.max(0, next - effectiveOffsetRef.current);
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
    root.querySelectorAll('.studio-ruler, .lane-track:not(.lane-track-video):not(.lane-track-film)').forEach((el) => {
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
    // 依赖里**不含**偏移（读 `effectiveOffsetRef`）——否则每拖一格滑块都会重挂一遍监听器。
    // `alignRes`/`videoUrl` 留下是有意的：新出现的 `.artifact-row` 要补 tabindex/role。
  }, [dataId, timelineDur, videoUrl, alignRes]);
  return <div className="page-wrap"><PageIntro eyebrow="多模态数据生产线" title="多模态对齐" description="将单条焊缝的视频、时序、音频与红外统一到同一时间轴，自动识别起收弧事件并生成对齐版本。" action={<Toolbar secondary="导出标注集" exportType="analysis" />} /><div className="split-source-banner"><div><strong>{record?.weld_id ?? dataId ?? '正在读取焊缝…'}</strong><span>版本 v{versionId ?? '—'} · {record?.source ?? '数据来源读取中'}</span></div><div className="source-status"><span className={signals?.source === 'real' ? 'real' : 'generated'}>{signals?.source === 'real' ? '真实信号' : '真实输入不可用'}</span><span>{videoUrl ? '视频已加载' : '视频未加载'}</span><span>{videoFps ? `视频 ${videoFps} fps` : '视频帧率未知（按帧切分不可用）'}</span><span>{signals ? `${signals.duration.toFixed(2)} 秒 · ${signals.sample_rate} Hz` : '信号加载中…'}</span></div></div><div className="alignment-layout"><section className="panel alignment-board">{alignRes?.version && <div className="alignment-banner ok" role="status"><CheckCircle2 size={15} />已生成「时间对齐」版本 {alignRes.version.version_no}（{alignRes.version.object_keys.length} 个产物 · 事件来源 {alignRes.event_source === 'real' ? '真实信号' : '生成回退'}）</div>}{jobStatus === 'failed' && <div className="alignment-banner bad" role="alert"><AlertTriangle size={15} />对齐任务失败：{errMsg}</div>}<div className="studio-head"><div><span className="file-badge"><Waves size={15} />多模态时间轴</span><h2>熔池视频 / 电流电压 / 音频 / 红外</h2></div><StatusPill tone={tone as 'green' | 'orange' | 'red'}>{statusText}</StatusPill></div><div className="studio-ruler"><div className="ruler-tickbar">{rulerTicks.map((t) => <span key={t} style={{ left: pct(t) }}>{fmt(t)}</span>)}</div><div className="ruler-events">{events && <i className="ruler-arc" style={{ left: pct(events.arc) }} title="起弧" />}{events && <b className="ruler-tail" style={{ left: pct(events.tail) }} title="收弧" />}</div>{playhead > 0 && <span className="ruler-playhead" style={{ left: pct(playhead) }} />}</div><VideoFilmLane frames={videoFrames} loading={framesLoading} videoDuration={videoFrames?.duration ?? videoDuration} timelineDur={timelineDur} offset={effectiveOffset} arcSignal={events?.arc ?? null} tailSignal={events?.tail ?? null} calibrated={calibration?.video.calibrated ?? false} durationNote={durationNote} onDraft={handleOffsetDraft} />{trackRows.map((row) => { const isVideo = row.channel === 'video'; return <div className="lane" key={row.channel}><div className="lane-label"><span className="lane-dot" style={{ background: isVideo ? '#4fa9c2' : (row.color ?? '#2c9caf') }} />{row.label}{row.track && <AvailabilityTag track={row.track} />}</div><div className={`lane-track ${isVideo ? 'lane-track-video' : ''}`}>{isVideo ? (videoUrl ? <video ref={videoRef} className="studio-video" src={videoUrl} controls onLoadedMetadata={(e) => setVideoDuration(Number.isFinite(e.currentTarget.duration) ? e.currentTarget.duration : null)} onDurationChange={(e) => setVideoDuration(Number.isFinite(e.currentTarget.duration) ? e.currentTarget.duration : null)} onTimeUpdate={(e) => { const ct = e.currentTarget.currentTime; setVideoTime(ct); setPlayhead(ct + effectiveOffsetRef.current); }} /> : <div className="lane-video-empty"><Play size={18} /><span>等待真实视频</span></div>) : (row.values && row.values.length > 1 && row.lo != null && row.hi != null && <svg className="lane-wave" viewBox="0 0 100 18" preserveAspectRatio="none"><path d={buildPath(row.values, row.lo, row.hi, 100, 18)} fill="none" stroke={row.color ?? '#2c9caf'} strokeWidth="1.1" vectorEffect="non-scaling-stroke" /></svg>)}{events && <i className="lane-marker" style={{ left: pct(events.arc) }} />}{events && <b className="lane-marker lane-marker-end" style={{ left: pct(events.tail) }} />}{playhead > 0 && <span className="lane-playhead" style={{ left: pct(playhead) }} />}</div></div>; })}<div className="studio-events"><span><i className="studio-evt arc" />起弧 <b>{events ? fmt(events.arc) : '—'}</b></span><span><i className="studio-evt seg" />有效焊接段 <b>{events ? `${fmt(events.weld_segment[0])} – ${fmt(events.weld_segment[1])}` : '—'}</b></span><span><i className="studio-evt tail" />收弧 <b>{events ? fmt(events.tail) : '—'}</b></span><span className="studio-dur">总时长 {fmt(timelineDur)}</span></div></section><aside className="alignment-aside"><OffsetCalibrationPanel calibrated={calibration?.video.calibrated ?? false} savedOffset={videoOffset} draft={videoOffsetDraft} effectiveOffset={effectiveOffset} onDraft={handleOffsetDraft} onReverse={handleReverseOffset} onSave={handleSaveOffset} onClear={handleClearOffset} saving={calibSaving} error={offsetError} notice={offsetNotice} readout={{ signalDuration: timelineDur, videoDuration, videoTime, arcSignal: events?.arc ?? null }} reverseHint={reverseHint} /><section className="panel"><div className="panel-heading"><div><h2>对齐任务</h2><p>选择要纳入对齐的模态</p></div><Waves size={17} /></div><div className="modal-checklist">{modalOptions.map((m) => <label className="modal-check" key={m.id}><input type="checkbox" checked={modalities.includes(m.id)} onChange={(e) => { setModalities((prev) => (e.target.checked ? [...prev, m.id] : prev.filter((x) => x !== m.id))); }} /><span className="modal-check-box">{m.icon}</span><b>{m.label}</b><small>{m.desc}</small></label>)}</div><div className="split-estimate studio-estimate"><strong>{modalities.length}</strong><span>种模态纳入对齐</span><small>{signals?.source === 'real' ? '真实信号' : '真实输入不可用'} · 起收弧事件将自动识别</small></div><button className="full-button" onClick={handleRun} disabled={running || !dataId || versionId == null || modalities.length === 0}>{done ? <><Check size={16} />已完成对齐</> : running ? <><Activity size={16} />对齐处理中 {progress}%</> : <><Waves size={16} />开始多模态对齐</>}</button>{done && <button className="full-button studio-reset" onClick={() => setJobId(null)}><RefreshCw size={15} />重新对齐</button>}</section>{alignRes && <section className="panel"><div className="panel-heading"><div><h2>对齐产物</h2><p>写入「时间对齐」版本</p></div><FileText size={17} /></div><div className="artifact-list">{alignRes.assets.map((a, i) => <div className="artifact-row" key={`${a}-${i}`}><span className="artifact-icon">{a.toLowerCase().endsWith('.csv') ? <BarChart3 size={13} /> : a.toLowerCase().endsWith('.jpg') ? <ImageIcon size={13} /> : <FileText size={13} />}</span><div><strong>{a.split('/').pop()}</strong><small>{a}</small></div></div>)}</div></section>}</aside></div><SeamRoiEditor calibration={calibration} imageUrl={seamImageUrl} imageError={seamImageError} loading={calibLoading} saving={calibSaving} error={calibError} onSave={handleSaveRoi} /></div>;
}


