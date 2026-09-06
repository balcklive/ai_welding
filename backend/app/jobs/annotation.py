"""annotation job handler（Task 14）：标注任务创建。

编排为真实异步：Job 状态/进度/结果回填为真。`label_studio_mode=on` 时进入 LS 集成——
把样本推 LS、置「LS 等待」态、由回写/对账驱动完成（决策 2，不跑 simulate_annotation）；
`off` / LS 不可达则回退旧模拟路径 `app.services.annotation.simulate_annotation`。AI 预标注 /
标注保存是同步端点，不经 handler。
"""

from sqlmodel import Session, select

from app.core.config import settings
from app.jobs.executor import register_handler
from app.models.analysis import AnnotationTask
from app.models.jobs import Job
from app.services import annotation as svc
from app.services import annotation_ls as ls_svc


@register_handler("annotation")
def handle(job_id: int, session: Session) -> None:
    """标注任务创建：LS 模式走推流等待态；否则回退模拟路径。

    由执行器在独立 `Session`（`SessionLocal`）内调用；失败时执行器兜底 `mark_failed`。
    """
    task = session.exec(
        select(AnnotationTask).where(AnnotationTask.job_id == job_id)
    ).first()
    if task is None:
        raise ValueError(f"Annotation task does not exist: job_id={job_id}")
    job = session.get(Job, job_id)
    if job is None:
        raise ValueError(f"Job does not exist: id={job_id}")
    if settings.label_studio_mode == "on" and ls_svc.prepare_ls_task(session, task):
        session.commit()  # 持久「LS 等待」态与映射，立即对账/轮询可见
        return
    svc.simulate_annotation(session, task, job)
