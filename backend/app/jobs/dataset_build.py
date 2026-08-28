"""dataset_build job handler（Task 15）：数据集构建（真实异步编排 + 模拟结果）。

编排为真实异步：Job 状态/进度/结果回填、`dataset_items` 固定清单、`quality` 计算、
快照写 MinIO 均为真；样本来源不足时由服务兜底生成确定性合成样本（`docs/开发规范.md` §3.1）。
领域逻辑在 `app.services.datasets.run_build`，本模块只做 handler 薄封装并注册到执行器
注册表（`@register_handler("dataset_build")`）。
"""

from sqlmodel import Session, select

from app.jobs.executor import register_handler
from app.models.datasets import DatasetBuildTask
from app.models.jobs import Job
from app.services import datasets as svc


@register_handler("dataset_build")
def handle(job_id: int, session: Session) -> None:
    """数据集构建：按来源 gather 候选样本 → 按焊缝分组 8:1:1 划分 → 落固定清单 → 计算质量。

    由执行器在独立 `Session`（`SessionLocal`）内调用；失败时执行器兜底 `mark_failed`。
    完整来源（type + 各 id）由创建时随 Job.result 携带（`dataset_build_tasks.source` 仅
    存类型字符串，契约 §3.22）。
    """
    task = session.exec(
        select(DatasetBuildTask).where(DatasetBuildTask.job_id == job_id)
    ).first()
    if task is None:
        raise ValueError(f"Dataset build task does not exist: job_id={job_id}")
    job = session.get(Job, job_id)
    if job is None:
        raise ValueError(f"Job does not exist: id={job_id}")
    svc.run_build(session, task, job)
