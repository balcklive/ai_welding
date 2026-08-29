# CLAUDE.md — src/features/versions/

版本详情抽屉 `VersionDetailDrawer`（右侧抽屉）。区分两类版本：**焊缝版本**（单条焊缝的处理历史）与**数据集快照**（固定样本清单），两种 mode 复用同一抽屉。

## 文件

- `VersionDetailDrawer.tsx`：`VersionDetailDrawer({mode, weldId, versionId, onClose} | {mode:'dataset', datasetId, version, onClose})`——mode="weld" 读版本详情 + 核验结果（`getVersion`/`getValidation`）；mode="dataset" 读数据集快照详情（`getDatasetVersion`）。

## 调用链

- 被谁调用：`src/features/data-context/DataContext.tsx`（`VersionPanel`，mode="weld"，点「查看」打开）、`src/features/datasets/DatasetWorkspace.tsx`（概览快照行，mode="dataset"）。
- 调用谁：`src/api/welds`（getVersion/getValidation）、`src/api/datasets`（getDatasetVersion）、`src/shared/components`。

## 关键规则/坑

- 严格区分「焊缝版本」与「数据集快照」称呼，页面不单独显示含义不明的「版本」（见 `docs/Playwright 菜单功能测试计划.md` §15 与 §17 VERSION-003）。
- 焊缝版本显示核验结果；数据集快照显示样本数/划分/质量，两者不混用字段。
