"""media_prep（视频登记挂载自动转码预览版）端到端测试。

链路：POST raw-files（视频 key）→ media_prep Job → run_job → preview_key 回填
→ POST annotation-tasks(source=video) 锚点样本用 preview_key 播放。

不连远程：内存 SQLite + StaticPool + seed_all + override 依赖 + executor SessionLocal
指向测试引擎 + FakeStorage；转码用 monkeypatch（不真跑 ffmpeg，编码判定走 `_probe_codec` 桩）。
用例走**新建登记**再挂视频（seed 0248 v1.0 已有 0001.mp4，会干扰锚点"第一个视频 key"的选取）。
"""

from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select
import pytest

import app.jobs.executor as executor_mod
from app.api.deps import get_current_user
from app.core.db import get_session
from app.core.seed import seed_all
from app.jobs.executor import run_job
from app.main import app
from app.models import DataVersion, User
from app.models.jobs import Job

client = TestClient(app)

#: mpeg4 源转码出的"预览版"（monkeypatch 假字节，只断言透传上传）
PREVIEW_BYTES = b"\x00\x00\x00\x18ftypisom" + b"moov-fake-preview"
_VIDEO_BYTES = b"\x00\x00\x00\x18ftypisom" + b"mdat" + b"\x00" * 64

_STORAGE: "FakeStorage | None" = None  # 由 fake_storage fixture 注入


class FakeStorage:
    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}

    def upload_stream(self, object_key, fileobj, size, content_type):
        data = fileobj.read()
        self.blobs[object_key] = data
        return object_key

    def get_object(self, object_key: str) -> bytes:
        if object_key not in self.blobs:
            raise FileNotFoundError(object_key)
        return self.blobs[object_key]

    def stat_object(self, object_key: str) -> int:
        return len(self.blobs.get(object_key, b""))


@pytest.fixture()
def db_engine():
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
    def _override():
        with Session(db_engine) as session:
            yield session

    app.dependency_overrides[get_session] = _override
    yield
    app.dependency_overrides.pop(get_session, None)


@pytest.fixture()
def override_get_current_user():
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
def executor_local(db_engine, monkeypatch):
    """run_job 用独立 session，指到同一测试引擎。"""
    monkeypatch.setattr(
        executor_mod,
        "SessionLocal",
        sessionmaker(bind=db_engine, class_=Session, expire_on_commit=False),
    )


@pytest.fixture()
def fake_storage(monkeypatch):
    global _STORAGE
    _STORAGE = FakeStorage()
    # welds.py / media_prep 都 `from app.storage import get_storage` 直取引用，
    # 两个绑定都要 patch（只 patch app.storage 会打到真实 MinIO）
    monkeypatch.setattr("app.storage.get_storage", lambda: _STORAGE)
    monkeypatch.setattr("app.api.v1.welds.get_storage", lambda: _STORAGE)
    return _STORAGE


def _attach_video() -> tuple[str, str]:
    """新建登记 + 挂载视频 key。返回 (registration_no, video_object_key)。"""
    resp = client.post(
        "/api/v1/registrations",
        json={"dataset_id": 1, "source": "产线采集", "weld_name": "media_prep 测试"},
    )
    assert resp.status_code == 200, resp.text[:300]
    reg_no = resp.json()["data"]["registration_no"]
    object_key = f"raw/{reg_no}/pool.mp4"
    _STORAGE.blobs[object_key] = _VIDEO_BYTES
    resp = client.post(
        f"/api/v1/registrations/{reg_no}/raw-files",
        json={"object_keys": [object_key]},
    )
    assert resp.status_code == 200, resp.text[:300]
    return reg_no, object_key


def _prep_job(db_engine) -> Job:
    with Session(db_engine) as session:
        return session.exec(select(Job).where(Job.type == "media_prep")).first()


def _v10_id_of(db_engine, reg_no: str) -> int:
    with Session(db_engine) as session:
        v = session.exec(
            select(DataVersion).where(
                DataVersion.record_id == _record_id(db_engine, reg_no),
                DataVersion.version_no == "v1.0",
            )
        ).first()
        return v.id


def _record_id(db_engine, reg_no: str) -> int:
    from app.models import DataRecord

    with Session(db_engine) as session:
        r = session.exec(
            select(DataRecord).where(DataRecord.registration_no == reg_no)
        ).first()
        return r.id


def _video_anchor_meta(job_id: str) -> dict:
    run_job(job_id)
    items = client.get(
        f"/api/v1/annotation-tasks/{job_id}/samples?page=1"
    ).json()["data"]["items"]
    return next(s for s in items if s["meta"]["mode"] == "video")["meta"]


def test_attach_creates_single_media_prep_job(
    override_get_session, override_get_current_user, fake_storage, executor_local, db_engine
):
    reg_no, video_key = _attach_video()
    job = _prep_job(db_engine)
    assert job.status == "pending"
    assert job.result["object_key"] == video_key
    assert job.result["weld_id"]  # 新登记的 weld_id 已随 job 携带


def test_prep_transcodes_and_anchor_uses_preview(
    override_get_session, override_get_current_user, fake_storage, executor_local,
    db_engine, monkeypatch,
):
    monkeypatch.setattr("app.jobs.media_prep._probe_codec", lambda data: "mpeg4")
    monkeypatch.setattr(
        "app.services.media_probe.transcode_preview",
        lambda data: (PREVIEW_BYTES, {"codec": "mpeg4"}),
    )
    reg_no, video_key = _attach_video()
    preview_key = f"processed/{_weld_id_of(db_engine, reg_no)}/video/pool.preview.mp4"
    run_job(_prep_job(db_engine).job_uid)

    with Session(db_engine) as session:
        job = session.exec(select(Job).where(Job.type == "media_prep")).first()
        assert job.status == "succeeded"
        assert job.result["transcode"] is True
        assert job.result["preview_key"] == preview_key
    assert _STORAGE.blobs[preview_key] == PREVIEW_BYTES

    # 视频标注锚点样本：video_key 用预览版，原始 key 保留在 source_video_key
    resp = client.post(
        "/api/v1/annotation-tasks",
        json={"source": "video", "version_id": _v10_id_of(db_engine, reg_no), "name": "t"},
    )
    assert resp.status_code == 200
    meta = _video_anchor_meta(resp.json()["data"]["job_id"])
    assert meta["video_key"] == preview_key
    assert meta["source_video_key"] == video_key


def _weld_id_of(db_engine, reg_no: str) -> str:
    from app.models import DataRecord

    with Session(db_engine) as session:
        r = session.exec(
            select(DataRecord).where(DataRecord.registration_no == reg_no)
        ).first()
        return r.weld_id


def test_prep_skips_browser_friendly_source(
    override_get_session, override_get_current_user, fake_storage, executor_local,
    db_engine, monkeypatch,
):
    """已是 h264 + faststart（moov 在 mdat 前）→ 不转码，preview_key = 原始 key。"""
    monkeypatch.setattr("app.jobs.media_prep._probe_codec", lambda data: "h264")

    def _boom(data):
        raise AssertionError("browser-friendly source must not be transcoded")

    monkeypatch.setattr("app.services.media_probe.transcode_preview", _boom)
    reg_no, video_key = _attach_video()
    # 覆写为 faststart 形态（moov 在 mdat 前）
    _STORAGE.blobs[video_key] = (
        b"\x00\x00\x00\x18ftypisom" + b"moov-mock-header" + b"mdat" + b"\x00" * 32
    )
    run_job(_prep_job(db_engine).job_uid)
    with Session(db_engine) as session:
        job = session.exec(select(Job).where(Job.type == "media_prep")).first()
        assert job.status == "succeeded"
        assert job.result["transcode"] is False
        assert job.result["preview_key"] == video_key


def test_prep_failure_marks_failed_and_anchor_falls_back(
    override_get_session, override_get_current_user, fake_storage, executor_local,
    db_engine, monkeypatch,
):
    monkeypatch.setattr("app.jobs.media_prep._probe_codec", lambda data: "mpeg4")

    def _fail(data):
        raise RuntimeError("转码失败模拟")

    monkeypatch.setattr("app.services.media_probe.transcode_preview", _fail)
    reg_no, video_key = _attach_video()
    run_job(_prep_job(db_engine).job_uid)
    with Session(db_engine) as session:
        job = session.exec(select(Job).where(Job.type == "media_prep")).first()
        assert job.status == "failed"
        assert "转码失败模拟" in (job.error or {}).get("message", "")

    # 转码失败：锚点回退原始 key（可播性由前端 onError 提示）
    resp = client.post(
        "/api/v1/annotation-tasks",
        json={"source": "video", "version_id": _v10_id_of(db_engine, reg_no)},
    )
    meta = _video_anchor_meta(resp.json()["data"]["job_id"])
    assert meta["video_key"] == video_key
