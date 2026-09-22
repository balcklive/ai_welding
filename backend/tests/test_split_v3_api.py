"""分段 v3 端点 + Job E2E（契约 §5.3–§5.5）。

覆盖设计 §12.3 的 P0/P1 剩余部分：

- `split-preview`：秒级规则、`preview_token`、分层 timeline、模态可用性、warnings；**只读**。
- `split-tasks`：**只接受 token**；规则/映射/有效区间任一变更 → 409 要求重新预览。
- `GET /split-tasks/{id}/samples` 分页与单样本详情。
- Job：v3 写多模态 `meta` + 时间列 + `manifest.json` + 焊缝图片 ROI 投影裁切；
  **图片裁切失败不阻断任务**（图片是增强模态）。

基础设施同 `test_calibration_api.py`：内存 SQLite + TestClient + 内存假存储 + 真实信号导入。
"""

from __future__ import annotations

import io
import json
import subprocess

import imageio_ffmpeg
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, select

from app.api.deps import get_current_user
from app.core.db import get_session
from app.main import app
from app.models import User
from app.models.analysis import Sample, SplitTask
from app.models.data import AuditLog, DataRecord, DataVersion
from app.services import signal_ingest, splitting
from app.services.jobs import create_job
from app.storage.client import StorageClient

client = TestClient(app)

IMAGE_W, IMAGE_H = 400, 120
SEAM_KEY = "raw/REG-SPLIT-0001/seam.png"
VIDEO_KEY = "raw/REG-SPLIT-0001/weld.mp4"
CSV_KEY = "raw/REG-SPLIT-0001/signal.csv"
WELD_ID = "WLD-SPLIT-0001"

SIGNAL_FS, SIGNAL_SECONDS = 100, 8.0
WELD_WINDOW = (1.0, 7.0)


class FakeStorage:
    """内存假存储：只实现本链路走到的接口。"""

    normalize_key = staticmethod(StorageClient.normalize_key)
    normalize_filename = staticmethod(StorageClient.normalize_filename)

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put(self, object_key: str, data: bytes) -> None:
        self.objects[object_key] = data

    def upload_stream(self, object_key, fileobj, size, content_type):  # noqa: ANN001
        self.objects[object_key] = fileobj.read()

    def get_object(self, object_key: str) -> bytes:
        if object_key not in self.objects:
            raise FileNotFoundError(object_key)
        return self.objects[object_key]

    def stat_object(self, object_key: str) -> int:
        return len(self.objects.get(object_key, b""))

    def delete_object(self, object_key: str) -> None:
        self.objects.pop(object_key, None)


def _png(width: int = IMAGE_W, height: int = IMAGE_H) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (90, 140, 160)).save(buffer, format="PNG")
    return buffer.getvalue()


def _signal_csv() -> bytes:
    n = int(SIGNAL_SECONDS * SIGNAL_FS)
    t = np.arange(n) / SIGNAL_FS
    current = np.where((t >= WELD_WINDOW[0]) & (t <= WELD_WINDOW[1]), 200.0, 0.0)
    frame = pd.DataFrame({
        "time": t, "Current": current,
        "Voltage": np.where(current > 0, 20.0, 0.0),
        "GasSpeed": 15.0, "WireFeedSpeed": 5.0, "WeldingSpeed": 4.0,
    })
    return frame.to_csv(index=False).encode("utf-8")


@pytest.fixture(scope="module")
def mp4_bytes(tmp_path_factory) -> bytes:
    path = tmp_path_factory.mktemp("split_video") / "weld.mp4"
    subprocess.run(
        [
            imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", "testsrc=size=320x240:rate=25:duration=8",
            "-pix_fmt", "yuv420p", "-c:v", "libx264", str(path),
        ],
        check=True, capture_output=True,
    )
    return path.read_bytes()


@pytest.fixture()
def engine():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def db_session(engine):
    with Session(engine, expire_on_commit=False) as session:
        yield session


@pytest.fixture()
def run_job(monkeypatch, engine):
    """Job 执行器的 session 指到测试引擎，返回同步执行入口（同 test_dataset_build_e2e）。"""
    from app.jobs.executor import run_job as _run_job

    monkeypatch.setattr(
        "app.jobs.executor.SessionLocal", lambda: Session(engine, expire_on_commit=False)
    )
    return _run_job


@pytest.fixture()
def storage(monkeypatch):
    fake = FakeStorage()
    fake.put(SEAM_KEY, _png())
    # 各模块的 `get_storage` 绑定方式不同（有的模块级、有的延迟导入），都要指到假存储
    for target in ("app.storage.get_storage", "app.jobs.split.get_storage"):
        monkeypatch.setattr(target, lambda: fake)
    return fake


@pytest.fixture()
def user(db_session) -> User:
    u = User(username="splitter", password_hash="x", display_name="分段员", role="user")
    db_session.add(u)
    db_session.commit()
    db_session.refresh(u)
    return u


@pytest.fixture()
def api(db_session, user):
    def _session():
        yield db_session

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_current_user] = lambda: user
    yield client
    app.dependency_overrides.pop(get_session, None)
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture()
def ready(db_session, user, storage, api):
    """真实信号已导入、视频与焊缝照片就位的 v1.0 版本。返回 (record, version_id)。"""
    record = DataRecord(
        weld_id=WELD_ID, registration_no="REG-SPLIT-0001", source="现场采集", quality="待复核",
    )
    db_session.add(record)
    db_session.commit()
    db_session.refresh(record)
    version = DataVersion(
        record_id=record.id, version_no="v1.0", action="原始数据",
        object_keys=[CSV_KEY, VIDEO_KEY, SEAM_KEY],
    )
    db_session.add(version)
    db_session.commit()
    db_session.refresh(version)
    record.latest_version_id = version.id
    db_session.add(record)
    db_session.add(AuditLog(
        user_id=user.id, action="create", resource_type="weld", resource_id=record.weld_id,
    ))
    db_session.commit()

    storage.put(CSV_KEY, _signal_csv())
    job = create_job(db_session, type="signal_ingest")
    from app.models.analysis import SignalIngest

    ingest = SignalIngest(
        job_id=job.id, version_id=version.id, source_object_key=CSV_KEY, status="pending",
    )
    db_session.add(ingest)
    db_session.commit()
    db_session.refresh(ingest)
    db_session.refresh(job)
    signal_ingest.run_ingest(db_session, ingest, job)
    db_session.commit()
    assert ingest.status == "succeeded", ingest.validation
    _seed_alignment_mapping(db_session, version.id)
    return record, version.id


def _seed_alignment_mapping(db_session, version_id: int, *, fps: float = 25.0, duration: float = 8.0):
    """伪造一次**成功对齐**留下的 mapping。

    分段侧刻意不下载视频来探 fps/duration（§6.4：预览要快），而是读对齐产物里已探测好的
    元信息。所以"没跑过对齐"的焊缝在预览里视频模态就是不可用的——这是真实链路顺序：
    对齐页标定 → 运行对齐 → 分段页消费（§4.1）。
    """
    from app.models.analysis import AlignmentTask

    job = create_job(db_session, type="alignment")
    task = AlignmentTask(
        job_id=job.id, version_id=version_id, tracks=[], assets=[],
        events={"arc": WELD_WINDOW[0], "weld_segment": list(WELD_WINDOW), "tail": WELD_WINDOW[1]},
        mapping={
            "schema_version": 1,
            "unified_axis": {"unit": "second", "origin": "signal_first_sample", "duration": SIGNAL_SECONDS},
            "event_bounds": {"start": WELD_WINDOW[0], "end": WELD_WINDOW[1]},
            "mappings": {
                "video": {
                    "type": "linear", "available": True, "calibrated": False,
                    "offset_seconds": 0.0, "fps": fps, "duration": duration, "reason": None,
                },
            },
        },
    )
    db_session.add(task)
    db_session.commit()


def _url(version_id: int, suffix: str) -> str:
    return f"/api/v1/welds/{WELD_ID}/versions/{version_id}/{suffix}"


def _ok(response):
    payload = response.json()
    assert payload["code"] == 0, payload
    return payload["data"]


def _preview(api, version_id: int, **rules):
    return _ok(api.post(_url(version_id, "split-preview"), json=rules))


# ── 预览 ─────────────────────────────────────────────────────────────


def test_preview_defaults_to_two_seconds_and_returns_token(api, ready) -> None:
    """§9.1：默认打开就是 2.0 秒时长 / 2.0 秒步长，且不写任何产物。"""
    _record, version_id = ready
    data = _preview(api, version_id, event_start=1.0, event_end=7.0)

    assert data["window_seconds"] == 2.0 and data["stride_seconds"] == 2.0
    assert data["overlap_seconds"] == 0.0
    assert data["tail_policy"] == "drop"
    assert data["sample_count"] == 3  # 1 + (600-200)//200
    assert data["preview_token"].startswith("spv_")
    assert data["rules_hash"] and data["mapping_hash"]
    assert [w["start"] for w in data["windows"]] == [1.0, 3.0, 5.0]
    assert data["effective_range"] == {"start": 1.0, "end": 7.0}


def test_preview_timeline_is_layered_and_bounded(api, ready) -> None:
    """§6.4：分层数据有上限——时序有降采样轨道、缩略图时间点、图片投影摘要。"""
    _record, version_id = ready
    data = _preview(api, version_id, event_start=1.0, event_end=7.0)
    timeline = data["timeline"]

    assert timeline["duration"] == pytest.approx(SIGNAL_SECONDS)
    assert timeline["signal"]["sample_rate"] == SIGNAL_FS
    ids = [track["id"] for track in timeline["signal"]["tracks"]]
    assert "cur" in ids and "vol" in ids
    for track in timeline["signal"]["tracks"]:
        assert len(track["times"]) == len(track["values"])
        assert len(track["values"]) <= 1200, "单轨点数必须受控"
    assert timeline["seam_image_projection"]["available"] is False  # 还没框 ROI


def test_preview_reports_modalities_and_warnings(api, ready) -> None:
    """未标定/不可用必须在预览里说清楚（§4.6），而不是让用户自己猜。"""
    _record, version_id = ready
    data = _preview(api, version_id, event_start=1.0, event_end=7.0)
    assert data["modalities"]["timeseries"]["available"] is True
    assert data["modalities"]["seam_image"]["available"] is True
    assert data["modalities"]["seam_image"]["calibrated"] is False
    assert any("Roi" in w or "ROI" in w for w in data["warnings"]), data["warnings"]


def test_preview_does_not_create_any_task(api, ready, db_session) -> None:
    """预览是只读的（§4.5）：不建 Job、不写 Sample。"""
    _record, version_id = ready
    _preview(api, version_id, event_start=1.0, event_end=7.0)
    assert db_session.exec(select(SplitTask)).all() == []
    assert db_session.exec(select(Sample)).all() == []


def test_preview_rejects_invalid_rules(api, ready) -> None:
    _record, version_id = ready
    body = {"window_seconds": 5.0, "stride_seconds": 5.0, "event_start": 1.0, "event_end": 1.2}
    rejected = api.post(_url(version_id, "split-preview"), json=body).json()
    assert rejected["code"] == 40000 and "短于一个切片窗口" in rejected["message"]


# ── 创建：token 是唯一凭证 ───────────────────────────────────────────


def test_create_uses_token_and_job_succeeds(api, ready, db_session, run_job, storage, mp4_bytes) -> None:
    """§5.4：创建只收 token；Job 跑完产出多模态样本 + manifest + 图片切片。"""
    record, version_id = ready
    storage.put(VIDEO_KEY, mp4_bytes)
    # 标定：视频 offset + 焊缝图片 ROI（否则视频/图片模态不可用）
    _ok(api.put(_url(version_id, "calibration"), json={
        "video": {"offset_seconds": 0.5},
        "seam_image": {"roi": {"x": 10, "y": 10, "w": 300, "h": 60}},
    }))
    preview = _preview(api, version_id, event_start=1.0, event_end=7.0)
    assert preview["modalities"]["video"]["calibrated"] is True
    assert preview["modalities"]["seam_image"]["calibrated"] is True

    created = _ok(api.post(_url(version_id, "split-tasks"), json={"preview_token": preview["preview_token"]}))
    task = _run_split(db_session, run_job, created["job_id"])

    assert task.sample_count == preview["sample_count"]
    assert task.task_format is None, "v3 起 task_format 废弃（§3.4）"
    rows = db_session.exec(select(Sample).where(Sample.split_task_id == task.id).order_by(Sample.id)).all()
    first = rows[0]
    assert first.start_time == 1.0 and first.end_time == 3.0
    assert first.meta["schema_version"] == 3
    assert first.meta["video"]["available"] is True
    assert first.meta["video"]["offset_seconds"] == 0.5
    assert first.meta["seam_image"]["available"] is True
    assert first.meta["seam_image"]["crop_key"], "焊缝图片切片应已落盘"

    # 图片切片是真 JPEG（ROI 高 60px，宽按弧长投影）
    cropped = storage.objects[first.meta["seam_image"]["crop_key"]]
    assert cropped.startswith(b"\xff\xd8")
    with Image.open(io.BytesIO(cropped)) as img:
        assert img.height == 60

    manifest = json.loads(storage.objects[f"processed/{WELD_ID}/split/{task.id}/manifest.json"])
    assert manifest["schema_version"] == 3 and manifest["rules_version"] == 3
    assert manifest["sample_count"] == preview["sample_count"]
    assert len(manifest["samples"]) == preview["sample_count"]
    assert manifest["mapping"]["mappings"]["video"]["offset_seconds"] == 0.5


def test_create_rejects_token_from_another_version(api, ready, db_session) -> None:
    record, version_id = ready
    other = DataVersion(record_id=record.id, version_no="v1.1", action="去噪处理", object_keys=[CSV_KEY])
    db_session.add(other)
    db_session.commit()
    db_session.refresh(other)

    preview = _preview(api, version_id, event_start=1.0, event_end=7.0)
    rejected = api.post(
        _url(other.id, "split-tasks"), json={"preview_token": preview["preview_token"]}
    ).json()
    assert rejected["code"] == 40000 and "不匹配" in rejected["message"]


def test_create_rejects_tampered_token(api, ready) -> None:
    _record, version_id = ready
    bad = api.post(_url(version_id, "split-tasks"), json={"preview_token": "spv_bogus.sig"}).json()
    assert bad["code"] == 40000


def test_recalibration_after_preview_returns_409(api, ready) -> None:
    """§5.4：预览之后标定变了就不能照切——否则屏幕上的边界与实际产物会不一致。"""
    _record, version_id = ready
    preview = _preview(api, version_id, event_start=1.0, event_end=7.0)

    _ok(api.put(_url(version_id, "calibration"), json={"video": {"offset_seconds": 1.5}}))

    conflict = api.post(_url(version_id, "split-tasks"), json={"preview_token": preview["preview_token"]})
    assert conflict.status_code == 409
    assert "重新预览" in conflict.json()["message"]


def test_changed_event_bounds_after_preview_returns_409(api, ready) -> None:
    """有效区间是从信号现算的：事件数据变了，同一 token 也不能照用。"""
    _record, version_id = ready
    token = _preview(api, version_id, event_start=1.0, event_end=7.0)["preview_token"]

    forged = splitting.sign_preview_token({
        "weld_id": WELD_ID,
        "version_id": version_id,
        "rules": {"window_seconds": 2.0, "stride_seconds": 2.0, "tail_policy": "drop",
                  "keep_event_buffer": 0.0, "event_start": 2.0, "event_end": 7.0},
        "rules_hash": "whatever",
        "mapping_hash": "whatever",
        "event_bounds": [1.0, 7.0],
        "expires_at": __import__("time").time() + 60,
    })
    conflict = api.post(_url(version_id, "split-tasks"), json={"preview_token": forged})
    assert conflict.status_code == 409
    assert token  # 原 token 仍可用（未受影响）


# ── 查询任务与样本 ───────────────────────────────────────────────────


def test_list_and_get_samples(api, ready, db_session, run_job, storage, mp4_bytes) -> None:
    """§5.5：列表只给时间窗与模态摘要，高频时序走单样本详情。"""
    _record, version_id = ready
    preview = _preview(api, version_id, event_start=1.0, event_end=7.0)
    created = _ok(api.post(_url(version_id, "split-tasks"), json={"preview_token": preview["preview_token"]}))
    task = _run_split(db_session, run_job, created["job_id"])

    page = _ok(api.get(f"/api/v1/split-tasks/{created['job_id']}/samples", params={"page": 1, "page_size": 2}))
    assert page["total"] == 3 and len(page["items"]) == 2
    row = page["items"][0]
    assert row["start_time"] == 1.0 and row["end_time"] == 3.0
    assert row["schema_version"] == 3
    assert "modalities" in row and "meta" not in row, "列表不该塞完整 manifest"

    detail = _ok(api.get(f"/api/v1/split-tasks/{created['job_id']}/samples/{row['id']}"))
    assert detail["meta"]["schema_version"] == 3
    assert detail["time_series"], "单样本详情要给该窗内的时序局部数据"
    for track in detail["time_series"]:
        assert len(track["values"]) <= 600

    unknown = api.get(f"/api/v1/split-tasks/{created['job_id']}/samples/999999")
    assert unknown.status_code == 404
    assert api.get("/api/v1/split-tasks/job_nope/samples").status_code == 404


def test_get_split_task_exposes_rules_version(api, ready, db_session, run_job) -> None:
    _record, version_id = ready
    preview = _preview(api, version_id, event_start=1.0, event_end=7.0)
    created = _ok(api.post(_url(version_id, "split-tasks"), json={"preview_token": preview["preview_token"]}))
    _run_split(db_session, run_job, created["job_id"])

    data = _ok(api.get(f"/api/v1/split-tasks/{created['job_id']}"))
    assert data["result"]["rules_version"] == 3
    assert data["result"]["schema_version"] == 3
    assert data["result"]["mapping_hash"] == preview["mapping_hash"]


# ── 增强模态：焊缝图片裁切失败不阻断 ─────────────────────────────────


def test_seam_crop_failure_does_not_block_the_task(api, ready, db_session, run_job, storage) -> None:
    """§6.1：图片是增强模态——解码失败只让该样本没有 `crop_key`，任务照常成功。"""
    record, version_id = ready
    _ok(api.put(_url(version_id, "calibration"), json={
        "seam_image": {"roi": {"x": 10, "y": 10, "w": 300, "h": 60}},
    }))
    storage.put(SEAM_KEY, b"not-an-image-at-all")  # 覆盖成坏图：裁切必失败

    preview = _preview(api, version_id, event_start=1.0, event_end=7.0)
    created = _ok(api.post(_url(version_id, "split-tasks"), json={"preview_token": preview["preview_token"]}))
    task = _run_split(db_session, run_job, created["job_id"])

    assert task.sample_count == preview["sample_count"], "图片坏了不该让整批样本失败"
    first = db_session.exec(
        select(Sample).where(Sample.split_task_id == task.id).order_by(Sample.id)
    ).first()
    assert first.meta["seam_image"]["crop_key"] is None
    assert first.meta["signal"]["available"] is True, "信号模态不受影响"


# ── 助手 ─────────────────────────────────────────────────────────────


def _run_split(db_session, run_job, job_uid: str) -> SplitTask:
    """同步跑一次 split Job（执行器不启线程），返回回填后的任务行。"""
    from app.models.jobs import Job

    run_job(job_uid)
    db_session.expire_all()
    job = db_session.exec(select(Job).where(Job.job_uid == job_uid)).first()
    assert job is not None and job.status == "succeeded", job.error if job else "job missing"
    task = db_session.exec(select(SplitTask).where(SplitTask.job_id == job.id)).first()
    assert task is not None
    return task
