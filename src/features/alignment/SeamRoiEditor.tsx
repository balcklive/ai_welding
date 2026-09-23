/**
 * 焊缝图片 ROI 标定面板（设计 §4.2/§4.3）。
 *
 * **全站只有这里能改 ROI**——分段页只读消费。本面板承担三件事：
 * 1) 在真实照片上拖拽框选并保存 ROI（`PUT …/calibration`，服务端按**图片真实像素**校验范围）；
 * 2) 回显已保存的 ROI——分段预览与正式任务读的是**同一份**，这是"所见即所得"的前提；
 * 3) 「不对焊缝图片进行分段」：写 `excluded: true`，此后图片模态不参与，
 *    分段只产时序/视频样本，manifest 里如实标记未参与 + 原因。
 *
 * **「不参与」与「未框选」必须在服务端分开**（`excluded` 布尔位）：两者都让图片模态不可用，
 * 但一个是用户已完成的决定（不该再催他去标定），一个是未完成的标定（必须给引导）。
 * 只把 ROI 清成 `null` 会把前者显示成后者——所以不参与走 `excluded`，不清 ROI。
 *
 * ROI 是**原始图片像素**坐标（不是归一化值）：服务端 `validate_calibration_patch` 拿图片宽高
 * 直接比大小，前端这里把鼠标位置按显示尺寸换算回像素——显示尺寸一变（缩放/换行）不影响结果。
 */
import { useRef, useState } from 'react';
import { AlertTriangle, Check, Crop, Trash2 } from 'lucide-react';
import type { Calibration, SeamRoi } from '../../api/types';

interface Props {
  /** 已保存的标定（父组件读一次，本面板只消费与回写）。 */
  calibration: Calibration | null;
  /** 焊缝照片的签名 URL；null = 没有图片或地址没取到。 */
  imageUrl: string | null;
  /** 图片地址读取失败的原因（`imageUrl` 为 null 时才有意义）。 */
  imageError: string | null;
  /** 标定/图片还在读取：此时不要下"该焊缝没有图片"这种结论。 */
  loading: boolean;
  saving: boolean;
  /** 保存失败的原因（服务端 400 的越界提示原样显示）。 */
  error: string | null;
  /** 保存：`{roi}` = 框选并参与分段，`{excluded:true}` = 明确不参与；成功返回 true。 */
  onSave: (patch: { roi: SeamRoi } | { excluded: true }) => Promise<boolean>;
}

/** 面板要显示的三种状态：已框选 / 明确不参与 / 还没框（未标定）。 */
type RoiState = 'framed' | 'excluded' | 'unset';

const MIN_ROI_PX = 2;

export function SeamRoiEditor({
  calibration, imageUrl, imageError, loading, saving, error, onSave,
}: Props) {
  const [draft, setDraft] = useState<SeamRoi | null>(null);
  const [dragging, setDragging] = useState(false);
  const [natural, setNatural] = useState<{ w: number; h: number } | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const startRef = useRef<{ x: number; y: number } | null>(null);

  const saved = calibration?.seam_image.roi ?? null;
  const excluded = calibration?.seam_image.excluded ?? false;
  // 「不参与」时服务端不再回 roi（整组被 excluded 取代），两者天然互斥
  const state: RoiState = excluded ? 'excluded' : saved ? 'framed' : 'unset';
  const roi = draft ?? saved;

  /** 鼠标位置 → 原始图片像素（按显示矩形等比换算，两端都钳在图片内）。 */
  const toPixels = (el: HTMLImageElement, clientX: number, clientY: number) => {
    const rect = el.getBoundingClientRect();
    const fx = Math.min(1, Math.max(0, (clientX - rect.left) / Math.max(1, rect.width)));
    const fy = Math.min(1, Math.max(0, (clientY - rect.top) / Math.max(1, rect.height)));
    return { x: fx * el.naturalWidth, y: fy * el.naturalHeight };
  };

  const roiFrom = (a: { x: number; y: number }, b: { x: number; y: number }): SeamRoi => {
    const x = Math.round(Math.min(a.x, b.x));
    const y = Math.round(Math.min(a.y, b.y));
    return { x, y, w: Math.round(Math.max(a.x, b.x)) - x, h: Math.round(Math.max(a.y, b.y)) - y };
  };

  const onDown = (e: React.PointerEvent<HTMLImageElement>) => {
    if (saving || !e.currentTarget.naturalWidth) return;
    e.currentTarget.setPointerCapture(e.pointerId);
    startRef.current = toPixels(e.currentTarget, e.clientX, e.clientY);
    setDraft(null);
    setNote(null);
    setDragging(true);
  };

  const onMove = (e: React.PointerEvent<HTMLImageElement>) => {
    if (!dragging || !startRef.current) return;
    setDraft(roiFrom(startRef.current, toPixels(e.currentTarget, e.clientX, e.clientY)));
  };

  const onUp = (e: React.PointerEvent<HTMLImageElement>) => {
    const start = startRef.current;
    if (!dragging || !start) return;
    setDragging(false);
    startRef.current = null;
    const next = roiFrom(start, toPixels(e.currentTarget, e.clientX, e.clientY));
    // 单击/误触不产生退化 ROI——服务端只校验范围，0 宽高会一路流进坐标映射
    setDraft(next.w >= MIN_ROI_PX && next.h >= MIN_ROI_PX ? next : null);
  };

  const save = async (patch: { roi: SeamRoi } | { excluded: true }) => {
    setNote(null);
    if (!await onSave(patch)) return;
    setDraft(null);
    setNote('roi' in patch
      ? '已保存 ROI：分段将按此框投影，分段页同步生效。'
      : '已保存：焊缝图片不参与分段，此后只生成时序 / 视频样本。');
  };

  const hasImageKey = Boolean(calibration?.seam_image.object_key);

  return (
    <section className="panel seam-roi-panel">
      <div className="studio-head">
        <div>
          <span className="file-badge"><Crop size={14} />焊缝图片 ROI 标定</span>
          <h2>框选焊缝条带（分段页只读，改动只在这里生效）</h2>
        </div>
        <span className={`track-availability ${state === 'framed' ? 'ok' : 'warn'}`}>
          {state === 'framed' ? '已框选' : state === 'excluded' ? '已选择不参与' : '未框选'}
        </span>
      </div>

      {error && (
        <div className="alignment-banner bad" role="alert"><AlertTriangle size={15} />{error}</div>
      )}
      {note && (
        <div className="alignment-banner ok" role="status"><Check size={15} />{note}</div>
      )}

      {imageUrl ? (
        <>
          <p className="preview-summary">
            在照片上按住拖拽框出焊缝条带，再点「保存 ROI」。保存前分段页一律视该模态为未参与——
            未保存的框不会影响样本产出。
          </p>
          <div className="seam-roi-stage">
            <div className="seam-roi-canvas">
              <img
                className="seam-roi-image"
                src={imageUrl}
                alt="焊缝照片（在此框选 ROI）"
                draggable={false}
                onLoad={(e) => setNatural({ w: e.currentTarget.naturalWidth, h: e.currentTarget.naturalHeight })}
                onPointerDown={onDown}
                onPointerMove={onMove}
                onPointerUp={onUp}
                onPointerCancel={onUp}
              />
              {roi && natural && natural.w > 0 && natural.h > 0 && (
                <i
                  className={`seam-roi-box${draft ? ' draft' : ''}`}
                  style={{
                    left: `${(roi.x / natural.w) * 100}%`,
                    top: `${(roi.y / natural.h) * 100}%`,
                    width: `${(roi.w / natural.w) * 100}%`,
                    height: `${(roi.h / natural.h) * 100}%`,
                  }}
                />
              )}
            </div>
          </div>
          <div className="seam-roi-meta">
            <span>图片尺寸：{natural ? `${natural.w} × ${natural.h} px` : '读取中…'}</span>
            <span>
              当前 ROI：
              {roi ? `x=${roi.x} y=${roi.y} w=${roi.w} h=${roi.h}`
                : state === 'excluded' ? '已选择不参与分段（分段只产时序 / 视频样本）'
                : '未框选（分段页会把该模态标为不可用）'}
            </span>
            {draft && <span className="warning-text">有未保存的改动</span>}
          </div>
          <div className="split-action-row">
            <button
              type="button"
              className="full-button"
              disabled={!draft || saving}
              aria-disabled={!draft || saving}
              onClick={() => draft && void save({ roi: draft })}
            >
              {saving ? '保存中…' : '保存 ROI'}
            </button>
            <button
              type="button"
              className="full-button studio-reset"
              disabled={saving || state === 'excluded'}
              aria-disabled={saving || state === 'excluded'}
              onClick={() => void save({ excluded: true })}
            >
              <Trash2 size={15} />
              {state === 'excluded' ? '已选择不对焊缝图片分段' : '不对焊缝图片进行分段'}
            </button>
          </div>
        </>
      ) : (
        <p className="seam-roi-empty">
          {loading ? '标定读取中…'
            : imageError ? `焊缝图片地址读取失败：${imageError}。图片模态不参与分段，时序 / 视频分段不受影响。`
            : hasImageKey ? '焊缝图片地址读取中…'
            : '该焊缝没有焊缝图片：无需标定，图片模态不参与分段，时序 / 视频分段不受影响。'}
        </p>
      )}
    </section>
  );
}
