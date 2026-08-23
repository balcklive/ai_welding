"""Job 执行器（Task 13）：DB 轮询 + 每域 handler 注册表。

- `HANDLERS`: `dict[job type → (job_id:int, session:Session) -> None]`，各域 handler 在
  `app/jobs/*.py` 里用 `@register_handler("type")` 注册（本包 `__init__.py` 导入即完成注册）。
- `start()` / `stop()`：后台 daemon 线程，每 ~1s 轮询 `pending` 的 job（默认批 5），
  **原子领单** = 对每个候选发条件 UPDATE `WHERE id AND status='pending'`（`rowcount==1`
  才算领到），再跑 handler——并发/多执行者不会重复领同一 job。
- `run_job(job_uid)`：**同步**入口（测试/手动），不启动线程；同样原子领单，领不到即跳过。

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
from sqlalchemy import update
from sqlmodel import Session, select

from app.core.db import SessionLocal
from app.models.jobs import Job
from app.services.jobs import get_job_by_uid, mark_failed

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
    """原子领单：仅把**仍为 pending** 的 job 置 running，返回真正领到的 job 列表。

    并发/多执行者下不能靠「SELECT pending → 内存 mark_running → commit」（会重复领同一
    job）。这里对每个候选走一条条件 UPDATE `WHERE id AND status='pending'`，靠数据库行级
    原子性：`rowcount == 1` 才算领到，否则（已被别的执行者领走/非 pending）跳过。
    """
    candidates = list(
        session.exec(select(Job).where(Job.status == "pending").limit(_BATCH_SIZE)).all()
    )
    claimed: list[Job] = []
    for job in candidates:
        result = session.exec(
            update(Job)
            .where(Job.id == job.id, Job.status == "pending")
            .values(status="running", finished_at=None)
        )
        if result.rowcount == 1:
            claimed.append(job)
    if claimed:
        session.commit()
    return claimed


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
    """同步执行一个 job（测试/手动）：**原子领单**(running+commit) → handler。不启动线程。

    全程用**一个**独立 Session（`SessionLocal`）。领单用条件 UPDATE（仅当仍为 pending，
    `rowcount == 1`），并发下已被别的执行者领走 → 跳过（不重复执行）。失败 → `mark_failed`
    + commit。
    """
    session = SessionLocal()
    try:
        job = get_job_by_uid(session, job_uid)
        if job is None:
            logger.warning("run_job 未知 job_uid: {}", job_uid)
            return
        result = session.exec(
            update(Job)
            .where(Job.id == job.id, Job.status == "pending")
            .values(status="running", finished_at=None)
        )
        session.commit()  # 领单先落库
        if result.rowcount != 1:
            logger.info("run_job 跳过 job {}（已被执行或非 pending）", job_uid)
            return
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
    """后台轮询线程：每 ~1s 领 pending job 并 dispatch 到对应 handler。

    线程生命周期防双轮询（review 发现并修复）：
    - `stop()` 只在确认线程真正退出（join 返回且 `is_alive()` False）后丢弃引用；超时仍存活
      （handler 长跑）则保留引用。
    - `start()` 若上一线程仍存活则**拒绝重复启动**（no-op + 告警）；仅在确认旧线程已死后才
      清 `_stop`——否则存活的旧线程会观察到 `_stop` 被清空而继续轮询，造成两个执行者。
    """

    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        # (a) 上一线程还在跑（stop() 超时未退出）时不重复启动——避免双执行者并发领单。
        if self._thread is not None and self._thread.is_alive():
            logger.warning("Job 执行器线程仍在运行，忽略重复 start()")
            return
        # (c) 只有确认旧线程已死（或从未启动）才清 _stop：还存活的旧线程若观察到 _stop 被
        #     清空会继续轮询 → 双执行者。is_alive() 为 False 即线程已结束，不可能再观察。
        self._thread = None
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="job-executor", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=2 * _POLL_INTERVAL)
            # (b) 只在确认线程真正退出后才丢弃引用；超时仍存活则保留，start() 会拒绝二次启动。
            if thread.is_alive():
                logger.warning(
                    "Job 执行器线程未在 {}s 内退出（handler 可能仍在跑），保留引用待其自然退出",
                    2 * _POLL_INTERVAL,
                )
            else:
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
                try:
                    _execute_claimed(job.id)
                except Exception:  # noqa: BLE001 - 单 job 兜底异常不阻断轮询
                    logger.opt(exception=True).exception(
                        "job(id={}) 执行兜底异常", job.id
                    )
            self._stop.wait(_POLL_INTERVAL)


_executor = _ExecutorThread()


def start() -> None:
    """启动后台轮询线程（FastAPI lifespan 启动时调用）。"""
    _executor.start()


def stop() -> None:
    """停止后台轮询线程（FastAPI lifespan 关闭时调用）。"""
    _executor.stop()
