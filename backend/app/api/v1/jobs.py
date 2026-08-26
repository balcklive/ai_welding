"""jobs 域路由（Task 7 实现）：通用任务状态轮询端点。

`GET /jobs/{job_id}`（job_id = job_uid，`/api/v1` 前缀由 main.py 统一添加）→
§1.5 Job JSON；不存在 → `err(40401, "任务不存在", status=404)`。需登录。
"""

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.api.deps import get_current_user
from app.core.db import get_session
from app.models.data import User
from app.schemas.common import err, ok
from app.services.jobs import get_job_by_uid, to_job_payload

router = APIRouter()


@router.get("/jobs/{job_id}")
def get_job(
    job_id: str,
    session: Session = Depends(get_session),
    _: User = Depends(get_current_user),
) -> object:
    """通用任务状态轮询（对齐/切分/训练/测试/数据集构建共用）。

    返回 §1.5 统一 Job 结构：{id, type, status, progress, result, error,
    created_at, finished_at}。job 不存在 → 404 `err(40401, "任务不存在")`。
    """
    job = get_job_by_uid(session, job_id)
    if job is None:
        return err(40401, "任务不存在", status=404)
    return ok(to_job_payload(job))
