# CLAUDE.md — src/features/alignment/

分析与标注·多模态对齐 + 数据切分工作区（2026-08-29 重构自 App.tsx 抽出）。`AlignmentWorkspace` 一个组件按 `splitOnly` 呈现两种形态。

## 文件

- `AlignmentWorkspace.tsx`：`AlignmentWorkspace({splitOnly, dataId})`。
  - `splitOnly=false`：**多模态对齐·时间轴对齐工作室**（`studio-ruler` 共享时间标尺 + 各模态 `lane` 轨道 + 模态勾选 → `createAlignmentTask`）。
  - `splitOnly=true`：**数据切分·样本生产流水线**（步骤条 + 切分条带 + 统计 + 规则面板 + 预览网格）→ `createSplitTask`。
  - 内部：`AvailabilityTag`（轨道可用性角标）、`ScissorsIcon`；常量 `VIDEO_EXTS`/`ALIGN_CHANNEL_MAP`/`ALIGN_TRACK_META`。

## 调用链

- 被谁调用：`src/App.tsx`（`analysis/alignment`、`analysis/split` 懒加载）。
- 调用谁：`src/api/analysis`（createAlignmentTask/createSplitTask）、`src/api/welds`（getWeld/listVersions）、`src/api/files`（getFileUrl）、`src/api/analysis`（getSignals）、`src/hooks/useJob`、`src/shared/components`（Toolbar）。

## 关键规则/坑

- **对齐页已真实化**：`listVersions` 找 v1.0 → 按视频扩展名取 key → `getFileUrl` 渲染 `<video>`；`getSignals(v1.0)` 真实波形画进轨道；成功/失败横幅（`event_source`/`job.error.message`）。
- **T10 切分单位（2026-09-14）**：切分页新增**切分单位**选择（帧 / 秒）。帧率有两个来源——本次跑完对齐的 `alignRes.tracks`、或**最近一次已存**对齐任务的视频元数据（切分页单独取一次帧率，**不设置 jobId**，否则会把上一次对齐的终态显示成一次切分结果）；拿不到帧率时禁用"帧"、切到"秒"并把数值换成秒量级（10 → 0.4），页面提示"没有视频帧率时只能按秒切分"。统计卡给出**两种口径**：切片时长（帧 与 = N.NNN 秒）、时序窗口（采样点数 @ 采样率）、切片步长、预计切片；换算只在组件里做一次（`windowSeconds`/`strideSeconds`/`windowSamples`），请求把 `unit` 一并发给后端。用户手动改过单位后不再自动切换（`unitTouchedRef`）。
- **切分页缓冲秒数可编辑**：`keep_event_buffer` 按准确数值透传，关闭时传 0（回归测试 `App.buffer-regression.test.mjs` 断言此行为）。
- 此页不展示切分规则/输出格式/预览按钮（`splitOnly=false` 形态）——避免「点创建切分任务实跑对齐任务」的错位。
- 对齐/切分 Job 用 `useJob` 轮询；需先选焊缝（`selectedDatasetId + selectedDataId`），否则 `SelectionRequired`。
