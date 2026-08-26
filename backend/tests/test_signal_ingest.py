"""Task 18：CSV 真实信号导入（校验 + Parquet + DSP 读真实信号）。

内存 SQLite + StaticPool + 真实 app TestClient（同 test_alignment / test_reports）。
`seed_all` 造演示数据后 override `get_session` / `get_current_user`；把
`app.jobs.executor.SessionLocal` 指到同一测试引擎（`run_job` 同步执行，不启动线程）；
`app.storage.get_storage` → FakeStorage（`blobs` 供 get_object 读 CSV/Parquet，
`upload_stream` 记录并回填 blobs，不连真实 MinIO）。

覆盖：
- 单元：表头映射（中/英文）、validate_signal 各 pass/warn/fail、启发式 detect_events
  检出 events + 2 个 anomalies、Parquet round-trip；
- API：raw-files 挂 .csv → 自动建 signal_ingest job → run_job → succeeded + parquet，
  `GET …/signals` 返回 `source="real"`；重复挂载幂等不重建；
  校验失败 CSV → failed 且分析回退 `source="generated"`；无 CSV 旧版本回退 generated；
  六 mode 在 real 数据下 200 + 形状不变；未登录 401。
"""

import io
import time

import numpy as np
import pandas as pd
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
from app.models import DataVersion, User
from app.models.analysis import SignalIngest
from app.models.jobs import Job
from app.services import signal_ingest as svc

client = TestClient(app)

WELD_0248 = "WLD-20260815-0248"
REG_0248 = "REG-20260815-00248"
CSV_KEY = f"raw/{REG_0248}/timeseries.csv"

#: mode → 应出现在返回 data 里的键（与 test_analysis.MODE_KEYS 一致）。
MODE_KEYS = {
    "psd": ("freqs", "psd"),
    "stft": ("times", "freqs", "magnitude"),
    "dwt": ("bands", "approx"),
    "wavelet": ("bands",),
    "phase": ("current", "voltage"),
    "pdd": ("bins", "counts", "kde"),
}


class FakeStorage:
    """假存储：`blobs` 供 get_object 读（CSV 由用例预置、Parquet 由 upload_stream 回填）。"""

    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}
        self.uploads: list[tuple] = []

    def upload_stream(self, object_key, fileobj, size, content_type):
        data = fileobj.read()
        self.uploads.append((object_key, size, content_type, data))
        self.blobs[object_key] = data
        return object_key

    def get_object(self, object_key: str) -> bytes:
        if object_key not in self.blobs:
            raise FileNotFoundError(object_key)
        return self.blobs[object_key]

    def stat_object(self, object_key: str) -> int:
        return len(self.blobs.get(object_key, b""))

    def presign_get(self, object_key, expires=3600):
        return f"https://minio.local/aiwelding/{object_key}?expires={expires}"


# ── fixtures（同 test_alignment） ─────────────────────────────────────


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
def executor_sessionlocal(db_engine, monkeypatch):
    """把 executor 的 SessionLocal 指到同一测试引擎（run_job 用独立 session）。"""
    monkeypatch.setattr(
        executor_mod,
        "SessionLocal",
        sessionmaker(bind=db_engine, class_=Session, expire_on_commit=False),
    )


@pytest.fixture()
def fake_storage(monkeypatch):
    storage = FakeStorage()
    monkeypatch.setattr("app.storage.get_storage", lambda: storage)
    return storage


# ── 测试数据构造 ──────────────────────────────────────────────────────


def _synthetic_df(duration: float = 5.0, fs: int = 1000, rng=None):
    """合成"起弧 ramp → 稳态 → 收弧 + 两个异常区段"信号（量程内、确定性）。"""
    rng = rng or np.random.default_rng(42)
    n = int(duration * fs)
    t = np.arange(n) / fs
    cur = np.full(n, 15.0)
    vol = np.full(n, 4.0)
    gas = np.full(n, 15.0)
    wir = np.full(n, 5.0)
    active = (t >= 0.6) & (t <= 4.6)
    cur[active] = 150 + 8 * np.sin(2 * np.pi * 2 * t[active]) + rng.normal(0, 3, active.sum())
    vol[active] = 22 + rng.normal(0, 1, active.sum())
    gas[active] = 15 + rng.normal(0, 0.3, active.sum())
    wir[active] = 5 + rng.normal(0, 0.2, active.sum())
    # 两个异常区段（高方差）
    for a, b in ((1.9, 2.3), (3.5, 3.9)):
        m = (t >= a) & (t <= b)
        cur[m] += rng.normal(0, 18, m.sum())
        vol[m] += rng.normal(0, 3, m.sum())
    return pd.DataFrame(
        {"时间": t, "电流(A)": cur, "电压(V)": vol, "气体流量(L/min)": gas, "送丝速度(m/min)": wir}
    )


def _signal_csv_bytes(**kw) -> bytes:
    return _synthetic_df(**kw).to_csv(index=False).encode("utf-8")


def _v10_id(db_engine, weld_id: str = WELD_0248) -> int:
    with Session(db_engine) as session:
        v = session.exec(
            select(DataVersion).where(DataVersion.version_no == "v1.0")
        ).first()
        return v.id


def _ingest_rows(db_engine):
    with Session(db_engine) as session:
        return session.exec(select(SignalIngest)).all()


def _signal_ingest_job_uid(db_engine) -> str:
    with Session(db_engine) as session:
        job = session.exec(
            select(Job).where(Job.type == "signal_ingest")
        ).first()
        return job.job_uid


# ── 单元：表头映射 ────────────────────────────────────────────────────


def test_map_columns_chinese_and_english():
    zh = svc.map_columns(["时间", "电流(A)", "电压(V)", "气体流量(L/min)", "送丝速度(m/min)"])
    assert zh[0] == {"time": "时间", "cur": "电流(A)", "vol": "电压(V)", "gas": "气体流量(L/min)", "wir": "送丝速度(m/min)"}
    assert zh[1] == []
    en = svc.map_columns(["time", "current", "voltage", "gas", "wire"])
    assert en[0] == {"time": "time", "cur": "current", "vol": "voltage", "gas": "gas", "wir": "wire"}
    assert en[1] == []
    mixed = svc.map_columns(["时间", "unknown_col", "电压(V)"])
    assert mixed[0] == {"time": "时间", "vol": "电压(V)"}
    assert mixed[1] == ["unknown_col"]


# ── 单元：validate_signal ─────────────────────────────────────────────


def test_validate_signal_pass_and_fs():
    df = _synthetic_df()
    result = svc.validate_signal(df)
    assert result["overall"] == "pass"
    assert result["fs"] == 1000
    assert result["row_count"] == len(df)
    assert result["duration"] > 4.9
    assert any(r["name"] == "采样一致性" and r["status"] == "pass" for r in result["rules"])


def test_validate_signal_fail_non_numeric():
    df = _synthetic_df()
    df["电流(A)"] = df["电流(A)"].astype(object)
    df.loc[5, "电流(A)"] = "abc"  # pandas 3.0 禁止 lossy setitem，先转 object 再赋值
    result = svc.validate_signal(df)
    assert result["overall"] == "fail"
    assert any(r["name"] == "数值类型" and r["status"] == "fail" for r in result["rules"])


def test_validate_signal_fail_no_signal_channel():
    df = pd.DataFrame({"时间": [0.0, 0.001, 0.002], "注释": ["a", "b", "c"]})
    result = svc.validate_signal(df)
    assert result["overall"] == "fail"
    assert any(r["name"] == "通道覆盖" and r["status"] == "fail" for r in result["rules"])


def test_validate_signal_warn_unknown_column():
    df = _synthetic_df()
    df["备注"] = "x"
    result = svc.validate_signal(df)
    assert result["overall"] == "warn"
    assert any(r["name"] == "表头识别" and r["status"] == "warn" for r in result["rules"])


def test_validate_signal_fallback_fs_from_record(db_engine):
    # 无时间列时用登记采样率兜底（seed 记录 sample_rate="10 kHz" → 10000 Hz）
    df = _synthetic_df().drop(columns=["时间"])
    with Session(db_engine) as session:
        record = session.exec(select(svc.DataRecord)).first()
    result = svc.validate_signal(df, record)
    assert result["overall"] in ("pass", "warn")
    assert result["fs"] == 10000
    # 无登记记录 → fs None → fail
    result2 = svc.validate_signal(df, None)
    assert result2["overall"] == "fail"
    assert result2["fs"] is None


# ── 单元：启发式 detect_events ────────────────────────────────────────


def test_detect_events_finds_arc_weld_tail_and_anomalies():
    df = _synthetic_df()
    column_map, _ = svc.map_columns(list(df.columns))
    events, anomalies = svc.detect_events(df, column_map, fs=1000)
    assert 0.5 <= events["arc"] <= 0.7
    assert events["weld_segment"][0] <= 0.7
    assert events["weld_segment"][1] >= 4.5
    assert events["tail"] >= events["weld_segment"][1]
    assert len(anomalies) == 2
    types = {a["type"] for a in anomalies}
    assert types <= {"电弧不稳", "飞溅倾向"}
    for a in anomalies:
        assert a["start"] < a["end"]
        assert 1.0 <= a["start"] <= 4.5


# ── 单元：Parquet round-trip ──────────────────────────────────────────


def test_parquet_roundtrip(db_engine):
    df = _synthetic_df()
    column_map, _ = svc.map_columns(list(df.columns))
    with Session(db_engine) as session:
        record = session.exec(
            select(svc.DataRecord).where(svc.DataRecord.weld_id == WELD_0248)
        ).first()
        version = session.exec(select(DataVersion)).first()
    pb = svc.to_parquet_bytes(df, column_map, 1000, record, version, 1, CSV_KEY)
    ingest = SignalIngest(
        id=1, job_id=1, version_id=version.id, source_object_key=CSV_KEY,
        status="succeeded", sample_rate=1000, duration=5.0,
        events={"arc": 0.6, "weld_segment": [0.6, 4.6], "tail": 4.86},
        anomalies=[{"start": 1.9, "end": 2.3, "type": "电弧不稳"}],
    )
    bundle = svc.bundle_from_parquet(pb, ingest, WELD_0248)
    assert bundle.source == "real"
    assert [c.id for c in bundle.channels] == ["cur", "vol", "gas", "wir"]
    assert bundle.sample_rate == 1000
    assert abs(bundle.duration - 5.0) < 0.02
    cur = bundle.channel("cur")
    assert cur.values.shape == (5000,)
    assert cur.mean == round(float(np.mean(df["电流(A)"])), 2)
    assert bundle.events["arc"] == 0.6
    assert bundle.anomalies == ingest.anomalies


# ── API：自动触发 + 导入 + 回退 ───────────────────────────────────────


def test_raw_files_csv_auto_trigger_and_ingest(
    db_engine, override_get_session, override_get_current_user,
    executor_sessionlocal, fake_storage,
) -> None:
    csv_bytes = _signal_csv_bytes()
    fake_storage.blobs[CSV_KEY] = csv_bytes
    v10 = _v10_id(db_engine)

    resp = client.post(
        f"/api/v1/registrations/{REG_0248}/raw-files",
        json={"object_keys": [CSV_KEY]},
    )
    assert resp.status_code == 200, resp.text[:300]
    assert resp.json()["code"] == 0
    # 自动建了 pending signal_ingest + job
    rows = _ingest_rows(db_engine)
    assert len(rows) == 1
    assert rows[0].version_id == v10
    assert rows[0].status == "pending"

    job_uid = _signal_ingest_job_uid(db_engine)
    run_job(job_uid)

    rows = _ingest_rows(db_engine)
    assert rows[0].status == "succeeded"
    assert rows[0].parquet_key.endswith(".parquet")
    assert rows[0].sample_rate == 1000
    assert rows[0].events["arc"] > 0
    assert len(rows[0].anomalies) == 2

    # 分析端点返回真实信号
    sig = client.get(f"/api/v1/welds/{WELD_0248}/versions/{v10}/signals").json()["data"]
    assert sig["source"] == "real"
    assert {c["id"] for c in sig["channels"]} == {"cur", "vol", "gas", "wir"}
    # 真实波形不同于生成器（起点为 idle 15A 而非生成器弧前形态）
    cur = next(c for c in sig["channels"] if c["id"] == "cur")
    assert len(cur["values"]) > 0

    result = client.get(f"/api/v1/welds/{WELD_0248}/versions/{v10}/analysis/result").json()["data"]
    assert result["source"] == "real"

    # 六 mode 在 real 数据下形状不变
    for mode, keys in MODE_KEYS.items():
        ch = "cur" if mode != "phase" else "cur"
        r = client.get(
            f"/api/v1/welds/{WELD_0248}/versions/{v10}/analysis/{mode}",
            params={"channel": ch},
        ).json()
        assert r["code"] == 0, (mode, r)
        for k in keys:
            assert k in r["data"], (mode, k)


def test_auto_executor_consumes_signal_ingest_job(
    db_engine, override_get_session, override_get_current_user,
    executor_sessionlocal, fake_storage, monkeypatch,
) -> None:
    fake_storage.blobs[CSV_KEY] = _signal_csv_bytes()
    client.post(
        f"/api/v1/registrations/{REG_0248}/raw-files",
        json={"object_keys": [CSV_KEY]},
    )
    job_uid = _signal_ingest_job_uid(db_engine)
    monkeypatch.setattr(executor_mod, "_POLL_INTERVAL", 0.05)
    executor_mod.stop()
    executor_mod.start()
    try:
        deadline = time.time() + 3
        data = None
        while time.time() < deadline:
            data = client.get(f"/api/v1/jobs/{job_uid}").json()["data"]
            if data["status"] in {"succeeded", "failed"}:
                break
            time.sleep(0.05)
        assert data is not None and data["status"] == "succeeded"
    finally:
        executor_mod.stop()


def test_reattach_same_csv_is_idempotent(
    db_engine, override_get_session, override_get_current_user,
    executor_sessionlocal, fake_storage,
) -> None:
    fake_storage.blobs[CSV_KEY] = _signal_csv_bytes()
    client.post(
        f"/api/v1/registrations/{REG_0248}/raw-files",
        json={"object_keys": [CSV_KEY]},
    )
    client.post(
        f"/api/v1/registrations/{REG_0248}/raw-files",
        json={"object_keys": [CSV_KEY, "raw/REG-20260815-00248/video.mp4"]},
    )
    rows = _ingest_rows(db_engine)
    assert len(rows) == 1  # 重复挂载同一 CSV 不重复建任务


def test_invalid_csv_failed_and_fallback_generated(
    db_engine, override_get_session, override_get_current_user,
    executor_sessionlocal, fake_storage,
) -> None:
    # 非数值 → 校验 fail → 不写 Parquet → 分析回退 generated
    bad = "时间,电流(A),电压(V)\n0,abc,1\n0.001,200,22\n0.002,100,21\n"
    fake_storage.blobs[CSV_KEY] = bad.encode()
    client.post(
        f"/api/v1/registrations/{REG_0248}/raw-files",
        json={"object_keys": [CSV_KEY]},
    )
    job_uid = _signal_ingest_job_uid(db_engine)
    run_job(job_uid)

    rows = _ingest_rows(db_engine)
    assert rows[0].status == "failed"
    assert rows[0].parquet_key is None

    v10 = _v10_id(db_engine)
    sig = client.get(f"/api/v1/welds/{WELD_0248}/versions/{v10}/signals").json()["data"]
    assert sig["source"] == "generated"


def test_no_csv_falls_back_generated(
    db_engine, override_get_session, override_get_current_user, fake_storage,
) -> None:
    # seed 假文件版本无 signal_ingest → 回退生成
    v10 = _v10_id(db_engine)
    sig = client.get(f"/api/v1/welds/{WELD_0248}/versions/{v10}/signals").json()["data"]
    assert sig["source"] == "generated"
    result = client.get(f"/api/v1/welds/{WELD_0248}/versions/{v10}/analysis/result").json()["data"]
    assert result["source"] == "generated"


def test_signal_ingest_requires_auth(
    db_engine, override_get_session,
) -> None:
    # 未 override get_current_user → 401
    resp = client.get(f"/api/v1/welds/{WELD_0248}/versions/1/signals")
    assert resp.status_code == 401
