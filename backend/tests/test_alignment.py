"""Task 13：Job 执行器 + 对齐任务（模拟）。

内存 SQLite + StaticPool + 真实 app TestClient（同 test_analysis / test_welds）。
`seed_all` 造演示数据（4 焊缝，0248 版本链 v1.0~v1.3、latest=v1.3）后 override
`get_session` / `get_current_user`；并把 `app.jobs.executor.SessionLocal` 指到同一
测试引擎（`run_job` 用它开独立 session，**不启动**后台轮询线程）。

覆盖：
- `POST …/alignment-tasks` → `{job_id}` + job 处于 pending；`run_job` 后 status=succeeded、
  result 内嵌 events/tracks/assets/version、`alignment_tasks.assets` 非空；
  自动多出 **v1.4 时间对齐** 版本且 `data_records.latest_version_id` 指向它；
- handler 抛异常 → job 结束 failed 且 error 记录（monkeypatch HANDLERS["alignment"]）；
- weld/version 不存在 → 40401/40402；未知 task_id → 40401；未登录 → 40100。
"""

import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, select

import app.jobs.executor as executor_mod
from app.api.deps import get_current_user
from app.core.db import get_session
from app.core.seed import seed_all
from app.jobs.executor import run_job
from app.main import app
from app.models import DataRecord, DataVersion, User
from app.models.analysis import AlignmentTask
from app.models.jobs import Job

client = TestClient(app)

WELD_0248 = "WLD-20260815-0248"
WELD_0245 = "WLD-20260814-0245"


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


def _version_id_by_no(weld_id, version_no="v1.0"):
    versions = client.get(f"/api/v1/welds/{weld_id}/versions").json()["data"]
    for v in versions:
        if v["version_no"] == version_no:
            return v["id"]
    raise AssertionError(f"{version_no} not found for {weld_id}")


def _post_alignment_task(weld_id, version_id, modalities):
    resp = client.post(
        f"/api/v1/welds/{weld_id}/versions/{version_id}/alignment-tasks",
        json={"modalities": modalities},
    )
    assert resp.status_code == 200, resp.text[:300]
    job_id = resp.json()["data"]["job_id"]
    assert job_id.startswith("job_")
    return job_id


# ---------- 端到端：创建 → run_job → succeeded + 自动版本 ----------


def test_alignment_task_end_to_end(
    db_engine,
    override_get_session,
    override_get_current_user,
    executor_sessionlocal,
    monkeypatch,
) -> None:
    storage = FakeStorage()
    monkeypatch.setattr("app.storage.get_storage", lambda: storage)
    vid = _version_id_by_no(WELD_0248)
    job_id = _post_alignment_task(WELD_0248, vid, ["video", "timeseries"])

    # 创建后 pending（尚未执行）
    pending = client.get(f"/api/v1/alignment-tasks/{job_id}").json()["data"]
    assert pending["type"] == "alignment"
    assert pending["status"] == "pending"
    assert pending["progress"] == 0
    assert pending["result"] is None

    # 同步执行（测试入口，不启动轮询线程）
    run_job(job_id)

    # Job succeeded，result 内嵌域字段
    done = client.get(f"/api/v1/alignment-tasks/{job_id}").json()["data"]
    assert done["status"] == "succeeded"
    assert done["progress"] == 100
    assert done["finished_at"].endswith("Z")
    result = done["result"]
    assert result["events"] == {"arc": 0.42, "weld_segment": [0.78, 4.28], "tail": 4.86}
    assert result["tracks"]
    assert result["assets"]
    assert result["version"]["action"] == "时间对齐"
    # 对齐产物对象键前缀（OSS 设计：processed/{weld_id}/align/...）
    assert all(a.startswith(f"processed/{WELD_0248}/align/") for a in result["assets"])
    assert [key for key, _data, _content_type in storage.uploads] == result["assets"]

    # alignment_tasks.assets / events 落库（直查）
    with Session(db_engine) as session:
        tasks = session.exec(select(AlignmentTask)).all()
        assert len(tasks) == 1
        assert tasks[0].assets
        assert tasks[0].events == result["events"]

    # 自动多出 v1.4「时间对齐」版本，且 latest_version_id 指向它
    versions = client.get(f"/api/v1/welds/{WELD_0248}/versions").json()["data"]
    nos = [v["version_no"] for v in versions]
    assert "v1.4" in nos
    aligned = next(v for v in versions if v["version_no"] == "v1.4")
    assert aligned["action"] == "时间对齐"
    assert aligned["operator"] == "算法任务"
    detail = client.get(f"/api/v1/welds/{WELD_0248}").json()["data"]
    assert detail["latest_version_id"] == aligned["id"]


# ---------- 失败：handler 抛异常 → job failed + error ----------


def test_alignment_job_failure_records_error(
    db_engine,
    override_get_session,
    override_get_current_user,
    executor_sessionlocal,
    monkeypatch,
) -> None:
    vid = _version_id_by_no(WELD_0248)
    job_id = _post_alignment_task(WELD_0248, vid, ["video"])

    def _boom(_job_id, _session):
        raise RuntimeError("模拟对齐内核崩溃")

    monkeypatch.setitem(executor_mod.HANDLERS, "alignment", _boom)
    run_job(job_id)

    data = client.get(f"/api/v1/alignment-tasks/{job_id}").json()["data"]
    assert data["status"] == "failed"
    assert data["error"] == {"message": "模拟对齐内核崩溃"}
    assert data["result"] is None
    assert data["finished_at"].endswith("Z")

    # 直查：job 落库为 failed（不滞留 running）
    with Session(db_engine) as session:
        job = session.exec(
            select(Job).where(Job.job_uid == job_id)
        ).first()
        assert job is not None
        assert job.status == "failed"


# ---------- 404 ----------


def test_alignment_storage_failure_cleans_uploaded_objects_and_keeps_db_consistent(
    db_engine,
    override_get_session,
    override_get_current_user,
    executor_sessionlocal,
    monkeypatch,
) -> None:
    storage = FakeStorage(fail_after=1)
    monkeypatch.setattr("app.storage.get_storage", lambda: storage)
    vid = _version_id_by_no(WELD_0248)
    job_id = _post_alignment_task(WELD_0248, vid, ["video", "timeseries"])

    run_job(job_id)

    data = client.get(f"/api/v1/alignment-tasks/{job_id}").json()["data"]
    assert data["status"] == "failed"
    assert data["error"] == {"message": "模拟 MinIO 写入失败"}
    assert data["result"] is None
    assert [key for key, _data, _content_type in storage.uploads] == [
        f"processed/{WELD_0248}/align/video.mp4"
    ]
    assert storage.deletes == [f"processed/{WELD_0248}/align/video.mp4"]

    with Session(db_engine) as session:
        record = session.exec(select(DataRecord).where(DataRecord.weld_id == WELD_0248)).first()
        assert record is not None
        versions = session.exec(select(DataVersion).where(DataVersion.record_id == record.id)).all()
        assert [v.version_no for v in versions] == ["v1.0", "v1.1", "v1.2", "v1.3"]
        task = session.exec(select(AlignmentTask)).first()
        assert task is not None
        assert task.assets is None
        assert task.events is None


def test_create_alignment_rejects_missing_inputs_with_4xx(
    override_get_session, override_get_current_user
) -> None:
    vid = _version_id_by_no(WELD_0245)
    resp = client.post(
        f"/api/v1/welds/{WELD_0245}/versions/{vid}/alignment-tasks",
        json={"modalities": ["video", "timeseries"]},
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["code"] == 40000
    assert "输入" in resp.json()["message"]


# ---------- 404 ----------


def test_create_alignment_unknown_weld_or_version(
    override_get_session, override_get_current_user
) -> None:
    vid = _version_id_by_no(WELD_0248)
    resp = client.post(
        "/api/v1/welds/WLD-NOPE-0000/versions/1/alignment-tasks",
        json={"modalities": ["video"]},
    )
    assert resp.status_code == 404 and resp.json()["code"] == 40401
    resp = client.post(
        f"/api/v1/welds/{WELD_0248}/versions/999999/alignment-tasks",
        json={"modalities": ["video"]},
    )
    assert resp.status_code == 404 and resp.json()["code"] == 40402


def test_get_alignment_task_unknown_404(
    override_get_session, override_get_current_user
) -> None:
    resp = client.get("/api/v1/alignment-tasks/job_deadbeef")
    assert resp.status_code == 404
    assert resp.json()["code"] == 40401


# ---------- 原子领单（review 修复）：已成功/非 pending 的 job 不会被重复执行 ----------


def test_alignment_create_is_idempotent_for_pending_and_succeeded_jobs(
    db_engine,
    override_get_session,
    override_get_current_user,
    executor_sessionlocal,
    monkeypatch,
) -> None:
    storage = FakeStorage()
    monkeypatch.setattr("app.storage.get_storage", lambda: storage)
    vid = _version_id_by_no(WELD_0248)
    first = _post_alignment_task(WELD_0248, vid, ["video"])
    second = _post_alignment_task(WELD_0248, vid, ["video"])
    assert second == first

    with Session(db_engine) as session:
        assert len(session.exec(select(AlignmentTask)).all()) == 1

    run_job(first)
    done = client.get(f"/api/v1/alignment-tasks/{first}").json()["data"]
    assert done["status"] == "succeeded"

    third = _post_alignment_task(WELD_0248, vid, ["video"])
    assert third == first
    with Session(db_engine) as session:
        assert len(session.exec(select(AlignmentTask)).all()) == 1


def test_create_alignment_concurrent_requests_return_same_job(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "alignment-concurrency.db"
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

    def _sync_create_job(session, type, result=None):
        if type == "alignment":
            barrier.wait(timeout=2)
        return original_create_job(session, type, result=result)

    monkeypatch.setattr("app.api.v1.analysis.create_job", _sync_create_job)

    results: list[tuple[int, dict]] = []
    errors: list[BaseException] = []

    def _worker() -> None:
        try:
            with TestClient(app) as local_client:
                resp = local_client.post(
                    f"/api/v1/welds/{WELD_0248}/versions/1/alignment-tasks",
                    json={"modalities": ["video"]},
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
        tasks = session.exec(select(AlignmentTask).where(AlignmentTask.version_id == 1)).all()
        assert len(tasks) == 1
        jobs = session.exec(select(Job).where(Job.job_uid == job_ids[0])).all()
        assert len(jobs) == 1



def test_run_job_skips_already_succeeded_job(
    db_engine,
    override_get_session,
    override_get_current_user,
    executor_sessionlocal,
    monkeypatch,
) -> None:
    storage = FakeStorage()
    monkeypatch.setattr("app.storage.get_storage", lambda: storage)
    vid = _version_id_by_no(WELD_0248)
    job_id = _post_alignment_task(WELD_0248, vid, ["video"])

    run_job(job_id)
    done = client.get(f"/api/v1/alignment-tasks/{job_id}").json()["data"]
    assert done["status"] == "succeeded"

    # 再跑一次：原子领单 WHERE status='pending' → rowcount 0 → 跳过，不重复执行
    run_job(job_id)
    again = client.get(f"/api/v1/alignment-tasks/{job_id}").json()["data"]
    assert again["status"] == "succeeded"
    assert again["result"] == done["result"]  # 结果未被改动/重跑

    # 只应有一个「时间对齐」v1.4 版本（未因重复 run_job 再生成 v1.5）
    versions = client.get(f"/api/v1/welds/{WELD_0248}/versions").json()["data"]
    assert "v1.4" in [v["version_no"] for v in versions]
    assert "v1.5" not in [v["version_no"] for v in versions]


# ---------- 执行器线程生命周期（review 修复）：防双轮询 ----------


def test_executor_thread_start_noop_when_running_and_stop_waits(monkeypatch) -> None:
    """start() 在旧线程存活时不重复启动；stop() 只在线程真正退出后丢弃引用。"""
    started = threading.Event()

    def _loop(self):
        started.set()
        while not self._stop.is_set():
            self._stop.wait(0.02)

    monkeypatch.setattr(executor_mod._ExecutorThread, "_loop", _loop)
    et = executor_mod._ExecutorThread()
    et.start()
    assert started.wait(2)
    thread_ref = et._thread

    et.start()  # 已存活 → no-op，不新建线程
    assert et._thread is thread_ref

    et.stop()
    assert et._thread is None  # 线程已退出，引用被清理


def test_executor_thread_stop_timeout_keeps_reference(monkeypatch) -> None:
    """stop() 超时（handler 长跑）保留引用；此时 start() 拒绝二次启动，直到线程自然退出。"""
    monkeypatch.setattr(executor_mod, "_POLL_INTERVAL", 0.01)  # stop 的 join 超时=0.02s
    entered = threading.Event()

    def _loop(self):
        entered.set()
        time.sleep(0.3)  # 无视 _stop，模拟长跑 handler（超过 join 超时）

    monkeypatch.setattr(executor_mod._ExecutorThread, "_loop", _loop)
    et = executor_mod._ExecutorThread()
    et.start()
    assert entered.wait(2)

    et.stop()  # join 0.02s 超时，线程仍在 sleep → 保留引用
    assert et._thread is not None
    assert et._thread.is_alive()

    et.start()  # 线程仍存活 → 拒绝重复启动（防双执行者）
    assert et._thread.is_alive()

    # 清理：等线程自然退出后引用已随 stop 的二次 join 或 start 的检测释放
    et._thread.join(timeout=2)
    assert not et._thread.is_alive()


# ---------- 未登录 ----------


def test_alignment_endpoints_require_login(db_engine, override_get_session) -> None:
    # 不 override get_current_user：无 Authorization 头 → 401 信封（依赖在路由逻辑前抛）。
    resp = client.post(
        f"/api/v1/welds/{WELD_0248}/versions/1/alignment-tasks",
        json={"modalities": ["video"]},
    )
    assert resp.status_code == 401
    assert resp.json()["code"] == 40100
    resp = client.get("/api/v1/alignment-tasks/job_any")
    assert resp.status_code == 401
    assert resp.json()["code"] == 40100
