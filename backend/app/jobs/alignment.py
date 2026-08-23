"""alignment job handler（Task 13）：多模态对齐（模拟）。

编排为真实异步：Job 状态/进度/结果回填与 MinIO 产物对象键为真，计算内核为演示
（`docs/开发规范.md` §3.1）。领域逻辑在 `app.services.alignment.simulate_alignment`，
本模块只做 handler 薄封装并注册到执行器注册表（`@register_handler("alignment")`）。
"""

from sqlmodel import Session, select

from app.jobs.executor import register_handler
from app.models.analysis import AlignmentTask
from app.models.jobs import Job
from app.services import alignment as svc


@register_handler("alignment")
def handle(job_id: int, session: Session) -> None:
    """多模态对齐：模拟进度 → 自动生成「时间对齐」版本 → 回填 task 域字段与 job.result。

    由执行器在独立 `Session`（`SessionLocal`）内调用；失败时执行器兜底 `mark_failed`。
    """
    task = session.exec(
        select(AlignmentTask).where(AlignmentTask.job_id == job_id)
    ).first()
    if task is None:
        raise ValueError(f"对齐任务不存在: job_id={job_id}")
    job = session.get(Job, job_id)
    if job is None:
        raise ValueError(f"Job 不存在: id={job_id}")
    svc.simulate_alignment(session, task, job)
