"""Task 3：统一信封 / 错误信封 / 分页助手 / 全局异常处理器 / 审计写入。

异常处理器用**独立的迷你 FastAPI 应用**测试（不污染 `app.main` 的真实 app）：
在隔离 app 上调用 `register_exception_handlers(app)`，加两条哑路由
（一条抛 HTTPException、一条触发参数校验），断言信封形状与状态码。
"""

import json

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlmodel import Session, SQLModel

from app.core.audit import write_audit
from app.main import register_exception_handlers
from app.models import AuditLog
from app.schemas.common import err, ok, paginate


# ---------- 信封 / 分页（纯函数） ----------


def test_ok_envelope_shape() -> None:
    assert ok({"status": "ok"}) == {
        "code": 0,
        "message": "ok",
        "data": {"status": "ok"},
    }
    assert ok(None) == {"code": 0, "message": "ok", "data": None}


def test_err_returns_http_status_and_envelope() -> None:
    resp = err(40101, "令牌失效", status=401)
    assert resp.status_code == 401
    assert resp.body.decode("utf-8") == '{"code":40101,"message":"令牌失效"}'
    # detail 缺省时不写入 body
    assert "detail" not in resp.body.decode("utf-8")


def test_err_with_detail_includes_detail() -> None:
    resp = err(
        42200, "参数校验失败", detail=[{"loc": ["item_id"], "msg": "invalid"}], status=422
    )
    assert resp.status_code == 422
    body = json.loads(resp.body)
    assert body["code"] == 42200
    assert body["detail"] == [{"loc": ["item_id"], "msg": "invalid"}]


def test_paginate_shape() -> None:
    out = paginate(items=[{"id": 1}], total=42, page=2, page_size=10)
    assert out == {
        "items": [{"id": 1}],
        "total": 42,
        "page": 2,
        "page_size": 10,
    }
    assert out["total"] == 42


# ---------- 全局异常处理器（隔离 app） ----------


@pytest.fixture()
def error_app_client() -> TestClient:
    """独立迷你 app：register_exception_handlers + 两条哑路由。"""
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/boom")
    def boom() -> None:
        raise HTTPException(status_code=404, detail="nope")

    @app.get("/items/{item_id}")
    def get_item(item_id: int) -> dict:
        return {"item_id": item_id}

    @app.get("/crash")
    def crash() -> None:
        raise RuntimeError("kaboom")

    # ServerErrorMiddleware 发完 500 响应后仍会 re-raise 原异常，
    # 故兜底 Exception 处理器测试需关闭 raise_server_exceptions。
    return TestClient(app, raise_server_exceptions=False)


def test_http_exception_maps_to_404_envelope(error_app_client: TestClient) -> None:
    resp = error_app_client.get("/boom")
    assert resp.status_code == 404
    assert resp.json() == {
        "code": 40400,
        "message": "资源不存在",
        "detail": "nope",
    }


def test_validation_error_returns_422_envelope(error_app_client: TestClient) -> None:
    resp = error_app_client.get("/items/not-a-number")
    assert resp.status_code == 422
    body = resp.json()
    assert body["code"] == 42200
    assert body["message"] == "参数校验失败"
    assert isinstance(body["detail"], list)
    assert body["detail"][0]["type"] == "int_parsing"


def test_unhandled_exception_returns_500_envelope(error_app_client: TestClient) -> None:
    resp = error_app_client.get("/crash")
    assert resp.status_code == 500
    assert resp.json() == {"code": 50000, "message": "服务内部错误"}


# ---------- 真实 app 的健康检查仍返回信封 ----------


def test_real_health_returns_envelope() -> None:
    from app.main import app

    client = TestClient(app)
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json() == {"code": 0, "message": "ok", "data": {"status": "ok"}}


# ---------- 审计写入（SQLite 内存） ----------


def test_write_audit_inserts_row() -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        entry = write_audit(
            session,
            user_id=1,
            action="create",
            resource_type="weld",
            resource_id="WLD-20260823-001",
            detail={"note": "登记新焊缝"},
        )
        # write_audit 写入的是 UTC 且 timezone-aware 的时间
        assert entry.created_at is not None
        assert entry.created_at.tzinfo is not None
        session.commit()
        assert entry.id is not None

    with Session(engine) as session:
        row = session.get(AuditLog, entry.id)
        assert row is not None
        assert row.user_id == 1
        assert row.action == "create"
        assert row.resource_type == "weld"
        assert row.resource_id == "WLD-20260823-001"
        assert row.detail == {"note": "登记新焊缝"}
        assert row.created_at is not None



def test_write_audit_truncates_long_resource_id_and_masks_sensitive_detail() -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    long_resource_id = "uploads/" + "a" * 400 + "/malformed.csv"

    with Session(engine) as session:
        entry = write_audit(
            session,
            user_id=1,
            action="upload",
            resource_type="file",
            resource_id=long_resource_id,
            detail={"token": "secret-token", "nested": {"password": "p@ss", "safe": "ok"}},
        )
        session.commit()
        assert entry.id is not None

    with Session(engine) as session:
        row = session.get(AuditLog, entry.id)
        assert row is not None
        assert row.resource_id is not None
        assert len(row.resource_id) <= 255
        assert row.resource_id.startswith("uploads/")
        assert row.resource_id != long_resource_id
        assert row.detail == {"token": "***", "nested": {"password": "***", "safe": "ok"}}
