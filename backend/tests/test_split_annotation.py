"""Task 14：切分任务（Split）+ 标注任务（Annotation）（均模拟）。

内存 SQLite + StaticPool + 真实 app TestClient（同 test_alignment.py）。
`seed_all` 造演示数据（4 焊缝 / 5 标签类别 / 0248 演示标注）后 override
`get_session` / `get_current_user`；并把 `app.jobs.executor.SessionLocal` 指到同一
测试引擎（`run_job` 用它开独立 session，**不启动**后台轮询线程）。

覆盖：
- 切分：创建 → `run_job` → succeeded + `SplitTask.sample_count` 回填 + `samples` 行
  （frame_no 0..n、object_keys 前缀 `processed/{weld_id}/split/`）；非法参数 400；
  未知焊缝/版本 40401/40402；未知 task_id 404；
- 标注：从切分任务创建 → `run_job` → 样本 `annotation_task_id` 指向新任务；manual 无归属；
  import（files 建样本 / split_task 改归属）；标签类别 5 类；AI 预标注确定性 2 区域；
  save labels 覆盖写 + 置信度语义（缺省沿用预标注值）；样本分页；404/401；
- 失败：monkeypatch `HANDLERS` 抛异常 → job failed（不滞留 running）。
"""

import pytest
import threading
from pathlib import Path
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, func, select

import app.jobs.executor as executor_mod
from app.api.deps import get_current_user
from app.core.db import get_session
from app.core.seed import seed_all
from app.jobs.executor import run_job
from app.main import app
from app.models import DataRecord, DataVersion, User
from app.models.analysis import Annotation, AnnotationTask, Sample, SplitTask
from app.models.jobs import Job

client = TestClient(app)

WELD_0248 = "WLD-20260815-0248"
WELD_0245 = "WLD-20260814-0245"
FIXED_RATE = 25
SPLIT_SAMPLE_COUNT = 5420 // FIXED_RATE  # 5.42s × 1000Hz = 5420 帧


@pytest.fixture()
def db_engine():
    """内存 SQLite + StaticPool：seed 演示数据，每用例全新引擎（环形 FK 不便 drop_all）。"""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        seed_all(session)
    yield engine
    engine.dispose()


@pytest.fixture()
def override_get_session(db_engine):
    """每请求开一个独立 Session（与真实 get_session 语义一致），退出即 close。"""

    def _override():
        with Session(db_engine) as session:
            yield session

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


@pytest.fixture()
def executor_sessionlocal(db_engine, monkeypatch):
    """把 executor 的 SessionLocal 指到同一测试引擎（run_job 用独立 session，不启动线程）。"""
    monkeypatch.setattr(
        executor_mod,
        "SessionLocal",
        sessionmaker(bind=db_engine, class_=Session, expire_on_commit=False),
    )


# ── 小助手 ────────────────────────────────────────────────────────────


def _version_id_by_no(weld_id, version_no="v1.0"):
    versions = client.get(f"/api/v1/welds/{weld_id}/versions").json()["data"]
    for v in versions:
        if v["version_no"] == version_no:
            return v["id"]
    raise AssertionError(f"{version_no} not found for {weld_id}")


def _create_split_task(weld_id, version_id, fixed_rate=FIXED_RATE, task_format="目标检测"):
    resp = client.post(
        f"/api/v1/welds/{weld_id}/versions/{version_id}/split-tasks",
        json={"fixed_rate": fixed_rate, "keep_event_buffer": 0.2, "task_format": task_format},
    )
    assert resp.status_code == 200, resp.text[:300]
    job_id = resp.json()["data"]["job_id"]
    assert job_id.startswith("job_")
    return job_id


def _create_annotation_task(source, split_task_id=None, name=None):
    resp = client.post(
        "/api/v1/annotation-tasks",
        json={"source": source, "split_task_id": split_task_id, "name": name},
    )
    assert resp.status_code == 200, resp.text[:300]
    job_id = resp.json()["data"]["job_id"]
    assert job_id.startswith("job_")
    return job_id


def _split_row(db_engine, split_job_id):
    with Session(db_engine) as session:
        job = session.exec(select(Job).where(Job.job_uid == split_job_id)).first()
        assert job is not None
        return session.exec(select(SplitTask).where(SplitTask.job_id == job.id)).first()


def _annot_row(db_engine, annot_job_id):
    with Session(db_engine) as session:
        job = session.exec(select(Job).where(Job.job_uid == annot_job_id)).first()
        assert job is not None
        return session.exec(
            select(AnnotationTask).where(AnnotationTask.job_id == job.id)
        ).first()


def _sample_count_for_split(db_engine, split_task_id):
    with Session(db_engine) as session:
        return int(
            session.exec(
                select(func.count(Sample.id)).where(Sample.split_task_id == split_task_id)
            ).one()
        )


class FakeStorage:
    def __init__(self, fail_after: int | None = None) -> None:
        self.fail_after = fail_after
        self.uploads: list[tuple[str, bytes, str]] = []
        self.deletes: list[str] = []

    def upload_stream(self, object_key, fileobj, size, content_type):
        if self.fail_after is not None and len(self.uploads) >= self.fail_after:
            raise RuntimeError("模拟 MinIO 写入失败")
        data = fileobj.read()
        self.uploads.append((object_key, data, content_type))
        return object_key

    def delete_object(self, object_key):
        self.deletes.append(object_key)


# ---------- 切分：创建 → run_job → 生成样本 + 回填 sample_count ----------


def test_split_task_end_to_end(
    db_engine,
    override_get_session,
    override_get_current_user,
    executor_sessionlocal,
    monkeypatch,
) -> None:
    storage = FakeStorage()
    monkeypatch.setattr("app.storage.get_storage", lambda: storage)
    monkeypatch.setattr("app.jobs.split._REF_DURATION_S", 0.05)
    vid = _version_id_by_no(WELD_0248)
    job_id = _create_split_task(WELD_0248, vid, fixed_rate=FIXED_RATE)

    pending = client.get(f"/api/v1/split-tasks/{job_id}").json()["data"]
    assert pending["type"] == "split"
    assert pending["status"] == "pending"
    assert pending["result"] is None

    run_job(job_id)

    done = client.get(f"/api/v1/split-tasks/{job_id}").json()["data"]
    assert done["status"] == "succeeded"
    assert done["progress"] == 100
    assert done["finished_at"].endswith("Z")
    result = done["result"]
    assert result["sample_count"] == 2
    assert len(result["samples"]) == 2
    assert result["samples"][0]["frame_no"] == 0

    split = _split_row(db_engine, job_id)
    assert split is not None
    assert split.sample_count == 2
    assert _sample_count_for_split(db_engine, split.id) == 2

    # 直查：样本 frame_no 0..n，object_keys 前缀 processed/{weld_id}/split/，且对象真实写入存储
    with Session(db_engine) as session:
        samples = session.exec(
            select(Sample).where(Sample.split_task_id == split.id).order_by(Sample.id)
        ).all()
        assert [s.frame_no for s in samples] == [0, 1]
        expected_keys: list[str] = []
        for s in samples:
            assert s.object_keys
            assert all(k.startswith(f"processed/{WELD_0248}/split/") for k in s.object_keys)
            expected_keys.extend(s.object_keys)
    assert [key for key, _data, _content_type in storage.uploads] == expected_keys
    assert [sample["object_keys"] for sample in result["samples"]] == [
        [expected_keys[0], expected_keys[1]],
        [expected_keys[2], expected_keys[3]],
    ]


def test_split_invalid_params(
    override_get_session, override_get_current_user
) -> None:
    vid = _version_id_by_no(WELD_0248)
    resp = client.post(
        f"/api/v1/welds/{WELD_0248}/versions/{vid}/split-tasks",
        json={"fixed_rate": 0, "task_format": "目标检测"},
    )
    assert resp.status_code == 400 and resp.json()["code"] == 40000
    resp = client.post(
        f"/api/v1/welds/{WELD_0248}/versions/{vid}/split-tasks",
        json={"fixed_rate": 25, "task_format": "不存在的格式"},
    )
    assert resp.status_code == 400 and resp.json()["code"] == 40000


def test_create_split_rejects_missing_inputs_with_4xx(
    override_get_session, override_get_current_user
) -> None:
    vid = _version_id_by_no(WELD_0245)
    resp = client.post(
        f"/api/v1/welds/{WELD_0245}/versions/{vid}/split-tasks",
        json={"fixed_rate": 25, "keep_event_buffer": 0.2, "task_format": "目标检测"},
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["code"] == 40000
    assert "输入" in resp.json()["message"]


def test_create_split_unknown_weld_or_version(
    override_get_session, override_get_current_user
) -> None:
    vid = _version_id_by_no(WELD_0248)
    resp = client.post(
        "/api/v1/welds/WLD-NOPE-0000/versions/1/split-tasks",
        json={"fixed_rate": 25, "task_format": "目标检测"},
    )
    assert resp.status_code == 404 and resp.json()["code"] == 40401
    resp = client.post(
        f"/api/v1/welds/{WELD_0248}/versions/999999/split-tasks",
        json={"fixed_rate": 25, "task_format": "目标检测"},
    )
    assert resp.status_code == 404 and resp.json()["code"] == 40402


def test_get_split_task_unknown_404(override_get_session, override_get_current_user) -> None:
    resp = client.get("/api/v1/split-tasks/job_deadbeef")
    assert resp.status_code == 404
    assert resp.json()["code"] == 40401


def test_split_create_is_idempotent_for_same_version_and_config(
    db_engine,
    override_get_session,
    override_get_current_user,
    executor_sessionlocal,
) -> None:
    vid = _version_id_by_no(WELD_0248)
    first = _create_split_task(WELD_0248, vid, fixed_rate=FIXED_RATE)
    second = _create_split_task(WELD_0248, vid, fixed_rate=FIXED_RATE)
    assert second == first

    with Session(db_engine) as session:
        matching = session.exec(select(SplitTask).where(SplitTask.version_id == vid)).all()
        assert len(matching) == 1

    run_job(first)
    done = client.get(f"/api/v1/split-tasks/{first}").json()["data"]
    assert done["status"] == "succeeded"

    third = _create_split_task(WELD_0248, vid, fixed_rate=FIXED_RATE)
    assert third == first
    with Session(db_engine) as session:
        matching = session.exec(select(SplitTask).where(SplitTask.version_id == vid)).all()
        assert len(matching) == 1


def test_split_create_allows_retry_after_failed_job(
    db_engine,
    override_get_session,
    override_get_current_user,
    executor_sessionlocal,
    monkeypatch,
) -> None:
    monkeypatch.setattr("app.jobs.split._REF_DURATION_S", 0.05)
    vid = _version_id_by_no(WELD_0248)
    job_id = _create_split_task(WELD_0248, vid, fixed_rate=FIXED_RATE)

    def _boom(_job_id, _session):
        raise RuntimeError("模拟切分内核崩溃")

    monkeypatch.setitem(executor_mod.HANDLERS, "split", _boom)
    run_job(job_id)
    failed = client.get(f"/api/v1/split-tasks/{job_id}").json()["data"]
    assert failed["status"] == "failed"

    retry = client.post(
        f"/api/v1/welds/{WELD_0248}/versions/{vid}/split-tasks",
        json={"fixed_rate": FIXED_RATE, "keep_event_buffer": 0.2, "task_format": "目标检测"},
    )
    assert retry.status_code == 200, retry.text
    retry_job_id = retry.json()["data"]["job_id"]
    assert retry_job_id != job_id

    duplicate_retry = client.post(
        f"/api/v1/welds/{WELD_0248}/versions/{vid}/split-tasks",
        json={"fixed_rate": FIXED_RATE, "keep_event_buffer": 0.2, "task_format": "目标检测"},
    )
    assert duplicate_retry.status_code == 200, duplicate_retry.text
    assert duplicate_retry.json()["data"]["job_id"] == retry_job_id

    with Session(db_engine) as session:
        tasks = session.exec(select(SplitTask).where(SplitTask.version_id == vid)).all()
        assert len(tasks) == 2
        jobs = session.exec(
            select(Job).where(Job.job_uid.in_([job_id, retry_job_id])).order_by(Job.id)
        ).all()
        assert [job.status for job in jobs] == ["failed", "pending"]


def test_split_task_storage_failure_cleans_objects_and_keeps_db_job_consistent(
    db_engine,
    override_get_session,
    override_get_current_user,
    executor_sessionlocal,
    monkeypatch,
) -> None:
    storage = FakeStorage(fail_after=1)
    monkeypatch.setattr("app.storage.get_storage", lambda: storage)
    monkeypatch.setattr("app.jobs.split._REF_DURATION_S", 0.05)
    vid = _version_id_by_no(WELD_0248)
    job_id = _create_split_task(WELD_0248, vid, fixed_rate=FIXED_RATE)

    run_job(job_id)

    data = client.get(f"/api/v1/split-tasks/{job_id}").json()["data"]
    assert data["status"] == "failed"
    assert data["error"] == {"message": "模拟 MinIO 写入失败"}
    assert data["result"] is None
    uploaded_keys = [key for key, _data, _content_type in storage.uploads]
    assert len(uploaded_keys) == 1
    assert uploaded_keys[0].startswith(f"processed/{WELD_0248}/split/")
    assert uploaded_keys[0].endswith(".jpg")
    assert storage.deletes == uploaded_keys

    split = _split_row(db_engine, job_id)
    assert split is not None
    assert split.sample_count is None
    with Session(db_engine) as session:
        assert session.exec(select(func.count(Sample.id))).one() == 2
        failed_job = session.exec(select(Job).where(Job.job_uid == job_id)).first()
        assert failed_job is not None
        assert failed_job.status == "failed"



def test_create_split_concurrent_requests_return_same_job(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "split-concurrency.db"
    engine = create_engine(
        f"sqlite:///{db_path}", connect_args={"check_same_thread": False}
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        seed_all(session)

    def _override_session():
        with Session(engine) as session:
            yield session

    dummy = User(
        id=1,
        username="lin_eng",
        password_hash="not-a-real-hash",
        display_name="林工",
        role="admin",
    )

    def _override_user() -> User:
        return dummy

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_current_user] = _override_user
    barrier = threading.Barrier(2)
    original_create_job = __import__("app.api.v1.analysis", fromlist=["create_job"]).create_job
    vid = client.get(f"/api/v1/welds/{WELD_0248}/versions").json()["data"][0]["id"]

    def _sync_create_job(session, type, result=None):
        if type == "split":
            barrier.wait(timeout=2)
        return original_create_job(session, type, result=result)

    monkeypatch.setattr("app.api.v1.analysis.create_job", _sync_create_job)

    results: list[tuple[int, dict]] = []
    errors: list[BaseException] = []

    def _worker() -> None:
        try:
            with TestClient(app) as local_client:
                resp = local_client.post(
                    f"/api/v1/welds/{WELD_0248}/versions/{vid}/split-tasks",
                    json={"fixed_rate": FIXED_RATE, "keep_event_buffer": 0.2, "task_format": "目标检测"},
                )
            results.append((resp.status_code, resp.json()))
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=_worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    app.dependency_overrides.pop(get_session, None)
    app.dependency_overrides.pop(get_current_user, None)

    assert not errors
    assert [status for status, _body in results] == [200, 200]
    job_ids = [body["data"]["job_id"] for _status, body in results]
    assert len(set(job_ids)) == 1
    with Session(engine) as session:
        tasks = session.exec(select(SplitTask).where(SplitTask.version_id == vid)).all()
        assert len(tasks) == 1
        jobs = session.exec(select(Job).where(Job.job_uid == job_ids[0])).all()
        assert len(jobs) == 1


# ---------- 标注：从切分任务创建 → run_job → 样本归属更新 ----------


def test_annotation_from_split_task_end_to_end(
    db_engine,
    override_get_session,
    override_get_current_user,
    executor_sessionlocal,
) -> None:
    vid = _version_id_by_no(WELD_0248)
    split_job_id = _create_split_task(WELD_0248, vid)
    run_job(split_job_id)
    split = _split_row(db_engine, split_job_id)

    annot_job_id = _create_annotation_task("split_task", split_task_id=split_job_id, name="AN-test")
    pending = client.get(f"/api/v1/annotation-tasks/{annot_job_id}").json()["data"]
    assert pending["type"] == "annotation"
    assert pending["status"] == "pending"

    run_job(annot_job_id)

    done = client.get(f"/api/v1/annotation-tasks/{annot_job_id}").json()["data"]
    assert done["status"] == "succeeded"
    assert done["result"]["samples_count"] == SPLIT_SAMPLE_COUNT
    assert done["result"]["source"] == "split_task"

    annot = _annot_row(db_engine, annot_job_id)
    assert annot is not None
    assert annot.split_task_id == split.id
    # 样本归属更新：该切分任务的样本 annotation_task_id 指向新标注任务
    with Session(db_engine) as session:
        samples = session.exec(
            select(Sample).where(Sample.split_task_id == split.id)
        ).all()
        assert len(samples) == SPLIT_SAMPLE_COUNT
        assert all(s.annotation_task_id == annot.id for s in samples)


def test_annotation_manual_source_reassigns_nothing(
    db_engine,
    override_get_session,
    override_get_current_user,
    executor_sessionlocal,
) -> None:
    annot_job_id = _create_annotation_task("manual")
    run_job(annot_job_id)
    done = client.get(f"/api/v1/annotation-tasks/{annot_job_id}").json()["data"]
    assert done["status"] == "succeeded"
    assert done["result"]["source"] == "manual"
    assert done["result"]["samples_count"] == 0


def test_create_annotation_task_validation(
    override_get_session, override_get_current_user
) -> None:
    resp = client.post("/api/v1/annotation-tasks", json={"source": "bad_source"})
    assert resp.status_code == 400 and resp.json()["code"] == 40000
    resp = client.post(
        "/api/v1/annotation-tasks",
        json={"source": "split_task", "split_task_id": "job_deadbeef"},
    )
    assert resp.status_code == 404 and resp.json()["code"] == 40401


# ---------- 导入：files 建样本 / split_task 改归属 ----------


def test_import_from_files_creates_samples(
    db_engine,
    override_get_session,
    override_get_current_user,
) -> None:
    annot_job_id = _create_annotation_task("manual")
    keys = ["processed/WLD-20260815-0248/split/1.jpg", "processed/WLD-20260815-0248/split/2.jpg"]
    resp = client.post(
        f"/api/v1/annotation-tasks/{annot_job_id}/import",
        json={"source": "files", "object_keys": keys},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["imported"] == 2

    samples = client.get(f"/api/v1/annotation-tasks/{annot_job_id}/samples").json()["data"]
    assert samples["total"] == 2
    assert {s["object_keys"][0] for s in samples["items"]} == set(keys)
    assert all(s["annotations"] == [] for s in samples["items"])


def test_import_from_split_task_reassigns(
    db_engine,
    override_get_session,
    override_get_current_user,
    executor_sessionlocal,
) -> None:
    vid = _version_id_by_no(WELD_0248)
    split_job_id = _create_split_task(WELD_0248, vid)
    run_job(split_job_id)
    split = _split_row(db_engine, split_job_id)

    annot_job_id = _create_annotation_task("manual")
    resp = client.post(
        f"/api/v1/annotation-tasks/{annot_job_id}/import",
        json={"source": "split_task", "split_task_id": split_job_id},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["imported"] == SPLIT_SAMPLE_COUNT

    samples = client.get(f"/api/v1/annotation-tasks/{annot_job_id}/samples").json()["data"]
    assert samples["total"] == SPLIT_SAMPLE_COUNT
    annot = _annot_row(db_engine, annot_job_id)
    with Session(db_engine) as session:
        rows = session.exec(select(Sample).where(Sample.split_task_id == split.id)).all()
        assert all(s.annotation_task_id == annot.id for s in rows)


def test_import_validation(
    override_get_session, override_get_current_user
) -> None:
    annot_job_id = _create_annotation_task("manual")
    resp = client.post(
        f"/api/v1/annotation-tasks/{annot_job_id}/import", json={"source": "bad"}
    )
    assert resp.status_code == 400 and resp.json()["code"] == 40000
    resp = client.post(
        f"/api/v1/annotation-tasks/{annot_job_id}/import",
        json={"source": "files", "object_keys": []},
    )
    assert resp.status_code == 400 and resp.json()["code"] == 40000
    resp = client.post(
        f"/api/v1/annotation-tasks/{annot_job_id}/import",
        json={"source": "split_task", "split_task_id": "job_deadbeef"},
    )
    assert resp.status_code == 404 and resp.json()["code"] == 40401


# ---------- 标签类别 / AI 预标注 / 保存标注 ----------


def test_label_categories(override_get_session, override_get_current_user) -> None:
    data = client.get("/api/v1/label-categories").json()["data"]
    assert len(data) == 5
    names = {c["name"] for c in data}
    assert names == {"焊瘤", "气孔", "未熔合", "咬边", "正常"}


def test_ai_pretag_deterministic(
    db_engine,
    override_get_session,
    override_get_current_user,
) -> None:
    annot_job_id = _create_annotation_task("manual")
    client.post(
        f"/api/v1/annotation-tasks/{annot_job_id}/import",
        json={"source": "files", "object_keys": ["processed/WLD-20260815-0248/split/1.jpg"]},
    )
    sample_id = client.get(f"/api/v1/annotation-tasks/{annot_job_id}/samples").json()["data"]["items"][0]["id"]

    first = client.post(
        f"/api/v1/annotation-tasks/{annot_job_id}/samples/{sample_id}/ai-pretag"
    ).json()["data"]
    second = client.post(
        f"/api/v1/annotation-tasks/{annot_job_id}/samples/{sample_id}/ai-pretag"
    ).json()["data"]
    assert len(first) == 2

    def _semantic(annotations):
        # 每次预标注是"删旧插新"（id 重新分配），但内容确定性一致——比内容不比 id。
        return [(a["category"], a["box"], a["confidence"]) for a in annotations]

    assert _semantic(first) == _semantic(second)

    # 落库：annotator=AI预标注，GET 样本可见 2 条 + 样本级 confidence=均值
    detail = client.get(
        f"/api/v1/annotation-tasks/{annot_job_id}/samples/{sample_id}"
    ).json()["data"]
    assert len(detail["annotations"]) == 2
    assert all(a["annotator"] == "AI预标注" for a in detail["annotations"])
    confs = [a["confidence"] for a in detail["annotations"]]
    assert detail["confidence"] == round(sum(confs) / 2, 3)


def test_save_labels_replace_and_confidence_semantics(
    db_engine,
    override_get_session,
    override_get_current_user,
) -> None:
    annot_job_id = _create_annotation_task("manual")
    client.post(
        f"/api/v1/annotation-tasks/{annot_job_id}/import",
        json={"source": "files", "object_keys": ["processed/WLD-20260815-0248/split/1.jpg"]},
    )
    sample_id = client.get(f"/api/v1/annotation-tasks/{annot_job_id}/samples").json()["data"]["items"][0]["id"]

    pretag = client.post(
        f"/api/v1/annotation-tasks/{annot_job_id}/samples/{sample_id}/ai-pretag"
    ).json()["data"]
    pretag_by_cat = {a["category"]: a["confidence"] for a in pretag}
    cats = list(pretag_by_cat)
    cat1, cat2 = cats[0], cats[1]

    # 保存人工标注：cat1 不显式给 confidence（沿用预标注值），cat2 覆盖为 0.5
    resp = client.post(
        f"/api/v1/annotation-tasks/{annot_job_id}/samples/{sample_id}/labels",
        json={
            "labels": [
                {"category": cat1, "box": [10, 20, 30, 40]},
                {"category": cat2, "box": [50, 60, 70, 80], "confidence": 0.5},
            ]
        },
    )
    assert resp.status_code == 200, resp.text[:300]
    saved = resp.json()["data"]
    assert len(saved) == 2
    assert all(a["annotator"] == "林工" for a in saved)

    # 回读：替换成功 + 置信度语义（缺省沿用预标注 / 覆盖取新值 + 均值更新）
    detail = client.get(
        f"/api/v1/annotation-tasks/{annot_job_id}/samples/{sample_id}"
    ).json()["data"]
    by_cat = {a["category"]: a for a in detail["annotations"]}
    assert by_cat[cat1]["confidence"] == pretag_by_cat[cat1]
    assert by_cat[cat2]["confidence"] == 0.5
    expected = round((pretag_by_cat[cat1] + 0.5) / 2, 3)
    assert detail["confidence"] == expected
    # 替换：仅剩 2 条（预标注被覆盖）
    assert len(detail["annotations"]) == 2


def test_save_labels_validation(
    override_get_session, override_get_current_user
) -> None:
    annot_job_id = _create_annotation_task("manual")
    client.post(
        f"/api/v1/annotation-tasks/{annot_job_id}/import",
        json={"source": "files", "object_keys": ["processed/WLD-20260815-0248/split/1.jpg"]},
    )
    sample_id = client.get(f"/api/v1/annotation-tasks/{annot_job_id}/samples").json()["data"]["items"][0]["id"]
    url = f"/api/v1/annotation-tasks/{annot_job_id}/samples/{sample_id}/labels"

    resp = client.post(url, json={"labels": [{"category": "不存在的类别", "box": [1, 2, 3, 4]}]})
    assert resp.status_code == 400 and resp.json()["code"] == 40000
    resp = client.post(url, json={"labels": [{"category": "焊瘤", "box": [1, 2, 3]}]})
    assert resp.status_code == 400 and resp.json()["code"] == 40000

    # confidence 越界（>=10 或 <0）会撞 Numeric(4,3) 列 → 400 而非 500
    resp = client.post(
        url, json={"labels": [{"category": "焊瘤", "box": [1, 2, 3, 4], "confidence": 10}]}
    )
    assert resp.status_code == 400 and resp.json()["code"] == 40000
    assert "0~1" in resp.json()["message"]
    resp = client.post(
        url, json={"labels": [{"category": "焊瘤", "box": [1, 2, 3, 4], "confidence": -0.1}]}
    )
    assert resp.status_code == 400 and resp.json()["code"] == 40000

    # 边界 0 / 1 仍合法（不被过度收紧）
    resp = client.post(
        url, json={"labels": [{"category": "焊瘤", "box": [1, 2, 3, 4], "confidence": 0}]}
    )
    assert resp.status_code == 200, resp.text[:300]
    resp = client.post(
        url, json={"labels": [{"category": "焊瘤", "box": [1, 2, 3, 4], "confidence": 1}]}
    )
    assert resp.status_code == 200, resp.text[:300]


# ---------- 样本分页 ----------


def test_get_samples_paginated(
    override_get_session, override_get_current_user
) -> None:
    annot_job_id = _create_annotation_task("manual")
    keys = [f"processed/WLD-20260815-0248/split/{i}.jpg" for i in range(25)]
    client.post(
        f"/api/v1/annotation-tasks/{annot_job_id}/import",
        json={"source": "files", "object_keys": keys},
    )
    page1 = client.get(
        f"/api/v1/annotation-tasks/{annot_job_id}/samples", params={"page": 1, "page_size": 10}
    ).json()["data"]
    assert page1["total"] == 25 and page1["page"] == 1 and page1["page_size"] == 10
    assert len(page1["items"]) == 10
    page3 = client.get(
        f"/api/v1/annotation-tasks/{annot_job_id}/samples", params={"page": 3, "page_size": 10}
    ).json()["data"]
    assert len(page3["items"]) == 5
    # page_size 超上限 100 被钳制，不报错
    big = client.get(
        f"/api/v1/annotation-tasks/{annot_job_id}/samples", params={"page": 1, "page_size": 1000}
    ).json()["data"]
    assert big["page_size"] == 100 and big["total"] == 25


# ---------- 404 ----------


def test_annotation_404s(
    db_engine,
    override_get_session,
    override_get_current_user,
) -> None:
    annot_job_id = _create_annotation_task("manual")
    client.post(
        f"/api/v1/annotation-tasks/{annot_job_id}/import",
        json={"source": "files", "object_keys": ["processed/WLD-20260815-0248/split/1.jpg"]},
    )
    sample_id = client.get(f"/api/v1/annotation-tasks/{annot_job_id}/samples").json()["data"]["items"][0]["id"]

    resp = client.get("/api/v1/annotation-tasks/job_deadbeef/samples")
    assert resp.status_code == 404 and resp.json()["code"] == 40401
    resp = client.get("/api/v1/annotation-tasks/job_deadbeef/samples/1")
    assert resp.status_code == 404 and resp.json()["code"] == 40401
    resp = client.get(f"/api/v1/annotation-tasks/{annot_job_id}/samples/999999")
    assert resp.status_code == 404 and resp.json()["code"] == 40401
    resp = client.post(
        f"/api/v1/annotation-tasks/{annot_job_id}/samples/999999/ai-pretag"
    )
    assert resp.status_code == 404 and resp.json()["code"] == 40401
    resp = client.get(f"/api/v1/annotation-tasks/job_deadbeef")
    assert resp.status_code == 404 and resp.json()["code"] == 40401
    # 样本属于其它任务：跨任务访问 404
    other = _create_annotation_task("manual")
    client.post(
        f"/api/v1/annotation-tasks/{other}/import",
        json={"source": "files", "object_keys": ["processed/WLD-20260815-0248/split/other.jpg"]},
    )
    other_sample = client.get(f"/api/v1/annotation-tasks/{other}/samples").json()["data"]["items"][0]["id"]
    resp = client.get(f"/api/v1/annotation-tasks/{annot_job_id}/samples/{other_sample}")
    assert resp.status_code == 404 and resp.json()["code"] == 40401


# ---------- 失败：handler 抛异常 → job failed ----------


def test_split_and_annotation_job_failure_records_error(
    db_engine,
    override_get_session,
    override_get_current_user,
    executor_sessionlocal,
    monkeypatch,
) -> None:
    def _boom(_job_id, _session):
        raise RuntimeError("模拟内核崩溃")

    monkeypatch.setitem(executor_mod.HANDLERS, "split", _boom)
    vid = _version_id_by_no(WELD_0248)
    split_job_id = _create_split_task(WELD_0248, vid)
    run_job(split_job_id)
    data = client.get(f"/api/v1/split-tasks/{split_job_id}").json()["data"]
    assert data["status"] == "failed"
    assert data["error"] == {"message": "模拟内核崩溃"}

    monkeypatch.setitem(executor_mod.HANDLERS, "annotation", _boom)
    annot_job_id = _create_annotation_task("manual")
    run_job(annot_job_id)
    data = client.get(f"/api/v1/annotation-tasks/{annot_job_id}").json()["data"]
    assert data["status"] == "failed"
    assert data["error"] == {"message": "模拟内核崩溃"}


# ---------- 未登录 ----------


def test_split_annotation_endpoints_require_login(db_engine, override_get_session) -> None:
    # 不 override get_current_user：无 Authorization 头 → 401（版本 id 用 seed 固定值 1，
    # 0248 的 v1.0 是首条；认证在业务逻辑前抛，无需真实 id）。
    url = f"/api/v1/welds/{WELD_0248}/versions/1/split-tasks"
    cases = [
        ("post", url, {"fixed_rate": 25, "task_format": "目标检测"}),
        ("get", "/api/v1/split-tasks/job_any", None),
        ("get", "/api/v1/label-categories", None),
        ("post", "/api/v1/annotation-tasks", {"source": "manual"}),
        ("post", "/api/v1/annotation-tasks/job_any/import", {"source": "files", "object_keys": ["a.jpg"]}),
        ("get", "/api/v1/annotation-tasks/job_any/samples", None),
        ("get", "/api/v1/annotation-tasks/job_any/samples/1", None),
        ("post", "/api/v1/annotation-tasks/job_any/samples/1/ai-pretag", None),
        ("post", "/api/v1/annotation-tasks/job_any/samples/1/labels", {"labels": []}),
        ("get", "/api/v1/annotation-tasks/job_any", None),
    ]
    for method, path, body in cases:
        resp = client.request(method, path, json=body)
        assert resp.status_code == 401, f"{method} {path}: {resp.text[:200]}"
        assert resp.json()["code"] == 40100
