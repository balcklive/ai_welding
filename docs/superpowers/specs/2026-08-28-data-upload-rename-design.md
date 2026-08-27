# 数据上传（原数据登记）改名 + 分类型上传区 设计

日期：2026-08-28 · 状态：已与用户确认

## 背景

线上「数据登记」页面的「生成登记编号」按钮常被用户视为"无用 / 未接后端"。排查结论：该按钮是**提交按钮**（创建记录 + 生成编号），被表单必填校验禁用，后端 `POST /api/v1/registrations` 已实现且线上正常。真正问题是**文案与语义脱节**。

与用户确认的产品语义：

- 「数据登记」= 把单个数据上传进特定数据集 → 改名「**数据上传**」。
- 「生成登记编号」按钮改名「**上传数据**」，语义 = 将这份数据上传到所选数据集。
- 上传区从「一个混合区（视频/CSV/WAV/JSON/图片）」拆成 **4 个独立区块**：CSV（时序）/ 图片 / 视频 / WAV（音频）。
- 提交时要求**至少一个文件**。

## 范围

- **只改前端 UI 文案 + 文档 / CLAUDE.md**；后端零改动（`attach_raw_files` 已支持批量 object_keys 并按扩展名推导 modalities，含 `.csv` 自动触发 signal_ingest）。
- 代码标识符不动：`createRegistration`、`/registrations`、`registration_no`、`Registration` 组件名等保持。
- 「登记编号」（`registration_no`）作为记录身份字段保留，列表/详情列名不改。
- **JSON 上传移除**（原混合区才支持，不在四区之内）。
- 每区 v1 仅**单文件**（多文件后续扩展）。

## 改动清单

### 1. 文案改名（`src/App.tsx`）

| 位置 | 现在 | 改成 |
|---|---|---|
| 侧边栏子菜单 label（`App.tsx:116`） | 数据登记 | 数据上传 |
| 数据中心描述（`App.tsx:107`） | 管理登记信息、质量核验和版本链路。 | 管理数据上传、质量核验和版本链路。 |
| 页标题 PageIntro | title=数据登记 | title=数据上传（eyebrow「标准化台账」、description 不变） |
| 流程 chip | 登记即进入数据流程 | 上传数据即进入数据流程 |
| 表单 h2 | 新建数据登记 | 上传数据（p「带 * 的字段为必填项」不变） |
| 草稿标签 | 登记草稿 | 上传草稿 |
| 提交按钮 | 生成登记编号 | 上传数据 |
| 按钮成功态 | 登记已生成：{regNo} | 上传成功：{regNo} |
| 右侧面板标题 | 登记规则 | 上传规则 |
| 规则条目 | 自动生成唯一登记编号 / 原始文件与后续版本自动关联 / 登记后触发入库前数据核验 / 所有操作写入审计日志 | 自动生成唯一编号 / 原始文件与后续版本自动关联 / 上传后触发入库前数据核验 / 所有操作写入审计日志 |
| 右侧面板 | 最近登记 | 最近上传 |
| 最近行状态 | 已登记 | 已上传 |
| 错误提示 | 登记创建失败，请检查必填项后重试 | 上传失败，请检查必填项后重试 |
| 错误提示 | 文件已上传但关联登记失败，请重新选择文件 | 文件已上传但关联失败，请重新选择文件 |
| 分析选择页空态（`App.tsx:1018`） | 该数据集暂无登记数据，请先在数据中心登记或核验。 | 该数据集暂无数据，请先在数据中心上传数据。 |

### 2. 上传区 → 4 个独立区块（`Registration` 组件内）

配置化 4 个 zone，各自独立 fileRef / 上传状态 / accept / 类型校验：

| 区块 key | 标签 | accept | 说明 |
|---|---|---|---|
| `csv` | 时序数据（CSV） | `.csv` | 拒绝非 .csv |
| `image` | 图片 | `image/png,image/jpeg,image/webp,image/bmp` | 拒绝非图片 |
| `video` | 视频 | `video/*` | 拒绝非视频 |
| `audio` | 音频（WAV） | `.wav,audio/wav` | 拒绝非 .wav |

- 每个区独立「选择文件」按钮 + 上传状态（上传中 / 成功 / 失败 + 文件名）。
- 选错格式**拦截并提示**，不只靠 accept 软过滤（用扩展名/`file.type` 校验）。
- 上传大小逻辑不变：`<100MB` 走 `uploadFile`，`≥100MB` 走 `presignUpload` + PUT，PUT 后先查 `res.ok`，失败抛错丢弃 object_key。
- 各 zone 的 object_key 累积到 **`pendingKeysRef`（数组）**，提交后一次性 `attachRawFiles(id, keys)`。
- 竞态沿用现有 exactly-once 约定（`regIdRef` + pendingKeysRef）：上传完成时若 `regIdRef.current` 已存在则立即 attach 并从数组移除；否则入数组，由提交成功后的 drain 统一补挂。每个文件键恰好补挂一次。

### 3. 提交校验（至少一个文件）

- 按钮 `disabled = 缺 dataset_id || 缺 source || 缺 weld_name || 无任何已上传文件`。
- 「是否有文件」必须是 **state**（不能只靠 ref），否则按钮不会随上传完成 re-render。用一个 `hasFile` state（或从 `uploads` state 派生）在首个文件上传成功后置真。
- `handleSubmit` 先校验「至少一个文件」，否则直接 return（按钮已禁用，兜底）。

### 4. 测试与门禁

- 更新 `src/App.analysis-select-regression.test.mjs:24` 断言文案为新的空态文案。
- `npm run lint && npm run typecheck && npm run build`（pre-push 门禁一致）。

## 非目标

- 不改后端接口 / 表 / 路由；不改代码标识符；不重构 App.tsx 结构。
- 不加多文件上传；不加 WAV 以外的音频格式；不加 JSON 区。
- 不改「先选数据集」入口模型（表单顶部所属数据集下拉保持）。

## 涉及文件

- `src/App.tsx`：`Registration` 组件（上传区重构 + 文案）、侧边栏 label、data-center 描述、`AnalysisSelect` 空态。
- `src/App.analysis-select-regression.test.mjs`：空态断言同步。
- 文档同步（命名对齐）：`README.md`「数据登记规则」小节、`src/CLAUDE.md`、根 `CLAUDE.md` 中"登记（上传新数据）"表述。
