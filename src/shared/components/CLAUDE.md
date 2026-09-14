# CLAUDE.md — src/shared/components/

通用 UI 组件（2026-08-29 重构自 App.tsx 抽出）。无业务逻辑，仅 props 渲染。

## 文件

- `PageScaffold.tsx`：**T6.1 新增**。导出 `PageBreadcrumb({crumbs})`（面包屑，`Crumb` 带 `onClick` 即渲染成可点回流）与 `PageScaffold({crumbs, context, children})`（**面包屑 → 上下文条（可选）→ 主体**）。工作区头不在这里——它在 `App.tsx` 的 `WorkspaceFrame`。**用词必须走术语表**（见 `docs/数据管理改造技术实施方案.md` §T6.2 的表）。
- `ContextBar.tsx`：**T6.1 新增**。`ContextBar({items, action})`，`items = [{label, value, hint?}]`——页面级上下文条（`所属数据集 | 数据 | 数据版本 | 状态 [更换]`）。顶部那个全局版本是 `features/data-context` 的 `SelectionSwitcher`，由 App 渲染在面包屑之后；本组件用于数据集层级里需要额外说明"当前在看哪个数据集版本"的页面。
- `ConfirmDialog.tsx`：**T4a/T7 新增**。`ConfirmDialog({title, description, items, confirmLabel, cancelLabel, tone, confirmDisabled, onConfirm, onCancel})`——确认弹窗（`tone="danger"` 走危险按钮），`items` 逐条列出"将要发生什么"（提交前是默认值清单、删除前是影响范围）。**不用浏览器原生 confirm**（Q21）；"能不能确认"由调用方判断（如后端预检返回 `can_delete=false`）。
- `ErrorState.tsx`：**T3.1 新增**。`ErrorState({scene, error, onRetry?})`——统一错误态（图标 + 主文案 + 原因 + 重试，`role="alert"`）；文案由 `lib/errors.toUserMessage(error, scene)` 生成。**接口失败的页面一律渲染它，不要再写演示数据兜底**（T3.2）。
- `InfoRow.tsx`：`InfoRow({label, value, accent})`——单行「标签/值」信息行（标注信息、详情页常用）。
- `PageIntro.tsx`：`PageIntro({eyebrow, title, description, action})`——页头区（眉题 + 标题 + 描述 + 右侧动作区），多数 feature 页复用。
- `StatusPill.tsx`：`StatusPill` + `StatusTone`（green/orange/red/blue/muted）——状态胶囊标签，`tone` 由调用方映射。
- `TextDialog.tsx`：`TextDialog({title, label, initialValue, choice?, onCancel, onConfirm})`——带输入框的轻量确认对话框（新建数据集等）。**2026-09**：新增可选 `choice`（`{label, initialValue?, options[]}`）→ 追加一个下拉字段，`onConfirm(value, choiceValue?)` 第二参回传选择值（新建数据集的「任务类型」用它消费系统设置字典 `dataset_task`；`options` 为空时调用方不传 `choice`）。
- `Toolbar.tsx`：`Toolbar({action, secondary, onAction, onRefresh, actionDisabled, exportType, exportRefIds, exportDisabled})`——页面顶部工具栏；**承担报告导出**：`exportType`/`exportRefIds` 传给 `api/reports.exportReport`，成功后 `window.open(url)`。**2026-09-14**：新增 `exportDisabled`（无报告可导时禁用，核验页 S12 用它）；导出失败文案改走 `toUserMessage(err, '导出报告')`。

## 调用链

- 被谁调用：`src/App.tsx` 及 `src/features/*`（Toolbar 被 App/Analysis/Alignment/Validation/Features/Models 复用；PageIntro/StatusPill/InfoRow/TextDialog 被多数 feature 页复用）。
- 调用谁：`../lib/formatting` 等纯工具；**不 import api/feature**。

## 关键规则/坑

- `Toolbar` 的导出逻辑必须显式传 `exportType` + `exportRefIds`（页级 ref id，如 version_id），缺 ref 时后端按 `type` 语义处理；改导出走 `/reports/export`，勿在组件内直连其他接口。
- 通用件样式类名集中在 `src/index.css`；新增组件时同步补样式并保持 `.ghost-button/.primary-button/.danger-button` 等既有按钮体系。
