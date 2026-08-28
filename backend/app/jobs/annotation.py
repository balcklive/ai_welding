"""annotation job handler（Task 14）：标注任务创建（模拟）。

编排为真实异步：Job 状态/进度/结果回填为真，计算内核为演示（`docs/开发规范.md` §3.1）。
领域逻辑在 `app.services.annotation.simulate_annotation`，本模块只做 handler 薄封装并注册
到执行器注册表（`@register_handler("annotation")`）。成功时（来源为 split_task）把该切分
任务的样本 `annotation_task_id` 指向本任务；AI 预标注 / 标注保存是同步端点，不经 handler。
"""

from sqlmodel import Session, select

from app.jobs.executor import register_handler
from app.models.analysis import AnnotationTask
from app.models.jobs import Job
from app.services import annotation as svc


@register_handler("annotation")
def handle(job_id: int, session: Session) -> None:
    """标注任务创建（模拟）：把来源样本归属到本任务。

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
    svc.simulate_annotation(session, task, job)
