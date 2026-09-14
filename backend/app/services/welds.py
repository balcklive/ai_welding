"""Welds 核心 CRUD 服务（Task 10）：焊缝数据列表 / 登记 / 版本 / 核验。

端点契约见 `docs/API接口清单.md` §3.3；业务规则见 `docs/数据库设计.md` §5。
路由层在 `app/api/v1/welds.py`。**写操作不 commit**（含 `write_audit`），
由路由在响应前统一 `session.commit()`（与 `services/jobs.py` 约定一致）。

关键设计决策（坑/边界，改这里时勿破坏）：
- 业务号 `WLD-YYYYMMDD-序号` / `REG-YYYYMMDD-序号`：序号 = **当日同前缀记录数 + 1**，
  零填充（WLD 4 位、REG 5 位，对齐 seed 0248/00248）。日期取登记体的 `collected_at`
  （缺省取今天 UTC）。
- 列表去重：直接查 `data_records`——`latest_version_id` 反规范化已编码"仅最新版本"，
  服务端 LIKE/前缀/精确筛选 + 分页，不做全量加载后过滤（README 规则）。
- tab 映射：`待核验` → `quality=='待复核'`；`已归档` → `quality=='通过'`
  （本项目无归档位，取"已核验通过视为归档"的确定映射）；`最近`/`全部最新` → 仅排序
  （created_at 倒序），不加过滤。
- 核验规则引擎：15 项**确定性**规则（无随机），规则名照抄 `src/App.tsx` Validation /
  `core/seed.py::VALIDATION_RULES`；结果只依赖版本 `object_keys`（存在性/扩展名/命名）
  与登记的工艺参数字段。score = max(0, 100 - 警告*5 - 失败*20)。
  质量级联（§5）：失败>0→异常；仅警告→待复核；否则→通过。
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from threading import Lock

from sqlmodel import Session, func, or_, select

from app.models.analysis import AlignmentTask, FeatureExtraction, SignalIngest, SplitTask
from app.models.data import (
    DataRecord,
    DataVersion,
    ValidationReport,
    ValidationRuleResult,
)
from app.services.datasets import collect_record_references
from app.services.jobs import _iso_utc

# ── 核验规则名（与 App.tsx / seed.VALIDATION_RULES 逐字一致，勿改顺序） ──
VALIDATION_RULES: list[str] = [
    "图像文件完整性",
    "时序信号连续性",
    "采样频率一致性",
    "起收弧事件完整",
    "电流范围合理性",
    "电压范围合理性",
    "送丝速度缺失值",
    "多模态时间戳",
    "视频帧率稳定性",
    "文件命名规范",
    "焊缝ID唯一性",
    "工艺参数完整性",
    "音频信号质量",
    "红外数据完整性",
    "元数据关联关系",
]

_VIDEO_EXTS = (".mp4", ".avi", ".mkv", ".mov")
_IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".bmp")
_TS_EXTS = (".csv", ".txt", ".dat")
_AUDIO_EXTS = (".wav", ".mp3", ".flac", ".m4a")

# 可编辑的登记字段（PATCH 白名单；weld_id/registration_no/quality/modalities 等不可编辑）。
EDITABLE_FIELDS: tuple[str, ...] = (
    "source",
    "collected_at",
    "weld_name",
    "product",
    "machine",
    "weld_method",
    "material",
    "thickness",
    # D7：写入只写新列；`current_voltage` 从白名单移除（旧列仅保留供回滚/回显）
    "current_a",
    "voltage_v",
    "sample_rate",
    "wire_feed_speed",
    "welding_speed",
    "dataset_id",
)


#: T4.2 量程（字段名 → 中文名 / 下限 / 上限 / 是否容忍 `mm` 单位后缀）。
#: 这三个字段在表里仍是 `VARCHAR(32)`（不做迁移），但**写入时归一化成裸数字**，新数据可直接排序比较；
#: 历史值展示时原样显示。
NUMBER_RANGES: dict[str, tuple[str, Decimal, Decimal, bool]] = {
    # 存量实测是 `6mm`，剥单位后必须是 0.1–200
    "thickness": ("板材厚度", Decimal("0.1"), Decimal("200"), True),
    "wire_feed_speed": ("送丝速度", Decimal("0"), Decimal("50"), False),
    "welding_speed": ("焊接速度", Decimal("0"), Decimal("5000"), False),
}


def normalize_number(field: str, value: str) -> str:
    """T4.2 的"以字符串存的数字"字段（厚度 / 送丝速度 / 焊接速度）→ 裸数字字符串。

    越界或解析不出直接 `ValueError`（请求体的 Pydantic 校验器会把它变成 422 字段级错误）。
    """
    label, low, high, allow_mm = NUMBER_RANGES[field]
    pattern = r"^\s*(\d+(?:\.\d+)?)\s*(?:mm|MM|毫米)?\s*$" if allow_mm else r"^\s*(\d+(?:\.\d+)?)\s*$"
    match = re.match(pattern, str(value or ""))
    if not match:
        raise ValueError(f"{label}需为数字（{low:g}–{high:g}）")
    number = Decimal(match.group(1))
    if number < low or number > high:
        raise ValueError(f"{label}需在 {low:g}–{high:g} 之间")
    return str(number)


def _normalized_or_none(field: str, value: str | None) -> str | None:
    return None if value is None else normalize_number(field, value)


def normalize_fields(data: dict) -> dict:
    """T4.2 的**归一化入口**（新建 / 编辑共用）：把厚度、送丝速度、焊接速度落库前统一成裸数字。

    量程校验在请求体里已做（Pydantic → 422 字段级错误），这里只负责改写入形态，顺带兜住
    服务层的直接调用方（脚本 / 测试）。
    """
    normalized = dict(data)
    for field in NUMBER_RANGES:
        if normalized.get(field):
            normalized[field] = normalize_number(field, normalized[field])
    return normalized


def parse_current_voltage(value: str | None) -> tuple[Decimal | None, Decimal | None]:
    """`current_voltage`（`180 A / 22 V`、`180A/22V`、`180/22`、`180`）→ `(current_a, voltage_v)`。

    与迁移 `0017` 的回填同一套规则：D7 之后写入只写新列，但**旧客户端的兼容请求**与**历史数据**
    仍会用这个函数解析一次。
    """
    if not value:
        return None, None
    match = _CURRENT_VOLTAGE_PATTERN.match(str(value))
    if not match:
        return None, None
    current = Decimal(match.group(1))
    voltage = Decimal(match.group(2)) if match.group(2) else None
    return current, voltage


_CURRENT_VOLTAGE_PATTERN = re.compile(
    r"^\s*(\d+(?:\.\d+)?)\s*[aA]?\s*(?:/\s*(\d+(?:\.\d+)?)\s*[vV]?\s*)?$"
)


def _resolve_current_voltage(data: dict) -> tuple[Decimal | None, Decimal | None]:
    """写入用的 `(current_a, voltage_v)`：新列优先；只给旧列（兼容请求）时解析一次。"""
    if data.get("current_a") is not None or data.get("voltage_v") is not None:
        return data.get("current_a"), data.get("voltage_v")
    return parse_current_voltage(data.get("current_voltage"))


def format_current_voltage(current_a: Decimal | float | None, voltage_v: Decimal | float | None) -> str | None:
    """`(current_a, voltage_v)` → 旧列 `current_voltage` 的字符串形态（`180 A / 22 V`）。

    `parse_current_voltage` 的逆运算，供**旧客户端**读取过渡期使用；迁移 `0017.downgrade` 的反填
    用的是同一套拼法（那里刻意留了独立副本，迁移不 import 应用代码）。
    """
    def _fmt(value) -> str | None:
        if value is None:
            return None
        number = float(value)
        return str(int(number)) if number.is_integer() else str(number)

    current, voltage = _fmt(current_a), _fmt(voltage_v)
    if current is None and voltage is None:
        return None
    if current is None:
        return f"? A / {voltage} V"
    if voltage is None:
        return f"{current} A"
    return f"{current} A / {voltage} V"


class WeldDeleteConflict(ValueError):
    """焊缝仍被不可逆业务产物引用，不能安全删除。"""

_REGISTRATION_PAYLOAD_LOCK = Lock()
_ACTIVE_REGISTRATION_KEYS: set[str] = set()
_RAW_FILES_PAYLOAD_LOCK = Lock()
_ACTIVE_RAW_FILES_KEYS: set[str] = set()


@dataclass
class _MySQLAdvisoryLock:
    name: str
    connection: object


# ── 业务号生成器 ─────────────────────────────────────────────────────


def _is_mysql_session(session: Session) -> bool:
    bind = session.get_bind()
    return bind is not None and bind.dialect.name == "mysql"



def _mysql_lock_connection(session: Session):
    bind = session.get_bind()
    if bind is None:
        raise RuntimeError("Database connection is unavailable")
    return bind.raw_connection()



def _mysql_lock_scalar(connection, sql: str, params: tuple) -> int | None:
    cursor = connection.cursor()
    try:
        cursor.execute(sql, params)
        row = cursor.fetchone()
        return None if row is None else row[0]
    finally:
        cursor.close()



def _acquire_registration_lock(session: Session, day: date) -> _MySQLAdvisoryLock | None:
    if not _is_mysql_session(session):
        return None
    lock_name = f"data_record_seq:{day.strftime('%Y%m%d')}"
    connection = _mysql_lock_connection(session)
    acquired = None
    try:
        acquired = _mysql_lock_scalar(connection, "SELECT GET_LOCK(%s, %s)", (lock_name, 1))
        if acquired != 1:
            raise RuntimeError("Failed to acquire the registration number lock")
        return _MySQLAdvisoryLock(lock_name, connection)
    except Exception:
        if acquired != 1:
            connection.close()
        raise



def _release_registration_lock(
    session: Session, lock_name: _MySQLAdvisoryLock | str | None
) -> None:
    if lock_name is None:
        return
    if isinstance(lock_name, _MySQLAdvisoryLock):
        try:
            _mysql_lock_scalar(lock_name.connection, "SELECT RELEASE_LOCK(%s)", (lock_name.name,))
        finally:
            lock_name.connection.close()
        return



def next_weld_id(session: Session, day: date) -> str:
    """`WLD-YYYYMMDD-序号`：序号 = 当日 WLD 前缀记录数 + 1，4 位零填充。"""
    prefix = f"WLD-{day.strftime('%Y%m%d')}-"
    count = _count_prefix(session, DataRecord.weld_id, prefix)
    return f"{prefix}{count + 1:04d}"


def next_registration_no(session: Session, day: date) -> str:
    """`REG-YYYYMMDD-序号`：序号 = 当日 REG 前缀记录数 + 1，5 位零填充。"""
    prefix = f"REG-{day.strftime('%Y%m%d')}-"
    count = _count_prefix(session, DataRecord.registration_no, prefix)
    return f"{prefix}{count + 1:05d}"


def next_version_no(session: Session, record_id: int) -> str:
    """`v1.<n>`：同焊缝现有最大次版本 + 1（v1.0..v1.3 → v1.4）。"""
    rows = session.exec(
        select(DataVersion.version_no).where(DataVersion.record_id == record_id)
    ).all()
    max_minor = 0
    for value in rows:
        try:
            minor = int(str(value).split(".", 1)[1])
        except (IndexError, ValueError):
            continue
        max_minor = max(max_minor, minor)
    return f"v1.{max_minor + 1}"


# ── 登记 ─────────────────────────────────────────────────────────────


def _canonical_number(value) -> str | None:
    """数字字段的规范写法（`180` 与 `180.0` 必须得到同一个幂等键——R6）。"""
    if value is None or value == "":
        return None
    try:
        return str(Decimal(str(value)).normalize())
    except InvalidOperation:
        return str(value)


def registration_request_key(data: dict, operator: str) -> str:
    """登记自然幂等键：同 operator + 同表单载荷视为同一次提交。

    载荷里**不再包含旧列** `current_voltage`（D7：写入只写新列），电流电压取**解析后的新值**再按
    规范数字比对——这样 `180` / `180.0` / `180A/22V` 三种写法会得到同一个键（否则同值不同表述会
    重复登记，`current_voltage` 还可能因缺项而让两次不同的提交撞成一个键）。
    """
    current_a, voltage_v = _resolve_current_voltage(data)
    payload = {
        "source": (data.get("source") or "").strip(),
        "collected_at": _iso_utc(_as_utc(data.get("collected_at"))),
        "weld_name": data.get("weld_name"),
        "product": data.get("product"),
        "machine": data.get("machine"),
        "weld_method": data.get("weld_method"),
        "material": data.get("material"),
        "thickness": _canonical_number(data.get("thickness")),
        "current_a": _canonical_number(current_a),
        "voltage_v": _canonical_number(voltage_v),
        "sample_rate": data.get("sample_rate"),
        "wire_feed_speed": _canonical_number(data.get("wire_feed_speed")),
        "welding_speed": _canonical_number(data.get("welding_speed")),
        "operator": operator,
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()



def _acquire_registration_payload_lock(
    session: Session, data: dict, operator: str
) -> _MySQLAdvisoryLock | str:
    request_key = registration_request_key(data, operator)
    if _is_mysql_session(session):
        lock_name = f"data_record_req:{request_key[:48]}"
        connection = _mysql_lock_connection(session)
        acquired = None
        try:
            acquired = _mysql_lock_scalar(connection, "SELECT GET_LOCK(%s, %s)", (lock_name, 0))
            if acquired != 1:
                raise RuntimeError("Duplicate registration request: the same form is already being submitted")
            return _MySQLAdvisoryLock(lock_name, connection)
        except Exception:
            if acquired != 1:
                connection.close()
            raise
    with _REGISTRATION_PAYLOAD_LOCK:
        if request_key in _ACTIVE_REGISTRATION_KEYS:
                raise RuntimeError("Duplicate registration request: the same form is already being submitted")
        _ACTIVE_REGISTRATION_KEYS.add(request_key)
    return request_key



def _release_registration_payload_lock(
    session: Session, lock_name: _MySQLAdvisoryLock | str | None
) -> None:
    if lock_name is None:
        return
    if isinstance(lock_name, _MySQLAdvisoryLock):
        try:
            _mysql_lock_scalar(lock_name.connection, "SELECT RELEASE_LOCK(%s)", (lock_name.name,))
        finally:
            lock_name.connection.close()
        return
    with _REGISTRATION_PAYLOAD_LOCK:
        _ACTIVE_REGISTRATION_KEYS.discard(lock_name)



def raw_files_request_key(version_id: int, object_keys: list[str]) -> str:
    payload = {
        "version_id": version_id,
        "object_keys": sorted(dict.fromkeys(object_keys)),
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()



def _acquire_raw_files_payload_lock(
    session: Session, version_id: int, object_keys: list[str]
) -> _MySQLAdvisoryLock | str:
    request_key = raw_files_request_key(version_id, object_keys)
    if _is_mysql_session(session):
        lock_name = f"raw_files_req:{request_key[:48]}"
        connection = _mysql_lock_connection(session)
        acquired = None
        try:
            acquired = _mysql_lock_scalar(connection, "SELECT GET_LOCK(%s, %s)", (lock_name, 0))
            if acquired != 1:
                raise RuntimeError("A CSV import task already exists")
            return _MySQLAdvisoryLock(lock_name, connection)
        except Exception:
            if acquired != 1:
                connection.close()
            raise
    with _RAW_FILES_PAYLOAD_LOCK:
        if request_key in _ACTIVE_RAW_FILES_KEYS:
            raise RuntimeError("A CSV import task already exists")
        _ACTIVE_RAW_FILES_KEYS.add(request_key)
    return request_key



def _release_raw_files_payload_lock(
    session: Session, lock_name: _MySQLAdvisoryLock | str | None
) -> None:
    if lock_name is None:
        return
    if isinstance(lock_name, _MySQLAdvisoryLock):
        try:
            _mysql_lock_scalar(lock_name.connection, "SELECT RELEASE_LOCK(%s)", (lock_name.name,))
        finally:
            lock_name.connection.close()
        return
    with _RAW_FILES_PAYLOAD_LOCK:
        _ACTIVE_RAW_FILES_KEYS.discard(lock_name)



def create_registration(
    session: Session, data: dict, operator: str
) -> tuple[DataRecord, DataVersion]:
    """事务内建 data_records + v1.0「原始数据」版本 + 回写 latest_version_id。

    不 commit（由路由统一提交）。返回 (record, v1.0_version)。
    """
    now = datetime.now(timezone.utc)
    collected_at = _as_utc(data.get("collected_at"))
    day = _seq_date(collected_at)
    # D7：**写入只写新列**（旧列在过渡期只读，回滚靠 `0017.downgrade` 反向回填）。请求只给旧字段
    # （旧客户端/历史脚本）时按 `180 A / 22 V` 解析一次；厚度/速度剥单位归一化成裸数字——量程已在
    # 请求体里校验过（R6 的"统一入口"），这里只落库形态。
    current_a, voltage_v = _resolve_current_voltage(data)
    normalized_thickness = _normalized_or_none("thickness", data.get("thickness"))

    record = DataRecord(
        weld_id=next_weld_id(session, day),
        registration_no=next_registration_no(session, day),
        weld_name=data.get("weld_name"),
        source=data.get("source") or "",
        collected_at=collected_at,
        machine=data.get("machine"),
        weld_method=data.get("weld_method"),
        material=data.get("material"),
        thickness=normalized_thickness,
        # 旧列在过渡期只读（不双写：两列不一致时"谁是权威"没有答案）
        current_voltage=None,
        current_a=current_a,
        voltage_v=voltage_v,
        sample_rate=data.get("sample_rate"),
        wire_feed_speed=data.get("wire_feed_speed"),
        welding_speed=data.get("welding_speed"),
        product=data.get("product"),
        dataset_id=int(data["dataset_id"]),
        modalities=[],
        quality="待复核",
        operator=operator,
        storage_bytes=0,
        created_at=now,
        updated_at=now,
    )
    session.add(record)
    session.flush()

    version = DataVersion(
        record_id=record.id,
        version_no="v1.0",
        action="原始数据",
        operator=operator,
        note="初始登记，原始数据",
        object_keys=[],
        created_at=now,
    )
    session.add(version)
    session.flush()
    record.latest_version_id = version.id
    session.add(record)
    return record, version


def update_registration(session: Session, record: DataRecord, data: dict) -> DataRecord:
    """PATCH 登记可编辑字段（白名单内；None 跳过，保留原值）。调用方 commit。

    归一化（`normalize_fields`）与旧列兼容解析（`_resolve_current_voltage`）与新建**走同一套**；
    `current_voltage` 不在白名单里，只会经由兼容解析写进新列，不会回写旧列。量程校验由请求体
    （`RegistrationUpdate`）负责——这里的兼容路径同样过它，只是解析动作在服务层再做一次。
    """
    data = normalize_fields(data)
    if data.get("current_voltage") and data.get("current_a") is None and data.get("voltage_v") is None:
        parsed_current, parsed_voltage = parse_current_voltage(data["current_voltage"])
        data = {**data, "current_a": parsed_current, "voltage_v": parsed_voltage}
    for field in EDITABLE_FIELDS:
        if field not in data or data[field] is None:
            continue
        value = _as_utc(data[field]) if field == "collected_at" else data[field]
        setattr(record, field, value)
    record.updated_at = datetime.now(timezone.utc)
    return record


def attach_raw_files(
    session: Session,
    record: DataRecord,
    version: DataVersion,
    object_keys: list[str],
    storage_bytes: int = 0,
) -> DataVersion:
    """把原始文件对象键挂到 v1.0 版本（去重追加）+ 累加 storage_bytes + 推导回填 modalities。

    调用方 commit。返回更新后的版本。
    """
    existing = list(version.object_keys or [])
    for key in object_keys:
        if key not in existing:
            existing.append(key)
    version.object_keys = existing
    record.storage_bytes = (record.storage_bytes or 0) + storage_bytes
    record.modalities = sorted(set((record.modalities or []) + _derive_modalities(object_keys)))
    record.updated_at = datetime.now(timezone.utc)
    return version


def get_v10_version(session: Session, record_id: int) -> DataVersion | None:
    """查某焊缝的 v1.0「原始数据」版本（登记时创建）。"""
    return session.exec(
        select(DataVersion).where(
            DataVersion.record_id == record_id, DataVersion.version_no == "v1.0"
        )
    ).first()


# ── 版本 ─────────────────────────────────────────────────────────────


def list_versions(session: Session, record_id: int) -> list[DataVersion]:
    """版本链：按 created_at / id 升序（v1.0 → v1.n）。"""
    return list(
        session.exec(
            select(DataVersion)
            .where(DataVersion.record_id == record_id)
            .order_by(DataVersion.created_at, DataVersion.id)
        ).all()
    )


def get_version(session: Session, version_id: int) -> DataVersion | None:
    return session.get(DataVersion, version_id)


def create_version(
    session: Session,
    record: DataRecord,
    action: str,
    note: str | None,
    object_keys: list[str] | None,
    operator: str,
    request_key: str | None = None,
) -> DataVersion:
    """新建加工版本（去噪处理/人工修正）+ 更新 latest_version_id。调用方 commit。"""
    version = DataVersion(
        record_id=record.id,
        version_no=next_version_no(session, record.id),
        action=action,
        operator=operator,
        note=note,
        request_key=request_key,
        object_keys=list(object_keys or []),
        created_at=datetime.now(timezone.utc),
    )
    session.add(version)
    session.flush()
    record.latest_version_id = version.id
    record.updated_at = datetime.now(timezone.utc)
    return version


def find_duplicate_version(
    session: Session,
    record_id: int,
    action: str,
    note: str | None,
    object_keys: list[str] | None,
) -> DataVersion | None:
    """查找同焊缝下 payload 完全相同的加工版本，供路由返回明确 409。"""
    request_key = version_request_key(action, note, object_keys)
    return session.exec(
        select(DataVersion)
        .where(
            DataVersion.record_id == record_id,
            DataVersion.action == action,
            DataVersion.request_key == request_key,
        )
        .order_by(DataVersion.id.desc())
    ).first()


# ── 核验 ─────────────────────────────────────────────────────────────


def run_validation(
    session: Session, record: DataRecord, version: DataVersion
) -> ValidationReport:
    """同步执行 15 项规则核验：写 report + rule_results + 回写 quality，返回 report。

    确定性：结果只依赖版本 `object_keys` 与登记的工艺参数字段，无随机，测试可稳定断言。
    调用方 commit。
    """
    rule_statuses = _evaluate_rules(list(version.object_keys or []), record)
    passed = sum(1 for r in rule_statuses if r["status"] == "passed")
    warning = sum(1 for r in rule_statuses if r["status"] == "warning")
    failed = sum(1 for r in rule_statuses if r["status"] == "failed")
    score = max(0, 100 - warning * 5 - failed * 20)

    report = ValidationReport(
        version_id=version.id,
        score=Decimal(str(score)),
        passed=passed,
        warning=warning,
        failed=failed,
        duration=Decimal(str(round(0.9 + 0.1 * len(version.object_keys or []), 2))),
        created_at=datetime.now(timezone.utc),
    )
    session.add(report)
    session.flush()
    for rule in rule_statuses:
        session.add(
            ValidationRuleResult(
                report_id=report.id,
                rule_name=rule["rule_name"],
                status=rule["status"],
                message=rule["message"],
            )
        )

    # 质量级联（数据库设计 §5）：失败>0→异常 / 仅警告→待复核 / 否则→通过。
    if failed > 0:
        record.quality = "异常"
    elif warning > 0:
        record.quality = "待复核"
    else:
        record.quality = "通过"
    record.updated_at = datetime.now(timezone.utc)
    return report


def get_latest_validation(session: Session, version_id: int) -> ValidationReport | None:
    """某版本最近一次核验报告（created_at 倒序取最新）。"""
    return session.exec(
        select(ValidationReport)
        .where(ValidationReport.version_id == version_id)
        .order_by(ValidationReport.created_at.desc(), ValidationReport.id.desc())
    ).first()


# ── 查询助手 ─────────────────────────────────────────────────────────


def list_welds(
    session: Session,
    q: str | None = None,
    source: str | None = None,
    brand: str | None = None,
    status: str | None = None,
    tab: str | None = None,
    dataset_id: int | None = None,
    page: int = 1,
    page_size: int = 20,
    weld_ids: list[str] | None = None,
) -> tuple[list[DataRecord], int]:
    """数据列表：服务端筛选 + 分页。去重由 `latest_version_id` 反规范化保证。

    返回 (items, total)。
    - q: weld_id / registration_no LIKE
    - source: 数据来源前缀（如 产线相机）
    - brand: 焊机品牌前缀（如 Fronius）
    - status: quality 精确（通过/待复核/异常）
    - tab: 待核验→待复核 / 已归档→通过 / 最近·全部最新→仅排序
    - dataset_id: 归属数据集精确（数据集优先两级选择的第二级范围）
    """
    conditions = _build_filters(q, source, brand, status, tab, dataset_id, weld_ids)
    total = int(
        session.exec(select(func.count(DataRecord.id)).where(*conditions)).one()
    )
    items = session.exec(
        select(DataRecord)
        .where(*conditions)
        .order_by(DataRecord.created_at.desc(), DataRecord.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return list(items), total


def get_record_by_weld_id(session: Session, weld_id: str) -> DataRecord | None:
    return session.exec(select(DataRecord).where(DataRecord.weld_id == weld_id)).first()


def delete_record(session: Session, record: DataRecord) -> dict[str, int]:
    """删除样本及其可安全删除的处理产物。

    **与预检共用同一个引用采集函数**（`datasets.collect_record_references`，T7）：改造前只按
    `SplitTask` 拦截，基础样本 / 数据集版本成员引用 / 标注任务三条路径都漏了——删样本会留下
    孤儿 `Sample` 指针，防泄漏分组对它退化成"每条一组"。
    """
    report = collect_record_references(session, record)
    if report.blocking:
        raise WeldDeleteConflict("；".join(report.blocking))

    versions = session.exec(
        select(DataVersion).where(DataVersion.record_id == record.id)
    ).all()
    version_ids = [version.id for version in versions if version.id is not None]
    if version_ids:
        for version_id in version_ids:
            for report in session.exec(select(ValidationReport).where(
                ValidationReport.version_id == version_id
            )).all():
                for rule in session.exec(select(ValidationRuleResult).where(
                    ValidationRuleResult.report_id == report.id
                )).all():
                    session.delete(rule)
                session.delete(report)
            for model in (AlignmentTask, FeatureExtraction, SignalIngest):
                for item in session.exec(select(model).where(model.version_id == version_id)).all():
                    session.delete(item)
        record.latest_version_id = None
        session.flush()
        for version in versions:
            session.delete(version)
        # DataVersion.record_id 是父记录删除的外键；先实际删除版本，避免 MySQL
        # 在同一次 flush 中错误地先删除 data_records。
        session.flush()

    session.delete(record)
    session.flush()
    return {"deleted_versions": len(versions)}


def list_through_welds(session: Session, weld_ids: list[str] | None = None) -> list[DataRecord]:
    """核验通过（quality=通过）的可分析焊缝，created_at 倒序。供 analysis candidates。"""
    stmt = select(DataRecord).where(DataRecord.quality == "通过")
    if weld_ids is not None:
        if weld_ids:
            stmt = stmt.where(DataRecord.weld_id.in_(weld_ids))
        else:
            stmt = stmt.where(DataRecord.id == -1)
    return list(
        session.exec(
            stmt.order_by(DataRecord.created_at.desc(), DataRecord.id.desc())
        ).all()
    )


def get_record_by_identifier(session: Session, identifier: str) -> DataRecord | None:
    """registration 端点兼容 DB id / registration_no / weld_id 三种标识。"""
    try:
        record = session.get(DataRecord, int(identifier))
        if record is not None:
            return record
    except (TypeError, ValueError):
        pass
    return session.exec(
        select(DataRecord).where(
            or_(
                DataRecord.registration_no == identifier,
                DataRecord.weld_id == identifier,
            )
        )
    ).first()


# ── payload ──────────────────────────────────────────────────────────


def record_payload(session: Session, record: DataRecord) -> dict:
    latest = None
    if record.latest_version_id is not None:
        latest = session.get(DataVersion, record.latest_version_id)
    return _record_dict(record, latest)


def records_payload(session: Session, records: list[DataRecord]) -> list[dict]:
    """批量序列化（latest_version 一次性查回，避免逐条 N+1）。"""
    ids = [r.latest_version_id for r in records if r.latest_version_id is not None]
    versions: dict[int, DataVersion] = {}
    if ids:
        for v in session.exec(
            select(DataVersion).where(DataVersion.id.in_(ids))
        ).all():
            versions[v.id] = v
    return [
        _record_dict(record, versions.get(record.latest_version_id))
        for record in records
    ]


def version_payload(version: DataVersion | None) -> dict | None:
    if version is None:
        return None
    return {
        "id": version.id,
        "record_id": version.record_id,
        "version_no": version.version_no,
        "action": version.action,
        "operator": version.operator,
        "note": version.note,
        "object_keys": version.object_keys or [],
        "created_at": _iso_utc(version.created_at),
    }


def validation_payload(session: Session, report: ValidationReport) -> dict:
    rules = session.exec(
        select(ValidationRuleResult)
        .where(ValidationRuleResult.report_id == report.id)
        .order_by(ValidationRuleResult.id)
    ).all()
    return {
        "id": report.id,
        "version_id": report.version_id,
        "score": float(report.score),
        "passed": report.passed,
        "warning": report.warning,
        "failed": report.failed,
        "duration": float(report.duration) if report.duration is not None else None,
        "created_at": _iso_utc(report.created_at),
        "rules": [
            {"rule_name": r.rule_name, "status": r.status, "message": r.message}
            for r in rules
        ],
    }


# ── 内部实现 ─────────────────────────────────────────────────────────


def version_request_key(action: str, note: str | None, object_keys: list[str] | None) -> str:
    """加工版本自然幂等键：同 action/note/object_keys（键顺序无关）得到同一摘要。"""
    payload = {
        "action": action,
        "note": note or None,
        "object_keys": sorted(dict.fromkeys(object_keys or [])),
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()



def _count_prefix(session: Session, column, prefix: str) -> int:
    return int(session.exec(select(func.count(DataRecord.id)).where(column.like(prefix + "%"))).one())


def _seq_date(collected_at: datetime | None) -> date:
    return (collected_at or datetime.now(timezone.utc)).date()


def _as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _build_filters(q, source, brand, status, tab, dataset_id=None, weld_ids=None) -> list:
    conditions = []
    if q:
        like = f"%{q}%"
        conditions.append(
            or_(DataRecord.weld_id.like(like), DataRecord.registration_no.like(like))
        )
    if source:
        conditions.append(DataRecord.source.like(f"{source}%"))
    if brand:
        conditions.append(DataRecord.machine.like(f"{brand}%"))
    if status:
        conditions.append(DataRecord.quality == status)
    if dataset_id is not None:
        conditions.append(DataRecord.dataset_id == dataset_id)
    if weld_ids is not None:
        if weld_ids:
            conditions.append(DataRecord.weld_id.in_(weld_ids))
        else:
            conditions.append(DataRecord.id == -1)
    if tab == "待核验":
        conditions.append(DataRecord.quality == "待复核")
    elif tab == "已归档":
        conditions.append(DataRecord.quality == "通过")
    # 「最近」/「全部最新」/未知 tab：不加过滤，统一 created_at 倒序。
    return conditions


def _derive_modalities(object_keys: list[str]) -> list[str]:
    """按文件扩展名推导模态（video 含视频与图像，词表对齐前端 video/timeseries/audio/infrared）。"""
    mods: set[str] = set()
    for key in object_keys:
        low = key.lower()
        if low.endswith(_VIDEO_EXTS + _IMAGE_EXTS):
            mods.add("video")
        if low.endswith(_TS_EXTS):
            mods.add("timeseries")
        if low.endswith(_AUDIO_EXTS):
            mods.add("audio")
        if "infrared" in low or low.endswith((".seq", ".raw")):
            mods.add("infrared")
    return list(mods)


def _has_ext(lower_keys: list[str], exts: tuple[str, ...]) -> bool:
    return any(k.endswith(e) for k in lower_keys for e in exts)


def _valid_key(key: str) -> bool:
    return bool(re.fullmatch(r"[\w./\-]+", key))


def _record_current_voltage(record: DataRecord | None) -> tuple[float | None, float | None]:
    """登记的电流 / 电压（T4b）：**新列优先，旧列解析回退**。"""
    if record is None:
        return None, None
    if record.current_a is not None or record.voltage_v is not None:
        return (
            float(record.current_a) if record.current_a is not None else None,
            float(record.voltage_v) if record.voltage_v is not None else None,
        )
    parsed_current, parsed_voltage = parse_current_voltage(record.current_voltage)
    return (
        float(parsed_current) if parsed_current is not None else None,
        float(parsed_voltage) if parsed_voltage is not None else None,
    )


def _evaluate_rules(keys: list[str], record: DataRecord | None) -> list[dict]:
    """15 项规则确定性评估：返回 `[{status, message}]`，与 `VALIDATION_RULES` 顺序一致。

    依据：object_keys 里视频/图像/时序/音频文件的存在性与命名、登记工艺参数。
    设计目标（供测试稳定断言）：
    - 完整加工版本（video+timeseries+audio，非 raw）→ 15 通过 → 质量「通过」
    - 含 raw 视频的完整版本 → 同样 15 通过（原始视频跳过帧率检查）→ 质量「通过」
    - 无任何文件 → 多条失败 → 质量「异常」
    """
    low = [k.lower() for k in keys]
    has_video = _has_ext(low, _VIDEO_EXTS) or _has_ext(low, _IMAGE_EXTS)
    has_ts = _has_ext(low, _TS_EXTS)
    has_audio = _has_ext(low, _AUDIO_EXTS)
    has_files = bool(keys)
    infra = any("infrared" in k for k in low)
    # 仅当 raw/ 前缀的 key 是**视频**扩展名才视为未加工视频。上传页直传的全部文件都锚定
    # raw/ 前缀（原数据登记约定），若按"存在 raw/ 即 raw"判定，上传数据将永远带帧率
    # 警告、质量最高只能「待复核」，永远进不了分析流。
    is_raw_video = any(k.startswith("raw/") and k.endswith(_VIDEO_EXTS) for k in low)

    def passed(msg: str = "检查通过 · 结果已记录") -> dict:
        return {"status": "passed", "message": msg}

    def warning(msg: str) -> dict:
        return {"status": "warning", "message": msg}

    def failed(msg: str) -> dict:
        return {"status": "failed", "message": msg}

    rules: list[dict] = []

    if has_video:
        rules.append(passed("图像/视频文件完整"))
    elif has_files:
        rules.append(warning("缺少图像/视频文件，建议补充"))
    else:
        rules.append(failed("未关联任何文件，缺少图像/视频数据"))

    if has_ts:
        rules.append(passed("时序信号连续，无断裂"))
    elif has_files:
        rules.append(warning("缺少时序信号文件，无法核验连续性"))
    else:
        rules.append(failed("未关联文件，缺少时序信号"))

    if has_ts:
        rules.append(passed("采样频率一致"))
    elif has_files:
        rules.append(warning("缺少时序信号，无法核对采样频率"))
    else:
        rules.append(failed("未关联文件，无法核对采样频率"))

    if has_files:
        rules.append(passed("起收弧事件信息完整"))
    else:
        rules.append(failed("未关联文件，缺少起收弧事件信息"))

    # T4b/D7：这两条规则原来看的是"有没有时序文件"（名不副实——只要传了 CSV 就算通过）。
    # 现在改读**登记值**：新列优先，只有旧列（历史数据）时解析一次，两列都空才算"缺少数据"。
    current_a, voltage_v = _record_current_voltage(record)
    if current_a is not None:
        rules.append(
            passed(f"电流范围合理（{current_a:g} A）")
            if 1 <= current_a <= 2000
            else failed(f"电流超出合理范围（{current_a:g} A，应为 1–2000 A）")
        )
    elif has_files:
        rules.append(warning("缺少电流数据，无法核验范围"))
    else:
        rules.append(failed("未关联文件，缺少电流数据"))

    if voltage_v is not None:
        rules.append(
            passed(f"电压范围合理（{voltage_v:g} V）")
            if 1 <= voltage_v <= 200
            else failed(f"电压超出合理范围（{voltage_v:g} V，应为 1–200 V）")
        )
    elif has_files:
        rules.append(warning("缺少电压数据，无法核验范围"))
    else:
        rules.append(failed("未关联文件，缺少电压数据"))

    if has_ts:
        rules.append(passed("送丝速度无异常缺失"))
    elif has_files:
        rules.append(warning("缺少送丝速度数据，无法核验缺失值"))
    else:
        rules.append(failed("未关联文件，缺少送丝速度数据"))

    if has_files:
        rules.append(passed("多模态时间戳对齐"))
    else:
        rules.append(failed("未关联文件，无法核验多模态时间戳"))

    if is_raw_video:
        rules.append(passed("原始视频，跳过帧率稳定检查"))
    elif has_video:
        rules.append(passed("视频帧率稳定，无波动"))
    else:
        rules.append(passed("无视频数据，跳过帧率检查"))

    if has_files and all(_valid_key(k) for k in keys):
        rules.append(passed("文件命名规范"))
    elif has_files:
        rules.append(failed("存在不合规的文件命名，请检查"))
    else:
        rules.append(failed("未关联文件，无法核验命名规范"))

    rules.append(passed("焊缝 ID 唯一，无冲突"))

    if record is not None and record.machine and record.material and record.weld_method:
        rules.append(passed("工艺参数完整"))
    else:
        rules.append(warning("工艺参数不完整，建议补充"))

    if has_audio:
        rules.append(passed("音频信号质量正常"))
    elif has_files:
        rules.append(passed("无音频数据，跳过检查"))
    else:
        rules.append(failed("未关联文件，缺少音频数据"))

    if infra:
        rules.append(passed("红外数据完整"))
    elif has_files:
        rules.append(passed("无红外数据，跳过检查"))
    else:
        rules.append(failed("未关联文件，缺少红外数据"))

    if record is not None and record.weld_id and record.registration_no:
        rules.append(passed("元数据关联关系正确"))
    else:
        rules.append(failed("元数据关联关系缺失"))

    assert len(rules) == len(VALIDATION_RULES), "核验规则数必须等于 15"
    return [
        {"rule_name": VALIDATION_RULES[i], **rules[i]}
        for i in range(len(VALIDATION_RULES))
    ]


def _record_dict(record: DataRecord, latest: DataVersion | None) -> dict:
    return {
        "id": record.id,
        "weld_id": record.weld_id,
        "weld_name": record.weld_name,
        "registration_no": record.registration_no,
        "source": record.source,
        "collected_at": _iso_utc(record.collected_at),
        "machine": record.machine,
        "weld_method": record.weld_method,
        "material": record.material,
        "thickness": record.thickness,
        # 过渡期双出口：新列是权威；旧列给**旧客户端**用（历史行原样输出，新登记的行按新列拼回来，
        # 否则老前端在"写入只写新列"之后会看到空白）。拼法与迁移 `0017.downgrade` 的反填一致。
        "current_voltage": record.current_voltage or format_current_voltage(record.current_a, record.voltage_v),
        "current_a": float(record.current_a) if record.current_a is not None else None,
        "voltage_v": float(record.voltage_v) if record.voltage_v is not None else None,
        "sample_rate": record.sample_rate,
        "wire_feed_speed": record.wire_feed_speed,
        "welding_speed": record.welding_speed,
        "data_fields": record.data_fields,
        "product": record.product,
        "dataset_id": record.dataset_id,
        "modalities": record.modalities or [],
        "quality": record.quality,
        "operator": record.operator,
        "storage_bytes": record.storage_bytes,
        "latest_version_id": record.latest_version_id,
        "created_at": _iso_utc(record.created_at),
        "updated_at": _iso_utc(record.updated_at),
        "latest_version": version_payload(latest),
    }
