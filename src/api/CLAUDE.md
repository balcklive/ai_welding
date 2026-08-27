# CLAUDE.md — src/api/

前端接口层（契约：`docs/API接口清单.md`）。当前进度：Task 18（`client.ts` + `types.ts`）+ **Task 19（9 个域模块全部完成：`auth`/`dashboard`/`welds`/`analysis`/`datasets`/`models`/`files`/`jobs`/`reports`）**。签名一律逐字对齐契约 §4.2（个别按后端实际返回体微调，见各模块注释）。

## 脚本

- `client.ts`：统一请求封装（**原生 fetch，不引 axios**）。
  - `BASE = '/api/v1'`、token 存 `localStorage`（key=`token`）。
  - `getToken() / setToken(token) / clearToken()`：token 读写。
  - `class ApiError extends Error`：`(code, message, status)`——`code` 为信封业务码，`status` 为 HTTP 状态码。
  - `buildQuery(params: object)`：查询参数 → 查询串（含 `?`）；数组展开为重复键（`channels=a&channels=b`），`undefined/null/''` 跳过。**参数用 `object` 而非 `Record<string, unknown>`**——接口无隐式索引签名，赋给 `Record<...>` 会 TS 报错，此处仅读 entries 无需索引签名。
  - `RequestOptions`：`{ method?, body?, query?, headers?, skipAuth? }`。
    - `query` 同为 `object`（兼容接口/类型别名）。
    - **`skipAuth?: boolean`（Task 19 新增）**：为 `true` 时跳过「HTTP 401 → 清 token + 重载」流程（仅 `auth.login` 用——密码错是业务失败，不应清会话/刷页面）；401 仍照常抛 ApiError。
    - **`body` 支持 FormData（Task 19 新增）**：`body instanceof FormData` 时直接透传且**不设 `Content-Type`**（浏览器自动带 boundary），供 `files.uploadFile` 走统一信封/401 处理，避免重复手写 fetch。
  - `request<T>(path, options?)`：拼 URL → 注入 `Authorization: Bearer <token>`（有 token 时）→ body JSON 化（非 FormData 时设 `Content-Type: application/json`）→ 解析信封 → **HTTP 401 → 清 token + 重载**（`skipAuth` 时跳过）→ `code !== 0` 抛 `ApiError` → 返回 `data`。网络失败/非 JSON 响应兜底为 `ApiError(-1, ..., 0)`。
- `types.ts`：全部实体/请求体类型，字段名/形状**逐字对齐后端 `*_payload` 序列化**与 `docs/API接口清单.md` §2、§1.4、§1.5。后端为契约：`Page<T>={items,total,page,page_size}`、`Job<T>={id,type,status,progress,result,error,created_at,finished_at}`、`Registration` = `DataRecord` 别名（`/registrations` 返回同构 record_payload）。Task 19 未新增类型（全部签名所需类型已在 `types.ts` 就绪）。
- 域模块（均相对 `/api/v1`，每个函数一行式 `request(...)` 转发）：
  - `auth.ts`：`login`（POST `/auth/login`，**`skipAuth: true`**，token 落库由调用方 `setToken` 负责）/ `getMe`（GET `/auth/me`）。
  - `dashboard.ts`：`getStats/getAttributes/getDistributions/getProjects`（GET `/dashboard/*`），以及 `getDashboardData` 的 5 分钟 localStorage 聚合缓存。后续迁移 Redis 时替换缓存实现，保持 `DashboardData` 契约不变。
  - `welds.ts`：列表 `listWelds(params)`（GET `/welds`，query 直接透传筛选/分页）；详情 `getWeld`；登记 `createRegistration/updateRegistration/getRegistration`（POST/PATCH/GET `/registrations(/{id})`）；`attachRawFiles(id, objectKeys, storageBytes?)`（POST `/registrations/{id}/raw-files`，`storage_bytes` 可选，缺省 0，省略则不传）；版本 `listVersions/createVersion/getVersion`；核验 `runValidation`（POST）/ `getValidation`（GET）`…/validation`。
  - `analysis.ts`：候选 `listCandidates`；对齐 `createAlignmentTask`（POST → `{job_id}`）+ `getAlignmentTask`（GET 轮询）；信号 `getSignals`（GET `…/signals`，**前端对 `channels[].values` 均匀抽稀到 ≤512 点**，`decimate` 本地工具，长度 ≤512 含 0/1 原样返回）；六 mode `getAnalysisMode(mode, channel, filter?)`（`filter` 映射为 query `filter_type/cutoff/cutoff2`，buildQuery 自动跳过缺省）；结果 `getAnalysisResult`（注意 `…/analysis/result` 为具体路径，先于 `{mode}` 注册是后端职责）；切分 `createSplitTask/getSplitTask`；标注 `listLabelCategories/createAnnotationTask/importAnnotationSamples/listAnnotationSamples(page)/getAnnotationSample/aiPretag/saveAnnotation`（`createAnnotationTask` 的 source 支持 `signal`（需带 `version_id`），`saveAnnotation` 的 labels 传 `LabelItem[]`（可含 `kind`/`points`/`start_time`/`end_time`），body 为 `{labels}` 覆盖写）；特征 `extractFeatures/getFeatureExtraction`。
  - `datasets.ts`：`listDatasets/createDataset/getDataset/getDimensions/getReadiness/listDatasetVersions/createDatasetVersion/getDatasetVersion/getLineage/createBuildTask`（构建异步 → `{job_id}`，body `{source}`）。
  - `models.ts`：`listModels`（返回 `{summary, models}`）/ `getModel` / `createModel` / `updateModelVersionStatus`（PATCH `…/versions/{vid}`）/ 训练 `createTrainingTask/getTrainingTask/getTrainingLogs`（`getTrainingLogs` 返回**纯文本字符串**，信封 data 即 str）/ 测试 `createTestTask/getTestTask` / 推理 `createInferenceTask/getInferenceTask`。
  - `files.ts`：`uploadFile(file, onProgress?)`（multipart `file` 字段，FormData 作 body 走 client 透传；fetch 无原生上传进度，完成后回调 100）/ `presignUpload({size, content_type, prefix})`（→ `{object_key, upload_url}`）/ `getFileUrl(objectKey, expires?)`（GET `/files/{key}/url`，key 含 `/` 走 `:path` 捕获，**不** encodeURIComponent 整串）。
  - `jobs.ts`：`getJob(jobId)`（GET `/jobs/{job_id}`，通用轮询）。
  - `reports.ts`：`exportReport(body)`（POST `/reports/export`，返回 `{urls:[{ref_id, url}]}`——契约 §4.2 写的 `{url}` 与后端实际 `{urls:[...]}` 不符，以后端/本实现为准）。

## 坑/限制

- **401 处理是硬约定**：除 `auth.login`（`skipAuth: true`）外，任何业务接口返回 HTTP 401（含 `getMe` 会话失效）都会清 token + 重载页面。改它需先确认。
- **查询数组用重复键，不带 `[]` 后缀**：后端 `request.query_params.getlist("channels")` 兼容 `channels=a&channels=b`（也兼容 `channels[]=`），`buildQuery` 已按重复键展开。
- **`unified_vector` 分组**（`types.ts::UnifiedVectorGroup`）：`{name, dims, range:[start,end)}`，42 维分组顺序见 `backend/app/services/features.py` 常量，勿乱改。
- **`Model` 的 `version/metric/status/file_key/latest_version_id` 为可选**：模型无版本时后端不输出这些键（`model_payload` 只在有 `latest` 时并入）。
- **信封错误码约定**：0=成功；4xxxx=客户端错误（40100 未登录、40400 资源不存在、40900 冲突、42200 参数校验）；5xxxx=服务端错误。见 `docs/API接口清单.md` §1.3。
- **`exportReport`/`saveAnnotation` 签名与 §4.2 文本有出入**：§4.2 写 `exportReport → Promise<{url: string}>`、`saveAnnotation(labels: Annotation[])`、`attachRawFiles` 无 storage_bytes——分别按后端实际响应体/请求体修正为 `{urls:[...]}`、`LabelItem[]`、可选 `storageBytes`。改前端时以本目录实现 + 后端 services 为准。
- 新增端点时：请求/响应形状先对齐后端（`backend/app/services` 或 `api/v1/*.py`），再补 `types.ts`；改 `client.ts` 时保持 401/信封解包语义不变。
