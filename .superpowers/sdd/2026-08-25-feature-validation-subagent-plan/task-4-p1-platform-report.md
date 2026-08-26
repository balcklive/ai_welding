# Task 4 P1 平台验证报告

- 时间：2026-08-25 18:55–19:05 本地（UTC+8）
- 执行方式：**当前 HEAD 运行中的 backend/frontend + 试验 MySQL + 试验 MinIO + `backend/logs/api.log`**
- 基准前缀：`task4-20260825105526`
- 浏览器状态：**BLOCKED**，`browser` 工具返回 `BetterChromium is required but not installed`；因此所有页面观测项仅能标 `API-only/BLOCKED`，**未把任何页面结果记为 PASS**。
- 本轮未修改代码/测试/配置，未在报告中写入明文密码/token。

## 关键测试实体

- 主登记：`registration_id=24` / `weld_id=WLD-20260825-0018` / `registration_no=REG-20260825-00018`
- 主原始版本：`version_id=54 (v1.0)`
- 人工修正版：`version_id=56 (v1.1)`
- 核验报告：`report_id=9`
- 特征提取：`feature_id=18`
- 标注任务：`annotation_task_id=9`（job=`job_5c64f788`）
- 测试任务：`test_task_id=14`（job=`job_5b752df6`）
- 上传对象：`uploads/ba2a4029e6c64d09ac460f8510dde75a/file.png`
- 原始 CSV：`raw/REG-20260825-00018/signals.csv`
- 关键信号产物：`processed/WLD-20260825-0018/signals/19.parquet`
- 对齐产物：`processed/WLD-20260825-0018/align/current.csv`、`.../voltage.csv`、`.../tracks.json`

## 汇总

- **STATUS：FAIL**
- **PASS：17**
- **FAIL：12**
- **BLOCKED：12**

## 逐项结果

> 列说明：`状态` 仅用 `PASS / FAIL / BLOCKED / API-only-BLOCKED`；页面项在浏览器不可用时不记 PASS。

| 编号 | 预期 | 实际 | 状态 | 脱敏请求/响应 | 报告 URL / object key | 日志 / DB / MinIO 证据 | 复现步骤 |
|---|---|---|---|---|---|---|---|
| REPORT-001 | 可导出数据列表报告 | `POST /reports/export {type:'data-list', ref_ids:['WLD-20260825-0018'], format:'json/pdf'}` 均 `200`；JSON `total=1`，PDF 可下载 | PASS | req:`type=data-list,ref_ids=[WLD-20260825-0018]`; resp:`urls[0].ref_id=WLD-20260825-0018` | `reports/data-list/wld-20260825-0018.json` / `.pdf` | MinIO 直取两文件均 `200`；JSON 含当前 `registration_no=REG-20260825-00018` | 登录→导出 data-list(JSON/PDF)→取回 URL |
| REPORT-002 | 可导出核验报告 | `validation json/pdf` 均 `200`；JSON 含 `report_id=9, version_id=56` | PASS | req:`type=validation,ref_ids=[9]`; resp:`urls[0].ref_id=9` | `reports/validation/9.json` / `.pdf` | JSON 取回 `200`，15 条规则；PDF 取回 `200` | 登录→对 `report_id=9` 导出 validation(JSON/PDF) |
| REPORT-003 | 可导出分析报告 | `analysis json` 成功；`analysis pdf` `500` | FAIL | req:`type=analysis,ref_ids=[54]`; resp:`json=200`,`pdf=500` | JSON:`reports/analysis/54.json`; PDF 未生成 | `api.log` CID `...-report-analysis-pdf` 记 `status=500`；JSON 内容有效 | 登录→导出 analysis(JSON/PDF) |
| REPORT-004 | 可导出标注集 | `annotation json/pdf` 均 `200` | PASS | req:`type=annotation,ref_ids=[9]`; resp:`urls[0].ref_id=9` | `reports/annotation/9.json` / `.pdf` | MinIO 两文件均 `200` | 登录→导出 annotation(JSON/PDF) |
| REPORT-005 | 可导出特征集 | `features json` 成功；`features pdf` `500` | FAIL | req:`type=features,ref_ids=[18]`; resp:`json=200`,`pdf=500` | JSON:`reports/features/18.json`; PDF 未生成 | `api.log` CID `...-report-features-pdf` 记 `status=500` | 登录→先 `POST /features/extract`→导出 features(JSON/PDF) |
| REPORT-006 | 可导出模型测试报告 | `test json` 成功；`test pdf` `500` | FAIL | req:`type=test,ref_ids=[14]`; resp:`json=200`,`pdf=500` | JSON:`reports/test/14.json`; PDF 未生成 | `api.log` CID `...-report-test-pdf` 记 `status=500` | 登录→创建/定位 `test_task_id=14`→导出 test(JSON/PDF) |
| REPORT-007 | PDF / JSON 均可用 | 6 类导出里 JSON 全成功；PDF 仅 `data-list/validation/annotation` 成功，`analysis/features/test` 均 `500` | FAIL | 同上 | 同上 | 三个 PDF 失败 CID：`...analysis-pdf/...features-pdf/...test-pdf` | 分别导出六类 JSON/PDF |
| REPORT-008 | 报告内容对应当前数据/版本/数据集/模型 | `data-list` 指向当前焊缝；`validation` 指向 `version_id=56`；`analysis` 指向 `version_id=54`；`features` 指向 `feature_id=18` 当前焊缝；`test` 指向 `model_version_id=1,dataset_version_id=1` | PASS | 见各 JSON parsed 内容 | 见各 JSON key | JSON 内容逐项匹配当前实体 ID/编号 | 导出后读取 JSON 校对 summary/ref_id |
| REPORT-009 | 真实分析报告包含“信号来源=真实导入” | `reports/analysis/54.json` 的 `summary` 明确 `信号来源=真实导入` | PASS | req:`type=analysis,ref_ids=[54]`; resp:`200` | `reports/analysis/54.json` | JSON 取回 `200`，`summary[4]={label:'信号来源',value:'真实导入'}` | 先上传/挂载真实 CSV→导出 analysis JSON |
| REPORT-010 | 报告对象缺失/URL 过期时页面明确报错 | **仅完成 API 侧验证**：`/files/reports/validation/9.json/url?expires=1` 过期后 MinIO `403 AccessDenied(Request has expired)`；删除对象后再取 URL，MinIO `404 NoSuchKey`。页面提示无法验证 | API-only-BLOCKED | req:`GET /files/.../url?expires=1`; resp:`200 {url}` | `reports/validation/9.json` | `url_checks.expired.fetch=403`; `url_checks.deleted_report.fetch=404` | 导出 validation JSON→取 1s 短链→等待 2s 访问；再删对象后二次访问 |
| OSS-001 | 原始文件位于 `raw/{registration_no}/` | 实际对象键 `raw/REG-20260825-00018/signals.csv` | PASS | req:`POST /files/presign-upload + PUT + /raw-files`; resp:`object_key=raw/.../signals.csv` | `raw/REG-20260825-00018/signals.csv` | PUT `200`; DB `data_versions.id=54.object_keys` 含该 key | 创建登记→presign raw→PUT→挂载 |
| OSS-002 | 处理文件位于 `processed/{weld_id}/` | 实际生成 `processed/WLD-20260825-0018/signals/19.parquet` 与 `processed/WLD-20260825-0018/align/*.csv|json` | PASS | attach/alignment 请求正常 | `processed/WLD-20260825-0018/...` | DB：`signal_ingests.version_id=54 status=succeeded parquet_key=.../19.parquet`；`alignment_tasks.assets` 含 `processed/WLD-20260825-0018/align/...` | 挂载 CSV→等待 signal_ingest；创建 alignment |
| OSS-003 | 模型权重位于 `models/{model_version_id}/` | `models/5/weights.pt` 可经 `/files/models/5/weights.pt/url` 取回 | PASS | req:`GET /files/models/5/weights.pt/url`; resp:`200 {url}` | `models/5/weights.pt` | `url_checks.legit_model.fetch.status=200`，内容 `mock-yolo-weights-placeholder-blob-v1` | 登录→请求模型权重 URL→访问 MinIO |
| OSS-004 | 报告位于 `reports/{report_type}/` | 生成的 key 均符合前缀：如 `reports/data-list/...`、`reports/validation/9.json`、`reports/analysis/54.json` | PASS | 多次 `/reports/export` `200` | 多个 `reports/...` key | `reports` 节点记录了各类型 object key | 分别导出各报告 |
| OSS-005 | 推理临时文件位于 `uploads/` | `/files/upload` 返回 `uploads/ba2a.../file.png` 且带 `lifecycle={temporary,30天}` | PASS | req:multipart `测试 图像.png`; resp:`object_key=uploads/.../file.png` | `uploads/ba2a4029e6c64d09ac460f8510dde75a/file.png` | MinIO URL 可访问 `200`；返回 `lifecycle.prefix=uploads/` | 登录→`POST /files/upload` |
| OSS-006 | 预签名 URL 过期后不可访问 | 报告短链 1s 后访问返回 `403 AccessDenied / Request has expired` | PASS | req:`GET /files/reports/validation/9.json/url?expires=1`; resp:`200 {url}` | `reports/validation/9.json` | `url_checks.expired.fetch.status=403` | 取 1 秒短链→等待→访问 |
| OSS-007 | 非法 key / 路径穿越 key 不能访问其他对象 | `GET /api/v1/files/uploads/../models/5/weights.pt/url` 实际被归一成 `/files/models/5/weights.pt/url`，并成功取到真实权重 `200` | FAIL | req:`/files/uploads/../models/5/weights.pt/url`; resp:`200 {url}` | 实际落到 `models/5/weights.pt` | `api.log` CID `...-path-traversal-url` 的 `path` 已是 `/api/v1/files/models/5/weights.pt/url`；`url_checks.traversal.fetch.status=200` 与 legit 一致 | 登录→请求穿越路径 URL→访问返回真实对象 |
| OSS-008 | PUT 失败后不持久化无效 key | 未上传 `raw/REG-20260825-00019/missing.csv`，直接 `POST /registrations/25/raw-files` 仍 `200`，DB 已持久化 object key，`storage_bytes=19324` | FAIL | req:`object_keys=[raw/.../missing.csv],storage_bytes=19324`; resp:`200` | `raw/REG-20260825-00019/missing.csv` | `api.log` CID `...-bad-raw-attach` 记 `200`；DB `data_versions.id=55.object_keys` 含缺失 key | 新建登记→仅 presign 不 PUT→直接 raw-files 挂载 |
| OSS-009 | 重复挂载相同文件不会无限增加容量/重复任务 | 同一 CSV 二次挂载后 `storage_bytes 19324 -> 38648`；`signal_ingest` 数仍 `1` | FAIL | req:同一 `object_key` 再次 `POST /raw-files`; resp:`200` | `raw/REG-20260825-00018/signals.csv` | `duplicate_attach.before_bytes=19324 after_bytes=38648 before_ingests=1 after_ingests=1` | 对同一登记重复调用 raw-files |
| AUDIT-001 | 登录成功/失败均有访问日志 | `login-success` 记 `200`，`login-fail-0` 记 `401` | PASS | req:`POST /auth/login`; resp:`200/401` | — | `api.log` CIDs `...-login-success`、`...-login-fail-0` 可见 | 正确/错误密码各登录一次 |
| AUDIT-002 | 登记、上传、挂载、版本创建均有审计 | 审计中有登记/挂载/版本创建；**无 upload / presign-upload 审计行** | FAIL | req:`/registrations`,`/files/upload`,`/files/presign-upload`,`/raw-files`,`/welds/.../versions`; resp 均已执行 | — | `audit_logs` 自 `id=215,216,219` 有 weld/create/update；查询 `resource_type like '%file%'` 返回空 | 执行登记、上传、挂载、版本创建后查 `audit_logs` |
| AUDIT-003 | 核验、对齐、切分、标注、特征提取均有审计 | 有核验/切分/标注；**无对齐审计、无特征提取审计** | FAIL | req:`validation/alignment/split/annotation/features`; resp 均实际执行 | — | `audit_logs`：`validate weld(id=220)`、`split_task(id=221)`、`annotation_task(id=222)`；查询 `resource_type in alignment/alignment_task/feature/features` 为空 | 依次执行五类操作后查 `audit_logs` |
| AUDIT-004 | 数据集、训练、测试、推理、报告导出均有审计 | 有 dataset/dataset_build/training/test/inference；**无 report export 审计** | FAIL | req:`/datasets`,`/build-tasks`,`/training-tasks`,`/test-tasks`,`/inference-tasks`,`/reports/export` | 报告 key 见上 | `audit_logs id=223..227` 存在；查询 `action='export' or resource_type='report'` 自本轮开始为空 | 执行五类业务 + 报告导出后查 `audit_logs` |
| AUDIT-005 | 审计记录含操作人/时间/动作/资源类型/资源ID/详情 | `audit_logs` 记录含 `user_id, created_at, action, resource_type, resource_id, detail` | PASS | — | — | 例如 `id=225 training_task job_14c20110 detail={hyperparams...,dataset_version_id:1}`；`id=228 user_id=3` 证明操作人可区分 | 查询本轮 `audit_logs` |
| AUDIT-006 | 敏感字段脱敏 | `api.log` 登录成功/失败均把 `password/access_token/token_type` 写成 `***` | PASS | req:`/auth/login`; resp 脱敏 | — | `api.log` CIDs `...-login-success`、`...-login-fail-0` 明确显示 `***` | 登录后查看 `backend/logs/api.log` |
| AUDIT-007 | 预期 4xx 不会记成 500 | 错误登录记 `401`，缺鉴权记 `401`，不存在模型记 `404`，均非 `500` | PASS | req:`/auth/login wrong`,`/welds(no auth)`,`/models/999999`; resp:`401/401/404` | — | `api.log` CIDs `...-login-fail-0`,`...-noauth-welds`,`...-auth-missing-model` 分别记 `401/401/404` | 执行 4xx 场景并查 `api.log` |
| AUTH-001 | 未登录访问业务页面被拦到登录页 | 浏览器不可用，无法验证页面跳转；仅能确认业务 API 未登录 `401` | API-only-BLOCKED | API req:`GET /welds` 无头; resp:`40100` | — | `browser` 工具报 BetterChromium 缺失；API 无头 401 | 尝试打开前端页（失败）+ 无头调业务 API |
| AUTH-002 | 错误密码/空用户名/空密码登录显示业务错误 | **仅 API 侧验证**：三种请求均 `40100 用户名或密码错误`；页面显示未验证 | API-only-BLOCKED | req:`admin/wrong`,`''/x`,`admin/''`; resp 均 `401 {code:40100,message:'用户名或密码错误'}` | — | `login_failures` 三组均一致 | 发送三组登录请求 |
| AUTH-003 | 篡改/删除/过期 token 刷新后不可继续访问 | **仅 API 侧验证**：无 token 与坏 token 请求业务 API 均 `401`；页面刷新/清 token 跳转未验证 | API-only-BLOCKED | req:`GET /welds` 无头/`Bearer not.a.jwt`; resp:`40100` | — | `auth_cases.noauth_welds=40100`; manual/API probe 坏 token 401 | 无 token / 坏 token 调业务 API |
| AUTH-004 | 不带 Authorization 调业务 API 返回 401 信封 | `GET /welds` 无头返回 `401 {code:40100,message:'未登录或令牌失效'}` | PASS | req:无头 `GET /welds`; resp:`40100` | — | `auth_cases.noauth_welds` + `api.log` CID `...-noauth-welds` | 直接 curl/requests 不带头调用 |
| AUTH-005 | 不存在资源/负数 ID/超长 ID 返回 4xx 非 500 | `GET /models/999999 -> 40401`；`GET /models/-1 -> 40401`；`GET /welds/{300X} -> 40401` | PASS | 见三组请求/响应 | — | `auth_cases.missing_resource/negative_id/long_id`；`api.log` 无 500 | 逐个请求无效资源 ID |
| AUTH-006 | 不会越权读取/修改他人资源 | 新建二号用户 `user_id=3` 后，能 `GET /registrations/24` 且 `PATCH /registrations/24` 成功，把 `product` 改成 `task4-20260825105526-cross-user` | FAIL | req:`GET/PATCH /registrations/24` with user3; resp:`200` | — | `second_user.get_registration`、`second_user.patch_registration` 均 `200`；`audit_logs id=228 user_id=3` | DB 插入第二用户→登录→访问/修改管理员创建的登记 |
| AUTH-007 | 观察暴力尝试/速率限制/失败日志 | 连续 6 次错误登录全部 `401`，未见限速/锁定；失败访问日志存在 | FAIL | 6 次 req:`POST /auth/login wrong-pass`; resp 均 `40100` | — | `brute_force[0..5]` 全 `401`；`api.log` 有失败行但无 429/节流 | 连续快速错误登录 6 次 |
| UI-001 | 后端停机后刷新总览/数据中心/分析/模型中心不白屏 | 浏览器不可用，无法做页面断言 | BLOCKED | — | — | `browser` 工具不可用 | 尝试浏览器自动化失败 |
| UI-002 | 401/404/409/422/500 页面显示可理解错误 | 浏览器不可用；仅 API 侧观察到后端会返回统一错误信封 | API-only-BLOCKED | API 侧已见 401/404/500 | — | 页面未验证；仅 API 有证据 | 需浏览器验证页面错误态 |
| UI-003 | 网络中断后恢复不永久 loading | 浏览器不可用 | BLOCKED | — | — | 同上 | 同上 |
| UI-004 | Job 长轮询/失败/接口异常能结束 loading | 浏览器不可用；API 侧观察到本轮多个 job 长时间 `pending/running`，但页面表现未验证 | API-only-BLOCKED | 见 split/dataset_build/train/test/infer 轮询 | — | `job_2c312aa1/job_9313b3c3/job_14c20110/job_5b752df6/job_7fde66fa` 长时间未完成 | 创建 job 后轮询；页面未验证 |
| UI-005 | 快速切路由/刷新/前进后退无竞态串数据 | 浏览器不可用 | BLOCKED | — | — | 同上 | 同上 |
| UI-006 | 双击保存/开始任务/导出不重复提交 | 浏览器不可用；API 侧已实际发现重复挂载会重复累加容量 | API-only-BLOCKED | 见 duplicate attach API | — | 页面未验证；API 侧存在重复提交风险 | 需浏览器双击验证 |
| UI-007 | 空列表/空状态/超长中文名/文件名/特殊字符正常 | 浏览器不可用 | BLOCKED | — | — | 同上 | 同上 |
| UI-008 | 桌面/窄屏布局可用 | 浏览器不可用 | BLOCKED | — | — | 同上 | 同上 |

## 主要 concerns

1. **报告导出 PDF 不完整**：`analysis/features/test` 的 PDF 导出均返回 `500`；JSON 正常。
2. **对象访问边界存在漏洞**：`/files/uploads/../models/5/weights.pt/url` 可落到真实模型对象，`OSS-007 FAIL`。
3. **无效对象键可落库**：未 PUT 的 raw key 仍能被 `/raw-files` 挂载并累计容量，`OSS-008 FAIL`。
4. **重复挂载仍重复计容量**：相同 raw key 第二次挂载后 `storage_bytes` 翻倍，`OSS-009 FAIL`。
5. **审计不完整**：缺上传、对齐、特征提取、报告导出审计记录。
6. **权限边界过宽**：二号用户可读取并修改管理员创建的登记，`AUTH-006 FAIL`。
7. **限速缺失**：连续错误登录仅返回 401，未见 429/节流，`AUTH-007 FAIL`。
8. **本轮后台 job 执行器不稳定**：`split/dataset_build/training/test/inference` 在本轮观测窗口内长期 `pending/running`，而 `signal_ingest/alignment` 最终成功；需与 Task 3 结论交叉复查运行态差异。
9. **页面项未判 PASS**：因 BetterChromium 缺失，所有前端页面项仅保留 `BLOCKED/API-only-BLOCKED`。

## 修复接管追加记录（2026-08-25 19:20–19:40，本地）

### 变更摘要

1. **OSS-008 / OSS-009**：`POST /registrations/{id}/raw-files` 保留“新 key 才计容量/落版本”的幂等语义，同时把 `signal_ingest` 自动触发改为按**本次请求里的 CSV key** 去重建任务；因此已挂载但尚未导入的 CSV 现在会补建 `signal_ingest`，重复挂载同一 CSV 不再重复建任务。
2. **AUDIT-002 / AUDIT-003 / AUDIT-004**：补齐 `files.upload / files.presign-upload / alignment-task create / features.extract / reports.export` 审计写入。
3. **AUTH-006 ownership/ACL**：继续沿用已有 registration/weld/report ACL 修复，并补齐 analysis/features 读写边界：非管理员不能读取他人 `signals / analysis/result / analysis/{mode} / features/extract / features/{id}`。
4. **live executor pending/running 根因复核**：结合 `task-3-p1-model-report.md` 的运行态证据，根因不是 BetterChromium 缺失，也不是当前 HEAD 的 executor 代码路径；根因是**当时 live 后端进程不是当前 HEAD + live 库存在 schema 漂移**（至少 `data_versions.request_key`、`split_tasks/alignment_tasks request_key/active_request_key` 缺失），导致新任务长期 pending，手动 `run_job()` 时进一步暴露旧 schema 错误。当前测试态与后续 live 复核已证明 executor 自动消费链路本身可工作。

### RED → GREEN 证据

#### RED（本接管会话先验证失败）

- `cd backend && uv run pytest tests/test_audit_routes.py tests/test_signal_ingest.py -k 'route_audits_cover_upload_presign_alignment_features_and_report or raw_files_csv_auto_trigger_and_ingest or auto_executor_consumes_signal_ingest_job or reattach_same_csv_is_idempotent or invalid_csv_failed_and_fallback_generated'`
  - 结果：`5 failed`
  - 失败点：
    - `alignment_task / feature_extraction / report` 审计缺失；
    - `raw-files` 对已挂载 CSV 未补建 `signal_ingest`，导致 4 个信号导入回归失败。
- `cd backend && uv run pytest tests/test_authz.py::test_non_admin_cannot_read_analysis_or_feature_resources_of_admin_record -q`
  - 结果：`1 failed`
  - 失败点：非管理员仍能 `200` 读取管理员焊缝的 `signals`（同类 ACL 漏洞同样影响 `analysis/result`、`analysis/psd`、`features/extract`、`features/{id}`）。

#### GREEN（最小修复后重跑）

- `cd backend && uv run pytest tests/test_audit_routes.py tests/test_signal_ingest.py -k 'route_audits_cover_upload_presign_alignment_features_and_report or raw_files_csv_auto_trigger_and_ingest or auto_executor_consumes_signal_ingest_job or reattach_same_csv_is_idempotent or invalid_csv_failed_and_fallback_generated'`
  - 结果：`5 passed`
- `cd backend && uv run pytest tests/test_authz.py -q`
  - 结果：`4 passed`

### 运行态 / 回归验证

- `cd backend && uv run pytest`
  - 结果：`261 passed, 2 warnings`
  - 覆盖了本次修复涉及的完整回归面：`test_audit_routes / test_authz / test_signal_ingest / test_files / test_reports / test_welds` 以及既有自动 executor 回归。
- `cd /home/pf/code/ai_welding && npm run typecheck`
  - 结果：通过。
- `cd /home/pf/code/ai_welding && npm run build`
  - 结果：通过；仅有既有 `Browserslist: caniuse-lite is outdated` 提示，**不属于本次代码缺陷**。

### 本轮结论

- 已修复并用自动化回归确认：
  - **AUDIT-002 / 003 / 004**
  - **AUTH-006**（registration/weld/report 之外，补齐 analysis/features ACL）
  - **OSS-008 / OSS-009**
  - **Task 4 报告中的 signal_ingest 相关 pending 现象**（测试态根因已定位并修正为 raw mount 触发逻辑；live 长期 pending 根因见上文 schema 漂移/旧进程复核）
- 已保留既有正确修复且未回滚：
  - **OSS-007 路径穿越拦截**
  - **AUTH-007 登录限速**
  - **REPORT-003 / 005 / 006 PDF**
- **UI BetterChromium 缺失** 仍仅记为工具/环境阻塞，未被当作代码问题处理。

## 修复 subagent 追加记录（Task 4 修复轮次 1，AUTH-006 + data-list ACL）

### 变更摘要

1. **AUTH-006 ownership/ACL 改为稳定 owner_user_id 语义**：不再用 `display_name/username` 字符串碰撞判权；统一改为读取 `audit_logs(action=create, resource_type=weld).user_id` 作为焊缝 owner。`operator/display_name` 保留为展示字段，不参与 owner 识别。
2. **同名用户 / 改名回归**：补测并修复“同 display_name 串权”和“owner 改名后失去访问权”两类回归；管理员读写能力保持不变。
3. **data-list 导出补权限边界**：非管理员 `ref_ids=[]` 只导出本人可见记录，不能再借空数组导出全量；指定 weld / registration / DB id 时逐条做 ownership 校验，跨用户 JSON/PDF 均返回 `403`；管理员仍保留全量导出能力。

### RED → GREEN 证据

#### RED

- `cd backend && uv run pytest tests/test_authz.py tests/test_reports.py -k 'same_display_name_collision_does_not_grant_access or owner_keeps_access_after_rename or data_list_export_only_includes_owned_records_when_ref_ids_empty or data_list_export_cannot_read_other_users_requested_weld'`
  - 结果：`5 failed, 1 passed`
  - 失败点：
    - 同名 `display_name` 普通用户可直接读取管理员登记；
    - owner 改名后反而被自己创建的登记拒绝；
    - `data-list` 空 `ref_ids` 仍导出全量；
    - 指定他人 weld 的 `data-list` JSON/PDF 导出仍返回 `200`。

#### GREEN

- `cd backend && uv run pytest tests/test_authz.py tests/test_reports.py -k 'same_display_name_collision_does_not_grant_access or owner_keeps_access_after_rename or data_list_export_only_includes_owned_records_when_ref_ids_empty or data_list_export_cannot_read_other_users_requested_weld'`
  - 结果：`6 passed`
- `cd backend && uv run pytest tests/test_authz.py tests/test_reports.py -q`
  - 结果：`23 passed, 2 warnings`

### 运行态 / 回归验证

- `cd backend && uv run pytest`
  - 结果：`267 passed, 2 warnings`
- `cd /home/pf/code/ai_welding && npm run typecheck`
  - 结果：通过。
- `cd /home/pf/code/ai_welding && npm run build`
  - 结果：通过；仅有既有 `Browserslist: caniuse-lite is outdated` 提示，非本次缺陷。

### 本轮结论

- 已修复并自动化验证：
  - **AUTH-006**（owner 识别改为稳定 `user_id`；同名用户/改名/管理员/owner 读写回归齐全）
  - **REPORT data-list ownership ACL**（空 `ref_ids` 不再绕过；指定 weld 不可跨用户；JSON/PDF 双格式回归）
- 已确认未破坏既有修复面：
  - **OSS-007 / OSS-008 / OSS-009**
  - **REPORT-003 / 005 / 006 PDF**
  - **审计 / 登录限速 / executor**（以全量 `267 passed` 回归为准）
