"""单条焊缝删除规则。"""

import pytest
from sqlalchemy import create_engine
from sqlmodel import Session, SQLModel

from app.models import DataRecord
from app.services.welds import delete_record


@pytest.fixture()
def engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return engine


def test_delete_weld_without_versions(engine):
    with Session(engine) as session:
        record = DataRecord(
            weld_id="WLD-DELETE-001",
            registration_no="REG-DELETE-001",
            source="test",
            quality="待复核",
        )
        session.add(record)
        session.commit()
        session.refresh(record)

        assert delete_record(session, record) == {"deleted_versions": 0}
        session.commit()
        assert session.get(DataRecord, record.id) is None
