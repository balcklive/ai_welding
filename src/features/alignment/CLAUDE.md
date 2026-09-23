# CLAUDE.md — src/features/alignment/

分析与标注·多模态对齐（标定层）+ 样本分段工作台。

## 文件

- `AlignmentWorkspace.tsx`：**多模态对齐 · 时间轴对齐工作室**。`studio-ruler` 共享时间标尺 + 各模态 `lane` 轨道 + 模态勾选 → `createAlignmentTask`；`listVersions` 找 v1.0 → `getFileUrl` 渲染 `<video>`、`getSignals(v1.0)` 画真实波形；`getCalibration` 取标定（offset 供播放器 seek 换算、`seam_image` 供 ROI 面板回显）；ROI 保存走 `handleSaveRoi` → `updateCalibration({seam_image: {roi} | {excluded:true}})`（**本页是全站唯一能改 ROI 的地方**）；成功/失败横幅（`event_source`/`job.error.message`）。内部件：`AvailabilityTag`、`SeamRoiEditor`、常量 `VIDEO_EXTS`/`ALIGN_CHANNEL_MAP`/`ALIGN_TRACK_META`。
- `SeamRoiEditor.tsx`：**焊缝图片 ROI 标定面板**（2026-09-23）。真实照片上拖拽框选 → 按 `naturalWidth/Height` 把鼠标位置换算回**原始像素**（ROI 是像素坐标，不是归一化值）→ `PUT …/calibration`（越界由服务端比图片宽高拒绝，错误原样显示）；「不对焊缝图片进行分段」写 `excluded: true`。**不写 ROI 的框（draft）绝不影响产出**——分段页与正式任务只认已保存的那份。
- `split/`：**样本分段工作台（v3）**，见 `split/CLAUDE.md`。

## 调用链

- 被谁调用：`src/App.tsx`（`analysis/alignment` → `AlignmentWorkspace`；`analysis/split` → `split/SplitWorkspace`）。
- 调用谁：`src/api/analysis`、`src/api/welds`、`src/api/files`、`src/hooks/useJob`、`src/shared/components`、`../analysis/signals/chartData`。

## 关键规则/坑

- **`splitOnly` 双形态已删除（2026-09-22，v3）**。分段不再是 `AlignmentWorkspace` 的一个变体，而是独立工作台 `split/SplitWorkspace`；本页只负责"建立统一坐标系"（标定）。**不要再把切分规则塞回这一页**——历史上出过"点创建切分任务实跑对齐任务"的错位。
- **职责边界（§4.1）**：本页 = 标定层（offset / ROI / 焊接速度来源，产出 mapping + 新版本）；分段页 = 切分层（只读标定，改时长/步长、预览、生成样本）。
- **视频 seek 必须成对换算**：seek 写 `currentTime = Math.max(0, t - videoOffset)`，`onTimeUpdate` 写回 `currentTime + videoOffset`。只改一处，seek 后游标会被立刻拨回原位。
- **标定 UI 已落地（2026-09-23）**：焊缝图片 ROI 框选在 `SeamRoiEditor`；**左键拖拽是唯一手势**（无缩放手柄，倾斜焊缝的旋转矩形仍留后续）。offset 仍只有 `PUT` 接口、页面暂无滑块（设计 §12.6 的 `CalibrationPanel` 只做了 ROI 这一半）。
- **「不参与分段」与「还没框 ROI」必须在服务端分开**（`calibration.seam_image.excluded`）：两者都让图片模态在预览/manifest 里记 `available=false`，但**原因与引导不同**——前者不该再催用户去标定。只把 ROI 清成 `null` 会把前者显示成后者，所以不参与走 `excluded`、不清 ROI；想回到"未标定"才用 `{seam_image: null}` 清空整组。
- 对齐/切分 Job 用 `useJob` 轮询；需先选焊缝（`selectedDatasetId + selectedDataId`），否则 `SelectionRequired`。
