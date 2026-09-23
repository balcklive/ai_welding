"""焊缝图片「不参与分段」显式开关（`calibration.seam_image.excluded`）回归。

业务规则（本批验收口径）：

1. 焊缝图片存在但**没框 ROI** → 该模态不可用 + 原因，**引导用户去对齐页框选**；
2. 用户**明确选择**「不对焊缝图片进行分段」→ 同样不可用，但原因与引导都不同
   （不再催去标定），且只生成时序 / 视频样本；
3. 两者**必须在服务端分开**（`excluded` 布尔位）：只把 ROI 清成 `null` 会把前者显示成后者。

覆盖：PUT 合并语义（写 / 撤销 / 清除）、`calibration_payload` 的角色转换、
`build_coordinate_mapping` 的映射与 calibrated、样本 manifest（`map_window_to_modalities`
经 `_seam_image_part`）与预览 warnings/modalities、以及**不参与时不下载图片**。

基础设施同 `test_calibration_api.py`：内存 SQLite + StaticPool + 真实 TestClient +
依赖覆盖 + `app.storage.get_storage` monkeypatch；不连远程 MySQL / MinIO。
"""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel

from app.api.deps import get_current_user
from app.core.db import get_session
from app.main import app
from app.models import User
from app.models.data import AuditLog, DataRecord, DataVersion
from app.services import alignment
from app.services.signals import generate_signals
from app.services.splitting import (
    build_time_windows,
    map_window_to_modalities,
    preview_warnings,
    _preview_modalities,
)
from app.storage.client import StorageClient

client = TestClient(app)

IMAGE_W, IMAGE_H = 400, 120
SEAM_KEY = "raw/REG-TEST-EXCL/seam.png"
ROI = {"x": 10, "y": 20, "w": 300, "h": 50}


class FakeStorage:
    """内存假存储；`downloads` 记录被读过的对象键（用来断言"不参与时不下载图片"）。"""

    normalize_key = staticmethod(StorageClient.normalize_key)
    normalize_filename = staticmethod(StorageClient.normalize_filename)

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.downloads: list[str] = []

    def put(self, object_key: str, data: bytes) -> None:
        self.objects[object_key] = data

    def get_object(self, object_key: str) -> bytes:
        self.downloads.append(object_key)
        if object_key not in self.objects:
            raise FileNotFoundError(object_key)
        return self.objects[object_key]

    def stat_object(self, object_key: str) -> int:
        return len(self.objects.get(object_key, b""))


def _png(width: int = IMAGE_W, height: int = IMAGE_H) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), (128, 128, 128)).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture()
def db_session():
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
    fake.put(SEAM_KEY, _png())
    monkeypatch.setattr("app.storage.get_storage", lambda: fake)
    return fake


@pytest.fixture()
def user(db_session) -> User:
    u = User(username="roi-owner", password_hash="x", display_name="标定员", role="user")
    db_session.add(u)
    db_session.commit()
    db_session.refresh(u)
    return u


@pytest.fixture()
def as_user(db_session, user):
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
    rec = DataRecord(
        weld_id="WLD-TEST-EXCL", registration_no="REG-TEST-EXCL",
        source="现场采集", quality="待复核", modalities=["video"],
    )
    db_session.add(rec)
    db_session.commit()
    db_session.refresh(rec)
    v10 = DataVersion(
        record_id=rec.id, version_no="v1.0", action="原始数据",
        object_keys=[SEAM_KEY],
    )
    db_session.add(v10)
    db_session.commit()
    db_session.refresh(v10)
    rec.latest_version_id = v10.id
    db_session.add(rec)
    db_session.add(AuditLog(
        user_id=user.id, action="create", resource_type="weld", resource_id=rec.weld_id,
    ))
    db_session.commit()
    db_session.refresh(rec)
    return rec


def _url(record: DataRecord, version_id: int | None = None) -> str:
    return f"/api/v1/welds/{record.weld_id}/versions/{version_id}/calibration"


# ── PUT：写入 / 撤销 / 清除 ──────────────────────────────────────────


def test_excluded_needs_no_roi_and_reads_no_image(as_user, record, storage) -> None:
    """「不参与」不需要 ROI，因而也不该付下载图片的成本（ROI 才需要真实宽高校验）。"""
    res = client.put(_url(record, record.latest_version_id), json={"seam_image": {"excluded": True}})
    assert res.status_code == 200, res.text
    body = res.json()["data"]["seam_image"]
    assert body["excluded"] is True
    assert body["roi"] is None
    assert body["calibrated"] is False  # 不参与 ≠ 已标定
    assert storage.downloads == [], "「不参与」不得下载焊缝图片"


def test_roi_write_clears_a_previous_exclusion(as_user, record, storage) -> None:
    """撤销"不参与"必须能覆盖旧值：合并语义是**整组替换**，故 ROI 补丁显式写 excluded=false。"""
    client.put(_url(record, record.latest_version_id), json={"seam_image": {"excluded": True}})
    res = client.put(_url(record, record.latest_version_id), json={"seam_image": {"roi": ROI}})
    assert res.status_code == 200, res.text
    body = res.json()["data"]["seam_image"]
    assert body["excluded"] is False
    assert body["calibrated"] is True
    assert body["roi"] == {"x": 10.0, "y": 20.0, "w": 300.0, "h": 50.0}


def test_excluded_clears_a_previous_roi(as_user, record, storage) -> None:
    client.put(_url(record, record.latest_version_id), json={"seam_image": {"roi": ROI}})
    client.put(_url(record, record.latest_version_id), json={"seam_image": {"excluded": True}})
    body = client.get(_url(record, record.latest_version_id)).json()["data"]["seam_image"]
    assert body == {"roi": None, "excluded": True, "calibrated": False, "object_key": SEAM_KEY}


def test_null_group_clears_back_to_unset(as_user, record, storage) -> None:
    """清空整组 = 回到"还没标定"，与"明确不参与"不是一回事。"""
    client.put(_url(record, record.latest_version_id), json={"seam_image": {"excluded": True}})
    res = client.put(_url(record, record.latest_version_id), json={"seam_image": None})
    assert res.status_code == 200, res.text
    assert res.json()["data"]["seam_image"]["excluded"] is False


def test_excluded_rejects_non_boolean(as_user, record) -> None:
    res = client.put(
        _url(record, record.latest_version_id), json={"seam_image": {"excluded": "yes"}}
    )
    assert res.status_code == 400
    assert res.json()["code"] == 40000


# ── 映射：不参与 → calibrated=false + 专属原因 ───────────────────────


def _mapping(calibration: dict) -> dict:
    bundle = generate_signals("WLD-TEST-EXCL", sample_rate=1000)
    return alignment.build_coordinate_mapping(
        bundle=bundle,
        events=bundle.events or {},
        calibration=calibration,
        has_scalar_speed=False,
        video_key=None,
        video_meta=None,
        seam_image_key=SEAM_KEY,
    )


def test_mapping_excluded_keeps_file_but_never_claims_calibrated() -> None:
    seam = _mapping({"seam_image": {"excluded": True}})["mappings"]["seam_image"]
    assert seam["available"] is True  # 文件在，只是不参与
    assert seam["excluded"] is True
    assert seam["calibrated"] is False
    assert seam["reason"] == alignment.SEAM_EXCLUDED_REASON


def test_mapping_unframed_and_excluded_have_different_reasons() -> None:
    """两条不可用路径的原因必须可区分——否则"已完成的选择"会被读成"未完成的标定"。"""
    unframed = _mapping({})["mappings"]["seam_image"]
    excluded = _mapping({"seam_image": {"excluded": True}})["mappings"]["seam_image"]
    assert unframed["excluded"] is False and unframed["calibrated"] is False
    assert unframed["reason"] != excluded["reason"]
    assert "未框选" in unframed["reason"]


# ── 样本 manifest 与预览 ─────────────────────────────────────────────


def _manifest(seam: dict) -> dict:
    window = build_time_windows(
        duration=10.0, sample_rate=1000, window_seconds=2.0, stride_seconds=2.0,
        event_bounds=(0.0, 10.0), tail_policy="drop",
    )[0]
    mapping = {"mappings": {"seam_image": seam}}
    return map_window_to_modalities(
        window, mapping=mapping, sample_rate=1000, weld_id="WLD-TEST-EXCL", version_id=1
    )


def test_manifest_marks_excluded_seam_image_unavailable_with_reason() -> None:
    seam = _mapping({"seam_image": {"excluded": True}})["mappings"]["seam_image"]
    part = _manifest(seam)["seam_image"]
    assert part["available"] is False
    assert part["excluded"] is True
    assert part["reason"] == alignment.SEAM_EXCLUDED_REASON
    assert "spatial_range" not in part  # 不投影，也就没有像素区间


def test_preview_warnings_do_not_nag_after_explicit_opt_out() -> None:
    excluded = _mapping({"seam_image": {"excluded": True}})
    unframed = _mapping({})
    rules = {"window_seconds": 2.0, "stride_seconds": 2.0, "tail_policy": "drop"}

    opt_out = preview_warnings(excluded, rules, [])
    assert any("不参与分段" in w for w in opt_out)
    assert not any("请前往对齐页标定" in w for w in opt_out), "已明确不参与就不该再催去标定"

    pending = preview_warnings(unframed, rules, [])
    assert any("请前往对齐页标定" in w for w in pending)


def test_preview_modalities_exposes_excluded() -> None:
    assert _preview_modalities(_mapping({"seam_image": {"excluded": True}}))["seam_image"]["excluded"] is True
    assert _preview_modalities(_mapping({}))["seam_image"]["excluded"] is False


def test_alignment_track_reports_not_aligned_when_excluded() -> None:
    task_mapping = _mapping({"seam_image": {"excluded": True}})
    track = alignment._seam_image_track(SEAM_KEY, task_mapping)
    assert track["aligned"] is False
    assert track["reason"] == alignment.SEAM_EXCLUDED_REASON
