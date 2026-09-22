/**
 * 多模态统一时间轴（设计 §4.3/§4.4）：共用比例尺 + 切片边界 + 选中高亮。
 *
 * 三条轨道（时序 / 视频 / 焊缝图片）共用**同一个横轴**，边界线贯穿全部轨道——
 * 这是"确认不同模态是否落入同一时间窗"的前提（§1 问题 3）。所有边界都来自服务端成功预览。
 */
import type { Ref } from 'react';
import type { SplitPreview } from '../../../api/types';
import { SeamImageLane } from './SeamImageLane';
import { SignalTimelineLane } from './SignalTimelineLane';
import { VideoTimelineLane } from './VideoTimelineLane';
import { fmtRange, pctOf } from './splitTypes';

interface Props {
  preview: SplitPreview;
  videoUrl: string | null;
  seamImageUrl: string | null;
  videoRef: Ref<HTMLVideoElement>;
  selectedIndex: number | null;
  playhead: number;
  onSelect: (index: number) => void;
  onSeek: (signalTime: number) => void;
  onTimeUpdate: (signalTime: number) => void;
}

const RULER_TICKS = 8;

export function MultimodalTimeline({
  preview, videoUrl, seamImageUrl, videoRef,
  selectedIndex, playhead, onSelect, onSeek, onTimeUpdate,
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
        videoUrl={videoUrl}
        videoRef={videoRef}
        duration={duration}
        offsetSeconds={selected?.video?.offset_seconds ?? 0}
        calibrated={Boolean(video.calibrated)}
        reason={video.reason ?? null}
        boundaries={boundaries}
        thumbnailTimes={preview.timeline.video_thumbnail_times}
        selected={selectedRange}
        onSeek={onSeek}
        onTimeUpdate={onTimeUpdate}
      />
      <SeamImageLane
        projection={preview.timeline.seam_image_projection}
        imageUrl={seamImageUrl}
        duration={duration}
        boundaries={boundaries}
        selected={selectedRange}
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
            <div className="sample-thumb">
              <span>#{w.index}</span>
            </div>
            <strong>{fmtRange(w.start, w.end)}</strong>
            <small>
              {w.video.available ? '视频✓' : '视频✕'} · {w.seam_image.available ? '图片✓' : '图片✕'}
            </small>
          </button>
        ))}
      </div>
    </div>
  );
}
