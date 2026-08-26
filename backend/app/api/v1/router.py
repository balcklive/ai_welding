"""v1 路由聚合（Task 3）。

各域 router 自身**不带前缀**，`/api/v1` 前缀统一由 `main.py` 挂载时添加。
后续任务在各自的域模块里补路由即可，本文件只在新增域时追加 `include_router`。
"""

from fastapi import APIRouter

from app.api.v1 import (
    analysis,
    auth,
    dashboard,
    datasets,
    files,
    jobs,
    models,
    reports,
    welds,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(dashboard.router)
api_router.include_router(welds.router)
api_router.include_router(analysis.router)
api_router.include_router(datasets.router)
api_router.include_router(models.router)
api_router.include_router(files.router)
api_router.include_router(jobs.router)
api_router.include_router(reports.router)
