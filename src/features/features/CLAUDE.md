# CLAUDE.md — src/features/features/

分析与标注·特征提取页（2026-08-29 重构自 App.tsx 抽出）。目录名 `features` 与功能「特征提取」同名，易混淆。

## 文件

- `FeatureExtractionPage.tsx`：`FeatureExtractionPage({dataId})`——「执行提取」工具栏按钮 → `extractFeatures`（归一化/格式读 UI 状态，L2 范数↔L2 映射）→ 三类特征表（时序 `TS_ROWS` / 视觉 `VISION_ROWS`+`VISION_DESC` / 音频 `AUDIO_ROWS`）+ 统一向量条由结果映射。`getWeld` 取上下文。

## 调用链

- 被谁调用：`src/App.tsx`（`analysis/features` 懒加载）。
- 调用谁：`src/api/analysis`（extractFeatures）、`src/api/welds`（getWeld）、`src/shared/components`（Toolbar/PageIntro）。

## 关键规则/坑

- **特征表刻意保留 mock 初始/兜底**（仅用户点「执行提取」才被接口覆盖）——这是全局 mock 禁令的唯一例外约定，见 `src/CLAUDE.md`。
- 三类特征展示行由结果数组映射，后端 42 维统一向量对应 `groups`；归一化（Z-Score/Min-Max/L2/无）从前端 UI 状态读取传给接口。
