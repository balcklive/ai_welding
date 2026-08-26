/**
 * src/api/datasets.ts — 数据集（§3.5 / §4.2）。
 *
 * - `dataset_id` 兼容 DB id / dataset_no。
 * - 构建任务异步：POST …/build-tasks 返回 `{job_id}`，经 `jobs.getJob` 轮询。
 */
import { request } from './client';
import type {
  Dataset,
  DatasetSource,
  DatasetVersion,
  DimensionStatus,
  LineageNode,
  ReadinessCheck,
} from './types';

/** 数据集列表（任务类型/样本数/完成度/版本/状态）。 */
export async function listDatasets(): Promise<Dataset[]> {
  return request<Dataset[]>('/datasets');
}

/** 新建数据集（同名 → 409）。 */
export async function createDataset(body: {
  name: string;
  task: string;
  source?: DatasetSource;
}): Promise<Dataset> {
  return request<Dataset>('/datasets', { method: 'POST', body });
}

/** 数据集详情：样本统计 / 训练验证测试划分 / 数据质量 / 更新时间。 */
export async function getDataset(id: string): Promise<Dataset> {
  return request<Dataset>(`/datasets/${id}`);
}

/** 输入维度状态（Voltage/GasSpeed/…/熔池视频）：已具备/缺失/必需。 */
export async function getDimensions(id: string): Promise<DimensionStatus[]> {
  return request<DimensionStatus[]>(`/datasets/${id}/dimensions`);
}

/** 模型适配检查（按任务动态返回检查项 + 可训练/暂不可训练）。 */
export async function getReadiness(id: string): Promise<ReadinessCheck> {
  return request<ReadinessCheck>(`/datasets/${id}/readiness`);
}

/** 数据集版本列表。 */
export async function listDatasetVersions(
  id: string,
): Promise<DatasetVersion[]> {
  return request<DatasetVersion[]>(`/datasets/${id}/versions`);
}

/** 新建版本（固定快照，不覆盖旧版，保证可复现）。 */
export async function createDatasetVersion(
  id: string,
  body: { name?: string; note?: string },
): Promise<DatasetVersion> {
  return request<DatasetVersion>(`/datasets/${id}/versions`, {
    method: 'POST',
    body,
  });
}

/** 版本详情（固定样本清单、划分）。 */
export async function getDatasetVersion(
  id: string,
  versionId: string,
): Promise<DatasetVersion> {
  return request<DatasetVersion>(`/datasets/${id}/versions/${versionId}`);
}

/** 数据血缘：原始焊缝 → 标注任务 → 数据集版本 → 模型训练。 */
export async function getLineage(id: string): Promise<LineageNode[]> {
  return request<LineageNode[]>(`/datasets/${id}/lineage`);
}

/** 数据集构建任务（异步：从切分样本/标注生成固定版本）。 */
export async function createBuildTask(
  id: string,
  versionId: string,
  source: DatasetSource,
): Promise<{ job_id: string }> {
  return request<{ job_id: string }>(
    `/datasets/${id}/versions/${versionId}/build-tasks`,
    { method: 'POST', body: { source } },
  );
}
