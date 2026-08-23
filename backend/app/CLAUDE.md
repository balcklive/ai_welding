# CLAUDE.md — backend/app/

应用代码包。当前进度：Task 1（配置 + 日志中间件 + 健康检查）+ Task 2（models + db）。

## 脚本

- `main.py`：FastAPI 实例 `app`。Task 1 直挂 `GET /api/v1/health`（返回统一信封 `{"code":0,"message":"ok","data":{"status":"ok"}}`）；`app.add_middleware(AccessLogMiddleware)`。路由聚合（`include_router(api_router, prefix="/api/v1")`）留给 Task 3。
- `core/__init__.py`：空。
- `core/config.py`：pydantic-settings `Settings` + 模块级单例 `settings`。字段覆盖 MinIO/MySQL/Auth/API 日志；`mysql_url` property 拼 `mysql+pymysql://...`。
- `core/logging.py`：`setup_logging()`（loguru 控制台 + 轮转文件）+ 纯 ASGI `AccessLogMiddleware`。
- `core/db.py`：MySQL `engine` + `SessionLocal` + `get_session()` 依赖（Task 2，详见 `core/CLAUDE.md`）。
- `models/`：全部 23 张 SQLModel 表类（Task 2，详见 `models/CLAUDE.md`）。

## 坑/限制

- **config.env_file 指向仓库根 `.env`**：`Path(__file__).resolve().parents[3] / ".env"`（本文件位于 backend/app/core/，往上 3 层 = 仓库根）。新增配置字段务必同步根 `.env` 与 `.env.example`。
- **`extra="ignore"`**：`.env` 里 `MINIO_CONSOLE`/`MINIO_REGION` 等未声明键被静默忽略，属预期。
- **日志脱敏**（开发规范 §2.4）：键名含 `password`/`token`/`secret` 的值与 Authorization 头 → `***`；`/auth/login` 请求体只记用户名。改中间件时不要破坏该规则。
- **调用人解析**：中间件解 JWT 的 `sub`（不校验签名，尽力而为），失败/缺失 → `anonymous`。Task 5 之后 token 需保证携带 `sub`（届时约定 user id 或 username，见该任务）。
- **返回体截断**：`logging.MAX_BODY_LOG_BYTES = 16KB`（可调，默认 16 KB）。
- **响应头回写** `X-Correlation-ID`，便于前端串联请求。
