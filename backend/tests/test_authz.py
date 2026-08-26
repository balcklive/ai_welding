"""Task 4：最小 ACL / ownership 边界回归。

内存 SQLite + StaticPool + 真实 app TestClient；`seed_all` 造 admin 资源。
通过 dependency override 在 admin / 普通用户之间切换，验证：
- 普通用户不能读取/修改管理员登记及其关联焊缝/版本/分析任务/报告；
- 管理员路径不回归；
- 资源创建者可继续访问自己创建的登记。
"""

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, select

from app.api.deps import get_current_user
from app.core.db import get_session
from app.core.seed import seed_all
from app.main import app
from app.models import DataVersion, User

client = TestClient(app)
WELD_0248 = "WLD-20260815-0248"


def _user(*, user_id: int, username: str, display_name: str, role: str) -> User:
    return User(
        id=user_id,
        username=username,
        password_hash="not-a-real-hash",
        display_name=display_name,
        role=role,
    )


class _CurrentUser:
    def __init__(self) -> None:
        self.value = _user(user_id=1, username="admin", display_name="林工", role="admin")

    def __call__(self) -> User:
        return self.value


state = _CurrentUser()


import pytest


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
    app.dependency_overrides[get_current_user] = state
    state.value = _user(user_id=1, username="admin", display_name="林工", role="admin")
    yield state
    app.dependency_overrides.pop(get_current_user, None)


def _version_id(db_engine) -> int:
    with Session(db_engine) as session:
        return session.exec(
            select(DataVersion.id)
            .join_from(DataVersion, DataVersion)
            .where(DataVersion.version_no == "v1.0")
            .order_by(DataVersion.id)
        ).first()


def test_non_admin_cannot_access_admin_registration_related_resources(
    db_engine, override_get_session, override_get_current_user
):
    record = client.get(f"/api/v1/welds/{WELD_0248}").json()["data"]
    registration_id = record["id"]
    version_id = client.get(f"/api/v1/welds/{WELD_0248}/versions").json()["data"][0]["id"]

    override_get_current_user.value = _user(user_id=2, username="worker", display_name="二号用户", role="user")

    for method, path, payload in [
        ("GET", f"/api/v1/registrations/{registration_id}", None),
        ("PATCH", f"/api/v1/registrations/{registration_id}", {"product": "hack"}),
        ("GET", f"/api/v1/welds/{WELD_0248}", None),
        ("GET", f"/api/v1/welds/{WELD_0248}/versions", None),
        ("POST", f"/api/v1/welds/{WELD_0248}/versions/{version_id}/alignment-tasks", {"modalities": ["video", "timeseries"]}),
        ("POST", "/api/v1/reports/export", {"type": "analysis", "ref_ids": [version_id], "format": "json"}),
    ]:
        resp = client.request(method, path, json=payload)
        assert resp.status_code == 403, (method, path, resp.text)
        assert resp.json()["code"] == 40300


def test_creator_can_access_own_registration_but_not_admin_resources(
    db_engine, override_get_session, override_get_current_user
):
    override_get_current_user.value = _user(user_id=2, username="worker", display_name="二号用户", role="user")
    created = client.post(
        "/api/v1/registrations",
        json={
            "source": "lab",
            "weld_name": "worker-own-record",
            "machine": "demo",
            "weld_method": "MAG焊",
            "material": "Q235B",
        },
    )
    assert created.status_code == 200, created.text
    record = created.json()["data"]
    registration_id = record["id"]

    get_resp = client.get(f"/api/v1/registrations/{registration_id}")
    assert get_resp.status_code == 200
    patch_resp = client.patch(
        f"/api/v1/registrations/{registration_id}",
        json={"product": "worker-product"},
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["data"]["product"] == "worker-product"

    admin_registration = client.get("/api/v1/welds").json()["data"]["items"]
    assert [item["weld_id"] for item in admin_registration] == [record["weld_id"]]


def test_admin_access_not_regressed(
    db_engine, override_get_session, override_get_current_user
):
    override_get_current_user.value = _user(user_id=1, username="admin", display_name="林工", role="admin")
    resp = client.get(f"/api/v1/registrations/REG-20260815-00248")
    assert resp.status_code == 200
    report = client.post(
        "/api/v1/reports/export",
        json={"type": "analysis", "ref_ids": [1], "format": "json"},
    )
    assert report.status_code == 200, report.text


def test_same_display_name_collision_does_not_grant_access(
    db_engine, override_get_session, override_get_current_user
):
    record = client.get(f"/api/v1/welds/{WELD_0248}").json()["data"]
    registration_id = record["id"]

    override_get_current_user.value = _user(
        user_id=2,
        username="different-user",
        display_name="林工",
        role="user",
    )

    resp = client.get(f"/api/v1/registrations/{registration_id}")
    assert resp.status_code == 403, resp.text
    assert resp.json()["code"] == 40300


def test_owner_keeps_access_after_rename(
    db_engine, override_get_session, override_get_current_user
):
    override_get_current_user.value = _user(user_id=2, username="worker", display_name="旧名字", role="user")
    created = client.post(
        "/api/v1/registrations",
        json={
            "source": "lab",
            "weld_name": "rename-safe-record",
            "machine": "demo",
            "weld_method": "MAG焊",
            "material": "Q235B",
        },
    )
    assert created.status_code == 200, created.text
    registration_id = created.json()["data"]["id"]

    override_get_current_user.value = _user(user_id=2, username="worker-renamed", display_name="新名字", role="user")

    get_resp = client.get(f"/api/v1/registrations/{registration_id}")
    assert get_resp.status_code == 200, get_resp.text
    patch_resp = client.patch(
        f"/api/v1/registrations/{registration_id}",
        json={"product": "renamed-owner-still-works"},
    )
    assert patch_resp.status_code == 200, patch_resp.text
    assert patch_resp.json()["data"]["product"] == "renamed-owner-still-works"


def test_non_admin_cannot_read_analysis_or_feature_resources_of_admin_record(
    db_engine, override_get_session, override_get_current_user
):
    version_id = client.get(f"/api/v1/welds/{WELD_0248}/versions").json()["data"][0]["id"]
    extraction = client.post(
        "/api/v1/features/extract",
        json={"weld_id": WELD_0248, "version_id": version_id, "normalization": "无", "format": "JSON"},
    )
    assert extraction.status_code == 200, extraction.text
    extraction_id = extraction.json()["data"]["id"]

    override_get_current_user.value = _user(user_id=2, username="worker", display_name="二号用户", role="user")

    for method, path, payload in [
        ("GET", f"/api/v1/welds/{WELD_0248}/versions/{version_id}/signals", None),
        ("GET", f"/api/v1/welds/{WELD_0248}/versions/{version_id}/analysis/result", None),
        ("GET", f"/api/v1/welds/{WELD_0248}/versions/{version_id}/analysis/psd?channel=cur", None),
        ("POST", "/api/v1/features/extract", {"weld_id": WELD_0248, "version_id": version_id, "normalization": "无", "format": "JSON"}),
        ("GET", f"/api/v1/features/{extraction_id}", None),
    ]:
        resp = client.request(method, path, json=payload)
        assert resp.status_code == 403, (method, path, resp.text)
        assert resp.json()["code"] == 40300
