# CLAUDE.md — src/features/features/

分析与标注·**切片级特征提取**工作台（2026-10）。目录名 `features` 与功能「特征提取」同名，易混淆。

## 文件

- `SampleFeatureWorkspace.tsx`：`SampleFeatureWorkspace({embedded?, dataId?})`——**单位是「分段任务 + 一个切片」，不是「焊缝的一个版本」**，所以 props **没有** `selectedVersionId`（`embedded` 只声明不解构，与 `AlignmentWorkspace` 同一写法）。两段式（同 `SampleAnnotationWorkspace`）：
  - 阶段 ①：`listSampleFeatureTasks(dataId)` → 「最近一次成功」卡 + 折叠的历史任务（`segment-history-toggle`）+ 删除（`ConfirmDialog` → `deleteSplitTask`，文案说明特征一并删除）；空态引导去「样本分段」。
  - 阶段 ②（`FeatureSliceView`）：切片条按 `BATCH_SIZE=40` 分批（「加载更多」，**全量的是索引不是媒体**）→ 选中片详情（`getSampleFeature` 取完整 36 维 + `getFileUrl` 只给**这一片**换代表帧 URL）→ 归一化 chips（**只影响导出文件**）+ 「执行提取/重新提取」（`createSampleFeatureExtraction` + `useJob` 轮询，成功后重拉列表）→ 导出 JSON/CSV（任务级接口）+ 「换个分段任务」。
  - **无 mock 初始态**：初始一律空集合 + loading，失败走 `ErrorState`。本页此前是全局 mock 禁令的**唯一例外**（"特征表刻意保留 mock 初始"），这一版起**退休**——`src/CLAUDE.md` 里那条例外已删除。
- `featureRows.ts`：展示行映射（`TS_ROWS`/`mapTsRows`、`VISION_ROWS`/`VISION_DESC`/`mapVisionRows`、`unifiedPalette`/`mapUnifiedGroups`）。**从原 `FeatureExtractionPage.tsx` 抽出来的**——按结构形状取数（`ts_features`/`vision_features`/`unified_vector` 同构），所以版本级与切片级都能用。**没有声音组**。

## 调用链

- 被谁调用：`src/App.tsx`（`analysis/features` 懒加载）。
- 调用谁：`src/api/sampleFeatures`（本页专属）、`src/api/analysis`（`deleteSplitTask`）、`src/api/files`（代表帧 URL）、`src/hooks/useJob`、`src/shared/components`（PageIntro/ErrorState/ConfirmDialog）、`../analysis/signals/chartData`（`fmt`）。

## 关键规则/坑

- **36 维 = 时序 28（cur 8 / vol 8 / gas 6 / wir 6）+ 视觉 8（几何 4 / 纹理 4），无声音组**。切片 manifest 自己就写着 `audio.available = False`，音频上传也已在 2026-10 收口拒收——**没有真实源就不占维度**，别拿合成音频凑 6 维。
- **落库的权威向量恒为原始值**（`normalization="无"`）。归一化 chips 只作用于**导出文件**：`_normalize` 是对**单个向量**运算的，逐切片 Z-Score 会把每片各自减均值、抹掉区分切片的那批量（电流均值/RMS/气体水平）；跨切片标准化属于训练侧、按 train 划分拟合。
- **只有「已完成 + v3」的分段任务可提特征**（后端 `splitting.segment_task_block_code` 判定，与段级标注工作台**同一份查询**、各自措辞）。历史口径的切片没有统一时间窗，逐切片特征对它不成立。
- **代表帧只给选中那一片签 URL**：任务几百片时全量预签名是几百次请求；列表行只带 `frame_key`，`getFileUrl` 按需换。
- **未提取不是错误**：列表行 `extracted:false`、详情 `feature:null`，都按正常态展示（"还没跑"）。列表行**不带 36 个数值**。
- **视觉缺失是逐片降级**：该片 `vision` 记 `missing` + 逐片 `warnings`（服务端给原因），任务仍成功、`status="partial"`；其余片照常。**别**把"有一片缺帧"当成整批失败去拦。
- 回归：`src/App.sample-features-regression.test.mjs`。
