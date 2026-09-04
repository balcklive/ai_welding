# CLAUDE.md — src/features/analysis/

分析与标注·起收弧识别工作区（`AdvancedWeldAnalysis`，2026-08-29 重构自 App.tsx 抽出）。

## 文件

- `AnalysisWorkspace.tsx`：
  - `AdvancedWeldAnalysis({dataId})`：焊缝深度分析。`getSignals` 拉四通道真实波形（挂载/滤波变化时拉取，勾选仅本地过滤）+ `getAnalysisMode`（psd/stft/dwt/wavelet/phase/pdd，mode/目标通道/滤波联动）+ `getAnalysisResult`（稳定度/三类占比/异常区段 chips）。KPIs 使用真实 `record.quality` 与 `weldDuration`（`ac568ee` 修复，不再硬编码假值）。
  - 内部图表组件：`PhasePlot`/`PddChart`/`ExploreWaveform`/`PsdChart`/`StftHeatmap`/`DwtChart`/`WaveletDecomp`。
  - `SampleWaveThumb` + `SplitPreviewSample`：切分预览缩略（供切分产物展示）。
- `signals/chartData.ts`：演示坐标系常量与工具（`CH/CW/t/SAMPLES/seg/isArc/isWeld` 等）。**仅供图表布局复用，勿作为真实数据源**。

## 调用链

- 被谁调用：`src/App.tsx`（`analysis/analysis` 懒加载）。
- 调用谁：`src/api/analysis`（getSignals/getAnalysisMode/getAnalysisResult）、`src/api/welds`（getWeld）、`src/shared/components`（Toolbar/PageIntro）、`src/features/data-context`（通过 App.tsx 的 SelectionRequired 上下文）。

## 关键规则/坑

- **通道 id `cur/vol/gas/wir` 前后端一致**；后端不输出颜色 → `chanColor` 按 id 映射（`chartData.chanColorOf` 对扩展通道/未知通道按顺序/哈希稳定取色）。**2026-09**：时域波形 `getSignals` 不再写死 `channels` 过滤 → 后端返回该焊缝全部分量（核心 4 + 焊接速度/六轴/熔池扩展）；默认勾选核心 4，新增通道可在 toggle 中叠加查看。
- `getSignals` 返回 `values` 已由 api 层抽稀 ≤512，`toPath` 按 `values.length` 归一化横轴（**勿按 mock 的 `SAMPLES`**）。
- 六种图表都吃后端数组（`freqs/psd`、`magnitude`、`bands+approx`、`bands`、`current+voltage`、`bins+counts+kde`），未取到 API 时用 `values` 走原内部计算兜底（SVG 结构不动）；`DwtChart`/`WaveletDecomp` 有 API 时标签用后端 `band.name`。
- 滤波由后端计算（请求带 `filter_type/cutoff/cutoff2`），前端不再本地 `applyFilter`。
- 波形初始用 `emptyChannels` 占位保留通道骨架，防 `channels[0]` undefined 崩溃。
- 分析基于当前焊缝最新版本；`getWeld` 带 15s 前端缓存（`api/welds`），异步任务刚完成后重进页面可能短暂读到旧 `latest_version_id`。
