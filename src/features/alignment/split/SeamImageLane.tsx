/**
 * 焊缝图片投影带（设计 §4.4/§3.1.2）：整张照片铺开为背景，边界按 `px(t)` 垂直落在照片上。
 *
 * **只读**——ROI 只能在对齐页框选（§4.3）。这里是"分段页不可编辑标定"最要紧的一条：
 * 若允许在分段页拖 ROI，屏幕上的边界就不再能由服务端复现，"所见即所得"失效。
 */
import type { SplitPreview } from '../../../api/types';
import { pctOf } from './splitTypes';

interface Props {
  projection: SplitPreview['timeline']['seam_image_projection'];
  imageUrl: string | null;
  duration: number;
  boundaries: number[];
  selected: { start: number; end: number } | null;
}

const SPEED_SOURCE_NOTE: Record<string, string> = {
  scalar: '按焊接速度稳态中位数映射（未使用逐点速度）',
  none: '未使用真实焊接速度，按时间比例映射',
};

export function SeamImageLane({ projection, imageUrl, duration, boundaries, selected }: Props) {
  const ready = projection.available && projection.roi && imageUrl;
  return (
    <div className="lane">
      <div className="lane-label">
        <i className="lane-dot" style={{ background: '#c08a4e' }} />
        焊缝图片
        <span className={`track-availability ${ready ? 'ok' : 'warn'}`}>
          {ready ? '已投影' : '未标定'}
        </span>
      </div>
      <div className="lane-track" style={{ height: 96 }}>
        {ready ? (
          <>
            {/* 照片按 ROI 长边铺满轨道宽度：`px(t)` 投影到的百分比与轨道百分比同一坐标系 */}
            <img
              src={imageUrl ?? ''}
              alt="焊缝图片投影"
              style={{
                position: 'absolute',
                top: 0,
                bottom: 0,
                left: 0,
                width: '100%',
                height: '100%',
                objectFit: 'cover',
                opacity: 0.85,
              }}
            />
          </>
        ) : (
          <div className="lane-video-empty">
            <span>{projection.reason ?? '焊缝图片未框选 ROI：该模态在样本中标记为不可用'}</span>
          </div>
        )}
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
          <i
            key={t}
            className="lane-marker"
            style={{
              left: `${pctOf(t, duration)}%`,
              background: ready ? '#16343d' : '#c08a4e',
            }}
          />
        ))}
      </div>
      {projection.speed_source && SPEED_SOURCE_NOTE[projection.speed_source] && (
        <small className="lane-note">{SPEED_SOURCE_NOTE[projection.speed_source]}</small>
      )}
    </div>
  );
}
