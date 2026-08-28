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
from types import SimpleNamespace
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, select

from app.api.deps import get_current_user
from app.core.db import get_session
from app.core.seed import seed_all
from app.main import app
from app.models import AuditLog, DataRecord, DataVersion, FeatureExtraction, Job, User
from app.services import features
from app.services.jobs import create_job
from app.jobs.features import handle as handle_feature_job
from app.jobs.executor import _mark_failed_in

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
        # 测试不依赖可选的演示数据种子（生产环境已移除演示数据）。
        for weld_id, registration_no in ((WELD_0248, "REG-TEST-0248"), ("WLD-20260814-0245", "REG-TEST-0245")):
            if not session.exec(select(DataRecord).where(DataRecord.weld_id == weld_id)).first():
                record = DataRecord(
                    weld_id=weld_id,
                    registration_no=registration_no,
                    source="test",
                    modalities=["timeseries"],
                    quality="通过",
                )
                session.add(record)
                session.commit()
                session.refresh(record)
                version = DataVersion(
                    record_id=record.id,
                    version_no="v1.0",
                    action="原始数据",
                    object_keys=[f"raw/{registration_no}/current.csv"],
                )
                session.add(version)
                session.commit()
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


def test_vision_provider_response_is_validated(monkeypatch) -> None:
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            import json

            return json.dumps({"features": _fake_vis()}).encode("utf-8")

    monkeypatch.setattr(features, "urlopen", lambda *args, **kwargs: FakeResponse())
    result = features.vision_features_from_provider(b"image-bytes", "http://vision.test/infer")
    assert result == _fake_vis()

    class InvalidResponse(FakeResponse):
        def read(self):
            return b'{"features": {"area": 1}}'

    monkeypatch.setattr(features, "urlopen", lambda *args, **kwargs: InvalidResponse())
    with pytest.raises(ValueError, match="字段不完整"):
        features.vision_features_from_provider(b"image-bytes", "http://vision.test/infer")


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
    override_get_session, override_get_current_user, db_session, monkeypatch
) -> None:
    vid = _version_id_by_no(WELD_0248)
    monkeypatch.setattr(
        "app.api.v1.analysis.signal_ingest.load_signal_bundle",
        lambda *args: SimpleNamespace(
            channels=[SimpleNamespace(id=key, values=np.linspace(1, 2, 100)) for key in ("cur", "vol", "gas", "wir")],
            source="real", sample_rate=1000, duration=0.1,
        ),
    )
    monkeypatch.setattr("app.api.v1.analysis._load_real_vision_features", lambda version: (_fake_vis(), "real"))
    monkeypatch.setattr("app.api.v1.analysis._load_real_audio_features", lambda version: (_fake_audio(), "real"))
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


def test_create_feature_extraction_task_is_idempotent(
    override_get_session, override_get_current_user, db_session
) -> None:
    record = DataRecord(weld_id="WLD-TASK-IDEMPOTENT", registration_no="REG-TASK-IDEMPOTENT", source="lab", quality="通过")
    db_session.add(record)
    db_session.commit()
    db_session.refresh(record)
    version = DataVersion(record_id=record.id, version_no="v1.0", action="原始数据", object_keys=["raw/task.csv"])
    db_session.add(version)
    db_session.commit()
    db_session.refresh(version)
    body = _extract_body(record.weld_id, version.id)
    first = client.post("/api/v1/features/extract-tasks", json=body)
    second = client.post("/api/v1/features/extract-tasks", json=body)
    assert first.status_code == 200 and second.status_code == 200
    assert first.json()["data"]["job_id"] == second.json()["data"]["job_id"]


def test_failed_feature_task_can_be_retried_and_is_audited(
    override_get_session, override_get_current_user, db_session
) -> None:
    record = DataRecord(weld_id="WLD-TASK-RETRY", registration_no="REG-TASK-RETRY", source="lab", quality="通过")
    db_session.add(record)
    db_session.commit()
    db_session.refresh(record)
    version = DataVersion(record_id=record.id, version_no="v1.0", action="原始数据", object_keys=["raw/retry.csv"])
    db_session.add(version)
    db_session.commit()
    db_session.refresh(version)
    body = _extract_body(record.weld_id, version.id)
    first = client.post("/api/v1/features/extract-tasks", json=body)
    first_job = db_session.exec(select(Job).where(Job.type == "feature_extraction")).first()
    assert first_job is not None
    _mark_failed_in(db_session, first_job.id, "vision provider unavailable")
    second = client.post("/api/v1/features/extract-tasks", json=body)
    assert first.status_code == 200 and second.status_code == 200
    assert second.json()["data"]["job_id"] != first.json()["data"]["job_id"]
    failed_audit = db_session.exec(
        select(AuditLog).where(AuditLog.action == "failed", AuditLog.resource_type == "feature_extraction_job")
    ).all()
    assert len(failed_audit) == 1


def test_feature_job_blocks_non_production_modalities(
    override_get_session, override_get_current_user, db_session, monkeypatch
) -> None:
    vid = _version_id_by_no(WELD_0248)
    monkeypatch.setattr(
        "app.jobs.features.signal_ingest.load_signal_bundle",
        lambda *args: SimpleNamespace(
            channels=[SimpleNamespace(id="cur", values=np.linspace(1, 2, 100))],
            source="generated", sample_rate=1000, duration=0.1,
        ),
    )
    job = create_job(
        db_session,
        "feature_extraction",
        {"request": _extract_body(WELD_0248, vid), "user_id": 1},
    )
    db_session.commit()

    # 测试版本只有测试时序输入，且没有视觉/音频正式输入；生产默认必须拒绝落库。
    with pytest.raises(ValueError, match="生产模式禁止"):
        handle_feature_job(job.id, db_session)
    assert db_session.exec(select(FeatureExtraction)).all() == []


def test_feature_job_persists_metadata_for_formal_modalities(
    override_get_session, override_get_current_user, db_session, monkeypatch
) -> None:
    vid = _version_id_by_no(WELD_0248)
    job = create_job(
        db_session,
        "feature_extraction",
        {"request": _extract_body(WELD_0248, vid), "user_id": 1},
    )
    job.status = "running"
    db_session.commit()

    class Channel:
        id = "cur"
        values = np.linspace(1.0, 2.0, 100)

    class Bundle:
        channels = [Channel()]
        source = "real"
        sample_rate = 2000
        duration = 0.05

    monkeypatch.setattr("app.jobs.features.signal_ingest.load_signal_bundle", lambda *args: Bundle())
    monkeypatch.setattr(
        "app.jobs.features._load_real_vision_features",
        lambda version: (_fake_vis(), "real"),
    )
    monkeypatch.setattr(
        "app.jobs.features._load_real_audio_features",
        lambda version: (_fake_audio(), "real"),
    )
    handle_feature_job(job.id, db_session)

    db_session.refresh(job)
    extraction = db_session.get(FeatureExtraction, job.result["extraction_id"])
    assert job.status == "succeeded"
    assert extraction is not None
    assert extraction.status == "succeeded"
    assert extraction.job_id == job.id
    assert extraction.source_by_modality == {"timeseries": "real", "vision": "real", "audio": "real"}
    assert extraction.sample_rate == 2000
    assert extraction.sample_count == 100
    assert extraction.pipeline_version == "feature-extraction-v2"


def test_feature_download_writes_real_json_and_npy_and_audit(
    override_get_session, override_get_current_user, db_session, monkeypatch
) -> None:
    vid = _version_id_by_no(WELD_0248)
    record = db_session.exec(select(DataRecord).where(DataRecord.weld_id == WELD_0248)).first()
    extracted_row = FeatureExtraction(
        version_id=vid,
        ts_features={}, vision_features=_fake_vis(), audio_features=_fake_audio(),
        unified_vector=features.unify({}, _fake_vis(), _fake_audio(), "无", "JSON"),
        normalization="无", format="JSON", created_by=1,
    )
    db_session.add(extracted_row)
    db_session.commit()
    db_session.refresh(extracted_row)
    extracted = {"id": extracted_row.id}

    class FakeStorage:
        def __init__(self):
            self.uploads = {}

        def upload_stream(self, key, fileobj, size, content_type):
            self.uploads[key] = (fileobj.read(), size, content_type)

        def presign_get(self, key):
            return f"https://storage.test/{key}"

    storage = FakeStorage()
    monkeypatch.setattr("app.storage.get_storage", lambda: storage)
    for fmt, suffix in (("JSON", ".json"), ("NPY", ".npy")):
        response = client.post(f"/api/v1/features/{extracted['id']}/download", json={"format": fmt})
        assert response.status_code == 200, response.text[:400]
        result = response.json()["data"]
        assert result["format"] == fmt
        assert result["object_key"].endswith(suffix)
        assert result["url"].startswith("https://storage.test/")
    audits = db_session.exec(
        select(AuditLog).where(AuditLog.action == "export", AuditLog.resource_type == "feature_extraction")
    ).all()
    assert len(audits) == 2


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
    assert resp.status_code == 400
    assert "真实时序信号" in resp.json()["message"]


def test_get_feature_extraction_unknown_id(
    override_get_session, override_get_current_user
) -> None:
    resp = client.get("/api/v1/features/999999")
    assert resp.status_code == 404 and resp.json()["code"] == 40401


def test_features_endpoints_require_login(override_get_session) -> None:
    assert client.post("/api/v1/features/extract", json={}).status_code == 401
    resp = client.get("/api/v1/features/1")
    assert resp.status_code == 401 and resp.json()["code"] == 40100
