"""标注任务完成闭环回归（2026-09-28，客户视角审查 P1-04）。

**问题**：图像标注已不嵌 LS 工作台——用户在主应用自己的画布上 `saveAnnotation` 直写；
而任务终态原先只由 LS webhook 回写驱动（`annotation_ls._maybe_complete_task`），
于是被推过 LS 的任务（`annotation_ls_sync` 停在 `annotating`）在主应用里保存多少次
都不会离开 `running`。线上实测 29 个 `annotation` job 从 9/6 起一直 running。

**修法**：`POST …/samples/{sample_id}/labels` 保存成功后，把该样本的 sync 行置 `synced` 并
尝试收尾任务——终态仍然只有一个来源（全部 sync 行已回写）。

覆盖：
1. mode=on：推 LS 等待中 → 逐个样本保存 → **全部保存完**才 synced + job succeeded；
2. 只保存了一部分样本 → 任务仍 running（没有"保存一次就清空任务"）；
3. mode=off / legacy 任务（无 sync 行）：保存标注**不改** `ls_status`、不动 job
   （它们的 job 早已由 handler 收尾，闭环逻辑不该越界）。

基础设施同 `test_sample_annotation.py`：内存 SQLite（StaticPool）+ 真实 TestClient +
假 Storage + 假 LS client + 执行器 SessionLocal 指到测试引擎。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, select

from app.api.deps import get_current_user
from app.core.db import get_session
from app.core.seed import seed_reference_data
from app.integrations import labelstudio as ls
from app.main import app
from app.models import User
from app.models.analysis import AnnotationLsSync, AnnotationTask, Sample
from app.models.jobs import Job

client = TestClient(app)
API = "/api/v1"


class FakeStorage:
    def presign_get(self, object_key: str, expires: int = 3600) -> str:
        return f"https://fake.local/{object_key}"


class _FakeCreateTasks:
    def __init__(self) -> None:
        self.created: list[dict] = []

    def create(self, project, data):  # noqa: ANN001
        self.created.append({"project": project, "data": data})
        return type("T", (), {"id": len(self.created)})()


class _FakeCreateClient:
    def __init__(self) -> None:
        self.tasks = _FakeCreateTasks()


@pytest.fixture()
def engine():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def db(engine):
    with Session(engine, expire_on_commit=False) as session:
        yield session


@pytest.fixture()
def run_job(monkeypatch, engine):
    from app.jobs.executor import run_job as _run_job

    monkeypatch.setattr(
        "app.jobs.executor.SessionLocal", lambda: Session(engine, expire_on_commit=False)
    )
    return _run_job


@pytest.fixture()
def user(db) -> User:
    row = User(username="labeler", password_hash="x", display_name="标注员", role="admin")
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@pytest.fixture()
def api(db, user, monkeypatch):
    app.dependency_overrides[get_session] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    monkeypatch.setattr("app.storage.get_storage", lambda: FakeStorage())
    seed_reference_data(db)
    db.commit()
    yield client
    app.dependency_overrides.pop(get_session, None)
    app.dependency_overrides.pop(get_current_user, None)


def _ok(response):
    payload = response.json()
    assert payload["code"] == 0, payload
    return payload["data"]


def _enable_ls(monkeypatch) -> _FakeCreateClient:
    from app.core.config import settings

    monkeypatch.setattr(settings, "label_studio_mode", "on")
    fake = _FakeCreateClient()
    monkeypatch.setattr(ls, "_client", lambda: fake)
    return fake


def _waiting_task_with_two_samples(api, db, run_job, monkeypatch) -> tuple[str, list[int]]:
    """建一个 manual 标注任务 → 跑 handler → 导入 2 张图：任务进入 LS 等待态、两个样本已推流。"""
    _enable_ls(monkeypatch)
    job_id = _ok(api.post(f"{API}/annotation-tasks", json={"source": "manual", "name": "LS 闭环"}))["job_id"]
    run_job(job_id)
    db.expire_all()
    # mode=on 时 import 路由会懒推 LS（样本晚于 handler 到达的既有路径）
    _ok(api.post(
        f"{API}/annotation-tasks/{job_id}/import",
        json={"source": "files", "object_keys": ["raw/a.jpg", "raw/b.jpg"]},
    ))
    sample_ids = [
        item["id"]
        for item in _ok(api.get(f"{API}/annotation-tasks/{job_id}/samples?page_size=20"))["items"]
    ]
    assert len(sample_ids) == 2, sample_ids
    return job_id, sample_ids


def _save(api, job_id: str, sample_id: int) -> None:
    _ok(api.post(
        f"{API}/annotation-tasks/{job_id}/samples/{sample_id}/labels",
        json={"labels": [{"category": "气孔", "kind": "box", "box": [10, 20, 30, 40]}]},
    ))


def _state(db, job_id: str) -> tuple[str, str, int]:
    db.expire_all()
    job = db.exec(select(Job).where(Job.job_uid == job_id)).one()
    task = db.exec(select(AnnotationTask).where(AnnotationTask.job_id == job.id)).one()
    pending = len([
        row
        for row in db.exec(
            select(AnnotationLsSync).where(AnnotationLsSync.annotation_task_id == task.id)
        ).all()
        if row.sync_status != "synced"
    ])
    return job.status, task.ls_status, pending


def test_saving_every_sample_closes_the_task(api, db, run_job, monkeypatch):
    """全部样本在主应用保存完 → 任务 synced + job succeeded（P1-04 的核心断言）。"""
    job_id, sample_ids = _waiting_task_with_two_samples(api, db, run_job, monkeypatch)
    assert _state(db, job_id) == ("running", "pending_ls", 2)

    _save(api, job_id, sample_ids[0])
    status, ls_status, pending = _state(db, job_id)
    assert pending == 1
    assert status == "running", "只保存了一个样本，任务不能提前收尾"
    assert ls_status == "pending_ls"

    _save(api, job_id, sample_ids[1])
    status, ls_status, pending = _state(db, job_id)
    assert pending == 0
    assert status == "succeeded", "全部样本已回写，job 必须离开 running"
    assert ls_status == "synced"


def test_resaving_a_sample_is_idempotent(api, db, run_job, monkeypatch):
    """重复保存同一样本（改标注再存）不会把已完成的 job 或 sync 行改回去。"""
    job_id, sample_ids = _waiting_task_with_two_samples(api, db, run_job, monkeypatch)
    _save(api, job_id, sample_ids[0])
    _save(api, job_id, sample_ids[1])
    _save(api, job_id, sample_ids[0])
    assert _state(db, job_id) == ("succeeded", "synced", 0)


def test_saving_labels_on_a_legacy_task_leaves_ls_state_alone(api, db, run_job, monkeypatch):
    """未走 LS 的任务（mode=off，无 sync 行）：保存标注不碰 `ls_status` 与 job 终态。

    这类任务的 job 在 handler 里就成功了（模拟路径），闭环逻辑不该越界去改它——
    更不能把 `legacy` 写成 `synced`（那等于谎称它走过 LS）。
    """
    from app.core.config import settings

    monkeypatch.setattr(settings, "label_studio_mode", "off")
    job_id = _ok(api.post(f"{API}/annotation-tasks", json={"source": "manual", "name": "离线标注"}))["job_id"]
    run_job(job_id)
    _ok(api.post(
        f"{API}/annotation-tasks/{job_id}/import",
        json={"source": "files", "object_keys": ["raw/a.jpg"]},
    ))
    sample_id = _ok(api.get(f"{API}/annotation-tasks/{job_id}/samples?page_size=20"))["items"][0]["id"]

    _save(api, job_id, sample_id)

    db.expire_all()
    job = db.exec(select(Job).where(Job.job_uid == job_id)).one()
    task = db.exec(select(AnnotationTask).where(AnnotationTask.job_id == job.id)).one()
    assert job.status == "succeeded"
    assert task.ls_status == "legacy", "没走 LS 的任务不该被标成 synced"
    assert db.exec(
        select(AnnotationLsSync).where(AnnotationLsSync.annotation_task_id == task.id)
    ).all() == []
