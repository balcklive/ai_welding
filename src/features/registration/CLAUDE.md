# CLAUDE.md — src/features/registration/

数据中心·数据上传页（原「数据登记」）。**新建操作，不要求先选数据**，点侧边栏「数据上传」直接进上传表单；`data-center/registration` 绝不加入 `routesRequiringData`。

## 文件

- `RegistrationPage.tsx`：`RegistrationPage()`——登记表单 + 4 区文件上传（时序 CSV/图片/视频/WAV，`UPLOAD_ZONES` 配置，各带 `accept` + `zoneAccepts` 类型校验、独立上传状态与 file input）。流程：`createRegistration`（部分失败重试复用 `regRef` 防重复登记）→ 逐文件**预签名直传**（`presignUpload` + `putFileDirect` XHR 带进度）→ `attachRawFiles` 统一挂载。

## 调用链

- 被谁调用：`src/App.tsx`（`data-center/registration` 懒加载）。
- 调用谁：`src/api/welds`（createRegistration/attachRawFiles/listWelds）、`src/api/datasets`（listDatasets，默认取第一个）、`src/api/files`（presignUpload/putFileDirect/uploadFile）、`src/features/datasets/weldRows`（toWeldRow/mockWeldRows 兜底最近上传）。

## 关键规则/坑

- **延迟上传**：选择文件只锚定（`files` state 存 File，状态 `pending`「已选择（待上传）」，不发网络请求），点「上传数据」才提交。
- **必填项 UX**：4 个启用条件（dataset/source/weld_name/hasFile）由 `missingFields` 统一驱动，按钮不用原生 `disabled` 而是 `.full-button--disabled` + `aria-disabled`，点击列出缺失项并对输入区红色闪烁。
- **对象键前缀固定 `raw/`**，勿用 `uploads/`（有 30 天生命周期清理）。
- PUT 后先查 `res.ok`，失败抛错丢弃 object_key；回调读 `regIdRef`/`pendingKeysRef` 修 stale-closure 竞态；file input 重选需清空。
- 最近上传 ← `listWelds({tab:'recent'})`；采集时间用 `datetime-local`（默认当前本地时间）。
