/**
 * src/api/sampleFeatures.ts — **切片级**特征提取（2026-10）。
 *
 * 与 `analysis.ts` 里的版本级特征（`extractFeatures` / `getLatestFeatureExtraction` …）是
 * **两条线**：那条是"焊缝一版数据一份 42 维"（供人看与报告导出），这条是"一个切片一份
 * 36 维"（供训练）。后端见 `backend/app/api/v1/sample_features.py`。
 *
 * 36 维 = 时序 28（cur 8 / vol 8 / gas 6 / wir 6）+ 视觉 8（几何 4 / 纹理 4），**无声音组**
 * ——切片 manifest 自己就写着 `audio.available = False`，音频上传也已在 2026-10 收口拒收。
 *
 * `taskId` 用创建分段任务时拿到的 **job_id**（后端双解析 job_uid / DB id）；前端一律传 job_uid。
 */
import { request } from './client';
import type {
  SampleFeatureDetail,
  SampleFeaturePage,
  SampleFeatureTask,
} from './types';

/** 该焊缝**可提取切片特征**的分段任务（已完成 + v3），工作台的入口列表。 */
export async function listSampleFeatureTasks(weldId: string): Promise<SampleFeatureTask[]> {
  const data = await request<{ items: SampleFeatureTask[] }>(
    `/welds/${weldId}/sample-feature-tasks`,
  );
  return data.items ?? [];
}

/** 建异步提取任务；相同入参在运行中/已完成时后端**幂等复用**同一 Job（返回同一个 job_id）。
 *
 *  `normalization` 只影响**导出文件**：落库的权威向量恒为原始值——逐切片 Z-Score 会把每片
 *  各自减均值、抹掉区分切片的那批量（电流均值/RMS/气体水平），标准化属于训练侧。 */
export async function createSampleFeatureExtraction(
  taskId: string,
  body: { normalization?: string } = {},
): Promise<{ job_id: string }> {
  return request<{ job_id: string }>(`/split-tasks/${taskId}/sample-feature-extractions`, {
    method: 'POST',
    body,
  });
}

/** 切片特征状态分页 + 进度。`filter='unextracted'` 只看未提取（服务端过滤）。
 *
 *  行里**不含 36 个数值**——要数值走 `getSampleFeature`。未提取是 `extracted:false`，不是 404。 */
export async function listSampleFeatures(
  taskId: string,
  params: { page?: number; page_size?: number; filter?: 'all' | 'unextracted' } = {},
): Promise<SampleFeaturePage> {
  return request<SampleFeaturePage>(`/split-tasks/${taskId}/sample-features`, {
    query: params,
  });
}

/** 单切片的完整向量；该片**还没提取**时 `feature` 为 `null`（「还没跑」是正常状态）。 */
export async function getSampleFeature(
  taskId: string,
  sampleId: number,
): Promise<{ sample_id: number; feature: SampleFeatureDetail | null }> {
  return request(`/split-tasks/${taskId}/sample-features/${sampleId}`);
}

/** 导出该任务的 n×36 矩阵（行序与服务端一致 = 时间窗升序），返回预签名下载地址。 */
export async function exportSampleFeatures(
  taskId: string,
  format: 'JSON' | 'CSV' = 'JSON',
): Promise<{ format: string; object_key: string; url: string }> {
  return request(`/split-tasks/${taskId}/sample-features/export`, { query: { format } });
}
