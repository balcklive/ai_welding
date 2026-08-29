# CLAUDE.md — src/shared/lib/

跨 feature 复用的纯工具函数。

## 文件

- `formatting.ts`：`formatDateTime(iso)`——ISO 时间串 → 本地可读格式（`YYYY-MM-DD HH:mm` 风格）；`null`/`undefined`/非法输入安全返回占位。版本列表、核验时间等展示统一走它。

## 调用链

- 被谁调用：`src/shared/components`、各 `src/features/*`（版本链、数据集快照时间等）。
- 调用谁：无依赖。

## 关键规则/坑

- 保持纯函数、无状态；新增格式化工具（数值/时长/百分比等）归本目录，勿散落到各 feature。
