"""Task 1：应用启动与健康检查测试（backend/app/main.py）。"""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_returns_envelope() -> None:
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json() == {"code": 0, "message": "ok", "data": {"status": "ok"}}


def test_health_sets_correlation_id_header() -> None:
    resp = client.get("/api/v1/health")
    assert resp.headers.get("x-correlation-id")
