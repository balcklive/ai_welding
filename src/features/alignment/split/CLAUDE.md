# CLAUDE.md — src/features/alignment/split/

样本分段工作台（v3，设计 §7.1）。**秒是唯一切分单位**，屏幕上的窗口/边界/数量一律以服务端成功预览为准——这里不复制任何切分算术。

## 文件

- `SplitWorkspace.tsx`：状态编排（§7.2）。`draftRules`（用户编辑值）/ `appliedPreview`（最后一次**成功**预览 + 其规则指纹）/ `selectedWindowIndex`；300ms 防抖 + `fetchTokenRef` 丢弃在途旧响应；创建任务只提交 `preview_token`。还负责取视频签名 URL 与 v1.0 标定 offset（seek 用）。**焊缝照片的键取服务端预览的 `seam_image_projection.object_key`**（见下"坑"），不再用扩展名启发式去猜。播放器已移到选中切片详情面板，本页**不再持有 `videoRef` / `onSeek`**。
- `SplitRulesPanel.tsx`：秒级规则（时长/步长/事件起止/缓冲/尾片策略）+ **只读标定摘要** + warnings + 创建按钮。
- `MultimodalTimeline.tsx`：共用比例尺的标尺 + 三条轨道 + 切片卡片；边界线贯穿全部轨道（§4.4）。**切片卡片显示该段自己的视频代表帧**（2026-09-23）：`w.video.frame.url` 是真帧（后端逐段抽帧 + 短期预签名 URL），取不到就显示 `frame.reason`——**不许用占位渐变或全局首帧冒充缩略图**，所以无帧的卡片走 `.sample-thumb-empty` 浅底 + 原因文字。`t_signal`/`t_video`/`frame_no` 一律用服务端给的值，前端不再自己换算。
- `SignalTimelineLane.tsx`：时序轨。按 `times[]` 的真实秒数画（服务端 min-max 抽稀非均匀，按序号均分会画错尖峰位置）。
- `VideoTimelineLane.tsx`：**视频轨 = 胶片条，一段一格**（2026-09-23 重做）。每格是本段自己的代表帧（`w.video.frame.url`），格宽 = 该段时长占比（`pctOf(w.start/end, duration)`），相邻格的缝隙就是切片边界；点格子 = `onSelect(w.index)`（与卡片网格同一入口）。**轨道里没有 `<video>`、没有 `lane-marker`**——旧写法是"一个播放器 + 80 个缩略图时间点竖线"，屏幕上只有一个画面加一堆等距竖线，看着像"对一张图在分段"。取不到帧的格子给原因（`frame.reason`）并走浅底 `.film-cell-empty`（深底看着像真有画面）。
- `SeamImageLane.tsx`：焊缝图片投影带（只读）。**横轴是沿焊缝的长度，不是时间**：照片按 `roi.w/roi.h` 反算放大倍率与偏移，只显示 ROI 那一块（`.seam-lane-photo` + 行内 `maxWidth/maxHeight:none` 顶掉 Tailwind preflight）；边界取自每段的 `seam_image.spatial_range.start_px`（末尾补 `end_px`），经 `pxPct = (px - roi.x)/roi.w` 落位。**没有已保存的 ROI 就绝不渲染原图**（`ready` 必须含 `projection.roi`），改显示空态 + 去对齐页框选的引导链接；`projection.excluded`（用户已明确选择不参与）走另一种文案，**不再催去标定**。
- `SliceDetailPanel.tsx`：选中切片详情。波形是把服务端已降采样的轨道**按窗口裁剪**的读派生视图，不额外发请求。**视频播放器在这里**（`key={window.index}` 换段重挂载 + `onLoadedMetadata` seek 到本段起点）：seek 写 `Math.max(0, t_signal - offset)`、`onTimeUpdate` 回写 `currentTime + offset`——**两处必须成对**，否则 seek 后游标会被立刻拨回去。代表帧同 `MultimodalTimeline`：预览显示 `<img>`（`frame.url`），产物路径显示可点开的对象键；取不到就写 `frame.reason`。
- `splitTypes.ts`：纯类型与派生计算（`RulesDraft` / `draftToRules` / `draftKey` / `pctOf` / `timePath` / `trackRange`）。

## 调用链

- 被谁调用：`src/App.tsx`（路由 `analysis/split` 懒加载）。
- 调用谁：`src/api/analysis`（`previewSplitTask` / `createSplitTask` / `getSplitTask` / `getCalibration`）、`src/api/files`、`src/api/welds`、`src/hooks/useJob`、`src/shared/components`、`../../analysis/signals/chartData`（`chanColorOf`）。

## 关键规则/坑

- **不在前端算正式窗口数**（§7.1 末段）。服务端 300ms 内会回权威值；本地算一份就会漂移，而漂移的表现是"预览 207、执行 208"这种最难查的 bug。`splitTypes.ts` 刻意不提供预估函数。
- **分段页不可编辑标定**（§4.3）。改 offset/ROI 只能去对齐页（`SeamRoiEditor`）；这里是"所见即所得"的前提——页面上任何一个边界都必须能在服务端复现。本目录**不得调用 `updateCalibration`**（回归测试 `src/App.roi-calibration-regression.test.mjs` 有断言）。
- **预览与正式任务共用同一份已保存标定**：预览请求体里没有标定，映射每次从 v1.0 权威标定现读——所以"预览里看到的就是切出来的"，页面上的未保存改动不会影响产出。
- **`draftKey` 与服务端 `rules_hash` 不是同一个东西**：客户端算不出服务端的 canonical JSON 哈希，所以存**请求体本身**做 stale 比对（语义一致：请求体没变就不算 stale）。
- **服务端 min-max 抽稀是非均匀的**：波形必须按每点自带的 `times` 画（`timePath`），不能按序号均分。
- **视频元信息来自对齐产物**：预览不下载视频探 fps（§6.4），所以**从未跑过对齐**的焊缝在预览里视频模态就是不可用的（带原因）。这是 §4.1 的真实链路顺序：对齐页标定 → 运行对齐 → 分段页消费。**例外（2026-09-23）**：逐段代表帧要求下视频抽帧，所以"预览完全不碰视频字节"这条对代表帧不成立——代价是**首次**预览慢一些（每段一次 ffmpeg，不设段数上限）。**第二次起免费**：`attach_preview_frames` 先 `stat_object` 探对象，已落盘的段直接复用（见 `backend/app/services/CLAUDE.md`）。
- **焊缝照片的键只认服务端预览给的那个**（`seam_image_projection.object_key`）：ROI 是照着对齐页那张图量的，分段页若用扩展名启发式自己挑（`keys.find(k => k.endsWith('.jpg'))`），可能先撞上对齐产物的 `processed/…/align/keyframes/*.jpg`——那就会拿一张对不上的照片去套 ROI 坐标。
- **两条轨的横轴不同**：视频/时序轨是**时间**，焊缝图片轨是**沿焊缝的长度**，只在匀速假设（`speed_source=none/scalar`）下才重合。焊缝图片轨的横轴不能改回按时间百分比——那正是"ROI 框了看不出效果、边界落在照片上错误位置"的成因。
- **代表帧的"没有"必须逐段说清**：视频不可用 / 该段落在视频覆盖范围外 / 该段中点在覆盖外 / 抽帧失败——四种原因都由服务端给，前端只展示、不自己编，也**不拿别的段或全局首帧顶替**。
- 视频/图片是**增强模态**：缺失只标记不阻断；`warnings[]` 会把未标定、无焊接速度、重叠、尾片等如实列出来。
