# CLAUDE.md — backend/tests/

pytest 测试。运行 `uv run pytest`（内存 SQLite / 假客户端，绝不连远程 MySQL / MinIO）。
`tests/__init__.py` 使 backend/ 进入 sys.path，pytest 才能 `from app...` import。

## 脚本

- `test_app.py`（Task 1）：`GET /api/v1/health` 统一信封 + `X-Correlation-ID` 回写。用真实 `app.main` 的 TestClient。
- `test_config.py`（Task 1）：`Settings` 默认值 / `mysql_url` 拼接（不读远程）。
- `test_logging.py`（Task 1）：`_mask`/`_mask_query` 脱敏（password/token/secret → `***`）与 `_caller_from_authorization` 调用人解析。
- `test_models.py`（Task 2）：内存 SQLite 建全部 23 张表 + 索引一致性（含与迁移 `0001_initial.py` 的索引对齐防漂移）+ 关键表插入/复合唯一/环形指针。
- `test_common.py`（Task 3）：`ok/err/paginate` 信封纯函数 + 全局异常处理器（隔离迷你 app）+ `write_audit` 审计写入。
- `test_storage.py`（Task 4）：`normalize_filename`/`normalize_key` 纯函数断言 + 假 `Minio` 客户端注入测参数透传，不连真实 MinIO。
- `test_auth.py`（Task 5）：JWT 认证。内存 SQLite **必须 `poolclass=StaticPool` + `check_same_thread=False`**——TestClient 在 worker 线程处理请求，默认 per-thread 池会让各线程看到互相独立的空库（"no such table"）；用 `app.dependency_overrides[get_session]` 覆盖登录与 `get_current_user` 两处依赖，seed 一个 argon2 用户测 login 成功/密码错/用户不存在、me 带/不带/坏 token、`decode_token` 往返、`verify_password`。另含防枚举机制断言：`_DUMMY_HASH` 是合法 argon2 哈希且任意明文均不匹配（不直接断言耗时，避免 CI 抖动）。
- `test_seed.py`（Task 6）：内存 SQLite + `SQLModel.metadata.create_all`，同线程直跑 `seed_all`（不用 TestClient/StaticPool）。`seed_all` 两次幂等（各表数量不翻倍）；label_categories==5 / welds==4 / models==3 / datasets==3；管理员 `verify_password(admin_password)` True；0248 有 4 版本且 latest→v1.3、核验 93.3/14/1/0/2.8 + 15 条规则（第 9 项警告）；0245 停在 v1.0；标注页演示数据就位。
- `test_jobs.py`（Task 7）：通用 Job 服务 + `GET /jobs/{job_id}`。内存 SQLite + StaticPool + 真实 app TestClient（同 test_auth.py）；依赖覆盖 `get_session` → 测试 session，另 override `get_current_user` → 假 User（免 seed/签 token）。覆盖：create_job（job_uid 前缀 `job_` + 8 位、pending/progress=0、created_at UTC aware、**不 commit**——rollback 后查不到、flush 即分配 id）、状态机（running/succeeded/failed 各设字段 + finished_at）、to_job_payload §1.5 形状 + ISO-8601 `...Z` 时间、`_iso_utc` 对 **naive datetime 按 UTC 处理**（读回路径 tzinfo 被剥离，防系统时区偏移）、GET 200 信封 / 未知 uid 404（40401）/ 未登录 401（40100）。
- `test_dashboard.py`（Task 8）：Dashboard 四端点。内存 SQLite + StaticPool + 真实 app TestClient；`seed_all` 造演示数据（4 焊缝 / 3 数据集 / 2 样本 / 2 标注）后 override `get_session` + `get_current_user`。覆盖：四端点信封 code==0、stats 数值（data_total==4 / manufacturer_total==4 / max_storage_bytes==2576980378 / annotated_samples==2 / completion==100.0）、attributes 非空（weld_methods 4 台 distinct machine、defect_types 含统计口径词表、modalities/sample_rate_tiers）、distributions 形状（welding_types==MAG2/MIG1/TIG1、defects 含全部统计词表、wordcloud name/size）、projects 3 条且字段来自数据集、四端点未登录全 401（40100）。

## 坑/限制

- **内存 SQLite + TestClient 必须 StaticPool**（见上）。`test_models.py` 未用 TestClient、同线程跑，才可用默认池。
- 断言 `err()` 信封用 `json.loads(resp.body)`（`err` 返回 `JSONResponse`，无 `.json()`）。
- 异常处理器测试用独立迷你 FastAPI app，避免污染真实 `app.main` 的路由/中间件。
- 依赖覆盖用函数对象做 key：`app.dependency_overrides[get_session] = override`，用后 `pop` 恢复。
