"""Job 执行器（Task 13）：DB 轮询 + 每域 handler 注册表。

- `HANDLERS`: `dict[job type → (job_id:int, session:Session) -> None]`，各域 handler 在
  `app/jobs/*.py` 里用 `@register_handler("type")` 注册（本包 `__init__.py` 导入即完成注册）。
- `start()` / `stop()`：后台 daemon 线程，每 ~1s 轮询 `pending` 的 job（默认批 5），
  领单语义 = 先 `mark_running` + `commit`（让轮询不重复领）再跑 handler。
- `run_job(job_uid)`：**同步**入口（测试/手动），不启动线程。

Handler 约定（坑，改动勿破坏）：
- 每个 handler 拿到**独立 `Session`**（`SessionLocal`，`expire_on_commit=False`），自行
  commit 终态（进度逐步 commit 让轮询可见）。它是执行器专用 session，**不是**请求 session。
- 失败兜底：executor 捕获任意 `Exception` → loguru 记 traceback → `mark_failed(job, {"message": str(e)})`
  + commit，**绝不把 job 卡在 running**。
- 未注册 type → `ValueError`，同样走 failed 兜底。
"""

from __future__ import annotations

import threading
from typing import Callable

from loguru import logger
from sqlmodel import Session, select

from app.core.db import SessionLocal
from app.models.jobs import Job
from app.services.jobs import get_job_by_uid, mark_failed, mark_running

#: job type → handler(job_id, session)。各域模块 import 时用 `@register_handler` 填充。
HANDLERS: dict[str, Callable[[int, Session], None]] = {}

#: 轮询间隔（秒）。轮询线程仅在 lifespan 启动；测试直接用 `run_job` 同步执行。
_POLL_INTERVAL = 1.0
#: 每轮最多领单数（领单 = running + commit 后再跑，避免重复领取）。
_BATCH_SIZE = 5


def register_handler(job_type: str) -> Callable:
    """注册一个 job handler 到全局注册表（作为装饰器使用）。"""

    def decorator(fn: Callable[[int, Session], None]) -> Callable[[int, Session], None]:
        HANDLERS[job_type] = fn
        return fn

    return decorator


def _claim_pending(session: Session) -> list[Job]:
    """领 `pending` job（`mark_running` + commit），返回已领单列表。"""
    jobs = list(
        session.exec(select(Job).where(Job.status == "pending").limit(_BATCH_SIZE)).all()
    )
    for job in jobs:
        mark_running(session, job)
    if jobs:
        session.commit()
    return jobs


def _dispatch(session: Session, job_id: int) -> None:
    """在给定 session 里对已领单（running）的 job 跑 handler 并 commit 终态。

    handler 自行 commit（进度/结果都在 session 内）；这里再兜底 commit 一次。
    抛出的任何异常由调用方统一转 failed。
    """
    fresh = session.get(Job, job_id)
    if fresh is None or fresh.status != "running":
        return
    handler = HANDLERS.get(fresh.type)
    if handler is None:
        raise ValueError(f"未注册的 job type: {fresh.type!r}")
    handler(fresh.id, session)
    session.commit()


def _mark_failed_in(session: Session, job_id: int, message: str) -> None:
    """把 job 置 failed（独立事务）。事务脏则先 rollback 再写，避免卡 running。"""
    session.rollback()
    failed = session.get(Job, job_id)
    if failed is not None:
        mark_failed(session, failed, {"message": message})
        session.commit()


def run_job(job_uid: str) -> None:
    """同步执行一个 job（测试/手动）：领单(running+commit) → handler。不启动线程。

    全程用**一个**独立 Session（`SessionLocal`）。失败 → `mark_failed` + commit。
    """
    session = SessionLocal()
    try:
        job = get_job_by_uid(session, job_uid)
        if job is None:
            logger.warning("run_job 未知 job_uid: {}", job_uid)
            return
        mark_running(session, job)
        session.commit()  # 领单先落库，轮询/并发不重复领取
        try:
            _dispatch(session, job.id)
        except Exception as exc:  # noqa: BLE001 - 执行器兜底，任何异常都写 failed
            logger.opt(exception=True).error(
                "job({}) 执行失败: {}", job_uid, exc
            )
            _mark_failed_in(session, job.id, str(exc))
    finally:
        session.close()


def _execute_claimed(job_id: int) -> None:
    """对已领单（running）的 job 开独立 Session 跑 handler；失败 → failed。

    失败回写本身再失败（如数据库不可写）只记日志，不让轮询线程炸掉。
    """
    session = SessionLocal()
    try:
        try:
            _dispatch(session, job_id)
        except Exception as exc:  # noqa: BLE001
            logger.opt(exception=True).error(
                "job(id={}) 执行失败: {}", job_id, exc
            )
            try:
                _mark_failed_in(session, job_id, str(exc))
            except Exception:  # noqa: BLE001 - 回写 failed 失败仅告警，不阻断线程
                session.rollback()
                logger.exception("回写 failed 状态失败: job(id={})", job_id)
    finally:
        session.close()


class _ExecutorThread:
    """后台轮询线程：每 ~1s 领 pending job 并 dispatch 到对应 handler。"""

    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="job-executor", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2 * _POLL_INTERVAL)
            self._thread = None

    def _loop(self) -> None:
        while not self._stop.is_set():
            claimed: list[Job] = []
            try:
                with SessionLocal() as session:
                    claimed = _claim_pending(session)
            except Exception:  # noqa: BLE001 - 轮询异常不退出线程，下轮再试
                logger.opt(exception=True).warning("job 轮询异常，跳过本轮")
            for job in claimed:
                _execute_claimed(job.id)
            self._stop.wait(_POLL_INTERVAL)


_executor = _ExecutorThread()


def start() -> None:
    """启动后台轮询线程（FastAPI lifespan 启动时调用）。"""
    _executor.start()


def stop() -> None:
    """停止后台轮询线程（FastAPI lifespan 关闭时调用）。"""
    _executor.stop()
