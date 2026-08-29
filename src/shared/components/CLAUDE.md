# CLAUDE.md — src/shared/components/

通用 UI 组件（2026-08-29 重构自 App.tsx 抽出）。无业务逻辑，仅 props 渲染。

## 文件

- `InfoRow.tsx`：`InfoRow({label, value, accent})`——单行「标签/值」信息行（标注信息、详情页常用）。
- `PageIntro.tsx`：`PageIntro({eyebrow, title, description, action})`——页头区（眉题 + 标题 + 描述 + 右侧动作区），多数 feature 页复用。
- `StatusPill.tsx`：`StatusPill` + `StatusTone`（green/orange/red/blue/muted）——状态胶囊标签，`tone` 由调用方映射。
- `TextDialog.tsx`：`TextDialog({title, label, initialValue, onCancel, onConfirm})`——带输入框的轻量确认对话框（新建数据集等）。
- `Toolbar.tsx`：`Toolbar({action, secondary, onAction, onRefresh, actionDisabled, exportType, exportRefIds})`——页面顶部工具栏；**承担报告导出**：`exportType`/`exportRefIds` 传给 `api/reports.exportReport`，成功后 `window.open(url)`。

## 调用链

- 被谁调用：`src/App.tsx` 及 `src/features/*`（Toolbar 被 App/Analysis/Alignment/Validation/Features/Models 复用；PageIntro/StatusPill/InfoRow/TextDialog 被多数 feature 页复用）。
- 调用谁：`../lib/formatting` 等纯工具；**不 import api/feature**。

## 关键规则/坑

- `Toolbar` 的导出逻辑必须显式传 `exportType` + `exportRefIds`（页级 ref id，如 version_id），缺 ref 时后端按 `type` 语义处理；改导出走 `/reports/export`，勿在组件内直连其他接口。
- 通用件样式类名集中在 `src/index.css`；新增组件时同步补样式并保持 `.ghost-button/.primary-button/.danger-button` 等既有按钮体系。
