# CLAUDE.md — src/components/annotation/

- `AnnotoriousImageEditor.tsx`：Annotorious v3 React 封装，提供图片矩形框和多边形绘制、已有标注加载、几何变化监听以及到平台 `box/points` 结构的转换。组件不直接请求 API，由页面显式保存。

时序标注继续由 ECharts 实现；视频帧可以复用本组件。图片坐标以原始像素为准。
