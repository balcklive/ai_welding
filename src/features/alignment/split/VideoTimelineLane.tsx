/**
 * 视频轨（设计 §4.4）：真实视频 + 缩略图时间点 + 贯穿的切片边界。
 *
 * 播放器 seek 必须按 `t_video = t_signal - offset` 换算（§3.1.1）——时间轴上的秒是
 * **信号时间**，直接把它当 `currentTime` 会在标定过 offset 的焊缝上系统性错位。
 */
import { Play } from 'lucide-react';
import type { Ref } from 'react';
import { pctOf } from './splitTypes';

interface Props {
  videoUrl: string | null;
  videoRef: Ref<HTMLVideoElement>;
  duration: number;
  offsetSeconds: number;
  calibrated: boolean;
  reason: string | null;
  boundaries: number[];
  thumbnailTimes: number[];
  selected: { start: number; end: number } | null;
  onSeek: (signalTime: number) => void;
  onTimeUpdate: (signalTime: number) => void;
}

export function VideoTimelineLane({
  videoUrl, videoRef, duration, offsetSeconds, calibrated, reason,
  boundaries, thumbnailTimes, selected, onSeek, onTimeUpdate,
}: Props) {
  return (
    <div className="lane lane-video">
      <div className="lane-label">
        <i className="lane-dot" style={{ background: '#2c9caf' }} />
        视频帧
        <span className={`track-availability ${calibrated ? 'ok' : 'warn'}`}>
          {calibrated ? '已标定' : '未标定'}
        </span>
      </div>
      <div className="lane-track lane-track-video">
        {videoUrl ? (
          <video
            ref={videoRef}
            className="studio-video"
            src={videoUrl}
            controls
            preload="metadata"
            // 播放器给的是**视频时间**，加回 offset 才是信号时间（与 seek 反向，必须成对）
            onTimeUpdate={(e) => onTimeUpdate(e.currentTarget.currentTime + offsetSeconds)}
          />
        ) : (
          <div className="lane-video-empty">
            <Play size={18} />
            <span>{reason ?? '等待真实视频'}</span>
          </div>
        )}
        {/* 缩略图时间点：给一个"这段窗口在视频里大概是什么位置"的落点提示 */}
        {thumbnailTimes.map((t) => (
          <i
            key={t}
            className="lane-marker"
            style={{ left: `${pctOf(t, duration)}%`, opacity: 0.35 }}
            title={`缩略图 ${t.toFixed(2)}s`}
          />
        ))}
        {selected && (
          <div
            className="cut-effective"
            style={{
              position: 'absolute', top: 0, bottom: 0,
              left: `${pctOf(selected.start, duration)}%`,
              width: `${Math.max(0, pctOf(selected.end, duration) - pctOf(selected.start, duration))}%`,
              opacity: 0.22,
            }}
          />
        )}
        {boundaries.map((t) => (
          <i key={t} className="lane-marker" style={{ left: `${pctOf(t, duration)}%` }} />
        ))}
        {/* 点轨道任意位置 → 按信号时间定位（seek 的换算收在 onSeek 里） */}
        <button
          type="button"
          aria-label="点击定位视频"
          onClick={(e) => {
            const rect = e.currentTarget.getBoundingClientRect();
            onSeek(((e.clientX - rect.left) / Math.max(1, rect.width)) * duration);
          }}
          style={{ position: 'absolute', inset: 0, background: 'transparent', border: 0, cursor: 'crosshair' }}
        />
      </div>
    </div>
  );
}
