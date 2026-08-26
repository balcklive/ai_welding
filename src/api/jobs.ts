/**
 * src/api/jobs.ts — 通用任务轮询（§3.7 / §4.2）。
 *
 * 对齐/切分/标注/数据集构建/训练/测试/推理共用同一 Job 结构（§1.5），
 * 由 `useJob` 轮询此端点直到 succeeded / failed。
 */
import { request } from './client';
import type { Job } from './types';

/** 通用任务状态轮询（返回 Job 信封）。 */
export async function getJob(jobId: string): Promise<Job<unknown>> {
  return request<Job<unknown>>(`/jobs/${jobId}`);
}
