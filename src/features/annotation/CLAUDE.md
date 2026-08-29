# CLAUDE.md — src/features/annotation/

分析与标注·数据标注工作区（2026-08-29 重构自 App.tsx 抽出）。图像/时序/视频三模式。

## 文件

- `AnnotationWorkspace.tsx`：
  - `AnnotationWorkspace({dataId})`：入口，三模式切换栏（图像/时序/视频）。
  - 图像模式：真实焊缝图 + `AnnotoriousImageEditor`（矩形/多边形）+ 标签类别（`listLabelCategories`，失败兜底 `mockLabelCategories`）+ AI 预标注（`aiPretag`）+ `saveAnnotation` 覆盖写保存。
  - `AnnotationSignal({dataId})`：时序标注（ECharts 波形点击设起点/终点选缺陷区间，kind='segment'）。
  - `AnnotationVideo({dataId})`：视频标注（播放/捕获帧 → Annotorious 画多边形 → `createAnnotationFrame` + saveAnnotation kind='polygon'）。

## 调用链

- 被谁调用：`src/App.tsx`（`analysis/annotation` 懒加载）。
- 调用谁：`src/api/analysis`（listLabelCategories/createAnnotationTask/listAnnotationSamples/getAnnotationSample/getSignals/aiPretag/saveAnnotation/createAnnotationFrame）、`src/api/welds`（getWeld/listVersions/getVersion）、`src/api/files`（getFileUrl）、`src/components/annotation/AnnotoriousImageEditor`（懒加载）、`src/hooks/useJob`、`src/features/analysis/signals/chartData`（fmt）。

## 关键规则/坑

- **标注必须真实数据**：图像模式从当前焊缝版本的真实图片对象建 manual 样本；`AnnotationSignal` 只允许 `getSignals().source === 'real'` 的波形进入标注；`AnnotationVideo` 只播放当前版本对象存储中的真实视频。
- **Annotorious key 重挂载**：图像编辑器按 `${imageEditorKey}-${sample?.id}`、视频按帧 `captureKey` 加 key，切换样本/工具/帧时重挂载以重置标注（勿复用同一实例，否则新图片不加载标注）。
- **波形两级加载**：首屏 `getSignals(max_points:2048)`；`dataZoom` 停止（300ms 防抖）后按可见窗口 `{max_points:4096, start, end}` 增量取细节；stale 响应用 `fetchTokenRef` 丢弃。坑：传 `max_points` 后 api 层不再本地 decimate。
- **视频预览兜底**：`<video>` 挂 `onError` → 明确原因（`MediaError.code===4` = 编码不支持，提示 media_prep 转码预览版）。
- 标签类别 `listLabelCategories` 带 10 分钟缓存（`api/analysis`）；后端无 `source=manual` 样本时，样本图从所属焊缝版本 object_keys 取真实图，无图显空态不回落静态演示图。
