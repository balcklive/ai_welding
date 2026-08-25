"""Task 17：通用报告导出（POST /reports/export）。

内存 SQLite + StaticPool + 真实 app TestClient（同 test_datasets.py）。
`seed_all` 造演示数据后 override `get_session` / `get_current_user`；
`app.storage.get_storage` → FakeStorage（记录 upload_stream 字节 + presign_get，
不连真实 MinIO）。Jinja2 + xhtml2pdf 真实渲染（本机有文泉驿中文字体）。

覆盖：
- `type=validation, format=json`：返回 urls，假存储收到的字节可解析为 JSON，
  内含核验报告 score（93.3）+ 15 条规则；对象键 `reports/validation/{id}.json`；
- `type=validation, format=pdf`：返回 urls，字节以 `%PDF` 开头（xhtml2pdf 输出）；
- `type=data-list, format=json`：`ref_ids=[]` → 全量单份（ref_id=`all`）+ 4 条记录；
  `ref_ids=[weld_id]` → 过滤单条 + 未知标识 404；
- 通用模板类型（analysis）走真实版本 id → 200 + urls；
- 未知 type / 未知 format → 400（40000）；引用实体不存在 → 404（40401）；
- 未登录 → 401（40100）。
"""

import json
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, select

from app.api.deps import get_current_user
from app.core.db import get_session
from app.core.seed import seed_all
from app.main import app
from app.models import DataVersion, FeatureExtraction, TestTask, User, ValidationReport

client = TestClient(app)


class FakeStorage:
    """记录 upload_stream / presign_get 的假存储（断言导出写入，不连 MinIO）。"""

    def __init__(self) -> None:
        self.uploads: list[tuple] = []
        self.gets: list[str] = []

    def upload_stream(self, object_key, fileobj, size, content_type):
        data = fileobj.read()
        self.uploads.append((object_key, size, content_type, data))
        return object_key

    def presign_get(self, object_key, expires=3600):
        self.gets.append(object_key)
        return f"https://minio.local/aiwelding/{object_key}?expires={expires}"


@pytest.fixture()
def db_engine():
    """内存 SQLite + StaticPool：seed 演示数据，每用例全新引擎（环形 FK 不便 drop_all）。"""
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
    """每请求开一个独立 Session（与真实 get_session 语义一致），退出即 close。"""

    def _override():
        with Session(db_engine) as session:
            yield session

    app.dependency_overrides[get_session] = _override
    yield
    app.dependency_overrides.pop(get_session, None)


class _CurrentUser:
    def __init__(self) -> None:
        self.value = User(
            id=1,
            username="lin_eng",
            password_hash="not-a-real-hash",
            display_name="林工",
            role="admin",
        )

    def __call__(self) -> User:
        return self.value


@pytest.fixture()
def override_get_current_user():
    """假登录：get_current_user 直接返回一个 User，免 seed / 免签 token。"""
    state = _CurrentUser()
    app.dependency_overrides[get_current_user] = state
    yield state
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture()
def fake_storage(db_engine, monkeypatch):
    storage = FakeStorage()
    monkeypatch.setattr("app.storage.get_storage", lambda: storage)
    return storage


def _validation_report_id(db_engine) -> int:
    with Session(db_engine) as session:
        return session.exec(
            select(ValidationReport).order_by(ValidationReport.id)
        ).first().id


def _version_id(db_engine) -> int:
    with Session(db_engine) as session:
        return session.exec(select(DataVersion).order_by(DataVersion.id)).first().id


def _uploaded(fake: FakeStorage, suffix: str):
    """取对象键以 `suffix` 结尾的那次上传字节。"""
    for key, _size, _ct, data in reversed(fake.uploads):
        if key.endswith(suffix):
            return key, data
    raise AssertionError(f"未找到对象键以 {suffix} 结尾的上传，实际: {[u[0] for u in fake.uploads]}")


def test_validation_json_contains_score(
    db_engine, override_get_session, override_get_current_user, fake_storage
):
    report_id = _validation_report_id(db_engine)
    resp = client.post(
        "/api/v1/reports/export",
        json={"type": "validation", "ref_ids": [report_id], "format": "json"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    urls = body["data"]["urls"]
    assert len(urls) == 1
    assert urls[0]["ref_id"] == str(report_id)
    assert urls[0]["url"].startswith("https://minio.local/")

    key, data = _uploaded(fake_storage, f"reports/validation/{report_id}.json")
    assert key == f"reports/validation/{report_id}.json"
    parsed = json.loads(data)
    assert parsed["score"] == 93.3
    assert parsed["passed"] == 14
    assert parsed["warning"] == 1
    assert parsed["failed"] == 0
    assert len(parsed["rules"]) == 15


def test_validation_pdf_starts_with_pdf_header(
    db_engine, override_get_session, override_get_current_user, fake_storage
):
    report_id = _validation_report_id(db_engine)
    resp = client.post(
        "/api/v1/reports/export",
        json={"type": "validation", "ref_ids": [report_id], "format": "pdf"},
    )
    assert resp.status_code == 200
    urls = resp.json()["data"]["urls"]
    assert len(urls) == 1
    key, data = _uploaded(fake_storage, f"reports/validation/{report_id}.pdf")
    assert key == f"reports/validation/{report_id}.pdf"
    assert data[:5] == b"%PDF-"


def test_data_list_json_all_records(
    db_engine, override_get_session, override_get_current_user, fake_storage
):
    resp = client.post(
        "/api/v1/reports/export",
        json={"type": "data-list", "ref_ids": [], "format": "json"},
    )
    assert resp.status_code == 200
    urls = resp.json()["data"]["urls"]
    assert len(urls) == 1
    assert urls[0]["ref_id"] == "all"

    key, data = _uploaded(fake_storage, "reports/data-list/all.json")
    assert key == "reports/data-list/all.json"
    parsed = json.loads(data)
    assert parsed["total"] == 4
    assert {item["weld_id"] for item in parsed["items"]} == {
        "WLD-20260815-0248",
        "WLD-20260815-0247",
        "WLD-20260814-0246",
        "WLD-20260814-0245",
    }


def test_data_list_filtered_by_weld_id(
    db_engine, override_get_session, override_get_current_user, fake_storage
):
    resp = client.post(
        "/api/v1/reports/export",
        json={
            "type": "data-list",
            "ref_ids": ["WLD-20260815-0248"],
            "format": "json",
        },
    )
    assert resp.status_code == 200
    urls = resp.json()["data"]["urls"]
    assert len(urls) == 1
    assert urls[0]["ref_id"] == "WLD-20260815-0248"  # ref_id 保留调用方原始标识
    key, data = _uploaded(fake_storage, "reports/data-list/wld-20260815-0248.json")
    parsed = json.loads(data)
    assert parsed["total"] == 1
    assert parsed["items"][0]["weld_id"] == "WLD-20260815-0248"
    assert key.startswith("reports/data-list/")


def test_analysis_generic_template(
    db_engine, override_get_session, override_get_current_user, fake_storage
):
    version_id = _version_id(db_engine)
    resp = client.post(
        "/api/v1/reports/export",
        json={"type": "analysis", "ref_ids": [version_id], "format": "json"},
    )
    assert resp.status_code == 200
    urls = resp.json()["data"]["urls"]
    assert len(urls) == 1
    assert urls[0]["ref_id"] == str(version_id)
    key, data = _uploaded(fake_storage, f"reports/analysis/{version_id}.json")
    parsed = json.loads(data)
    assert parsed["sections"]  # 至少一个分节（分析结论）
    assert parsed["summary"][0]["label"] == "焊缝"


def _seed_feature_extraction(db_engine) -> int:
    with Session(db_engine) as session:
        version_id = _version_id(db_engine)
        row = FeatureExtraction(
            version_id=version_id,
            ts_features={"cur": {"mean": 1.0}},
            vision_features={"area": 2.0},
            audio_features={"spectral_centroid": 3.0},
            unified_vector={"total_dims": 3, "values": [1.0, 2.0, 3.0]},
            normalization="Z-Score",
            format="JSON",
            created_at=datetime.now(timezone.utc),
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return row.id


def _seed_test_task(db_engine) -> int:
    with Session(db_engine) as session:
        row = TestTask(
            job_id=9991,
            model_version_id=1,
            dataset_version_id=1,
            tasks=["异常分类"],
            metrics={"accuracy": 0.91},
            confusion_matrix=[[9, 1], [2, 8]],
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return row.id


def test_analysis_pdf_exports_current_entity(
    db_engine, override_get_session, override_get_current_user, fake_storage
):
    version_id = _version_id(db_engine)
    resp = client.post(
        "/api/v1/reports/export",
        json={"type": "analysis", "ref_ids": [version_id], "format": "pdf"},
    )
    assert resp.status_code == 200, resp.text
    key, data = _uploaded(fake_storage, f"reports/analysis/{version_id}.pdf")
    assert key == f"reports/analysis/{version_id}.pdf"
    assert data[:5] == b"%PDF-"

    json_resp = client.post(
        "/api/v1/reports/export",
        json={"type": "analysis", "ref_ids": [version_id], "format": "json"},
    )
    parsed = json.loads(_uploaded(fake_storage, f"reports/analysis/{version_id}.json")[1])
    assert json_resp.status_code == 200
    assert parsed["ref_id"] == str(version_id)
    assert any(item["label"] == "版本" and item["value"] == "v1.0" for item in parsed["summary"])


def test_features_pdf_exports_current_entity(
    db_engine, override_get_session, override_get_current_user, fake_storage
):
    extraction_id = _seed_feature_extraction(db_engine)
    resp = client.post(
        "/api/v1/reports/export",
        json={"type": "features", "ref_ids": [extraction_id], "format": "pdf"},
    )
    assert resp.status_code == 200, resp.text
    key, data = _uploaded(fake_storage, f"reports/features/{extraction_id}.pdf")
    assert key == f"reports/features/{extraction_id}.pdf"
    assert data[:5] == b"%PDF-"

    client.post(
        "/api/v1/reports/export",
        json={"type": "features", "ref_ids": [extraction_id], "format": "json"},
    )
    parsed = json.loads(_uploaded(fake_storage, f"reports/features/{extraction_id}.json")[1])
    assert parsed["ref_id"] == str(extraction_id)
    assert any(item["label"] == "版本" and item["value"] == "v1.0" for item in parsed["summary"])


def test_test_pdf_exports_current_entity(
    db_engine, override_get_session, override_get_current_user, fake_storage
):
    task_id = _seed_test_task(db_engine)
    resp = client.post(
        "/api/v1/reports/export",
        json={"type": "test", "ref_ids": [task_id], "format": "pdf"},
    )
    assert resp.status_code == 200, resp.text
    key, data = _uploaded(fake_storage, f"reports/test/{task_id}.pdf")
    assert key == f"reports/test/{task_id}.pdf"
    assert data[:5] == b"%PDF-"

    client.post(
        "/api/v1/reports/export",
        json={"type": "test", "ref_ids": [task_id], "format": "json"},
    )
    parsed = json.loads(_uploaded(fake_storage, f"reports/test/{task_id}.json")[1])
    assert parsed["ref_id"] == str(task_id)
    assert any(item["label"] == "模型版本" and item["value"] == 1 for item in parsed["summary"])
    assert any(item["label"] == "数据集版本" and item["value"] == 1 for item in parsed["summary"])


def test_unknown_type_returns_400(
    db_engine, override_get_session, override_get_current_user, fake_storage
):
    resp = client.post(
        "/api/v1/reports/export",
        json={"type": "nope", "ref_ids": [1], "format": "json"},
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == 40000
    assert fake_storage.uploads == []


def test_unknown_format_returns_400(
    db_engine, override_get_session, override_get_current_user, fake_storage
):
    resp = client.post(
        "/api/v1/reports/export",
        json={"type": "validation", "ref_ids": [1], "format": "csv"},
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == 40000
    assert fake_storage.uploads == []


def test_missing_entity_returns_404(
    db_engine, override_get_session, override_get_current_user, fake_storage
):
    resp = client.post(
        "/api/v1/reports/export",
        json={"type": "validation", "ref_ids": [999999], "format": "json"},
    )
    assert resp.status_code == 404
    assert resp.json()["code"] == 40401
    assert fake_storage.uploads == []

    resp = client.post(
        "/api/v1/reports/export",
        json={"type": "data-list", "ref_ids": ["NO-SUCH-WELD"], "format": "json"},
    )
    assert resp.status_code == 404
    assert resp.json()["code"] == 40401


def test_unauthorized_returns_401(db_engine):
    resp = client.post(
        "/api/v1/reports/export",
        json={"type": "validation", "ref_ids": [1], "format": "json"},
    )
    assert resp.status_code == 401
    assert resp.json()["code"] == 40100


@pytest.mark.parametrize("fmt", ["json", "pdf"])
def test_non_admin_data_list_export_only_includes_owned_records_when_ref_ids_empty(
    db_engine, override_get_session, override_get_current_user, fake_storage, fmt
):
    override_get_current_user.value = User(
        id=2,
        username="worker",
        password_hash="not-a-real-hash",
        display_name="二号用户",
        role="user",
    )
    created = client.post(
        "/api/v1/registrations",
        json={
            "source": "lab",
            "weld_name": "worker-owned-record",
            "machine": "demo",
            "weld_method": "MAG焊",
            "material": "Q235B",
        },
    )
    assert created.status_code == 200, created.text
    weld_id = created.json()["data"]["weld_id"]

    resp = client.post(
        "/api/v1/reports/export",
        json={"type": "data-list", "ref_ids": [], "format": fmt},
    )
    assert resp.status_code == 200, resp.text

    suffix = "reports/data-list/all.json" if fmt == "json" else "reports/data-list/all.pdf"
    key, data = _uploaded(fake_storage, suffix)
    assert key == suffix
    if fmt == "json":
        parsed = json.loads(data)
        assert parsed["total"] == 1
        assert [item["weld_id"] for item in parsed["items"]] == [weld_id]
    else:
        assert data[:5] == b"%PDF-"


@pytest.mark.parametrize("fmt", ["json", "pdf"])
def test_non_admin_data_list_export_cannot_read_other_users_requested_weld(
    db_engine, override_get_session, override_get_current_user, fake_storage, fmt
):
    override_get_current_user.value = User(
        id=2,
        username="worker",
        password_hash="not-a-real-hash",
        display_name="二号用户",
        role="user",
    )

    resp = client.post(
        "/api/v1/reports/export",
        json={"type": "data-list", "ref_ids": ["WLD-20260815-0248"], "format": fmt},
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == 40300
    assert fake_storage.uploads == []


def test_jinja_autoescape_escapes_user_fields(
    db_engine, override_get_session, override_get_current_user, fake_storage
):
    """回归：.j2 模板必须开 autoescape（select_autoescape 按文件名结尾匹配不到 .j2，
    曾导致 {{ weld_name }} 等用户字段原样渲染、可向 PDF 注入任意 HTML）。"""
    from app.services.reports import _env

    assert _env.autoescape is True
    html = _env.get_template("data_list.html.j2").render(
        title="数据列表",
        ref_id="all",
        total=1,
        generated_at="now",
        items=[
            {
                "weld_id": "WLD-1",
                "registration_no": "REG-1",
                "weld_name": '<img src=x onerror=alert(1)>',
                "source": "src",
                "machine": "m",
                "weld_method": "wm",
                "material": "mat",
                "quality": "ok",
                "operator": "op",
            }
        ],
    )
    assert "<img" not in html
    assert "&lt;img src=x onerror=alert(1)&gt;" in html
