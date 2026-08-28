"""生产启动初始化测试：只创建管理员和参考字典，不灌入业务演示数据。"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, select

from app.core.config import settings
from app.core.security import verify_password
from app.core.seed import seed_all
from app.models import AnnotationTask, DataRecord, Dataset, LabelCategory, Model, Sample, User


@pytest.fixture()
def engine() -> Engine:
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(eng)
    return eng


def _count(session: Session, model) -> int:
    return len(list(session.exec(select(model)).all()))


def test_seed_all_is_idempotent_and_contains_no_business_demo_data(engine: Engine) -> None:
    with Session(engine) as session:
        seed_all(session)
        models = (LabelCategory, User, DataRecord, Dataset, Model, AnnotationTask, Sample)
        first = {model: _count(session, model) for model in models}
        seed_all(session, demo=True)
        assert {model: _count(session, model) for model in models} == first
        assert first[LabelCategory] == 5
        assert first[User] == 1
        assert first[DataRecord] == 0
        assert first[Dataset] == 0
        assert first[Model] == 0
        assert first[AnnotationTask] == 0
        assert first[Sample] == 0


def test_admin_seeded_and_password_verifies(engine: Engine) -> None:
    with Session(engine) as session:
        seed_all(session)
        admin = session.exec(select(User).where(User.username == settings.admin_username)).first()
        assert admin is not None
        assert admin.display_name == "系统管理员"
        assert admin.role == "admin"
        assert verify_password(settings.admin_password, admin.password_hash) is True
