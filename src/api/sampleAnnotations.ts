/**
 * src/api/sampleAnnotations.ts — 分段样本**段级标注**（v3 多模态样本，2026-09-22）。
 *
 * 范围：只面向**已完成且 `rules_version>=3`** 的分段任务。一个标注对象就是一个 `Sample`
 * （一个时间窗），每段只有一个主结论（`normal` / `defect` + 主缺陷类别）；没有框/点/掩膜。
 *
 * 后端契约见 `backend/app/api/v1/sample_annotations.py`：
 * - 列表/详情/保存/撤销都在 `/split-tasks/{task_id}/annotation-samples*`，`task_id` 用
 *   创建分段任务时拿到的 **job_id**（后端双解析 job_uid / DB id）；
 * - `task_id` 兼容 job_uid 与 DB id，但前端一律传 job_uid；
 * - 样本的**三模态细节**走既有的 `GET /split-tasks/{id}/samples/{sample_id}`
 *   （`api/analysis.getSplitSample`）——每条信息只有一个主人，这里不复制。
 */
import { request } from './client';
import type {
  SampleAnnotation,
  SegmentAnnotatableTask,
  SegmentAnnotationExport,
  SegmentCategory,
  SegmentLabel,
  SegmentSamplePage,
} from './types';

/** 该焊缝**可进入标注**的分段任务（已完成 + v3），工作台的入口列表。 */
export async function listAnnotatableTasks(
  weldId: string,
): Promise<SegmentAnnotatableTask[]> {
  const data = await request<{ items: SegmentAnnotatableTask[] }>(
    `/welds/${weldId}/segment-annotation-tasks`,
  );
  return data.items ?? [];
}

/** 主缺陷词表（默认只给启用项；`includeInactive` 供展示历史标注引用的停用类别）。 */
export async function listSegmentCategories(
  includeInactive = false,
): Promise<SegmentCategory[]> {
  const data = await request<{ categories: SegmentCategory[] }>(
    '/segment-annotation/categories',
    { query: { include_inactive: includeInactive ? 1 : undefined } },
  );
  return data.categories ?? [];
}

/** 可标注样本列表（分页 + 进度）。`filter='unannotated'` 只看未标注（服务端过滤）。 */
export async function listSegmentSamples(
  taskId: string,
  params: { page?: number; page_size?: number; filter?: 'all' | 'unannotated' } = {},
): Promise<SegmentSamplePage> {
  return request<SegmentSamplePage>(`/split-tasks/${taskId}/annotation-samples`, {
    query: params,
  });
}

/** 单样本的当前结论（未标注时 `annotation` 为 null——「没标过」是正常状态，不是 404）。 */
export async function getSegmentAnnotation(
  taskId: string,
  sampleId: number,
): Promise<{ sample_id: number; start_time: number | null; end_time: number | null; annotation: SampleAnnotation | null }> {
  return request(`/split-tasks/${taskId}/annotation-samples/${sampleId}`);
}

/** 保存段级结论（**upsert**：重复保存是更新，不产生第二行）。 */
export async function saveSegmentAnnotation(
  taskId: string,
  sampleId: number,
  body: { label: SegmentLabel; defect_category_id?: number | null; note?: string | null },
): Promise<{ annotation: SampleAnnotation | null; progress: SegmentSamplePage['progress'] }> {
  return request(`/split-tasks/${taskId}/annotation-samples/${sampleId}`, {
    method: 'PUT',
    body,
  });
}

/** 撤销结论（回到未标注态）。 */
export async function clearSegmentAnnotation(
  taskId: string,
  sampleId: number,
): Promise<{ cleared: boolean; progress: SegmentSamplePage['progress'] }> {
  return request(`/split-tasks/${taskId}/annotation-samples/${sampleId}`, {
    method: 'DELETE',
  });
}

/** 版本化导出（数据集构建消费的输入；顶层带 `schema_version`）。 */
export async function exportSegmentAnnotations(
  taskId: string,
): Promise<SegmentAnnotationExport> {
  return request<SegmentAnnotationExport>(
    `/split-tasks/${taskId}/annotation-export`,
  );
}
