/**
 * src/shared/lib/terms.ts — 界面正式名（术语基线，T1）
 *
 * 单一来源，见 `docs/数据管理改造技术实施方案.md` §2.1 正式术语表。
 * 各页面**不要再写中文字面量**：要展示"数据集版本"就写 `TERMS.datasetVersion`。
 *
 * 明确禁止再出现（作为界面文案时）：快照、固定快照、焊缝版本、可训练、未核验、数据质量。
 * 代码标识（`Dataset` / `Sample` / `DataRecord` / `DatasetItem`）与后端字段名一律不动。
 */

export const TERMS = {
  /** 数据集容器（`Dataset`）。 */
  dataset: '数据集',
  /** 数据集的冻结版本（`DatasetVersion`）。 */
  datasetVersion: '数据集版本',
  /** 一次登记的对象（`DataRecord`）。 */
  sample: '样本',
  /** 数据集版本内的成员（`Sample` / `DatasetItem`）。 */
  slice: '切片',
  /** 样本的处理历史（`DataVersion`）。 */
  dataVersion: '数据版本',
  /** 数据版本链上的当前指针（`latest_version_id`）。 */
  currentDataVersion: '当前数据版本',
  /** 质量指标（分母是切片数），见 T2.3。 */
  effectiveRatio: '有效切片占比',
} as const;

/** 数据集任务类型 → 成员在版本里的叫法（训练数据准备用）。 */
export const READY_TEXT = {
  passed: '适配检查通过',
  failed: '适配检查未通过',
  unknown: '待检查',
} as const;

/**
 * 后端输入维度英文标识 → 界面中文名（S6）。
 * 未列出的维度（如已中文化的「焊缝照片」「熔池视频」）原样展示。
 */
export const DIMENSION_LABELS: Record<string, string> = {
  Current: '电流',
  Voltage: '电压',
  GasSpeed: '气流速度',
  Molten_feature: '熔池特征',
  Sound_feature: '声学特征',
};

/** 维度名 → 中文名（未知标识回退原值）。 */
export const dimensionLabel = (name: string): string => DIMENSION_LABELS[name] ?? name;
