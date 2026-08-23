/**
 * src/api/models.ts — 模型中心（§3.6 / §4.2）。
 *
 * - 训练/测试/推理均异步：POST 返回 `{job_id}`，前端轮询对应 GET 端点（Job 结构）。
 * - `getTrainingLogs` 返回纯文本（信封 data 为字符串）。
 */
import { request } from './client';
import type {
  InferenceRequest,
  InferenceResult,
  Job,
  Model,
  ModelSummary,
  ModelVersion,
  TestConfig,
  TestResult,
  TrainingConfig,
  TrainingResult,
} from './types';

/** 模型仓库列表 + 汇总（总数/生产候选/最近训练/GPU 资源）。 */
export async function listModels(): Promise<{
  summary: ModelSummary;
  models: Model[];
}> {
  return request<{ summary: ModelSummary; models: Model[] }>('/models');
}

/** 模型详情（含全部版本列表）。 */
export async function getModel(id: string): Promise<Model> {
  return request<Model>(`/models/${id}`);
}

/** 新建模型（登记模型仓库条目，同名 → 409）。 */
export async function createModel(body: {
  name: string;
  type: string;
  description?: string;
}): Promise<Model> {
  return request<Model>('/models', { method: 'POST', body });
}

/** 更新模型版本状态/备注（如置为生产候选）。 */
export async function updateModelVersionStatus(
  modelId: string,
  modelVersionId: string,
  body: { status?: string; note?: string },
): Promise<ModelVersion> {
  return request<ModelVersion>(`/models/${modelId}/versions/${modelVersionId}`, {
    method: 'PATCH',
    body,
  });
}

/** 创建训练任务（异步）。 */
export async function createTrainingTask(
  body: TrainingConfig,
): Promise<{ job_id: string }> {
  return request<{ job_id: string }>('/training-tasks', {
    method: 'POST',
    body,
  });
}

/** 训练状态：指标 + 训练/验证损失曲线 + 进度（轮询 Job 结构）。 */
export async function getTrainingTask(
  id: string,
): Promise<Job<TrainingResult>> {
  return request<Job<TrainingResult>>(`/training-tasks/${id}`);
}

/** 训练日志（纯文本）。 */
export async function getTrainingLogs(id: string): Promise<string> {
  return request<string>(`/training-tasks/${id}/logs`);
}

/** 创建测试任务（异步）。 */
export async function createTestTask(
  body: TestConfig,
): Promise<{ job_id: string }> {
  return request<{ job_id: string }>('/test-tasks', { method: 'POST', body });
}

/** 测试结果：准确率/召回率/F1/推理时延 + 混淆矩阵（轮询 Job 结构）。 */
export async function getTestTask(id: string): Promise<Job<TestResult>> {
  return request<Job<TestResult>>(`/test-tasks/${id}`);
}

/** 提交推理（异步）。 */
export async function createInferenceTask(
  body: InferenceRequest,
): Promise<{ job_id: string }> {
  return request<{ job_id: string }>('/inference-tasks', {
    method: 'POST',
    body,
  });
}

/** 推理结果：预测框/类别/置信度/耗时（轮询 Job 结构）。 */
export async function getInferenceTask(
  id: string,
): Promise<Job<InferenceResult>> {
  return request<Job<InferenceResult>>(`/inference-tasks/${id}`);
}
