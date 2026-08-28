"""inference job handler（Task 16）：模型推理（模拟）。

编排为真实异步：Job 状态/进度/结果回填与 `inference_tasks.result` 落库为真，
计算内核为演示（确定性预测框/类别/置信度/耗时，`docs/开发规范.md` §3.1）。
领域逻辑在 `app.services.models.run_inference`，本模块只做 handler 薄封装并注册到
执行器注册表（`@register_handler("inference")`）。
"""

from sqlmodel import Session, select

from app.jobs.executor import register_handler
from app.models.jobs import Job
from app.models.models import InferenceTask
from app.services import models as svc


@register_handler("inference")
def handle(job_id: int, session: Session) -> None:
    """模拟推理：进度 → boxes/categories/confidence/latency → 回填 task 与 job.result。

    由执行器在独立 `Session`（`SessionLocal`）内调用；失败时执行器兜底 `mark_failed`。
    """
    task = session.exec(
        select(InferenceTask).where(InferenceTask.job_id == job_id)
    ).first()
    if task is None:
        raise ValueError(f"Inference task does not exist: job_id={job_id}")
    job = session.get(Job, job_id)
    if job is None:
        raise ValueError(f"Job does not exist: id={job_id}")
    svc.run_inference(session, task, job)
