"""应用存活与就绪检查。

Liveness 只由 Web 进程本身回答；readiness 必须确认数据库可连接、数据库迁移处于
当前 Alembic head，并且关键表与 MinIO 目标桶可访问。对外只暴露检查项状态，具体
异常写日志，避免连接信息或凭据泄漏到响应中。
"""

from functools import lru_cache
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from loguru import logger
from sqlalchemy import inspect, text

from app.core.db import engine
from app.storage import get_storage

_REQUIRED_TABLES = {"users", "jobs", "data_records"}


@lru_cache(maxsize=1)
def expected_database_revision() -> str:
    """读取随应用发布的唯一 Alembic head。"""
    backend_dir = Path(__file__).resolve().parents[2]
    config = Config(str(backend_dir / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    head = scripts.get_current_head()
    if not head:
        raise RuntimeError("Alembic head is not defined")
    return head


def check_database() -> dict[str, str]:
    """确认数据库连接、迁移版本和关键表均可用。"""
    expected = expected_database_revision()
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
        current = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one_or_none()
        if current != expected:
            raise RuntimeError(
                f"Database revision mismatch: current={current!r}, expected={expected!r}"
            )
        tables = set(inspect(connection).get_table_names())
        missing = sorted(_REQUIRED_TABLES - tables)
        if missing:
            raise RuntimeError(f"Required database tables are missing: {missing}")
    return {"status": "ok", "revision": expected}


def check_object_storage() -> dict[str, str]:
    """确认 MinIO 服务与目标桶可访问。"""
    storage = get_storage()
    storage.check_ready()
    return {"status": "ok", "bucket": storage.bucket}


def readiness_report() -> tuple[bool, dict[str, dict[str, str]]]:
    """执行全部依赖检查；失败详情只记日志，响应仅返回检查项状态。"""
    checks: dict[str, dict[str, str]] = {}
    ready = True
    for name, check in (
        ("database", check_database),
        ("object_storage", check_object_storage),
    ):
        try:
            checks[name] = check()
        except Exception as exc:  # noqa: BLE001 - readiness 需要聚合所有检查结果
            ready = False
            checks[name] = {"status": "failed"}
            logger.opt(exception=True).warning("Readiness check failed ({}): {}", name, exc)
    return ready, checks
