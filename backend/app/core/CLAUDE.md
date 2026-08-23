# CLAUDE.md — backend/app/core/

核心配置与基础设施。当前进度：Task 1（配置 + 日志中间件）+ Task 2（db 会话）+ Task 3（audit 写入）+ Task 5（密码哈希 + JWT）。

## 脚本

- `__init__.py`：空包。
- `config.py`：pydantic-settings `Settings` + 模块级单例 `settings`。字段覆盖 MinIO/MySQL/Auth/API 日志；`mysql_url` property 拼 `mysql+pymysql://...`。
- `logging.py`：`setup_logging()`（loguru 控制台 + 轮转文件）+ 纯 ASGI `AccessLogMiddleware`。
- `db.py`：**Task 2**。模块级 `engine`（MySQL，`settings.mysql_url`，`pool_pre_ping=True`）、`SessionLocal`（`sessionmaker`，`expire_on_commit=False`）、`get_session()`（FastAPI 依赖，`yield` 一个 `Session`）。
- `audit.py`：**Task 3**。`write_audit(session, user_id, action, resource_type, resource_id=None, detail=None)` 向 `audit_logs`（模型 `AuditLog`，§3.23）插一行，`created_at=datetime.now(timezone.utc)`（UTC aware）。**只 `session.add` + `session.flush`，不 commit**——由调用方统一 commit，保证审计与业务变更同事务。
- `security.py`：**Task 5**。`hash_password(plain) -> str` / `verify_password(plain, hash) -> bool`（pwdlib `PasswordHash.recommended()`，Argon2）；`create_access_token(user: User) -> str`（PyJWT HS256，`sub=str(user.id)`，`exp = now + access_token_expire_minutes`，`iat` 已设）；`decode_token(token) -> int`（返回 user id，失败抛 `jwt.PyJWTError`/`ValueError`）。**坑：** pwdlib `verify` 对无法识别的哈希格式（如测试里随手填的 `"hash"`）会抛 `UnknownHashError`，`verify_password` 统一捕获按不匹配处理，避免坏哈希让登录 500。

## 坑/限制

- **config.env_file 指向仓库根 `.env`**：`Path(__file__).resolve().parents[3] / ".env"`（本文件位于 backend/app/core/，往上 3 层 = 仓库根）。新增配置字段务必同步根 `.env` 与 `.env.example`。
- **`extra="ignore"`**：`.env` 里 `MINIO_CONSOLE`/`MINIO_REGION` 等未声明键被静默忽略，属预期。
- **日志脱敏**（开发规范 §2.4）：键名含 `password`/`token`/`secret` 的值与 Authorization 头 → `***`；`/auth/login` 请求体只记用户名。改中间件时不要破坏该规则。
- **调用人解析**：中间件解 JWT 的 `sub`（不校验签名，尽力而为），失败/缺失 → `anonymous`。Task 5 之后 token 需保证携带 `sub`。
- **返回体截断**：`logging.MAX_BODY_LOG_BYTES = 16KB`（可调，默认 16 KB）。
- **响应头回写** `X-Correlation-ID`，便于前端串联请求。
- **db.py 的 MySQL 引擎不要在生产/测试里误用**：测试用内存 SQLite 引擎 + `SQLModel.metadata.create_all`（见 `tests/test_models.py`），绝不连远程库。`import app.core.db` 会触发建 MySQL engine（惰性，不连库）。
- **业务用 Session 推荐 `Session(engine)` 或 `SessionLocal()`**；依赖注入用 `get_session()`。
