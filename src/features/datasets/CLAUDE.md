# CLAUDE.md — src/features/datasets/

数据管理·数据集工作区（2026-08-29 重构自 App.tsx 抽出）。严格按 **数据集列表 → 数据集概览 → 当前快照成员 → 成员详情** 层级展示。

## 文件

- `DatasetWorkspace.tsx`：
  - `DatasetWorkspace`（入口，`view` 状态机：list / overview / records / dataset-records / record-detail）；含**删除数据集**入口（`deleteDataset`，后端引用检查拒绝）。
  - **2026-09 新建数据集可选任务类型**：`新建数据集` 弹窗（`TextDialog` 的 `choice`）从系统设置字典 `dataset_task` 取启用项，`createDataset({name, task})` 的 `task` 不再写死「目标检测」；`taskOptions` 初始为空（加载期不闪现任何值）。**T3.2/T3.3（2026-09-14）**：字典请求失败**不再回落** `FALLBACK_DATASET_TASKS`（已删），改为置 `taskOptionsError` → 页面内 `ErrorState` + 重试 + 禁用「新建数据集」（S7 的 hover 提示同时改为页面内提示条）；字典成功但为空（管理员全删）同样禁用并页面内提示。
- **2026-09-14（T8 异步状态 + T9 规模底线）**：版本列表项显示构建状态（`build_status`：构建中 / 构建失败 / 已完成），**构建中的行不可进入切片**（`.dataset-version.building`，点击不跳转）且不显示"查看详情"；失败时给「重新构建」（`retryBuildTask`，后端幂等、不过手工闸门）。数据集列表改**服务端分页 + 关键字**（`listDatasets({q,page,page_size})`，页脚分页器；`listQuery` 变化回到第 1 页）；成员表与全部样本表每页条数统一默认 **20**，可选 20/50/100（`PAGE_SIZE_OPTIONS`，后端 `page_size` 上限 100）。
- **2026-09-15（S1：列表序号）**：数据集列表每行前置序号 `.dataset-row-index`，取值 `(listPage - 1) * LIST_PAGE_SIZE + index + 1`——**跨页连续**，与分页器「共 N 条」同口径（**不是每页从 1 重来**：那样第 2 页的"第 3 行"和搜索前的"第 3 行"会指向不同数据集）。它是**当前筛选结果的位置**，数据集的身份标识仍是 `dataset_no`（`DS-…`），沟通时以编号为准。**坑**：`index.css` 里 `.dataset-list-row` 的栅格列数与移动端媒体查询按 `span:nth-of-type(n)` 隐藏列，**插入序号列后这些下标全部右移一位**（隐藏列 3/4/5 → 4/5/6，栅格 `34px …` → `26px 34px …`）；再加列/加字段时要同步改这两处，否则窄屏会隐藏错列。界面契约回归见 `tools/data-center-ui-e2e.mjs`（含第 2 页序号接着 21 的跨页断言）。
- **2026-09-14（T6 骨架 + T5 上下文）**：五个视图的面包屑改由 `shared/components/PageScaffold` 的 `PageBreadcrumb` 渲染，用词按方案 §T6.2（列表为「数据管理/数据集」，最深层为「…/全部样本/{数据 ID}」），并为 4 个子视图补 `onHome`（回数据集列表）使面包屑可回流；三处 `dataset-context-card` 换成 `shared/components/ContextBar`（同一份样式类 `.context-bar`）。**S2**：`onDetailChange` 改为 `view !== 'list'`——「登记数据」入口在概览/版本成员/全部样本/成员详情都保留，不再只在概览出现。界面契约回归见 `tools/data-center-ui-e2e.mjs`（34 条，含面包屑用词/回流与上下文条）。
- **2026-09-14（T2 结构 + 术语）**：概览统计卡改为「样本数（`weld_count`）+ 切片数（`item_count`）」，有效切片占比改用新增的 `QualityStat` 组件，**只读后端 `effective_ratio`**（历史版本没有该字段 → 显示 `—`；**不得用三个 `*_rate` 反推**，各原因可重叠）；`DatasetInputPanel` 与 `ModelReadiness` 合并为 **`FieldCompleteness`（字段完备性）**，不再拉 `getReadiness`（后端闸门保留，模型中心自己按需拉）；成员表去掉「核验状态」列与筛选下拉、全部样本表去掉「核验状态」列并把送丝/焊接速度拆两列（`index.css` 的 `.dataset-record-row.member-row` / `.source-row` 分别声明列数）；成员详情去掉核验状态行与右侧徽标。界面契约回归见 `tools/data-center-ui-e2e.mjs`。
- **2026-09-14（T7 删除确认）**：数据集与样本的删除都改成自研 `ConfirmDialog`（不用原生 confirm，Q21）+ **后端预检** `getDatasetDeleteImpact` / `getWeldDeleteImpact`（与真删共用同一份引用规则）：弹窗列出"关联 · N / 将一并删除 · N"，有阻塞项时逐条说明原因并禁用确认；删除成功后**不再 `window.location.reload()`**，而是 `onDeleted` → 回列表并局部刷新。
- 内部组件：`DatasetDetail`（概览 + 删除条）/ `DatasetDetailContent` / `DatasetRecords`（快照成员）/ `DatasetSourceRecords`（全部焊缝）/ `RawSignalPreview`（原始多通道波形，复用 `/signals`）/ `RawMediaPreview`（视频/图片预览）/ `DatasetRecordDetail`（成员详情，设置 `selectedDataId`）/ `DatasetInputPanel`（输入维度）/ `ModelReadiness`（模型适配检查）。**2026-09 多模态字段**：`RawSignalPreview` 不再写死 `channels` 过滤 → 后端返回该焊缝全部分量通道（核心 4 + 焊接速度/六轴/熔池扩展）逐个 toggle；`DatasetSourceRecords` 源记录表新增「送丝 / 焊接速度」列；`DatasetRecordDetailContent` 数据详情加「送丝速度/焊接速度」InfoRow，且含 `record.data_fields` 时额外渲染「采集字段概览」段（全通道稳态代表值）。
- **2026-09-14（R4 / R2 / R3）**：① 成员页在 `versionSummary.annotations_frozen === false`（历史版本没冻结标注快照）时给一行如实说明——训练读的是「当前」标注、不受该版本约束；② `DatasetRecordDetailContent` 加「信号导入」InfoRow（`useIngestStatus`），失败时渲染独立的「信号导入失败」面板（逐个失败文件 + 原因 + 「重新导入」`reimportSignals`）——**刷新/换设备后仍能看到真实导入状态**（T4.4 的跨刷新恢复落点）；③ 字段完备性的时序维度改由后端按**真实导入通道**判定（R3），前端零改动。
- `weldRows.ts`：`toWeldRow(record)`——`DataRecord → WeldRow` 映射。**`mockWeldRows` 已删除（T3.2）**；`fallbacks.ts` 整文件已删除。

## 调用链

- 被谁调用：`src/App.tsx`（`data-center/datasets` 懒加载）。
- 调用谁：`src/api/datasets`（listDatasets/createDataset/deleteDataset/**getDatasetDeleteImpact**/getDataset/getDimensions/listDatasetVersions/getDatasetVersion/listDatasetVersionItems/createDatasetVersion）、`src/api/welds`（listWelds/getWeld/deleteWeld/**getWeldDeleteImpact**/**reimportSignals**）、`src/hooks/useIngestStatus`（信号导入状态）、`src/api/files`（getFileUrl）、`src/api/analysis`（getSignals）、`src/api/settings`（listOptionGroups，取 `dataset_task` 组）、`src/shared/components`（含带 `choice` 的 `TextDialog`）、`src/features/versions/VersionDetailDrawer`（mode="dataset"）。

## 关键规则/坑

- **层级与重绑定**：列表页不内嵌概览；真实 `listDatasets` 成功后，选中版本必须重绑定为所选数据集的 `current_version_id`（无当前版本则为 `null`），不得保留 mock 版本。
- **成员数据源**：`DatasetItemRow` 是固定 `dataset_items` 快照的样本粒度行；筛选 `q/quality/split` 必须由 `listDatasetVersionItems` 请求服务端，**不能前端全量后过滤**；成员行/总数初始为空 + loading 态，绝不用 `mockDatasetItemRows` 作初始值（会闪假数据）。
- **成员详情只接受行中真实 `weld_id`** 调 `getWeld`，绝不以 `sample_id` 代替焊缝 ID。
- 删除数据集/焊缝是后端强制引用检查的破坏性操作：后端拒绝时展示 409 错误文案；删除成功后 `window.location.reload()`。
- `RawSignalPreview` 的 effect 重跑时先 `setChannels([])` 清空旧波形，防止旧版本波形闪图。
