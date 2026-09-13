# CLAUDE.md — src/features/registration/

数据管理·数据登记页。**新建操作，不要求先选数据**，点侧边栏「数据登记」直接进登记表单；`data-center/registration` 绝不加入 `routesRequiringData`。

## 文件

- `RegistrationPage.tsx`：`RegistrationPage()`——登记表单 + 4 区文件上传（时序 CSV/图片/视频/WAV，`UPLOAD_ZONES` 配置，各带 `accept` + `zoneAccepts` 类型校验、独立上传状态与 file input）。流程：`createRegistration`（部分失败重试复用 `regRef` 防重复登记）→ 逐文件**预签名直传**（`presignUpload` + `putFileDirect` XHR 带进度）→ `attachRawFiles` 统一挂载。**2026-09**：工艺参数区新增可空输入「送丝速度 / 焊接速度」（`wire_feed_speed`/`welding_speed`，登记即存；挂载标准多模态 CSV 后由导入按稳态中位数自动回填）。**2026-09 可选项字典化**：焊机型号/焊接方法改为读系统设置字典（`listOptionGroups()` 的 `machine`/`weld_method` 组，只取 `active` 项），数据来源/关联产品信息改为**输入框 + `<datalist>` 候选**（保留自由填写）。

## 调用链

- 被谁调用：`src/App.tsx`（`data-center/registration` 懒加载）。
- 调用谁：`src/api/welds`（createRegistration/attachRawFiles/listWelds）、`src/api/datasets`（listDatasets，默认取第一个）、`src/api/files`（presignUpload/putFileDirect/uploadFile）、`src/api/settings`（listOptionGroups，取 machine/weld_method/source/product 四组启用项）、`src/features/datasets/weldRows`（toWeldRow/mockWeldRows 兜底最近上传）。

## 关键规则/坑

- **延迟上传**：选择文件只锚定（`files` state 存 File，状态 `pending`「已选择（待上传）」，不发网络请求），点「登记数据」才提交。
- **必填项 UX**：4 个启用条件（dataset/source/weld_name/hasFile）由 `missingFields` 统一驱动，按钮不用原生 `disabled` 而是 `.full-button--disabled` + `aria-disabled`，点击列出缺失项并对输入区红色闪烁。
- **对象键前缀固定 `raw/`**，勿用 `uploads/`（有 30 天生命周期清理）。
- PUT 后先查 `res.ok`，失败抛错丢弃 object_key；回调读 `regIdRef`/`pendingKeysRef` 修 stale-closure 竞态；file input 重选需清空。
- 最近上传 ← `listWelds({tab:'recent'})`；采集时间用 `datetime-local`（默认当前本地时间）。
- **可选项字典（2026-09）**：`optionValues` 初值**为空数组**（字典到达前不闪现兜底品牌），`listOptionGroups()` 单独发请求（失败不影响数据集/最近登记加载），仅在 **catch 分支**回落到 `FALLBACK_OPTIONS`（= 字典化前的硬编码值，保证接口异常时登记流程可用）。焊机型号/焊接方法默认值改为**字典首个启用项**（原写死 `Fronius CMT`/`MAG焊`），只在用户未填时回填。`withCurrent()` 会把当前值补进候选——这样某型号被停用后，**编辑老数据仍能回显与提交**，不会因字典变更丢失既有值。
