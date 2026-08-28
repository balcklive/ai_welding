"""波形预览抽稀（min-max 池化 + 时间窗）：纯函数 + `/signals` 端点参数。

不连远程库：内存 SQLite + StaticPool + seed_all + override 依赖（同 test_analysis）。
seed 无真实 Parquet → `/signals` 走 generated 兜底（5.42s / 1000Hz → 5420 点），
正好用来断言抽稀与窗口切片在生成信号路径上的行为。
"""

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.api.deps import get_current_user
from app.core.db import get_session
from app.core.seed import seed_all
from app.main import app
from app.models import DataVersion, User
from app.services.signals import downsample_indices

client = TestClient(app)

WELD_0248 = "WLD-20260815-0248"


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
def vid(db_engine) -> int:
    with Session(db_engine) as session:
        v = session.exec(
            select(DataVersion).where(DataVersion.version_no == "v1.0")
        ).first()
        return v.id


# ── 纯函数：downsample_indices ────────────────────────────────────────


def test_downsample_keeps_transient_spike():
    """min-max 池化必须保留孤立瞬态尖峰（均匀抽样会把它抽没）。"""
    x = np.zeros(1000)
    x[555] = 100.0
    idx = downsample_indices(x, 100)
    assert 555 in set(idx.tolist())
    assert len(idx) <= 100


def test_downsample_time_ordered_and_bounded():
    x = np.sin(np.linspace(0, 40 * np.pi, 90000))
    idx = downsample_indices(x, 2048)
    assert len(idx) <= 2048
    assert np.all(np.diff(idx) > 0)  # 时间升序
    assert idx[0] == 0 and idx[-1] == len(x) - 1  # 端点保留


def test_downsample_flat_and_small_inputs():
    assert len(downsample_indices(np.full(500, 3.0), 10)) == 10
    small = np.arange(50.0)
    assert np.array_equal(downsample_indices(small, 100), small)  # 全量直通
    assert np.array_equal(downsample_indices(small, 0), small)  # 非法参数直通


def test_downsample_deterministic():
    x = np.random.default_rng(7).standard_normal(5000)
    assert np.array_equal(downsample_indices(x, 256), downsample_indices(x, 256))


# ── 端点：max_points / start / end ────────────────────────────────────


def test_signals_max_points_returns_times(
    override_get_session, override_get_current_user, vid
):
    resp = client.get(
        f"/api/v1/welds/{WELD_0248}/versions/{vid}/signals?max_points=64"
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["source"] == "generated"
    for chan in data["channels"]:
        assert 0 < len(chan["values"]) <= 64
        assert len(chan["times"]) == len(chan["values"])  # min-max 非均匀，必带 times
        # times 单调递增且落在 [0, duration]
        assert all(b > a for a, b in zip(chan["times"], chan["times"][1:]))
        assert chan["times"][0] >= 0 and chan["times"][-1] <= data["duration"]
    # 抽稀后量程信息不变
    assert data["channels"][0]["lo"] == 0


def test_signals_max_points_preserves_extremes(
    override_get_session, override_get_current_user, vid
):
    """抽稀后通道 min/max 与全量一致（尖峰/谷值不被抽掉）。"""
    full = client.get(f"/api/v1/welds/{WELD_0248}/versions/{vid}/signals").json()["data"]
    sparse = client.get(
        f"/api/v1/welds/{WELD_0248}/versions/{vid}/signals?max_points=256"
    ).json()["data"]
    for cf, cs in zip(full["channels"], sparse["channels"]):
        assert min(cs["values"]) == pytest.approx(min(cf["values"]), abs=1e-6)
        assert max(cs["values"]) == pytest.approx(max(cf["values"]), abs=1e-6)


def test_signals_window_slice(
    override_get_session, override_get_current_user, vid
):
    resp = client.get(
        f"/api/v1/welds/{WELD_0248}/versions/{vid}/signals"
        "?max_points=128&start=1&end=2&channels=cur"
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert len(data["channels"]) == 1
    chan = data["channels"][0]
    assert len(chan["values"]) <= 128
    assert all(1.0 <= t <= 2.0 for t in chan["times"])  # 窗口内
    assert data["duration"] == pytest.approx(5.42)  # duration 恒为全程


def test_signals_without_params_stays_full_and_compat(
    override_get_session, override_get_current_user, vid
):
    """不传参数保持旧契约：全分辨率、无 times 字段。"""
    resp = client.get(f"/api/v1/welds/{WELD_0248}/versions/{vid}/signals")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert len(data["channels"]) == 4
    assert all("times" not in c for c in data["channels"])
    assert len(data["channels"][0]["values"]) == 5420


def test_signals_invalid_params(
    override_get_session, override_get_current_user, vid
):
    for query in ("max_points=1", "max_points=99999", "start=2&end=1", "start=1"):
        resp = client.get(
            f"/api/v1/welds/{WELD_0248}/versions/{vid}/signals?{query}"
        )
        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] == 40000
