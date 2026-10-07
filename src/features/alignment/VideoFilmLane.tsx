/**
 * 统一轴上的视频胶片条（2026-10，对齐页的 offset 直接操纵）。
 *
 * **为什么要有这条轨**：此前"视频的时间 bar"是 `<video controls>` 的原生进度条，量程是视频
 * 自己的 0–duration，与信号轴（标尺 / 时序轨）**没有任何几何关系**——两条 bar 叠在一起
 * 看起来能对上、实际对不上。这里把视频画成统一轴上**真实占位的一段**：
 *
 * ```text
 * left  = offset                     ← 条的左端就是"视频零点落在信号轴的哪一秒"
 * width = videoDuration
 * ```
 *
 * 于是"对齐"从读数字变成看位置：拖这条 → `offset` 变 → 起弧帧滑到起弧标记下面即可。
 * 往右拖 offset 变大（视频整体在信号轴上往后挪）。
 *
 * **拖动全程零网络**：帧的内容与 offset 无关（服务端 `seek_offset` 恒 0），服务端只按视频
 * 时刻抽一次帧、带上 `t_video`；位置换算全在本组件（`t_video + offset`）。松手才保存。
 *
 * **不与点击定位冲突**：对齐页的 seek 事件委托挂在 `.alignment-board` 上，选择器把
 * `.lane-track-video` 与 `.lane-track-film` 都排除在外——所以点这条不会 seek。改选择器时
 * **必须保住这两个排除项**，否则点一下条会既改 offset 又 seek。
 */
import { useRef, useState } from 'react';
import { Play } from 'lucide-react';
import type { VideoFrames } from '../../api/types';

interface Props {
  /** 胶片条帧（只读端点返回）；未取到为 null。 */
  frames: VideoFrames | null;
  /** 帧请求在途。 */
  loading: boolean;
  /** 条宽用的视频时长：**优先后端探测值**，退化为 `<video>` 元素时长；都没有则不画条。 */
  videoDuration: number | null;
  /** 统一轴（信号轴）总时长。 */
  timelineDur: number;
  /** 当前生效的偏移（`草稿 ?? 已保存`）。 */
  offset: number;
  /** 起弧 / 收弧在信号轴上的时刻（画标记 + 起弧磁吸的目标）。 */
  arcSignal: number | null;
  tailSignal: number | null;
  calibrated: boolean;
  /** 时长来源不一致的提示（转码预览件 vs 原始对象差一两帧属预期）。 */
  durationNote: string | null;
  onDraft: (value: number) => void;
}

/** 磁吸阈值（像素）与吸附后的**释放**阈值（迟滞）——否则在边界上会来回抖。 */
const SNAP_PX = 14;
const SNAP_RELEASE_PX = 24;
/** 磁吸的第二个条件：纯像素阈值在长信号上会大得离谱（646px 轨道 + 182s 信号 → 14px ≈ 3.9s）。 */
const SNAP_SECONDS = 0.5;
/** 拖动结果至少留一点重叠，保证条永远抓得住（数字框不受此限）。 */
const EDGE_EPSILON = 0.05;

export function VideoFilmLane({
  frames, loading, videoDuration, timelineDur, offset, arcSignal, tailSignal,
  calibrated, durationNote, onDraft,
}: Props) {
  const dragRef = useRef<{
    pointerId: number; startX: number; startOffset: number; trackWidth: number; last: number;
  } | null>(null);
  const snappedRef = useRef(false);
  const [dragging, setDragging] = useState(false);

  /**
   * 轴上比例——**刻意不钳**。`AlignmentWorkspace.pct` / `splitTypes.pctOf` 都
   * `Math.min(100, Math.max(0, …))`，拿它们算条的位置/宽度会说谎：offset 超出信号时长时条
   * 粘在最右边，视频比信号长时宽封顶 100%，把"视频超出"这个事实藏起来。越界交给
   * `.lane-track{overflow:hidden}` 如实裁掉。
   */
  const axisPct = (seconds: number) => `${(seconds / (timelineDur || 1)) * 100}%`;
  /** 标记线可以钳（它只是指示位置，跑出轨道没有意义）。 */
  const markPct = (seconds: number) => `${Math.min(100, Math.max(0, (seconds / (timelineDur || 1)) * 100))}%`;

  const count = frames?.frames.length ?? 0;
  const drawBar = timelineDur > 0 && videoDuration != null && videoDuration > 0;
  /** 有帧全抽失败但时长已知的情况——**条照画、照样能拖**（条宽只靠时长，不靠帧）。 */
  const canDrag = drawBar;

  const onPointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!canDrag) return;
    // 条内是 <img>（默认可拖），不挡掉会启动原生 dragstart、把拖动抢走
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    const rect = event.currentTarget.getBoundingClientRect();
    dragRef.current = {
      pointerId: event.pointerId, startX: event.clientX, startOffset: offset,
      trackWidth: rect.width, last: offset,
    };
    snappedRef.current = false;
    setDragging(true);
  };

  const onPointerMove = (event: React.PointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId || drag.trackWidth <= 0) return;
    // 用**轨道**宽换算：`left` 表达的是轴上的比例（`offset / timelineDur`），
    // 所以轴上的 1px = `timelineDur / trackWidth` 秒。用条宽只有在条恰好铺满整根轨道时才对，
    // 条一短就会过量移动（拖 100px、条跑 100×(track/bar) px）。
    const pxPerSec = drag.trackWidth / (timelineDur || 1);
    let next = drag.startOffset + (event.clientX - drag.startX) / pxPerSec;

    if (arcSignal != null) {
      const limit = snappedRef.current ? SNAP_RELEASE_PX : SNAP_PX;
      const near = Math.abs(next - arcSignal) * pxPerSec <= limit
        && Math.abs(next - arcSignal) <= SNAP_SECONDS;
      if (near) {
        // 语义：假设"视频从起弧开始录" ⇒ 视频零点落在起弧时刻 ⇒ offset = arc
        next = arcSignal;
        snappedRef.current = true;
      } else {
        snappedRef.current = false;
      }
    }

    if (videoDuration != null) {
      next = Math.min(
        (timelineDur || 0) - EDGE_EPSILON,
        Math.max(-videoDuration + EDGE_EPSILON, next),
      );
    }

    const value = Math.round(next * 100) / 100;
    // 纯点击 / 像素级抖动不该产生"有未保存的改动"
    if (Math.abs(value - drag.last) < 1e-3) return;
    drag.last = value;
    onDraft(value);
  };

  const endDrag = (event: React.PointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    dragRef.current = null;
    snappedRef.current = false;
    setDragging(false);
  };

  /** 键盘微调：条带 `role="slider"` 就必须真有键盘行为，否则是假可及性。 */
  const onKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (!canDrag) return;
    const step = event.shiftKey ? 0.5 : 0.05;
    if (event.key === 'ArrowLeft') {
      event.preventDefault();
      onDraft(Math.round((offset - step) * 100) / 100);
    } else if (event.key === 'ArrowRight') {
      event.preventDefault();
      onDraft(Math.round((offset + step) * 100) / 100);
    }
  };

  const emptyText = loading ? '正在抽取视频帧…'
    : frames?.reason ? frames.reason
      : timelineDur <= 0 ? '信号加载中…'
        : videoDuration == null ? '视频时长未知（元数据未就绪）'
          : '等待真实视频';

  return (
    <div className="lane">
      <div className="lane-label">
        <i className="lane-dot" style={{ background: '#2c9caf' }} />
        视频帧
        <span className={`track-availability ${calibrated ? 'ok' : 'warn'}`}>
          {calibrated ? '已标定' : '未标定'}
        </span>
        {durationNote && <span className="film-strip-note" title={durationNote}>{durationNote}</span>}
      </div>
      <div className="lane-track lane-track-film">
        {drawBar ? (
          <>
            <div
              className={`video-film-strip${dragging ? ' is-dragging' : ''}`}
              style={{ left: axisPct(offset), width: axisPct(videoDuration ?? 0) }}
              role="slider"
              tabIndex={0}
              aria-label="拖动对齐视频与信号的时间零点"
              aria-valuenow={Math.round(offset * 100) / 100}
              title={`视频占信号轴 ${offset.toFixed(2)}s – ${(offset + (videoDuration ?? 0)).toFixed(2)}s，拖动改偏移`}
              onPointerDown={onPointerDown}
              onPointerMove={onPointerMove}
              onPointerUp={endDrag}
              onPointerCancel={endDrag}
              onKeyDown={onKeyDown}
            >
              {frames?.frames.map((frame) => (
                <span
                  className="film-cell"
                  key={frame.index}
                  style={{ width: `${100 / Math.max(1, count)}%` }}
                  title={frame.url
                    ? `视频第 ${frame.t_video.toFixed(2)}s → 信号 ${(frame.t_video + offset).toFixed(2)}s`
                    : `视频第 ${frame.t_video.toFixed(2)}s 无帧`}
                >
                  {frame.url
                    ? <img src={frame.url} alt={`视频第 ${frame.t_video.toFixed(2)} 秒`} loading="lazy" draggable={false} />
                    // 无帧走浅底 + 原因，**不拿别的格或首帧顶替**
                    : <span className="film-cell-empty">无帧</span>}
                </span>
              ))}
            </div>
            {arcSignal != null && (
              <i className="lane-marker" style={{ left: markPct(arcSignal) }} title="起弧" />
            )}
            {tailSignal != null && (
              <b className="lane-marker lane-marker-end" style={{ left: markPct(tailSignal) }} title="收弧" />
            )}
          </>
        ) : (
          <div className="lane-video-empty"><Play size={18} /><span>{emptyText}</span></div>
        )}
      </div>
    </div>
  );
}
