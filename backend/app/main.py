"""FastAPI 应用入口。

- Task 1：日志中间件（`AccessLogMiddleware`）+ 健康检查。
- Task 3：挂载 v1 路由聚合（`/api/v1` 前缀在此添加）+ 全局异常处理器
  （统一返回 `{code,message,detail?}` 信封，见 `schemas/common.py`）。
- 启动时仅初始化管理员和系统标签字典；业务数据必须通过正式流程进入。
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
from app.core.health import readiness_report
from app.core.logging import AccessLogMiddleware, setup_logging
from app.core.seed import seed_all
from app.jobs import executor
from app.schemas.common import err, ok

setup_logging()

if settings.secret_key in ("change-me", "") or settings.admin_password in ("admin123", ""):
    logger.warning(
        "Weak default credentials detected: SECRET_KEY or ADMIN_PASSWORD is still using a default value; change it in .env before production"
    )

@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时 seed + 启动 Job 执行器；关闭时停止执行器。

    1. seed（仅管理员和系统标签字典，幂等）：失败直接中止启动，避免伪健康。
    2. `executor.start()`：启用时由后台线程每 ~1s 轮询 pending 的 Job 并 dispatch 到
       对应 handler；候选部署容器通过配置禁用（见 `app/jobs/executor.py`）。
    """
    # 数据库不可达或 schema 不完整时必须阻止服务进入可用状态；生产镜像会在此之前
    # 执行 Alembic，直接本地启动时也不再静默伪装成健康服务。
    with Session(engine) as session:
        seed_all(session)
    logger.info("Startup initialization completed")
    if settings.job_executor_enabled:
        executor.start()
        logger.info("Job executor started (background database polling)")
    else:
        logger.info("Job executor disabled for this process")
    try:
        yield
    finally:
        if settings.job_executor_enabled:
            executor.stop()
            logger.info("Job executor stopped")


app = FastAPI(title="AI Welding Platform API", version="0.1.0", lifespan=lifespan)
# gzip：波形/信号类 JSON 大响应压缩比 3~5x（配合 /signals max_points 服务端抽稀，
# 公网低带宽下首屏从 ~26MB 降到 ~几十 KB）。
app.add_middleware(GZipMiddleware, minimum_size=2048)
app.add_middleware(AccessLogMiddleware)


@app.get("/api/v1/health")
def health() -> dict:
    """兼容旧监控的存活检查；部署门禁必须使用 `/health/ready`。"""
    return ok({"status": "ok"})


@app.get("/api/v1/health/live")
def health_live() -> dict:
    """Liveness：进程能够响应 HTTP 即为存活，不检查外部依赖。"""
    return ok({"status": "live"})


@app.get("/api/v1/health/ready")
def health_ready() -> object:
    """Readiness：数据库、迁移、关键表和 MinIO 全部可用才返回 200。"""
    ready, checks = readiness_report()
    if not ready:
        return err(
            50300,
            "服务未就绪",
            detail={"status": "not_ready", "checks": checks},
            status=503,
        )
    return ok({"status": "ready", "checks": checks})


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

    @app.exception_handler(ValueError)
    async def _business_value_error(request: Request, exc: ValueError) -> object:
        return err(40000, str(exc), status=400)

    @app.exception_handler(Exception)
    async def _unhandled_error(request: Request, exc: Exception) -> object:
        logger.exception("Unhandled exception: {}", exc)
        return err(50000, "服务内部错误", status=500)


register_exception_handlers(app)
