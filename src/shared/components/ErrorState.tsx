import { AlertTriangle, RefreshCw } from 'lucide-react';
import { toUserMessage } from '../lib/errors';

/**
 * 统一的错误态（T3.1）：图标 + 主文案 + 原因 + 重试。
 *
 * 替代"演示数据兜底"——接口失败时展示明确原因，而不是伪装成有数据。
 * 文案由 `toUserMessage(error, scene)` 生成，调用方只给场景名。
 */
export function ErrorState({
  scene,
  error,
  onRetry,
}: {
  /** 场景名，用于拼「{场景}失败…」，如 "加载数据集"。 */
  scene: string;
  /** 捕获到的异常（`ApiError` 或其他）。 */
  error: unknown;
  /** 给了才渲染"重试"按钮。 */
  onRetry?: () => void;
}) {
  const { message, reason } = toUserMessage(error, scene);
  return (
    <div className="error-state" role="alert">
      <AlertTriangle size={23} />
      <strong>{message}</strong>
      {reason && <p className="error-state-reason">{reason}</p>}
      {onRetry && (
        <button className="outline-button" type="button" onClick={onRetry}>
          <RefreshCw size={14} />重试
        </button>
      )}
    </div>
  );
}
