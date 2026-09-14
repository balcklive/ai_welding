# CLAUDE.md — src/features/data-context/

全局「先选数据」上下文（2026-08-29 重构自 App.tsx 抽出）。被 `App.tsx` 的 `AppShell`/`WorkspaceFrame` 复用，非独立路由页。

## 文件

- `DataContext.tsx`：
  - `SelectionSwitcher`：工作区顶部的数据集/焊缝切换器（读 `selectedDatasetId`/`selectedDataId`；`onChange` 在数据管理回到数据集列表）。
  - `SelectionRequired({onBack, onSelectHere})`：未选数据时的引导占位。**T5/S3（2026-09-14）**：真正的选择器就在本页顶部，原来那个"前往选择数据"却跳到数据集列表——给了 `onSelectHere` 时改为渲染「在本页选择数据」（点击聚焦并高亮顶部选择器，见 App 的 `focusDataSwitcher`）+ 一个「去数据集列表」兜底出口；调用方不给 `onSelectHere` 时保持旧行为。
  - **T9（2026-09-14）**：两个选择器都改成**服务端搜索**——`SelectionSwitcher` 的样本下拉前加「搜索样本」输入框（300ms 防抖 → `listWelds({dataset_id, q, page_size:50})`），`AnalysisSelect` 第二级卡片同样加搜索框（原先固定拉 50 条且没有翻页入口，第 51 条之后永远选不到）；数据集下拉一律走 `listDatasetOptions()`（`?options=1` 轻量全量，D19）。
  - `SelectionSwitcher` 新增 `emphasis`（T5）：本页需要数据上下文却没选时，容器加 `.needs-attention`（边框/底色强调）并把提示文案换成「本页需要数据上下文：请先选择数据集和一条样本」。容器固定 `id="data-context-switcher"`，供守卫按钮聚焦。
  - `DatasetTestingContext`：数据集上下文条（测试用）。
  - `AnalysisSelect`：分析「选择数据」两级选择——第一级 `listDatasets` 下拉，第二级 `listWelds({dataset_id})` 全部样本；**仅 `quality===异常` 的卡片 disabled 置灰**（待复核可进）。**T3.2：两级 mock 兜底已删除**，失败分别置 `datasetError`/`weldError` → `ErrorState` + 重试（`reloadKey`）。
  - `VersionPanel`：只读版本链（`listVersions`）+ 新建数据版本（`createVersion`）+ 执行核验（`runValidation`）+ `VersionDetailDrawer`（mode="weld"）打开；`VersionCreateDialog` 内部组件。
  - `SelectionContext`：`getWeld` 拉当前选中焊缝详情（失败才回 mock 行）。

## 调用链

- 被谁调用：`src/App.tsx`（AppShell 维护全局 `selectedDatasetId`/`selectedDataId`；`WorkspaceFrame` 顶部渲染 `SelectionSwitcher`；分析/核验/版本等路由未选中时渲染 `SelectionRequired`）。
- 调用谁：`src/api/welds`（listWelds/getWeld/listVersions/createVersion/runValidation）、`src/api/datasets`（listDatasets）、`src/api/files`（presignUpload/putFileDirect）、`src/features/datasets/weldRows`（toWeldRow）、`src/features/versions/VersionDetailDrawer`、`src/shared/components`（StatusPill/ErrorState）、`src/shared/lib/errors`（toUserMessage）。

## 关键规则/坑

- **「先选数据」核心约定**：核验/版本/分析等基于单条焊缝的操作必须先选中焊缝；`AnalysisSelect` 的 `onContinue` 设置 `selectedDataId` 后进入对齐。
- `AnalysisSelect` 仅核验异常卡片 disabled；待复核可进（若按「非通过即拦」会永远进不了分析流）。
- `SelectionContext` / `SelectionSwitcher` 的 `getWeld` 失败**显示原因**（`rowError`，上下文条内红字），不再回 mock 行（T3.2）。
- `GET /analysis/candidates` 已不再被 AnalysisSelect 消费（保留兼容）。
- 版本面板 mock 已删：加载期「版本链路加载中…」，失败「版本信息暂时无法读取」，不用 mock 版本链作初始值。
