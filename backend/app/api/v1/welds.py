"""welds 域路由（Task 10）：焊缝数据列表 / 登记 / 版本 / 核验。

端点契约见 `docs/API接口清单.md` §3.3，全部需登录（router 级 `Depends(get_current_user)`），
返回统一 `ok(...)` / `err(...)` 信封；业务逻辑在 `app.services.welds`。
`/api/v1` 前缀由 main.py 挂载时统一添加，本 router 自身不带前缀（路径写完整相对路径）。

错误码约定（与既有域一致）：40401=焊缝/登记不存在、40402=版本不存在、
40403=该版本尚未核验、40900=冲突、**40901=CSV 已存在导入任务**（前端据此按"已挂载成功"继续，
而不是把重试当失败卡住，见 T4.4）、40000=参数错误。
"""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlmodel import Session, select

from app.api.deps import forbid_unless_record_owned, get_current_user, owned_weld_ids
from app.core.audit import write_audit
from app.core.db import get_session
from app.models.analysis import SignalIngest
from app.models.data import DataRecord, User
from app.models.datasets import Dataset
from app.models.jobs import Job
from app.schemas.common import err, ok, paginate
from app.services import welds as svc
from app.services import settings as settings_svc
from app.services.signal_ingest import _parse_fs
from app.services import datasets as dataset_svc
from app.services.datasets import collect_record_references
from app.services.welds import normalize_number, parse_current_voltage
from app.services.jobs import create_job
from app.storage import get_storage

router = APIRouter(dependencies=[Depends(get_current_user)])

#: 新建版本允许的加工动作（API 契约 §3.3）。
VALID_ACTIONS = {"去噪处理", "人工修正"}

#: T4.4：`CSV 已存在导入任务` 用**独立错误码**——前端据此判定"这次挂载其实已经成功了"，
#: 继续进入导入态，而不是把重试当失败卡住（用中文文案匹配太脆）。
CSV_INGEST_CONFLICT = 40901

#: 采集时间的未来容差：前端提交的是**本地墙钟**（`datetime-local`），后端按 UTC 存（`_as_utc`
#: 的历史口径），UTC+8 用户当天的默认值天生比 UTC 早 8 小时，所以按 1 天判"未来"——足以挡住
#: 2030 这类明显误填，又不会把正常的本地时间判非法。
_COLLECTED_AT_TOLERANCE = timedelta(days=1)


# ── T4.2 校验器（新建 / 编辑共用同一套，防"只堵一条路"）────────────────


def _checked_number(field: str, value: str | None) -> str | None:
    """板材厚度 / 送丝速度 / 焊接速度：剥单位 + 量程（越界 → `ValueError` → 422 字段级错误）。"""
    return None if value is None else normalize_number(field, value)


def _checked_sample_rate(value: str | None) -> str | None:
    """采样频率：必须能被 `_parse_fs` 解析出 Hz（`10 kHz` / `1000` / `20K` 都可以）。"""
    if value is None:
        return None
    if _parse_fs(value) is None:
        raise ValueError("采样频率需形如 10 kHz / 1000 / 20K")
    return value


def _checked_collected_at(value: datetime | None) -> datetime | None:
    """采集时间：不晚于当前时间（容差见 `_COLLECTED_AT_TOLERANCE`）。"""
    if value is None:
        return None
    moment = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if moment > datetime.now(timezone.utc) + _COLLECTED_AT_TOLERANCE:
        raise ValueError("采集时间不能晚于当前时间")
    return value


#: 必须落在系统设置字典里的登记字段：请求体字段名 → (option_items.group_key, 界面名)。
DICTIONARY_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("machine", "machine", "焊机型号"),
    ("weld_method", "weld_method", "焊接方法"),
)


def _dictionary_violation(
    session: Session, data: dict, current: DataRecord | None = None
) -> dict | None:
    """焊机型号 / 焊接方法 必须是系统设置里**启用中**的项（T4.2「字典必选」，R6 补的这道闸）。

    编辑存量数据时放行"与当前值相同"的情况：选项可能在数据登记后被停用或改名，不该因此让这条
    数据改不动（前端 `withCurrent` 也是同一口径）。
    """
    for field, group, label in DICTIONARY_FIELDS:
        value = data.get(field)
        if not value:
            continue
        if current is not None and value == getattr(current, field):
            continue
        if value not in settings_svc.list_active_values(session, group):
            return err(
                40000,
                f"{label}「{value}」不在系统设置的候选里，请先在「系统设置」中添加",
                status=400,
            )
    return None


def _resolve_current_voltage(body: BaseModel) -> tuple[float | None, float | None]:
    """请求体 → `(current_a, voltage_v)`：新列优先；只给旧列时按 `180 A / 22 V` 解析一次。

    与 `services.welds._resolve_current_voltage`（落库用）同一口径，只是入参是模型而非 dict。
    """
    current, voltage = body.current_a, body.voltage_v
    if current is not None or voltage is not None:
        return current, voltage
    parsed = parse_current_voltage(body.current_voltage)
    return (
        float(parsed[0]) if parsed[0] is not None else None,
        float(parsed[1]) if parsed[1] is not None else None,
    )


def _checked_legacy_current_voltage(value: str | None, info: ValidationInfo) -> str | None:
    """D7 兼容：老客户端只给 `current_voltage` 时，**必须能解析且与新列同一套量程**——
    不能靠旧字段绕过 `current_a` / `voltage_v` 的 Pydantic 约束（R6）。给了新列就丢弃旧值。
    """
    if not value:
        return None
    if info.data.get("current_a") is not None or info.data.get("voltage_v") is not None:
        return None
    current, voltage = parse_current_voltage(value)
    if current is None and voltage is None:
        raise ValueError("需形如 180 A / 22 V")
    if current is not None and not 1 <= current <= 2000:
        raise ValueError("电流需在 1–2000 A 之间")
    if voltage is not None and not 1 <= voltage <= 200:
        raise ValueError("电压需在 1–200 V 之间")
    return value


class RegistrationCreate(BaseModel):
    """新建登记请求体（T4.2：按建模所需完整集**强校验**，防绕过前端）。

    必填：`dataset_id` / `source` / `collected_at` / `weld_name` / `machine` / `weld_method` /
    `material` / `thickness` / `current_a` / `voltage_v` / `sample_rate`；
    选填：`product` / `wire_feed_speed` / `welding_speed`。

    量程（与前端即时校验同一套）：电流 1–2000 A、电压 1–200 V、板材厚度 0.1–200 mm（接受
    `6mm` 这类带单位的存量写法，落库前统一成裸数字）、送丝 0–50 m/min、焊接 0–5000 mm/min。
    校验失败 → 422 + `detail.errors()`（字段路径），由前端 T3.1 的错误态翻译成字段级中文提示。
    """

    model_config = ConfigDict(extra="forbid")

    dataset_id: int
    source: str = Field(min_length=2, max_length=64)
    collected_at: datetime
    weld_name: str = Field(min_length=2, max_length=64)
    machine: str = Field(min_length=1, max_length=64)
    weld_method: str = Field(min_length=1, max_length=32)
    material: str = Field(min_length=1, max_length=32)
    thickness: str = Field(min_length=1, max_length=32)
    #: 必填，但**声明成可选**：老客户端（蓝绿切换期）只给 `current_voltage`，两条路都由
    #: `_require_current_and_voltage` 统一判"必须能解析出两个值"（必填语义不放松）。
    current_a: float | None = Field(default=None, ge=1, le=2000)
    voltage_v: float | None = Field(default=None, ge=1, le=200)
    sample_rate: str = Field(min_length=1, max_length=32)
    product: str | None = Field(default=None, max_length=128)
    wire_feed_speed: str | None = Field(default=None, max_length=32)
    welding_speed: str | None = Field(default=None, max_length=32)
    #: 旧字段：仅作**兼容**——给了新列就不再读它；只给旧值时按 `180 A / 22 V` 解析进新列。
    current_voltage: str | None = Field(default=None, max_length=32)

    _check_thickness = field_validator("thickness")(lambda cls, value: _checked_number("thickness", value))
    _check_wire_feed_speed = field_validator("wire_feed_speed")(lambda cls, value: _checked_number("wire_feed_speed", value))
    _check_welding_speed = field_validator("welding_speed")(lambda cls, value: _checked_number("welding_speed", value))
    _check_sample_rate = field_validator("sample_rate")(lambda cls, value: _checked_sample_rate(value))
    _check_collected_at = field_validator("collected_at")(lambda cls, value: _checked_collected_at(value))
    _check_current_voltage = field_validator("current_voltage")(lambda cls, value, info: _checked_legacy_current_voltage(value, info))

    @model_validator(mode="after")
    def _require_current_and_voltage(self) -> "RegistrationCreate":
        """T4.2：电流 / 电压必填——新客户端给 `current_a` / `voltage_v`，老客户端给 `current_voltage`
        （`180 A / 22 V` 形态），两条路都必须解析出**两个值**才算齐（必填语义不因兼容而放松）。
        """
        current, voltage = _resolve_current_voltage(self)
        if current is None:
            raise ValueError("电流为必填项（1–2000 A）")
        if voltage is None:
            raise ValueError("电压为必填项（1–200 V）")
        return self


class RegistrationUpdate(BaseModel):
    """编辑登记信息（PATCH 语义：只改给出的字段）；`dataset_id` 用于把数据移到另一数据集。

    字段量程与新建一致（给出时才校验）；`current_voltage` 旧字段**不再可写**（D7：写入只写新列），
    仅在请求里给出且未给新列时用于解析回填。
    """

    dataset_id: int | None = None
    source: str | None = Field(default=None, min_length=2, max_length=64)
    collected_at: datetime | None = None
    weld_name: str | None = Field(default=None, min_length=2, max_length=64)
    product: str | None = Field(default=None, max_length=128)
    machine: str | None = Field(default=None, min_length=1, max_length=64)
    weld_method: str | None = Field(default=None, min_length=1, max_length=32)
    material: str | None = Field(default=None, min_length=1, max_length=32)
    thickness: str | None = Field(default=None, min_length=1, max_length=32)
    current_a: float | None = Field(default=None, ge=1, le=2000)
    voltage_v: float | None = Field(default=None, ge=1, le=200)
    sample_rate: str | None = Field(default=None, min_length=1, max_length=32)
    wire_feed_speed: str | None = Field(default=None, max_length=32)
    welding_speed: str | None = Field(default=None, max_length=32)
    current_voltage: str | None = Field(default=None, max_length=32)

    _check_thickness = field_validator("thickness")(lambda cls, value: _checked_number("thickness", value))
    _check_wire_feed_speed = field_validator("wire_feed_speed")(lambda cls, value: _checked_number("wire_feed_speed", value))
    _check_welding_speed = field_validator("welding_speed")(lambda cls, value: _checked_number("welding_speed", value))
    _check_sample_rate = field_validator("sample_rate")(lambda cls, value: _checked_sample_rate(value))
    _check_collected_at = field_validator("collected_at")(lambda cls, value: _checked_collected_at(value))
    _check_current_voltage = field_validator("current_voltage")(lambda cls, value, info: _checked_legacy_current_voltage(value, info))


class RawFilesRequest(BaseModel):
    """原始文件挂载请求体（§3.3 POST …/raw-files）。`storage_bytes` 缺省 0。"""

    object_keys: list[str]
    storage_bytes: int = 0


class VersionCreate(BaseModel):
    """新建数据版本请求体（§3.3 POST /welds/{weld_id}/versions）。"""

    action: str
    note: str | None = None
    object_keys: list[str] | None = None


def _operator(user: User) -> str:
    """服务端取当前登录用户作 operator（优先展示名，对齐 seed 林工）。"""
    return user.display_name or user.username


def _is_safe_object_key(value: str) -> bool:
    value = value.strip()
    if not value or value.startswith("/") or "\\" in value:
        return False
    parts = value.split("/")
    return all(part not in {"", ".", ".."} for part in parts)


def _is_retryable_write_error(exc: Exception) -> bool:
    if isinstance(exc, IntegrityError):
        return True
    if isinstance(exc, OperationalError):
        return "locked" in str(exc).lower()
    return False



def _stat_new_object_keys(version, object_keys: list[str]) -> tuple[list[str], int] | str:
    existing = set(version.object_keys or [])
    new_keys = []
    total = 0
    storage = get_storage()
    for key in object_keys:
        if not _is_safe_object_key(key):
            return f"object_key 非法: {key}"
        if key in existing or key in new_keys:
            continue
        try:
            size = int(storage.stat_object(key))
        except Exception:
            return f"对象不存在或不可访问: {key}"
        if size <= 0:
            return f"对象大小非法: {key}"
        new_keys.append(key)
        total += size
    return new_keys, total


# ── 列表 / 详情 ──────────────────────────────────────────────────────


@router.get("/welds")
def list_welds(
    q: str | None = None,
    source: str | None = None,
    brand: str | None = None,
    status: str | None = None,
    tab: str | None = None,
    dataset_id: int | None = Query(None, ge=1),
    page: int = 1,
    page_size: int = 20,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """数据列表：服务端筛选 + 分页，按焊缝 ID 去重、仅最新版本（§3.3）。

    `dataset_id`：归属数据集精确筛选（分析与标注「选择数据」两级选择的第二级范围）。
    """
    page = max(1, page)
    page_size = max(1, min(page_size, 100))
    if dataset_id is not None and session.get(Dataset, dataset_id) is None:
        return err(40401, "数据集不存在", status=404)
    items, total = svc.list_welds(
        session,
        q=q,
        source=source,
        brand=brand,
        status=status,
        tab=tab,
        dataset_id=dataset_id,
        page=page,
        page_size=page_size,
        weld_ids=owned_weld_ids(session, current_user),
    )
    return ok(paginate(svc.records_payload(session, items), total, page, page_size))


@router.get("/welds/{weld_id}")
def get_weld(
    weld_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """单条焊缝详情（含最新版本信息）。"""
    record = svc.get_record_by_weld_id(session, weld_id)
    if record is None:
        return err(40401, "焊缝不存在", status=404)
    forbid_unless_record_owned(session, current_user, record)
    return ok(svc.record_payload(session, record))


@router.get("/welds/{weld_id}/delete-impact")
def get_weld_delete_impact(
    weld_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """删除前的影响范围预检（T7）：与 `DELETE /welds/{id}` 共用同一份引用采集。"""
    record = svc.get_record_by_weld_id(session, weld_id)
    if record is None:
        return err(40401, "焊缝不存在", status=404)
    forbid_unless_record_owned(session, current_user, record)
    return ok(collect_record_references(session, record).payload())


@router.delete("/welds/{weld_id}")
def delete_weld(
    weld_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """删除单条焊缝及其版本产物；已进入切分/标注/固定快照时拒绝删除。"""
    record = svc.get_record_by_weld_id(session, weld_id)
    if record is None:
        return err(40401, "焊缝不存在", status=404)
    forbid_unless_record_owned(session, current_user, record)
    try:
        result = svc.delete_record(session, record)
    except svc.WeldDeleteConflict as exc:
        return err(40900, str(exc), status=409)
    write_audit(
        session,
        current_user.id,
        "delete",
        "weld",
        weld_id,
        {"registration_no": record.registration_no, **result},
    )
    session.commit()
    return ok({"deleted": True, **result})


# ── 登记 ─────────────────────────────────────────────────────────────


@router.post("/registrations")
def create_registration(
    body: RegistrationCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """新建数据登记：事务内生成 WLD-/REG- 编号 + v1.0 原始数据版本 + 审计。"""
    source = (body.source or "").strip()
    if not source:
        return err(40000, "数据来源不能为空", status=400)
    if session.get(Dataset, body.dataset_id) is None:
        return err(40401, "所属数据集不存在", status=404)
    payload = body.model_dump()
    violation = _dictionary_violation(session, payload)
    if violation is not None:
        return violation
    for attempt in range(3):
        request_lock = None
        day_lock = None
        try:
            request_lock = svc._acquire_registration_payload_lock(
                session, payload, _operator(current_user)
            )
            day_lock = svc._acquire_registration_lock(
                session,
                svc._seq_date(svc._as_utc(payload.get("collected_at"))),
            )
            record, _version = svc.create_registration(
                session, payload, _operator(current_user)
            )
            write_audit(
                session,
                current_user.id,
                "create",
                "weld",
                record.weld_id,
                {"registration_no": record.registration_no, "action": "登记原始数据"},
            )
            session.commit()
            return ok(svc.record_payload(session, record))
        except RuntimeError as exc:
            session.rollback()
            return err(40900, str(exc), status=409)
        except (IntegrityError, OperationalError) as exc:
            session.rollback()
            if attempt < 2 and _is_retryable_write_error(exc):
                continue
            if isinstance(exc, IntegrityError):
                return err(40900, "登记编号冲突，请重试", status=409)
            raise
        finally:
            try:
                svc._release_registration_lock(session, day_lock)
            except Exception:
                pass
            try:
                svc._release_registration_payload_lock(session, request_lock)
            except Exception:
                pass
    return err(40900, "登记编号冲突，请重试", status=409)


@router.get("/registrations/{registration_id}")
def get_registration(
    registration_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """登记信息详情（兼容 DB id / registration_no / weld_id 标识）。"""
    record = svc.get_record_by_identifier(session, registration_id)
    if record is None:
        return err(40401, "登记信息不存在", status=404)
    forbid_unless_record_owned(session, current_user, record)
    return ok(svc.record_payload(session, record))


@router.patch("/registrations/{registration_id}")
def update_registration(
    registration_id: str,
    body: RegistrationUpdate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """编辑登记信息（部分字段）+ 审计。"""
    record = svc.get_record_by_identifier(session, registration_id)
    if record is None:
        return err(40401, "登记信息不存在", status=404)
    forbid_unless_record_owned(session, current_user, record)
    changes = body.model_dump(exclude_unset=True)
    if "dataset_id" in changes and session.get(Dataset, changes["dataset_id"]) is None:
        return err(40401, "所属数据集不存在", status=404)
    violation = _dictionary_violation(session, changes, record)
    if violation is not None:
        return violation
    svc.update_registration(session, record, changes)
    write_audit(
        session,
        current_user.id,
        "update",
        "weld",
        record.weld_id,
        {"registration_no": record.registration_no},
    )
    session.commit()
    return ok(svc.record_payload(session, record))


@router.post("/registrations/{registration_id}/raw-files")
def attach_raw_files(
    registration_id: str,
    body: RawFilesRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """挂载登记原始文件到 v1.0 版本（去重追加 object_keys + 累加 storage_bytes）+ 审计。"""
    record = svc.get_record_by_identifier(session, registration_id)
    if record is None:
        return err(40401, "登记信息不存在", status=404)
    forbid_unless_record_owned(session, current_user, record)
    if not body.object_keys:
        return err(40000, "object_keys 不能为空", status=400)
    csv_keys = []
    seen_csv_keys: set[str] = set()
    for key in body.object_keys:
        key = (key or "").strip()
        if key.lower().endswith(".csv") and key not in seen_csv_keys:
            seen_csv_keys.add(key)
            csv_keys.append(key)

    auto_build: dict | None = None
    for attempt in range(3):
        version = svc.get_v10_version(session, record.id)
        if version is None:
            return err(40402, "v1.0 原始数据版本不存在", status=404)
        request_lock = None
        try:
            if csv_keys:
                request_lock = svc._acquire_raw_files_payload_lock(
                    session, version.id, csv_keys
                )
                existing = set(
                    session.exec(
                        select(SignalIngest.source_object_key).where(
                            SignalIngest.version_id == version.id
                        )
                    ).all()
                )
                if any(key in existing for key in csv_keys):
                    return err(CSV_INGEST_CONFLICT, "CSV 已存在导入任务", status=409)
            statted = _stat_new_object_keys(version, body.object_keys)
            if isinstance(statted, str):
                return err(40000, statted, status=400)
            new_object_keys, storage_bytes = statted
            existing_csv_keys = {key for key in csv_keys if key not in set(new_object_keys)}
            if existing_csv_keys:
                existing = set(
                    session.exec(
                        select(SignalIngest.source_object_key).where(
                            SignalIngest.version_id == version.id
                        )
                    ).all()
                )
                if any(key in existing for key in existing_csv_keys):
                    return err(CSV_INGEST_CONFLICT, "CSV 已存在导入任务", status=409)
            svc.attach_raw_files(
                session, record, version, new_object_keys, storage_bytes
            )
            write_audit(
                session,
                current_user.id,
                "update",
                "weld",
                record.weld_id,
                {"action": "关联原始文件", "count": len(new_object_keys), "requested_count": len(body.object_keys)},
            )
            # 自动触发信号导入（Task 18）：本次挂载含 .csv 键时，为每个**新** CSV 建
            # signal_ingest Job + SignalIngest(pending)（同一事务）。`signal_ingests`
            # 表对 (version_id, source_object_key) 唯一约束兜底并发重复挂载。
            if csv_keys:
                existing = set(
                    session.exec(
                        select(SignalIngest.source_object_key).where(
                            SignalIngest.version_id == version.id
                        )
                    ).all()
                )
                if any(key in existing for key in csv_keys):
                    return err(CSV_INGEST_CONFLICT, "CSV 已存在导入任务", status=409)
                for key in csv_keys:
                    if key in existing:
                        continue
                    job = create_job(
                        session,
                        "signal_ingest",
                        result={"version_id": version.id, "source_object_key": key},
                    )
                    session.add(
                        SignalIngest(
                            job_id=job.id,
                            version_id=version.id,
                            source_object_key=key,
                            status="pending",
                            created_at=datetime.now(timezone.utc),
                        )
                    )
            # 视频可播性预处理：本次挂载含**新**视频 key 时为每个建 media_prep Job
            # （探测编码 → 非浏览器友好（如 mpeg4）则转 H.264+faststart 预览版，
            # 写 processed/{weld_id}/video/；已是 h264+faststart 直接标记免转）。
            # 同 key 已有 pending/running/succeeded 的 media_prep job 则不重复建。
            video_keys = [
                key
                for key in new_object_keys
                if key.lower().endswith(svc._VIDEO_EXTS + (".webm",))
            ]
            if video_keys:
                existing_prep = {
                    (prep.result or {}).get("object_key")
                    for prep in session.exec(
                        select(Job).where(
                            Job.type == "media_prep",
                            Job.status.in_(["pending", "running", "succeeded"]),
                        )
                    ).all()
                }
                for key in video_keys:
                    if key in existing_prep:
                        continue
                    create_job(
                        session,
                        "media_prep",
                        result={
                            "weld_id": record.weld_id,
                            "version_id": version.id,
                            "object_key": key,
                        },
                    )
            # 原始文件真正挂载成功后，数据才算进入数据集；此时自动生成新的数据集快照。
            # 仅在本次确实挂载了新文件时触发，避免重复上传产生空版本。
            if new_object_keys:
                dataset = session.get(Dataset, record.dataset_id)
                if dataset is not None:
                    auto_version, auto_job = dataset_svc.create_auto_build_task(session, dataset)
                    auto_build = {
                        "dataset_version_id": auto_version.id,
                        "version_no": auto_version.version_no,
                        "job_id": auto_job.job_uid,
                    }
            session.commit()
            payload = svc.version_payload(version)
            # T8：挂载响应带出自动构建任务——否则前端拿不到 job_id，既没法轮询、刷新后也无从恢复
            # （数据版本自身的构建状态由 `GET /datasets/{id}/versions` 的 build_status 提供）。
            if auto_build is not None:
                payload["dataset_build"] = auto_build
            return ok(payload)
        except RuntimeError as exc:
            session.rollback()
            return err(40900, str(exc), status=409)
        except (IntegrityError, OperationalError) as exc:
            session.rollback()
            if attempt < 2 and _is_retryable_write_error(exc):
                continue
            version = svc.get_v10_version(session, record.id)
            if version is not None and csv_keys:
                existing = set(
                    session.exec(
                        select(SignalIngest.source_object_key).where(
                            SignalIngest.version_id == version.id
                        )
                    ).all()
                )
                if any(key in existing for key in csv_keys):
                    return err(CSV_INGEST_CONFLICT, "CSV 已存在导入任务", status=409)
            if isinstance(exc, IntegrityError):
                return err(CSV_INGEST_CONFLICT, "CSV 已存在导入任务", status=409)
            raise
        finally:
            try:
                svc._release_raw_files_payload_lock(session, request_lock)
            except Exception:
                pass

    return err(CSV_INGEST_CONFLICT, "CSV 已存在导入任务", status=409)


# ── T4.4：登记 → 上传 → 挂载 → 导入的状态与恢复 ───────────────────────


def _ingest_state(session: Session, record: DataRecord) -> dict:
    """登记链路状态：**全部由已有数据推导**（不新增表），刷新/换设备后看到的都一样。

    判据（与方案 §T4.4 表格一致）：
    - `awaiting_upload`：记录已建，但 v1.0 的 `object_keys` 为空（文件还没挂上）；
    - `importing`：已挂载文件，且有 `signal_ingests` 行还在 `pending`/`running`；
    - `failed`：有 `signal_ingests` 行 `failed`；
    - `ready`：全部导入成功，或本次没有 CSV 需要导入。
    """
    version = svc.get_v10_version(session, record.id)
    keys = list(version.object_keys or []) if version is not None else []
    rows = (
        session.exec(select(SignalIngest).where(SignalIngest.version_id == version.id)).all()
        if version is not None
        else []
    )
    failed = [
        {
            "source_object_key": row.source_object_key,
            "message": (row.error or {}).get("message") if isinstance(row.error, dict) else None,
        }
        for row in rows
        if row.status == "failed"
    ]
    if not keys:
        status = "awaiting_upload"
    elif any(row.status in ("pending", "running") for row in rows):
        status = "importing"
    elif failed:
        status = "failed"
    else:
        status = "ready"
    return {
        "registration_no": record.registration_no,
        "weld_id": record.weld_id,
        "status": status,
        "uploaded_files": len(keys),
        "csv_total": len(rows),
        "csv_failed": failed,
    }


def _record_or_error(session: Session, registration_id: str) -> DataRecord | dict:
    record = svc.get_record_by_identifier(session, registration_id)
    if record is None:
        return err(40401, "登记信息不存在", status=404)
    return record


@router.get("/registrations/{registration_id}/ingest-status")
def get_ingest_status(
    registration_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """登记链路状态（T4.4）：界面显示「等待上传文件 / 导入中 / 可分析 / 导入失败」的唯一依据。

    与"登记成功"是两件事——`POST /registrations` 只代表记录与 v1.0 建好了，
    核验与分析依赖的是**导入完成后的真实信号**。
    """
    record = _record_or_error(session, registration_id)
    if isinstance(record, dict):
        return record
    forbid_unless_record_owned(session, current_user, record)
    return ok(_ingest_state(session, record))


@router.post("/registrations/{registration_id}/reimport")
def reimport_signals(
    registration_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """重新导入**失败**的 CSV（T4.4）：清掉 failed 行与其 Job 后重新入队。

    为什么要专门开一个入口：`signal_ingests` 对 `(version_id, source_object_key)` 唯一，
    失败行也会被挂载接口的 409 拦掉，于是"旧代码解析失败、新代码能解析"的文件会**永远卡住**
    （线上已踩过）。这里让用户能自助恢复，不必删库。
    """
    record = _record_or_error(session, registration_id)
    if isinstance(record, dict):
        return record
    forbid_unless_record_owned(session, current_user, record)
    version = svc.get_v10_version(session, record.id)
    if version is None:
        return err(40402, "v1.0 原始数据版本不存在", status=404)
    failed_rows = session.exec(
        select(SignalIngest).where(
            SignalIngest.version_id == version.id, SignalIngest.status == "failed"
        )
    ).all()
    if not failed_rows:
        return err(40000, "没有导入失败的文件，无需重新导入", status=400)
    for row in failed_rows:
        # 先取出要用的值：`delete` 之后不保证还能读属性
        failed_job_id, source_key = row.job_id, row.source_object_key
        session.delete(row)
        old_job = session.get(Job, failed_job_id)
        if old_job is not None:
            session.delete(old_job)
        session.flush()
        job = create_job(
            session,
            "signal_ingest",
            result={"version_id": version.id, "source_object_key": source_key},
        )
        session.add(
            SignalIngest(
                job_id=job.id,
                version_id=version.id,
                source_object_key=source_key,
                status="pending",
                created_at=datetime.now(timezone.utc),
            )
        )
    write_audit(
        session,
        current_user.id,
        "update",
        "weld",
        record.weld_id,
        {"action": "重新导入信号", "count": len(failed_rows)},
    )
    session.commit()
    return ok(_ingest_state(session, record))


# ── 版本 ─────────────────────────────────────────────────────────────


@router.get("/welds/{weld_id}/versions")
def list_versions(
    weld_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """版本链（v1.0→v1.n，含操作人/时间/动作）。"""
    record = svc.get_record_by_weld_id(session, weld_id)
    if record is None:
        return err(40401, "焊缝不存在", status=404)
    forbid_unless_record_owned(session, current_user, record)
    versions = svc.list_versions(session, record.id)
    return ok([svc.version_payload(v) for v in versions])


@router.get("/welds/{weld_id}/versions/{version_id}")
def get_version(
    weld_id: str,
    version_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """单个版本详情。"""
    record = svc.get_record_by_weld_id(session, weld_id)
    if record is None:
        return err(40401, "焊缝不存在", status=404)
    forbid_unless_record_owned(session, current_user, record)
    version = svc.get_version(session, version_id)
    if version is None or version.record_id != record.id:
        return err(40402, "版本不存在", status=404)
    return ok(svc.version_payload(version))


@router.post("/welds/{weld_id}/versions")
def create_version(
    weld_id: str,
    body: VersionCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """新建数据版本（去噪处理/人工修正），不覆盖旧版 + 更新 latest + 审计。"""
    record = svc.get_record_by_weld_id(session, weld_id)
    if record is None:
        return err(40401, "焊缝不存在", status=404)
    forbid_unless_record_owned(session, current_user, record)
    if body.action not in VALID_ACTIONS:
        return err(40000, "action 需为去噪处理或人工修正", status=400)
    duplicate = svc.find_duplicate_version(
        session, record.id, body.action, body.note, body.object_keys
    )
    if duplicate is not None:
        return err(40900, "重复版本请求：相同 action/note/object_keys 已存在", status=409)
    try:
        version = svc.create_version(
            session,
            record,
            body.action,
            body.note,
            body.object_keys,
            _operator(current_user),
            request_key=svc.version_request_key(body.action, body.note, body.object_keys),
        )
        write_audit(
            session,
            current_user.id,
            "update",
            "weld",
            record.weld_id,
            {"action": body.action, "version_no": version.version_no},
        )
        session.commit()
    except IntegrityError:
        session.rollback()
        duplicate = svc.find_duplicate_version(
            session, record.id, body.action, body.note, body.object_keys
        )
        if duplicate is not None:
            return err(40900, "重复版本请求：相同 action/note/object_keys 已存在", status=409)
        raise
    return ok(svc.version_payload(version))


# ── 核验 ─────────────────────────────────────────────────────────────


@router.post("/welds/{weld_id}/versions/{version_id}/validation")
def run_validation(
    weld_id: str,
    version_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """执行核验（同步 15 项规则）：写报告 + 按规则回写 quality + 审计。"""
    record = svc.get_record_by_weld_id(session, weld_id)
    if record is None:
        return err(40401, "焊缝不存在", status=404)
    forbid_unless_record_owned(session, current_user, record)
    version = svc.get_version(session, version_id)
    if version is None or version.record_id != record.id:
        return err(40402, "版本不存在", status=404)
    report = svc.run_validation(session, record, version)
    write_audit(
        session,
        current_user.id,
        "validate",
        "weld",
        record.weld_id,
        {"version_no": version.version_no, "score": float(report.score)},
    )
    session.commit()
    return ok(svc.validation_payload(session, report))


@router.get("/welds/{weld_id}/versions/{version_id}/validation")
def get_validation(
    weld_id: str,
    version_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """核验明细：报告 + 15 条规则状态与异常原因。"""
    record = svc.get_record_by_weld_id(session, weld_id)
    if record is None:
        return err(40401, "焊缝不存在", status=404)
    forbid_unless_record_owned(session, current_user, record)
    version = svc.get_version(session, version_id)
    if version is None or version.record_id != record.id:
        return err(40402, "版本不存在", status=404)
    report = svc.get_latest_validation(session, version.id)
    if report is None:
        return err(40403, "该版本尚未核验", status=404)
    return ok(svc.validation_payload(session, report))
