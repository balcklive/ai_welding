"""FastAPI 公共依赖（Task 5）。

- `get_current_user`：从 `Authorization: Bearer <token>` 解出当前登录用户；
  任何失败（缺头 / 非 Bearer / token 无效 / 用户不存在）→ `HTTPException(401, "未登录或令牌失效")`，
  由 `main.py` 的全局 HTTPException 处理器兜底为统一信封 `err(40100, ...)`。
"""

from fastapi import Depends, Header, HTTPException
from sqlmodel import Session, select

from app.core.db import get_session
from app.core.security import decode_token
from app.models.data import AuditLog, DataRecord, User

def _unauthorized() -> HTTPException:
    return HTTPException(status_code=401, detail="未登录或令牌失效")


def get_current_user(
    session: Session = Depends(get_session),
    authorization: str | None = Header(default=None),
) -> User:
    """解析 Bearer token → 查库 → 返回 `User`；失败统一 401。"""
    token = _extract_bearer_token(authorization)
    if token is None:
        raise _unauthorized()
    try:
        user_id = decode_token(token)
    except Exception:  # noqa: BLE001 - 签名/过期/格式错误统一视为未登录
        raise _unauthorized() from None
    user = session.get(User, user_id)
    if user is None:
        raise _unauthorized()
    return user


def _extract_bearer_token(authorization: str | None) -> str | None:
    """从 Authorization 头取出 token；非 `Bearer <token>` 返回 None。"""
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token


def is_admin(user: User) -> bool:
    return (user.role or "").lower() == "admin"


def owned_weld_ids(session: Session, user: User) -> list[str] | None:
    if is_admin(user):
        return None
    return list(
        session.exec(
            select(AuditLog.resource_id)
            .where(
                AuditLog.user_id == user.id,
                AuditLog.action == "create",
                AuditLog.resource_type == "weld",
                AuditLog.resource_id.is_not(None),
            )
            .order_by(AuditLog.id)
        ).all()
    )


def owner_user_id_for_record(session: Session, record: DataRecord) -> int | None:
    return session.exec(
        select(AuditLog.user_id)
        .where(
            AuditLog.action == "create",
            AuditLog.resource_type == "weld",
            AuditLog.resource_id == record.weld_id,
            AuditLog.user_id.is_not(None),
        )
        .order_by(AuditLog.id)
    ).first()


def can_access_record(session: Session, user: User, record: DataRecord) -> bool:
    if is_admin(user):
        return True
    owner_user_id = owner_user_id_for_record(session, record)
    return owner_user_id == user.id


def forbid_unless_record_owned(session: Session, user: User, record: DataRecord) -> None:
    if can_access_record(session, user, record):
        return
    raise HTTPException(status_code=403, detail="无权限")
