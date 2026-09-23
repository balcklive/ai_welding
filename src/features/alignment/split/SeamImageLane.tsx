/**
 * 焊缝图片投影带（设计 §4.4/§3.1.2）：整张照片铺开为背景，边界按 `px(t)` 垂直落在照片上。
 *
 * **只读**——ROI 只能在对齐页框选（§4.3）。这里是"分段页不可编辑标定"最要紧的一条：
 * 若允许在分段页拖 ROI，屏幕上的边界就不再能由服务端复现，"所见即所得"失效。
 *
 * **未框选 ROI 时绝不铺原图**：没有 ROI 就没有长度↔时间映射，此时把整张焊缝原图摊在时间轴上
 * 会让人以为这一段样本带着图片——而 manifest 里它其实不可用。故这里只给"未参与"与去对齐页的引导。
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

/** 求值顺序即语义：有 ROI 且图能加载才投影；否则按"为什么没有"给不同的话。
 *
 * 「用户明确选择不参与」与「还没框 ROI」必须分开说：前者是已完成的决定，再催他去标定是错的；
 * 后者是未完成的标定，必须给去对齐页的引导——这是业务规则里"必须先框选并保存 ROI"的落点。
 */
function unavailableText(projection: Props['projection'], hasUrl: boolean): string {
  if (!projection.object_key) {
    return '该焊缝没有焊缝图片：图片模态不参与本轮分段，时序 / 视频样本照常生成。';
  }
  if (projection.excluded) {
    return `${projection.reason ?? '已选择不对焊缝图片进行分段'}：本轮只生成时序 / 视频样本。`;
  }
  if (!projection.roi) {
    return `未参与分段：${projection.reason ?? '焊缝图片未框选 ROI'}。必须先到「多模态对齐」页框选并保存 ROI，才可让焊缝图片参与分段。`;
  }
  if (!hasUrl) return '焊缝图片地址未取到，该模态在本轮分段中不可用；请到「多模态对齐」页确认图片可读。';
  return projection.reason ?? '焊缝图片在本轮分段中不可用。';
}

export function SeamImageLane({ projection, imageUrl, duration, boundaries, selected }: Props) {
  const ready = projection.available && projection.roi && imageUrl;
  // 只读 + 未框选 → 该模态**不参与**（而非"暂时画不出来"）
  const notParticipating = !ready && Boolean(projection.object_key);
  const badge = projection.excluded ? '已选择不参与' : projection.object_key ? '未参与' : '无图片';
  return (
    <div className="lane">
      <div className="lane-label">
        <i className="lane-dot" style={{ background: '#c08a4e' }} />
        焊缝图片
        <span className="track-availability ok" hidden={!ready}>已投影</span>
        {!ready && <span className="track-availability warn">{badge}</span>}
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
          <div className="lane-video-empty seam-lane-empty">
            <span>{unavailableText(projection, Boolean(imageUrl))}</span>
            {notParticipating && !projection.excluded && (
              <a className="seam-lane-link" href="#/analysis/alignment">前往多模态对齐页框选并保存 ROI →</a>
            )}
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
      <small className="lane-note">
        本页只读：ROI 改动只能去「多模态对齐」页做，预览与正式任务用的是同一份标定。
      </small>
      {projection.speed_source && SPEED_SOURCE_NOTE[projection.speed_source] && (
        <small className="lane-note">{SPEED_SOURCE_NOTE[projection.speed_source]}</small>
      )}
    </div>
  );
}
