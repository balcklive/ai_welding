# CLAUDE.md — backend/app/

应用代码包。当前进度：Task 1（配置 + 日志中间件 + 健康检查）+ Task 2（models + db）+ Task 3（统一信封 + 异常处理 + 路由聚合 + audit + 分页助手）+ Task 4（MinIO 存储客户端）+ Task 5（密码哈希 + JWT + login/me）+ Task 6（启动 seed）。

## 脚本

- `main.py`：FastAPI 实例 `app`。Task 1 直挂 `GET /api/v1/health`（返回统一信封 `{"code":0,"message":"ok","data":{"status":"ok"}}`）+ `AccessLogMiddleware`；Task 3 `include_router(api_router, prefix="/api/v1")` 聚合 v1 路由，并 `register_exception_handlers(app)` 注册全局异常处理器（`RequestValidationError`→42200 / `HTTPException` 按 status 映射 / 兜底 `Exception`→50000）。异常错误码映射见本文件 docstring。Task 5 修复：`setup_logging()` 后检查 `settings.secret_key`/`settings.admin_password` 是否弱默认值（`change-me`/`admin123`），是则 `logger.warning` 提示生产改密。Task 6：lifespan 启动时 `with Session(engine) as s: seed_all(s)`（MySQL 不可达仅告警不阻塞）。
- `core/seed.py`：**Task 6**。`seed_all/seed_admin/seed_demo`，详见 `core/CLAUDE.md`。
- `core/__init__.py`：空。
- `core/config.py`：pydantic-settings `Settings` + 模块级单例 `settings`。字段覆盖 MinIO/MySQL/Auth/API 日志；`mysql_url` property 拼 `mysql+pymysql://...`。
- `core/logging.py`：`setup_logging()`（loguru 控制台 + 轮转文件）+ 纯 ASGI `AccessLogMiddleware`。
- `core/db.py`：MySQL `engine` + `SessionLocal` + `get_session()` 依赖（Task 2，详见 `core/CLAUDE.md`）。
- `core/audit.py`：`write_audit(...)` 向 `audit_logs` 写审计（Task 3，详见 `core/CLAUDE.md`）。
- `core/security.py`：密码哈希 + JWT 签发/解析（Task 5，详见 `core/CLAUDE.md`）。
- `models/`：全部 23 张 SQLModel 表类（Task 2，详见 `models/CLAUDE.md`）。
- `schemas/`：统一响应信封 `ok/err` + 分页 `paginate`（Task 3，详见 `schemas/CLAUDE.md`）。
- `api/`：v1 路由聚合（Task 3 骨架，各域占位）+ `deps.py` 公共依赖 `get_current_user`（Task 5），详见 `api/CLAUDE.md`。

## 坑/限制

- **config.env_file 指向仓库根 `.env`**：`Path(__file__).resolve().parents[3] / ".env"`（本文件位于 backend/app/core/，往上 3 层 = 仓库根）。新增配置字段务必同步根 `.env` 与 `.env.example`。
- **`extra="ignore"`**：`.env` 里 `MINIO_CONSOLE`/`MINIO_REGION` 等未声明键被静默忽略，属预期。
- **日志脱敏**（开发规范 §2.4）：键名含 `password`/`token`/`secret` 的值与 Authorization 头 → `***`；`/auth/login` 请求体只记用户名。改中间件时不要破坏该规则。
- **调用人解析**：中间件解 JWT 的 `sub`（不校验签名，尽力而为），失败/缺失 → `anonymous`。Task 5 之后 token 需保证携带 `sub`（届时约定 user id 或 username，见该任务）。
- **返回体截断**：`logging.MAX_BODY_LOG_BYTES = 16KB`（可调，默认 16 KB）。
- **响应头回写** `X-Correlation-ID`，便于前端串联请求。
