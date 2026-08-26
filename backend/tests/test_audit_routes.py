"""Task 4：upload/presign/alignment/features/report export 审计回归。"""

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, select

from app.api.deps import get_current_user
from app.core.db import get_session
from app.core.seed import seed_all
from app.main import app
from app.models import AuditLog, User

client = TestClient(app)
WELD_0248 = "WLD-20260815-0248"


class FakeStorage:
    def __init__(self) -> None:
        self.sizes = {
            "raw/REG-20260815-00248/align.csv": 12,
        }

    def normalize_key(self, prefix: str, filename: str) -> str:
        return f"{prefix.strip('/')}/{filename or 'file'}"

    def upload_stream(self, object_key, fileobj, size, content_type):
        return object_key

    def presign_get(self, object_key, expires=3600):
        return f"https://minio.local/{object_key}?expires={expires}"

    def presign_put(self, prefix, filename, size, content_type):
        key = self.normalize_key(prefix, filename)
        return key, f"https://minio.local/{key}?signature=put"

    def stat_object(self, object_key: str) -> int:
        if object_key not in self.sizes:
            raise FileNotFoundError(object_key)
        return self.sizes[object_key]


import pytest


@pytest.fixture()
def db_engine(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        seed_all(session)
    monkeypatch.setattr("app.api.v1.files.get_storage", lambda: FakeStorage())
    monkeypatch.setattr("app.api.v1.welds.get_storage", lambda: FakeStorage())
    monkeypatch.setattr("app.storage.get_storage", lambda: FakeStorage())
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
        username="admin",
        password_hash="not-a-real-hash",
        display_name="林工",
        role="admin",
    )

    def _override() -> User:
        return dummy

    app.dependency_overrides[get_current_user] = _override
    yield
    app.dependency_overrides.pop(get_current_user, None)


def _audit_keys(db_engine):
    with Session(db_engine) as session:
        return [(row.action, row.resource_type, row.resource_id) for row in session.exec(select(AuditLog).order_by(AuditLog.id)).all()]


def test_route_audits_cover_upload_presign_alignment_features_and_report(
    db_engine, override_get_session, override_get_current_user
):
    client.post("/api/v1/files/upload", files={"file": ("demo.txt", b"hello", "text/plain")})
    client.post(
        "/api/v1/files/presign-upload",
        json={"size": 1024, "content_type": "video/mp4", "prefix": "uploads/demo", "filename": "video.mp4"},
    )
    version_id = client.get(f"/api/v1/welds/{WELD_0248}/versions").json()["data"][0]["id"]
    client.post(
        f"/api/v1/welds/{WELD_0248}/versions/{version_id}/alignment-tasks",
        json={"modalities": ["video", "timeseries"]},
    )
    client.post(
        "/api/v1/features/extract",
        json={"weld_id": WELD_0248, "version_id": version_id, "normalization": "无", "format": "JSON"},
    )
    client.post(
        "/api/v1/reports/export",
        json={"type": "analysis", "ref_ids": [version_id], "format": "json"},
    )

    keys = _audit_keys(db_engine)
    assert any(action == "upload" and resource_type == "file" for action, resource_type, _ in keys)
    assert any(action == "presign_upload" and resource_type == "file" for action, resource_type, _ in keys)
    assert any(action == "create" and resource_type == "alignment_task" for action, resource_type, _ in keys)
    assert any(action == "extract" and resource_type == "feature_extraction" for action, resource_type, _ in keys)
    assert any(action == "export" and resource_type == "report" for action, resource_type, _ in keys)
