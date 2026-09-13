"""启动初始化：仅创建必要的系统账号和标签字典，不创建业务演示数据。"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlmodel import Session, select

from app.core.config import settings
from app.core.security import hash_password
from app.models.analysis import LabelCategory
from app.models.data import User
from app.models.settings import OptionItem

LABEL_CATEGORIES: tuple[tuple[str, str], ...] = (
    ("焊瘤", "#d16f69"), ("气孔", "#d69b4b"), ("未熔合", "#5b8def"),
    ("咬边", "#9b78c8"), ("正常", "#58a889"), ("熔池", "#f032e6"),
)

#: 录入类可选项的出厂默认值（2026-09 系统设置字典化前，这些值硬编码在前端）。
#: 仅作首次初始化：管理员在「系统设置」页的增删改都会留在库里，seed 不覆盖已存在项。
#: - machine / weld_method 对齐登记页原下拉；dataset_task 对齐原写死的「目标检测」等三选；
#: - source 取系统内既有登记示例；product 无既有取值，留空由管理员按项目维护。
DEFAULT_OPTION_ITEMS: tuple[tuple[str, str], ...] = (
    ("machine", "Fronius CMT"),
    ("machine", "OTC FD-V8"),
    ("machine", "Panasonic YD-500"),
    ("weld_method", "MAG焊"),
    ("weld_method", "MIG焊"),
    ("weld_method", "TIG焊"),
    ("source", "产线相机 · 03号"),
    ("source", "实训线 · 02号"),
    ("source", "实训线 · 01号"),
    ("dataset_task", "目标检测"),
    ("dataset_task", "语义分割"),
    ("dataset_task", "多模态回归"),
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
    for index, (name, color) in enumerate(LABEL_CATEGORIES):
        if session.exec(select(LabelCategory).where(LabelCategory.name == name)).first() is None:
            session.add(LabelCategory(name=name, color=color, sort_order=(index + 1) * 10, active=True))
    # 选项字典：同组内按出厂顺序 append（已有项不覆盖，保留管理员改动）。
    counters: dict[str, int] = {}
    for group_key, value in DEFAULT_OPTION_ITEMS:
        counters[group_key] = counters.get(group_key, 0) + 10
        exists = session.exec(
            select(OptionItem).where(
                OptionItem.group_key == group_key, OptionItem.value == value
            )
        ).first()
        if exists is None:
            session.add(
                OptionItem(
                    group_key=group_key,
                    value=value,
                    sort_order=counters[group_key],
                    active=True,
                )
            )


def seed_all(session: Session, *, demo: bool | None = None) -> None:
    """幂等初始化系统基础数据；业务数据必须来自正式上传和任务流程。

    ``demo`` 参数保留用于兼容旧启动入口，但生产 seed 永不创建业务演示数据。
    """
    seed_admin(session)
    seed_reference_data(session)
    session.commit()
