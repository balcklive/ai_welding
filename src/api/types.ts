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

/**
 * 登记链路状态（T4.4）：由后端从已有数据推导（不新增表），刷新/换设备后看到的是同一个真相。
 * 「登记成功」≠「导入完成」——`ready` 才代表核验/分析能读到真实信号。
 */
export interface IngestStatus {
  registration_no: string;
  weld_id: string;
  status: 'awaiting_upload' | 'importing' | 'failed' | 'ready';
  /** 已挂到 v1.0 的对象键数量（0 = 还没上传过文件）。 */
  uploaded_files: number;
  /** 本次登记的 CSV 导入任务总数（0 = 没有 CSV 需要导入，此时 `ready` 即"可分析"）。 */
  csv_total: number;
  /** 导入失败的 CSV 与原因（`reimportSignals` 的输入）。 */
  csv_failed: { source_object_key: string; message?: string | null }[];
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
  /** D7 之前的老列（`180 A / 22 V`）：过渡期仍返回，供历史数据回显；写入只写下面两列。 */
  current_voltage: string | null;
  /** D7：电流（A）/ 电压（V）拆列（迁移 0017 从 `current_voltage` 解析回填）。 */
  current_a?: number | null;
  voltage_v?: number | null;
  sample_rate: string | null;
  /** 单值工艺参数：送丝速度 / 焊接速度（登记可填；标准 CSV 导入后按稳态中位数回填）。 */
  wire_feed_speed: string | null;
  welding_speed: string | null;
  /** 导入字段概览：全通道稳态代表值 [{id,name,unit,value}]（CSV 导入自动写）。 */
  data_fields: DataFieldSummaryItem[] | null;
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

/** 一条焊缝数据记录的字段概览项（对应 CSV 一个通道列的稳态代表值）。 */
export interface DataFieldSummaryItem {
  id: string;
  name: string;
  unit: string;
  value: number | null;
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
  /** 是否启用（系统设置可停用；停用类别仍随接口返回，供历史标注解析名称/颜色）。 */
  active?: boolean;
  sort_order?: number;
}

/** 系统设置·可选项字典项（`GET /settings/options`）。 */
export interface OptionItem {
  id: number;
  /** 选项值：即写入业务列的字符串（data_records.machine、datasets.task …）。 */
  value: string;
  color: string | null;
  /** false = 已停用（历史数据仍展示，录入候选不再出现）。 */
  active: boolean;
  sort_order: number;
}

/** 系统设置·选项组（一组可维护的录入候选项）。 */
export interface OptionGroup {
  key: string;
  label: string;
  description: string;
  /** 是否支持颜色（仅标注缺陷类别）。 */
  color: boolean;
  /** 录入页是否保留手工填写（数据来源/产品信息为候选提示而非强约束）。 */
  free_text: boolean;
  items: OptionItem[];
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

/** Label Studio 标注任务同步状态（`GET /labelstudio/tasks/{job_uid}`，前端 iframe 嵌入用）。 */
export interface LabelStudioTask {
  id: number;
  source: string;
  /** `legacy`=未走 LS(off/回退) | `pending_ls`=等待 LS 标注 | `annotating`=进行中 | `synced`=已全部回写。 */
  ls_status: string;
  /** LS 公网宿主 URL（浏览器/iframe 可访问，非服务端内网）。 */
  ls_public_url: string;
  /** 该任务样本映射到的 LS 项目 id（去重），iframe 用它拼项目 URL。 */
  ls_project_ids: number[];
  created_at: string | null;
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

/** 扣分原因明细（T2.3）：`rate` 与 `affected` 都按**去重并集**算，各原因允许重叠。 */
export interface QualityDeduction {
  /** 界面标签，由后端给（前端不拼文案）。 */
  label: string;
  /** 命中该原因的切片占比（0–1）。 */
  rate: number;
  /** 命中该原因的切片数。 */
  affected: number;
}

/**
 * 数据集质量（T2.3）。
 *
 * `effective_ratio` 是界面唯一该展示的口径（未命中任何原因的切片占比）；三个 `*_rate` 是明细。
 * 注意：
 * - `dimension_missing_rate` 自 T2.3 起是**切片级**（缺任一必需字段的切片占比）；
 * - `effective_ratio` / `deductions` 是 T2.3 才写入的快照字段，**历史版本没有这两个键** →
 *   展示层必须按"缺值"处理（显示 `—`），不能用三个 rate 反推（各原因可重叠，`1 - 之和` 会算出负数）。
 */
export interface DatasetQuality {
  repeat_rate: number;
  empty_label_rate: number;
  dimension_missing_rate: number;
  /** 有效切片占比（0–1）；空版本为 `null`；T2.3 之前的版本为 `undefined`。 */
  effective_ratio?: number | null;
  deductions?: Record<string, QualityDeduction>;
}

/** 删除前的影响范围预检（T7）：后端用**与实际删除同一份**引用规则算出来。 */
export interface DeleteImpact {
  /** 关联数量（界面展示"影响范围"）。 */
  counts: Record<string, number>;
  /** 非空 = 不能删，逐条说明原因。 */
  blocking: string[];
  /** 实际会一并删除的数量（与关联数量分开，避免"关联 12、实际删 3"被混成一个数）。 */
  deletable: Record<string, number>;
  can_delete: boolean;
}

export interface DatasetSplit {
  train: number;
  val: number;
  test: number;
}

/**
 * 选择器专用的轻量数据集（`GET /datasets?options=1`，D19/T9）。
 *
 * 只含下拉/默认值要用的字段（无 quality / 时间戳等重字段）。**列表页不要用它**——
 * 列表走 `listDatasets({page,page_size,q})` 的分页接口。
 */
export interface DatasetOption {
  id: number;
  dataset_no: string;
  name: string;
  task: string;
  status: string;
  sample_count: number;
  weld_count: number;
  progress: number | null;
  current_version_id: number | null;
  version: string | null;
  split: Partial<DatasetSplit> | null;
}

export interface Dataset {
  /** 已登记样本数，与数据集版本中的切片数区分。 */
  weld_count?: number;
  id: number;
  dataset_no: string;
  name: string;
  task: string;
  sample_count: number;
  progress: number | null;
  status: string;
  current_version_id: number | null;
  version: string | null;
  /** 当前版本的构建状态（T8）：pending/running/succeeded/failed；`null` = 未构建。 */
  build_status?: JobStatus | null;
  /** 当前版本的构建任务 job_uid（T8）。 */
  build_job_id?: string | null;
  /** 当前版本划分；未构建/无当前版本时为 `null`，已建版本但未构建时为 `{}`。 */
  split: Partial<DatasetSplit> | null;
  quality: DatasetQuality | null;
  created_at: string | null;
  updated_at: string | null;
}

/** 挂载原始文件后自动创建的构建任务（T8：`POST …/raw-files` 响应的 `dataset_build`）。 */
export interface DatasetBuildTicket {
  dataset_version_id: number;
  version_no: string;
  job_id: string;
}

export interface DatasetVersion {
  id: number;
  dataset_id: number;
  version_no: string;
  /** 该版本最新一次构建任务的状态（T8）；`null`/`undefined` = 从未构建（手工建的空版本）。 */
  build_status?: JobStatus | null;
  /** 该版本最新一次构建任务的 job_uid（T8），供轮询与"重新构建"。 */
  build_job_id?: string | null;
  /** 数据集版本划分；后端恒输出该键，未构建版本为 `{}`（train/val/test 缺省）。 */
  split: Partial<DatasetSplit>;
  item_count: number;
  snapshot_id: string | null;
  quality: DatasetQuality | null;
  created_at: string | null;
  /**
   * 该版本的标注是否已冻结（T16.1 / R4）：`true` = 成员行带构建时的标注快照，训练输入不随
   * 以后改标注而变；`false` = 历史版本（T16 之前构建），训练只能现查当前标注；`null` = 空版本。
   * 只在**版本详情**接口返回（列表不查，避免逐版本多一次查询）。
   */
  annotations_frozen?: boolean | null;
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
  /** 成员来源样本的当前/锁定数据版本，用于区分数据集版本。 */
  weld_version?: string | null;
}

export interface Model {
  id: number;
  name: string;
  type: string;
  description: string | null;
  /** 以下为最新数据版本（无版本时缺省）。 */
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

/** 焊缝照片上的轴对齐矩形（**原始图片像素**，非归一化）。 */
export interface SeamRoi {
  x: number;
  y: number;
  w: number;
  h: number;
}

/** 标定（§3.4）：视频零点 offset + 焊缝图片 ROI。
 *
 * 权威归属固定钉在该焊缝的 **v1.0 原始版本**上——任何属于该焊缝的版本都读到同一份。
 * `video.offset_seconds` 语义：视频零点在信号轴上的时刻，换算为 `t_video = t_signal - offset`。
 */
export interface Calibration {
  /** 原始标定（未标定 → 空对象）。 */
  calibration: {
    video?: { offset_seconds: number } | null;
    seam_image?: { roi?: SeamRoi | null; excluded?: boolean } | null;
  };
  /** 标定归属版本（v1.0）；该焊缝无 v1.0 时为 null。 */
  anchored_version_id: number | null;
  video: { offset_seconds: number; calibrated: boolean };
  seam_image: {
    roi: SeamRoi | null;
    /** 已框选 ROI 且未被排除。 */
    calibrated: boolean;
    /** 用户明确选择「不对焊缝图片进行分段」——与"还没框 ROI"是两回事。 */
    excluded: boolean;
    object_key: string | null;
  };
}

/** PUT …/calibration 请求体（§3.4）：**合并语义**——省略的组保持原值，显式 `null` 清除该组。
 *
 * `seam_image` 组在服务端是**整组替换**（`validate_calibration_patch`），两条路径互斥：
 * - `{roi}` → 框选并参与分段（服务端同时显式写 `excluded: false`，撤销旧的"不参与"）；
 * - `{excluded: true}` → 明确不参与分段：不必给 ROI，也不下载图片做越界校验。
 */
export interface CalibrationUpdate {
  video?: { offset_seconds: number } | null;
  seam_image?: { roi?: SeamRoi; excluded?: boolean } | null;
}

export interface SplitResult {
  sample_count: number;
  rules: SplitRules & { rules_version?: number; event_bounds?: [number, number] };
  /** v3 起废弃（§3.4）：新任务为 `null`，历史任务保留原值。 */
  task_format?: string | null;
  /** 3 = v3 多模态样本；`null` = 历史任务（≤2），不在新页面伪装成新格式（§3.4）。 */
  schema_version?: number | null;
  rules_version?: number;
  /** 产出这批样本时用的坐标映射摘要；与预览不一致说明标定变过。 */
  mapping_hash?: string | null;
  manifest_key?: string | null;
  samples?: {
    id: number;
    frame_no: number;
    object_keys: string[];
    annotation_task_id?: number | null;
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

/** 分段规则（v3 / §2.3）：**秒是唯一切分单位**，按帧入口已废弃。 */
export interface SplitRules {
  /** 窗口时长（秒），默认 2.0。 */
  window_seconds?: number;
  /** 步长（秒），默认 2.0（= 不重叠）。 */
  stride_seconds?: number;
  event_start?: number;
  event_end?: number;
  keep_event_buffer?: number;
  /** 尾片策略：`drop`（默认）/ `keep`。 */
  tail_policy?: 'drop' | 'keep';
}

/** 一个分段的**视频代表帧**（§3.3）：默认取该段窗口中点，`t_video = t_signal - offset`。
 *
 * 同一段只认这一帧——**不许拿全局首帧或占位图冒充**。预览下 `url` 是**短期**预签名地址
 * （过期后重新预览即可）；产物路径下只有 `object_key`（自己换地址）。`available=false` 时
 * `reason` 必是真实原因（视频不可用 / 该段落视频覆盖外 / 抽帧失败）。
 */
export interface SplitVideoFrame {
  available: boolean;
  reason?: string | null;
  /** 帧在**信号轴**上的时刻（秒）。 */
  t_signal?: number;
  /** 帧在**视频轴**上的时刻（秒，`t_signal - offset`）。 */
  t_video?: number;
  /** 视频帧号（`t_video × fps`）。 */
  frame_no?: number;
  object_key?: string | null;
  /** 预览专用：短期预签名 URL。 */
  url?: string | null;
}

/** 单个窗口在某个模态上的摘要（§3.3）。`available=false` 时 `reason` 必有值。 */
export interface SplitModalitySlot {
  available: boolean;
  calibrated?: boolean;
  /** 该模态被用户明确排除在本轮分段之外（焊缝图片的「不对其分段」选择）。 */
  excluded?: boolean;
  reason?: string | null;
  object_key?: string | null;
  /** 视频：`start_frame`/`end_frame`/`offset_seconds`/`fps`/`keyframes[{at}]`/`frame`。 */
  start_frame?: number;
  end_frame?: number;
  offset_seconds?: number;
  fps?: number;
  keyframes?: { at: number }[];
  /** 本段代表帧（每段各不相同）。 */
  frame?: SplitVideoFrame;
  /** 焊缝图片：`roi` 与沿 ROI 长边的像素区间。 */
  roi?: { x: number; y: number; w: number; h: number } | null;
  spatial_range?: { start_px: number; end_px: number };
  speed_source?: string | null;
  crop_key?: string | null;
}

export interface SplitPreviewWindow {
  index: number;
  start: number;
  end: number;
  duration: number;
  signal: SplitModalitySlot & { sample_rate?: number; start_index?: number; end_index?: number };
  video: SplitModalitySlot;
  seam_image: SplitModalitySlot;
}

export interface SplitTimelineTrack {
  id: string;
  name: string;
  unit: string;
  times: number[];
  values: number[];
}

export interface SplitPreview {
  /** 创建任务的**唯一凭证**（§5.4）：屏幕上的边界与真正切出来的由它绑定。 */
  preview_token: string;
  rules: SplitRules;
  rules_hash: string;
  mapping_hash: string;
  effective_range: { start: number; end: number };
  window_seconds: number;
  stride_seconds: number;
  overlap_seconds: number;
  overlap_ratio: number;
  tail_policy: 'drop' | 'keep';
  sample_count: number;
  windows: SplitPreviewWindow[];
  timeline: {
    duration: number;
    events: WeldEvent;
    signal: { sample_rate: number; tracks: SplitTimelineTrack[] };
    video_thumbnail_times: number[];
    seam_image_projection: {
      available: boolean;
      object_key: string | null;
      roi: { x: number; y: number; w: number; h: number } | null;
      /** 用户已选择「不对焊缝图片进行分段」：不可用，但**不是**待标定，别再引导去框选。 */
      excluded: boolean;
      speed_source: string | null;
      reason: string | null;
    };
  };
  /** 各模态的可用性与**标定状态**（分段页只读展示，不可在此编辑）。 */
  modalities: Record<string, { available: boolean; calibrated: boolean; excluded?: boolean; reason: string | null; speed_source?: string | null }>;
  warnings: string[];
}

export interface SplitSample {
  id: number;
  frame_no: number | null;
  start_time: number | null;
  end_time: number | null;
  schema_version: number | null;
  object_keys: string[];
  modalities: Record<string, { available: boolean; calibrated: boolean; reason: string | null }>;
}

export interface SplitSampleDetail extends SplitSample {
  meta: Record<string, unknown> | null;
  time_series: SplitTimelineTrack[];
}

// ── 分段样本段级标注（2026-09-22，见 `backend/app/api/v1/sample_annotations.py`） ──

/** 段级结论：一个样本只有一个主结论（`normal` 正常 / `defect` 缺陷）。 */
export type SegmentLabel = 'normal' | 'defect';

/** 主缺陷词表项（`option_items` 的 `defect_category` 分组；`id` 是稳定 ID）。 */
export interface SegmentCategory {
  id: number;
  value: string;
  active: boolean;
  sort_order: number;
}

/** 一个样本的段级标注。`defect_category_name` 是**写入当时**的名称快照——
 *  类别改名/停用后历史标注仍按它展示，不要回查词表去"修正"。 */
export interface SampleAnnotation {
  sample_id: number;
  label: SegmentLabel;
  defect_category_id: number | null;
  defect_category_name: string | null;
  note: string | null;
  /** 标注数据 schema 版本（数据集构建消费前先认它）。 */
  schema_version: number;
  /** 复核态（一期 UI 不暴露；默认 approved）。 */
  review_status: string | null;
  annotator: string | null;
  created_at: string | null;
  updated_at: string | null;
}

/** 标注工作台列表行（**轻量**：只有导航与进度需要的字段，不带 meta/媒体对象键）。 */
export interface SegmentSampleRow {
  id: number;
  frame_no: number | null;
  start_time: number | null;
  end_time: number | null;
  annotated: boolean;
  label: SegmentLabel | null;
  defect_category_name: string | null;
}

/** 标注进度（工作台顶部与数据集构建的覆盖率口径）。 */
export interface SegmentProgress {
  total: number;
  annotated: number;
  unannotated: number;
  normal: number;
  defect: number;
  progress: number;
  defect_distribution: { name: string; count: number }[];
}

export type SegmentSamplePage = Page<SegmentSampleRow> & { progress: SegmentProgress };

/** 可进入标注的分段任务（`GET /welds/{weld_id}/segment-annotation-tasks`）——只含
 *  **已完成 + v3** 的任务，是标注工作台的入口列表。 */
export interface SegmentAnnotatableTask {
  /** job_uid：后续所有标注端点都用它寻址（与创建分段任务时拿到的一致）。 */
  task_id: string;
  split_task_id: number;
  version_id: number;
  version_no: string;
  sample_count: number;
  window_seconds: number | null;
  stride_seconds: number | null;
  /** 有效事件区间 [start, end]（秒）。 */
  effective_range: number[] | null;
  finished_at: string | null;
  progress: Pick<SegmentProgress, 'total' | 'annotated' | 'unannotated' | 'progress'>;
}

/** 版本化导出（数据集构建消费的输入，**不含媒体字节**）。 */
export interface SegmentAnnotationExport {
  schema_version: number;
  task_id: number;
  weld_id: string | null;
  source_version_id: number;
  label_vocabulary: { id: number; name: string; active: boolean }[];
  sample_count: number;
  annotated_count: number;
  items: {
    sample_id: number;
    sample_index: number | null;
    start_time: number | null;
    end_time: number | null;
    label: SegmentLabel | null;
    defect_category_id?: number | null;
    defect_category_name?: string | null;
    note?: string | null;
    annotator?: string | null;
  }[];
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
  input_type: 'image' | 'video';
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
  /** D7：电流（A）/ 电压（V）——表单里是字符串，提交时转成数字（后端量程 1–2000 / 1–200）。 */
  current_a?: number | string | null;
  voltage_v?: number | string | null;
  /** 旧字段：后端仅作兼容解析，前端不再使用（保留以免历史调用点类型报错）。 */
  current_voltage?: string | null;
  sample_rate?: string | null;
  wire_feed_speed?: string | null;
  welding_speed?: string | null;
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
  type: 'annotation_task' | 'split_task' | 'manual' | 'filter' | 'dataset_records';
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
