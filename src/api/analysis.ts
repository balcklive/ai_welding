/**
 * src/api/analysis.ts — 分析与标注（§3.4 / §4.2）。
 *
 * - `getSignals` 对 `channels[].values` 做前端均匀抽稀到 ≤512 点（图表渲染用，
 *   降低首帧数据量）；长度 ≤512（含 0/1 点）原样返回。
 * - 对齐/切分/标注任务均异步：POST 返回 `{job_id}`，前端轮询对应 GET 端点。
 */
import { request } from './client';
import type {
  AlignmentResult,
  AnalysisMode,
  AnalysisResult,
  AnalysisViewData,
  Annotation,
  DataRecord,
  FeatureExtractRequest,
  FeatureExtraction,
  Job,
  LabelCategory,
  LabelItem,
  Page,
  Sample,
  SignalData,
  SignalQuery,
  SplitResult,
  SplitRules,
} from './types';

/** 均匀抽稀：等距下标取样到 ≤n 点；长度 ≤n（含 0/1 点）原样返回。 */
function decimate(values: number[], n = 512): number[] {
  if (values.length <= n) return values;
  const step = (values.length - 1) / (n - 1);
  const out = new Array<number>(n);
  for (let i = 0; i < n; i++) {
    out[i] = values[Math.round(i * step)];
  }
  return out;
}

/** 选择数据页：已登记且核验通过的可分析数据列表。 */
export async function listCandidates(): Promise<DataRecord[]> {
  return request<DataRecord[]>('/analysis/candidates');
}

/** 提交多模态对齐任务（异步；成功后自动生成「时间对齐」版本）。 */
export async function createAlignmentTask(
  weldId: string,
  versionId: string,
  modalities: string[],
): Promise<{ job_id: string }> {
  return request<{ job_id: string }>(
    `/welds/${weldId}/versions/${versionId}/alignment-tasks`,
    { method: 'POST', body: { modalities } },
  );
}

/** 对齐任务状态/结果（轮询 Job 结构）。 */
export async function getAlignmentTask(
  taskId: string,
): Promise<Job<AlignmentResult>> {
  return request<Job<AlignmentResult>>(`/alignment-tasks/${taskId}`);
}

/** 多通道时域波形（前端降采样到 ≤512 点/通道）。 */
export async function getSignals(
  weldId: string,
  versionId: string,
  opts: SignalQuery = {},
): Promise<SignalData> {
  const data = await request<SignalData>(
    `/welds/${weldId}/versions/${versionId}/signals`,
    { query: opts },
  );
  return {
    ...data,
    channels: data.channels.map((ch) => ({
      ...ch,
      values: decimate(ch.values),
    })),
  };
}

/** 单视图分析数据（psd | stft | dwt | wavelet | phase | pdd），filter 为可选滤波联动。 */
export async function getAnalysisMode(
  weldId: string,
  versionId: string,
  mode: AnalysisMode,
  channel: string,
  filter?: {
    type: '低通' | '高通' | '带通';
    cutoff: number;
    cutoff2?: number;
  },
): Promise<AnalysisViewData> {
  return request<AnalysisViewData>(
    `/welds/${weldId}/versions/${versionId}/analysis/${mode}`,
    {
      query: {
        channel,
        filter_type: filter?.type,
        cutoff: filter?.cutoff,
        cutoff2: filter?.cutoff2,
      },
    },
  );
}

/** AI 异常检测结果：焊接稳定度、正常/电弧不稳/飞溅比例、异常区段列表。 */
export async function getAnalysisResult(
  weldId: string,
  versionId: string,
): Promise<AnalysisResult> {
  return request<AnalysisResult>(
    `/welds/${weldId}/versions/${versionId}/analysis/result`,
  );
}

/** 提交数据切分任务（异步）。 */
export async function createSplitTask(
  weldId: string,
  versionId: string,
  rules: SplitRules,
): Promise<{ job_id: string }> {
  return request<{ job_id: string }>(
    `/welds/${weldId}/versions/${versionId}/split-tasks`,
    { method: 'POST', body: rules },
  );
}

/** 切分任务状态/结果（轮询 Job 结构）。 */
export async function getSplitTask(taskId: string): Promise<Job<SplitResult>> {
  return request<Job<SplitResult>>(`/split-tasks/${taskId}`);
}

/** 缺陷标签类别（焊瘤/气孔/未熔合/咬边/正常，模型口径）。 */
export async function listLabelCategories(): Promise<LabelCategory[]> {
  return request<LabelCategory[]>('/label-categories');
}

/** 创建标注任务（异步：从切分样本/手动选样生成）。 */
export async function createAnnotationTask(body: {
  source: 'split_task' | 'manual';
  split_task_id?: string;
  name?: string;
}): Promise<{ job_id: string }> {
  return request<{ job_id: string }>('/annotation-tasks', {
    method: 'POST',
    body,
  });
}

/** 导入额外样本到标注任务（补充文件或其它切分任务样本）。 */
export async function importAnnotationSamples(
  taskId: string,
  body: {
    source: 'files' | 'split_task';
    object_keys?: string[];
    split_task_id?: string;
  },
): Promise<void> {
  await request<void>(`/annotation-tasks/${taskId}/import`, {
    method: 'POST',
    body,
  });
}

/** 标注样本列表（分页）。 */
export async function listAnnotationSamples(
  taskId: string,
  page: number,
): Promise<Page<Sample>> {
  return request<Page<Sample>>(`/annotation-tasks/${taskId}/samples`, {
    query: { page },
  });
}

/** 单个样本详情（图像/信号 + 现有标注 + 样本级 confidence）。 */
export async function getAnnotationSample(
  taskId: string,
  sampleId: string,
): Promise<Sample> {
  return request<Sample>(`/annotation-tasks/${taskId}/samples/${sampleId}`);
}

/** AI 预标注（同步）：返回疑似缺陷区域 + 置信度。 */
export async function aiPretag(
  taskId: string,
  sampleId: string,
): Promise<Annotation[]> {
  return request<Annotation[]>(
    `/annotation-tasks/${taskId}/samples/${sampleId}/ai-pretag`,
    { method: 'POST' },
  );
}

/** 保存/更新标注（同步，覆盖写）。 */
export async function saveAnnotation(
  taskId: string,
  sampleId: string,
  labels: LabelItem[],
): Promise<void> {
  await request<void>(
    `/annotation-tasks/${taskId}/samples/${sampleId}/labels`,
    { method: 'POST', body: { labels } },
  );
}

/** 执行特征提取（同步）：时序/视觉/声音特征 + 统一向量。 */
export async function extractFeatures(
  body: FeatureExtractRequest,
): Promise<FeatureExtraction> {
  return request<FeatureExtraction>('/features/extract', {
    method: 'POST',
    body,
  });
}

/** 特征提取结果（导出时使用）。 */
export async function getFeatureExtraction(
  id: string,
): Promise<FeatureExtraction> {
  return request<FeatureExtraction>(`/features/${id}`);
}
