# CLAUDE.md — src/features/alignment/split/

样本分段工作台（v3，设计 §7.1）。**秒是唯一切分单位**，屏幕上的窗口/边界/数量一律以服务端成功预览为准——这里不复制任何切分算术。

## 文件

- `SplitWorkspace.tsx`：状态编排（§7.2）。`draftRules`（用户编辑值）/ `appliedPreview`（最后一次**成功**预览 + 其规则指纹）/ `selectedWindowIndex`；300ms 防抖 + `fetchTokenRef` 丢弃在途旧响应；创建任务只提交 `preview_token`。还负责取视频/焊缝照片签名 URL 与 v1.0 标定 offset（seek 用）。
- `SplitRulesPanel.tsx`：秒级规则（时长/步长/事件起止/缓冲/尾片策略）+ **只读标定摘要** + warnings + 创建按钮。
- `MultimodalTimeline.tsx`：共用比例尺的标尺 + 三条轨道 + 切片卡片；边界线贯穿全部轨道（§4.4）。
- `SignalTimelineLane.tsx`：时序轨。按 `times[]` 的真实秒数画（服务端 min-max 抽稀非均匀，按序号均分会画错尖峰位置）。
- `VideoTimelineLane.tsx`：视频轨。`seek` 写 `Math.max(0, t - offset)`、`onTimeUpdate` 回写 `currentTime + offset`——**两处必须成对**，否则 seek 后游标会被立刻拨回去。
- `SeamImageLane.tsx`：焊缝图片投影带（只读）。整张照片铺开为背景，边界按 `px(t)` 落下；未框 ROI 时显示"未标定"而非空白。
- `SliceDetailPanel.tsx`：选中切片详情。波形是把服务端已降采样的轨道**按窗口裁剪**的读派生视图，不额外发请求。
- `splitTypes.ts`：纯类型与派生计算（`RulesDraft` / `draftToRules` / `draftKey` / `pctOf` / `timePath` / `trackRange`）。

## 调用链

- 被谁调用：`src/App.tsx`（路由 `analysis/split` 懒加载）。
- 调用谁：`src/api/analysis`（`previewSplitTask` / `createSplitTask` / `getSplitTask` / `getCalibration`）、`src/api/files`、`src/api/welds`、`src/hooks/useJob`、`src/shared/components`、`../../analysis/signals/chartData`（`chanColorOf`）。

## 关键规则/坑

- **不在前端算正式窗口数**（§7.1 末段）。服务端 300ms 内会回权威值；本地算一份就会漂移，而漂移的表现是"预览 207、执行 208"这种最难查的 bug。`splitTypes.ts` 刻意不提供预估函数。
- **分段页不可编辑标定**（§4.3）。改 offset/ROI 只能去对齐页；这里是"所见即所得"的前提——页面上任何一个边界都必须能在服务端复现。
- **`draftKey` 与服务端 `rules_hash` 不是同一个东西**：客户端算不出服务端的 canonical JSON 哈希，所以存**请求体本身**做 stale 比对（语义一致：请求体没变就不算 stale）。
- **服务端 min-max 抽稀是非均匀的**：波形必须按每点自带的 `times` 画（`timePath`），不能按序号均分。
- **视频元信息来自对齐产物**：预览不下载视频探 fps（§6.4），所以**从未跑过对齐**的焊缝在预览里视频模态就是不可用的（带原因）。这是 §4.1 的真实链路顺序：对齐页标定 → 运行对齐 → 分段页消费。
- 视频/图片是**增强模态**：缺失只标记不阻断；`warnings[]` 会把未标定、无焊接速度、重叠、尾片等如实列出来。
