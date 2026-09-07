"""标注 handler 的 LS 接线回归：LS 模式下推样本进 LS + 置等待态，off/不可达回退模拟。

不连真实 LS/MySQL/MinIO：内存 SQLite + monkeypatch `labelstudio._client`（假 client 记录
创建）与 `app.storage.get_storage`（假 presign）。真实全链路见 `scripts/premise_validation/e2e_ls_roundtrip.py`。

被测试对象：`app.jobs.annotation.handle`（`@register_handler("annotation")`）在
`settings.label_studio_mode == "on"` 时改走 `annotation_ls.prepare_ls_task`（推流 + 等待态），
否则回退 `annotation.simulate_annotation`（旧模拟路径，决策 2 / 计划 Track A 51 行）。
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlmodel import SQLModel, Session, create_engine, select

from app import storage as app_storage
from app.integrations import labelstudio as ls
from app.models.analysis import AnnotationLsSync, AnnotationTask, Sample
from app.models.jobs import Job
from app.services.jobs import create_job


@pytest.fixture()
def engine():
    eng = create_engine("sqlite://")
    SQLModel.metadata.create_all(eng)
    yield eng
    eng.dispose()


def _now():
    return datetime.now(timezone.utc)


class _FakeCreateTasks:
    def __init__(self):
        self.created: list[dict] = []

    def create(self, project, data):
        self.created.append({"project": project, "data": data})
        return type("T", (), {"id": len(self.created)})()


class _FakeCreateClient:
    def __init__(self):
        self.tasks = _FakeCreateTasks()


class _FakeStorage:
    def presign_get(self, key, expires=None):
        return f"https://fake/{key}"


def _seed_manual_annotatable(engine, n=2):
    with Session(engine) as session:
        job = create_job(session, type="annotation")
        task = AnnotationTask(job_id=job.id, source="manual", ls_status="legacy", created_at=_now())
        session.add(task)
        session.flush()
        for i in range(n):
            session.add(
                Sample(
                    annotation_task_id=task.id,
                    object_keys=[f"processed/weld/annotate/s{i}.jpg"],
                    meta={"mode": "image"},
                )
            )
        session.commit()
        return job.id, task.id


def _seed_anchor_task(engine, source, mode):
    """建 signal/video 来源任务：仅 1 个锚点样本（meta 携带媒体引用，object_keys=[]）。

    模拟创建路由（`analysis_annotations.py`）：signal 锚点带 version_id，video 锚点带 video_key，
    均无 object_keys——这正是媒体导出桥落地前"推流必为 0"的来源。
    """
    with Session(engine) as session:
        job = create_job(session, type="annotation")
        metadata: dict = {"mode": mode, "weld_id": "WLD", "version_id": 1}
        if source == "video":
            metadata["video_key"] = "raw/REG-20260815-00248/0001.mp4"
        task = AnnotationTask(job_id=job.id, source=source, ls_status="legacy", created_at=_now())
        session.add(task)
        session.flush()
        session.add(Sample(annotation_task_id=task.id, object_keys=[], meta=metadata))
        session.commit()
        return job.id, task.id


def test_handler_mode_on_signal_video_sources_fallback(engine, monkeypatch):
    """mode=on 且 source=signal/video（媒体导出桥未落地）：回退旧模拟路径，不入 LS 等待态、不卡死。

    回归保护：signal/video 任务的锚点样本 object_keys=[]，若进入 LS 等待态会推流 0 条 + 永无
    回写 → job 永久 running（阻塞）。决策：媒体未导出，signal/video 暂留旧画布，故回退 simulate。
    """
    from app.core.config import settings
    from app.jobs import annotation as ann_handler

    monkeypatch.setattr(settings, "label_studio_mode", "on")
    client = _FakeCreateClient()
    monkeypatch.setattr(ls, "_client", lambda: client)
    monkeypatch.setattr(app_storage, "get_storage", lambda: _FakeStorage())
    for source, mode in (("signal", "signal"), ("video", "video")):
        with Session(engine) as session:
            job_id, task_id = _seed_anchor_task(engine, source, mode)
            ann_handler.handle(job_id, session)
            session.commit()
            task = session.get(AnnotationTask, task_id)
            assert task.ls_status == "legacy"  # 未进入 LS 等待态
            job = session.get(Job, job_id)
            assert job.status == "succeeded"  # 回退模拟 → job 终态，不永久 running
            syncs = session.exec(
                select(AnnotationLsSync).where(AnnotationLsSync.annotation_task_id == task_id)
            ).all()
            assert syncs == []  # 无 LS 映射行
            assert client.tasks.created == []  # 未调用 LS tasks.create


def test_handler_mode_on_pushes_samples_and_waits(engine, monkeypatch):
    """LS 模式：handler 推样本进 LS + 置「LS 等待」态 + job 不立即终态（等回写）。"""
    from app.core.config import settings
    from app.jobs import annotation as ann_handler

    monkeypatch.setattr(settings, "label_studio_mode", "on")
    client = _FakeCreateClient()
    monkeypatch.setattr(ls, "_client", lambda: client)
    monkeypatch.setattr(app_storage, "get_storage", lambda: _FakeStorage())
    with Session(engine) as session:
        job_id, task_id = _seed_manual_annotatable(engine, n=2)
        ann_handler.handle(job_id, session)
        session.commit()
        task = session.get(AnnotationTask, task_id)
        assert task.ls_status == "pending_ls"
        syncs = session.exec(
            select(AnnotationLsSync).where(AnnotationLsSync.annotation_task_id == task_id)
        ).all()
        assert len(syncs) == 2
        assert all(s.sync_status == "annotating" for s in syncs)
        assert all(s.ls_task_id is not None for s in syncs)  # 已拿到 LS task id
        assert client.tasks.created  # 实际调用了 LS tasks.create
        job = session.get(Job, job_id)
        assert job.status in ("pending", "running")  # 等待回写，不立即 succeeded


def test_handler_mode_off_keeps_simulate_path(engine, monkeypatch):
    """off 模式：handler 仍走旧模拟路径（job succeeded + 不建 sync 行）。"""
    from app.core.config import settings
    from app.jobs import annotation as ann_handler

    monkeypatch.setattr(settings, "label_studio_mode", "off")
    with Session(engine) as session:
        job_id, task_id = _seed_manual_annotatable(engine, n=2)
        ann_handler.handle(job_id, session)
        session.commit()
        job = session.get(Job, job_id)
        assert job.status == "succeeded"  # 回退旧模拟路径
        task = session.get(AnnotationTask, task_id)
        assert task.ls_status == "legacy"  # 未进入等待态
        syncs = session.exec(
            select(AnnotationLsSync).where(AnnotationLsSync.annotation_task_id == task_id)
        ).all()
        assert syncs == []


def test_handler_mode_on_but_ls_unavailable_falls_back(engine, monkeypatch):
    """mode=on 但 LS client 不可达（get_storage/url 缺失）：回退旧模拟路径，不炸。"""
    from app.core.config import settings
    from app.jobs import annotation as ann_handler

    monkeypatch.setattr(settings, "label_studio_mode", "on")
    monkeypatch.setattr(ls, "_client", lambda: None)  # off / 缺 url/key
    with Session(engine) as session:
        job_id, task_id = _seed_manual_annotatable(engine, n=2)
        ann_handler.handle(job_id, session)
        session.commit()
        job = session.get(Job, job_id)
        assert job.status == "succeeded"  # LS 不可达 → 回退模拟，不炸
        syncs = session.exec(
            select(AnnotationLsSync).where(AnnotationLsSync.annotation_task_id == task_id)
        ).all()
        assert syncs == []


def test_push_samples_to_ls_is_idempotent(engine, monkeypatch):
    """重复推流不重复建 LS task：只在首次创建，第二次跳过（manual-import 晚于 handler 时安全）。"""
    from app.services import annotation_ls as al

    client = _FakeCreateClient()
    monkeypatch.setattr(ls, "_client", lambda: client)
    monkeypatch.setattr(app_storage, "get_storage", lambda: _FakeStorage())
    with Session(engine) as session:
        _job_id, task_id = _seed_manual_annotatable(engine, n=2)
        task = session.get(AnnotationTask, task_id)
        samples = session.exec(
            select(Sample).where(Sample.annotation_task_id == task_id)
        ).all()
        first = al.push_samples_to_ls(session, task, samples)
        second = al.push_samples_to_ls(session, task, samples)
        session.commit()
        assert first == 2
        assert second == 0  # 已在 LS 建过 task → 幂等跳过
        assert len(client.tasks.created) == 2  # 只建了 2 个 LS task，不重复
