"""welds 域路由（Task 10）：焊缝数据列表 / 登记 / 版本 / 核验。

端点契约见 `docs/API接口清单.md` §3.3，全部需登录（router 级 `Depends(get_current_user)`），
返回统一 `ok(...)` / `err(...)` 信封；业务逻辑在 `app.services.welds`。
`/api/v1` 前缀由 main.py 挂载时统一添加，本 router 自身不带前缀（路径写完整相对路径）。

错误码约定（与既有域一致）：40401=焊缝/登记不存在、40402=版本不存在、
40403=该版本尚未核验、40900=冲突、40000=参数错误。
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session, select

from app.api.deps import get_current_user
from app.core.audit import write_audit
from app.core.db import get_session
from app.models.analysis import SignalIngest
from app.models.data import User
from app.schemas.common import err, ok, paginate
from app.services import welds as svc
from app.services.jobs import create_job

router = APIRouter(dependencies=[Depends(get_current_user)])

#: 新建版本允许的加工动作（API 契约 §3.3）。
VALID_ACTIONS = {"去噪处理", "人工修正"}


class RegistrationCreate(BaseModel):
    """新建登记请求体（§3.3 POST /registrations）。`source` 必填，其余可空。"""

    source: str
    collected_at: datetime | None = None
    weld_name: str | None = None
    product: str | None = None
    machine: str | None = None
    weld_method: str | None = None
    material: str | None = None
    thickness: str | None = None
    current_voltage: str | None = None
    sample_rate: str | None = None


class RegistrationUpdate(BaseModel):
    """编辑登记请求体（§3.3 PATCH /registrations/{id}，字段均可选）。"""

    source: str | None = None
    collected_at: datetime | None = None
    weld_name: str | None = None
    product: str | None = None
    machine: str | None = None
    weld_method: str | None = None
    material: str | None = None
    thickness: str | None = None
    current_voltage: str | None = None
    sample_rate: str | None = None


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


# ── 列表 / 详情 ──────────────────────────────────────────────────────


@router.get("/welds")
def list_welds(
    q: str | None = None,
    source: str | None = None,
    brand: str | None = None,
    status: str | None = None,
    tab: str | None = None,
    page: int = 1,
    page_size: int = 20,
    session: Session = Depends(get_session),
) -> dict:
    """数据列表：服务端筛选 + 分页，按焊缝 ID 去重、仅最新版本（§3.3）。"""
    page = max(1, page)
    page_size = max(1, min(page_size, 100))
    items, total = svc.list_welds(
        session,
        q=q,
        source=source,
        brand=brand,
        status=status,
        tab=tab,
        page=page,
        page_size=page_size,
    )
    return ok(paginate(svc.records_payload(session, items), total, page, page_size))


@router.get("/welds/{weld_id}")
def get_weld(weld_id: str, session: Session = Depends(get_session)) -> dict:
    """单条焊缝详情（含最新版本信息）。"""
    record = svc.get_record_by_weld_id(session, weld_id)
    if record is None:
        return err(40401, "焊缝不存在", status=404)
    return ok(svc.record_payload(session, record))


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
    record, _version = svc.create_registration(
        session, body.model_dump(), _operator(current_user)
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


@router.get("/registrations/{registration_id}")
def get_registration(registration_id: str, session: Session = Depends(get_session)) -> dict:
    """登记信息详情（兼容 DB id / registration_no / weld_id 标识）。"""
    record = svc.get_record_by_identifier(session, registration_id)
    if record is None:
        return err(40401, "登记信息不存在", status=404)
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
    svc.update_registration(session, record, body.model_dump(exclude_unset=True))
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
    if not body.object_keys:
        return err(40000, "object_keys 不能为空", status=400)
    version = svc.get_v10_version(session, record.id)
    if version is None:
        return err(40402, "v1.0 原始数据版本不存在", status=404)
    svc.attach_raw_files(
        session, record, version, body.object_keys, body.storage_bytes
    )
    write_audit(
        session,
        current_user.id,
        "update",
        "weld",
        record.weld_id,
        {"action": "关联原始文件", "count": len(body.object_keys)},
    )
    # 自动触发信号导入（Task 18）：本次挂载含 .csv 键时，为每个**新** CSV 建
    # signal_ingest Job + SignalIngest(pending)（同一事务）。`signal_ingests`
    # 表对 (version_id, source_object_key) 唯一约束兜底并发重复挂载。
    csv_keys = [k for k in body.object_keys if k.lower().endswith(".csv")]
    if csv_keys:
        existing = set(
            session.exec(
                select(SignalIngest.source_object_key).where(
                    SignalIngest.version_id == version.id
                )
            ).all()
        )
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
    session.commit()
    return ok(svc.version_payload(version))


# ── 版本 ─────────────────────────────────────────────────────────────


@router.get("/welds/{weld_id}/versions")
def list_versions(weld_id: str, session: Session = Depends(get_session)) -> dict:
    """版本链（v1.0→v1.n，含操作人/时间/动作）。"""
    record = svc.get_record_by_weld_id(session, weld_id)
    if record is None:
        return err(40401, "焊缝不存在", status=404)
    versions = svc.list_versions(session, record.id)
    return ok([svc.version_payload(v) for v in versions])


@router.get("/welds/{weld_id}/versions/{version_id}")
def get_version(
    weld_id: str, version_id: int, session: Session = Depends(get_session)
) -> dict:
    """单个版本详情。"""
    record = svc.get_record_by_weld_id(session, weld_id)
    if record is None:
        return err(40401, "焊缝不存在", status=404)
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
    if body.action not in VALID_ACTIONS:
        return err(40000, "action 需为去噪处理或人工修正", status=400)
    duplicate = svc.find_duplicate_version(
        session, record.id, body.action, body.note, body.object_keys
    )
    if duplicate is not None:
        return err(40900, "重复版本请求：相同 action/note/object_keys 已存在", status=409)
    version = svc.create_version(
        session,
        record,
        body.action,
        body.note,
        body.object_keys,
        _operator(current_user),
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
    weld_id: str, version_id: int, session: Session = Depends(get_session)
) -> dict:
    """核验明细：报告 + 15 条规则状态与异常原因。"""
    record = svc.get_record_by_weld_id(session, weld_id)
    if record is None:
        return err(40401, "焊缝不存在", status=404)
    version = svc.get_version(session, version_id)
    if version is None or version.record_id != record.id:
        return err(40402, "版本不存在", status=404)
    report = svc.get_latest_validation(session, version.id)
    if report is None:
        return err(40403, "该版本尚未核验", status=404)
    return ok(svc.validation_payload(session, report))
