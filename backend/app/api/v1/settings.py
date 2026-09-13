"""settings 域路由：系统设置·可选项字典（2026-09 新增，实现原预留 `GET/PUT /settings` 的字典部分）。

端点（契约见 `docs/API接口清单.md` §3.13）：

- `GET    /settings/options`                       全部选项组 + 选项（含停用项）；
- `POST   /settings/options/{group_key}`           新增选项；
- `PATCH  /settings/options/{group_key}/{item_id}` 改名 / 改色 / 停用 / 启用；
- `POST   /settings/options/{group_key}/{item_id}/move` 上移 / 下移一位；
- `DELETE /settings/options/{group_key}/{item_id}` 删除（被引用则软删为停用）。

鉴权：读=登录即可，写=**仅管理员**（`users.role == 'admin'`）。字典是全局配置，
非管理员改动会影响所有人的录入口径，故写操作收紧。

错误码：40410=选项分组不存在、40411=选项不存在、40900=同组重名、40000=参数错误。
审计：写操作统一 `write_audit(...)` 落 `audit_logs`（与登记/数据集删除同事务提交）。
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session

from app.api.deps import get_current_user, is_admin
from app.core.audit import write_audit
from app.core.db import get_session
from app.models.data import User
from app.schemas.common import err, ok
from app.services import settings as svc

router = APIRouter(dependencies=[Depends(get_current_user)])


class OptionCreate(BaseModel):
    """新增选项请求体；`color` 仅标注类别使用（形如 `#d16f69`）。"""

    value: str
    color: str | None = None


class OptionUpdate(BaseModel):
    """更新选项请求体：三个字段均可选，缺省即不改（PATCH 语义）。"""

    value: str | None = None
    color: str | None = None
    active: bool | None = None


class OptionMove(BaseModel):
    """排序请求体：direction ∈ {up, down}。"""

    direction: str


def _require_admin(user: User) -> None:
    """字典写操作仅管理员；由 main.py 全局处理器兜底为 `err(40300, ...)`。"""
    if not is_admin(user):
        raise HTTPException(status_code=403, detail="仅管理员可修改系统可选项配置")


def _group_payload(session: Session, group_key: str) -> dict:
    """单个分组的完整快照（写操作后回显，前端直接替换本地 state）。"""
    for group in svc.list_groups(session):
        if group["key"] == group_key:
            return group
    return err(40410, "选项分组不存在", status=404)


@router.get("/settings/options")
def list_options(session: Session = Depends(get_session)) -> dict:
    """全部可配置选项组（含停用项）：数据厂家/焊机型号、焊接方法、数据来源、
    产品/项目信息、数据集任务类型、标注缺陷类别。"""
    return ok({"groups": svc.list_groups(session)})


@router.post("/settings/options/{group_key}")
def create_option(
    group_key: str,
    body: OptionCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """新增可选项（同组重名 409）。"""
    _require_admin(current_user)
    try:
        item = svc.create_item(session, group_key, body.value, body.color)
    except svc.OptionGroupNotFound as exc:
        return err(40410, str(exc), status=404)
    except svc.OptionConflict as exc:
        return err(40900, str(exc), status=409)
    write_audit(
        session, current_user.id, "create", "option_item",
        f"{group_key}:{item['value']}",
        {"group_key": group_key, "value": item["value"]},
    )
    session.commit()
    return ok({"item": item, "group": _group_payload(session, group_key)})


@router.patch("/settings/options/{group_key}/{item_id}")
def update_option(
    group_key: str,
    item_id: int,
    body: OptionUpdate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """改名 / 改颜色 / 停用-启用（改名只影响后续录入，历史数据保留原值）。"""
    _require_admin(current_user)
    try:
        item = svc.update_item(
            session,
            group_key,
            item_id,
            value=body.value,
            color=body.color,
            active=body.active,
        )
    except svc.OptionGroupNotFound as exc:
        return err(40410, str(exc), status=404)
    except svc.OptionItemNotFound as exc:
        return err(40411, str(exc), status=404)
    except svc.OptionConflict as exc:
        return err(40900, str(exc), status=409)
    write_audit(
        session, current_user.id, "update", "option_item",
        f"{group_key}:{item['value']}",
        {
            "group_key": group_key,
            "value": item["value"],
            "active": item["active"],
            "changed": body.model_dump(exclude_none=True),
        },
    )
    session.commit()
    return ok({"item": item, "group": _group_payload(session, group_key)})


@router.post("/settings/options/{group_key}/{item_id}/move")
def move_option(
    group_key: str,
    item_id: int,
    body: OptionMove,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """上移 / 下移一位（整组按 10 递增重排 sort_order）。"""
    _require_admin(current_user)
    try:
        items = svc.move_item(session, group_key, item_id, body.direction)
    except svc.OptionGroupNotFound as exc:
        return err(40410, str(exc), status=404)
    except svc.OptionItemNotFound as exc:
        return err(40411, str(exc), status=404)
    write_audit(
        session, current_user.id, "update", "option_item",
        f"{group_key}:{item_id}",
        {"group_key": group_key, "direction": body.direction, "moved": item_id},
    )
    session.commit()
    return ok({"items": items, "group": _group_payload(session, group_key)})


@router.delete("/settings/options/{group_key}/{item_id}")
def delete_option(
    group_key: str,
    item_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """删除可选项：已被业务数据引用 → 软删（停用）；未被引用 → 物理删除。"""
    _require_admin(current_user)
    try:
        result = svc.delete_item(session, group_key, item_id)
    except svc.OptionGroupNotFound as exc:
        return err(40410, str(exc), status=404)
    except svc.OptionItemNotFound as exc:
        return err(40411, str(exc), status=404)
    write_audit(
        session, current_user.id, "delete", "option_item",
        f"{group_key}:{result['value']}",
        {"group_key": group_key, **result},
    )
    session.commit()
    return ok({"deleted": True, "group": _group_payload(session, group_key), **result})
