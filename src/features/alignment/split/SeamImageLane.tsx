/**
 * 焊缝图片投影带（设计 §3.1.2/§4.4）：只显示**已标定的 ROI 区域**，边界按 `px(t)` 落下。
 *
 * 这条轨的横轴**不是时间，是沿焊缝的长度**：服务端把每段时间窗经弧长积分投影成 ROI 长边上
 * 的像素区间（`seam_image.spatial_range`），照片按 `roi.x/roi.w` 反算偏移与放大倍率铺在轨道里。
 * 所以一条边界线落下的位置，就是该样本那张图片切片被裁下来的位置——两边是同一份坐标。
 *
 * **不能整张照片铺满轨道**：ROI 之外的部分在时间轴上没有对应关系（照片宽度 ≠ 有效焊接区间），
 * 铺满会让用户框的 ROI 完全看不出效果，边界线也会落在照片上错误的位置。
 *
 * **只读**——ROI 只能在对齐页框选（§4.3）。这里是"分段页不可编辑标定"最要紧的一条：
 * 若允许在分段页拖 ROI，屏幕上的边界就不再能由服务端复现，"所见即所得"失效。
 *
 * **未框选 ROI 时绝不铺原图**：没有 ROI 就没有长度↔时间映射，此时把整张焊缝原图摊在时间轴上
 * 会让人以为这一段样本带着图片——而 manifest 里它其实不可用。故这里只给"未参与"与去对齐页的引导。
 */
import { useState } from 'react';
import type { SplitPreview, SplitPreviewWindow } from '../../../api/types';

interface Props {
  projection: SplitPreview['timeline']['seam_image_projection'];
  windows: SplitPreviewWindow[];
  imageUrl: string | null;
  selectedIndex: number | null;
}

/** 顶掉 Tailwind preflight 的 `img{max-width:100%;height:auto}`——它会把下面按 ROI 算出的
 *  宽度截成轨道宽度、高度改成 auto，ROI 裁切整个失真（`.seam-lane-photo` 里再兜一层）。 */
const NO_CLAMP = { maxWidth: 'none', maxHeight: 'none' } as const;

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

export function SeamImageLane({ projection, windows, imageUrl, selectedIndex }: Props) {
  const ready = Boolean(projection.available && projection.roi && imageUrl);
  const roi = projection.roi;
  const [natural, setNatural] = useState<{ w: number; h: number } | null>(null);
  // 只读 + 未框选 → 该模态**不参与**（而非"暂时画不出来"）
  const notParticipating = !ready && Boolean(projection.object_key);
  const badge = projection.excluded ? '已选择不参与' : projection.object_key ? '未参与' : '无图片';

  /** ROI 像素 → 轨道百分比。轨道左端 = `roi.x`，右端 = `roi.x + roi.w`。 */
  const pxPct = (px: number) => (roi ? ((px - roi.x) / roi.w) * 100 : 0);

  // 边界 = 每段起点的像素位置 + 最后一段的终点（半开区间，相邻段不重复算边界）
  const bounds: number[] = [];
  for (const w of windows) {
    const px = w.seam_image.spatial_range?.start_px;
    if (typeof px === 'number') bounds.push(px);
  }
  const lastEnd = windows.length
    ? windows[windows.length - 1].seam_image.spatial_range?.end_px
    : undefined;
  if (typeof lastEnd === 'number') bounds.push(lastEnd);

  const selected = windows.find((w) => w.index === selectedIndex)?.seam_image.spatial_range ?? null;

  // 照片按 ROI 反算：ROI 那一块正好铺满轨道（`roi.w` 像素 → 轨道宽度），再整体左上偏移
  const photo = ready && roi && natural && natural.w > 0 && natural.h > 0
    ? {
      width: `${(natural.w / roi.w) * 100}%`,
      height: `${(natural.h / roi.h) * 100}%`,
      left: `${-(roi.x / roi.w) * 100}%`,
      top: `${-(roi.y / roi.h) * 100}%`,
    }
    : null;

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
          <img
            className="seam-lane-photo"
            src={imageUrl ?? ''}
            alt="焊缝照片投影（只显示已标定的 ROI 区域）"
            draggable={false}
            onLoad={(e) => setNatural({ w: e.currentTarget.naturalWidth, h: e.currentTarget.naturalHeight })}
            // 尺寸算出来前先占位（不用 `display:none`，否则 onLoad 永远不触发）
            style={photo
              ? { position: 'absolute', ...NO_CLAMP, ...photo }
              : { position: 'absolute', visibility: 'hidden' }}
          />
        ) : (
          <div className="lane-video-empty seam-lane-empty">
            <span>{unavailableText(projection, Boolean(imageUrl))}</span>
            {notParticipating && !projection.excluded && (
              <a className="seam-lane-link" href="#/analysis/alignment">前往多模态对齐页框选并保存 ROI →</a>
            )}
          </div>
        )}
        {ready && roi && selected && (
          <div
            className="cut-effective"
            style={{
              position: 'absolute', top: 0, bottom: 0,
              left: `${pxPct(selected.start_px)}%`,
              width: `${Math.max(0, pxPct(selected.end_px) - pxPct(selected.start_px))}%`,
              opacity: 0.22,
            }}
          />
        )}
        {ready && roi && bounds.map((px) => (
          <i
            key={px}
            className="lane-marker"
            style={{ left: `${pxPct(px)}%`, background: '#16343d' }}
          />
        ))}
      </div>
      <small className="lane-note">
        本页只读：ROI 改动只能去「多模态对齐」页做，预览与正式任务用的是同一份标定。
        这条带的横轴是**沿焊缝的长度**，与上方时间轴只在匀速假设下才重合。
      </small>
      {projection.speed_source && SPEED_SOURCE_NOTE[projection.speed_source] && (
        <small className="lane-note">{SPEED_SOURCE_NOTE[projection.speed_source]}</small>
      )}
    </div>
  );
}
