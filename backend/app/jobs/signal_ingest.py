"""signal_ingest job handler（Task 18）：CSV 真实信号导入。

挂载 `raw-files` 含 `.csv` 对象键时自动建此 Job（见 `app/api/v1/welds.py`）。
领域逻辑在 `app.services.signal_ingest.run_ingest`：下载 CSV → 10 条校验 → 启发式
事件检测 → 写 MinIO Parquet → 回填 `signal_ingests` 行与 job.result。

**关键差异**：`run_ingest` 内部**自捕获异常**并把 `signal_ingests.status` 置 failed 后
正常返回——executor 的 failed 兜底会先 `rollback` 丢弃 handler 写过的行状态，故不能
像 alignment/split 那样把业务异常重抛给执行器。
"""

from sqlmodel import Session, select

from app.jobs.executor import register_handler
from app.models.analysis import SignalIngest
from app.models.jobs import Job
from app.services import signal_ingest as svc


@register_handler("signal_ingest")
def handle(job_id: int, session: Session) -> None:
    """按 job 查 `signal_ingests` 行并执行导入（校验/启发式/Parquet）。

    由执行器在独立 `Session`（`SessionLocal`）内调用；任务行不存在则抛错走执行器
    failed 兜底（此时无行状态可写，与 run_ingest 自捕获的场景不冲突）。
    """
    ingest = session.exec(
        select(SignalIngest).where(SignalIngest.job_id == job_id)
    ).first()
    if ingest is None:
        raise ValueError(f"signal_ingest task does not exist: job_id={job_id}")
    job = session.get(Job, job_id)
    if job is None:
        raise ValueError(f"Job does not exist: id={job_id}")
    svc.run_ingest(session, ingest, job)
