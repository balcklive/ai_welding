# CLAUDE.md — src/features/datasets/

数据管理·数据集工作区（2026-08-29 重构自 App.tsx 抽出）。严格按 **数据集列表 → 数据集概览 → 当前快照成员 → 成员详情** 层级展示。

## 文件

- `DatasetWorkspace.tsx`：
  - `DatasetWorkspace`（入口，`view` 状态机：list / overview / records / dataset-records / record-detail）；含**删除数据集**入口（`deleteDataset`，后端引用检查拒绝）。
  - 内部组件：`DatasetDetail`（概览 + 删除条）/ `DatasetDetailContent` / `DatasetRecords`（快照成员）/ `DatasetSourceRecords`（全部焊缝）/ `RawSignalPreview`（原始多通道波形，复用 `/signals`）/ `RawMediaPreview`（视频/图片预览）/ `DatasetRecordDetail`（成员详情，设置 `selectedDataId`）/ `DatasetInputPanel`（输入维度）/ `ModelReadiness`（模型适配检查）。**2026-09 多模态字段**：`RawSignalPreview` 不再写死 `channels` 过滤 → 后端返回该焊缝全部分量通道（核心 4 + 焊接速度/六轴/熔池扩展）逐个 toggle；`DatasetSourceRecords` 源记录表新增「送丝 / 焊接速度」列；`DatasetRecordDetailContent` 数据详情加「送丝速度/焊接速度」InfoRow，且含 `record.data_fields` 时额外渲染「采集字段概览」段（全通道稳态代表值）。
- `fallbacks.ts`：`fallbackDatasetOptions`——接口失败时的兜底数据集选项（仅 catch 分支使用）。
- `weldRows.ts`：`toWeldRow(record)`——`DataRecord → WeldRow` 映射；`mockWeldRows`——兜底焊缝行（仅接口失败时用）。

## 调用链

- 被谁调用：`src/App.tsx`（`data-center/datasets` 懒加载）。
- 调用谁：`src/api/datasets`（listDatasets/createDataset/deleteDataset/getDataset/getDimensions/getReadiness/listDatasetVersions/getDatasetVersion/listDatasetVersionItems/createDatasetVersion）、`src/api/welds`（listWelds/getWeld/deleteWeld）、`src/api/files`（getFileUrl）、`src/api/analysis`（getSignals）、`src/shared/components`、`src/features/versions/VersionDetailDrawer`（mode="dataset"）。

## 关键规则/坑

- **层级与重绑定**：列表页不内嵌概览；真实 `listDatasets` 成功后，选中版本必须重绑定为所选数据集的 `current_version_id`（无当前版本则为 `null`），不得保留 mock 版本。
- **成员数据源**：`DatasetItemRow` 是固定 `dataset_items` 快照的样本粒度行；筛选 `q/quality/split` 必须由 `listDatasetVersionItems` 请求服务端，**不能前端全量后过滤**；成员行/总数初始为空 + loading 态，绝不用 `mockDatasetItemRows` 作初始值（会闪假数据）。
- **成员详情只接受行中真实 `weld_id`** 调 `getWeld`，绝不以 `sample_id` 代替焊缝 ID。
- 删除数据集/焊缝是后端强制引用检查的破坏性操作：后端拒绝时展示 409 错误文案；删除成功后 `window.location.reload()`。
- `RawSignalPreview` 的 effect 重跑时先 `setChannels([])` 清空旧波形，防止旧版本波形闪图。
