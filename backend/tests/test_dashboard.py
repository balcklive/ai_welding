"""Task 8：Dashboard 四个总览端点测试。

内存 SQLite + StaticPool + 真实 app TestClient（同 test_auth / test_jobs）。
先 `seed_all` 造演示数据（4 焊缝 / 3 数据集 / 2 样本 / 2 标注），再 override
`get_session` → 测试 session、`get_current_user` → 假 User（免签 token）。

覆盖：四端点信封 code==0、stats 数值（data_total==4 等）、projects 3 条且字段
来自数据集、attributes 非空（含统计口径词表）、distributions 缺陷含统计词表、
未登录 401。
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
from app.services.dashboard import DEFECT_VOCAB

client = TestClient(app)

STATS_PATH = "/api/v1/dashboard/stats"
ATTRIBUTES_PATH = "/api/v1/dashboard/attributes"
DISTRIBUTIONS_PATH = "/api/v1/dashboard/distributions"
PROJECTS_PATH = "/api/v1/dashboard/projects"


@pytest.fixture()
def db_session():
    """内存 SQLite + StaticPool：每用例全新引擎 + seed_all 演示数据。"""
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
    """假登录：get_current_user 直接返回一个 User，免 seed/免签 token。"""
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


# ---------- GET /dashboard/stats ----------


def test_stats_envelope_and_values(
    override_get_session, override_get_current_user
) -> None:
    resp = client.get(STATS_PATH)
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    assert body["message"] == "ok"

    data = body["data"]
    assert data["data_total"] == 4
    assert data["manufacturer_total"] == 4
    assert data["max_storage_bytes"] == 2576980378
    assert data["annotated_samples"] == 2
    # 2 个样本全部已标注 → 完成度 100%
    assert data["annotation_completion"] == 100.0


# ---------- GET /dashboard/attributes ----------


def test_attributes_envelope_and_non_empty(
    override_get_session, override_get_current_user
) -> None:
    resp = client.get(ATTRIBUTES_PATH)
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0

    data = body["data"]
    # 焊机种类（distinct machine，seed 4 台）
    assert data["weld_methods"]
    assert set(data["weld_methods"]) == {
        "Fronius CMT",
        "OTC FD-V8",
        "Kemppi Minarc",
        "Panasonic YD-500",
    }
    # 缺陷种类 = 统计口径词表 + count
    assert data["defect_types"]
    assert [d["name"] for d in data["defect_types"]] == DEFECT_VOCAB
    assert all({"name", "count"} <= set(d) for d in data["defect_types"])
    # 多模态种类（distinct modality 名）
    assert set(data["modalities"]) == {"video", "timeseries", "audio", "infrared"}
    # 采集频率档位（distinct sample_rate）
    assert data["sample_rate_tiers"] == ["10 kHz", "20 kHz"]


# ---------- GET /dashboard/distributions ----------


def test_distributions_envelope_and_shapes(
    override_get_session, override_get_current_user
) -> None:
    resp = client.get(DISTRIBUTIONS_PATH)
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0

    data = body["data"]
    # 厂商比重：非空，shape {name, value}
    assert data["manufacturers"]
    assert all({"name", "value"} <= set(m) for m in data["manufacturers"])
    # 过渡类型 / 焊接类型：非空且数值与 seed 自洽
    assert data["transition_types"]
    assert data["welding_types"]
    welding = {w["name"]: w["value"] for w in data["welding_types"]}
    assert welding == {"MAG焊": 2, "MIG焊": 1, "TIG焊": 1}
    # 缺陷分布：含统计口径词表全部条目
    assert {d["name"] for d in data["defects"]} == set(DEFECT_VOCAB)
    assert all({"name", "count"} <= set(d) for d in data["defects"])
    # 厂商词云：非空，shape {name, size}
    assert data["wordcloud"]
    assert all({"name", "size"} <= set(w) for w in data["wordcloud"])


# ---------- GET /dashboard/projects ----------


def test_projects_three_entries_from_datasets(
    override_get_session, override_get_current_user
) -> None:
    resp = client.get(PROJECTS_PATH)
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0

    projects = body["data"]
    assert len(projects) == 3
    assert {p["name"] for p in projects} == {
        "焊接缺陷检测集",
        "熔池分割数据集",
        "工艺质量预测集",
    }
    for project in projects:
        assert set(project) == {
            "name",
            "status",
            "sample_count",
            "progress",
            "updated_at",
        }
        assert project["status"] in {"标注中", "可训练"}
        assert isinstance(project["sample_count"], int)
        assert isinstance(project["progress"], float)
        assert project["updated_at"].endswith("Z")


# ---------- 未登录 ----------


def test_dashboard_requires_login(override_get_session) -> None:
    """不 override get_current_user：无 Authorization 头 → 401 信封。"""
    for path in (STATS_PATH, ATTRIBUTES_PATH, DISTRIBUTIONS_PATH, PROJECTS_PATH):
        resp = client.get(path)
        assert resp.status_code == 401, path
        assert resp.json()["code"] == 40100, path
