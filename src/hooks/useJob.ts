/**
 * src/hooks/useJob.ts — 通用异步任务轮询钩子（§4.3 横切工具 / §1.5）。
 *
 * 对齐/切分/标注/数据集构建/训练/测试/推理共用同一 Job 结构（§1.5），
 * 各域模块返回 `{job_id}` 后交给本钩子轮询 `jobs.getJob(jobId)`：
 * 每 `intervalMs`（默认 1500ms）拉一次，直到 `succeeded` / `failed` 自动停。
 *
 * - `jobId` 为 `null` → 不轮询，并清空上一次结果；
 * - `jobId` 变化 → 自动重新开始轮询（旧的在途响应会被丢弃，防串任务）；
 * - 组件卸载 → 清定时器并置 unmount 标志，杜绝卸载后 setState；
 * - `start()` / `stop()` 供调用方手动控制（幂等）。
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { getJob } from '../api/jobs';
import type { Job } from '../api/types';

export interface UseJobReturn<T> {
  /** 最近一次轮询到的 Job；从未拉取/已停止后为 `null`。 */
  job: Job<T> | null;
  /** 派生自 `job`；无 job 时为 `null`。 */
  status: Job<T>['status'] | null;
  /** 派生自 `job`；无 job 时为 0。 */
  progress: number;
  /** 派生自 `job`；仅 `succeeded` 后才有值，否则 `null`。 */
  result: T | null;
  /** 最近一次请求失败的错误（网络 / 非 0 信封码）；成功时清空。 */
  error: unknown;
  /** 手动开始轮询（jobId 为 null 时为空操作）。 */
  start: () => void;
  /** 手动停止轮询（保留当前 job/result 状态，不重置）。 */
  stop: () => void;
}

export function useJob<T = unknown>(
  jobId: string | null,
  intervalMs = 1500,
): UseJobReturn<T> {
  const [job, setJob] = useState<Job<T> | null>(null);
  const [error, setError] = useState<unknown>(null);

  // refs：让 interval 回调始终读到最新 jobId / intervalMs，不重建定时器
  const jobIdRef = useRef<string | null>(jobId);
  const intervalMsRef = useRef(intervalMs);
  // 卸载后置 false，setState 前检查，避免 React 18 卸载警告/竞态
  const mountedRef = useRef(true);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  jobIdRef.current = jobId;
  intervalMsRef.current = intervalMs;

  const stop = useCallback(() => {
    if (timerRef.current !== null) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const start = useCallback(() => {
    mountedRef.current = true;
    stop();
    const id = jobIdRef.current;
    if (!id) return;

    const tick = async () => {
      if (!mountedRef.current) return;
      const current = jobIdRef.current;
      if (!current) return;
      try {
        const next = await getJob(current);
        // 卸载或 jobId 已变 → 丢弃在途响应，防串任务/卸载后 setState
        if (!mountedRef.current || jobIdRef.current !== current) return;
        setJob(next as Job<T>);
        setError(null);
        if (next.status === 'succeeded' || next.status === 'failed') {
          stop();
        }
      } catch (err) {
        if (!mountedRef.current || jobIdRef.current !== current) return;
        setError(err);
      }
    };

    // 立即首拉（不等第一个 interval），再定时轮询
    void tick();
    timerRef.current = setInterval(tick, intervalMsRef.current);
  }, [stop]);

  // jobId 驱动：非空 → 自动开始；变 null → 停止并清空
  useEffect(() => {
    if (jobId) {
      start();
    } else {
      stop();
      setJob(null);
      setError(null);
    }
    return stop;
  }, [jobId, start, stop]);

  // 卸载守卫
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      stop();
    };
  }, [stop]);

  const status = job ? job.status : null;
  const progress = job ? job.progress : 0;
  const result = job ? job.result : null;

  return { job, status, progress, result, error, start, stop };
}
