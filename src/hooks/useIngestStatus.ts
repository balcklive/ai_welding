/**
 * src/hooks/useIngestStatus.ts — 登记链路状态的轮询（T4.4 / R2）。
 *
 * 「登记成功」≠「导入完成」：CSV 挂载后后端异步导入信号，核验/分析要等导入完成才读得到真数据。
 * 状态由后端 `GET /registrations/{id}/ingest-status` **从已有数据推导**，所以刷新页面、换设备
 * 看到的都一样（这也是 R2 要求的"跨刷新恢复"）。
 *
 * 只在 `importing` 时继续轮询（其余状态是终态）；请求失败就停——错误态由页面展示，
 * 不该每 2 秒刷一次错误。用递归 `setTimeout` 而不是 `setInterval`：终态 / 失败天然不再排期。
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { getIngestStatus } from '../api/welds';
import type { IngestStatus } from '../api/types';

/** 登记链路状态 → 界面文案（四种静态态，不显示百分比、不预测耗时；登记页与数据详情共用）。 */
export function ingestStatusText(status: IngestStatus | null): string {
  switch (status?.status) {
    case 'awaiting_upload': return '等待上传文件';
    case 'importing': return '导入中…';
    case 'failed': return '导入失败';
    case 'ready': return status.csv_total > 0 ? '可分析（信号已导入）' : '可分析（无需导入）';
    default: return '读取中…';
  }
}

export interface UseIngestStatusReturn {
  status: IngestStatus | null;
  error: unknown;
  /** 重新拉一次（导入失败后点「重新导入」、或用户手动重试）。 */
  refresh: () => void;
}

export function useIngestStatus(
  registrationId: string | null,
  intervalMs = 2000,
): UseIngestStatusReturn {
  const [status, setStatus] = useState<IngestStatus | null>(null);
  const [error, setError] = useState<unknown>(null);
  const mountedRef = useRef(true);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const idRef = useRef<string | null>(registrationId);
  idRef.current = registrationId;

  const stop = useCallback(() => {
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const tick = useCallback(async () => {
    const id = idRef.current;
    if (!id || !mountedRef.current) return;
    try {
      const next = await getIngestStatus(id);
      // 卸载或登记已切换 → 丢弃在途响应
      if (!mountedRef.current || idRef.current !== id) return;
      setStatus(next);
      setError(null);
      if (next.status === 'importing') timerRef.current = setTimeout(tick, intervalMs);
    } catch (err) {
      if (!mountedRef.current || idRef.current !== id) return;
      setError(err);
      setStatus(null);
    }
  }, [intervalMs]);

  const refresh = useCallback(() => {
    stop();
    void tick();
  }, [stop, tick]);

  useEffect(() => {
    mountedRef.current = true;
    if (!registrationId) {
      stop();
      setStatus(null);
      setError(null);
      return stop;
    }
    void tick();
    return () => {
      mountedRef.current = false;
      stop();
    };
  }, [registrationId, tick, stop]);

  return { status, error, refresh };
}
