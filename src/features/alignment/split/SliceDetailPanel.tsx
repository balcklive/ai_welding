/**
 * 选中切片详情（设计 §4.3 下半区）：时间窗 + 时序局部波形 + 视频帧时刻 + 焊缝图片切片 + 缺失说明。
 *
 * 波形是把服务端已降采样的轨道**按选中窗口裁剪**得到的读派生视图——不额外发请求，
 * 也不本地重算任何规则。视频实际帧与焊缝图片切片由分段 Job 产出（§2.2：预览阶段不批量
 * 生成媒体文件），这里给时刻与对象键；生成后可按对象键下载。
 */
import type { SplitPreview, SplitPreviewWindow } from '../../../api/types';
import { chanColorOf } from '../../analysis/signals/chartData';
import { fmtRange, pctOf, timePath, trackRange } from './splitTypes';

interface Props {
  window: SplitPreviewWindow | null;
  preview: SplitPreview;
  /** 该窗口已生成时（任务跑完）的切片对象键，按类型分。 */
  cropKey?: string | null;
  cropUrl?: string | null;
  onOpenKey?: (key: string) => void;
}

export function SliceDetailPanel({ window, preview, cropKey, cropUrl, onOpenKey }: Props) {
  if (!window) {
    return (
      <section className="panel">
        <div className="studio-head"><div><span className="file-badge">切片详情</span><h2>未选择切片</h2></div></div>
        <p className="preview-summary">点击上方轨道边界或切片卡片选择一个时间窗。</p>
      </section>
    );
  }
  const duration = preview.timeline.duration;
  const localTracks = preview.timeline.signal.tracks.map((track) => {
    const times: number[] = [];
    const values: number[] = [];
    for (let i = 0; i < track.times.length; i += 1) {
      if (track.times[i] >= window.start - 1e-9 && track.times[i] <= window.end + 1e-9) {
        times.push(track.times[i]);
        values.push(track.values[i]);
      }
    }
    return { ...track, times, values };
  });
  const span = Math.max(window.end - window.start, 1e-6);

  return (
    <section className="panel">
      <div className="studio-head">
        <div>
          <span className="file-badge">切片 #{window.index}</span>
          <h2>{fmtRange(window.start, window.end, 3)}</h2>
        </div>
        <span className="studio-dur">{window.duration.toFixed(3)}s</span>
      </div>

      {localTracks.map((track) => {
        const [lo, hi] = trackRange(track);
        const color = chanColorOf(track.id);
        return (
          <div className="lane" key={track.id}>
            <div className="lane-label">
              <i className="lane-dot" style={{ background: color }} />
              {track.name}
              <span className="lane-meta">{track.values.length} 点</span>
            </div>
            <div className="lane-track">
              {track.values.length > 1 ? (
                <svg className="lane-wave" viewBox="0 0 1000 40" preserveAspectRatio="none" aria-hidden>
                  <path
                    d={timePath(
                      // 局部视图横轴按窗口自身的起点对齐（不是整段时长）
                      track.times.map((t) => t - window.start),
                      track.values, lo, hi, span, 1000, 40,
                    )}
                    fill="none" stroke={color} strokeWidth={1.4} vectorEffect="non-scaling-stroke"
                  />
                </svg>
              ) : (
                <div className="lane-video-empty"><span>该窗口内没有降采样点</span></div>
              )}
            </div>
          </div>
        );
      })}

      <ModalityNote
        title="视频"
        slot={window.video}
        ready={window.video.available}
        detail={window.video.available
          ? `帧号 ${window.video.start_frame}–${window.video.end_frame} · fps ${window.video.fps} · offset ${window.video.offset_seconds?.toFixed(3)}s`
          : null}
        extra={window.video.available
          ? `首/中/末帧时刻：${(window.video.keyframes ?? []).map((k) => k.at.toFixed(2)).join(' / ') || '无'}`
          : null}
        calibrated={window.video.calibrated}
      />

      {/* 本段代表帧：预览给短期 URL，产物路径给对象键（点开看）。取不到就写原因，不占位。 */}
      {window.video.frame?.available && window.video.frame.url ? (
        <figure className="slice-frame">
          <img src={window.video.frame.url} alt={`分段 #${window.index} 的视频代表帧`} />
          <figcaption>
            本段代表帧（窗口中点）：t_signal {window.video.frame.t_signal?.toFixed(3)}s ·
            t_video {window.video.frame.t_video?.toFixed(3)}s · 视频帧号 {window.video.frame.frame_no}
          </figcaption>
        </figure>
      ) : window.video.frame?.available && window.video.frame.object_key ? (
        <button
          type="button"
          className="artifact-row"
          onClick={() => onOpenKey?.(window.video.frame!.object_key!)}
        >
          <span className="artifact-icon">帧</span>
          <div><strong>打开本段视频代表帧</strong><small>{window.video.frame.object_key}</small></div>
        </button>
      ) : (
        <p className="preview-summary" style={{ marginTop: 8 }}>
          本段无视频代表帧：{window.video.frame?.reason ?? window.video.reason ?? '视频不可用'}
        </p>
      )}

      <ModalityNote
        title="焊缝图片"
        slot={window.seam_image}
        ready={window.seam_image.available}
        detail={window.seam_image.available && window.seam_image.spatial_range
          ? `沿 ROI 长边投影：${window.seam_image.spatial_range.start_px.toFixed(1)} – ${window.seam_image.spatial_range.end_px.toFixed(1)} px`
          : null}
        calibrated={window.seam_image.calibrated}
        missingLabel={window.seam_image.excluded ? '未参与本轮分段' : undefined}
      />

      {(cropKey || cropUrl) && (
        <div className="artifact-list">
          {cropUrl && (
            <img
              src={cropUrl}
              alt={`切片 #${window.index} 的焊缝图片`}
              style={{ width: '100%', borderRadius: 6, display: 'block' }}
            />
          )}
          {cropKey && (
            <button type="button" className="artifact-row" onClick={() => onOpenKey?.(cropKey)}>
              <span className="artifact-icon">图</span>
              <div><strong>打开图片切片</strong><small>{cropKey}</small></div>
            </button>
          )}
        </div>
      )}

      <p className="preview-summary" style={{ marginTop: 12 }}>
        该窗口占全段时间轴的 {pctOf(window.start, duration).toFixed(1)}% – {pctOf(window.end, duration).toFixed(1)}%。
        各模态缺失原因见上方轨道角标——缺失**不阻止分段**，但会如实写进样本 manifest。
      </p>
    </section>
  );
}

function ModalityNote({
  title, slot, ready, detail, extra, calibrated, missingLabel,
}: {
  title: string;
  slot: { reason?: string | null };
  ready: boolean;
  detail: string | null;
  extra?: string | null;
  calibrated?: boolean;
  /** 不可用时的前缀；默认「不可用」，被用户排除的模态用「未参与本轮分段」。 */
  missingLabel?: string;
}) {
  return (
    <div className="split-ratio-note" style={{ marginTop: 12 }}>
      <span className="file-badge">{title}</span>
      <small>
        {ready ? (
          <>
            {detail}
            {extra ? <><br />{extra}</> : null}
            <br />标定：{calibrated ? '已标定' : '未标定（关键帧按假设对齐，见上方警告）'}
          </>
        ) : (
          <>{missingLabel ?? '不可用'}：{slot.reason ?? '源未附加'}</>
        )}
      </small>
    </div>
  );
}
