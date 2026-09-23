/**
 * 标注右栏（2026-09-23）：选中窗口的**结论表单**在上，该段的**三模态细节**在下。
 *
 * 表单在上的理由：总览时间轴已经回答了"这一段长什么样、上下文是什么"，右栏的第一职责是
 * **把结论定下来**——把表单压到详情下面会让每标一段都多滚一次屏。
 *
 * 模态细节是"放大看的那一份"：时间轴上四条降采样波形是**整条焊缝**抽稀到 ≤1200 点后的
 * 批次切片，这里换成本窗自己的 ≤600 点局部波形（`GET /split-tasks/{id}/samples/{sid}`）；
 * 视频播放器也只在这里（时间轴上的视频轨是"一段一格"的实拍帧，不播视频）。
 *
 * 三模态**共用同一个时间窗**（`window.start`/`window.end`）——屏幕上不存在"各模态各自的时间轴"。
 * 模态缺失只显示原因、**不阻断标注**：结论来自人工判断，不依赖某个模态是否可用。
 */
import type { RefObject } from 'react';
import { AlertTriangle, Ban, CheckCircle2, ChevronRight, Save, Trash2 } from 'lucide-react';
import type {
  AnnotationTimelineWindow, SampleAnnotation, SegmentCategory, SegmentLabel, SplitSampleDetail,
} from '../../../api/types';
import { chanColorOf } from '../../analysis/signals/chartData';
import { fmtRange, timePath, trackRange } from '../../alignment/split/splitTypes';

/** 结论草稿（用户正在编辑、尚未保存的那一份）。 */
export interface VerdictDraft {
  label: SegmentLabel;
  categoryId: number | null;
  note: string;
}

/** 词表候选：启用项 + **当前标注引用的那一项**（它可能后来被停用了，得能显示出来）。 */
function categoryOptions(categories: SegmentCategory[], annotation: SampleAnnotation | null) {
  return categories.filter((item) => item.active || item.id === annotation?.defect_category_id);
}

interface Props {
  window: AnnotationTimelineWindow;
  detail: SplitSampleDetail | null;
  detailError: string | null;
  videoUrl: string | null;
  videoFailed: boolean;
  onVideoFailed: () => void;
  /** 由工作台持有：换窗口时要命令式地 seek 到本窗起点（`t_video = t_signal − offset`）。 */
  videoRef: RefObject<HTMLVideoElement>;
  categories: SegmentCategory[];
  annotation: SampleAnnotation | null;
  draft: VerdictDraft;
  onDraft: (patch: Partial<VerdictDraft>) => void;
  busy: boolean;
  onSave: (advance: boolean) => void;
  onClear: () => void;
}

export function AnnotationRail({
  window: row, detail, detailError, videoUrl, videoFailed, onVideoFailed, videoRef,
  categories, annotation, draft, onDraft, busy, onSave, onClear,
}: Props) {
  const range = row.start != null && row.end != null ? fmtRange(row.start, row.end) : '—';
  const draftInvalid = draft.label === 'defect' && draft.categoryId == null;
  const candidates = categoryOptions(categories, annotation);
  const videoMeta = (detail?.meta?.video ?? null) as { offset_seconds?: number; fps?: number; start_frame?: number; end_frame?: number } | null;

  return (
    <aside className="panel annot-rail">
      <div className="studio-head">
        <div>
          <span className="file-badge">窗口 #{row.index ?? '—'}</span>
          <h2>{range}</h2>
        </div>
        <StatusTag row={row} />
      </div>

      {/* ① 结论：一期只有这一个表单，没有框 / 点 / 掩膜 */}
      <div className="segment-verdict">
        <div className="segment-verdict-head">
          <b>本段结论</b>
          {annotation && <small>最近由 {annotation.annotator ?? '—'} 标注</small>}
        </div>
        <div className="segment-verdict-choice">
          <button
            className={`segment-choice ${draft.label === 'normal' ? 'active ok' : ''}`}
            onClick={() => onDraft({ label: 'normal', categoryId: null })}
          ><CheckCircle2 size={15} />正常</button>
          <button
            className={`segment-choice ${draft.label === 'defect' ? 'active bad' : ''}`}
            onClick={() => onDraft({ label: 'defect' })}
          ><AlertTriangle size={15} />缺陷</button>
        </div>

        {draft.label === 'defect' && (
          <div className="segment-category-grid">
            {candidates.length === 0 && (
              <p className="preview-summary">暂无可用缺陷类别，请到「系统设置 → 分段样本缺陷词表」维护。</p>
            )}
            {candidates.map((item) => (
              <button
                key={item.id}
                className={`segment-category ${draft.categoryId === item.id ? 'active' : ''}`}
                onClick={() => onDraft({ categoryId: item.id })}
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
          onChange={(event) => onDraft({ note: event.target.value })}
        />

        <div className="segment-actions">
          <button className="primary-button" disabled={busy || draftInvalid} onClick={() => onSave(false)}>
            <Save size={14} />保存
          </button>
          <button className="outline-button" disabled={busy || draftInvalid} onClick={() => onSave(true)}>
            保存并下一段<ChevronRight size={14} />
          </button>
          {annotation && (
            <button className="ghost-button" disabled={busy} onClick={onClear}>
              <Trash2 size={13} />撤销标注
            </button>
          )}
          {draftInvalid && <span className="toolbar-error">选择「缺陷」时必须指定主缺陷类别</span>}
        </div>
        <p className="annot-hint">快捷键：← / → 换窗口，N 标正常并保存，D 选缺陷</p>
      </div>

      {/* ② 模态细节：本窗自己的波形 / 播放器 / 图片切片（缺失只标记，不阻断上面的表单） */}
      {detailError && <p className="toolbar-error settings-notice" role="alert">{detailError}</p>}
      {!detail && !detailError && <p className="dataset-empty-state" role="status">该窗口细节加载中…</p>}

      {detail && (
        <>
          <div className="segment-modality">
            <div className="segment-modality-head">
              <b>时域信号</b>
              <ModalityTag available={Boolean(row.signal.available)} reason={row.signal.reason} />
            </div>
            {detail.time_series.length === 0 ? (
              <p className="preview-summary">该窗口没有可用的时序数据（源信号未导入或读取失败）。</p>
            ) : detail.time_series.map((track) => <LocalWave key={track.id} track={track} />)}
          </div>

          <div className="segment-modality">
            <div className="segment-modality-head">
              <b>视频</b>
              <ModalityTag available={Boolean(row.video.available)} reason={row.video.reason}
                           calibrated={row.video.calibrated} />
            </div>
            {videoUrl ? (
              <>
                {/* key 换窗口重挂载：否则同一个 <video> 不会重新定位到新窗起点 */}
                <video
                  key={row.sample_id}
                  ref={videoRef}
                  className="segment-video"
                  src={videoUrl}
                  controls
                  preload="metadata"
                  onError={onVideoFailed}
                />
                <p className="preview-summary">
                  {videoFailed
                    ? '该视频当前浏览器无法解码（多为 MPEG-4 Part 2 等非 H.264 编码）。等到媒体预处理生成 H.264 预览版后可重试。'
                    : `已定位到本窗起点：t_video = t_signal − offset（offset ${(videoMeta?.offset_seconds ?? 0).toFixed(3)}s）${
                        videoMeta?.fps ? ` · fps ${videoMeta.fps} · 帧 ${videoMeta.start_frame}–${videoMeta.end_frame}` : ''
                      }`}
                </p>
              </>
            ) : (
              <p className="preview-summary">
                本窗没有可播放的视频对象。{row.video.reason ? `原因：${row.video.reason}` : ''}
              </p>
            )}
          </div>

          <div className="segment-modality">
            <div className="segment-modality-head">
              <b>焊缝图片切片</b>
              <ModalityTag available={Boolean(row.seam_image.available)} reason={row.seam_image.reason}
                           calibrated={row.seam_image.calibrated} />
            </div>
            {row.crop_url ? (
              <img className="segment-crop" src={row.crop_url} alt={`窗口 ${row.index ?? ''} 的焊缝图片切片`} />
            ) : (
              <p className="preview-summary">
                本窗没有焊缝图片切片——图片是**增强模态**，缺失不影响该窗成立。
                {row.seam_image.reason ? `原因：${row.seam_image.reason}` : ''}
              </p>
            )}
          </div>
        </>
      )}
    </aside>
  );
}

/** 窗口头的结论角标；未标注时给中性的"未标注"而不是留空。 */
function StatusTag({ row }: { row: AnnotationTimelineWindow }) {
  if (!row.annotated) return <span className="segment-modality-tag warn">未标注</span>;
  return row.label === 'defect'
    ? <span className="segment-modality-tag bad">{row.defect_category_name || '缺陷'}</span>
    : <span className="segment-modality-tag ok">正常</span>;
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

/** 本窗局部波形：横轴是本窗自身的起止（不是整条焊缝），按点自带的秒坐标画。 */
function LocalWave({ track }: { track: { id: string; name: string; unit: string; times: number[]; values: number[] } }) {
  const color = chanColorOf(track.id);
  const start = track.times[0] ?? 0;
  const span = Math.max((track.times[track.times.length - 1] ?? start) - start, 1e-6);
  const [lo, hi] = trackRange(track);
  return (
    <div className="lane">
      <div className="lane-label">
        <i className="lane-dot" style={{ background: color }} />
        {track.name}
        <span className="lane-meta">{track.values.length} 点{track.unit ? ` · ${track.unit}` : ''}</span>
      </div>
      <div className="lane-track">
        {track.values.length > 1 ? (
          <svg className="lane-wave" viewBox="0 0 1000 40" preserveAspectRatio="none" aria-hidden>
            <path
              d={timePath(track.times.map((t) => t - start), track.values, lo, hi, span, 1000, 40)}
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

/** 空态：没选中任何窗口（批次为空 / 还没加载完）。 */
export function EmptyRail() {
  return (
    <aside className="panel annot-rail">
      <div className="lane-video-empty annot-rail-empty">
        <Ban size={18} />
        <span>点时间轴上的任意一列开始标注</span>
      </div>
    </aside>
  );
}
