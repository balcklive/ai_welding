# CLAUDE.md — src/features/analysis/signals/

信号图表坐标系工具（演示/布局坐标常量）。

## 文件

- `chartData.ts`：`CH`/`CW`/`AXIS_L`/`AXIS_B`/`PLOT_W`/`PLOT_H`（SVG 画布尺寸）、`dur`（5.42s）、`SAMPLES`（216）、`t`（时间轴）、`seg(s,e)`、`arc`/`weldS`/`weldE`/`ext`、`isArc(x)`/`isWeld(x)` 等演示焊接事件坐标。

## 调用链

- 被谁调用：`src/features/annotation/AnnotationWorkspace.tsx`（`fmt` 时间格式）、`src/features/analysis/AnalysisWorkspace.tsx`（布局常量）。
- 调用谁：无。

## 关键规则/坑

- **`SAMPLES`/`dur` 是演示常量，不是真实数据坐标**：真实波形以 `getSignals` 返回的 `values`（已抽稀）和 `times` 为准，勿用这里的 `SAMPLES` 归一化（见 `src/CLAUDE.md` Task 23 分析页映射约定）。
