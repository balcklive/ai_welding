"""Task 1：应用启动与健康检查测试（backend/app/main.py）。"""

from fastapi.testclient import TestClient

from app import main
from app.main import app

client = TestClient(app)


def test_health_returns_envelope() -> None:
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json() == {"code": 0, "message": "ok", "data": {"status": "ok"}}


def test_health_sets_correlation_id_header() -> None:
    resp = client.get("/api/v1/health")
    assert resp.headers.get("x-correlation-id")


def test_liveness_does_not_require_external_dependencies() -> None:
    resp = client.get("/api/v1/health/live")
    assert resp.status_code == 200
    assert resp.json()["data"] == {"status": "live"}


def test_readiness_returns_checks_when_dependencies_are_ready(monkeypatch) -> None:
    monkeypatch.setattr(
        main,
        "readiness_report",
        lambda: (
            True,
            {
                "database": {"status": "ok", "revision": "0011"},
                "object_storage": {"status": "ok", "bucket": "aiwelding"},
            },
        ),
    )
    resp = client.get("/api/v1/health/ready")
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "ready"


def test_readiness_returns_503_without_leaking_exception_details(monkeypatch) -> None:
    monkeypatch.setattr(
        main,
        "readiness_report",
        lambda: (
            False,
            {
                "database": {"status": "failed"},
                "object_storage": {"status": "ok", "bucket": "aiwelding"},
            },
        ),
    )
    resp = client.get("/api/v1/health/ready")
    payload = resp.json()
    assert resp.status_code == 503
    assert payload["code"] == 50300
    assert payload["detail"]["checks"]["database"] == {"status": "failed"}
