# CLAUDE.md — src/features/validation/

数据中心·数据核验页（15 项确定性规则）。

## 文件

- `ValidationPage.tsx`：`ValidationPage({dataId})`——挂载时 `getWeld` 取 `latest_version_id` → `getValidation` 拉核验报告；「执行核验」→ `runValidation`（同步，返回评分 + 规则结果）。

## 调用链

- 被谁调用：`src/App.tsx`（`data-center/validation`，需 `selectedDataId` 否则 `SelectionRequired`）。
- 调用谁：`src/api/welds`（getWeld/getValidation/runValidation）、`src/shared/components`（Toolbar/PageIntro/StatusPill）。

## 关键规则/坑

- **mock 兜底边界**：mock 报告仅接口失败/无版本可查时经 `fallback()` 兜底并显示提示横幅；加载期评分 `—`、状态"加载中"、规则区"核验规则加载中…"。规则名单提为模块级 `mockValidationRuleNames`。
- **规则映射**：由 `ValidationRuleResult.status`（passed/warning/failed）映射图标/文案/状态色（失败红、警告橙、通过绿）；汇总状态 `failed>0→异常 / 仅警告→待复核 / 否则→核验通过`。
- 15 条规则名与后端 seed/`welds.VALIDATION_RULES` 逐字一致，勿改。
