# CLAUDE.md — src/shared/

跨 feature 复用的 UI 组件与工具函数层。**只放无业务耦合的通用件**，业务页面组件一律进 `src/features/*`。

## 目录

- `components/`：通用 UI 组件（页头、工具栏、状态标签、文本对话框、信息行），详见 `components/CLAUDE.md`。
- `lib/`：纯工具函数（时间格式化），详见 `lib/CLAUDE.md`。

## 调用链

- 被谁调用：`src/App.tsx` 与各 `src/features/*` 页面（`Toolbar` 被 App/Analysis/Alignment/Validation/Features/Models 复用；`PageIntro`/`StatusPill`/`InfoRow`/`TextDialog` 被多数 feature 页复用）。
- 调用谁：不依赖任何 feature 或 api 模块。

## 关键规则/坑

- 共享组件**不得 import 业务数据/接口**，只接收 props 渲染；否则会在多个页面间传递隐性耦合。
- 新增共享件时保持 TS 类型完整（props 显式定义），勿让 props 用 `any` 扩散。
