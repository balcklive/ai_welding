"""Task 9：files 三端点（upload / presign-upload / url）测试。

内存 SQLite + StaticPool + 真实 app TestClient（同 test_auth / test_dashboard）。
依赖覆盖 `get_session` → 测试 session、`get_current_user` → 假 User（免签 token）；
**存储层 monkeypatch** `app.api.v1.files.get_storage` → 包 `FakeMinio` 的
`StorageClient`，只做参数透传断言，**不连真实 MinIO**。

覆盖：presign-upload 有效/自定义 filename/size=0/size>2GB/空 prefix、
upload 小文件（upload_stream 记录 key+size）/超限封顶、
get url 正常/expires 边界/坏 key、三个端点未登录全 401（不 override get_current_user）。
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel

from app.api.deps import get_current_user
from app.api.v1 import files as files_mod
from app.core.db import get_session
from app.main import app
from app.models import User
from app.storage import StorageClient

client = TestClient(app)

UPLOAD_PATH = "/api/v1/files/upload"
PRESIGN_PATH = "/api/v1/files/presign-upload"


class FakeMinio:
    """记录调用的假 Minio：断言参数透传并返回固定预签名 URL。"""

    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.puts: list[tuple] = []

    def bucket_exists(self, bucket: str) -> bool:
        return True

    def make_bucket(self, bucket: str) -> None:
        pass

    def presigned_put_object(self, bucket, object_name, expires=None, **kw):
        self.calls.append(("put", object_name))
        return f"https://minio.local/{bucket}/{object_name}?signature=put"

    def presigned_get_object(self, bucket, object_name, expires=None, **kw):
        self.calls.append(("get", object_name))
        return f"https://minio.local/{bucket}/{object_name}?expires=3600"

    def put_object(self, bucket, object_name, data, length, content_type=None, **kw):
        self.calls.append(("upload", object_name, length, content_type))
        self.puts.append((object_name, length))
        return object_name


@pytest.fixture()
def db_session():
    """内存 SQLite + StaticPool：每用例全新引擎（TestClient worker 线程共享连接）。"""
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


@pytest.fixture()
def storage_fixture(monkeypatch):
    """把 files 模块里的 `get_storage` 替换为包 FakeMinio 的 StorageClient。"""
    fake = FakeMinio()
    storage = StorageClient(client=fake, bucket="aiwelding")
    monkeypatch.setattr(files_mod, "get_storage", lambda: storage)
    return storage, fake


# ---------- POST /files/presign-upload ----------


def test_presign_upload_ok(
    override_get_session, override_get_current_user, storage_fixture
) -> None:
    _, fake = storage_fixture
    resp = client.post(
        PRESIGN_PATH,
        json={
            "size": 2 * 1024 * 1024 * 1024,
            "content_type": "video/mp4",
            "prefix": "raw/REG-20260815-00001",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    data = body["data"]
    # object_key = normalize_key(prefix, "file")：以 prefix 开头 + 默认文件名
    assert data["object_key"].startswith("raw/REG-20260815-00001/")
    assert data["object_key"].endswith("/file")
    assert isinstance(data["upload_url"], str) and data["upload_url"].startswith(
        "https://minio.local/aiwelding/"
    )
    assert data["upload_url"].endswith(data["object_key"] + "?signature=put")
    assert ("put", data["object_key"]) in fake.calls


def test_presign_upload_custom_filename(
    override_get_session, override_get_current_user, storage_fixture
) -> None:
    resp = client.post(
        PRESIGN_PATH,
        json={
            "size": 100 * 1024 * 1024,
            "content_type": "video/mp4",
            "prefix": "raw/REG-001",
            "filename": "原始视频.MP4",
        },
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    # 中文主干清洗空 → 回退 file，扩展名保留
    assert data["object_key"] == "raw/REG-001/file.mp4"


def test_presign_upload_size_zero(
    override_get_session, override_get_current_user, storage_fixture
) -> None:
    resp = client.post(
        PRESIGN_PATH, json={"size": 0, "content_type": "x", "prefix": "raw/R1"}
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body["code"] == 40000
    assert "size" in body["message"]


def test_presign_upload_size_over_2gb(
    override_get_session, override_get_current_user, storage_fixture
) -> None:
    resp = client.post(
        PRESIGN_PATH,
        json={
            "size": 2 * 1024 * 1024 * 1024 + 1,
            "content_type": "x",
            "prefix": "raw/R1",
        },
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == 40000


def test_presign_upload_empty_prefix(
    override_get_session, override_get_current_user, storage_fixture
) -> None:
    resp = client.post(
        PRESIGN_PATH, json={"size": 1024, "content_type": "x", "prefix": ""}
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == 40000


# ---------- POST /files/upload ----------


def test_upload_small_file(
    override_get_session, override_get_current_user, storage_fixture
) -> None:
    _, fake = storage_fixture
    resp = client.post(
        UPLOAD_PATH,
        files={"file": ("原始视频.MP4", b"hello-world", "video/mp4")},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    data = body["data"]
    assert data["object_key"].startswith("uploads/")
    assert data["object_key"].endswith("/file.mp4")
    assert isinstance(data["url"], str) and data["url"].startswith(
        "https://minio.local/aiwelding/"
    )
    # upload_stream 记录了 key + size（11 字节），并签发 GET url
    assert ("upload", data["object_key"], 11, "video/mp4") in fake.calls
    assert ("get", data["object_key"]) in fake.calls


def test_upload_over_limit(
    override_get_session, override_get_current_user, storage_fixture, monkeypatch
) -> None:
    """流式封顶：把上限压到 4 字节，发 5 字节 → 400，且未触发真实上传。"""
    _, fake = storage_fixture
    monkeypatch.setattr(files_mod, "MAX_PROXY_UPLOAD_SIZE", 4)
    resp = client.post(
        UPLOAD_PATH,
        files={"file": ("big.bin", b"12345", "application/octet-stream")},
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == 40000
    assert not fake.puts


# ---------- GET /files/{object_key}/url ----------


def test_get_url_ok(
    override_get_session, override_get_current_user, storage_fixture
) -> None:
    _, fake = storage_fixture
    resp = client.get("/api/v1/files/uploads/uuid-1/0001.mp4/url")
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    data = body["data"]
    assert data["url"].startswith(
        "https://minio.local/aiwelding/uploads/uuid-1/0001.mp4"
    )
    assert ("get", "uploads/uuid-1/0001.mp4") in fake.calls


def test_get_url_expires_boundary(
    override_get_session, override_get_current_user, storage_fixture
) -> None:
    resp = client.get("/api/v1/files/a/b.mp4/url?expires=86400")
    assert resp.status_code == 200
    assert resp.json()["code"] == 0


def test_get_url_expires_out_of_range(
    override_get_session, override_get_current_user, storage_fixture
) -> None:
    resp = client.get("/api/v1/files/a/b.mp4/url?expires=999999")
    assert resp.status_code == 400
    assert resp.json()["code"] == 40000


def test_get_url_bad_key(
    override_get_session, override_get_current_user, storage_fixture
) -> None:
    # 空白 key（%20）→ strip 后为空 → 400
    resp = client.get("/api/v1/files/%20/url")
    assert resp.status_code == 400
    assert resp.json()["code"] == 40000


# ---------- 未登录 ----------


def test_upload_requires_login(override_get_session) -> None:
    """不 override get_current_user：无 Authorization 头 → 401 信封。"""
    resp = client.post(UPLOAD_PATH, files={"file": ("a.txt", b"x", "text/plain")})
    assert resp.status_code == 401
    assert resp.json()["code"] == 40100


def test_presign_upload_requires_login(override_get_session) -> None:
    resp = client.post(
        PRESIGN_PATH, json={"size": 1, "content_type": "x", "prefix": "a"}
    )
    assert resp.status_code == 401
    assert resp.json()["code"] == 40100


def test_get_url_requires_login(override_get_session) -> None:
    resp = client.get("/api/v1/files/a/b.mp4/url")
    assert resp.status_code == 401
    assert resp.json()["code"] == 40100
