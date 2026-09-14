# CLAUDE.md — src/shared/lib/

跨 feature 复用的纯工具函数。

## 文件

- `errors.ts`：**T3.1 新增**。`toUserMessage(err, scene) → {message, reason?}`——把异常翻译成用户可读文案：网络失败 / 404 / 403 / 409（保留后端业务文案）/ 5xx / 422（`detail.errors()` 的字段路径 → 中文名，见 `FIELD_LABELS`）/ 兜底"请重试"。**鸭子类型识别 `ApiError`（只认 `code`/`status`），刻意不 import `api/client`**：本目录是纯工具层，且零依赖才能被 `node --test` 直接跑（`src/errors.test.mjs`）。字段级原因依赖 `client.ts` 保留信封 `detail`。
- `terms.ts`：**T1 新增**。界面正式名的单一来源（`TERMS`：数据集/数据集版本/样本/切片/数据版本/当前数据版本/有效切片占比），另有 `READY_TEXT` 与 `DIMENSION_LABELS`/`dimensionLabel()`（后端英文维度标识 → 中文，S6）。**页面不要再写这些中文字面量**；明确禁止再出现：快照、固定快照、焊缝版本、可训练、未核验、数据质量。术语基线见 `docs/数据管理改造技术实施方案.md` §2.1。
- `formatting.ts`：`formatDateTime(iso)`——ISO 时间串 → 本地可读格式（`YYYY-MM-DD HH:mm` 风格）；`null`/`undefined`/非法输入安全返回占位。版本列表、核验时间等展示统一走它。

## 调用链

- 被谁调用：`src/shared/components`、各 `src/features/*`（版本链、数据集版本时间等）。
- 调用谁：无依赖。

## 关键规则/坑

- 保持纯函数、无状态；新增格式化工具（数值/时长/百分比等）归本目录，勿散落到各 feature。
