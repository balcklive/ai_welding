/**
 * src/api/types.ts — 前端接口类型定义
 *
 * 与 `docs/API接口清单.md` §2（核心实体）逐字段对齐，字段名/形状与后端响应保持一致。
 * 后端为契约：各 `*_payload` 序列化函数（`backend/app/services/**`）为准——
 * 若不确定形状，以该文档 §2 与后端 services 的 payload 为准，勿自造字段。
 */

// ── 统一信封（§1.3） ─────────────────────────────────────────────────
/** 成功信封：`{code:0, message, data}`。错误信封为 `{code, message, detail?}`（无 data）。 */
export interface Envelope<T> {
  code: number;
  message: string;
  data: T;
}

// ── 分页 / 异步任务（§1.4 / §1.5） ───────────────────────────────────
/** 分页载荷：`{items, total, page, page_size}`。 */
export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export type JobStatus = 'pending' | 'running' | 'succeeded' | 'failed';

/** 通用异步任务状态（§1.5 / §6.1）。id = job_uid。 */
export interface Job<T> {
  id: string;
  type: string;
  status: JobStatus;
  progress: number;
  result: T | null;
  error: unknown;
  created_at: string | null;
  finished_at: string | null;
}

// ── §2 核心实体 ─────────────────────────────────────────────────────
export interface User {
  id: number;
  username: string;
  display_name: string;
  role: string;
  avatar: string | null;
}

export interface DataVersion {
  id: number;
  record_id: number;
  version_no: string;
  action: string;
  operator: string | null;
  note: string | null;
  object_keys: string[];
  created_at: string | null;
}

export interface DataRecord {
  id: number;
  weld_id: string;
  weld_name: string | null;
  registration_no: string;
  source: string;
  collected_at: string | null;
  machine: string | null;
  weld_method: string | null;
  material: string | null;
  thickness: string | null;
  current_voltage: string | null;
  sample_rate: string | null;
  product: string | null;
  dataset_id: number;
  modalities: string[];
  quality: string;
  operator: string | null;
  storage_bytes: number | null;
  latest_version_id: number | null;
  created_at: string | null;
  updated_at: string | null;
  latest_version: DataVersion | null;
}

/**
 * 登记信息（§2）。`POST/GET/PATCH /registrations` 返回与 DataRecord 同构
 * （后端 `record_payload`，含 latest_version），故为 DataRecord 别名。
 */
export type Registration = DataRecord;

export interface ValidationRuleResult {
  rule_name: string;
  status: string;
  message: string | null;
}

export interface ValidationReport {
  id: number;
  version_id: number;
  score: number;
  passed: number;
  warning: number;
  failed: number;
  duration: number | null;
  created_at: string | null;
  rules: ValidationRuleResult[];
}

export interface LabelCategory {
  id: number;
  name: string;
  color: string | null;
}

export interface Annotation {
  id: number;
  sample_id: number;
  category: string;
  /** 几何类型：box（目标检测 bbox）/ segment（时序区间）/ polygon（多边形区域）。 */
  kind: string;
  box: number[];
  points: number[][];
  start_time: number | null;
  end_time: number | null;
  confidence: number | null;
  annotator: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface Sample {
  id: number;
  split_task_id: number | null;
  annotation_task_id: number | null;
  frame_no: number | null;
  object_keys: string[];
  meta: Record<string, unknown> | null;
  annotations: Annotation[];
  /** 样本级置信度 = 当前标注置信度均值（无标注 → null）。 */
  confidence: number | null;
}

export interface UnifiedVectorGroup {
  name: string;
  dims: number;
  range: [number, number];
}

export interface UnifiedVector {
  total_dims: number;
  groups: UnifiedVectorGroup[];
  normalization: string;
  format: string;
  values: number[];
}

export interface FeatureExtraction {
  id: number;
  version_id: number;
  ts_features: Record<string, Record<string, number>>;
  vision_features: Record<string, number>;
  audio_features: Record<string, number>;
  unified_vector: UnifiedVector;
  normalization: string;
  format: string;
  created_at: string | null;
  modality_status?: {
    timeseries?: 'real' | 'generated' | 'missing' | 'heuristic';
    vision?: 'real' | 'generated' | 'missing' | 'heuristic';
    audio?: 'real' | 'generated' | 'missing' | 'heuristic';
  };
  status?: 'succeeded' | 'partial' | 'failed';
  source_by_modality?: Record<string, string>;
  input_object_keys?: string[];
  algorithm_version?: string;
  pipeline_version?: string;
  sample_rate?: number | null;
  sample_count?: number | null;
  duration?: number | null;
  missing_modalities?: string[];
  warnings?: string[];
  started_at?: string | null;
  finished_at?: string | null;
}

export interface FeatureExtractionHistoryItem {
  id: number;
  status: string;
  normalization: string;
  format: string;
  algorithm_version: string;
  pipeline_version: string;
  source_by_modality: Record<string, string>;
  created_at: string | null;
  finished_at: string | null;
}

export interface DatasetQuality {
  repeat_rate: number;
  empty_label_rate: number;
  dimension_missing_rate: number;
}

export interface DatasetSplit {
  train: number;
  val: number;
  test: number;
}

export interface Dataset {
  id: number;
  dataset_no: string;
  name: string;
  task: string;
  sample_count: number;
  progress: number | null;
  status: string;
  current_version_id: number | null;
  version: string | null;
  /** 当前版本划分；未构建/无当前版本时为 `null`，已建版本但未构建时为 `{}`。 */
  split: Partial<DatasetSplit> | null;
  quality: DatasetQuality | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface DatasetVersion {
  id: number;
  dataset_id: number;
  version_no: string;
  /** 固定快照划分；后端恒输出该键，未构建版本为 `{}`（train/val/test 缺省）。 */
  split: Partial<DatasetSplit>;
  item_count: number;
  snapshot_id: string | null;
  quality: DatasetQuality | null;
  created_at: string | null;
}

export interface DatasetItem {
  id: number;
  dataset_version_id: number;
  sample_id: number;
  split: string;
}

/** 数据集固定版本中的单条样本成员（§3.5）。 */
export interface DatasetItemRow {
  sample_id: number;
  weld_id: string | null;
  weld_name: string | null;
  registration_no: string | null;
  source: string | null;
  machine: string | null;
  modalities: string[];
  quality: string | null;
  split: 'train' | 'val' | 'test';
  frame_no: number | null;
  created_at: string | null;
}

/** 数据项目卡片（总览，由数据集派生）：`{name, status, sample_count, progress, updated_at}`。 */
export interface Project {
  name: string;
  status: string;
  sample_count: number;
  progress: number;
  updated_at: string | null;
}

export interface Model {
  id: number;
  name: string;
  type: string;
  description: string | null;
  /** 以下为最新版本快照（无版本时缺省）。 */
  version?: string | null;
  metric?: Record<string, unknown> | null;
  status?: string | null;
  file_key?: string | null;
  latest_version_id?: number | null;
  /** 仅 `getModel` 详情返回全部版本列表。 */
  versions?: ModelVersion[];
}

export interface ModelVersion {
  id: number;
  model_id: number;
  version_no: string;
  metric: Record<string, unknown> | null;
  status: string;
  file_key: string | null;
  created_at: string | null;
}

export interface ModelSummary {
  total: number;
  prod_candidates: number;
  recent_training: string | null;
}

// ── Dashboard 总览（§3.2） ──────────────────────────────────────────
export interface DashboardStats {
  data_total: number;
  manufacturer_total: number;
  max_storage_bytes: number;
  annotated_samples: number;
  annotation_completion: number;
}

export interface DashboardAttributes {
  weld_methods: string[];
  defect_types: { name: string; count: number }[];
  modalities: string[];
  sample_rate_tiers: string[];
}

export interface DashboardDistributions {
  manufacturers: { name: string; value: number }[];
  transition_types: { name: string; value: number }[];
  welding_types: { name: string; value: number }[];
  defects: { name: string; count: number }[];
  wordcloud: { name: string; size: number }[];
}

// ── 信号 / 分析（§3.4） ─────────────────────────────────────────────
export interface WeldEvent {
  arc: number;
  weld_segment: [number, number];
  tail: number;
}

export interface WeldAnomaly {
  start: number;
  end: number;
  type: string;
}

export interface SignalChannel {
  id: string;
  name: string;
  unit: string;
  values: number[];
  /** 服务端抽稀（max_points）时返回：每个采样点的秒时刻（min-max 选点非均匀，须按 [t,v] 画点）。 */
  times?: number[];
  lo: number;
  hi: number;
  mean: number;
}

export interface SignalData {
  source: 'real' | 'generated';
  duration: number;
  sample_rate: number;
  channels: SignalChannel[];
  events: WeldEvent;
  anomalies: WeldAnomaly[];
}

export type AnalysisMode = 'psd' | 'stft' | 'dwt' | 'wavelet' | 'phase' | 'pdd';

export interface PsdData {
  freqs: number[];
  psd: number[];
}

export interface StftData {
  times: number[];
  freqs: number[];
  magnitude: number[][];
}

export interface WaveletBand {
  name: string;
  values: number[];
}

export interface DwtData {
  bands: WaveletBand[];
  approx: { name: string; values: number[] };
}

export interface WaveletData {
  bands: WaveletBand[];
}

export interface PhaseData {
  current: number[];
  voltage: number[];
}

export interface PddData {
  bins: number[];
  counts: number[];
  kde: number[];
}

/** 单视图分析数据（mode 分发）：psd | stft | dwt | wavelet | phase | pdd。 */
export type AnalysisViewData =
  | PsdData
  | StftData
  | DwtData
  | WaveletData
  | PhaseData
  | PddData;

export interface AnalysisResult {
  source?: 'real' | 'generated';
  stability: number;
  segments: {
    normal: number;
    arc_instability: number;
    sputter: number;
  };
  anomalies: WeldAnomaly[];
}

/** 单条对齐轨道（对齐真实化后扩展）：availability 部分成功语义。 */
export interface AlignmentTrack {
  channel: string;
  modality: string;
  availability: 'available' | 'generated' | 'unavailable';
  source: 'real' | 'generated' | null;
  aligned: boolean;
  asset: string | null;
  object_key: string | null;
  metadata: {
    sample_rate?: number;
    duration?: number;
    channels?: string[];
    fps?: number | null;
    width?: number | null;
    height?: number | null;
    keyframes?: { event: string; t: number; asset?: string }[];
    object_key?: string;
  } | null;
  reason: string | null;
}

export interface AlignmentResult {
  events: WeldEvent;
  /** 事件来源：real=真实信号 detect_events；generated=无导入回退确定性生成。 */
  event_source?: 'real' | 'generated';
  tracks: AlignmentTrack[];
  assets: string[];
  version: DataVersion;
}

export interface SplitResult {
  sample_count: number;
  rules: { fixed_rate: number; stride?: number; keep_event_buffer: number; event_bounds?: [number, number] };
  task_format: string;
  samples: {
    id: number;
    frame_no: number;
    object_keys: string[];
    annotation_task_id: number | null;
  }[];
}

export interface TrainingMetrics {
  mAP50: number;
  precision: number;
  recall: number;
}

export interface TrainingResult {
  metrics: TrainingMetrics;
  loss_curve: { train: number[]; val: number[] };
  model_version: ModelVersion;
  progress: number;
}

export interface TestResult {
  metrics: { accuracy: number; recall: number; f1: number; latency_ms: number };
  confusion_matrix: number[][];
}

export interface InferenceResult {
  boxes: number[][];
  categories: string[];
  confidence: number[];
  latency_ms: number;
}

// ── 请求体 / 查询参数（§3.x 端点） ─────────────────────────────────
export interface WeldListQuery {
  q?: string;
  source?: string;
  brand?: string;
  status?: string;
  tab?: string;
  /** 归属数据集精确筛选（分析与标注「选择数据」两级选择的第二级范围）。 */
  dataset_id?: number;
  page?: number;
  page_size?: number;
}

export interface SignalQuery {
  channels?: string[];
  filter_type?: string;
  cutoff?: number;
  cutoff2?: number;
  /** 波形预览服务端 min-max 抽稀点数上限（2~20000）；DSP 分析端点不受影响。 */
  max_points?: number;
  /** 时间窗（秒）：缩放增量取细节时按窗口请求高分辨率数据。 */
  start?: number;
  end?: number;
}

export interface SplitRules {
  fixed_rate: number;
  stride?: number;
  keep_event_buffer?: number;
  task_format?: string;
  event_start?: number;
  event_end?: number;
}

export interface SplitPreview {
  input: { version_id: number; duration: number; sample_rate: number; source: 'real' };
  events: WeldEvent;
  summary: { sample_count: number; effective_start: number; effective_end: number; window_seconds: number; stride_seconds: number };
  windows: { index: number; start: number; end: number; frame_start: number; frame_end: number }[];
}

export interface FeatureExtractRequest {
  weld_id: string;
  version_id: number;
  normalization?: string;
  format?: string;
}

export interface TrainingConfig {
  /** 新接口支持多个固定数据集版本；保留单数键兼容旧后端。 */
  dataset_version_ids?: number[];
  dataset_version_id?: number;
  base_model_id?: number;
  model_type?: string;
  epochs?: number;
  batch_size?: number;
  learning_rate?: number;
  val_ratio?: number;
  /** 高级参数（后端 `extra=allow` 收集进 hyperparams）。 */
  [key: string]: unknown;
}

export interface TestConfig {
  model_version_id: number;
  dataset_version_id: number;
  tasks?: string[];
}

export interface InferenceRequest {
  model_version_id: number;
  input: string;
  input_type: string;
}

export interface ExportRequest {
  type: string;
  ref_ids?: unknown[];
  format?: string;
}

export interface RegistrationForm {
  dataset_id: number;
  source: string;
  collected_at?: string | null;
  weld_name?: string | null;
  product?: string | null;
  machine?: string | null;
  weld_method?: string | null;
  material?: string | null;
  thickness?: string | null;
  current_voltage?: string | null;
  sample_rate?: string | null;
}

export interface AnnotationTaskCreate {
  source: 'split_task' | 'manual' | 'signal' | 'video';
  split_task_id?: string;
  version_id?: number;
  name?: string;
}

export interface ImportSamplesBody {
  source: 'files' | 'split_task';
  object_keys?: string[];
  split_task_id?: string;
}

/** 单条标注标签输入。按 `kind` 分支：box 为 `[x, y, w, h]`；segment 用 start_time/end_time；polygon 用 points。 */
export interface LabelItem {
  category: string;
  kind?: string;
  box?: number[];
  points?: number[][];
  start_time?: number | null;
  end_time?: number | null;
  confidence?: number | null;
}

export interface SaveLabelsBody {
  labels: LabelItem[];
}

// ── §4.2 补充类型（被 api 模块签名引用） ─────────────────────────────
export interface LoginResult {
  access_token: string;
  token_type: string;
  user: User;
}

export interface DatasetSource {
  type: 'annotation_task' | 'split_task' | 'manual' | 'filter';
  annotation_task_id?: string;
  split_task_id?: string;
  sample_ids?: string[];
  filters?: Record<string, unknown>;
}

export interface DimensionStatus {
  name: string;
  status: string;
  required: boolean;
}

export interface ReadinessCheck {
  readiness: string;
  checks: { name: string; passed: boolean }[];
}

export interface LineageNode {
  type: string;
  label: string;
  count: number;
  items: unknown[];
}
