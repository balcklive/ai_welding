"""Task 10：Welds 列表/登记/版本/核验（核心 CRUD）测试。

内存 SQLite + StaticPool + 真实 app TestClient（同 test_dashboard / test_auth）。
先 `seed_all` 造演示数据（4 焊缝：0248/0247/0246/0245；0248 有 v1.0~v1.3 版本链，
0248 已核验 93.3/14/1/0；0245 停在 v1.0 且 quality=异常），再 override
`get_session` → 测试 session、`get_current_user` → 假 User（免签 token）。

覆盖：登记事务（WLD-/REG- 编号生成 + v1.0 + latest 联动 + 同日序号递增）；
列表分页与筛选（q/source/brand/status/tab）；版本链 + 新建 v1.4 并 bump latest；
raw-files 挂载（追加 keys + 累加 storage_bytes + 推导 modalities）；
核验（0248 v1.2 全部通过→quality 通过；新建无文件版本→失败→quality 异常）；
全部端点未登录 401。
"""

import threading
from datetime import date
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, select

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.db import get_session
from app.core.seed import seed_all
from app.main import app
from app.models import DataRecord, DataVersion, Dataset, User

client = TestClient(app)

WELD_0248 = "WLD-20260815-0248"
WELD_0247 = "WLD-20260815-0247"
WELD_0246 = "WLD-20260814-0246"
WELD_0245 = "WLD-20260814-0245"


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


class FakeStorage:
    def __init__(self) -> None:
        self.sizes: dict[str, int] = {}

    def stat_object(self, object_key: str) -> int:
        if object_key not in self.sizes:
            raise FileNotFoundError(object_key)
        return self.sizes[object_key]


@pytest.fixture()
def fake_storage(monkeypatch):
    storage = FakeStorage()
    monkeypatch.setattr("app.api.v1.welds.get_storage", lambda: storage)
    return storage


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


def _register(**overrides):
    body = {
        # 登记必须归属数据集（RegistrationCreate.dataset_id 必填）；seed 第一个数据集 id=1。
        "dataset_id": 1,
        "source": "产线相机 · 04号",
        "collected_at": "2026-08-16T08:00:00Z",
        "weld_name": "测试焊缝",
        "product": "测试产品",
        "machine": "Fronius CMT",
        "weld_method": "MAG焊",
        "material": "Q235B",
        "thickness": "6 mm",
        "current_voltage": "180 A / 22 V",
        "sample_rate": "10 kHz",
    }
    body.update(overrides)
    return client.post("/api/v1/registrations", json=body)


def _versions_of(weld_id):
    return client.get(f"/api/v1/welds/{weld_id}/versions").json()["data"]


# ---------- POST /registrations ----------


def test_create_registration_makes_record_and_v1_0(
    override_get_session, override_get_current_user, db_session
) -> None:
    resp = _register()
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0

    data = body["data"]
    assert data["weld_id"].startswith("WLD-20260816-")
    assert data["registration_no"].startswith("REG-20260816-")
    assert data["quality"] == "待复核"
    assert data["operator"] == "林工"
    assert data["modalities"] == []
    assert data["storage_bytes"] == 0
    assert data["source"] == "产线相机 · 04号"

    latest = data["latest_version"]
    assert latest is not None
    assert latest["version_no"] == "v1.0"
    assert latest["action"] == "原始数据"
    assert latest["operator"] == "林工"
    assert latest["object_keys"] == []
    assert latest["id"] == data["latest_version_id"]

    # DB 侧联动：record.latest_version_id 指向 v1.0 版本，且同焊缝内版本唯一。
    from app.models.data import DataRecord, DataVersion

    record = db_session.get(DataRecord, data["id"])
    assert record is not None
    assert record.weld_id == data["weld_id"]
    version = db_session.get(DataVersion, record.latest_version_id)
    assert version is not None
    assert version.record_id == record.id
    assert version.version_no == "v1.0"
    assert version.object_keys == []


def test_sequential_registration_numbers_same_day(
    override_get_session, override_get_current_user
) -> None:
    """同一天登记两次，WLD-/REG- 序号顺序递增（基于当日前缀计数）。"""
    first = _register().json()["data"]
    second = _register().json()["data"]

    assert first["weld_id"] == "WLD-20260816-0001"
    assert first["registration_no"] == "REG-20260816-00001"
    assert second["weld_id"] == "WLD-20260816-0002"
    assert second["registration_no"] == "REG-20260816-00002"



def test_create_registration_retries_generated_id_conflict(
    override_get_session, override_get_current_user, monkeypatch
) -> None:
    import app.api.v1.welds as welds_api
    from sqlalchemy.exc import IntegrityError

    original_create_registration = welds_api.svc.create_registration
    calls = {"count": 0}

    def _flaky_create_registration(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise IntegrityError("INSERT", {}, Exception("duplicate generated id"))
        return original_create_registration(*args, **kwargs)

    monkeypatch.setattr(welds_api.svc, "create_registration", _flaky_create_registration)

    resp = client.post(
        "/api/v1/registrations",
        json={
            # 登记必须归属数据集；seed 第一个数据集 id=1。
            "dataset_id": 1,
            "source": "并发测试产线",
            "collected_at": "2026-08-16T08:00:00Z",
            "weld_name": "并发登记",
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["code"] == 0
    assert calls["count"] == 2


def test_create_registration_requires_source(
    override_get_session, override_get_current_user
) -> None:
    resp = client.post("/api/v1/registrations", json={"dataset_id": 1, "source": "  "})
    assert resp.status_code == 400
    assert resp.json()["code"] == 40000



def test_create_registration_rejects_concurrent_duplicate_payload(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import time
    import app.api.v1.welds as welds_api

    db_path = tmp_path / "weld-registration-concurrency.db"
    engine = create_engine(
        f"sqlite:///{db_path}", connect_args={"check_same_thread": False}
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        seed_all(session)

    def _override_session():
        with Session(engine) as session:
            yield session

    dummy = User(
        id=1,
        username="lin_eng",
        password_hash="not-a-real-hash",
        display_name="林工",
        role="admin",
    )

    def _override_user() -> User:
        return dummy

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_current_user] = _override_user

    original_create_registration = welds_api.svc.create_registration

    def _slow_create_registration(*args, **kwargs):
        time.sleep(0.2)
        return original_create_registration(*args, **kwargs)

    monkeypatch.setattr(welds_api.svc, "create_registration", _slow_create_registration)

    payload = {
        # 登记必须归属数据集；seed 第一个数据集 id=1。
        "dataset_id": 1,
        "source": "task5p2-dup",
        "collected_at": "2026-08-16T08:00:00Z",
        "weld_name": "重复登记",
        "product": "测试产品",
        "machine": "Fronius CMT",
        "weld_method": "MAG焊",
        "material": "Q235B",
        "thickness": "6 mm",
        "current_voltage": "180 A / 22 V",
        "sample_rate": "10 kHz",
    }
    results: list[tuple[int, dict]] = []
    errors: list[BaseException] = []

    def _worker(delay: float = 0.0) -> None:
        try:
            if delay:
                time.sleep(delay)
            with TestClient(app) as local_client:
                resp = local_client.post("/api/v1/registrations", json=payload)
            results.append((resp.status_code, resp.json()))
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [
        threading.Thread(target=_worker, args=(0.0,)),
        threading.Thread(target=_worker, args=(0.05,)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    app.dependency_overrides.pop(get_session, None)
    app.dependency_overrides.pop(get_current_user, None)

    assert not errors
    assert sorted(status for status, _body in results) == [200, 409]
    with Session(engine) as session:
        records = session.exec(
            select(DataRecord).where(
                DataRecord.source == "task5p2-dup",
                DataRecord.weld_name == "重复登记",
            )
        ).all()
        assert len(records) == 1


def test_mysql_registration_lock_released_after_rollback_allows_followup_registration() -> None:
    import app.api.v1.welds as welds_api

    admin_db = settings.mysql_database
    test_db = f"{admin_db}_lock_{uuid4().hex[:8]}"
    admin_engine = create_engine(
        settings.mysql_url.rsplit(f"/{admin_db}?", 1)[0] + "/mysql?charset=utf8mb4"
    )
    with admin_engine.connect() as conn:
        conn.execute(text(f"CREATE DATABASE `{test_db}` CHARACTER SET utf8mb4"))
        conn.commit()

    test_engine = create_engine(
        settings.mysql_url.replace(f"/{admin_db}?", f"/{test_db}?"),
        pool_size=3,
        max_overflow=0,
        pool_use_lifo=True,
    )
    SQLModel.metadata.create_all(test_engine)
    with Session(test_engine) as session:
        session.add(
            User(
                id=1,
                username="lin_eng",
                password_hash="not-a-real-hash",
                display_name="林工",
                role="admin",
            )
        )
        # 登记必须归属数据集：独立库里也补一条 Dataset(id=1)，否则新登记的
        # `session.get(Dataset, dataset_id)` 存在性校验（40401）过不了。
        session.add(
            Dataset(
                id=1,
                dataset_no="DS-TEST-LOCK-001",
                name="锁回归数据集",
                task="目标检测",
                status="标注中",
            )
        )
        session.commit()

    def _override_session():
        with Session(test_engine) as session:
            yield session

    dummy = User(
        id=1,
        username="lin_eng",
        password_hash="not-a-real-hash",
        display_name="林工",
        role="admin",
    )

    def _override_user() -> User:
        return dummy

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_current_user] = _override_user

    test_day = date(2099, 1, (uuid4().int % 28) + 1)
    day_lock = None
    holder_session = None
    leaked_session = None
    try:
        holder_session = Session(test_engine)
        conn_id = holder_session.connection().execute(text("SELECT CONNECTION_ID()")).scalar()
        day_lock = welds_api.svc._acquire_registration_lock(holder_session, test_day)
        holder_session.rollback()

        leaked_session = Session(test_engine)
        leaked_conn_id = leaked_session.connection().execute(
            text("SELECT CONNECTION_ID()")
        ).scalar()
        assert leaked_conn_id == conn_id

        welds_api.svc._release_registration_lock(holder_session, day_lock)
        leaked_session.close()
        leaked_session = None

        resp = client.post(
            "/api/v1/registrations",
            json={
                # 登记必须归属数据集；seed 第一个数据集 id=1。
                "dataset_id": 1,
                "source": "task5-lock-followup",
                "collected_at": f"{test_day.isoformat()}T09:00:00Z",
                "weld_name": "锁释放后普通登记",
            },
        )

        assert resp.status_code == 200, resp.text
        assert resp.json()["code"] == 0
    finally:
        app.dependency_overrides.pop(get_session, None)
        app.dependency_overrides.pop(get_current_user, None)
        if leaked_session is not None:
            try:
                leaked_session.connection().execute(
                    text("SELECT RELEASE_LOCK(:name)"), {"name": day_lock}
                )
            except Exception:
                pass
            leaked_session.close()
        if holder_session is not None:
            holder_session.close()
        test_engine.dispose()
        with admin_engine.connect() as conn:
            conn.execute(text(f"DROP DATABASE IF EXISTS `{test_db}`"))
            conn.commit()
        admin_engine.dispose()


# ---------- GET /welds ----------


def test_list_welds_returns_all_seeded(
    override_get_session, override_get_current_user
) -> None:
    resp = client.get("/api/v1/welds")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total"] == 4
    assert data["page"] == 1
    assert data["page_size"] == 20
    assert len(data["items"]) == 4
    # 每条都带最新版本信息（去重只显示最新版本的体现）
    for item in data["items"]:
        assert item["latest_version"] is not None
        assert set(item) >= {
            "id", "weld_id", "weld_name", "registration_no", "source",
            "quality", "latest_version_id", "latest_version",
        }


def test_list_welds_pagination(override_get_session, override_get_current_user) -> None:
    resp = client.get("/api/v1/welds", params={"page": 1, "page_size": 2})
    data = resp.json()["data"]
    assert data["total"] == 4
    assert len(data["items"]) == 2

    resp = client.get("/api/v1/welds", params={"page": 2, "page_size": 2})
    data = resp.json()["data"]
    assert len(data["items"]) == 2
    ids = {item["weld_id"] for item in data["items"]}
    # created_at 倒序：8/15 两条在前页，8/14 两条（0246/0245）在后页
    assert ids == {WELD_0246, WELD_0245}


def test_list_welds_filters(override_get_session, override_get_current_user) -> None:
    def _ids(**params):
        data = client.get("/api/v1/welds", params=params).json()["data"]
        return data["total"], {item["weld_id"] for item in data["items"]}

    # q：焊缝 ID 关键词
    total, ids = _ids(q="0248")
    assert total == 1 and ids == {WELD_0248}
    # q：登记编号关键词
    total, ids = _ids(q="REG-20260814")
    assert total == 2 and ids == {WELD_0246, WELD_0245}
    # source：前缀
    total, ids = _ids(source="产线相机")
    assert total == 2 and ids == {WELD_0248, WELD_0246}
    # brand：焊机品牌前缀
    total, ids = _ids(brand="Fronius")
    assert total == 1 and ids == {WELD_0248}
    # status：精确 quality
    total, ids = _ids(status="异常")
    assert total == 1 and ids == {WELD_0245}
    # tab：待核验 → quality=待复核
    total, ids = _ids(tab="待核验")
    assert total == 1 and ids == {WELD_0247}
    # tab：已归档 → quality=通过（0248 / 0246）
    total, ids = _ids(tab="已归档")
    assert total == 2 and ids == {WELD_0248, WELD_0246}
    # 组合：待核验 + source
    total, ids = _ids(tab="待核验", source="实训线")
    assert total == 1 and ids == {WELD_0247}


def test_list_welds_dataset_filter(
    db_session, override_get_session, override_get_current_user
) -> None:
    """GET /welds?dataset_id：按归属数据集过滤；数据集不存在 → 404（40401）。"""
    created = client.post(
        "/api/v1/datasets",
        json={"name": "过滤测试数据集", "task": "目标检测"},
    ).json()["data"]
    new_id = created["id"]
    # 把 0246 移入新数据集，其余焊缝仍归 seed 默认数据集
    record = db_session.exec(
        select(DataRecord).where(DataRecord.weld_id == WELD_0246)
    ).one()
    record.dataset_id = new_id
    db_session.commit()

    def _ids(**params):
        data = client.get("/api/v1/welds", params=params).json()["data"]
        return data["total"], {item["weld_id"] for item in data["items"]}

    # 新数据集：只剩 0246
    total, ids = _ids(dataset_id=new_id)
    assert total == 1 and ids == {WELD_0246}
    # seed 默认数据集：其余 3 条
    default_dataset = db_session.exec(select(Dataset).order_by(Dataset.id)).first()
    total, ids = _ids(dataset_id=default_dataset.id)
    assert total == 3 and ids == {WELD_0248, WELD_0247, WELD_0245}
    # 可与其他筛选组合
    total, ids = _ids(dataset_id=default_dataset.id, status="通过")
    assert total == 1 and ids == {WELD_0248}
    # 数据集不存在 → 404
    resp = client.get("/api/v1/welds", params={"dataset_id": 999999})
    assert resp.status_code == 404
    assert resp.json()["code"] == 40401


# ---------- GET / PATCH /registrations/{id} ----------


def test_patch_registration_updates_editable_fields(
    override_get_session, override_get_current_user
) -> None:
    record = client.get(f"/api/v1/welds/{WELD_0248}").json()["data"]
    record_id = record["id"]

    resp = client.patch(
        f"/api/v1/registrations/{record_id}",
        json={"weld_name": "改名后的焊缝", "thickness": "8 mm"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["weld_name"] == "改名后的焊缝"
    assert data["thickness"] == "8 mm"
    # 未提交字段保持不变（partial update）
    assert data["machine"] == "Fronius CMT"
    assert data["registration_no"] == record["registration_no"]

    # 也支持用登记编号作标识；不存在 → 404
    resp = client.patch(
        "/api/v1/registrations/REG-20260815-00248",
        json={"weld_name": "再改名"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["weld_name"] == "再改名"

    resp = client.patch("/api/v1/registrations/999999", json={"weld_name": "x"})
    assert resp.status_code == 404
    assert resp.json()["code"] == 40401


def test_get_registration_by_identifier(
    override_get_session, override_get_current_user
) -> None:
    record = client.get(f"/api/v1/welds/{WELD_0248}").json()["data"]
    # DB id
    by_id = client.get(f"/api/v1/registrations/{record['id']}")
    # registration_no
    by_no = client.get("/api/v1/registrations/REG-20260815-00248")
    # weld_id
    by_weld = client.get(f"/api/v1/registrations/{WELD_0248}")
    assert by_id.json()["data"]["weld_id"] == WELD_0248
    assert by_no.json()["data"]["weld_id"] == WELD_0248
    assert by_weld.json()["data"]["weld_id"] == WELD_0248


# ---------- GET /welds/{weld_id} ----------


def test_get_weld_detail(override_get_session, override_get_current_user) -> None:
    resp = client.get(f"/api/v1/welds/{WELD_0248}")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["weld_id"] == WELD_0248
    assert data["latest_version"]["version_no"] == "v1.3"
    assert data["quality"] == "通过"

    resp = client.get("/api/v1/welds/WLD-NOPE-0000")
    assert resp.status_code == 404
    assert resp.json()["code"] == 40401


# ---------- 版本链 ----------


def test_version_chain_and_create_version(
    override_get_session, override_get_current_user
) -> None:
    versions = _versions_of(WELD_0248)
    assert [v["version_no"] for v in versions] == ["v1.0", "v1.1", "v1.2", "v1.3"]
    assert versions[0]["action"] == "原始数据"
    assert all({"version_no", "action", "operator", "object_keys", "created_at"} <= set(v) for v in versions)

    # 新建 v1.4（去噪处理）+ 更新 latest
    resp = client.post(
        f"/api/v1/welds/{WELD_0248}/versions",
        json={"action": "去噪处理", "note": "二次去噪", "object_keys": ["processed/WLD-20260815-0248/denoise/timeseries2.csv"]},
    )
    assert resp.status_code == 200
    new_version = resp.json()["data"]
    assert new_version["version_no"] == "v1.4"
    assert new_version["action"] == "去噪处理"
    assert new_version["operator"] == "林工"
    assert new_version["note"] == "二次去噪"

    versions = _versions_of(WELD_0248)
    assert len(versions) == 5
    assert versions[-1]["version_no"] == "v1.4"

    detail = client.get(f"/api/v1/welds/{WELD_0248}").json()["data"]
    assert detail["latest_version_id"] == new_version["id"]

    # 非法 action → 400
    resp = client.post(
        f"/api/v1/welds/{WELD_0248}/versions", json={"action": "乱搞"}
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == 40000


def test_single_version_endpoint(override_get_session, override_get_current_user) -> None:
    versions = _versions_of(WELD_0248)
    vid = versions[1]["id"]  # v1.1
    resp = client.get(f"/api/v1/welds/{WELD_0248}/versions/{vid}")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["id"] == vid
    assert data["version_no"] == "v1.1"

    # 版本属于别的焊缝 → 404
    resp = client.get(f"/api/v1/welds/{WELD_0247}/versions/{vid}")
    assert resp.status_code == 404
    assert resp.json()["code"] == 40402


def test_create_version_rejects_duplicate_payload_with_4xx(
    override_get_session, override_get_current_user
) -> None:
    payload = {
        "action": "人工修正",
        "note": "补充人工标注",
        "object_keys": ["processed/WLD-20260815-0248/manual/fix.jpg"],
    }
    first = client.post(f"/api/v1/welds/{WELD_0248}/versions", json=payload)
    assert first.status_code == 200, first.text

    before = _versions_of(WELD_0248)
    dup = client.post(f"/api/v1/welds/{WELD_0248}/versions", json=payload)
    assert dup.status_code == 409, dup.text
    assert dup.json()["code"] == 40900
    assert "重复" in dup.json()["message"]
    assert _versions_of(WELD_0248) == before



def test_create_version_concurrent_duplicate_requests_only_persist_one_row(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "weld-version-concurrency.db"
    engine = create_engine(
        f"sqlite:///{db_path}", connect_args={"check_same_thread": False}
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        seed_all(session)

    def _override_session():
        with Session(engine) as session:
            yield session

    dummy = User(
        id=1,
        username="lin_eng",
        password_hash="not-a-real-hash",
        display_name="林工",
        role="admin",
    )

    def _override_user() -> User:
        return dummy

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_current_user] = _override_user
    barrier = threading.Barrier(2)
    import app.api.v1.welds as welds_api

    original_create_version = welds_api.svc.create_version

    def _sync_create_version(*args, **kwargs):
        barrier.wait(timeout=2)
        return original_create_version(*args, **kwargs)

    monkeypatch.setattr(welds_api.svc, "create_version", _sync_create_version)
    payload = {
        "action": "人工修正",
        "note": "并发人工修正",
        "object_keys": ["processed/WLD-20260815-0248/manual/concurrent-fix.jpg"],
    }
    results: list[tuple[int, dict]] = []
    errors: list[BaseException] = []

    def _worker() -> None:
        try:
            with TestClient(app) as local_client:
                resp = local_client.post(f"/api/v1/welds/{WELD_0248}/versions", json=payload)
            results.append((resp.status_code, resp.json()))
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=_worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    app.dependency_overrides.pop(get_session, None)
    app.dependency_overrides.pop(get_current_user, None)

    assert not errors
    assert sorted(status for status, _body in results) == [200, 409]
    with Session(engine) as session:
        record = session.exec(select(DataRecord).where(DataRecord.weld_id == WELD_0248)).first()
        assert record is not None
        versions = session.exec(select(DataVersion).where(DataVersion.record_id == record.id)).all()
        assert len(versions) == 5
        matching = [v for v in versions if v.note == payload["note"]]
        assert len(matching) == 1


# ---------- POST /registrations/{id}/raw-files ----------


def test_attach_raw_files(
    override_get_session, override_get_current_user, fake_storage
) -> None:
    record = client.get(f"/api/v1/welds/{WELD_0248}").json()["data"]
    record_id = record["id"]
    before_bytes = record["storage_bytes"]
    fake_storage.sizes = {
        "raw/REG-20260815-00248/0003.mp4": 600,
        "raw/REG-20260815-00248/timeseries2.csv": 400,
        "raw/REG-20260815-00248/audio2.wav": 5,
    }

    resp = client.post(
        f"/api/v1/registrations/{record_id}/raw-files",
        json={
            "object_keys": [
                "raw/REG-20260815-00248/0003.mp4",
                "raw/REG-20260815-00248/timeseries2.csv",
            ],
            "storage_bytes": 1000,
        },
    )
    assert resp.status_code == 200
    version = resp.json()["data"]
    assert version["version_no"] == "v1.0"
    assert set(version["object_keys"]) >= {
        "raw/REG-20260815-00248/0003.mp4",
        "raw/REG-20260815-00248/timeseries2.csv",
    }

    detail = client.get(f"/api/v1/welds/{WELD_0248}").json()["data"]
    assert detail["storage_bytes"] == before_bytes + 1000
    assert set(detail["modalities"]) >= {"video", "timeseries"}

    # 空 object_keys → 400
    resp = client.post(f"/api/v1/registrations/{record_id}/raw-files", json={"object_keys": []})
    assert resp.status_code == 400
    assert resp.json()["code"] == 40000

    # 也支持用登记编号作标识
    resp = client.post(
        "/api/v1/registrations/REG-20260815-00248/raw-files",
        json={"object_keys": ["raw/REG-20260815-00248/audio2.wav"], "storage_bytes": 5},
    )
    assert resp.status_code == 200


def test_attach_raw_files_rejects_missing_object_without_persisting_key(
    override_get_session, override_get_current_user, fake_storage, db_session
) -> None:
    record = client.get(f"/api/v1/welds/{WELD_0248}").json()["data"]
    record_id = record["id"]
    resp = client.post(
        f"/api/v1/registrations/{record_id}/raw-files",
        json={"object_keys": ["raw/REG-20260815-00248/missing.csv"], "storage_bytes": 999},
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == 40000

    version = db_session.exec(
        select(DataVersion).where(DataVersion.record_id == record_id, DataVersion.version_no == "v1.0")
    ).first()
    assert version is not None
    assert "raw/REG-20260815-00248/missing.csv" not in (version.object_keys or [])

    refreshed = client.get(f"/api/v1/welds/{WELD_0248}").json()["data"]
    assert refreshed["storage_bytes"] == record["storage_bytes"]


def test_attach_raw_files_is_idempotent_for_existing_keys(
    override_get_session, override_get_current_user, fake_storage
) -> None:
    record = client.get(f"/api/v1/welds/{WELD_0248}").json()["data"]
    record_id = record["id"]
    key = "raw/REG-20260815-00248/dup.mp4"
    fake_storage.sizes = {key: 321}

    first = client.post(
        f"/api/v1/registrations/{record_id}/raw-files",
        json={"object_keys": [key], "storage_bytes": 999},
    )
    assert first.status_code == 200, first.text
    after_first = client.get(f"/api/v1/welds/{WELD_0248}").json()["data"]

    second = client.post(
        f"/api/v1/registrations/{record_id}/raw-files",
        json={"object_keys": [key], "storage_bytes": 999},
    )
    assert second.status_code == 200, second.text
    after_second = client.get(f"/api/v1/welds/{WELD_0248}").json()["data"]

    assert after_first["storage_bytes"] == record["storage_bytes"] + 321
    assert after_second["storage_bytes"] == after_first["storage_bytes"]
    assert second.json()["data"]["object_keys"].count(key) == 1



def test_attach_raw_files_second_csv_submit_returns_409(
    override_get_session, override_get_current_user, fake_storage
) -> None:
    record = client.get(f"/api/v1/welds/{WELD_0248}").json()["data"]
    record_id = record["id"]
    key = "raw/REG-20260815-00248/second-submit.csv"
    fake_storage.sizes = {key: 321}

    first = client.post(
        f"/api/v1/registrations/{record_id}/raw-files",
        json={"object_keys": [key]},
    )
    assert first.status_code == 200, first.text

    second = client.post(
        f"/api/v1/registrations/{record_id}/raw-files",
        json={"object_keys": [key]},
    )
    assert second.status_code == 409, second.text
    assert second.json()["code"] == 40900



def test_attach_raw_files_rejects_concurrent_duplicate_csv_submit(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import time
    import app.api.v1.welds as welds_api

    db_path = tmp_path / "weld-raw-files-concurrency.db"
    engine = create_engine(
        f"sqlite:///{db_path}", connect_args={"check_same_thread": False}
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        seed_all(session)

    class FileStorage:
        def stat_object(self, object_key: str) -> int:
            return 321 if object_key == key else 0

    def _override_session():
        with Session(engine) as session:
            yield session

    dummy = User(
        id=1,
        username="lin_eng",
        password_hash="not-a-real-hash",
        display_name="林工",
        role="admin",
    )

    def _override_user() -> User:
        return dummy

    key = "raw/REG-20260815-00248/concurrent-submit.csv"
    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_current_user] = _override_user
    monkeypatch.setattr("app.api.v1.welds.get_storage", lambda: FileStorage())

    original_attach_raw_files = welds_api.svc.attach_raw_files

    def _slow_attach_raw_files(*args, **kwargs):
        time.sleep(0.2)
        return original_attach_raw_files(*args, **kwargs)

    monkeypatch.setattr(welds_api.svc, "attach_raw_files", _slow_attach_raw_files)
    record = client.get(f"/api/v1/welds/{WELD_0248}").json()["data"]
    payload = {"object_keys": [key]}
    results: list[tuple[int, dict]] = []
    errors: list[BaseException] = []

    def _worker(delay: float = 0.0) -> None:
        try:
            if delay:
                time.sleep(delay)
            with TestClient(app) as local_client:
                resp = local_client.post(
                    f"/api/v1/registrations/{record['id']}/raw-files",
                    json=payload,
                )
            results.append((resp.status_code, resp.json()))
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [
        threading.Thread(target=_worker, args=(0.0,)),
        threading.Thread(target=_worker, args=(0.05,)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    app.dependency_overrides.pop(get_session, None)
    app.dependency_overrides.pop(get_current_user, None)

    assert not errors
    assert sorted(status for status, _body in results) == [200, 409]



def test_attach_raw_files_returns_409_when_csv_ingest_already_exists(
    override_get_session, override_get_current_user, fake_storage, db_session
) -> None:
    from app.models.analysis import SignalIngest
    from app.services.jobs import create_job

    record = client.get(f"/api/v1/welds/{WELD_0248}").json()["data"]
    record_id = record["id"]
    version = db_session.exec(
        select(DataVersion).where(DataVersion.record_id == record_id, DataVersion.version_no == "v1.0")
    ).first()
    assert version is not None
    key = "raw/REG-20260815-00248/existing-ingest.csv"
    fake_storage.sizes = {key: 321}

    version.object_keys = list(version.object_keys or []) + [key]
    job = create_job(
        db_session,
        "signal_ingest",
        result={"version_id": version.id, "source_object_key": key},
    )
    db_session.add(
        SignalIngest(
            job_id=job.id,
            version_id=version.id,
            source_object_key=key,
            status="pending",
        )
    )
    db_session.commit()

    before = client.get(f"/api/v1/welds/{WELD_0248}").json()["data"]
    resp = client.post(
        f"/api/v1/registrations/{record_id}/raw-files",
        json={"object_keys": [key], "storage_bytes": 999},
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["code"] == 40900

    after = client.get(f"/api/v1/welds/{WELD_0248}").json()["data"]
    assert after["storage_bytes"] == before["storage_bytes"]



def test_attach_raw_files_duplicate_ingest_conflict_returns_existing_or_409(
    override_get_session, override_get_current_user, fake_storage, monkeypatch, db_session
) -> None:
    import app.api.v1.welds as welds_api
    from app.models.analysis import SignalIngest
    from sqlalchemy.exc import IntegrityError

    record = client.get(f"/api/v1/welds/{WELD_0248}").json()["data"]
    record_id = record["id"]
    key = "raw/REG-20260815-00248/concurrent.csv"
    fake_storage.sizes = {key: 321}
    original_commit = welds_api.Session.commit
    triggered = {"value": False}

    def _flaky_commit(self, *args, **kwargs):
        if not triggered["value"] and any(
            isinstance(obj, SignalIngest) and obj.source_object_key == key
            for obj in self.new
        ):
            triggered["value"] = True
            raise IntegrityError("INSERT", {}, Exception("duplicate signal ingest"))
        return original_commit(self, *args, **kwargs)

    monkeypatch.setattr(welds_api.Session, "commit", _flaky_commit)
    resp = client.post(
        f"/api/v1/registrations/{record_id}/raw-files",
        json={"object_keys": [key]},
    )

    assert resp.status_code in {200, 409}, resp.text
    assert triggered["value"] is True
    refreshed = client.get(f"/api/v1/welds/{WELD_0248}").json()["data"]
    assert refreshed["storage_bytes"] == record["storage_bytes"] + 321
    if resp.status_code == 200:
        assert resp.json()["data"]["object_keys"].count(key) == 1
    version = db_session.exec(
        select(DataVersion).where(DataVersion.record_id == record_id, DataVersion.version_no == "v1.0")
    ).first()
    assert version is not None
    ingests = db_session.exec(select(SignalIngest).where(SignalIngest.version_id == version.id)).all()
    assert len([row for row in ingests if row.source_object_key == key]) == 1


# ---------- 核验 ----------


def _version_id_by_no(weld_id, version_no):
    for v in _versions_of(weld_id):
        if v["version_no"] == version_no:
            return v["id"]
    raise AssertionError(f"version {version_no} not found for {weld_id}")


def test_validation_passed_version(override_get_session, override_get_current_user) -> None:
    """0248 v1.2（对齐：video+timeseries+audio，非 raw）→ 15 项全过 → quality 通过。"""
    vid = _version_id_by_no(WELD_0248, "v1.2")
    resp = client.post(f"/api/v1/welds/{WELD_0248}/versions/{vid}/validation")
    assert resp.status_code == 200
    report = resp.json()["data"]
    assert report["score"] == 100.0
    assert report["passed"] == 15
    assert report["warning"] == 0
    assert report["failed"] == 0
    assert len(report["rules"]) == 15
    assert all(r["status"] == "passed" for r in report["rules"])
    assert report["created_at"].endswith("Z")

    detail = client.get(f"/api/v1/welds/{WELD_0248}").json()["data"]
    assert detail["quality"] == "通过"

    # GET validation 返回同一份明细
    resp = client.get(f"/api/v1/welds/{WELD_0248}/versions/{vid}/validation")
    assert resp.status_code == 200
    assert resp.json()["data"]["id"] == report["id"]
    assert len(resp.json()["data"]["rules"]) == 15


def test_validation_failed_version(override_get_session, override_get_current_user) -> None:
    """新建无文件版本 → 多条规则失败 → quality 异常。"""
    resp = client.post(
        f"/api/v1/welds/{WELD_0248}/versions",
        json={"action": "人工修正", "note": "缺文件版本"},
    )
    new_version = resp.json()["data"]
    vid = new_version["id"]

    resp = client.post(f"/api/v1/welds/{WELD_0248}/versions/{vid}/validation")
    assert resp.status_code == 200
    report = resp.json()["data"]
    assert report["failed"] > 0
    assert report["score"] == 0.0
    assert len(report["rules"]) == 15
    statuses = {r["status"] for r in report["rules"]}
    assert "failed" in statuses

    detail = client.get(f"/api/v1/welds/{WELD_0248}").json()["data"]
    assert detail["quality"] == "异常"


def test_validation_raw_video_version_passes(
    override_get_session, override_get_current_user
) -> None:
    """0248 v1.0（raw/ 视频完整版）→ 原始视频跳过帧率检查 → 15 项全过 → quality 通过。

    上传页直传文件全部锚定 raw/ 前缀，若"存在 raw/ 即警告"，上传数据将永远
    带帧率警告、最高只能「待复核」，永远进不了分析流（回归保护）。
    """
    vid = _version_id_by_no(WELD_0248, "v1.0")
    resp = client.post(f"/api/v1/welds/{WELD_0248}/versions/{vid}/validation")
    assert resp.status_code == 200
    report = resp.json()["data"]
    assert report["passed"] == 15
    assert report["warning"] == 0
    assert report["failed"] == 0

    detail = client.get(f"/api/v1/welds/{WELD_0248}").json()["data"]
    assert detail["quality"] == "通过"


def test_validation_unknown_version(override_get_session, override_get_current_user) -> None:
    resp = client.post(f"/api/v1/welds/{WELD_0248}/versions/999999/validation")
    assert resp.status_code == 404
    assert resp.json()["code"] == 40402


# ---------- 未登录 ----------


def test_welds_require_login(override_get_session) -> None:
    """不 override get_current_user：所有端点无 Authorization 头 → 401 信封。"""
    paths = [
        ("GET", "/api/v1/welds"),
        ("GET", f"/api/v1/welds/{WELD_0248}"),
        ("POST", "/api/v1/registrations"),
        ("PATCH", "/api/v1/registrations/1"),
        ("POST", "/api/v1/registrations/1/raw-files"),
        ("GET", f"/api/v1/welds/{WELD_0248}/versions"),
        ("POST", f"/api/v1/welds/{WELD_0248}/versions"),
        ("GET", f"/api/v1/welds/{WELD_0248}/versions/1"),
        ("POST", f"/api/v1/welds/{WELD_0248}/versions/1/validation"),
        ("GET", f"/api/v1/welds/{WELD_0248}/versions/1/validation"),
    ]
    for method, path in paths:
        resp = client.request(method, path, json={})
        assert resp.status_code == 401, (method, path)
        assert resp.json()["code"] == 40100, (method, path)
