from fastapi import FastAPI

from app.core.logging import AccessLogMiddleware, setup_logging

setup_logging()

app = FastAPI(title="AI Welding Platform API", version="0.1.0")
app.add_middleware(AccessLogMiddleware)


@app.get("/api/v1/health")
def health() -> dict:
    """健康检查（统一信封，Task 1 直挂，路由聚合见 Task 3）。"""
    return {"code": 0, "message": "ok", "data": {"status": "ok"}}
