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
- `test_auth.py`（Task 5）：JWT 认证。内存 SQLite **必须 `poolclass=StaticPool` + `check_same_thread=False`**——TestClient 在 worker 线程处理请求，默认 per-thread 池会让各线程看到互相独立的空库（"no such table"）；用 `app.dependency_overrides[get_session]` 覆盖登录与 `get_current_user` 两处依赖，seed 一个 argon2 用户测 login 成功/密码错/用户不存在、me 带/不带/坏 token、`decode_token` 往返、`verify_password`。

## 坑/限制

- **内存 SQLite + TestClient 必须 StaticPool**（见上）。`test_models.py` 未用 TestClient、同线程跑，才可用默认池。
- 断言 `err()` 信封用 `json.loads(resp.body)`（`err` 返回 `JSONResponse`，无 `.json()`）。
- 异常处理器测试用独立迷你 FastAPI app，避免污染真实 `app.main` 的路由/中间件。
- 依赖覆盖用函数对象做 key：`app.dependency_overrides[get_session] = override`，用后 `pop` 恢复。
