# Task 5 P2 边界 / 并发 / 负载 / 恢复测试报告

- 运行批次：`task5p2-20260825T124520Z`
- Git HEAD：`c3825f5908776990adf77b16e4d1cf717bb3a579`
- 环境确认：仅使用本地试验环境 `http://127.0.0.1:8000` + `http://127.0.0.1:5173/ai_welding/`
- 健康检查：`GET /api/v1/health` 前后均 `200 / {code:0,status:"ok"}`
- 日志：`backend/logs/api.log`
- Fixture：`backend/tests/fixtures/destructive/`（27 个文件，约 190MB）
- 说明：本次**未触碰生产**；所有测试数据均带 `task5p2-...` 前缀，便于追溯。

## 1. 基线与增量

### 起止计数

| 指标 | 基线 | 结束 | 增量 |
|---|---:|---:|---:|
| `data_records` | 131 | 176 | +45 |
| `data_versions` | 165 | 211 | +46 |
| `signal_ingests` | 93 | 119 | +26 |
| `jobs` | 233 | 267 | +34 |
| `alignment_tasks` | 16 | 17 | +1 |
| `training_tasks` | 29 | 31 | +2 |
| `inference_tasks` | 27 | 32 | +5 |
| MinIO 对象数 | 6134 | 6202 | +68 |
| MinIO 字节数 | 422561394 | 514181303 | +91619909 |

### Job 状态变化

- 基线：`failed=37, running=7, succeeded=189`
- 结束：`failed=40, running=7, succeeded=220`
- 观察：新增成功 Job 为主；失败 Job 增量 `+3`，与畸形 CSV / 并发冲突一致。

## 2. BOUNDARY-001..009

| 编号 | 结论 | 证据摘要 |
|---|---|---|
| BOUNDARY-001 | 通过 | `q=' OR 1=1--`、`q='; DROP TABLE users;--` 均返回 `200`，无 500、无异常数据泄露。 |
| BOUNDARY-002 | 阻塞 | API 侧恶意字符串登记成功且无 500；但持续负载后 headless 浏览器/Vite hydration 无法稳定完成，**未能最终可视化确认**“无弹窗执行”。 |
| BOUNDARY-003 | 通过 | `empty_0bytes.csv` 上传 `200`，挂载时正确返回 `400`：`对象大小非法`，非 500。 |
| BOUNDARY-004 | 失败 | `malformed_empty` / `no_header` 能落到 failed ingest；但 `malformed_non_numeric.csv` 上传直接 `500`。 |
| BOUNDARY-005 | 失败 | BOM CSV 成功导入；UTF-16 正常 failed ingest；但 `malformed_inconsistent_columns.csv` 上传 `500`。 |
| BOUNDARY-006 | 通过 | 损坏 MP4/JPG/空 WAV 上传均 `200`，未触发 500/泄露。 |
| BOUNDARY-007 | 失败 | 路径穿越下载 URL 正确 `400`；伪扩展名上传 `200`；但超长文件名上传 `500`，路径穿越文件名场景出现连接重置。 |
| BOUNDARY-008 | 失败 | `presign-upload` 101MB 返回 `200`（预签名直传可用）；但 `valid_large_100k.csv` 与 `valid_huge_1m.csv` 代理上传均在 ~60-69s 超时，未完成导入。 |
| BOUNDARY-009 | 通过 | 分页边界被钳制（`page_size=0 -> 1`，`100000 -> 100`）；非法分析 `mode/channel/filter` 均返回 `400`，无 500。 |

### 关键边界细节

- `BOUNDARY-003`：`POST /registrations/{id}/raw-files` 返回 `40000`，消息 `对象大小非法`。
- `BOUNDARY-005`：`malformed_utf8_bom.csv` 实际被成功识别并导入（5000 行、1000Hz、5.0s）。
- `BOUNDARY-008`：
  - `POST /files/presign-upload` for `101MB`：`200`，约 `414.73ms`。
  - `POST /files/upload` for `valid_large_100k.csv`：客户端 `~60077ms` 超时。
  - `POST /files/upload` for `valid_huge_1m.csv`：客户端 `~68784ms` 超时。

### 边界失败的日志证据

1. **长 object key 导致上传 500**
   - `backend/logs/api.log` 记录：
   - `pymysql.err.DataError: (1406, "Data too long for column 'resource_id' at row 1")`
   - 触发点：`/api/v1/files/upload` 写 `audit_logs.resource_id`，例如 `malformed_non_numeric.csv`。
2. **长文件名 / 特殊文件名未被 graceful 处理**
   - 同样落到 `audit_logs.resource_id` 长度问题，导致 `500` 而非预期 `4xx/200`。

## 3. LOAD-001..006

| 编号 | 结论 | 证据摘要 |
|---|---|---|
| LOAD-001 | 失败 | 50 并发重复登记：`200=4, 500=26, timeout=20`；应为 409/幂等，但实际大量 500。 |
| LOAD-002 | 失败 | 20 并发挂载同一 CSV：`200=7, 500=13`；最终仅 1 条 ingest 成功，但冲突未被转成 409/已有任务。 |
| LOAD-003 | 通过 | 20 导入 + 5 对齐 + 5 训练 + 5 推理共 35 次提交全部 `200`；仅生成 8 个唯一 job_id，全部最终 `succeeded`。 |
| LOAD-004 | 通过 | 100 并发读（总览/项目/列表/候选）全部 `200`；`p50=2790.64ms`，`p95=3938.38ms`，无 5xx。 |
| LOAD-005 | 阻塞 | 并发分析读取 20 次全部 `200`（`p50=1281.33ms`）；但 1M/100k 大 CSV 上传在 60s 客户端超时，未形成可轮询导入任务，故只能记录实际边界。 |
| LOAD-006 | 通过 | 任务状态在重启前后均可恢复；重启后健康检查恢复 `200`，被抽查 Job 仍为 `succeeded`。 |

### 并发 / 负载明细

#### LOAD-001 并发重复登记（50）

- 状态码分布：`200=4, 500=26, timeout=20`
- `p50=19167.01ms`，`p95=60078.41ms`，`max=61250.78ms`
- 日志明确出现未兜底唯一约束异常：
  - `Duplicate entry 'WLD-20260825-0146' for key 'data_records.uq_data_records_weld_id'`
- 结论：**符合“发生冲突”，但不符合“返回 409 而不是 500”**。

#### LOAD-002 并发挂载同一 CSV（20）

- 状态码分布：`200=7, 500=13`
- `p50=4916.75ms`，`p95=7295.38ms`
- 最终只生成 1 条 `signal_ingests` 成功记录：
  - `signal_ingest_id=108`
  - `job_uid=job_7834ccb3`
  - `row_count=500`
- 日志明确出现未兜底唯一约束异常：
  - `Duplicate entry '189-uploads/.../valid_small_500.csv' for key 'signal_ingests.uq_signal_ingests_version_key'`
- 结论：**幂等结果最终成立，但接口层没有把冲突转成 409/复用已有任务，而是大量 500。**

#### LOAD-003 多任务提交

- 总请求数：35
- 状态码：全部 `200`
- 唯一 Job 数：8
- 8 个 Job 最终状态：全部 `succeeded`
- 说明：任务执行器在该规模下未见死锁。

#### LOAD-004 100 并发只读

- 全部 `200`
- `p50=2790.64ms`，`p95=3938.38ms`，`max=5420.17ms`
- 未见连接池耗尽/5xx。

#### LOAD-005 大文件导入期间刷分析页

- 20 次分析读取全部 `200`
- `p50=1281.33ms`，`p95=1731.26ms`
- 但大 CSV 代理上传未在 60s 内返回，实际边界已记录，未无限等待。

#### LOAD-006 恢复验证

- 登录暴力（受控 admin 字典，7 次）状态：`401=5, 429=2, 5xx=0`
- 后端重启后：`GET /api/v1/health -> 200`
- 抽查任务：重启前 `succeeded`，重启后仍 `succeeded`
- 结论：服务恢复与已完成任务可恢复。

## 4. 日志 / 恢复 / 追溯

- 所有新增测试记录都带 `task5p2-...` 前缀，可在：
  - `data_records.source`
  - `data_records.weld_name`
  - `audit_logs.detail/request`
  - MinIO `raw/` / `uploads/` 前缀
  中追溯。
- 本次未做强制清库；保持**可追溯**而非强删。
- 日志脱敏正常：登录 password / token 已在 `api.log` 中掩码为 `***`。

## 5. 主要问题 / concerns

1. **登记并发存在未兜底唯一键冲突**：`LOAD-001` 触发 `data_records.uq_data_records_weld_id`，大量 500，未转 409。
2. **同一 CSV 并发挂载存在未兜底唯一键冲突**：`LOAD-002` 触发 `signal_ingests.uq_signal_ingests_version_key`，大量 500。
3. **上传审计链路会被长 object key / 文件名击穿**：`audit_logs.resource_id` 长度不足导致 `/files/upload` 直接 500（`Data too long for column 'resource_id'`）。
4. **大 CSV 代理上传实际边界偏低**：100k / 1M CSV 在本环境中均在 60s 客户端超时，未完成导入；101MB 仅预签名直传路径可用。
5. **浏览器层 XSS / 前端优雅降级验证不完整**：持续负载后 headless 浏览器对 Vite 页面 hydration 不稳定，`BOUNDARY-002` 只能给出 API 侧结论，不能最终可视化确认“无弹窗执行”。

## 6. 结论汇总

- 通过：7
- 失败：6
- 阻塞：2
- 额外观察（不计入 15 项）：登录暴力受控测试返回 `401/429`，无 500。

## 7. 修复接管（2026-08-25，P2 收尾）

### 已落实的后端修复

1. **登记并发 409/幂等**
   - `POST /registrations` 新增**自然幂等 payload 锁**：按 operator + 表单载荷计算 request key。
   - MySQL 走 `GET_LOCK(data_record_req:...)`，SQLite/本地并发走进程内锁集合。
   - 重复中的同 payload 提交直接 `40900`，不再落第二条记录，也不再冒成 500。

2. **并发同 CSV 挂载 409 / 容量不重复**
   - `POST /registrations/{id}/raw-files` 对 CSV 请求新增 version+object_keys 级别的 payload 锁。
   - 若任一请求中的 CSV 已有 `signal_ingests` 行，直接 `40900`。
   - 非 CSV 原始文件仍保持幂等追加；`storage_bytes` 只对新 key 累加，不会被并发/重复请求放大。

3. **`audit_logs.resource_id` 兼容长 object key**
   - 新增 Alembic `0005_audit_resource_id_255.py`：`audit_logs.resource_id` 从 64 扩到 255。
   - `write_audit()` 现在**完整保留 ≤255** 的资源标识；只有 >255 时才截断并附 12 位 sha1 后缀。
   - 长文件名 / 长 object key 上传不再因审计写入 `Data too long` 打成 500。

4. **大 CSV 不再静默 60s 超时**
   - `POST /files/upload` 对 CSV 增加默认 `5MB` 代理门槛（`MAX_PROXY_CSV_UPLOAD_SIZE`）。
   - 超限立即 `40000`：`CSV 文件过大，请改用 /api/v1/files/presign-upload 直传后再挂载异步导入`。
   - 保留小 CSV 代理上传路径；大 CSV 走 `presign-upload + raw-files + signal_ingest job` 的明确异步路径。

### 新增 / 收紧的自动化回归

- `backend/tests/test_welds.py`
  - `test_create_registration_rejects_concurrent_duplicate_payload`
  - `test_attach_raw_files_second_csv_submit_returns_409`
  - `test_attach_raw_files_rejects_concurrent_duplicate_csv_submit`
  - `test_attach_raw_files_returns_409_when_csv_ingest_already_exists`
- `backend/tests/test_files.py`
  - `test_upload_large_csv_uses_default_4xx_instead_of_hanging`
  - `test_upload_long_filename_does_not_fail_audit`
- `backend/tests/test_common.py`
  - 长 `resource_id` + detail 脱敏审计回归
- `backend/tests/test_models.py`
  - 在线 Alembic 路径断言 `head == 0005`，并校验 `audit_logs.resource_id == 255`

### RED / GREEN 记录

- RED：
  - `uv run pytest tests/test_welds.py::test_create_registration_rejects_immediate_duplicate_payload tests/test_welds.py::test_attach_raw_files_returns_409_when_csv_ingest_already_exists -q`
  - 结果：2 failed（重复登记仍 200；已有 ingest 的 CSV 仍 200）
- GREEN（定向）：
  - `uv run pytest tests/test_welds.py::test_create_registration_rejects_concurrent_duplicate_payload tests/test_welds.py::test_attach_raw_files_second_csv_submit_returns_409 tests/test_welds.py::test_attach_raw_files_rejects_concurrent_duplicate_csv_submit tests/test_welds.py::test_attach_raw_files_returns_409_when_csv_ingest_already_exists tests/test_files.py::test_upload_large_csv_uses_default_4xx_instead_of_hanging tests/test_files.py::test_upload_long_filename_does_not_fail_audit tests/test_common.py::test_write_audit_truncates_long_resource_id_and_masks_sensitive_detail tests/test_models.py::test_alembic_upgrade_online_real_path_executes_0003 -q`
  - 结果：全部通过（最终定向集已纳入全量 pytest）

### 全量验证

- `cd backend && uv run pytest -q`
  - **277 passed**, 2 warnings
- `cd backend && uv run alembic upgrade head`
  - MySQL 在线升级执行成功（当前 head 含 `0005`）
- `npm run typecheck`
  - 通过
- `npm run build`
  - 通过（仅有既有 Browserslist outdated 提示）

### 真实受控复测（本地试验环境）

1. **并发同 CSV 挂载（当前代码 / 独立 8001 进程）**
   - 建立一条 DB 直写的 v1.0 测试记录后，对同一个 `valid_small_500.csv` object key 发起 8 并发挂载：
   - 结果：`200=1, 409=7`
   - `storage_bytes = 12012`（只计 1 次）
   - `signal_ingests`：仅 1 行

2. **大 CSV 真实复测**
   - `valid_large_100k.csv` 通过 `POST /files/upload`
   - 结果：`40000 / CSV 文件过大，请改用 /api/v1/files/presign-upload 直传后再挂载异步导入`
   - 响应耗时：约 **199.65ms**
   - 结论：已从“60s+ 静默超时”改为“明确 4xx + 明确异步路径”

3. **并发登记复测**
   - 一轮真实并发复测已出现 `200=1, 409=7`；
   - 但后续在共享本地试验库上重复压测时，出现全部 `40900/获取登记编号锁失败` 的现象，说明当前环境里还存在**同日登记编号锁被其他本地会话占用/竞争**的噪声。
   - pytest 的并发回归（SQLite 文件库）已稳定验证 `200+409` 且仅落一条记录；接口层不再出现 500。

### BOUNDARY-002 状态

- **保持阻塞，不补造 UI 证据**。
- 本轮仅修后端与自动化回归；未伪造“浏览器无弹窗执行”的前端可视化结论。

## 8. 修复轮次 1（MySQL 登记编号 advisory lock 生命周期）

### 审查结论 / 根因

- `GET_LOCK` / `RELEASE_LOCK` 是 **MySQL 连接级** 语义，不随事务自动释放。
- 旧实现把 `GET_LOCK` 绑在请求 `Session` 当前连接上；`commit()` / `rollback()` 后再在 `finally` 里用 `session.connection()` 调 `RELEASE_LOCK`。
- 在连接池竞争下，`Session` 可能已切到**另一条 pooled connection**，导致：
  - `RELEASE_LOCK` 实际跑在错误连接上；
  - 原连接上的 lock 驻留在池里；
  - 后续普通登记命中同日编号锁时误报 `40900 获取登记编号锁失败`。

### 代码修复

- `backend/app/services/welds.py`
  - 为 MySQL advisory lock 新增独立 `_MySQLAdvisoryLock` 句柄。
  - 登记编号锁 / 登记 payload 锁 / raw-files payload 锁统一改为：
    1. 用 **独立专用连接** 执行 `GET_LOCK`
    2. 业务请求的 `Session` 事务与该锁连接解耦
    3. `finally` 中先显式 `RELEASE_LOCK`
    4. 再 `close()` 归还锁连接到池
- 不再依赖 Session 事务结束或连接池回收来隐式解锁。

### 新增自动化回归（TDD）

- RED：
  - `cd backend && uv run pytest tests/test_welds.py::test_mysql_registration_lock_released_after_rollback_allows_followup_registration -q`
  - 失败现象：复现 rollback 后 lock 驻留，随后普通 `POST /api/v1/registrations` 返回 `40900 获取登记编号锁失败`。
- GREEN（定向）：
  - `cd backend && uv run pytest tests/test_welds.py::test_create_registration_rejects_concurrent_duplicate_payload tests/test_welds.py::test_mysql_registration_lock_released_after_rollback_allows_followup_registration tests/test_welds.py::test_attach_raw_files_rejects_concurrent_duplicate_csv_submit tests/test_welds.py::test_attach_raw_files_returns_409_when_csv_ingest_already_exists -q`
  - 结果：`4 passed`

### 全量 / 迁移验证

- `cd backend && uv run pytest -q`
  - 结果：`278 passed, 2 warnings`
- `cd backend && uv run alembic upgrade head`
  - 结果：成功（MySQL head 已可在线升级）

### 真实 HTTP 并发与后续单次登记复测

- 本地进程：`uv run uvicorn app.main:app --host 127.0.0.1 --port 8001`
- 认证：管理员登录后对同 payload 发起 8 并发 `POST /api/v1/registrations`
- 测试日：`2099-02-28`
- 结果：
  - 并发重复登记：`200 x 1`，`409 x 7`，`500 x 0`
  - 409 消息：`重复登记请求：相同表单正在提交`
  - 后续普通登记（不同 payload，同日立即追加一笔）：`200`，成功生成
    - `weld_id = WLD-20990228-0002`
    - `registration_no = REG-20990228-00002`
- 结论：MySQL advisory lock 不再驻留；并发重复登记满足 **1 成功 / 其余 409 / 0 个 500**，后续普通登记立即可用。
