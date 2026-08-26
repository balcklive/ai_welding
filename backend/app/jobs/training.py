"""training job handler（Task 16）：模型训练（模拟）。

编排为真实异步：Job 状态/进度/结果回填与训练成功自动生成 `model_versions`
（status=实验版本）+ 权重写 MinIO `models/{model_version_id}/weights.pt` 为真，
计算内核为演示（指标收敛/损失曲线模拟，`docs/开发规范.md` §3.1）。
领域逻辑在 `app.services.models.run_training`，本模块只做 handler 薄封装并注册到
执行器注册表（`@register_handler("training")`）。
"""

from sqlmodel import Session, select

from app.jobs.executor import register_handler
from app.models.jobs import Job
from app.models.models import TrainingTask
from app.services import models as svc


@register_handler("training")
def handle(job_id: int, session: Session) -> None:
    """模拟训练：进度 → 指标/损失曲线 → 事务内生成 model_version + 权重写 MinIO。

    由执行器在独立 `Session`（`SessionLocal`）内调用；失败时执行器兜底 `mark_failed`。
    """
    task = session.exec(
        select(TrainingTask).where(TrainingTask.job_id == job_id)
    ).first()
    if task is None:
        raise ValueError(f"训练任务不存在: job_id={job_id}")
    job = session.get(Job, job_id)
    if job is None:
        raise ValueError(f"Job 不存在: id={job_id}")
    svc.run_training(session, task, job)
