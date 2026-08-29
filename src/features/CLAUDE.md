# CLAUDE.md — src/features/

按业务域拆分的前端工作区页面（2026-08-29 重构自 `src/App.tsx` 巨型单文件）。每个子目录一个业务域，页面组件统一由 `src/App.tsx` 的 `WorkspaceFrame` 按路由懒加载（`React.lazy`）渲染。

## 目录

- `overview/`：数据总览（`OverviewPage`）。
- `datasets/`：数据管理·数据集（列表→概览→快照成员→成员详情 + 原始波形/媒体预览 + 数据集/焊缝删除）。
- `registration/`：数据管理·数据登记（新建操作，不要求先选数据）。
- `validation/`：数据管理·数据核验（15 项规则）。
- `versions/`：`VersionDetailDrawer` 版本详情抽屉（焊缝版本 / 数据集快照两种 mode）。
- `analysis/`：分析与标注·起收弧识别（`AdvancedWeldAnalysis` + 六种图表 + `signals/chartData` 演示坐标系工具）。
- `annotation/`：分析与标注·数据标注（图像/时序/视频三模式，基于 Annotorious）。
- `alignment/`：分析与标注·多模态对齐 + 数据切分（`AlignmentWorkspace`，`splitOnly` 双形态）。
- `models/`：模型中心（训练数据准备/模型资产/新建训练/测试评估/推理验证）。
- `features/`：分析与标注·特征提取（`FeatureExtractionPage`）。
- `data-context/`：全局「先选数据」上下文（选择器/选择引导/数据集两级选择/版本面板），由 `App.tsx` 复用。

## 调用链

- 被谁调用：`src/App.tsx`（`WorkspaceFrame` 按 route 懒加载各 workspace；`DataContext` 系列组件被 AppShell/WorkspaceFrame 复用）。
- 调用谁：`src/api/*`（接口层）、`src/shared/*`（通用组件/工具）、`src/hooks/useJob`（异步任务轮询）、`src/components/annotation/AnnotoriousImageEditor`（标注编辑器）、`src/app/navigation`（Route 类型）。

## 关键规则/坑

- **mock 全局禁令**：任何会被接口成功响应覆盖的 state，初始值一律不得用 mock（会在响应前闪假数据），必须初始为空 + loading 态；mock 仅允许在 catch 失败分支兜底。已修复清单见 `src/CLAUDE.md`。
- **「先选数据」上下文**：基于单条焊缝的操作（核验/版本/分析/标注等）必须先经 `DataContext` 选中焊缝；`data-center/registration` 是新建操作，不在 `routesRequiringData` 内。
- 新增 feature 目录必须同步：本目录 CLAUDE.md + `src/app/navigation.ts`（Route/navStructure/workspaceHeaders）+ `src/App.tsx`（懒加载映射）。
- 每个子目录均有自己的 `CLAUDE.md` 记录文件职责、调用链与坑。
