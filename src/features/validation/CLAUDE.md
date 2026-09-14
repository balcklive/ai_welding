# CLAUDE.md — src/features/validation/

数据管理·数据核验页（15 项确定性规则）。

## 文件

- `ValidationPage.tsx`：`ValidationPage({dataId})`——挂载时 `getWeld` 取 `latest_version_id` → `getValidation` 拉核验报告；「执行核验」→ `runValidation`（同步，返回评分 + 规则结果）。

## 调用链

- 被谁调用：`src/App.tsx`（`data-center/validation`，需 `selectedDataId` 否则 `SelectionRequired`）。
- 调用谁：`src/api/welds`（getWeld/getValidation/runValidation）、`src/shared/components`（Toolbar/PageIntro/StatusPill）。

## 关键规则/坑

- **三种状态分离（T3.2，2026-09-14）**：`fallback()` 演示报告与 `mockValidationRuleNames` **已删除**。现在——**空态**（无数据版本 / 该版本尚未核验，走 404 判定 `isNotFound`：给引导文案，不是错误）、**错误态**（`ErrorState` + 重试）、**有结果**（正常渲染）。加载期评分 `—`、状态"加载中"、规则区"核验规则加载中…"。
- **S12**：`Toolbar` 新增 `exportDisabled`，核验页在 `!report` 时禁用「下载核验报告」（原可点，会导出演示报告）。
- **规则映射**：由 `ValidationRuleResult.status`（passed/warning/failed）映射图标/文案/状态色（失败红、警告橙、通过绿）；汇总状态 `failed>0→异常 / 仅警告→待复核 / 否则→核验通过`。
- 15 条规则名与后端 seed/`welds.VALIDATION_RULES` 逐字一致，勿改。
