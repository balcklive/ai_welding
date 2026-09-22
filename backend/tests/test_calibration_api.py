"""标定 API + 对齐 offset 消费（E2E）。

覆盖设计文档 §12.3 的 P0/P1 闭环：

- `GET`/`PUT /welds/{weld_id}/versions/{version_id}/calibration`：鉴权、焊缝/版本归属、
  审计；**标定权威归属 = 焊缝 v1.0 原始版本**（任何版本读到同一份）。
- 校验：offset 正负与有限性、ROI 形状、**ROI 必须落在真实图片像素范围内**。
- 重新标定**不改**历史 `alignment_tasks.mapping`。
- 对齐任务写入 `mapping` 并**按 `t_video = t_signal - offset` 抽帧**。

基础设施：内存 SQLite + StaticPool + 真实 app TestClient（同 test_jobs.py）；
`get_session`/`get_current_user` 依赖覆盖；`app.storage.get_storage` monkeypatch 到内存假存储；
视频用 imageio-ffmpeg 现生成（同 test_media_probe.py）。
"""

from __future__ import annotations

import io
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
from app.models.analysis import AlignmentTask, SignalIngest
from app.models.data import AuditLog, DataRecord, DataVersion
from app.services import signal_ingest
from app.services.alignment import run_alignment
from app.services.jobs import create_job
from app.storage.client import StorageClient

client = TestClient(app)

IMAGE_W, IMAGE_H = 400, 120
VIDEO_FPS, VIDEO_SECONDS = 10, 2.0
SEAM_KEY = "raw/REG-TEST-0001/seam.png"
VIDEO_KEY = "raw/REG-TEST-0001/weld.mp4"
CSV_KEY = "raw/REG-TEST-0001/signal.csv"

#: 人造信号：焊接段 0.6–2.6s 电流 200A、段外 0A。实测 `detect_events` 得
#: `arc=0.59 / weld_segment=[0.59, 2.61] / tail=2.62`——两个事件早于 2s 视频、两个晚于，
#: 换 offset 就会换一批事件落进视频覆盖范围，是"offset 真的作用在取帧上"的判据。
SIGNAL_FS, SIGNAL_SECONDS = 100, 4.0
WELD_WINDOW = (0.6, 2.6)
EARLY_EVENTS = {"arc", "weld_start"}
LATE_EVENTS = {"weld_end", "tail"}


# ── 基础设施 ─────────────────────────────────────────────────────────


class FakeStorage:
    """内存假存储：不连 MinIO。方法集覆盖本链路实际走到的那几个。"""

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
    buf = io.BytesIO()
    Image.new("RGB", (width, height), (128, 128, 128)).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture(scope="module")
def mp4_bytes(tmp_path_factory) -> bytes:
    """真实 2s/10fps/320×240 mp4（testsrc：逐帧变化，可用于区分取帧位置）。"""
    path = tmp_path_factory.mktemp("calibration_video") / "weld.mp4"
    subprocess.run(
        [
            imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error",
            "-f", "lavfi", "-i",
            f"testsrc=size=320x240:rate={VIDEO_FPS}:duration={VIDEO_SECONDS}",
            "-pix_fmt", "yuv420p", "-c:v", "libx264", str(path),
        ],
        check=True, capture_output=True,
    )
    return path.read_bytes()


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
def storage(monkeypatch) -> FakeStorage:
    fake = FakeStorage()
    fake.put(SEAM_KEY, _png())  # 焊缝照片默认在位；要测"读不到"的用例自行删掉该键
    monkeypatch.setattr("app.storage.get_storage", lambda: fake)
    return fake


@pytest.fixture()
def user(db_session) -> User:
    u = User(username="tester", password_hash="x", display_name="测试员", role="user")
    db_session.add(u)
    db_session.commit()
    db_session.refresh(u)
    return u


@pytest.fixture()
def other_user(db_session) -> User:
    u = User(username="intruder", password_hash="x", display_name="别人", role="user")
    db_session.add(u)
    db_session.commit()
    db_session.refresh(u)
    return u


@pytest.fixture()
def as_user(db_session, user):
    app.dependency_overrides[get_session] = lambda: iter(())
    app.dependency_overrides[get_session] = _session_override(db_session)
    app.dependency_overrides[get_current_user] = lambda: user
    yield user
    app.dependency_overrides.pop(get_session, None)
    app.dependency_overrides.pop(get_current_user, None)


def _session_override(session: Session):
    def _override():
        yield session
    return _override


@pytest.fixture()
def record(db_session, user) -> DataRecord:
    """一条归属 `user` 的焊缝 + v1.0 原始版本；object_keys 含焊缝照片与视频。"""
    rec = DataRecord(
        weld_id="WLD-TEST-0001",
        registration_no="REG-TEST-0001",
        source="现场采集",
        quality="待复核",
        modalities=["video"],
    )
    db_session.add(rec)
    db_session.commit()
    db_session.refresh(rec)
    v10 = DataVersion(
        record_id=rec.id, version_no="v1.0", action="原始数据",
        object_keys=[SEAM_KEY, VIDEO_KEY, CSV_KEY],
    )
    db_session.add(v10)
    db_session.commit()
    db_session.refresh(v10)
    rec.latest_version_id = v10.id
    db_session.add(rec)
    # ownership ACL 只看 audit_logs(create, weld, resource_id=weld_id) —— 建主记录
    db_session.add(AuditLog(
        user_id=user.id, action="create", resource_type="weld", resource_id=rec.weld_id,
    ))
    db_session.commit()
    db_session.refresh(rec)
    return rec


def _url(record: DataRecord, version_id: int | None = None) -> str:
    return f"/api/v1/welds/{record.weld_id}/versions/{version_id}/calibration"


# ── GET：未标定与已标定 ──────────────────────────────────────────────


def test_get_calibration_uncalibrated_defaults(as_user, record) -> None:
    res = client.get(_url(record, record.latest_version_id))
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["calibration"] == {}
    assert data["anchored_version_id"] == record.latest_version_id
    assert data["video"] == {"offset_seconds": 0.0, "calibrated": False}
    assert data["seam_image"] == {"roi": None, "calibrated": False, "object_key": SEAM_KEY}


def test_put_then_get_roundtrip(as_user, record, db_session) -> None:
    res = client.put(
        _url(record, record.latest_version_id),
        json={"video": {"offset_seconds": -1.1}},
    )
    assert res.status_code == 200
    assert res.json()["data"]["video"] == {"offset_seconds": -1.1, "calibrated": True}

    again = client.get(_url(record, record.latest_version_id)).json()["data"]
    assert again["video"]["offset_seconds"] == -1.1
    assert again["video"]["calibrated"] is True

    v10 = db_session.get(DataVersion, record.latest_version_id)
    assert v10.calibration == {"video": {"offset_seconds": -1.1}}


@pytest.mark.parametrize("offset", [2.5, -2.5, 0.0, -0.25])
def test_put_accepts_signed_offsets(as_user, record, offset) -> None:
    res = client.put(_url(record, record.latest_version_id), json={"video": {"offset_seconds": offset}})
    assert res.status_code == 200
    assert res.json()["data"]["video"]["offset_seconds"] == offset


def test_put_roi_within_bounds(as_user, record, storage, db_session) -> None:
    res = client.put(
        _url(record, record.latest_version_id),
        json={"seam_image": {"roi": {"x": 10, "y": 20, "w": 300, "h": 50}}},
    )
    assert res.status_code == 200
    body = res.json()["data"]
    assert body["seam_image"]["calibrated"] is True
    assert body["seam_image"]["roi"] == {"x": 10.0, "y": 20.0, "w": 300.0, "h": 50.0}


# ── PUT：校验 ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "payload",
    [
        {"video": {"offset_seconds": "1.0"}},
        {"video": {"offset_seconds": None}},
        {"video": {"offset_seconds": 100000.0}},
        {"video": {"offset_seconds": True}},
    ],
)
def test_put_rejects_bad_offset(as_user, record, payload) -> None:
    res = client.put(_url(record, record.latest_version_id), json=payload)
    assert res.status_code == 400
    assert res.json()["code"] == 40000


@pytest.mark.parametrize(
    "roi",
    [
        {"x": -1, "y": 0, "w": 10, "h": 10},
        {"x": 0, "y": 0, "w": 0, "h": 10},
        {"x": 0, "y": 0, "w": 10},
        {"x": 390, "y": 0, "w": 20, "h": 10},   # x+w=410 > 400
        {"x": 0, "y": 110, "w": 10, "h": 20},   # y+h=130 > 120
    ],
)
def test_put_rejects_roi_outside_image(as_user, record, roi, db_session) -> None:
    res = client.put(
        _url(record, record.latest_version_id), json={"seam_image": {"roi": roi}}
    )
    assert res.status_code == 400
    assert res.json()["code"] == 40000
    # 拒绝时不得落库半成品
    assert db_session.get(DataVersion, record.latest_version_id).calibration is None


def test_put_rejects_roi_when_image_unreadable(as_user, record, storage) -> None:
    """storage 里没有该对象 → 拿不到真实宽高 → 拒绝，而不是放行一个核实不了的断言。"""
    storage.objects.pop(SEAM_KEY)
    res = client.put(
        _url(record, record.latest_version_id),
        json={"seam_image": {"roi": {"x": 0, "y": 0, "w": 10, "h": 10}}},
    )
    assert res.status_code == 400
    assert "不可读" in res.json()["message"]


def test_put_rejects_roi_when_record_has_no_image(as_user, record, storage, db_session) -> None:
    v10 = db_session.get(DataVersion, record.latest_version_id)
    v10.object_keys = [VIDEO_KEY]
    db_session.add(v10)
    db_session.commit()

    res = client.put(
        _url(record, record.latest_version_id),
        json={"seam_image": {"roi": {"x": 0, "y": 0, "w": 10, "h": 10}}},
    )
    assert res.status_code == 400
    assert "没有焊缝图片" in res.json()["message"]


def test_put_offset_does_not_need_image(as_user, record) -> None:
    """只改 offset 不付读图成本——storage 里没有图片也应当成功。"""
    res = client.put(_url(record, record.latest_version_id), json={"video": {"offset_seconds": 1.0}})
    assert res.status_code == 200


# ── 权威归属：任何版本读到同一份 ─────────────────────────────────────


def test_put_via_other_version_still_anchors_to_v10(as_user, record, db_session) -> None:
    derived = DataVersion(
        record_id=record.id, version_no="v1.1", action="去噪处理", object_keys=[VIDEO_KEY],
    )
    db_session.add(derived)
    db_session.commit()
    db_session.refresh(derived)

    res = client.put(_url(record, derived.id), json={"video": {"offset_seconds": 0.75}})
    assert res.status_code == 200
    assert res.json()["data"]["anchored_version_id"] == record.latest_version_id  # 仍是 v1.0

    # v1.1 自己不带标定，读 v1.1 也拿到 v1.0 那份
    assert db_session.get(DataVersion, derived.id).calibration is None
    assert client.get(_url(record, derived.id)).json()["data"]["video"]["offset_seconds"] == 0.75


# ── 鉴权 / 归属 / 审计 ───────────────────────────────────────────────


def test_calibration_requires_login(record) -> None:
    app.dependency_overrides.pop(get_current_user, None)
    assert client.get(_url(record, record.latest_version_id)).status_code == 401
    assert client.put(
        _url(record, record.latest_version_id), json={"video": {"offset_seconds": 1.0}}
    ).status_code == 401


def test_calibration_forbidden_for_non_owner(as_user, other_user, record) -> None:
    app.dependency_overrides[get_current_user] = lambda: other_user
    assert client.get(_url(record, record.latest_version_id)).status_code == 403
    assert client.put(
        _url(record, record.latest_version_id), json={"video": {"offset_seconds": 1.0}}
    ).status_code == 403


def test_calibration_unknown_weld_and_version(as_user, record, db_session) -> None:
    assert client.get("/api/v1/welds/WLD-NOPE/versions/1/calibration").status_code == 404

    stranger = DataVersion(record_id=record.id, version_no="v9.9", action="人工修正")
    db_session.add(stranger)
    db_session.commit()
    db_session.refresh(stranger)
    other = DataRecord(weld_id="WLD-TEST-0002", registration_no="REG-TEST-0002", source="现场采集")
    db_session.add(other)
    db_session.commit()
    db_session.refresh(other)
    # 另一条焊缝也要归属当前用户，否则会先被 ACL 挡成 403，测不到版本校验
    db_session.add(AuditLog(
        user_id=as_user.id, action="create", resource_type="weld", resource_id=other.weld_id,
    ))
    db_session.commit()
    # 版本存在但不属于该焊缝 → 40402
    assert client.get(_url(other, stranger.id)).status_code == 404


def test_put_writes_audit(as_user, record, db_session) -> None:
    client.put(
        _url(record, record.latest_version_id),
        json={"video": {"offset_seconds": 1.25}},
    )
    entry = db_session.exec(
        select(AuditLog).where(
            AuditLog.action == "update", AuditLog.resource_type == "calibration"
        )
    ).first()
    assert entry is not None
    assert entry.user_id == as_user.id
    assert entry.resource_id == str(record.latest_version_id)
    assert entry.detail["calibration"] == {"video": {"offset_seconds": 1.25}}


# ── 对齐任务：写 mapping + 按 offset 抽帧 ────────────────────────────


def _signal_csv_bytes() -> bytes:
    n = int(SIGNAL_SECONDS * SIGNAL_FS)
    t = np.arange(n) / SIGNAL_FS
    current = np.where((t >= WELD_WINDOW[0]) & (t <= WELD_WINDOW[1]), 200.0, 0.0)
    frame = pd.DataFrame({
        "time": t,
        "Current": current,
        "Voltage": np.where(current > 0, 20.0, 0.0),
        "GasSpeed": 15.0,
        "WireFeedSpeed": 5.0,
    })
    return frame.to_csv(index=False).encode("utf-8")


def _ingest_real_signal(db_session, record: DataRecord, storage: FakeStorage) -> None:
    """跑一次**真实**信号导入，落 succeeded 的 `SignalIngest` + Parquet。

    对齐没有 generated 回退（`load_signal_bundle` 缺导入直接抛），所以 E2E 必须先有真导入。
    """
    storage.put(CSV_KEY, _signal_csv_bytes())
    v10 = db_session.get(DataVersion, record.latest_version_id)
    job = create_job(db_session, type="signal_ingest")
    ingest = SignalIngest(
        job_id=job.id, version_id=v10.id, source_object_key=CSV_KEY, status="pending",
    )
    db_session.add(ingest)
    db_session.commit()
    db_session.refresh(ingest)
    db_session.refresh(job)
    signal_ingest.run_ingest(db_session, ingest, job)
    db_session.commit()  # run_ingest 与 run_alignment 同约定：不自己 commit，由调用方提交
    db_session.refresh(ingest)
    assert ingest.status == "succeeded", ingest.validation


@pytest.fixture()
def aligned_setup(as_user, record, storage, mp4_bytes, db_session):
    """真实信号已导入 + 焊缝照片与视频就位的焊缝（`record`），返回 (焊缝, v1.0 版本 id)。"""
    storage.put(VIDEO_KEY, mp4_bytes)
    storage.put(SEAM_KEY, _png())
    _ingest_real_signal(db_session, record, storage)
    return record, record.latest_version_id


def _run_alignment(db_session, record: DataRecord, version_id: int) -> AlignmentTask:
    """在给定版本上跑一次真实对齐，返回回填后的任务行。"""
    job = create_job(db_session, type="alignment")
    task = AlignmentTask(job_id=job.id, version_id=version_id, modalities=["video", "timeseries"])
    db_session.add(task)
    db_session.commit()
    db_session.refresh(task)
    db_session.refresh(job)
    run_alignment(db_session, task, job)
    db_session.commit()  # run_alignment 不自己 commit（executor 的职责）
    db_session.refresh(task)
    return task


def _keyframe_events(task: AlignmentTask) -> set[str]:
    video_track = next(t for t in task.tracks if t["channel"] == "video")
    return {kf["event"] for kf in (video_track["metadata"] or {}).get("keyframes", [])}


def test_alignment_writes_mapping_and_marks_video_aligned(aligned_setup, db_session) -> None:
    record, version_id = aligned_setup
    client.put(_url(record, version_id), json={"video": {"offset_seconds": 0.5}})

    task = _run_alignment(db_session, record, version_id)

    assert task.mapping is not None
    video = task.mapping["mappings"]["video"]
    assert video["calibrated"] is True
    assert video["offset_seconds"] == 0.5
    assert task.mapping["unified_axis"]["unit"] == "second"
    # 已标定 → 视频轨才敢声称对齐
    assert next(t for t in task.tracks if t["channel"] == "video")["aligned"] is True
    # mapping.json 落盘
    assert any(k.endswith("/align/mapping.json") for k in task.assets)


def test_alignment_video_unaligned_without_calibration(aligned_setup, db_session) -> None:
    record, version_id = aligned_setup
    task = _run_alignment(db_session, record, version_id)

    video = task.mapping["mappings"]["video"]
    assert video["calibrated"] is False
    assert video["offset_seconds"] == 0.0  # 仍给 0 供换算，但如实标记未标定
    assert "未标定" in video["reason"]
    assert next(t for t in task.tracks if t["channel"] == "video")["aligned"] is False


def test_alignment_keyframes_follow_offset(aligned_setup, db_session) -> None:
    """换 offset 就换一批事件落进视频覆盖范围——证明偏移真的作用在取帧上。

    事件固定在**信号轴**上（arc/weld_start≈0.59，weld_end/tail≈2.61），视频只有 2 秒，
    故换算到视频轴后 `0 <= t - offset < 2` 的才抽得到：
    offset=0 → 两个早事件；offset=1.0 → 两个晚事件。
    """
    record, version_id = aligned_setup

    client.put(_url(record, version_id), json={"video": {"offset_seconds": 0.0}})
    assert _keyframe_events(_run_alignment(db_session, record, version_id)) == EARLY_EVENTS

    client.put(_url(record, version_id), json={"video": {"offset_seconds": 1.0}})
    assert _keyframe_events(_run_alignment(db_session, record, version_id)) == LATE_EVENTS


def test_recalibration_does_not_touch_historical_mapping(aligned_setup, storage, db_session) -> None:
    """重新标定只影响此后新发起的对齐——历史任务的 mapping 与产物保持当时口径。"""
    record, version_id = aligned_setup
    client.put(_url(record, version_id), json={"video": {"offset_seconds": 0.5}})
    old_task = _run_alignment(db_session, record, version_id)
    old_video = dict(old_task.mapping["mappings"]["video"])
    old_json = storage.objects[f"processed/{record.weld_id}/align/mapping.json"]

    client.put(_url(record, version_id), json={"video": {"offset_seconds": 1.0}})

    db_session.refresh(old_task)
    assert old_task.mapping["mappings"]["video"] == old_video
    assert old_task.mapping["mappings"]["video"]["offset_seconds"] == 0.5
    assert storage.objects[f"processed/{record.weld_id}/align/mapping.json"] == old_json
