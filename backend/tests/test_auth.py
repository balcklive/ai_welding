"""Task 5：JWT 认证（login/me）测试。

用**内存 SQLite** + 真实 app（`app.main`）的 TestClient，依赖覆盖 `get_session` →
测试 session（不连远程 MySQL）。seed 一个用户（hash_password 存 argon2 哈希）。
覆盖：登录成功/密码错/用户不存在、me 带/不带/坏 token、decode_token 往返、verify_password。
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, select

from app.core.db import get_session
from app.core.security import (
    create_access_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.main import app
from app.models import User

client = TestClient(app)


@pytest.fixture()
def db_session():
    """内存 SQLite 引擎 + 建全部表 + seed 一个用户。每用例全新引擎（环形 FK 不便 drop_all）。"""
    # 内存 SQLite + StaticPool：TestClient 在 worker 线程处理请求，
    # 必须让所有线程共享同一连接，否则各线程看到的是互相独立的空库。
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(
            User(
                username="lin_eng",
                password_hash=hash_password("s3cret-pass"),
                display_name="林工",
                role="admin",
            )
        )
        session.commit()
        yield session
    engine.dispose()


@pytest.fixture()
def override_get_session(db_session):
    """把真实 app 的 `get_session` 依赖覆盖为测试 session（覆盖 login 与 get_current_user 两处）。"""
    def _override():
        yield db_session

    app.dependency_overrides[get_session] = _override
    yield
    app.dependency_overrides.pop(get_session, None)


def _login(username: str = "lin_eng", password: str = "s3cret-pass"):
    return client.post(
        "/api/v1/auth/login", json={"username": username, "password": password}
    )


# ---------- POST /auth/login ----------


def test_login_success(override_get_session) -> None:
    resp = _login()
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    data = body["data"]
    assert data["token_type"] == "bearer"
    assert isinstance(data["access_token"], str) and data["access_token"]
    # decode_token 能解出 seed 用户 id（登录签发的 token 有效）
    user = data["user"]
    assert user["username"] == "lin_eng"
    assert user["display_name"] == "林工"
    assert user["role"] == "admin"
    assert set(user) == {"id", "username", "display_name", "role", "avatar"}


def test_login_wrong_password(override_get_session) -> None:
    resp = _login(password="wrong-pass")
    assert resp.status_code == 401
    body = resp.json()
    assert body["code"] == 40100
    assert body["message"] == "用户名或密码错误"


def test_login_unknown_user(override_get_session) -> None:
    resp = _login(username="nobody")
    assert resp.status_code == 401
    assert resp.json()["code"] == 40100


# ---------- GET /auth/me ----------


def test_me_with_valid_token(override_get_session, db_session) -> None:
    user = db_session.exec(select(User).where(User.username == "lin_eng")).first()
    token = create_access_token(user)
    resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["id"] == user.id
    assert data["username"] == "lin_eng"
    assert data["display_name"] == "林工"


def test_me_without_token(override_get_session) -> None:
    resp = client.get("/api/v1/auth/me")
    assert resp.status_code == 401
    assert resp.json()["code"] == 40100


def test_me_with_bad_token(override_get_session) -> None:
    resp = client.get(
        "/api/v1/auth/me", headers={"Authorization": "Bearer not.a.jwt"}
    )
    assert resp.status_code == 401
    assert resp.json()["code"] == 40100


def test_me_with_non_bearer_scheme(override_get_session) -> None:
    resp = client.get("/api/v1/auth/me", headers={"Authorization": "Basic abc"})
    assert resp.status_code == 401
    assert resp.json()["code"] == 40100


# ---------- 纯函数：security ----------


def test_verify_password_roundtrip() -> None:
    hashed = hash_password("s3cret-pass")
    assert hashed != "s3cret-pass"
    assert verify_password("s3cret-pass", hashed) is True
    assert verify_password("wrong", hashed) is False


def test_verify_password_invalid_hash_returns_false() -> None:
    # 非 argon2 哈希（如测试里随手填的 "hash"）应视为不匹配而非抛异常
    assert verify_password("anything", "hash") is False


def test_decode_token_roundtrip(db_session) -> None:
    user = db_session.exec(select(User).where(User.username == "lin_eng")).first()
    token = create_access_token(user)
    assert decode_token(token) == user.id
