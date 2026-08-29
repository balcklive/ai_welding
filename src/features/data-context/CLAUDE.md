# CLAUDE.md — src/features/data-context/

全局「先选数据」上下文（2026-08-29 重构自 App.tsx 抽出）。被 `App.tsx` 的 `AppShell`/`WorkspaceFrame` 复用，非独立路由页。

## 文件

- `DataContext.tsx`：
  - `SelectionSwitcher`：工作区顶部的数据集/焊缝切换器（读 `selectedDatasetId`/`selectedDataId`；`onChange` 在数据管理回到数据集列表）。
  - `SelectionRequired`：未选数据时的引导占位（`onBack` 回选择页）。
  - `DatasetTestingContext`：数据集上下文条（测试用）。
  - `AnalysisSelect`：分析「选择数据」两级选择——第一级 `listDatasets` 下拉（失败兜底 mock），第二级 `listWelds({dataset_id})` 全部焊缝（失败兜底 mock）；**仅 `quality===异常` 的卡片 disabled 置灰**（待复核可进）。
  - `VersionPanel`：只读版本链（`listVersions`）+ 新建数据版本（`createVersion`）+ 执行核验（`runValidation`）+ `VersionDetailDrawer`（mode="weld"）打开；`VersionCreateDialog` 内部组件。
  - `SelectionContext`：`getWeld` 拉当前选中焊缝详情（失败才回 mock 行）。

## 调用链

- 被谁调用：`src/App.tsx`（AppShell 维护全局 `selectedDatasetId`/`selectedDataId`；`WorkspaceFrame` 顶部渲染 `SelectionSwitcher`；分析/核验/版本等路由未选中时渲染 `SelectionRequired`）。
- 调用谁：`src/api/welds`（listWelds/getWeld/listVersions/createVersion/runValidation）、`src/api/datasets`（listDatasets）、`src/api/files`（presignUpload/putFileDirect）、`src/features/datasets/weldRows`（mockWeldRows 兜底）、`src/features/versions/VersionDetailDrawer`、`src/shared/components`（StatusPill）。

## 关键规则/坑

- **「先选数据」核心约定**：核验/版本/分析等基于单条焊缝的操作必须先选中焊缝；`AnalysisSelect` 的 `onContinue` 设置 `selectedDataId` 后进入对齐。
- `AnalysisSelect` 仅核验异常卡片 disabled；待复核可进（若按「非通过即拦」会永远进不了分析流）。
- `SelectionContext` 初始 `row=null`，`getWeld` 失败才回 mock 行（防假数据闪现）。
- `GET /analysis/candidates` 已不再被 AnalysisSelect 消费（保留兼容）。
- 版本面板 mock 已删：加载期「版本链路加载中…」，失败「版本信息暂时无法读取」，不用 mock 版本链作初始值。
