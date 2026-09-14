# CLAUDE.md — src/features/registration/

数据管理·数据登记页。**新建操作，不要求先选数据**，点侧边栏「数据登记」直接进登记表单；`data-center/registration` 绝不加入 `routesRequiringData`。

## 文件

- `RegistrationPage.tsx`：`RegistrationPage()`——登记表单 + 4 区文件上传（时序 CSV/图片/视频/WAV，`UPLOAD_ZONES` 配置，各带 `accept` + `zoneAccepts` 类型校验、独立上传状态与 file input）。流程：`createRegistration`（部分失败重试复用 `regRef` 防重复登记）→ 逐文件**预签名直传**（`presignUpload` + `putFileDirect` XHR 带进度）→ `attachRawFiles` 统一挂载。**2026-09**：工艺参数区新增可空输入「送丝速度 / 焊接速度」（`wire_feed_speed`/`welding_speed`，登记即存；挂载标准多模态 CSV 后由导入按稳态中位数自动回填）。**2026-09 可选项字典化**：焊机型号/焊接方法改为读系统设置字典（`listOptionGroups()` 的 `machine`/`weld_method` 组，只取 `active` 项），数据来源/关联产品信息改为**输入框 + `<datalist>` 候选**（保留自由填写）。

## 调用链

- 被谁调用：`src/App.tsx`（`data-center/registration` 懒加载）。
- 调用谁：`src/api/welds`（createRegistration/attachRawFiles/listWelds）、`src/api/datasets`（listDatasets，默认取第一个）、`src/api/files`（presignUpload/putFileDirect/uploadFile）、`src/api/settings`（listOptionGroups，取 machine/weld_method/source/product 四组启用项）、`src/features/datasets/weldRows`（toWeldRow）、`src/app/navigation`（`Route`，三个出口跳转用）。

## 关键规则/坑

- **T4a（2026-09-14）登记改造**：① **所属数据集继承并锁定**——`App.tsx` 传 `lockedDatasetId`（当前 `selectedDatasetId`）；带上下文进入直接进表单并显示只读的「所属数据集」，未带上下文则先渲染 `.registration-step`（选数据集 → `confirmDataset` → 锁定）；必填校验看 `lockedDatasetId`（不是 `form.dataset_id`）。② **默认值链（T4.2.1）**：上下文（数据集/采集时间）→ 本次上传的 CSV 推导采样率（`sampleRateFromCsv`，只处理数值时间列，解析不出就留空）→ 该用户上次成功登记的值（localStorage `ai-welding:last-registration:<userId>`，`DEFAULTABLE_FIELDS` 白名单）→ 字典首项；只在字段为空时回填，填过的字段带 `<em className="default-mark">默认</em>`，并有「清除默认值（N 项）」一键清空。③ **提交前汇总确认**：只要还有"仍是默认值"的字段，点「登记数据」先弹 `ConfirmDialog` 列出这些字段与值，确认后才提交（默认值会让必填校验永不触发，这一步才是真正防填错的地方）。④ **三个出口（T4.3）**：结果卡 `.registration-result` 给「查看这条数据 / 继续登记下一条 / 去数据核验」；后两个分别带上下文跳转与重置表单（保留数据集与上次工艺参数作为默认）。⑤ 写操作失败**保留用户输入**（T3.2 的读写分开规则）。
- 单元/契约回归：`src/App.analysis-select-regression.test.mjs` 钉住"继承并锁定 + missingFields 看 lockedDatasetId"；界面契约 E2E `tools/data-center-ui-e2e.mjs` 覆盖两步流程、默认标记、CSV 推采样率、确认弹窗、三个出口、继续登记。

- **延迟上传**：选择文件只锚定（`files` state 存 File，状态 `pending`「已选择（待上传）」，不发网络请求），点「登记数据」才提交。
- **必填项 UX**：5 个启用条件（dataset（T4a 起看 `lockedDatasetId`）/source/collected_at/weld_name/hasFile）由 `missingFields` 统一驱动，按钮不用原生 `disabled` 而是 `.full-button--disabled` + `aria-disabled`，点击列出缺失项并对输入区红色闪烁。
- **对象键前缀固定 `raw/`**，勿用 `uploads/`（有 30 天生命周期清理）。
- PUT 后先查 `res.ok`，失败抛错丢弃 object_key；回调读 `regIdRef`/`pendingKeysRef` 修 stale-closure 竞态；file input 重选需清空。
- 最近上传 ← `listWelds({tab:'recent'})`；采集时间用 `datetime-local`（默认当前本地时间）。
- **可选项字典（2026-09）**：`optionValues` 初值**为空数组**（字典到达前不闪现兜底品牌），`listOptionGroups()` 单独发请求（失败不影响数据集/最近登记加载）。**T3.2/T3.3（2026-09-14）**：`FALLBACK_OPTIONS` 已删除——字典失败置 `optionsError`（页面内 `ErrorState` + 重试），且**字典不全时禁止提交**（按钮禁用 + 点击提示）。焊机型号/焊接方法默认值改为**字典首个启用项**（原写死 `Fronius CMT`/`MAG焊`），只在用户未填时回填。`withCurrent()` 会把当前值补进候选——这样某型号被停用后，**编辑老数据仍能回显与提交**，不会因字典变更丢失既有值。
- **三块数据各自独立失败态（T3.2）**：数据集下拉（`datasetsError`）、最近登记（`recentError`）、可选项字典（`optionsError`）分别请求、分别报错；`retry()` 递增 `reloadKey` 重跑全部。最近登记徽标显示真实 `quality`（原固定显示"已登记"，S10）。
