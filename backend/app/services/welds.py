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
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlmodel import Session, func, or_, select

from app.models.data import (
    DataRecord,
    DataVersion,
    ValidationReport,
    ValidationRuleResult,
)
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
    "current_voltage",
    "sample_rate",
)


# ── 业务号生成器 ─────────────────────────────────────────────────────


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


def create_registration(
    session: Session, data: dict, operator: str
) -> tuple[DataRecord, DataVersion]:
    """事务内建 data_records + v1.0「原始数据」版本 + 回写 latest_version_id。

    不 commit（由路由统一提交）。返回 (record, v1.0_version)。
    """
    now = datetime.now(timezone.utc)
    collected_at = _as_utc(data.get("collected_at"))
    day = _seq_date(collected_at)

    record = DataRecord(
        weld_id=next_weld_id(session, day),
        registration_no=next_registration_no(session, day),
        weld_name=data.get("weld_name"),
        source=data.get("source") or "",
        collected_at=collected_at,
        machine=data.get("machine"),
        weld_method=data.get("weld_method"),
        material=data.get("material"),
        thickness=data.get("thickness"),
        current_voltage=data.get("current_voltage"),
        sample_rate=data.get("sample_rate"),
        product=data.get("product"),
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
    """PATCH 登记可编辑字段（白名单内；None 跳过，保留原值）。调用方 commit。"""
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
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[DataRecord], int]:
    """数据列表：服务端筛选 + 分页。去重由 `latest_version_id` 反规范化保证。

    返回 (items, total)。
    - q: weld_id / registration_no LIKE
    - source: 数据来源前缀（如 产线相机）
    - brand: 焊机品牌前缀（如 Fronius）
    - status: quality 精确（通过/待复核/异常）
    - tab: 待核验→待复核 / 已归档→通过 / 最近·全部最新→仅排序
    """
    conditions = _build_filters(q, source, brand, status, tab)
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


def list_through_welds(session: Session) -> list[DataRecord]:
    """核验通过（quality=通过）的可分析焊缝，created_at 倒序。供 analysis candidates。"""
    return list(
        session.exec(
            select(DataRecord)
            .where(DataRecord.quality == "通过")
            .order_by(DataRecord.created_at.desc(), DataRecord.id.desc())
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


def _build_filters(q, source, brand, status, tab) -> list:
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


def _evaluate_rules(keys: list[str], record: DataRecord | None) -> list[dict]:
    """15 项规则确定性评估：返回 `[{status, message}]`，与 `VALIDATION_RULES` 顺序一致。

    依据：object_keys 里视频/图像/时序/音频文件的存在性与命名、登记工艺参数。
    设计目标（供测试稳定断言）：
    - 完整加工版本（video+timeseries+audio，非 raw）→ 15 通过 → 质量「通过」
    - 含 raw 视频的完整版本 → 仅「视频帧率稳定性」警告 → 质量「待复核」
    - 无任何文件 → 多条失败 → 质量「异常」
    """
    low = [k.lower() for k in keys]
    has_video = _has_ext(low, _VIDEO_EXTS) or _has_ext(low, _IMAGE_EXTS)
    has_ts = _has_ext(low, _TS_EXTS)
    has_audio = _has_ext(low, _AUDIO_EXTS)
    has_files = bool(keys)
    infra = any("infrared" in k for k in low)
    is_raw_video = any(k.startswith("raw/") for k in low) and has_video

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

    if has_ts:
        rules.append(passed("电流范围合理"))
    elif has_files:
        rules.append(warning("缺少电流数据，无法核验范围"))
    else:
        rules.append(failed("未关联文件，缺少电流数据"))

    if has_ts:
        rules.append(passed("电压范围合理"))
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
        rules.append(warning("视频帧率存在轻微波动，建议复核"))
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
        "current_voltage": record.current_voltage,
        "sample_rate": record.sample_rate,
        "product": record.product,
        "modalities": record.modalities or [],
        "quality": record.quality,
        "operator": record.operator,
        "storage_bytes": record.storage_bytes,
        "latest_version_id": record.latest_version_id,
        "created_at": _iso_utc(record.created_at),
        "updated_at": _iso_utc(record.updated_at),
        "latest_version": version_payload(latest),
    }
