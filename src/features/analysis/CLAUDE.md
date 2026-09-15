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

- **时间轴/起收弧事件只来自接口（2026-09-15 修复）**：`getSignals` 成功且 `source==='real'` 时记 `signalDuration`（`data.duration`）与 `signalEvents`（`data.events`），`timelineDur = signalDuration ?? dur`；`ExploreWaveform`/`PhasePlot` 的游标映射、`explore-axis` 刻度（`timeTicks`，`.explore-axis` 是 `space-between`，**刻度必须等距**）、波形异常色带（吃 `result.anomalies`）、下方 `event-track` 起弧/稳态/收弧全部按真实值渲染。修复前这些一律用 `chartData` 的演示常量（`dur=5.42` / `anomalA`/`anomalB` / 写死的 `00:00.42 / 00:00.78-00:04.28 / 00:04.86`）——18s 的真实信号被画成固定 0–5s、且 KPI「有效焊接段」是真实值，两处自相矛盾。**`chartData.dur` 现在只在无真实信号（空波形）时兜底，勿再喂给正常渲染路径**。回归 `src/App.analysis-timeline-regression.test.mjs`。
- **通道 id `cur/vol/gas/wir` 前后端一致**；后端不输出颜色 → `chanColor` 按 id 映射（`chartData.chanColorOf` 对扩展通道/未知通道按顺序/哈希稳定取色）。**2026-09**：时域波形 `getSignals` 不再写死 `channels` 过滤 → 后端返回该焊缝全部分量（核心 4 + 焊接速度/六轴/熔池扩展）；默认勾选核心 4，新增通道可在 toggle 中叠加查看。
- `getSignals` 返回 `values` 已由 api 层抽稀 ≤512，`toPath` 按 `values.length` 归一化横轴（**勿按 mock 的 `SAMPLES`**）。
- 六种图表都吃后端数组（`freqs/psd`、`magnitude`、`bands+approx`、`bands`、`current+voltage`、`bins+counts+kde`），未取到 API 时用 `values` 走原内部计算兜底（SVG 结构不动）；`DwtChart`/`WaveletDecomp` 有 API 时标签用后端 `band.name`。
- **滤波参数按 Hz 呈现、只作用于目标通道（2026-09-15 修复）**：后端 `filter_type/cutoff/cutoff2` 里的
  `cutoff/cutoff2` 是**相对奈奎斯特（fs/2）的归一化频率**，Hz = `cutoff × sample_rate / 2`。
  修复前滑杆把归一化值 ×1000 当 Hz 显示（`0.30` 显示成“300 Hz”，实际 fs=5000 → 750 Hz、
  fs=20k → 3000 Hz，滑杆 min 0.05 也不是 50 Hz），且 `filterOn` 时**全通道**波形被替换成滤波结果、
  下方“滤波后”卡片画的又是同一份数据，导致“切换低通/高通/带通数据差异巨大 + 无法对比滤波前后”。
  现在：`sampleRate` 取自 `getSignals`（唯一 Hz 换算依据，未知时不给假数值）；两个滑杆按**对数刻度**在
  `MIN_FILTER_HZ ~ 0.99×奈奎斯特` 间调 Hz；`passbandText` 显式写出通带阈值（低通保留 0–f、高通 f–奈奎斯特、
  带通 f1–f2，含采样率/奈奎斯特提示）；切到带通自动整理 `cutoff < cutoff2`（否则后端 400）；
  **主波形与其它通道保持原始信号**，滤波结果只请求目标通道（`getSignals({channels:[filterChan], filter_type…})`）
  并画进 `FilterCompare`（上=原始、下=滤波后，各自按自身量程缩放并把量程写进图注），
  PSD/STFT/DWT/小波/相图/PDD 仍吃滤波后数据（分析端点自己带滤波参数）。
  回归 `src/App.analysis-filter-regression.test.mjs`。后端滤波仍由 `dsp.filter_signal` 计算（前端无本地 `applyFilter`）。
- **滤波后量程/直方图由后端按滤波后序列重算（2026-09-15）**：`GET …/signals` 带 `filter_type` 时返回的
  `lo/hi/mean` 是滤波后序列的统计（否则高通/带通去均值信号会按原始量程画成贴边直线）；
  `/analysis/pdd` 带滤波时直方图量程同理，避免全部落进首 bin。
- 波形初始用 `emptyChannels` 占位保留通道骨架，防 `channels[0]` undefined 崩溃。
- 分析基于当前焊缝最新版本；`getWeld` 带 15s 前端缓存（`api/welds`），异步任务刚完成后重进页面可能短暂读到旧 `latest_version_id`。
