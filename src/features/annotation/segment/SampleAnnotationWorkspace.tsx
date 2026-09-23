/**
 * 分段样本标注工作台（段级分类，2026-09-22；**2026-09-23 改为总览打标流**）。
 *
 * 一期范围没变：一个标注对象就是一个 `Sample`（一个时间窗），每窗只有**一个主结论**
 * （`normal` / `defect` + 主缺陷类别），不做框 / 点 / 掩膜，也不做两级精度。
 *
 * **改的是"怎么看、怎么标"**。旧版是"左列表选一段 → 右栏看一段 → 表单标一段"，屏幕上永远
 * 只有一段。现在是一条**整条焊缝的统一时间轴**，纵向叠：4 条信号泳道 → 焊缝图片带 →
 * 视频帧胶片条 → 标注行，窗口竖线贯穿全部泳道，结论直接落在窗口列上。这与分段页
 * （`features/alignment/split`）是同一个视觉母题，用的是同一份服务端时间轴。
 *
 * 三条关键约定（前两条是设计文档 §4 的硬约束，第三条是本次新增的口径）：
 * - 三模态**共用同一个 `Sample` 时间窗**：屏幕上不存在"各模态各自的时间轴"，窗口起止一律
 *   取服务端的 `start_time`/`end_time`。
 * - 模态缺失（未标定 / 无视频 / 图片不可用）**如实显示原因，不阻断标注**。
 * - **全量的是索引，不是媒体**：窗口索引、标注态、媒体地址由 `annotation-timeline` 一次给全
 *   （几百段的元信息很轻），但**只有当前批次的图会挂 `<img>`**（`loading="lazy"`），
 *   批次之外不渲染任何切片——这才对得起"不把整个任务的切片灌进前端"那条约束。
 *
 * 为什么按批横铺而不是一屏铺满：一条焊缝 90~200 段，全铺时每格只有十几像素、看不见帧图。
 * 所以顶部留一条**全局条**（每窗一格色块，看进度与缺陷分布、点击跳批），下面是当前批次
 * 20 段的宽时间轴（每格 ~65px，看得清图），打标在批次里做。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ChevronLeft, ChevronRight, Crosshair, Undo2 } from 'lucide-react';
import { getSplitSample } from '../../../api/analysis';
import { ApiError } from '../../../api/client';
import { getFileUrl } from '../../../api/files';
import {
  clearSegmentAnnotation, getAnnotationTimeline, getSegmentAnnotation,
  listAnnotatableTasks, listSegmentCategories, saveSegmentAnnotation,
} from '../../../api/sampleAnnotations';
import type {
  AnnotationTimeline, AnnotationTimelineWindow, SampleAnnotation, SegmentAnnotatableTask,
  SegmentCategory, SplitSampleDetail, SplitTimelineTrack,
} from '../../../api/types';
import { SignalTimelineLane } from '../../alignment/split/SignalTimelineLane';
import { fmtRange, pctOf } from '../../alignment/split/splitTypes';
import { PageIntro } from '../../../shared/components/PageIntro';
import { StatusPill } from '../../../shared/components/StatusPill';
import { AnnotationRail, EmptyRail, type VerdictDraft } from './AnnotationRail';

/** 空结论草稿（默认"正常"，类别必须为空——切到正常要清掉残影）。 */
const emptyDraft = (): VerdictDraft => ({ label: 'normal', categoryId: null, note: '' });

/** 一批铺多少段。一屏可用宽度 ~1300px → 每格 ~65px，够看清帧图和焊缝切片；
 *  再密就看不清图，再疏则一屏装不下上下文。 */
const BATCH_SIZE = 20;
const RULER_TICKS = 8;

type Tone = 'ok' | 'bad' | 'none';

/** 焊缝图片带在服务端的模态可用性（`timeline` 缺失时整条轨道也走空态）。 */
type SeamProjection = NonNullable<AnnotationTimeline['timeline']>['seam_image_projection'];

const errorText = (err: unknown, fallback: string): string =>
  err instanceof ApiError && err.message ? err.message
    : err instanceof Error && err.message ? err.message : fallback;

const toneOf = (row: AnnotationTimelineWindow): Tone =>
  row.annotated ? (row.label === 'defect' ? 'bad' : 'ok') : 'none';

const markText = (row: AnnotationTimelineWindow): string =>
  !row.annotated ? '未标注'
    : row.label === 'defect' ? (row.defect_category_name || '缺陷') : '正常';

/**
 * 把整条焊缝的降采样轨道裁到当前批次，并把时间轴原点移到批次起点（`x = t − from`）。
 *
 * **必须裁**：`timePath` 会把越界时刻钳到 `[0, duration]`，不裁的话整条焊缝的其它点全被
 * 压到批次左右边缘上，画出一条假的水平线。裁出来正好一段。
 */
function clipTrack(track: SplitTimelineTrack, from: number, to: number): SplitTimelineTrack {
  const times: number[] = [];
  const values: number[] = [];
  for (let i = 0; i < track.times.length && i < track.values.length; i += 1) {
    const t = track.times[i];
    if (t >= from && t <= to) {
      times.push(t - from);
      values.push(track.values[i]);
    }
  }
  return { ...track, times, values };
}

export function SampleAnnotationWorkspace({ dataId }: { dataId?: string }) {
  const [tasks, setTasks] = useState<SegmentAnnotatableTask[]>([]);
  const [tasksLoading, setTasksLoading] = useState(true);
  const [tasksError, setTasksError] = useState<string | null>(null);
  const [taskId, setTaskId] = useState<string | null>(null);

  const [timeline, setTimeline] = useState<AnnotationTimeline | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [categories, setCategories] = useState<SegmentCategory[]>([]);

  /** 选中的窗口是**唯一的导航源头**：所在批次由它在列表里的下标反推（见 `batchIndex`）。
   *  这样翻批、点全局条、按 ←/→ 都只是"改选中项"，不存在两个状态要对齐的问题。 */
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<SplitSampleDetail | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [annotation, setAnnotation] = useState<SampleAnnotation | null>(null);
  const [draft, setDraft] = useState<VerdictDraft>(emptyDraft);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<{ tone: 'ok' | 'error'; text: string } | null>(null);
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const [videoFailed, setVideoFailed] = useState(false);
  const videoRef = useRef<HTMLVideoElement>(null);

  // ── 入口：该焊缝已完成的分段任务 ────────────────────────────────────
  useEffect(() => {
    if (!dataId) return;
    let cancelled = false;
    setTasksLoading(true);
    setTasksError(null);
    listAnnotatableTasks(dataId)
      .then((items) => { if (!cancelled) setTasks(items); })
      .catch((err) => { if (!cancelled) setTasksError(errorText(err, '分段任务列表读取失败')); })
      .finally(() => { if (!cancelled) setTasksLoading(false); });
    return () => { cancelled = true; };
  }, [dataId]);

  // 词表：含停用项——历史标注可能引用了后来被停用的类别，要能显示而不是空候选
  useEffect(() => {
    listSegmentCategories(true).then(setCategories).catch(() => setCategories([]));
  }, []);

  // ── 总览时间轴：一次拿全窗口 + 标注态 + 媒体地址 ────────────────────
  const loadTimeline = useCallback(async (target: string) => {
    setLoading(true);
    setLoadError(null);
    try {
      const data = await getAnnotationTimeline(target);
      setTimeline(data);
      setSelectedId(data.windows[0]?.sample_id ?? null);
    } catch (err) {
      setTimeline(null);
      setSelectedId(null);
      setLoadError(errorText(err, '标注时间轴读取失败'));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!taskId) return;
    void loadTimeline(taskId);
  }, [taskId, loadTimeline]);

  // ── 选中窗口的细节与本窗结论 ────────────────────────────────────────
  const current = useMemo(
    () => timeline?.windows.find((row) => row.sample_id === selectedId) ?? null,
    [timeline, selectedId],
  );

  useEffect(() => {
    if (!taskId || selectedId == null) {
      setDetail(null);
      setAnnotation(null);
      setDetailError(null);
      return;
    }
    let cancelled = false;
    setDetail(null);
    setDetailError(null);
    setNotice(null);
    Promise.all([getSplitSample(taskId, selectedId), getSegmentAnnotation(taskId, selectedId)])
      .then(([sample, existing]) => {
        if (cancelled) return;
        setDetail(sample);
        setAnnotation(existing.annotation);
        setDraft(existing.annotation
          ? {
              label: existing.annotation.label,
              categoryId: existing.annotation.defect_category_id,
              note: existing.annotation.note ?? '',
            }
          : emptyDraft());
      })
      .catch((err) => { if (!cancelled) setDetailError(errorText(err, '窗口细节读取失败')); });
    return () => { cancelled = true; };
  }, [taskId, selectedId]);

  // 视频对象：本窗 manifest 里那个键换签名 URL（图片直接用时间轴给的那两份，不重复签）
  const videoKey = useMemo(() => {
    const meta = (detail?.meta?.video ?? null) as { object_key?: string } | null;
    return typeof meta?.object_key === 'string' ? meta.object_key : null;
  }, [detail]);

  useEffect(() => {
    setVideoFailed(false);
    if (!videoKey) { setVideoUrl(null); return; }
    let cancelled = false;
    getFileUrl(videoKey)
      .then((res) => { if (!cancelled) setVideoUrl(res.url); })
      .catch(() => { if (!cancelled) setVideoUrl(null); });
    return () => { cancelled = true; };
  }, [videoKey]);

  // 换窗口 → 播放器定位到本窗的视频轴起点（`t_video = t_signal − offset`）。
  // offset 来自时间轴的模态槽（服务端已从标定算出），未标定即 0。
  useEffect(() => {
    const video = videoRef.current;
    if (!video || current?.start == null) return;
    const offset = typeof current.video.offset_seconds === 'number' ? current.video.offset_seconds : 0;
    video.currentTime = Math.max(0, current.start - offset);
  }, [current, videoUrl]);

  // ── 批次（由选中项反推） ───────────────────────────────────────────
  const windows = useMemo(() => timeline?.windows ?? [], [timeline]);
  const batchCount = Math.max(1, Math.ceil(windows.length / BATCH_SIZE));
  const selectedIndex = windows.findIndex((row) => row.sample_id === selectedId);
  const batchIndex = selectedIndex >= 0 ? Math.floor(selectedIndex / BATCH_SIZE) : 0;
  const batch = windows.slice(batchIndex * BATCH_SIZE, (batchIndex + 1) * BATCH_SIZE);
  const batchFrom = batch[0]?.start ?? 0;
  const batchTo = batch[batch.length - 1]?.end ?? batchFrom;
  const batchDuration = Math.max(batchTo - batchFrom, 1e-6);

  const selectAt = useCallback((index: number) => {
    if (index < 0 || index >= windows.length) return;
    setSelectedId(windows[index].sample_id);
  }, [windows]);

  const step = (delta: number) => selectAt(selectedIndex >= 0 ? selectedIndex + delta : 0);
  const goBatch = (delta: number) => selectAt((batchIndex + delta) * BATCH_SIZE);

  /** 跳到下一处未标注（到末尾回卷）。取代旧版的「只看未标注」筛选——总览已经把
   *  标注态铺在屏幕上了，再叠一个会改变批次数量的筛选只会让"第几批"变得没法说清。 */
  const jumpUnannotated = () => {
    if (!windows.length) return;
    const start = selectedIndex < 0 ? -1 : selectedIndex;
    for (let i = 1; i <= windows.length; i += 1) {
      const index = (start + i) % windows.length;
      if (!windows[index].annotated) { selectAt(index); return; }
    }
    setNotice({ tone: 'ok', text: '该分段任务已全部标注完成' });
  };

  // ── 保存 / 撤销：原地改那一列，不重拉整个时间轴 ────────────────────
  const patchWindow = (sampleId: number, next: Partial<AnnotationTimelineWindow>) => {
    setTimeline((prev) => prev && {
      ...prev,
      windows: prev.windows.map((row) => (row.sample_id === sampleId ? { ...row, ...next } : row)),
    });
  };

  /** 保存。`override` 给快捷键用——`N` 要"此刻就按正常提交"，不能等 `setDraft` 落地。 */
  const submit = async (advance: boolean, override?: VerdictDraft) => {
    if (!taskId || !current || busy) return;
    const verdict = override ?? draft;
    setBusy(true);
    setNotice(null);
    // "下一段"用**保存前**的下标算：保存后这一列的 `annotated` 就变了，
    // 而"总览已把全部窗口拿在手里"，所以下标是稳定的。
    const nextIndex = selectedIndex + 1;
    try {
      const res = await saveSegmentAnnotation(taskId, current.sample_id, {
        label: verdict.label,
        defect_category_id: verdict.label === 'defect' ? verdict.categoryId : null,
        note: verdict.note.trim() ? verdict.note.trim() : null,
      });
      patchWindow(current.sample_id, {
        annotated: true,
        label: verdict.label,
        defect_category_name: verdict.label === 'defect'
          ? (res.annotation?.defect_category_name ?? null) : null,
        note: verdict.note.trim() ? verdict.note.trim() : null,
      });
      setAnnotation(res.annotation);
      setTimeline((prev) => prev && { ...prev, progress: res.progress });
      setNotice({ tone: 'ok', text: '已保存' });
      if (advance) selectAt(nextIndex);
    } catch (err) {
      setNotice({ tone: 'error', text: errorText(err, '保存失败，请重试') });
    } finally {
      setBusy(false);
    }
  };

  const removeAnnotation = async () => {
    if (!taskId || !current || busy) return;
    setBusy(true);
    setNotice(null);
    try {
      const res = await clearSegmentAnnotation(taskId, current.sample_id);
      patchWindow(current.sample_id, {
        annotated: false, label: null, defect_category_name: null, note: null,
      });
      setAnnotation(null);
      setDraft(emptyDraft());
      setTimeline((prev) => prev && { ...prev, progress: res.progress });
      setNotice({ tone: 'ok', text: '已撤销该段标注' });
    } catch (err) {
      setNotice({ tone: 'error', text: errorText(err, '撤销失败，请重试') });
    } finally {
      setBusy(false);
    }
  };

  // ── 快捷键：←/→ 换窗口、N 标正常、D 进缺陷态 ───────────────────────
  // 只在**文本输入控件**里放行（那些键在那儿有自己的含义）。
  // **按钮不算**：点窗口列后焦点就落在那个按钮上，把按钮也排除掉的话"点一格再按 N"这条
  // 最顺手的路径会当场失效。我们绑的四个键在按钮上没有默认行为，不会误触。
  const submitRef = useRef(submit);
  submitRef.current = submit;
  useEffect(() => {
    if (!timeline) return;
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target && target.closest('input, textarea, select, [contenteditable="true"]')) return;
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      if (event.key === 'ArrowLeft') { event.preventDefault(); step(-1); return; }
      if (event.key === 'ArrowRight') { event.preventDefault(); step(1); return; }
      if (event.key === 'n' || event.key === 'N') {
        const next: VerdictDraft = { label: 'normal', categoryId: null, note: draft.note };
        setDraft(next);
        // 用**这一份**直接提交，不等 setDraft 落地（否则打的是上一份结论）
        void submitRef.current(true, next);
        return;
      }
      if (event.key === 'd' || event.key === 'D') setDraft((prev) => ({ ...prev, label: 'defect' }));
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  });

  // ── 渲染 ───────────────────────────────────────────────────────────
  if (!dataId) {
    return <p className="dataset-empty-state" role="status">请先在「选择数据」中选定一条焊缝。</p>;
  }

  if (!taskId) {
    return (
      <>
        <PageIntro
          eyebrow="多模态数据生产线"
          title="分段样本标注"
          description="从该焊缝**已完成**的分段任务进入：每段一个主结论（正常 / 缺陷 + 主缺陷类别），时序、视频、焊缝图片共用同一个时间窗。"
        />
        <section className="panel">
          <div className="studio-head">
            <div><span className="file-badge">可标注的分段任务</span><h2>{dataId}</h2></div>
            {tasks.length > 0 && <span className="studio-dur">{tasks.length} 个任务</span>}
          </div>
          {tasksLoading && <p className="dataset-empty-state" role="status">分段任务加载中…</p>}
          {tasksError && <p className="toolbar-error" role="alert">{tasksError}</p>}
          {!tasksLoading && !tasksError && tasks.length === 0 && (
            <p className="dataset-empty-state" role="status">
              该焊缝还没有已完成的分段任务。请先在「样本分段」页按秒级规则生成多模态样本，
              任务成功后再回到这里做段级标注。
            </p>
          )}
          {tasks.length > 0 && (
            <div className="segment-task-list">
              {tasks.map((task) => (
                <button key={task.task_id} className="segment-task-card" onClick={() => setTaskId(task.task_id)}>
                  <div>
                    <strong>{task.task_id}</strong>
                    <small>
                      {task.version_no} · {task.sample_count} 段 · 窗口 {task.window_seconds ?? '—'}s / 步长 {task.stride_seconds ?? '—'}s
                      {task.effective_range ? ` · 有效 ${fmtRange(task.effective_range[0], task.effective_range[1])}` : ''}
                    </small>
                  </div>
                  <div className="segment-task-progress">
                    <span>{task.progress.annotated}/{task.progress.total}</span>
                    <StatusPill tone={task.progress.progress >= 100 ? 'green' : task.progress.annotated > 0 ? 'orange' : 'muted'}>
                      {task.progress.progress >= 100 ? '已完成' : `${task.progress.progress}%`}
                    </StatusPill>
                  </div>
                </button>
              ))}
            </div>
          )}
        </section>
      </>
    );
  }

  const progress = timeline?.progress ?? null;
  const tracks = timeline?.timeline?.signal.tracks ?? [];
  // 全局条的横轴是**整条焊缝**：格宽 = 该段时长 / 焊缝总时长。总时长优先用服务端给的
  // `timeline.duration`，波形读不回来时退到"首窗起点 → 末窗终点"（总览不该因为没波形而消失）。
  const weldFrom = windows[0]?.start ?? 0;
  const weldTo = windows[windows.length - 1]?.end ?? weldFrom;
  const weldDuration = timeline?.timeline?.duration ?? Math.max(weldTo - weldFrom, 1e-6);
  const boundaries = batch.map((row) => (row.start ?? 0) - batchFrom);
  if (batch.length) boundaries.push(batchTo - batchFrom);

  return (
    <>
      <PageIntro
        eyebrow="多模态数据生产线"
        title="分段样本标注"
        description="整条焊缝一条时间轴：四面信号、焊缝图片、视频帧按同一个时间窗上下对齐，结论直接标在窗口列上。"
        action={<button className="outline-button" onClick={() => setTaskId(null)}><Undo2 size={14} />换个分段任务</button>}
      />

      {notice && (
        <p className={notice.tone === 'error' ? 'toolbar-error settings-notice' : 'accent-text settings-notice'}
           role={notice.tone === 'error' ? 'alert' : 'status'}>{notice.text}</p>
      )}
      {loadError && <p className="toolbar-error settings-notice" role="alert">{loadError}</p>}
      {timeline?.warnings.map((text) => (
        <p key={text} className="toolbar-error settings-notice" role="status">{text}</p>
      ))}
      {loading && <p className="dataset-empty-state" role="status">标注时间轴加载中…</p>}

      {timeline && (
        <>
          {/* 全局条：整条焊缝一窗一格，看进度与缺陷分布；点一格跳到它所在的批次 */}
          <section className="panel annot-overview">
            <div className="annot-overview-head">
              <span className="file-badge">整条焊缝</span>
              <span className="studio-dur">{windows.length} 段 · 已标 {progress?.annotated ?? 0} · 未标 {progress?.unannotated ?? 0}</span>
            </div>
            <div className="annot-strip" role="list" aria-label="整条焊缝窗口总览">
              {windows.map((row) => (
                <button
                  type="button"
                  key={row.sample_id}
                  role="listitem"
                  className={`annot-strip-cell ${toneOf(row)}${row.sample_id === selectedId ? ' is-current' : ''}`}
                  style={{ width: `${Math.max(pctOf((row.end ?? 0) - (row.start ?? 0), weldDuration), 0.4)}%` }}
                  title={`#${row.index ?? '—'} ${fmtRange(row.start ?? 0, row.end ?? 0)} · ${markText(row)}`}
                  aria-label={`跳转到窗口 ${row.index ?? ''}（${markText(row)}）`}
                  onClick={() => setSelectedId(row.sample_id)}
                />
              ))}
            </div>
            <div className="annot-overview-foot">
              <span>红=缺陷 · 绿=正常 · 灰=未标注（格宽即该段时长）</span>
              {progress && progress.defect_distribution.length > 0 && (
                <span className="annot-defect-summary">
                  {progress.defect_distribution.map((item) => <em key={item.name}>{item.name} {item.count}</em>)}
                </span>
              )}
            </div>
          </section>

          <div className="annot-layout">
            <section className="panel annot-timeline">
              <div className="annot-batch-bar">
                <div>
                  <span className="file-badge">本批次</span>
                  <b className="annot-batch-range">
                    {batch.length ? `#${batch[0].index ?? '—'}–#${batch[batch.length - 1].index ?? '—'}` : '—'}
                  </b>
                  <small>第 {batchIndex + 1}/{batchCount} 批 · {fmtRange(batchFrom, batchTo)}</small>
                </div>
                <div className="annot-batch-actions">
                  <button className="ghost-button" disabled={batchIndex <= 0} onClick={() => goBatch(-1)}>
                    <ChevronLeft size={14} />上一批
                  </button>
                  <button className="ghost-button" disabled={batchIndex >= batchCount - 1} onClick={() => goBatch(1)}>
                    下一批<ChevronRight size={14} />
                  </button>
                  <button className="outline-button" onClick={jumpUnannotated}>
                    <Crosshair size={14} />下一处未标注
                  </button>
                </div>
              </div>

              <div className="studio-ruler">
                <div className="ruler-tickbar">
                  {Array.from({ length: RULER_TICKS + 1 }, (_, i) => {
                    const t = (batchDuration * i) / RULER_TICKS;
                    return <span key={i} style={{ left: `${pctOf(t, batchDuration)}%` }}>{(t + batchFrom).toFixed(1)}</span>;
                  })}
                </div>
              </div>

              {/* ① 信号泳道：整条焊缝的降采样轨道按批次裁出来，按真实秒坐标画 */}
              <SignalTimelineLane
                tracks={tracks.map((track) => clipTrack(track, batchFrom, batchTo))}
                duration={batchDuration}
                boundaries={boundaries}
                selected={current?.start != null && current.end != null
                  ? { start: current.start - batchFrom, end: current.end - batchFrom } : null}
              />

              {/* ② 焊缝图片带：每格是本窗自己的 ROI 投影切片（分段任务的落盘产物） */}
              <FilmLane
                title="焊缝图片"
                dot="#c08a4e"
                cells={batch.map((row) => ({
                  row,
                  url: row.crop_url,
                  reason: row.seam_image.reason ?? '该窗没有焊缝图片切片（图片是增强模态，缺失不影响标注）',
                }))}
                availability={timeline.timeline?.seam_image_projection ?? null}
                duration={batchDuration}
                from={batchFrom}
                selectedId={selectedId}
                onSelect={setSelectedId}
              />

              {/* ③ 视频帧轨：每格是本窗自己的代表帧 */}
              <FilmLane
                title="视频帧"
                dot="#2c9caf"
                cells={batch.map((row) => ({
                  row,
                  url: row.frame_url,
                  reason: row.video.reason ?? '该窗没有视频代表帧',
                }))}
                availability={null}
                duration={batchDuration}
                from={batchFrom}
                selectedId={selectedId}
                onSelect={setSelectedId}
              />

              {/* ④ 标注行：结论落在窗口列上。这条**永远在**——标注态不属于任何一个模态。 */}
              <div className="lane annot-mark-lane">
                <div className="lane-label">
                  <i className="lane-dot" style={{ background: '#6f9c7f' }} />
                  标注
                  <span className="lane-meta">{batch.filter((row) => row.annotated).length}/{batch.length}</span>
                </div>
                <div className="lane-track annot-mark-row">
                  {batch.map((row) => (
                    <button
                      type="button"
                      key={row.sample_id}
                      className={`annot-mark ${toneOf(row)}${row.sample_id === selectedId ? ' is-selected' : ''}`}
                      style={{
                        left: `${pctOf((row.start ?? 0) - batchFrom, batchDuration)}%`,
                        width: `${Math.max(0, pctOf((row.end ?? 0) - batchFrom, batchDuration) - pctOf((row.start ?? 0) - batchFrom, batchDuration))}%`,
                      }}
                      title={`#${row.index ?? '—'} ${fmtRange(row.start ?? 0, row.end ?? 0)} · ${markText(row)}`}
                      aria-label={`窗口 #${row.index ?? '—'}（${markText(row)}）`}
                      aria-pressed={row.sample_id === selectedId}
                      onClick={() => setSelectedId(row.sample_id)}
                    >
                      <b>{row.annotated ? (row.label === 'defect' ? '✗' : '✓') : '·'}</b>
                      {row.annotated && <em>{markText(row)}</em>}
                    </button>
                  ))}
                </div>
              </div>

              <small className="lane-note">
                一格 = 一个时间窗（该段的时长决定格宽），窗口竖线贯穿所有泳道；
                点任意一格选中该窗，右栏给出结论表单与其三模态细节。
              </small>
            </section>

            {current
              ? (
                <AnnotationRail
                  window={current}
                  detail={detail}
                  detailError={detailError}
                  videoUrl={videoUrl}
                  videoFailed={videoFailed}
                  onVideoFailed={() => setVideoFailed(true)}
                  videoRef={videoRef}
                  categories={categories}
                  annotation={annotation}
                  draft={draft}
                  onDraft={(patch) => setDraft((prev) => ({ ...prev, ...patch }))}
                  busy={busy}
                  onSave={(advance) => void submit(advance)}
                  onClear={() => void removeAnnotation()}
                />
              )
              : <EmptyRail />}
          </div>
        </>
      )}
    </>
  );
}

/**
 * 标注页的胶片轨：**一段一格**，格宽 = 该段在批次时间轴上的占比，格内是本段自己的图。
 *
 * 与分段页的 `VideoTimelineLane` 是同一个视觉母题，但**刻意没有合并成一个组件**：
 * 那条轨格内只有图和"无帧"的原因，且被 `App.split-lanes-regression.test.mjs` 逐条钉着；
 * 这条轨要额外承载**该段的标注态着色**（`normal`/`defect`/`none`），还要给图片轨与视频轨
 * 各渲染一份。合并的代价是给那条轨加一堆可选 props，再加一层把 `AnnotationTimelineWindow`
 * 伪装成 `SplitPreviewWindow` 的适配层——那个适配层是在骗人。宁可多这几十行。
 */
function FilmLane({
  title, dot, cells, availability, duration, from, selectedId, onSelect,
}: {
  title: string;
  dot: string;
  cells: { row: AnnotationTimelineWindow; url: string | null; reason: string }[];
  /** 焊缝图片带的模态可用性（无图片 / 已选择不参与 / 未标定 ROI → 整条轨走空态）。 */
  availability: SeamProjection | null;
  duration: number;
  from: number;
  selectedId: number | null;
  onSelect: (sampleId: number) => void;
}) {
  const ready = cells.some((cell) => cell.url);
  const emptyText = availability && !availability.available
    ? (availability.excluded
        ? `已选择不对焊缝图片进行分段：${availability.reason ?? '本轮只生成时序 / 视频样本'}`
        : (availability.reason ?? '焊缝图片在本轮分段中不可用'))
    : `本批次没有${title}缩略图`;
  return (
    <div className="lane">
      <div className="lane-label">
        <i className="lane-dot" style={{ background: dot }} />
        {title}
        {!ready && <span className="track-availability warn">无图</span>}
      </div>
      <div className="lane-track lane-track-film">
        {ready ? cells.map(({ row, url, reason }) => {
          const left = pctOf((row.start ?? 0) - from, duration);
          const width = Math.max(0, pctOf((row.end ?? 0) - from, duration) - left);
          return (
            <button
              type="button"
              key={row.sample_id}
              className={`film-cell ${toneOf(row)}${row.sample_id === selectedId ? ' is-selected' : ''}`}
              style={{ left: `${left}%`, width: `${width}%` }}
              title={url ? `#${row.index ?? '—'} 的${title}` : `#${row.index ?? '—'} 无图：${reason}`}
              aria-label={`选择窗口 #${row.index ?? ''}`}
              aria-pressed={row.sample_id === selectedId}
              onClick={() => onSelect(row.sample_id)}
            >
              {url ? <img src={url} alt={`窗口 #${row.index ?? ''} 的${title}`} loading="lazy" />
                : <span className="film-cell-empty" aria-hidden>无图</span>}
            </button>
          );
        }) : (
          <div className="lane-video-empty"><span>{emptyText}</span></div>
        )}
      </div>
    </div>
  );
}
