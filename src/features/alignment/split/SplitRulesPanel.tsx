/**
 * 固定时间切分规则面板（设计 §4.3 右侧）：秒级规则 + **只读标定摘要**。
 *
 * 标定在这里只能看、不能改（§4.3）：改 offset/ROI 要去对齐页。这是"所见即所得"的守卫——
 * 分段页上任何一个边界都必须能在服务端复现，多一个本地可改的标定参数就破坏了这一点。
 */
import type { SplitPreview } from '../../../api/types';
import type { RulesDraft } from './splitTypes';

interface Props {
  draft: RulesDraft;
  /** 字段级错误（§4.6：时长/步长 ≤ 0 时不在本地发请求，直接给字段错误）。 */
  fieldError: string | null;
  preview: SplitPreview | null;
  previewError: string | null;
  previewing: boolean;
  /** 草稿与最后一次成功预览不一致 → 禁止创建（§7.2）。 */
  stale: boolean;
  creating: boolean;
  onDraft: (patch: Partial<RulesDraft>) => void;
  onCreate: () => void;
  onGoToAlignment: () => void;
}

export function SplitRulesPanel({
  draft, fieldError, preview, previewError, previewing, stale, creating,
  onDraft, onCreate, onGoToAlignment,
}: Props) {
  const video = preview?.modalities.video;
  const seam = preview?.modalities.seam_image;
  const canCreate = Boolean(preview) && !stale && !previewing && !fieldError && !creating;

  return (
    <section className="panel split-preview-panel">
      <div className="studio-head">
        <div>
          <span className="file-badge">切分规则</span>
          <h2>固定时间窗口</h2>
        </div>
        {previewing && <span className="preview-summary">计算中…</span>}
      </div>

      <label className="split-field-label" htmlFor="split-window">切片时长（秒）</label>
      <input
        id="split-window"
        className="split-control"
        type="number" min={0.1} step={0.1}
        value={draft.windowSeconds}
        onChange={(e) => onDraft({ windowSeconds: Number(e.target.value) })}
      />

      <label className="split-field-label" htmlFor="split-stride">切片步长（秒）</label>
      <input
        id="split-stride"
        className="split-control"
        type="number" min={0.1} step={0.1}
        value={draft.strideSeconds}
        onChange={(e) => onDraft({ strideSeconds: Number(e.target.value) })}
      />

      <label className="split-field-label" htmlFor="split-start">有效事件起点（秒）</label>
      <input
        id="split-start"
        className="split-control"
        type="number" step={0.01}
        value={draft.eventStart ?? ''}
        placeholder="留空 = 用系统检测的焊接段"
        onChange={(e) => onDraft({ eventStart: e.target.value === '' ? null : Number(e.target.value) })}
      />

      <label className="split-field-label" htmlFor="split-end">有效事件终点（秒）</label>
      <input
        id="split-end"
        className="split-control"
        type="number" step={0.01}
        value={draft.eventEnd ?? ''}
        placeholder="留空 = 用系统检测的焊接段"
        onChange={(e) => onDraft({ eventEnd: e.target.value === '' ? null : Number(e.target.value) })}
      />

      <label className="split-field-label">事件缓冲</label>
      <label className="modal-check" style={{ padding: '8px 10px' }}>
        <input
          type="checkbox"
          checked={draft.keepEventBuffer}
          onChange={(e) => onDraft({ keepEventBuffer: e.target.checked })}
        />
        <span className="modal-check-box" />
        <b>在事件边界外扩缓冲</b>
        <small>先加缓冲再切窗；关闭时为 0</small>
      </label>
      {draft.keepEventBuffer && (
        <input
          className="split-control"
          type="number" min={0} step={0.1}
          aria-label="缓冲秒数"
          value={draft.bufferSeconds}
          onChange={(e) => onDraft({ bufferSeconds: Number(e.target.value) })}
        />
      )}

      <label className="split-field-label" htmlFor="split-tail">尾片策略</label>
      <select
        id="split-tail"
        className="split-control"
        value={draft.tailPolicy}
        onChange={(e) => onDraft({ tailPolicy: e.target.value as 'drop' | 'keep' })}
      >
        <option value="drop">丢弃不足一个完整时长的末尾窗口（默认）</option>
        <option value="keep">保留不等长尾片</option>
      </select>

      {fieldError && <p className="toolbar-error" role="alert">{fieldError}</p>}
      {previewError && <p className="toolbar-error" role="alert">{previewError}</p>}

      <div className="split-estimate studio-estimate">
        <strong>{preview ? preview.sample_count : '—'}</strong>
        <span>预计切片数</span>
        <small>
          {preview
            ? `重叠 ${preview.overlap_seconds.toFixed(2)} 秒（${(preview.overlap_ratio * 100).toFixed(0)}%）· 尾片 ${preview.tail_policy === 'keep' ? '保留' : '丢弃'}`
            : '规则改动后自动重新预览'}
        </small>
      </div>

      {/* 标定状态：**只读**摘要 + 跳转（§4.3） */}
      <div className="split-ratio-note">
        <span className="file-badge">标定状态（只读）</span>
        <small>
          视频零点：{video?.calibrated ? '已标定' : '未标定'}
          {video && !video.available ? '（视频不可用）' : ''}
          <br />
          焊缝图片 ROI：{seam?.calibrated ? '已框选' : '未框选'}
          {seam?.speed_source ? `（速度来源 ${seam.speed_source}）` : ''}
        </small>
        <button type="button" className="full-button studio-reset" onClick={onGoToAlignment}>
          前往对齐页标定
        </button>
      </div>

      {(preview?.warnings.length ?? 0) > 0 && (
        <div className="alignment-banner warn" role="status">
          <div>
            {preview?.warnings.map((w) => <div key={w}>{w}</div>)}
          </div>
        </div>
      )}

      <div className="split-action-row">
        <button
          type="button"
          className="full-button"
          disabled={!canCreate}
          aria-disabled={!canCreate}
          onClick={onCreate}
        >
          {creating ? '创建中…' : '确认生成样本'}
        </button>
      </div>
      {stale && <p className="toolbar-error" role="status">规则已改动，正在重新预览——请等预览完成后再生成。</p>}
    </section>
  );
}
