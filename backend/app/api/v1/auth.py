"""auth 域路由（Task 5）：JWT 认证 + login/me。

- `POST /auth/login`：body `{username, password}` → 校验 users 表 →
  成功 `ok({access_token, token_type:"bearer", user})`；用户名/密码错 → `err(40100, "用户名或密码错误", status=401)`。
- `GET /auth/me`（需登录）：返回当前用户 `ok(user)`。
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session, select

from app.api.deps import get_current_user
from app.core.db import get_session
from app.core.security import create_access_token, verify_password
from app.models.data import User
from app.schemas.common import err, ok

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    """登录请求体。"""

    username: str
    password: str


def user_payload(user: User) -> dict:
    """用户对外暴露的字段（接口契约 §2 User：id/username/display_name/role/avatar）。"""
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "role": user.role,
        "avatar": user.avatar,
    }


@router.post("/login")
def login(body: LoginRequest, session: Session = Depends(get_session)) -> dict:
    """登录：用户名 + 密码校验，成功返回 JWT 与用户信息。"""
    user = session.exec(select(User).where(User.username == body.username)).first()
    if user is None or not verify_password(body.password, user.password_hash):
        return err(40100, "用户名或密码错误", status=401)
    return ok(
        {
            "access_token": create_access_token(user),
            "token_type": "bearer",
            "user": user_payload(user),
        }
    )


@router.get("/me")
def me(current_user: User = Depends(get_current_user)) -> dict:
    """当前登录用户（恢复会话用）。"""
    return ok(user_payload(current_user))
