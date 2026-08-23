"""通用 Job 服务（Task 7）：统一异步任务生命周期（§1.5 / §3.6）。

状态机：pending → running → succeeded | failed。
- `create_job` / `mark_running` / `mark_succeeded` / `mark_failed` **只 add + flush，
  不 commit**——由调用方（路由/执行器）统一 commit，保证与业务变更同事务。
- `to_job_payload` 输出 §1.5 的 Job JSON（id=job_uid，时间为 ISO-8601 UTC 字符串）。
"""

from datetime import datetime, timezone
from uuid import uuid4

from sqlmodel import Session, select

from app.models.jobs import Job


def create_job(session: Session, type: str, result: dict | None = None) -> Job:
    """新建 pending 状态 Job。`job_uid=f"job_{uuid4().hex[:8]}"`，progress=0，
    created_at=UTC now（timezone-aware）。add + flush 后返回；**不 commit**。"""
    job = Job(
        job_uid=f"job_{uuid4().hex[:8]}",
        type=type,
        status="pending",
        progress=0,
        result=result,
        created_at=datetime.now(timezone.utc),
    )
    session.add(job)
    session.flush()
    return job


def get_job_by_uid(session: Session, uid: str) -> Job | None:
    """按 job_uid 查 Job；不存在返回 None。"""
    return session.exec(select(Job).where(Job.job_uid == uid)).first()


def mark_running(session: Session, job: Job) -> None:
    """pending → running。清空 finished_at（兼容重跑场景）。调用方 commit。"""
    job.status = "running"
    job.finished_at = None


def mark_succeeded(session: Session, job: Job, result: dict | None) -> None:
    """running → succeeded。progress 置 100，写入 result 与 finished_at。调用方 commit。"""
    job.status = "succeeded"
    job.progress = 100
    job.result = result
    job.finished_at = datetime.now(timezone.utc)


def mark_failed(session: Session, job: Job, error: dict | None) -> None:
    """running → failed。写入 error 与 finished_at（progress 保留失败时进度）。调用方 commit。"""
    job.status = "failed"
    job.error = error
    job.finished_at = datetime.now(timezone.utc)


def to_job_payload(job: Job) -> dict:
    """输出 §1.5 的 Job JSON：{id, type, status, progress, result, error, created_at, finished_at}。

    id = job_uid；时间为 ISO-8601 UTC 字符串（`2026-08-23T09:42:00Z`，秒级）。
    result/error 原样透传（None 或 dict），保持 JSON 安全。
    """
    return {
        "id": job.job_uid,
        "type": job.type,
        "status": job.status,
        "progress": job.progress,
        "result": job.result,
        "error": job.error,
        "created_at": _iso_utc(job.created_at),
        "finished_at": _iso_utc(job.finished_at),
    }


def _iso_utc(dt: datetime | None) -> str | None:
    """datetime → ISO-8601 UTC 字符串（秒级 `2026-08-23T09:42:00Z`）；None 透传。

    服务写入的一律是 UTC aware 时间，但 SQLite / MySQL `DATETIME(timezone=True)` 读回时
    会剥离 tzinfo（变成 naive）。naive 值即 UTC，故先补上 UTC tzinfo 再 `astimezone`，
    否则 `astimezone` 会把 naive 当系统本地时区换算，在非 UTC 主机上产生时间偏移。
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (
        dt.astimezone(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
