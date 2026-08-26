"""Task 12：特征提取测试（真实多模态特征 + 端点）。

纯函数部分（ts_features/vision_features/audio_features/unify）不连 DB；
端点部分用内存 SQLite + StaticPool + 真实 app TestClient（同 test_analysis.py）：
`seed_all` 造演示数据后 override `get_session` / `get_current_user`。

覆盖：
- ts_features：8 键、均值≈np.mean、50Hz 正弦 FFT 主频≈50Hz；
- vision_features：8 键、面积>0（合成熔池真实 regionprops）；
- audio_features：6 键、全部有限；
- unify：total_dims==42、groups 覆盖 [0,42)、Z-Score 归一化后方差≈1、
  Min-Max∈[0,1]、L2 范数≈1、`无` 原样透传、format 透传；
- 端点：POST 200 + 落库（GET 返回同一份）、坏 weld/version 404、非法
  normalization/format 400、未知 extraction_id 404、未登录 401。
"""

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, select

from app.api.deps import get_current_user
from app.core.db import get_session
from app.core.seed import seed_all
from app.main import app
from app.models import DataRecord, DataVersion, FeatureExtraction, User
from app.services import features

client = TestClient(app)

WELD_0248 = "WLD-20260815-0248"


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        seed_all(session)
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


# ---------- ts_features ----------


def test_ts_features_shape_and_mean() -> None:
    x = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    feats = features.ts_features(x)
    assert set(feats) == set(features.TS_FEATURE_KEYS)
    assert abs(feats["mean"] - np.mean(x)) < 1e-9
    assert abs(feats["variance"] - np.var(x)) < 1e-9
    assert feats["peak"] == 5.0
    assert np.isfinite(feats["skewness"])
    assert np.isfinite(feats["kurtosis"])


def test_ts_features_fft_dominant_freq_of_50hz_sine() -> None:
    fs = 1000
    t = np.linspace(0, 1, fs, endpoint=False)  # 精确 1/fs 采样间隔
    x = np.sin(2 * np.pi * 50 * t)
    feats = features.ts_features(x, fs=fs)
    assert abs(feats["fft_dominant_freq"] - 50.0) < 1.0


# ---------- vision_features ----------


def test_vision_features_shape_and_area() -> None:
    vis = features.vision_features()
    assert set(vis) == set(features.VISION_GEOMETRY_KEYS + features.VISION_TEXTURE_KEYS)
    assert vis["area"] > 0
    assert vis["perimeter"] > 0
    assert vis["aspect_ratio"] > 1.0  # 旋转椭圆长轴 > 短轴
    for val in vis.values():
        assert np.isfinite(val)


# ---------- audio_features ----------


def test_audio_features_shape_and_finite() -> None:
    audio, fs = features.generate_audio(WELD_0248)
    af = features.audio_features(audio, fs)
    assert set(af) == set(features.AUDIO_FEATURE_KEYS)
    for val in af.values():
        assert np.isfinite(val)
    assert af["spectral_centroid"] > 0
    assert af["spectral_rolloff"] > 0


def test_audio_features_zero_input_safe() -> None:
    af = features.audio_features(np.zeros(2048), fs=1000)
    assert all(v == 0.0 for v in af.values())


# ---------- unify ----------


def _fake_ts() -> dict:
    """构造 4 通道非恒定特征（值随索引变化），使 Z-Score/Min-Max 有意义。"""
    return {
        "cur": {k: float(i) for i, k in enumerate(features.TS_FEATURE_KEYS)},
        "vol": {k: float(i) for i, k in enumerate(features.TS_FEATURE_KEYS)},
        "gas": {k: float(i) for i, k in enumerate(features.TS_STAT_KEYS)},
        "wir": {k: float(i) for i, k in enumerate(features.TS_STAT_KEYS)},
    }


def _fake_vis() -> dict:
    return {k: float(i + 1) for i, k in enumerate(features.VISION_GEOMETRY_KEYS + features.VISION_TEXTURE_KEYS)}


def _fake_audio() -> dict:
    return {k: float(i + 1) for i, k in enumerate(features.AUDIO_FEATURE_KEYS)}


def test_unify_total_dims_and_groups_cover_range() -> None:
    u = features.unify(_fake_ts(), _fake_vis(), _fake_audio(), "无", "JSON")
    assert u["total_dims"] == 42
    assert len(u["values"]) == 42
    groups = u["groups"]
    assert len(groups) == len(features.GROUP_NAMES)
    assert [g["name"] for g in groups] == features.GROUP_NAMES
    prev_end = 0
    for g in groups:
        start, end = g["range"]
        assert start == prev_end
        assert end - start == g["dims"]
        prev_end = end
    assert prev_end == 42  # groups 精确覆盖 [0, 42)


def test_unify_zscore_changes_values_and_variance_one() -> None:
    u = features.unify(_fake_ts(), _fake_vis(), _fake_audio(), "Z-Score", "JSON")
    assert abs(float(np.var(u["values"])) - 1.0) < 1e-9
    assert abs(float(np.mean(u["values"]))) < 1e-9
    assert u["normalization"] == "Z-Score"
    assert u["format"] == "JSON"


def test_unify_minmax_and_l2() -> None:
    u = features.unify(_fake_ts(), _fake_vis(), _fake_audio(), "Min-Max", "CSV")
    assert abs(float(np.min(u["values"])) - 0.0) < 1e-9
    assert abs(float(np.max(u["values"])) - 1.0) < 1e-9
    assert u["format"] == "CSV"

    u2 = features.unify(_fake_ts(), _fake_vis(), _fake_audio(), "L2", "PT")
    assert abs(float(np.linalg.norm(u2["values"])) - 1.0) < 1e-9
    assert u2["format"] == "PT"


def test_unify_none_passthrough_equals_raw_concat() -> None:
    u = features.unify(_fake_ts(), _fake_vis(), _fake_audio(), "无", "JSON")
    raw = features._concat_vector(_fake_ts(), _fake_vis(), _fake_audio())
    assert u["values"] == [float(v) for v in raw]


def test_unify_unknown_normalization_raises() -> None:
    with pytest.raises(ValueError):
        features.unify(_fake_ts(), _fake_vis(), _fake_audio(), "bogus", "JSON")


# ---------- 端点 ----------


def _version_id_by_no(weld_id, version_no="v1.0"):
    versions = client.get(f"/api/v1/welds/{weld_id}/versions").json()["data"]
    for v in versions:
        if v["version_no"] == version_no:
            return v["id"]
    raise AssertionError(f"{version_no} not found for {weld_id}")


def _extract_body(weld_id, vid, **overrides):
    body = {
        "weld_id": weld_id,
        "version_id": vid,
        "normalization": "Z-Score",
        "format": "JSON",
    }
    body.update(overrides)
    return body


def test_extract_features_endpoint_persists_and_get_roundtrip(
    override_get_session, override_get_current_user, db_session
) -> None:
    vid = _version_id_by_no(WELD_0248)
    resp = client.post("/api/v1/features/extract", json=_extract_body(WELD_0248, vid))
    assert resp.status_code == 200, resp.text[:400]
    data = resp.json()["data"]
    assert resp.json()["code"] == 0

    # 形状对齐 App.tsx
    assert data["version_id"] == vid
    assert set(data["ts_features"]) == {"cur", "vol", "gas", "wir"}
    for chan_feats in data["ts_features"].values():
        assert set(chan_feats) == set(features.TS_FEATURE_KEYS)
    assert set(data["vision_features"]) == set(
        features.VISION_GEOMETRY_KEYS + features.VISION_TEXTURE_KEYS
    )
    assert set(data["audio_features"]) == set(features.AUDIO_FEATURE_KEYS)
    uv = data["unified_vector"]
    assert uv["total_dims"] == 42
    assert len(uv["values"]) == 42
    assert len(uv["groups"]) == 7
    assert uv["normalization"] == "Z-Score"
    assert uv["format"] == "JSON"
    assert data["created_at"] is not None

    # 落库：feature_extractions 表里有一条
    row = db_session.get(FeatureExtraction, data["id"])
    assert row is not None
    assert row.version_id == vid
    assert row.unified_vector["total_dims"] == 42

    # GET /features/{id} 返回同一份（确定性可复现）
    resp2 = client.get(f"/api/v1/features/{data['id']}")
    assert resp2.status_code == 200
    assert resp2.json()["data"] == data


def test_extract_features_bad_ids(
    override_get_session, override_get_current_user
) -> None:
    vid = _version_id_by_no(WELD_0248)
    resp = client.post(
        "/api/v1/features/extract", json=_extract_body("WLD-NOPE-0000", vid)
    )
    assert resp.status_code == 404 and resp.json()["code"] == 40401
    resp = client.post(
        "/api/v1/features/extract", json=_extract_body(WELD_0248, 999999)
    )
    assert resp.status_code == 404 and resp.json()["code"] == 40402
    # 跨焊缝版本
    other_vid = _version_id_by_no("WLD-20260814-0245")
    resp = client.post(
        "/api/v1/features/extract", json=_extract_body(WELD_0248, other_vid)
    )
    assert resp.status_code == 404 and resp.json()["code"] == 40402


def test_extract_features_invalid_params(
    override_get_session, override_get_current_user
) -> None:
    vid = _version_id_by_no(WELD_0248)
    resp = client.post(
        "/api/v1/features/extract",
        json=_extract_body(WELD_0248, vid, normalization="bogus"),
    )
    assert resp.status_code == 400 and resp.json()["code"] == 40000
    resp = client.post(
        "/api/v1/features/extract",
        json=_extract_body(WELD_0248, vid, format="bogus"),
    )
    assert resp.status_code == 400 and resp.json()["code"] == 40000


def test_extract_features_marks_fallback_modalities(
    override_get_session, override_get_current_user, db_session
) -> None:
    record = DataRecord(
        weld_id="WLD-TEST-FEAT-0001",
        registration_no="REG-TEST-FEAT-0001",
        source="lab",
        modalities=["timeseries"],
        quality="通过",
    )
    db_session.add(record)
    db_session.commit()
    db_session.refresh(record)
    version = DataVersion(
        record_id=record.id,
        version_no="v1.0",
        action="原始数据",
        object_keys=["raw/REG-TEST-FEAT-0001/current.csv"],
    )
    db_session.add(version)
    db_session.commit()
    db_session.refresh(version)

    resp = client.post(
        "/api/v1/features/extract",
        json=_extract_body(record.weld_id, version.id, normalization="无"),
    )
    assert resp.status_code == 200, resp.text[:400]
    data = resp.json()["data"]
    assert data["modality_status"] == {
        "timeseries": "available",
        "vision": "fallback",
        "audio": "fallback",
    }


def test_get_feature_extraction_unknown_id(
    override_get_session, override_get_current_user
) -> None:
    resp = client.get("/api/v1/features/999999")
    assert resp.status_code == 404 and resp.json()["code"] == 40401


def test_features_endpoints_require_login(override_get_session) -> None:
    assert client.post("/api/v1/features/extract", json={}).status_code == 401
    resp = client.get("/api/v1/features/1")
    assert resp.status_code == 401 and resp.json()["code"] == 40100
