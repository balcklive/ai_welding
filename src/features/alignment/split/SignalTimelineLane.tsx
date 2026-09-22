/**
 * 时序轨（设计 §4.4）：电流/电压等通道的降采样波形 + 贯穿的切片边界。
 *
 * 横坐标按**真实秒数**线性映射，与服务端 `timeline.signal.tracks[].times` 一致——
 * 所有轨道共用同一比例尺，禁止各轨单独缩放（否则"边界对齐"就是假的）。
 */
import { chanColorOf } from '../../analysis/signals/chartData';
import type { SplitTimelineTrack } from '../../../api/types';
import { pctOf, timePath, trackRange } from './splitTypes';

interface LaneProps {
  tracks: SplitTimelineTrack[];
  duration: number;
  boundaries: number[];
  selected: { start: number; end: number } | null;
}

export function SignalTimelineLane({ tracks, duration, boundaries, selected }: LaneProps) {
  if (!tracks.length) {
    return (
      <div className="lane">
        <div className="lane-label"><i className="lane-dot" />时序</div>
        <div className="lane-track">
          <div className="lane-video-empty"><span>该版本没有可用的真实时序信号</span></div>
        </div>
      </div>
    );
  }
  return (
    <>
      {tracks.map((track) => (
        <SignalRow
          key={track.id}
          track={track}
          duration={duration}
          boundaries={boundaries}
          selected={selected}
        />
      ))}
    </>
  );
}

function SignalRow({
  track, duration, boundaries, selected,
}: { track: SplitTimelineTrack } & Omit<LaneProps, 'tracks'>) {
  const [lo, hi] = trackRange(track);
  const color = chanColorOf(track.id);
  return (
    <div className="lane">
      <div className="lane-label">
        <i className="lane-dot" style={{ background: color }} />
        {track.name}
        <span className="lane-meta">{track.unit}</span>
      </div>
      <div className="lane-track">
        {selected && (
          <div
            className="cut-effective"
            style={{
              position: 'absolute', top: 0, bottom: 0,
              left: `${pctOf(selected.start, duration)}%`,
              width: `${Math.max(0, pctOf(selected.end, duration) - pctOf(selected.start, duration))}%`,
              opacity: 0.28,
            }}
          />
        )}
        <svg className="lane-wave" viewBox="0 0 1000 40" preserveAspectRatio="none" aria-hidden>
          <path
            d={timePath(track.times, track.values, lo, hi, duration, 1000, 40)}
            fill="none"
            stroke={color}
            strokeWidth={1.4}
            vectorEffect="non-scaling-stroke"
          />
        </svg>
        {boundaries.map((t) => (
          <i key={t} className="lane-marker" style={{ left: `${pctOf(t, duration)}%` }} />
        ))}
      </div>
    </div>
  );
}
