/**
 * 多模态统一时间轴（设计 §4.3/§4.4）：共用比例尺 + 切片边界 + 选中高亮。
 *
 * 三条轨道（时序 / 视频 / 焊缝图片）共用**同一个横轴**，边界线贯穿全部轨道——
 * 这是"确认不同模态是否落入同一时间窗"的前提（§1 问题 3）。所有边界都来自服务端成功预览。
 */
import type { SplitPreview } from '../../../api/types';
import { SeamImageLane } from './SeamImageLane';
import { SignalTimelineLane } from './SignalTimelineLane';
import { VideoTimelineLane } from './VideoTimelineLane';
import { fmtRange, pctOf } from './splitTypes';

interface Props {
  preview: SplitPreview;
  seamImageUrl: string | null;
  selectedIndex: number | null;
  playhead: number;
  onSelect: (index: number) => void;
}

const RULER_TICKS = 8;

export function MultimodalTimeline({
  preview, seamImageUrl, selectedIndex, playhead, onSelect,
}: Props) {
  const duration = preview.timeline.duration;
  const video = preview.modalities.video ?? { available: false, calibrated: false, reason: null };
  // 边界 = 每个窗口的起点 + 最后一个窗口的终点；半开区间下相邻窗口不会重复算边界
  const boundaries = preview.windows.length
    ? [...preview.windows.map((w) => w.start), preview.windows[preview.windows.length - 1].end]
    : [];
  const selected = preview.windows.find((w) => w.index === selectedIndex) ?? null;
  const selectedRange = selected ? { start: selected.start, end: selected.end } : null;

  return (
    <div className="alignment-board">
      <div className="studio-head">
        <div>
          <span className="file-badge">统一时间轴</span>
          <h2>时序 / 视频 / 焊缝图片</h2>
        </div>
        <span className="studio-dur">
          {duration.toFixed(3)}s · 有效 {fmtRange(preview.effective_range.start, preview.effective_range.end)}
        </span>
      </div>

      <div className="studio-ruler">
        <div className="ruler-tickbar">
          {Array.from({ length: RULER_TICKS + 1 }, (_, i) => {
            const t = (duration * i) / RULER_TICKS;
            return (
              <span key={i} style={{ left: `${pctOf(t, duration)}%` }}>{t.toFixed(1)}</span>
            );
          })}
        </div>
        <div className="ruler-events">
          {typeof preview.timeline.events.arc === 'number' && (
            <i className="ruler-arc" style={{ left: `${pctOf(preview.timeline.events.arc, duration)}%` }} title="起弧" />
          )}
          {typeof preview.timeline.events.tail === 'number' && (
            <b className="ruler-tail" style={{ left: `${pctOf(preview.timeline.events.tail, duration)}%` }} title="收弧" />
          )}
        </div>
        {boundaries.map((t) => (
          <i key={t} className="lane-marker" style={{ left: `${pctOf(t, duration)}%`, opacity: 0.5 }} />
        ))}
        <i className="ruler-playhead" style={{ left: `${pctOf(playhead, duration)}%` }} />
      </div>

      <SignalTimelineLane
        tracks={preview.timeline.signal.tracks}
        duration={duration}
        boundaries={boundaries}
        selected={selectedRange}
      />
      <VideoTimelineLane
        windows={preview.windows}
        duration={duration}
        calibrated={Boolean(video.calibrated)}
        reason={video.reason ?? null}
        selectedIndex={selectedIndex}
        onSelect={onSelect}
      />
      <SeamImageLane
        projection={preview.timeline.seam_image_projection}
        windows={preview.windows}
        imageUrl={seamImageUrl}
        selectedIndex={selectedIndex}
      />

      {/* 切片卡片：与轨道上的边界是"同一切片的两种入口"（§4.4） */}
      <div className="sample-preview-grid">
        {preview.windows.map((w) => (
          <button
            type="button"
            key={w.index}
            className={`sample-preview-card${w.index === selectedIndex ? ' is-selected' : ''}`}
            aria-pressed={w.index === selectedIndex}
            onClick={() => onSelect(w.index)}
          >
            {/* 代表帧：**本段自己的**那一帧（窗口中点）。取不到就如实写原因——
                既不拿全局首帧充数，也不用占位渐变假装有图。 */}
            <div className={`sample-thumb${w.video.frame?.url ? '' : ' sample-thumb-empty'}`}>
              {w.video.frame?.url ? (
                <img src={w.video.frame.url} alt={`分段 #${w.index} 的视频代表帧`} loading="lazy" />
              ) : (
                <span>无代表帧：{w.video.frame?.reason ?? w.video.reason ?? '视频不可用'}</span>
              )}
              <span className="sample-thumb-no">#{w.index}</span>
            </div>
            <strong>{fmtRange(w.start, w.end)}</strong>
            <small>
              {w.video.available ? '视频✓' : '视频✕'} ·{' '}
              {/* 图片：明确不参与 / 未框选 / 无图 三种"没有"要分开说，别让用户以为"再等等就有了" */}
              {w.seam_image.available ? '图片✓'
                : w.seam_image.excluded ? '图片未参与'
                : '图片✕'}
            </small>
          </button>
        ))}
      </div>
    </div>
  );
}
