"""Label Studio 集成回归测试：region 转换 / 回写幂等 / best-effort。

不连真实 LS/MySQL/MinIO：
- 纯函数：convert_region(0-100%→像素)、_region_category、extract_annotator、media_field_for。
- handle_annotation_event + writeback：内存 SQLite，monkeypatch `labelstudio._client` 返回
  假 client（tasks.get 返回假 annotation payload），验证回写 `annotations` 与幂等（重发不重复落行）。
- best-effort：`_client` 返回 None 时 push_samples_to_ls 返回 0，不抛。

真实全链路见 `backend/scripts/premise_validation/e2e_ls_roundtrip.py`（跑裸打真实环境）。
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlmodel import SQLModel, Session, create_engine, select

from app.integrations import labelstudio as ls
from app.models.analysis import (
    Annotation,
    AnnotationLsSync,
    AnnotationTask,
    Sample,
)
from app.models.jobs import Job
from app.services import annotation_ls as svc
from app.services.jobs import create_job


@pytest.fixture()
def engine():
    eng = create_engine("sqlite://")
    SQLModel.metadata.create_all(eng)
    yield eng
    eng.dispose()


def _now():
    return datetime.now(timezone.utc)


# ── 纯函数：LS region → 平台几何 ─────────────────────────────────────────


def test_convert_region_rectanglelabels_percent_to_pixel():
    geo = ls.convert_region({
        "type": "rectanglelabels", "original_width": 640, "original_height": 480,
        "value": {"x": 12.5, "y": 20.0, "width": 30.0, "height": 25.0, "rectanglelabels": ["气孔"]},
    })
    assert geo == {"kind": "box", "box": [80.0, 96.0, 192.0, 120.0]}  # 12.5%*640=80 ...


def test_convert_region_polygonlabels_percent_to_pixel():
    geo = ls.convert_region({
        "type": "polygonlabels", "original_width": 640, "original_height": 480,
        "value": {"points": [[10.0, 20.0], [40.0, 20.0], [40.0, 50.0], [10.0, 50.0]], "polygonlabels": ["熔池"]},
    })
    assert geo == {"kind": "polygon", "points": [[64.0, 96.0], [256.0, 96.0], [256.0, 240.0], [64.0, 240.0]]}


def test_convert_region_unknown_type_returns_none():
    assert ls.convert_region({"type": "nope", "value": {}}) is None


def test_convert_region_falls_back_to_default_dims():
    geo = ls.convert_region({"type": "polygonlabels", "value": {"points": [[50.0, 50.0]], "polygonlabels": ["熔池"]}})
    assert geo == {"kind": "polygon", "points": [[320.0, 240.0]]}  # default 640x480, 50% each


def test_region_category_reads_plural_label():
    assert ls._region_category({"value": {"rectanglelabels": ["气孔"]}}) == "气孔"
    assert ls._region_category({"value": {"polygonlabels": ["熔池"]}}) == "熔池"
    assert ls._region_category({"value": {}}) == ""
    assert ls._region_category({"value": {"labels": ["焊瘤"]}}) == "焊瘤"  # 兼容历史


def test_extract_annotator_from_completed_by():
    assert ls.extract_annotator({"completed_by": {"email": "x@y.com", "id": 1}}) == "x@y.com"
    assert ls.extract_annotator({"completed_by": {"id": 7}}) == "7"
    assert ls.extract_annotator({"created_username": " xiaofei450@126.com, 1"}) == "xiaofei450@126.com"
    assert ls.extract_annotator({}) == "LabelStudio"


def test_media_field_for():
    assert ls.media_field_for("segment") == "csv"
    assert ls.media_field_for("box") == "image"
    assert ls.media_field_for("polygon") == "image"


# ── handle_annotation_event + 幂等（mock client） ────────────────────────


class _FakeTasks:
    def __init__(self, payload: dict):
        self._payload = payload

    def get(self, task_id):
        payload = self._payload  # 闭包捕获，避免引用实例 attrs
        return type("Task", (), {"to_dict": lambda self: payload})()


class _FakeClient:
    def __init__(self, payload: dict):
        self.tasks = _FakeTasks(payload)


def _seed(engine):
    with Session(engine) as session:
        job = create_job(session, type="annotation")
        task = AnnotationTask(job_id=job.id, source="manual", ls_status="pending_ls", created_at=_now())
        session.add(task)
        session.flush()
        sample = Sample(annotation_task_id=task.id, object_keys=["e2e/frame.png"], meta={"mode": "image"})
        session.add(sample)
        session.flush()
        sync = AnnotationLsSync(annotation_task_id=task.id, sample_id=sample.id,
                                ls_project_id=3, ls_task_id=42, sync_status="annotating")
        session.add(sync)
        session.commit()
        return job.id, task.id, sample.id


_BOX_ANNOTATION = {
    "id": 9,
    "was_cancelled": False,
    "result": [{
        "id": "r-1", "type": "rectanglelabels", "from_name": "label", "to_name": "image",
        "original_width": 640, "original_height": 480, "image_rotation": 0,
        "value": {"x": 12.5, "y": 20.0, "width": 30.0, "height": 25.0, "rectanglelabels": ["气孔"]},
    }],
    "completed_by": {"id": 1, "email": "xiaofei450@126.com"},
}


def test_handle_annotation_event_writes_back_idempotently(engine, monkeypatch):
    client = _FakeClient({"annotations": [_BOX_ANNOTATION]})
    monkeypatch.setattr(ls, "_client", lambda: client)
    with Session(engine) as session:
        _job_id, task_id, sample_id = _seed(engine)
        res = svc.handle_annotation_event(session, "annotation_created", {"task": {"id": 42}})
        assert res == {"task_id": 42, "samples": 1}
        anns = session.exec(select(Annotation).where(Annotation.sample_id == sample_id)).all()
        assert len(anns) == 1
        assert anns[0].category == "气孔"
        assert anns[0].kind == "box"
        assert anns[0].box == [80.0, 96.0, 192.0, 120.0]
        assert anns[0].annotator == "xiaofei450@126.com"
        sync = session.exec(select(AnnotationLsSync).where(AnnotationLsSync.ls_task_id == 42)).first()
        assert sync.sync_status == "synced"
        task = session.get(AnnotationTask, task_id)
        assert task.ls_status == "synced"

        # 幂等：重复事件不重复落行
        svc.handle_annotation_event(session, "annotation_updated", {"task": {"id": 42}})
        after = session.exec(select(Annotation).where(Annotation.sample_id == sample_id)).all()
        assert len(after) == 1


def test_handle_annotation_event_skips_when_no_effective_annotation(engine, monkeypatch):
    # was_cancelled → choose_effective_annotation 返回 None → 不写 annotation，sync 仍 annotating
    client = _FakeClient({"annotations": [{"id": 1, "was_cancelled": True, "result": []}]})
    monkeypatch.setattr(ls, "_client", lambda: client)
    with Session(engine) as session:
        _job_id, _task_id, sample_id = _seed(engine)
        res = svc.handle_annotation_event(session, "annotation_created", {"task": {"id": 42}})
        assert res is None
        anns = session.exec(select(Annotation).where(Annotation.sample_id == sample_id)).all()
        assert anns == []


def test_handle_annotation_event_empty_submission_marks_synced(engine, monkeypatch):
    """空提交（标注员认定无缺陷，result=[]）→ 视为有效空标注：回写 0 行但样本 synced、任务完成。

    回归保护：此前空提交被当"无有效标注" → 样本永不 synced → 任务卡死（图片"正常"样本无法提交）。
    """
    client = _FakeClient({"annotations": [{
        "id": 5, "was_cancelled": False, "result": [],
        "completed_by": {"id": 1, "email": "annot@x.com"},
    }]})
    monkeypatch.setattr(ls, "_client", lambda: client)
    with Session(engine) as session:
        job_id, task_id, sample_id = _seed(engine)  # 单样本任务，sync_status=annotating
        res = svc.handle_annotation_event(session, "annotation_created", {"task": {"id": 42}})
        assert res == {"task_id": 42, "samples": 1}  # 不 skip（空提交是有效提交）
        anns = session.exec(select(Annotation).where(Annotation.sample_id == sample_id)).all()
        assert anns == []  # 无缺陷 → 不落缺陷行
        sync = session.exec(select(AnnotationLsSync).where(AnnotationLsSync.ls_task_id == 42)).first()
        assert sync.sync_status == "synced"  # 空提交也算完成
        task = session.get(AnnotationTask, task_id)
        assert task.ls_status == "synced"
        job = session.get(Job, job_id)
        assert job.status == "succeeded"


def test_handle_annotation_event_skips_unknown_task(engine):
    with Session(engine) as session:
        assert svc.handle_annotation_event(session, "annotation_created", {"task": {"id": 999}}) is None


def test_to_task_payload_includes_ls_url_and_projects(engine):
    """`GET /labelstudio/tasks/{id}` 需返回 ls_public_url + ls_project_ids（前端 iframe 嵌入用）。"""
    from app.core.config import settings

    with Session(engine) as session:
        _job_id, task_id, _sample_id = _seed(engine)
        task = session.get(AnnotationTask, task_id)
        payload = svc.to_task_payload(session, task)
        assert payload["ls_status"] == "pending_ls"
        assert payload["ls_project_ids"] == [3]  # _seed 的 sync 行 ls_project_id=3
        assert payload["ls_public_url"] == settings.label_studio_public_url
        assert "created_at" in payload


def _seed_multi(engine, n=2):
    with Session(engine) as session:
        job = create_job(session, type="annotation")
        task = AnnotationTask(job_id=job.id, source="manual", ls_status="pending_ls", created_at=_now())
        session.add(task)
        session.flush()
        sample_ids = []
        for i in range(n):
            sample = Sample(annotation_task_id=task.id, object_keys=[f"a{i}.jpg"], meta={"mode": "image"})
            session.add(sample)
            session.flush()
            sample_ids.append(sample.id)
            session.add(
                AnnotationLsSync(
                    annotation_task_id=task.id, sample_id=sample.id,
                    ls_project_id=3, ls_task_id=42 + i, sync_status="annotating",
                )
            )
        session.commit()
        return job.id, task.id


def test_handle_annotation_event_completes_job_when_all_synced(engine, monkeypatch):
    """单样本（唯一的 sync 行）回写后 → 任务全 synced → job 也 succeeded。"""
    client = _FakeClient({"annotations": [_BOX_ANNOTATION]})
    monkeypatch.setattr(ls, "_client", lambda: client)
    with Session(engine) as session:
        job_id, task_id, sample_id = _seed(engine)
        svc.handle_annotation_event(session, "annotation_created", {"task": {"id": 42}})
        session.commit()
        task = session.get(AnnotationTask, task_id)
        assert task.ls_status == "synced"
        job = session.get(Job, job_id)
        assert job.status == "succeeded"


def test_handle_annotation_event_partial_sync_keeps_job_running(engine, monkeypatch):
    """多样本任务，仅一个样本回写 → 任务仍在等待（pending_ls）、job 未终态。"""
    client = _FakeClient({"annotations": [_BOX_ANNOTATION]})
    monkeypatch.setattr(ls, "_client", lambda: client)
    with Session(engine) as session:
        job_id, task_id = _seed_multi(engine, n=2)
        # 只处理 ls_task_id=42 的样本，43 仍未回写
        svc.handle_annotation_event(session, "annotation_created", {"task": {"id": 42}})
        session.commit()
        task = session.get(AnnotationTask, task_id)
        assert task.ls_status == "pending_ls"  # 还有一个样本未回写
        job = session.get(Job, job_id)
        assert job.status in ("pending", "running")


# ── best-effort：LS off/不可达不炸 ────────────────────────────────────────


def test_push_samples_to_ls_off_returns_zero(engine, monkeypatch):
    monkeypatch.setattr(ls, "_client", lambda: None)  # off / unavailable
    with Session(engine) as session:
        _job_id, task_id, sample_id = _seed(engine)
        task = session.get(AnnotationTask, task_id)
        sample = session.get(Sample, sample_id)
        created = svc.push_samples_to_ls(session, task, [sample])
        assert created == 0  # best-effort：不抛、不建 LS task
