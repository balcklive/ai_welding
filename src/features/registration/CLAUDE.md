# CLAUDE.md — src/features/registration/

数据管理·数据登记页。**新建操作，不要求先选数据**，点侧边栏「数据登记」直接进登记表单；`data-center/registration` 绝不加入 `routesRequiringData`。

## 文件

- `RegistrationPage.tsx`：`RegistrationPage()`——登记表单 + 4 区文件上传（时序 CSV/图片/视频/WAV，`UPLOAD_ZONES` 配置，各带 `accept` + `zoneAccepts` 类型校验、独立上传状态与 file input）。流程：`createRegistration`（部分失败重试复用 `regRef` 防重复登记）→ 逐文件**预签名直传**（`presignUpload` + `putFileDirect` XHR 带进度）→ `attachRawFiles` 统一挂载。**2026-09**：工艺参数区新增可空输入「送丝速度 / 焊接速度」（`wire_feed_speed`/`welding_speed`，登记即存；挂载标准多模态 CSV 后由导入按稳态中位数自动回填）。**2026-09 可选项字典化**：焊机型号/焊接方法改为读系统设置字典（`listOptionGroups()` 的 `machine`/`weld_method` 组，只取 `active` 项），数据来源/关联产品信息改为**输入框 + `<datalist>` 候选**（保留自由填写）。

## 调用链

- 被谁调用：`src/App.tsx`（`data-center/registration` 懒加载）。
- 调用谁：`src/api/welds`（createRegistration/attachRawFiles/listWelds/reimportSignals）、`src/hooks/useIngestStatus`（登记链路状态）、`src/api/datasets`（listDatasets，默认取第一个）、`src/api/files`（presignUpload/putFileDirect/uploadFile）、`src/api/settings`（listOptionGroups，取 machine/weld_method/source/product 四组启用项）、`src/features/datasets/weldRows`（toWeldRow）、`src/app/navigation`（`Route`，三个出口跳转用）。

## 关键规则/坑

- **T4a（2026-09-14）登记改造**：① **所属数据集继承并锁定**——`App.tsx` 传 `lockedDatasetId`（当前 `selectedDatasetId`）；带上下文进入直接进表单并显示只读的「所属数据集」，未带上下文则先渲染 `.registration-step`（选数据集 → `confirmDataset` → 锁定）；必填校验看 `lockedDatasetId`（不是 `form.dataset_id`）。② **默认值链（T4.2.1）**：上下文（数据集/采集时间）→ 本次上传的 CSV 推导采样率（`sampleRateFromCsv`，只处理数值时间列，解析不出就留空）→ 该用户上次成功登记的值（localStorage `ai-welding:last-registration:<userId>`，`DEFAULTABLE_FIELDS` 白名单）→ 字典首项；只在字段为空时回填，填过的字段带 `<em className="default-mark">默认</em>`，并有「清除默认值（N 项）」一键清空。③ **提交前汇总确认**：只要还有"仍是默认值"的字段，点「登记数据」先弹 `ConfirmDialog` 列出这些字段与值，确认后才提交（默认值会让必填校验永不触发，这一步才是真正防填错的地方）。④ **三个出口（T4.3）**：结果卡 `.registration-result` 给「查看这条数据 / 继续登记下一条 / 去数据核验」；后两个分别带上下文跳转与重置表单（保留数据集与上次工艺参数作为默认）。⑤ **登记完成后显示数据集版本构建状态**（T8）：挂载响应带出 `dataset_build.job_id`，结果卡用 `useJob` 轮询显示「构建中 / 已完成 / 构建失败（可在数据集页面重新构建）」；刷新后由数据集页面的 `build_status` 恢复（上下文不入 URL，登记页本身不持久化）。⑥ 写操作失败**保留用户输入**（T3.2 的读写分开规则）。
- **T4b（2026-09-14，R1/R6）**：① 「电流 / 电压」从一格拆成**两个输入框**（`input placeholder="例如：180"` 与 `"例如：22"`，各带"默认"标记与单位后缀）；② `DefaultableField` 改为 `DEFAULTABLE_FIELDS` 元组推导出的字符串字段联合类型，`loadLastValues` 按白名单过滤（老版本可能存过 `current_voltage`）；③ 提交载荷里 `current_a`/`voltage_v` 转数字、厚度剥 `mm`——**表单字符串 → 请求数字的边界只在这一处**；④ 必填/量程与后端同一套（电流 1–2000、电压 1–200、厚度 0.1–200、送丝 0–50、焊接 0–5000）。
- **T4.4（2026-09-14，R2）**：① `uploadedKeys` 记住**已直传成功**的对象键（按上传区）——重试只补失败的那个文件，**换文件时清掉该区的键**（否则会把上一个文件挂到这次登记上）；② 提交期间用 `<fieldset className="form-fieldset" disabled>`（CSS `display:contents`，不打断栅格）禁用整个表单，避免"提交中改了表单、重试却复用了已建登记"；③ 失败时在表单外给 `.registration-error`：说明「当前登记 REG-… 已创建」+「重试提交 / 放弃本次登记」两个出口；④ `attachRawFiles` 撞上 `CSV_INGEST_CONFLICT_CODE`（40901）时**按已挂载成功继续**（下一次挂载重试必然撞它）；⑤ 结果卡用 `useIngestStatus` 显示信号导入四态，失败时列出文件与原因并给「重新导入」（`reimportSignals`）；⑥ 错误文案统一走 `toUserMessage(err, '登记数据')`（T3.1）。
- 单元/契约回归：`src/App.analysis-select-regression.test.mjs` 钉住"继承并锁定 + missingFields 看 lockedDatasetId"；界面契约 E2E `tools/data-center-ui-e2e.mjs` 覆盖两步流程、默认标记、CSV 推采样率、确认弹窗、三个出口、继续登记、**两个电流/电压输入框与提交载荷字段**、**导入状态与重新导入**；后端 `backend/tests/test_registration_t4b.py` 覆盖校验/兼容/迁移对拍。

- **延迟上传**：选择文件只锚定（`files` state 存 File，状态 `pending`「已选择（待上传）」，不发网络请求），点「登记数据」才提交。
- **必填项 UX**：5 个启用条件（dataset（T4a 起看 `lockedDatasetId`）/source/collected_at/weld_name/hasFile）由 `missingFields` 统一驱动，按钮不用原生 `disabled` 而是 `.full-button--disabled` + `aria-disabled`，点击列出缺失项并对输入区红色闪烁。
- **对象键前缀固定 `raw/`**，勿用 `uploads/`（有 30 天生命周期清理）。
- PUT 后先查 `res.ok`，失败抛错丢弃 object_key；回调读 `regIdRef`/`pendingKeysRef` 修 stale-closure 竞态；file input 重选需清空。
- 最近上传 ← `listWelds({tab:'recent'})`；采集时间用 `datetime-local`（默认当前本地时间）。
- **可选项字典（2026-09）**：`optionValues` 初值**为空数组**（字典到达前不闪现兜底品牌），`listOptionGroups()` 单独发请求（失败不影响数据集/最近登记加载）。**T3.2/T3.3（2026-09-14）**：`FALLBACK_OPTIONS` 已删除——字典失败置 `optionsError`（页面内 `ErrorState` + 重试），且**字典不全时禁止提交**（按钮禁用 + 点击提示）。焊机型号/焊接方法默认值改为**字典首个启用项**（原写死 `Fronius CMT`/`MAG焊`），只在用户未填时回填。`withCurrent()` 会把当前值补进候选——这样某型号被停用后，**编辑老数据仍能回显与提交**，不会因字典变更丢失既有值。
- **S2（2026-09-15）：录入控件统一为「下拉候选 + 可自定义输入」**：焊机型号 / 焊接方法从**严格 `<select>`** 改为 **`<input list>` + `<datalist>`**（与数据来源 / 关联产品信息同一形态，4 个 datalist 的 `id` 常量：`MACHINE_LIST_ID`/`WELD_METHOD_LIST_ID`/`SOURCE_LIST_ID`/`PRODUCT_LIST_ID`）。字典仍是**候选来源**（`listOptionGroups()` 只取 `active` 项，`withCurrent()` 保证停用/历史值仍可回显），但**不再是强约束**——现场清单里没有的型号/方法可以直接填，`isCustomValue()` 判定后给 `.custom-value-hint`「新值」提示并引导到「系统设置」补候选。**为什么**：预置项不足时严格下拉只有两种结局——填不进去（阻塞作业）或随手挑一个（污染台账）。**边界**：① 新值**原样入库**（后端 `machine`/`weld_method` 本就是 1–64/1–32 的普通字符串，不校验候选）；② 后端 `OPTION_GROUPS` 的 `free_text` 已同步为 `true`（契约 §3.8），设置页据此说明"可手工填写"；③ 总览的「厂商比重/词云」按 `machine` 首个词统计、`weld_method` 只映射已知方法（其它计入「未分类」，见 `backend/app/services/dashboard.py`），所以自由输入会带来**同义异写**风险——这是提示文案要求"补进候选"的原因，不是可选项。④ 必填语义不变：两者仍在 `missingFields` 里（现补了 `*` 星标与点击闪烁）。**未做**（另议）：板材材质/厚度没有字典组（材质为纯文本、厚度为数值），批次目前不是独立字段（混在「样本名称（焊缝 / 批次）」里，要做下拉需加列 + 迁移）。
- **2026-09-15（小改）**：板材厚度 / 电流 / 电压 / 采样频率的必填星号原先是 `<label>` 的**独立栅格子项**（`display:grid` 下会折到下一行）；改为与数据来源一致的 `<span>字段名<span className="required-mark"> *</span>…</span>` 写法，星号与「默认」标记回到标题行内。
- **三块数据各自独立失败态（T3.2）**：数据集下拉（`datasetsError`）、最近登记（`recentError`）、可选项字典（`optionsError`）分别请求、分别报错；`retry()` 递增 `reloadKey` 重跑全部。最近登记徽标显示真实 `quality`（原固定显示"已登记"，S10）。
