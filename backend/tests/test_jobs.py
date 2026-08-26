"""Task 7：通用 Job 服务 + GET /jobs/{job_id} 轮询端点。

内存 SQLite + StaticPool + 真实 app 的 TestClient（同 test_auth.py）。依赖覆盖：
- `get_session` → 测试 session（同一连接跨线程，StaticPool）
- `get_current_user` → 直接返回假 User（免 seed/签发 token）

覆盖：create_job（job_uid 前缀 / pending / created_at / 不 commit）、状态机
流转（running / succeeded / failed + finished_at）、to_job_payload 形状、
GET 200 信封 / 未知 uid 404 / 未登录 401。
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel

from app.api.deps import get_current_user
from app.core.db import get_session
from app.main import app
from app.models import User
from app.services.jobs import (
    create_job,
    get_job_by_uid,
    mark_failed,
    mark_running,
    mark_succeeded,
    to_job_payload,
)

client = TestClient(app)


@pytest.fixture()
def db_session():
    """内存 SQLite + StaticPool：每用例全新引擎（环形 FK 不便 drop_all）。"""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


@pytest.fixture()
def override_get_session(db_session):
    def _override():
        yield db_session

    app.dependency_overrides[get_session] = _override
    yield
    app.dependency_overrides.pop(get_session, None)


@pytest.fixture()
def override_get_current_user():
    """假登录：get_current_user 直接返回一个 User，免 seed / 免签 token。"""
    dummy = User(
        id=1,
        username="lin_eng",
        password_hash="not-a-real-hash",
        display_name="林工",
        role="admin",
    )

    def _override() -> User:
        return dummy

    app.dependency_overrides[get_current_user] = _override
    yield
    app.dependency_overrides.pop(get_current_user, None)


# ---------- 服务层：create_job ----------


def test_create_job_uid_prefix_and_pending(db_session) -> None:
    job = create_job(db_session, type="training")
    assert job.job_uid.startswith("job_")
    assert len(job.job_uid) == len("job_") + 8
    assert job.status == "pending"
    assert job.progress == 0
    assert job.result is None
    assert job.error is None
    # created_at 是 timezone-aware 的 UTC 时间
    assert job.created_at is not None
    assert job.created_at.tzinfo is not None


def test_create_job_does_not_commit(db_session) -> None:
    """服务只 flush 不 commit：rollback 后 insert 被丢弃（落库由调用方 commit 负责）。"""
    job = create_job(db_session, type="training")
    uid = job.job_uid
    db_session.rollback()
    # rollback 后该行未提交即被回滚，重新查询查不到
    assert get_job_by_uid(db_session, uid) is None


def test_create_job_flush_assigns_id_and_result(db_session) -> None:
    job = create_job(db_session, type="alignment", result={"source": "weld_1"})
    assert job.id is not None
    assert job.result == {"source": "weld_1"}


# ---------- 服务层：状态机 ----------


def test_mark_running_sets_status(db_session) -> None:
    job = create_job(db_session, type="training")
    mark_running(db_session, job)
    assert job.status == "running"
    assert job.finished_at is None


def test_mark_succeeded_sets_result_and_finished_at(db_session) -> None:
    job = create_job(db_session, type="training")
    mark_running(db_session, job)
    mark_succeeded(db_session, job, {"metric": 0.95})
    assert job.status == "succeeded"
    assert job.progress == 100
    assert job.result == {"metric": 0.95}
    assert job.error is None
    assert job.finished_at is not None
    assert job.finished_at.tzinfo is not None


def test_mark_failed_sets_error_and_finished_at(db_session) -> None:
    job = create_job(db_session, type="training")
    mark_running(db_session, job)
    mark_failed(db_session, job, {"message": "训练超时"})
    assert job.status == "failed"
    assert job.error == {"message": "训练超时"}
    assert job.result is None
    assert job.finished_at is not None


# ---------- 服务层：to_job_payload ----------


def test_to_job_payload_shape_and_iso_times(db_session) -> None:
    job = create_job(db_session, type="training")
    mark_succeeded(db_session, job, {"acc": 0.9})
    payload = to_job_payload(job)

    assert set(payload) == {
        "id",
        "type",
        "status",
        "progress",
        "result",
        "error",
        "created_at",
        "finished_at",
    }
    assert payload["id"] == job.job_uid
    assert payload["type"] == "training"
    assert payload["status"] == "succeeded"
    assert payload["progress"] == 100
    assert payload["result"] == {"acc": 0.9}
    assert payload["error"] is None
    # ISO-8601 UTC 字符串（`...Z`）
    assert payload["created_at"].endswith("Z")
    assert payload["finished_at"].endswith("Z")


def test_to_job_payload_pending_times(db_session) -> None:
    job = create_job(db_session, type="training")
    payload = to_job_payload(job)
    assert payload["status"] == "pending"
    assert payload["progress"] == 0
    assert payload["result"] is None
    assert payload["error"] is None
    assert payload["finished_at"] is None
    assert payload["created_at"].endswith("Z")


def test_iso_utc_naive_datetime_treated_as_utc() -> None:
    """naive datetime（SQLite/MySQL 读回时 tzinfo 被剥离）按 UTC 处理，不被系统时区偏移。"""
    from app.services.jobs import _iso_utc

    # naive 即 UTC：不因主机非 UTC 时区产生偏移
    naive = datetime(2026, 8, 23, 9, 42, 0)
    assert _iso_utc(naive) == "2026-08-23T09:42:00Z"

    # aware UTC 与 naive 同刻输出一致
    aware = datetime(2026, 8, 23, 9, 42, 0, tzinfo=timezone.utc)
    assert _iso_utc(aware) == "2026-08-23T09:42:00Z"

    # 非 UTC 时区 aware 值先转 UTC 再输出
    shifted = datetime(2026, 8, 23, 17, 42, 0, tzinfo=timezone(timedelta(hours=8)))
    assert _iso_utc(shifted) == "2026-08-23T09:42:00Z"

    # None 透传
    assert _iso_utc(None) is None


# ---------- 端点：GET /jobs/{job_id} ----------


def test_get_job_returns_envelope(
    override_get_session, override_get_current_user, db_session
) -> None:
    job = create_job(db_session, type="training")
    mark_succeeded(db_session, job, {"metric": 0.95})
    db_session.commit()

    resp = client.get(f"/api/v1/jobs/{job.job_uid}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    data = body["data"]
    assert data["id"] == job.job_uid
    assert data["type"] == "training"
    assert data["status"] == "succeeded"
    assert data["progress"] == 100
    assert data["result"] == {"metric": 0.95}
    assert data["error"] is None
    assert data["created_at"].endswith("Z")
    assert data["finished_at"].endswith("Z")


def test_get_job_unknown_uid_404(
    override_get_session, override_get_current_user
) -> None:
    resp = client.get("/api/v1/jobs/job_deadbeef")
    assert resp.status_code == 404
    body = resp.json()
    assert body["code"] == 40401
    assert body["message"] == "任务不存在"


def test_get_job_requires_login(override_get_session) -> None:
    """不 override get_current_user：无 Authorization 头 → 401 信封。"""
    resp = client.get("/api/v1/jobs/job_deadbeef")
    assert resp.status_code == 401
    assert resp.json()["code"] == 40100
