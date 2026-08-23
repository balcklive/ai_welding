"""Task 11：Analysis 端点测试（candidates / signals / 六 mode / result）。

内存 SQLite + StaticPool + 真实 app TestClient（同 test_welds / test_dashboard）。
先 `seed_all` 造演示数据（4 焊缝：0248/0247/0246/0245，其中 0248、0246 quality=通过），
再 override `get_session` → 测试 session、`get_current_user` → 假 User。

覆盖：candidates 只含通过焊缝；signals 4 通道 + 2 异常 + 正确时长 + channels[] 筛选与
滤波联动；六个 mode 端点返回 200 且含预期键（psd freqs/psd、stft magnitude、
dwt/wavelet bands、phase current、pdd counts）；result 含 stability+segments+anomalies；
未知 mode / 未知通道 / 非法滤波参数 → 400；全部端点未登录 401。
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel

from app.api.deps import get_current_user
from app.core.db import get_session
from app.core.seed import seed_all
from app.main import app
from app.models import User

client = TestClient(app)

WELD_0248 = "WLD-20260815-0248"
WELD_0247 = "WLD-20260815-0247"
WELD_0246 = "WLD-20260814-0246"
WELD_0245 = "WLD-20260814-0245"

#: mode → 应出现在返回 data 里的键。
MODE_KEYS = {
    "psd": ("freqs", "psd"),
    "stft": ("times", "freqs", "magnitude"),
    "dwt": ("bands", "approx"),
    "wavelet": ("bands",),
    "phase": ("current", "voltage"),
    "pdd": ("bins", "counts", "kde"),
}


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


def _version_id_by_no(weld_id, version_no="v1.0"):
    versions = client.get(f"/api/v1/welds/{weld_id}/versions").json()["data"]
    for v in versions:
        if v["version_no"] == version_no:
            return v["id"]
    raise AssertionError(f"{version_no} not found for {weld_id}")


# ---------- GET /analysis/candidates ----------


def test_candidates_only_through_welds(
    override_get_session, override_get_current_user
) -> None:
    resp = client.get("/api/v1/analysis/candidates")
    assert resp.status_code == 200
    data = resp.json()["data"]
    ids = {item["weld_id"] for item in data}
    assert ids == {WELD_0248, WELD_0246}  # quality=通过 只有这两条
    for item in data:
        assert item["quality"] == "通过"
        assert {"weld_id", "registration_no", "weld_name", "quality"} <= set(item)


# ---------- GET …/signals ----------


def test_signals_returns_4_channels_and_events(
    override_get_session, override_get_current_user
) -> None:
    vid = _version_id_by_no(WELD_0248)
    resp = client.get(f"/api/v1/welds/{WELD_0248}/versions/{vid}/signals")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["duration"] == 5.42
    assert data["sample_rate"] == 1000
    assert len(data["channels"]) == 4
    ids = [c["id"] for c in data["channels"]]
    assert ids == ["cur", "vol", "gas", "wir"]
    for chan in data["channels"]:
        assert set(chan) >= {"id", "name", "unit", "values", "lo", "hi", "mean"}
        assert len(chan["values"]) == 5420
        assert all(chan["lo"] <= v <= chan["hi"] for v in chan["values"])
    assert data["events"] == {"arc": 0.42, "weld_segment": [0.78, 4.28], "tail": 4.86}
    assert len(data["anomalies"]) == 2
    assert data["anomalies"][0]["type"] == "电弧不稳"
    assert data["anomalies"][1]["type"] == "飞溅倾向"


def test_signals_channel_selection_and_filter(
    override_get_session, override_get_current_user
) -> None:
    vid = _version_id_by_no(WELD_0248)
    # channels[] 筛选
    resp = client.get(
        f"/api/v1/welds/{WELD_0248}/versions/{vid}/signals",
        params=[("channels[]", "cur"), ("channels[]", "vol")],
    )
    data = resp.json()["data"]
    assert [c["id"] for c in data["channels"]] == ["cur", "vol"]

    # 滤波联动（低通）→ 200 且值仍在量程内
    resp = client.get(
        f"/api/v1/welds/{WELD_0248}/versions/{vid}/signals",
        params=[("channels[]", "cur"), ("filter_type", "低通"), ("cutoff", "0.2")],
    )
    assert resp.status_code == 200
    cur = resp.json()["data"]["channels"][0]
    assert all(0 <= v <= 300 for v in cur["values"])

    # 非法滤波参数 → 400
    resp = client.get(
        f"/api/v1/welds/{WELD_0248}/versions/{vid}/signals",
        params={"filter_type": "低通", "cutoff": "2"},
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == 40000
    # 未知通道 → 400
    resp = client.get(
        f"/api/v1/welds/{WELD_0248}/versions/{vid}/signals",
        params=[("channels[]", "cur"), ("channels[]", "bogus")],
    )
    assert resp.status_code == 400


def test_signals_unknown_weld_or_version(
    override_get_session, override_get_current_user
) -> None:
    vid = _version_id_by_no(WELD_0248)
    resp = client.get(f"/api/v1/welds/WLD-NOPE-0000/versions/{vid}/signals")
    assert resp.status_code == 404 and resp.json()["code"] == 40401
    resp = client.get(f"/api/v1/welds/{WELD_0248}/versions/999999/signals")
    assert resp.status_code == 404 and resp.json()["code"] == 40402


# ---------- GET …/analysis/{mode} ----------


@pytest.mark.parametrize("mode", sorted(MODE_KEYS))
def test_analysis_modes_return_expected_keys(
    override_get_session, override_get_current_user, mode
) -> None:
    vid = _version_id_by_no(WELD_0248)
    resp = client.get(f"/api/v1/welds/{WELD_0248}/versions/{vid}/analysis/{mode}")
    assert resp.status_code == 200, (mode, resp.text[:300])
    data = resp.json()["data"]
    for key in MODE_KEYS[mode]:
        assert key in data, (mode, key)
    if mode in ("dwt", "wavelet"):
        assert len(data["bands"]) == (4 if mode == "dwt" else 5)


def test_analysis_mode_with_filter_and_channel(
    override_get_session, override_get_current_user
) -> None:
    vid = _version_id_by_no(WELD_0248)
    resp = client.get(
        f"/api/v1/welds/{WELD_0248}/versions/{vid}/analysis/psd",
        params={"channel": "vol", "filter_type": "高通", "cutoff": "0.1"},
    )
    assert resp.status_code == 200
    assert "freqs" in resp.json()["data"]
    # pdd 携带通道量程 → bins 端点落在 lo..hi 区间
    resp = client.get(
        f"/api/v1/welds/{WELD_0248}/versions/{vid}/analysis/pdd",
        params={"channel": "cur"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["bins"][0] >= 0


def test_analysis_unknown_mode_and_channel(
    override_get_session, override_get_current_user
) -> None:
    vid = _version_id_by_no(WELD_0248)
    resp = client.get(f"/api/v1/welds/{WELD_0248}/versions/{vid}/analysis/whatever")
    assert resp.status_code == 400
    assert resp.json()["code"] == 40000
    resp = client.get(
        f"/api/v1/welds/{WELD_0248}/versions/{vid}/analysis/psd",
        params={"channel": "bogus"},
    )
    assert resp.status_code == 400


# ---------- GET …/analysis/result ----------


def test_analysis_result_stability_and_segments(
    override_get_session, override_get_current_user
) -> None:
    vid = _version_id_by_no(WELD_0248)
    resp = client.get(f"/api/v1/welds/{WELD_0248}/versions/{vid}/analysis/result")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert 0 <= data["stability"] <= 100
    assert set(data["segments"]) == {"normal", "arc_instability", "sputter"}
    assert abs(sum(data["segments"].values()) - 100) < 0.02
    assert len(data["anomalies"]) == 2
    # 确定性：同焊缝结果可复现
    again = client.get(f"/api/v1/welds/{WELD_0248}/versions/{vid}/analysis/result")
    assert again.json()["data"] == data


# ---------- 未登录 ----------


def test_analysis_endpoints_require_login(override_get_session) -> None:
    # 未登录时 router 级依赖在路由逻辑前抛 401，故版本 id 用字面值即可（不查库）。
    vid = 1
    paths = [
        ("GET", "/api/v1/analysis/candidates"),
        ("GET", f"/api/v1/welds/{WELD_0248}/versions/{vid}/signals"),
        ("GET", f"/api/v1/welds/{WELD_0248}/versions/{vid}/analysis/psd"),
        ("GET", f"/api/v1/welds/{WELD_0248}/versions/{vid}/analysis/result"),
    ]
    for method, path in paths:
        resp = client.request(method, path)
        assert resp.status_code == 401, (method, path)
        assert resp.json()["code"] == 40100, (method, path)
