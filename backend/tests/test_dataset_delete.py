"""数据集删除规则：空数据集可删，仍有焊缝引用时必须拒绝。"""

import pytest
from sqlalchemy import create_engine
from sqlmodel import Session, SQLModel, select

from app.models import DataRecord, Dataset, DatasetVersion
from app.services.datasets import DatasetDeleteConflict, create_dataset, delete_dataset


@pytest.fixture()
def engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return engine


def test_delete_empty_dataset(engine):
    with Session(engine) as session:
        dataset = create_dataset(session, "待删除数据集", "目标检测")
        dataset_id = dataset.id
        result = delete_dataset(session, dataset)
        session.commit()

        assert result == {"deleted_versions": 0}
        assert session.get(Dataset, dataset_id) is None


def test_delete_empty_dataset_removes_versions(engine):
    with Session(engine) as session:
        dataset = create_dataset(session, "带快照待删除", "目标检测")
        version = DatasetVersion(
            dataset_id=dataset.id,
            version_no="v1.0",
            split={"train": 0, "val": 0, "test": 0},
            item_count=0,
        )
        session.add(version)
        session.flush()
        dataset.current_version_id = version.id
        session.commit()
        session.refresh(dataset)

        delete_dataset(session, dataset)
        session.commit()
        assert session.get(Dataset, dataset.id) is None
        assert session.get(DatasetVersion, version.id) is None


def test_delete_dataset_with_records_is_rejected(engine):
    with Session(engine) as session:
        dataset = create_dataset(session, "有数据集", "目标检测")
        session.add(DataRecord(
            weld_id="WLD-DELETE-001",
            registration_no="REG-DELETE-001",
            source="test",
            dataset_id=dataset.id,
        ))
        session.commit()
        session.refresh(dataset)

        with pytest.raises(DatasetDeleteConflict, match="仍包含 1 条焊缝数据"):
            delete_dataset(session, dataset)
        assert session.exec(select(Dataset).where(Dataset.id == dataset.id)).first() is not None
