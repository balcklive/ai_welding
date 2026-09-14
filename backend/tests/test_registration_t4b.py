"""T4b 登记改造回归（R1 的落库侧 + R6 的校验与兼容）。

全部走真实 HTTP 接口（`/api/v1/registrations`），断言的是接口行为与库里的真实值：

1. **写入只写新列**：`current_a` / `voltage_v` 落库，旧列 `current_voltage` 保持 NULL；读取侧仍给
   旧客户端拼出 `180 A / 22 V`（过渡期双出口）；
2. **量程与形态校验**：电流 1–2000、电压 1–200、厚度 0.1–200（存量 `6mm` 写法可过）、送丝 0–50、
   焊接 0–6000 以内、采集时间不晚于当天、采样频率可解析——全部走 422 + **字段路径**；
3. **字典必选**：焊机型号 / 焊接方法 不在系统设置里 → 400；编辑存量数据时"原值原样提交"放行
   （选项被停用/改名不该让老数据改不动）；
4. **旧字段不能绕过校验**：PATCH 只给 `current_voltage` 时按新列同一套量程判（越界 → 422），
   合法值则解析进新列——不会回写旧列、也不会绕过 `current_a` / `voltage_v` 的约束；
5. **迁移与服务层解析规则一致**：`0017` 的解析/反填函数与 `services.welds` 的同名规则对同一组
   存量形态给出相同结果（两处实现漂移就报错）。
"""

import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel

from app.api.deps import get_current_user
from app.core.db import get_session
from app.main import app
from app.models import DataRecord, User
from app.services import welds as svc

client = TestClient(app)
API = "/api/v1"

#: 存量实测形态（`docs/数据管理改造技术实施方案.md` §T4.2.1）→ 期望的 `(current_a, voltage_v)`。
LEGACY_FORMS: tuple[tuple[str, tuple[float | None, float | None]], ...] = (
    ("180 A / 22 V", (180, 22)),
    ("180A/22V", (180, 22)),          # 无空格形态
    ("250A / 25V", (250, 25)),
    ("180/22", (180, 22)),
    ("180", (180, None)),
    ("", (None, None)),
    ("不是数字", (None, None)),
)


@pytest.fixture()
def engine():
    # StaticPool：FastAPI 的同步端点跑在线程池里，不加它每个线程会各拿一个**空**内存库。
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def db(engine):
    with Session(engine) as session:
        yield session


@pytest.fixture()
def api(db):
    app.dependency_overrides[get_session] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: User(
        id=1, username="t4b", password_hash="x", display_name="T4B", role="admin"
    )
    # 字典必须存在：登记的焊机型号 / 焊接方法只能从系统设置里选（生产由 seed 出厂初始化）。
    from app.core.seed import seed_reference_data

    seed_reference_data(db)
    db.commit()
    yield client
    app.dependency_overrides.pop(get_session, None)
    app.dependency_overrides.pop(get_current_user, None)


# ── 助手 ─────────────────────────────────────────────────────────────


def _ok(response):
    payload = response.json()
    assert payload["code"] == 0, payload
    return payload["data"]


def _new_dataset(api, name: str = "T4b 数据集") -> int:
    return _ok(api.post(f"{API}/datasets", json={"name": name, "task": "时序分类"}))["id"]


def _payload(dataset_id: int, **overrides) -> dict:
    """一份合法的登记载荷（用例按需覆盖单个字段）。"""
    payload = {
        "dataset_id": dataset_id,
        "source": "T4b 产线",
        "collected_at": "2026-09-01T10:00:00",
        "weld_name": "T4b 样本",
        "machine": "Fronius CMT",
        "weld_method": "MAG焊",
        "material": "Q235",
        "thickness": "6mm",
        "current_a": 180,
        "voltage_v": 22,
        "sample_rate": "10 kHz",
    }
    payload.update(overrides)
    return payload


def _error_fields(response) -> list[str]:
    """422 响应里的字段路径（Pydantic `loc` 的最后一段），用于断言"错在哪一格"。"""
    detail = response.json().get("detail")
    assert isinstance(detail, list), response.json()
    return [str(item["loc"][-1]) for item in detail]


# ── 1. 写入只写新列 ──────────────────────────────────────────────────


def test_registration_writes_split_columns_and_keeps_legacy_field_readable(api, db):
    dataset_id = _new_dataset(api)
    # 存量写法 `6mm`：剥单位后落库
    data = _ok(api.post(f"{API}/registrations", json=_payload(dataset_id, thickness="6mm", current_a=180, voltage_v=22)))

    assert data["current_a"] == 180
    assert data["voltage_v"] == 22
    # 旧列给旧客户端用：新登记的行按新列拼回 `180 A / 22 V`
    assert data["current_voltage"] == "180 A / 22 V"
    assert data["thickness"] == "6"

    record = db.get(DataRecord, data["id"])
    assert float(record.current_a) == 180
    assert float(record.voltage_v) == 22
    assert record.current_voltage is None, "D7 写入只写新列，旧列必须保持 NULL"
    assert record.thickness == "6"


def test_registration_without_unit_on_thickness_is_accepted(api):
    dataset_id = _new_dataset(api)
    data = _ok(api.post(f"{API}/registrations", json=_payload(dataset_id, thickness="12")))
    assert data["thickness"] == "12"


# ── 2. 量程与形态校验（字段级 422）───────────────────────────────────


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("current_a", 0),
        ("current_a", 2001),
        ("voltage_v", 0),
        ("voltage_v", 201),
        ("thickness", "0.05"),
        ("thickness", "300"),
        ("thickness", "abc"),
        ("wire_feed_speed", "60"),
        ("welding_speed", "6000"),
        ("sample_rate", "很快"),
        ("source", "x"),          # 2–64 字
        ("weld_name", "x"),
    ],
)
def test_out_of_range_fields_are_rejected_with_field_path(api, field, value):
    dataset_id = _new_dataset(api)
    response = api.post(f"{API}/registrations", json=_payload(dataset_id, **{field: value}))
    assert response.status_code == 422, response.json()
    assert field in _error_fields(response)


def test_collected_at_in_the_future_is_rejected(api):
    dataset_id = _new_dataset(api)
    future = (datetime.now(timezone.utc) + timedelta(days=3)).replace(microsecond=0)
    response = api.post(f"{API}/registrations", json=_payload(dataset_id, collected_at=future.isoformat()))
    assert response.status_code == 422, response.json()
    assert "collected_at" in _error_fields(response)


def test_collected_at_local_wall_clock_today_is_accepted(api):
    """前端提交的是**本地墙钟**（`datetime-local`），UTC+8 的"今天下午"在 UTC 看来是未来几小时——
    容差必须容得下它（否则默认值一打开就被判非法）。"""
    dataset_id = _new_dataset(api)
    local_evening = (datetime.now(timezone.utc) + timedelta(hours=12)).replace(microsecond=0)
    data = _ok(api.post(f"{API}/registrations", json=_payload(dataset_id, collected_at=local_evening.isoformat())))
    assert data["registration_no"]


# ── 3. 字典必选 ──────────────────────────────────────────────────────


def test_machine_outside_dictionary_is_rejected(api):
    dataset_id = _new_dataset(api)
    response = api.post(f"{API}/registrations", json=_payload(dataset_id, machine="不存在的机型"))
    assert response.status_code == 400, response.json()
    assert "焊机型号" in response.json()["message"]


def test_weld_method_outside_dictionary_is_rejected(api):
    dataset_id = _new_dataset(api)
    response = api.post(f"{API}/registrations", json=_payload(dataset_id, weld_method="神秘焊法"))
    assert response.status_code == 400, response.json()
    assert "焊接方法" in response.json()["message"]


def test_patch_accepts_the_record_own_value_even_if_option_was_disabled(api, db):
    """选项在登记之后被停用：老数据仍要能改（前端 `withCurrent` 的同一口径）。"""
    from app.models.settings import OptionItem
    from sqlmodel import select

    dataset_id = _new_dataset(api)
    record = _ok(api.post(f"{API}/registrations", json=_payload(dataset_id)))

    row = db.exec(select(OptionItem).where(OptionItem.value == "Fronius CMT")).first()
    row.active = False
    db.commit()

    # 原值原样提交 → 放行；换一个停用之外的值 → 仍走字典校验
    assert api.patch(f"{API}/registrations/{record['id']}", json={"machine": "Fronius CMT"}).status_code == 200
    assert api.patch(f"{API}/registrations/{record['id']}", json={"machine": "停用后的新机型"}).status_code == 400


# ── 4. 旧字段不能绕过校验 ────────────────────────────────────────────


def test_legacy_current_voltage_cannot_bypass_range(api):
    dataset_id = _new_dataset(api)
    record = _ok(api.post(f"{API}/registrations", json=_payload(dataset_id)))

    response = api.patch(f"{API}/registrations/{record['id']}", json={"current_voltage": "9999 A / 22 V"})
    assert response.status_code == 422, response.json()
    assert "current_voltage" in _error_fields(response)

    response = api.patch(f"{API}/registrations/{record['id']}", json={"current_voltage": "180 A / 999 V"})
    assert response.status_code == 422, response.json()


def test_legacy_current_voltage_is_parsed_into_split_columns(api, db):
    dataset_id = _new_dataset(api)
    record = _ok(api.post(f"{API}/registrations", json=_payload(dataset_id)))

    data = _ok(api.patch(f"{API}/registrations/{record['id']}", json={"current_voltage": "250 A / 25 V"}))
    assert data["current_a"] == 250
    assert data["voltage_v"] == 25

    row = db.get(DataRecord, record["id"])
    assert float(row.current_a) == 250
    assert row.current_voltage is None, "兼容解析只写新列，不得回写旧列"


def test_legacy_payload_on_create_still_works(api):
    """老客户端（只发 `current_voltage`）走兼容解析，仍能完成登记。"""
    dataset_id = _new_dataset(api)
    payload = _payload(dataset_id)
    payload.pop("current_a")
    payload.pop("voltage_v")
    payload["current_voltage"] = "180A/22V"
    data = _ok(api.post(f"{API}/registrations", json=payload))
    assert data["current_a"] == 180
    assert data["voltage_v"] == 22


def test_extra_fields_are_rejected(api):
    """`extra="forbid"`：拼错字段名不会静默丢弃（否则用户以为存上了）。"""
    dataset_id = _new_dataset(api)
    response = api.post(f"{API}/registrations", json=_payload(dataset_id, current=180))
    assert response.status_code == 422, response.json()


# ── 5. 幂等键：规范数字 + 不含旧列 ───────────────────────────────────


def test_request_key_ignores_number_formatting():
    """同值不同表述必须得到同一个键：否则一次提交会被当成两次（重复登记）。"""
    base = {
        "dataset_id": 1,
        "source": "s",
        "collected_at": datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc),
        "weld_name": "n",
    }
    key = lambda extra: svc.registration_request_key({**base, **extra}, "op")  # noqa: E731

    assert key({"current_a": 180, "voltage_v": 22}) == key({"current_a": 180.0, "voltage_v": 22.00})
    assert key({"current_voltage": "180 A / 22 V"}) == key({"current_a": 180, "voltage_v": 22})
    assert key({"current_voltage": "180A/22V"}) == key({"current_a": 180, "voltage_v": 22})
    # 不同电流不得撞键
    assert key({"current_a": 181, "voltage_v": 22}) != key({"current_a": 180, "voltage_v": 22})


# ── 6. 迁移与服务层解析规则一致 ──────────────────────────────────────


def _load_migration_module():
    path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0017_split_current_voltage.py"
    spec = importlib.util.spec_from_file_location("migration_0017", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(("raw", "expected"), LEGACY_FORMS)
def test_migration_parses_every_legacy_form(raw, expected):
    migration = _load_migration_module()
    assert migration._parse_current_voltage(raw) == expected


@pytest.mark.parametrize(("raw", "expected"), LEGACY_FORMS)
def test_service_parses_every_legacy_form_the_same_way(raw, expected):
    """两处实现（迁移 `0017` 与服务层）必须给出同一结果——漂移会让"回填的历史值"与"读取时解析
    的值"不一致。"""
    migration = _load_migration_module()
    parsed = svc.parse_current_voltage(raw)
    service = (
        float(parsed[0]) if parsed[0] is not None else None,
        float(parsed[1]) if parsed[1] is not None else None,
    )
    assert service == expected
    assert migration._parse_current_voltage(raw) == expected


def test_downgrade_backfill_round_trips():
    """回滚反填（`_format_legacy`）必须能被重新解析回同一对数字——否则蓝绿回滚一次就丢值。"""
    migration = _load_migration_module()
    for current, voltage in ((180, 22), (250, 25), (180.5, 22.25)):
        legacy = migration._format_legacy(current, voltage)
        assert migration._parse_current_voltage(legacy) == (current, voltage)


def test_service_format_matches_downgrade_backfill():
    """读取侧给旧客户端拼的字符串，与回滚反填用的是同一套拼法。"""
    migration = _load_migration_module()
    for current, voltage in ((180, 22), (250, 25), (180, None), (None, 22)):
        assert svc.format_current_voltage(current, voltage) == migration._format_legacy(current, voltage)
