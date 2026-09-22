/**
 * 分段样本标注工作台（段级分类，2026-09-22）。
 *
 * 一期范围：**只面向已完成且 `rules_version=3` 的分段任务**。一个标注对象就是一个
 * `Sample`（一个时间窗），每段只有**一个主结论**：`normal` / `defect`（+ 主缺陷类别）。
 * 不做框、点、掩膜，也不做两级精度——旧的 `analysis/annotation` 页仍负责那套几何标注。
 *
 * 关键约定：
 * - 三个模态（时序 / 视频 / 焊缝图片）**共用同一个 Sample 的时间窗**：屏幕上不存在"各模态
 *   各自的时间轴"，窗口起止一律取 `sample.start_time`/`end_time`（服务端切分时定下）。
 * - 样本列表**分页拉取**（每页 50），上一段/下一段在页边界自动翻页——不把整个任务的
 *   切片灌进一次响应，也不在前端缓存全量。
 * - 模态缺失（未标定 / 无视频 / 图片不可用）**如实显示原因，不阻断标注**：缺陷结论来自
 *   人工判断，不依赖某个模态是否可用。
 * - 词表（主缺陷类别）的增删改在「系统设置 → 分段样本缺陷词表」，这里只读；历史标注显示的是
 *   **写入当时的名称快照**，不回查词表去"修正"。
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { AlertTriangle, CheckCircle2, ChevronLeft, ChevronRight, Save, Trash2, Undo2 } from 'lucide-react';
import { getSplitSample } from '../../../api/analysis';
import { ApiError } from '../../../api/client';
import { getFileUrl } from '../../../api/files';
import {
  clearSegmentAnnotation, getSegmentAnnotation, listAnnotatableTasks, listSegmentCategories,
  listSegmentSamples, saveSegmentAnnotation,
} from '../../../api/sampleAnnotations';
import type {
  SampleAnnotation, SegmentAnnotatableTask, SegmentCategory, SegmentLabel,
  SegmentProgress, SegmentSampleRow, SplitSampleDetail,
} from '../../../api/types';
import { chanColorOf } from '../../analysis/signals/chartData';
import { fmtRange, timePath, trackRange } from '../../alignment/split/splitTypes';
import { PageIntro } from '../../../shared/components/PageIntro';
import { StatusPill } from '../../../shared/components/StatusPill';

/** 列表分页大小（服务端上限 200；50 足够列表可视高度，翻页由"上一段/下一段"自动触发）。 */
const PAGE_SIZE = 50;
/** 时序轨道的局部波形点数上限（详情端点已降采样到 ≤600，这里只做像素级抽稀）。 */
const WAVE_POINTS = 400;

const errorText = (err: unknown, fallback: string): string =>
  err instanceof ApiError && err.message ? err.message
    : err instanceof Error && err.message ? err.message : fallback;

const labelText = (row: { label: SegmentLabel | null; defect_category_name: string | null }): string =>
  row.label === 'defect' ? (row.defect_category_name || '缺陷')
    : row.label === 'normal' ? '正常' : '未标注';

/** 详情 `meta` 的模态块（服务端 manifest 的原始形状，只取用到的字段）。 */
interface ModalityMeta {
  available?: boolean;
  calibrated?: boolean;
  reason?: string | null;
  object_key?: string | null;
  crop_key?: string | null;
  fps?: number;
  offset_seconds?: number;
  start_frame?: number;
  end_frame?: number;
  keyframes?: { at: number }[];
  spatial_range?: { start_px: number; end_px: number };
  roi?: { x: number; y: number; w: number; h: number };
}

export function SampleAnnotationWorkspace({ dataId }: { dataId?: string }) {
  const [tasks, setTasks] = useState<SegmentAnnotatableTask[]>([]);
  const [tasksLoading, setTasksLoading] = useState(true);
  const [tasksError, setTasksError] = useState<string | null>(null);
  const [taskId, setTaskId] = useState<string | null>(null);

  const [categories, setCategories] = useState<SegmentCategory[]>([]);
  const [filter, setFilter] = useState<'all' | 'unannotated'>('all');
  const [page, setPage] = useState(1);
  const [rows, setRows] = useState<SegmentSampleRow[]>([]);
  const [total, setTotal] = useState(0);
  const [progress, setProgress] = useState<SegmentProgress | null>(null);
  const [currentId, setCurrentId] = useState<number | null>(null);
  const [detail, setDetail] = useState<SplitSampleDetail | null>(null);
  const [annotation, setAnnotation] = useState<SampleAnnotation | null>(null);
  const [draft, setDraft] = useState<{ label: SegmentLabel; categoryId: number | null; note: string }>(
    { label: 'normal', categoryId: null, note: '' },
  );
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [listError, setListError] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ tone: 'ok' | 'error'; text: string } | null>(null);
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const [videoFailed, setVideoFailed] = useState(false);
  const [cropUrl, setCropUrl] = useState<string | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  /** 翻页后要自动选中的位置（`'first'` / `'last'`）；行数据到达后由下面的效果消费。 */
  const pendingSelectRef = useRef<'first' | 'last' | null>(null);

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
    listSegmentCategories(true)
      .then(setCategories)
      .catch(() => setCategories([]));
  }, []);

  // ── 样本列表（分页） ───────────────────────────────────────────────
  const loadPage = useCallback(async (target: string, nextFilter: 'all' | 'unannotated', nextPage: number) => {
    setLoading(true);
    setListError(null);
    try {
      const data = await listSegmentSamples(target, {
        page: nextPage,
        page_size: PAGE_SIZE,
        filter: nextFilter,
      });
      setRows(data.items);
      setTotal(data.total);
      setProgress(data.progress);
      return data;
    } catch (err) {
      setRows([]);
      setTotal(0);
      setListError(errorText(err, '样本列表读取失败'));
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!taskId) return;
    let cancelled = false;
    // 注意：**不要**在这里清 `pendingSelectRef`——翻页正是靠它把选中项带到新页；
    // 它由下面的 `[rows]` 效果消费后自清，悬空时也只会多选一次首/末行。
    loadPage(taskId, filter, page).then((data) => {
      if (cancelled || !data) return;
      setCurrentId((prev) => {
        if (prev != null && data.items.some((row) => row.id === prev)) return prev;
        return data.items[0]?.id ?? null;
      });
    });
    return () => { cancelled = true; };
  }, [taskId, filter, page, loadPage]);

  // 翻页后选中新页的首/末行（上一段/下一段走到页边界时触发）
  useEffect(() => {
    const pending = pendingSelectRef.current;
    if (!pending || !rows.length) return;
    pendingSelectRef.current = null;
    setCurrentId(pending === 'first' ? rows[0].id : rows[rows.length - 1].id);
  }, [rows]);

  // ── 单样本：结论 + 三模态细节（同一个时间窗） ──────────────────────
  useEffect(() => {
    if (!taskId || currentId == null) {
      setDetail(null);
      setAnnotation(null);
      return;
    }
    let cancelled = false;
    setDetail(null);
    setNotice(null);
    Promise.all([getSplitSample(taskId, currentId), getSegmentAnnotation(taskId, currentId)])
      .then(([sample, current]) => {
        if (cancelled) return;
        setDetail(sample);
        setAnnotation(current.annotation);
        setDraft(current.annotation
          ? {
              label: current.annotation.label,
              categoryId: current.annotation.defect_category_id,
              note: current.annotation.note ?? '',
            }
          : { label: 'normal', categoryId: null, note: '' });
      })
      .catch((err) => { if (!cancelled) setListError(errorText(err, '样本详情读取失败')); });
    return () => { cancelled = true; };
  }, [taskId, currentId]);

  // 媒体签名 URL：视频（按 offset 换算 seek）与焊缝图片切片
  const videoMeta = (detail?.meta?.video ?? null) as ModalityMeta | null;
  const seamMeta = (detail?.meta?.seam_image ?? null) as ModalityMeta | null;
  const videoKey = typeof videoMeta?.object_key === 'string' ? videoMeta.object_key : null;
  const cropKey = typeof seamMeta?.crop_key === 'string' ? seamMeta.crop_key
    : (detail?.object_keys ?? []).find((key) => key.endsWith('.jpg')) ?? null;

  useEffect(() => {
    setVideoFailed(false);
    if (!videoKey) { setVideoUrl(null); return; }
    let cancelled = false;
    getFileUrl(videoKey)
      .then((res) => { if (!cancelled) setVideoUrl(res.url); })
      .catch(() => { if (!cancelled) setVideoUrl(null); });
    return () => { cancelled = true; };
  }, [videoKey]);

  useEffect(() => {
    if (!cropKey) { setCropUrl(null); return; }
    let cancelled = false;
    getFileUrl(cropKey)
      .then((res) => { if (!cancelled) setCropUrl(res.url); })
      .catch(() => { if (!cancelled) setCropUrl(null); });
    return () => { cancelled = true; };
  }, [cropKey]);

  // 选中样本变化 → 视频 seek 到该段的**视频轴**起点（`t_video = t_signal - offset`）。
  // 与分段页同一换算；offset 来自本样本 manifest 的 video 映射，未标定即 0。
  useEffect(() => {
    const video = videoRef.current;
    if (!video || detail?.start_time == null) return;
    const offset = typeof videoMeta?.offset_seconds === 'number' ? videoMeta.offset_seconds : 0;
    video.currentTime = Math.max(0, detail.start_time - offset);
  }, [detail, videoMeta, videoUrl]);

  // ── 导航与保存 ─────────────────────────────────────────────────────
  const index = rows.findIndex((row) => row.id === currentId);
  const hasPrevPage = page > 1;
  const hasNextPage = page * PAGE_SIZE < total;
  const canPrev = index > 0 || hasPrevPage;
  const canNext = (index >= 0 && index < rows.length - 1) || hasNextPage;

  const goPrev = () => {
    if (index > 0) { setCurrentId(rows[index - 1].id); return; }
    if (hasPrevPage) { pendingSelectRef.current = 'last'; setPage((value) => value - 1); }
  };

  const goNext = () => {
    if (index >= 0 && index < rows.length - 1) { setCurrentId(rows[index + 1].id); return; }
    if (hasNextPage) { pendingSelectRef.current = 'first'; setPage((value) => value + 1); }
  };

  /** 保存（`advance` 为真时保存并跳到下一段）。 */
  const submit = async (advance: boolean) => {
    if (!taskId || currentId == null || busy) return;
    setBusy(true);
    setNotice(null);
    const indexBefore = index;
    try {
      await saveSegmentAnnotation(taskId, currentId, {
        label: draft.label,
        defect_category_id: draft.label === 'defect' ? draft.categoryId : null,
        note: draft.note.trim() ? draft.note.trim() : null,
      });
    } catch (err) {
      setBusy(false);
      setNotice({ tone: 'error', text: errorText(err, '保存失败，请重试') });
      return;
    }
    // 保存成功：刷新当前页（进度与行状态都变了）。
    // **未标注筛选下当前行会从列表消失**，所以用保存前的下标定位"下一段"。
    const data = await loadPage(taskId, filter, page);
    setBusy(false);
    setNotice({ tone: 'ok', text: '已保存' });
    if (!data) return;
    if (!advance) return;
    const sameIndex = data.items.findIndex((row) => row.id === currentId);
    const nextIndex = sameIndex >= 0 ? sameIndex + 1 : indexBefore;
    if (nextIndex < data.items.length) setCurrentId(data.items[nextIndex].id);
    else if (page * PAGE_SIZE < data.total) { pendingSelectRef.current = 'first'; setPage((value) => value + 1); }
  };

  const removeAnnotation = async () => {
    if (!taskId || currentId == null || busy) return;
    setBusy(true);
    setNotice(null);
    try {
      await clearSegmentAnnotation(taskId, currentId);
      setAnnotation(null);
      setDraft({ label: 'normal', categoryId: null, note: '' });
      await loadPage(taskId, filter, page);
      setNotice({ tone: 'ok', text: '已撤销该段标注' });
    } catch (err) {
      setNotice({ tone: 'error', text: errorText(err, '撤销失败，请重试') });
    } finally {
      setBusy(false);
    }
  };

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
                <button key={task.task_id} className="segment-task-card" onClick={() => { setTaskId(task.task_id); setPage(1); setFilter('all'); }}>
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

  const windowRows = rows;
  const range = detail && detail.start_time != null && detail.end_time != null
    ? fmtRange(detail.start_time, detail.end_time) : '—';
  const draftInvalid = draft.label === 'defect' && draft.categoryId == null;

  return (
    <>
      <PageIntro
        eyebrow="多模态数据生产线"
        title="分段样本标注"
        description="每段一个主结论：正常，或缺陷 + 主缺陷类别。三个模态共用该段的时间窗，缺失模态只提示原因、不阻断标注。"
        action={<button className="outline-button" onClick={() => setTaskId(null)}><Undo2 size={14} />换个分段任务</button>}
      />

      {notice && (
        <p className={notice.tone === 'error' ? 'toolbar-error settings-notice' : 'accent-text settings-notice'}
           role={notice.tone === 'error' ? 'alert' : 'status'}>{notice.text}</p>
      )}
      {listError && <p className="toolbar-error settings-notice" role="alert">{listError}</p>}

      <div className="segment-annotation-layout">
        <aside className="panel segment-sidebar">
          <div className="studio-head">
            <div><span className="file-badge">样本列表</span><h2>{progress ? `${progress.annotated}/${progress.total}` : '—'}</h2></div>
            <span className="studio-dur">{progress ? `${progress.progress}%` : '—'}</span>
          </div>
          <div className="segment-progress-bar" aria-hidden>
            <i style={{ width: `${progress?.progress ?? 0}%` }} />
          </div>
          <div className="segment-filter">
            <button className={filter === 'all' ? 'segment-chip active' : 'segment-chip'} onClick={() => { setFilter('all'); setPage(1); }}>全部</button>
            <button className={filter === 'unannotated' ? 'segment-chip active' : 'segment-chip'} onClick={() => { setFilter('unannotated'); setPage(1); }}>
              未标注{progress ? ` ${progress.unannotated}` : ''}
            </button>
          </div>
          {progress && progress.defect_distribution.length > 0 && (
            <div className="segment-defect-summary">
              {progress.defect_distribution.map((item) => (
                <span key={item.name}>{item.name} {item.count}</span>
              ))}
            </div>
          )}
          {loading && <p className="dataset-empty-state" role="status">样本加载中…</p>}
          {!loading && windowRows.length === 0 && (
            <p className="dataset-empty-state" role="status">
              {filter === 'unannotated' ? '该任务已全部标注完成。' : '该任务没有样本。'}
            </p>
          )}
          <div className="segment-sample-list">
            {windowRows.map((row) => (
              <button
                key={row.id}
                className={`segment-sample-row ${row.id === currentId ? 'active' : ''}`}
                onClick={() => setCurrentId(row.id)}
              >
                <span className="segment-sample-no">#{row.frame_no ?? '—'}</span>
                <span className="segment-sample-time">
                  {row.start_time != null && row.end_time != null ? `${row.start_time.toFixed(2)}–${row.end_time.toFixed(2)}s` : '—'}
                </span>
                <span className={`segment-sample-label ${row.annotated ? (row.label === 'defect' ? 'bad' : 'ok') : ''}`}>
                  {labelText(row)}
                </span>
              </button>
            ))}
          </div>
          <div className="segment-pager">
            <button className="ghost-button" disabled={!canPrev} onClick={goPrev}><ChevronLeft size={14} />上一段</button>
            <span>{page}/{Math.max(1, Math.ceil(total / PAGE_SIZE))}</span>
            <button className="ghost-button" disabled={!canNext} onClick={goNext}>下一段<ChevronRight size={14} /></button>
          </div>
        </aside>

        <section className="panel segment-detail">
          <div className="studio-head">
            <div>
              <span className="file-badge">样本 #{detail?.frame_no ?? '—'}</span>
              <h2>{range}</h2>
            </div>
            {annotation && <StatusPill tone={annotation.label === 'defect' ? 'red' : 'green'}>{labelText(annotation)}</StatusPill>}
          </div>

          {!detail && <p className="dataset-empty-state" role="status">样本详情加载中…</p>}

          {detail && (
            <>
              {/* ① 时序：该窗口内的局部波形（服务端已降采样，≤600 点/通道） */}
              <div className="segment-modality">
                <div className="segment-modality-head">
                  <b>时域信号</b>
                  <ModalityTag available={Boolean(detail.modalities?.signal?.available)} reason={detail.modalities?.signal?.reason} />
                </div>
                {detail.time_series.length === 0 ? (
                  <p className="preview-summary">该窗口没有可用的时序数据（源信号未导入或读取失败）。</p>
                ) : detail.time_series.map((track) => (
                  <LocalWave key={track.id} track={track} />
                ))}
              </div>

              {/* ② 视频：定位到本段起点（t_video = t_signal − offset） */}
              <div className="segment-modality">
                <div className="segment-modality-head">
                  <b>视频</b>
                  <ModalityTag available={Boolean(detail.modalities?.video?.available)}
                               reason={detail.modalities?.video?.reason}
                               calibrated={videoMeta?.calibrated} />
                </div>
                {videoUrl ? (
                  <>
                    <video
                      ref={videoRef}
                      className="segment-video"
                      src={videoUrl}
                      controls
                      preload="metadata"
                      onError={() => setVideoFailed(true)}
                    />
                    <p className="preview-summary">
                      {videoFailed
                        ? '该视频当前浏览器无法解码（多为 MPEG-4 Part 2 等非 H.264 编码）。等到媒体预处理生成 H.264 预览版后可重试。'
                        : `已定位到本段起点：t_video = t_signal − offset（offset ${(videoMeta?.offset_seconds ?? 0).toFixed(3)}s）${
                            videoMeta?.fps ? ` · fps ${videoMeta.fps} · 帧 ${videoMeta.start_frame}–${videoMeta.end_frame}` : ''
                          }${
                            (videoMeta?.keyframes ?? []).length
                              ? ` · 关联帧时刻 ${(videoMeta?.keyframes ?? []).map((k) => k.at.toFixed(2)).join(' / ')}s`
                              : ''
                          }`}
                    </p>
                  </>
                ) : (
                  <p className="preview-summary">
                    本段没有可播放的视频对象。{detail.modalities?.video?.reason ? `原因：${detail.modalities.video.reason}` : ''}
                  </p>
                )}
              </div>

              {/* ③ 焊缝图片：按弧长投影裁出的本段条带 */}
              <div className="segment-modality">
                <div className="segment-modality-head">
                  <b>焊缝图片切片</b>
                  <ModalityTag available={Boolean(detail.modalities?.seam_image?.available)}
                               reason={detail.modalities?.seam_image?.reason}
                               calibrated={seamMeta?.calibrated} />
                </div>
                {cropUrl ? <img className="segment-crop" src={cropUrl} alt={`样本 ${detail.frame_no} 的焊缝图片切片`} />
                  : <p className="preview-summary">
                      本段没有焊缝图片切片——图片是**增强模态**，缺失不影响该段成立。{detail.modalities?.seam_image?.reason ? `原因：${detail.modalities.seam_image.reason}` : ''}
                    </p>}
                {seamMeta?.spatial_range && (
                  <p className="preview-summary">
                    沿 ROI 长边投影：{seamMeta.spatial_range.start_px.toFixed(1)} – {seamMeta.spatial_range.end_px.toFixed(1)} px
                    {seamMeta.roi ? `（ROI ${seamMeta.roi.w}×${seamMeta.roi.h}）` : ''}
                  </p>
                )}
              </div>

              {/* ④ 结论：一期只有这一个表单，没有框/点/掩膜 */}
              <div className="segment-verdict">
                <div className="segment-verdict-head">
                  <b>本段结论</b>
                  {annotation && <small>最近由 {annotation.annotator ?? '—'} 标注</small>}
                </div>
                <div className="segment-verdict-choice">
                  <button
                    className={`segment-choice ${draft.label === 'normal' ? 'active ok' : ''}`}
                    onClick={() => setDraft((prev) => ({ ...prev, label: 'normal', categoryId: null }))}
                  ><CheckCircle2 size={15} />正常</button>
                  <button
                    className={`segment-choice ${draft.label === 'defect' ? 'active bad' : ''}`}
                    onClick={() => setDraft((prev) => ({ ...prev, label: 'defect' }))}
                  ><AlertTriangle size={15} />缺陷</button>
                </div>

                {draft.label === 'defect' && (
                  <div className="segment-category-grid">
                    {categories.filter((item) => item.active || item.id === annotation?.defect_category_id).length === 0 && (
                      <p className="preview-summary">暂无可用缺陷类别，请到「系统设置 → 分段样本缺陷词表」维护。</p>
                    )}
                    {categories
                      .filter((item) => item.active || item.id === annotation?.defect_category_id)
                      .map((item) => (
                        <button
                          key={item.id}
                          className={`segment-category ${draft.categoryId === item.id ? 'active' : ''}`}
                          onClick={() => setDraft((prev) => ({ ...prev, categoryId: item.id }))}
                        >
                          {item.value}
                          {!item.active && <em>已停用</em>}
                        </button>
                      ))}
                  </div>
                )}

                <label className="split-field-label" htmlFor="segment-note">备注（可选）</label>
                <textarea
                  id="segment-note"
                  className="segment-note"
                  rows={2}
                  maxLength={512}
                  placeholder="例如：收弧处可见气孔，长度约 3mm"
                  value={draft.note}
                  onChange={(event) => setDraft((prev) => ({ ...prev, note: event.target.value }))}
                />

                <div className="segment-actions">
                  <button className="primary-button" disabled={busy || draftInvalid} onClick={() => void submit(false)}>
                    <Save size={14} />保存
                  </button>
                  <button className="outline-button" disabled={busy || draftInvalid} onClick={() => void submit(true)}>
                    保存并下一段<ChevronRight size={14} />
                  </button>
                  {annotation && (
                    <button className="ghost-button" disabled={busy} onClick={() => void removeAnnotation()}>
                      <Trash2 size={13} />撤销标注
                    </button>
                  )}
                  {draftInvalid && <span className="toolbar-error">选择「缺陷」时必须指定主缺陷类别</span>}
                </div>
              </div>
            </>
          )}
        </section>
      </div>
    </>
  );
}

/** 模态可用性角标：不可用时**如实给出原因**（缺失不阻断标注）。 */
function ModalityTag({ available, reason, calibrated }: { available: boolean; reason?: string | null; calibrated?: boolean }) {
  if (!available) {
    return <span className="segment-modality-tag bad" title={reason ?? undefined}>不可用{reason ? ` · ${reason}` : ''}</span>;
  }
  if (calibrated === false) {
    return <span className="segment-modality-tag warn" title="时间零点未标定，该模态按 offset=0 假设对齐">未标定</span>;
  }
  return <span className="segment-modality-tag ok">可用</span>;
}

/** 本段局部波形：横轴是该段自身的起止（不是全段时长），按点自带的秒坐标画。 */
function LocalWave({ track }: { track: { id: string; name: string; unit: string; times: number[]; values: number[] } }) {
  const color = chanColorOf(track.id);
  const start = track.times[0] ?? 0;
  const span = Math.max((track.times[track.times.length - 1] ?? start) - start, 1e-6);
  const [lo, hi] = trackRange(track);
  // 像素级抽稀：详情端点已降到 ≤600 点，这里再按屏幕宽度取样，避免一条 SVG path 上千段
  const step = Math.max(1, Math.ceil(track.values.length / WAVE_POINTS));
  const times = step > 1 ? track.times.filter((_, i) => i % step === 0) : track.times;
  const values = step > 1 ? track.values.filter((_, i) => i % step === 0) : track.values;
  return (
    <div className="lane">
      <div className="lane-label">
        <i className="lane-dot" style={{ background: color }} />
        {track.name}
        <span className="lane-meta">{track.values.length} 点{track.unit ? ` · ${track.unit}` : ''}</span>
      </div>
      <div className="lane-track">
        {values.length > 1 ? (
          <svg className="lane-wave" viewBox="0 0 1000 40" preserveAspectRatio="none" aria-hidden>
            <path
              d={timePath(times.map((t) => t - start), values, lo, hi, span, 1000, 40)}
              fill="none" stroke={color} strokeWidth={1.4} vectorEffect="non-scaling-stroke"
            />
          </svg>
        ) : (
          <div className="lane-video-empty"><span>该窗口内没有降采样点</span></div>
        )}
      </div>
    </div>
  );
}
