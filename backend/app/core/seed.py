"""启动初始化：仅创建必要的系统账号和标签字典，不创建业务演示数据。"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlmodel import Session, select

from app.core.config import settings
from app.core.security import hash_password
from app.models.analysis import LabelCategory
from app.models.data import User

LABEL_CATEGORIES: tuple[tuple[str, str], ...] = (
    ("焊瘤", "#d16f69"), ("气孔", "#d69b4b"), ("未熔合", "#5b8def"),
    ("咬边", "#9b78c8"), ("正常", "#58a889"),
)


def seed_admin(session: Session) -> None:
    if session.exec(select(User).where(User.username == settings.admin_username)).first():
        return
    session.add(User(
        username=settings.admin_username,
        password_hash=hash_password(settings.admin_password),
        display_name="系统管理员", role="admin",
        created_at=datetime.now(timezone.utc),
    ))


def seed_reference_data(session: Session) -> None:
    for name, color in LABEL_CATEGORIES:
        if session.exec(select(LabelCategory).where(LabelCategory.name == name)).first() is None:
            session.add(LabelCategory(name=name, color=color))


def seed_all(session: Session, *, demo: bool | None = None) -> None:
    """幂等初始化系统基础数据；业务数据必须来自正式上传和任务流程。

    ``demo`` 参数保留用于兼容旧启动入口，但生产 seed 永不创建业务演示数据。
    """
    seed_admin(session)
    seed_reference_data(session)
    session.commit()
