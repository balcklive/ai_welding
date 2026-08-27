"""alignment job handler（Task 13，真实化内核）：多模态对齐。

编排为真实异步，计算内核同样真实：事件来自真实信号（detect_events / 生成回退如实标注）、
视频经 ffmpeg 探测元数据并抽关键帧、产物为真实 CSV/JPG/tracks.json（部分成功语义，
缺失模态转 unavailable + reason）。领域逻辑在 `app.services.alignment.run_alignment`，
本模块只做 handler 薄封装并注册到执行器注册表（`@register_handler("alignment")`）。
"""

from sqlmodel import Session, select

from app.jobs.executor import register_handler
from app.models.analysis import AlignmentTask
from app.models.jobs import Job
from app.services import alignment as svc


@register_handler("alignment")
def handle(job_id: int, session: Session) -> None:
    """多模态对齐：真实内核（信号/事件/视频探测/产物）→ 自动生成「时间对齐」版本 →
    回填 task 域字段与 job.result。

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
    svc.run_alignment(session, task, job)
