# CLAUDE.md — backend/app/core/

核心配置与基础设施。当前进度：Task 1（配置 + 日志中间件）+ Task 2（db 会话）+ Task 3（audit 写入）+ Task 5（密码哈希 + JWT）+ Task 6（启动 seed）。

## 脚本

- `__init__.py`：空包。
- `config.py`：pydantic-settings `Settings` + 模块级单例 `settings`。字段覆盖 MinIO/MySQL/Auth/API 日志；`mysql_url` property 拼 `mysql+pymysql://...`；`job_executor_enabled` 允许候选容器禁用任务消费。**2026-09 新增 `minio_server_endpoint`**（`MINIO_SERVER_ENDPOINT`，服务端内网端点，空则回退公网——配合 storage 双端点内网化，见 `storage/CLAUDE.md`）。
- `logging.py`：`setup_logging()`（loguru 控制台 + 轮转文件）+ 纯 ASGI `AccessLogMiddleware`。
- `db.py`：**Task 2**。模块级 `engine`（MySQL，`settings.mysql_url`，`pool_pre_ping=True`）、`SessionLocal`（`sessionmaker`，`expire_on_commit=False`）、`get_session()`（FastAPI 依赖，`yield` 一个 `Session`）。
- `health.py`：readiness 聚合。数据库检查 `SELECT 1`、Alembic 当前 revision、关键表（users/jobs/data_records）；对象存储检查 MinIO 目标桶存在。对外仅返回检查项状态，异常详情只写日志。
- `audit.py`：**Task 3**。`write_audit(session, user_id, action, resource_type, resource_id=None, detail=None)` 向 `audit_logs`（模型 `AuditLog`，§3.23）插一行，`created_at=datetime.now(timezone.utc)`（UTC aware）。**只 `session.add` + `session.flush`，不 commit**——由调用方统一 commit，保证审计与业务变更同事务。**Task 4 修复**：`detail` 会递归脱敏键名含 `password/token/secret` 的字段，避免把登录密码、令牌或导出密钥类信息写进审计表。**Task 5 P2 修复**：`resource_id` 现在允许完整保存 ≤255 的 object key；仅当超出 255 时才截断并附 12 位 sha1 后缀，避免长文件名/长对象键把上传审计打成 500。
- `security.py`：**Task 5**。`hash_password(plain) -> str` / `verify_password(plain, hash) -> bool`（pwdlib `PasswordHash.recommended()`，Argon2）；`create_access_token(user: User) -> str`（PyJWT HS256，`sub=str(user.id)`，`exp = now + access_token_expire_minutes`，`iat` 已设）；`decode_token(token) -> int`（返回 user id，失败抛 `jwt.PyJWTError`/`ValueError`）。**坑：** pwdlib `verify` 对无法识别的哈希格式（如测试里随手填的 `"hash"`）会抛 `UnknownHashError`，`verify_password` 统一捕获按不匹配处理，避免坏哈希让登录 500。
- `seed.py`：**Task 6**。`seed_admin(session)` 无 `users.username == admin_username` 时插管理员（林工/admin，argon2 哈希）；`seed_demo(session)` 写演示数据（数值对齐 `src/App.tsx`：4 条焊缝 + 版本链 v1.0→v1.3（0245 停在 v1.0）、0248 核验 93.3 + 15 条规则（第 9 项警告）、3 数据集 + 3 模型、标注页演示样本、审计日志）；`seed_all(session, *, demo=True)` = `seed_admin` +（`demo=True` 时）`seed_demo` + 末尾统一 `session.commit()`，**幂等**（按业务唯一键跳过）。**坑：** 全部走 ORM，无 MySQL 特有 SQL（SQLite 测试可用）；`Session(engine)` 的 `with` 退出只 close 不 commit，故 `seed_all` 必须自行 commit 数据才会落库。**`demo` 默认 True 仅供测试；`main.py` 传 `settings.seed_demo`（`SEED_DEMO`，默认 false）**——演示数据集带假账（`dataset_versions.item_count=5680` 但 `dataset_items` 空，前端"样本数 5680 点进去为空"即此），线上曾因此污染真实库并每次重启回灌，勿随意打开。

## 坑/限制

- **config.env_file 指向仓库根 `.env`**：`Path(__file__).resolve().parents[3] / ".env"`（本文件位于 backend/app/core/，往上 3 层 = 仓库根）。新增配置字段务必同步根 `.env` 与 `.env.example`。
- **`extra="ignore"`**：`.env` 里 `MINIO_CONSOLE`/`MINIO_REGION` 等未声明键被静默忽略，属预期。
- **日志脱敏**（开发规范 §2.4）：键名含 `password`/`token`/`secret` 的值与 Authorization 头 → `***`；`/auth/login` 请求体只记用户名。改中间件时不要破坏该规则。
- **调用人解析**：中间件解 JWT 的 `sub`（不校验签名，尽力而为），失败/缺失 → `anonymous`。Task 5 之后 token 需保证携带 `sub`。
- **返回体截断**：`logging.MAX_BODY_LOG_BYTES = 16KB`（可调，默认 16 KB）。
- **响应头回写** `X-Correlation-ID`，便于前端串联请求。
- **db.py 的 MySQL 引擎不要在生产/测试里误用**：测试用内存 SQLite 引擎 + `SQLModel.metadata.create_all`（见 `tests/test_models.py`），绝不连远程库。`import app.core.db` 会触发建 MySQL engine（惰性，不连库）。
- **业务用 Session 推荐 `Session(engine)` 或 `SessionLocal()`**；依赖注入用 `get_session()`。
