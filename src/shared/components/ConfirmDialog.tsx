import type { ReactNode } from 'react';

/** 弹窗里列出的一条「将要发生什么」：提交前是默认值清单，删除前是影响范围。 */
export interface ConfirmItem {
  label: string;
  value?: ReactNode;
}

/**
 * 确认弹窗（T4a 提交前确认 / T7 危险操作确认共用）。**不用浏览器原生 confirm**（Q21）。
 *
 * - `tone="danger"` 用危险按钮（删除类操作）；默认走主按钮。
 * - `items` 逐条列出影响范围或默认值；调用方负责判断"能不能确认"（`confirmDisabled`），
 *   例如有阻塞引用时置灰并另给原因文案。
 * - 样式复用现有 `.app-dialog*`（与 `TextDialog` 同一套外观）。
 */
export function ConfirmDialog({
  title,
  description,
  items,
  confirmLabel = '确认',
  cancelLabel = '取消',
  tone = 'default',
  confirmDisabled = false,
  onConfirm,
  onCancel,
}: {
  title: string;
  description?: ReactNode;
  items?: ConfirmItem[];
  confirmLabel?: string;
  cancelLabel?: string;
  tone?: 'default' | 'danger';
  confirmDisabled?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <div className="app-dialog-backdrop" role="presentation" onClick={onCancel}>
      <div className="app-dialog" role="dialog" aria-modal="true" aria-label={title} onClick={(event) => event.stopPropagation()}>
        <div className="app-dialog-head"><h2>{title}</h2><button className="icon-button" onClick={onCancel} aria-label="关闭">×</button></div>
        {description && <p className="dialog-description">{description}</p>}
        {items && items.length > 0 && (
          <ul className="dialog-items">
            {items.map((item) => (
              <li key={item.label}><span>{item.label}</span><strong>{item.value ?? '—'}</strong></li>
            ))}
          </ul>
        )}
        <div className="app-dialog-actions">
          <button className="outline-button" type="button" onClick={onCancel}>{cancelLabel}</button>
          <button className={tone === 'danger' ? 'danger-button' : 'primary-button'} type="button" onClick={onConfirm} disabled={confirmDisabled}>{confirmLabel}</button>
        </div>
      </div>
    </div>
  );
}
