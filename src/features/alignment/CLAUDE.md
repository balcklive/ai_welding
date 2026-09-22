# CLAUDE.md — src/features/alignment/

分析与标注·多模态对齐（标定层）+ 样本分段工作台。

## 文件

- `AlignmentWorkspace.tsx`：**多模态对齐 · 时间轴对齐工作室**。`studio-ruler` 共享时间标尺 + 各模态 `lane` 轨道 + 模态勾选 → `createAlignmentTask`；`listVersions` 找 v1.0 → `getFileUrl` 渲染 `<video>`、`getSignals(v1.0)` 画真实波形；`getCalibration` 取 offset 供播放器 seek 换算；成功/失败横幅（`event_source`/`job.error.message`）。内部件：`AvailabilityTag`、常量 `VIDEO_EXTS`/`ALIGN_CHANNEL_MAP`/`ALIGN_TRACK_META`。
- `split/`：**样本分段工作台（v3）**，见 `split/CLAUDE.md`。

## 调用链

- 被谁调用：`src/App.tsx`（`analysis/alignment` → `AlignmentWorkspace`；`analysis/split` → `split/SplitWorkspace`）。
- 调用谁：`src/api/analysis`、`src/api/welds`、`src/api/files`、`src/hooks/useJob`、`src/shared/components`、`../analysis/signals/chartData`。

## 关键规则/坑

- **`splitOnly` 双形态已删除（2026-09-22，v3）**。分段不再是 `AlignmentWorkspace` 的一个变体，而是独立工作台 `split/SplitWorkspace`；本页只负责"建立统一坐标系"（标定）。**不要再把切分规则塞回这一页**——历史上出过"点创建切分任务实跑对齐任务"的错位。
- **职责边界（§4.1）**：本页 = 标定层（offset / ROI / 焊接速度来源，产出 mapping + 新版本）；分段页 = 切分层（只读标定，改时长/步长、预览、生成样本）。
- **视频 seek 必须成对换算**：seek 写 `currentTime = Math.max(0, t - videoOffset)`，`onTimeUpdate` 写回 `currentTime + videoOffset`。只改一处，seek 后游标会被立刻拨回原位。
- **标定写入目前只有接口**（`PUT …/calibration`）：页面上的 offset 滑块 / ROI 框选（§4.2 的 `CalibrationPanel`/`SeamRoiEditor`）**尚未实现**——见设计文档 §12.6。
- 对齐/切分 Job 用 `useJob` 轮询；需先选焊缝（`selectedDatasetId + selectedDataId`），否则 `SelectionRequired`。
