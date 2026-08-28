"""FastAPI 应用入口。

- Task 1：日志中间件（`AccessLogMiddleware`）+ 健康检查。
- Task 3：挂载 v1 路由聚合（`/api/v1` 前缀在此添加）+ 全局异常处理器
  （统一返回 `{code,message,detail?}` 信封，见 `schemas/common.py`）。
- Task 6：lifespan 启动时执行 `seed_all`（管理员必 seed；演示数据由 `SEED_DEMO`
  控制，默认 false 不灌入，见 `core/seed.py`）；MySQL 不可达时仅告警不阻塞启动。
- Task 13：lifespan 启动 `executor.start()`（后台 DB 轮询执行器，处理对齐等异步 Job）、
  关闭 `executor.stop()`（见 `app/jobs/`）。

异常错误码映射：
- `RequestValidationError` → `err(42200, "参数校验失败", status=422)`
- `HTTPException` → 401→40100 / 403→40300 / 404→40400 / 409→40900，其余→50000
  （`status_code` 仅 401/403/404/409 原样回写，其他一律 500）
- 兜底 `Exception` → 500 `err(50000, "服务内部错误")`（loguru 记 traceback）
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.gzip import GZipMiddleware
from loguru import logger
from sqlmodel import Session

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.db import engine
from app.core.logging import AccessLogMiddleware, setup_logging
from app.core.seed import seed_all
from app.jobs import executor
from app.schemas.common import err, ok

setup_logging()

if settings.secret_key in ("change-me", "") or settings.admin_password in ("admin123", ""):
    logger.warning(
        "检测到弱默认凭据：SECRET_KEY 或 ADMIN_PASSWORD 仍为默认值，生产环境务必在 .env 中修改"
    )

@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时 seed + 启动 Job 执行器；关闭时停止执行器。

    1. seed（管理员 + 按 `SEED_DEMO` 决定是否灌演示数据，幂等）：MySQL 不可达时仅
       `logger.warning` 后跳过，避免启动直接崩溃（本地演示可容忍）。
    2. `executor.start()`：后台线程每 ~1s 轮询 pending 的 Job 并 dispatch 到对应 handler
       （Task 13，见 `app/jobs/executor.py`）。
    """
    try:
        with Session(engine) as session:
            seed_all(session, demo=settings.seed_demo)
        if settings.seed_demo:
            logger.info("启动 seed 完成：管理员 + 演示数据已就绪")
        else:
            logger.info("启动 seed 完成：仅管理员（SEED_DEMO=false，未灌演示数据）")
    except Exception:  # noqa: BLE001 - 启动期数据库不可达不应阻塞服务启动
        logger.opt(exception=True).warning(
            "启动 seed 失败（数据库不可达？），跳过 seed，服务继续启动"
        )
    executor.start()
    logger.info("Job 执行器已启动（后台 DB 轮询）")
    try:
        yield
    finally:
        executor.stop()
        logger.info("Job 执行器已停止")


app = FastAPI(title="AI Welding Platform API", version="0.1.0", lifespan=lifespan)
# gzip：波形/信号类 JSON 大响应压缩比 3~5x（配合 /signals max_points 服务端抽稀，
# 公网低带宽下首屏从 ~26MB 降到 ~几十 KB）。
app.add_middleware(GZipMiddleware, minimum_size=2048)
app.add_middleware(AccessLogMiddleware)


@app.get("/api/v1/health")
def health() -> dict:
    """健康检查（统一信封）。"""
    return ok({"status": "ok"})


app.include_router(api_router, prefix="/api/v1")

# In the production image, FastAPI serves the Vite build alongside the API.
# Keep this conditional so local backend-only tests and development remain valid.
frontend_dir = Path(__file__).resolve().parents[1] / "dist"
if frontend_dir.is_dir():
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")


def register_exception_handlers(app: FastAPI) -> None:
    """注册全局异常处理器：所有错误统一返回 `{code,message,detail?}` 信封。"""

    @app.exception_handler(RequestValidationError)
    async def _validation_error(
        request: Request, exc: RequestValidationError
    ) -> object:
        return err(42200, "参数校验失败", detail=exc.errors(), status=422)

    @app.exception_handler(HTTPException)
    async def _http_error(request: Request, exc: HTTPException) -> object:
        mapping = {
            401: (40100, "未登录或令牌失效"),
            403: (40300, "无权限"),
            404: (40400, "资源不存在"),
            409: (40900, "冲突"),
        }
        code, message = mapping.get(exc.status_code, (50000, "服务内部错误"))
        status = exc.status_code if exc.status_code in mapping else 500
        detail = exc.detail if exc.detail is not None else None
        return err(code, message, detail=detail, status=status)

    @app.exception_handler(Exception)
    async def _unhandled_error(request: Request, exc: Exception) -> object:
        logger.exception("Unhandled exception: {}", exc)
        return err(50000, "服务内部错误", status=500)


register_exception_handlers(app)
