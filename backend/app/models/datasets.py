"""数据集域实体：数据集 / 数据集版本 / 数据集成员 / 数据集构建任务。

对应 `docs/数据库设计.md` §3.14–§3.16、§3.22。
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import JSON, Column, DateTime, Numeric, UniqueConstraint
from sqlmodel import Field, SQLModel


class Dataset(SQLModel, table=True):
    """§3.14 datasets 数据集"""

    __tablename__ = "datasets"

    id: int | None = Field(default=None, primary_key=True)
    dataset_no: str = Field(max_length=64, unique=True)
    name: str = Field(max_length=128)
    task: str = Field(max_length=32)
    sample_count: int = Field(default=0)
    progress: Decimal | None = Field(
        default=None, sa_column=Column(Numeric(5, 2))
    )
    status: str = Field(max_length=16)
    # 反规范化：当前版本指针。
    current_version_id: int | None = Field(
        default=None, foreign_key="dataset_versions.id"
    )
    created_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True))
    )
    updated_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True))
    )


class DatasetVersion(SQLModel, table=True):
    """§3.15 dataset_versions 数据集版本（固定快照，同一数据集内版本号唯一）"""

    __tablename__ = "dataset_versions"
    __table_args__ = (
        UniqueConstraint(
            "dataset_id", "version_no", name="uq_dataset_versions_dataset_version"
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    dataset_id: int = Field(foreign_key="datasets.id", index=True)
    version_no: str = Field(max_length=16)
    split: dict = Field(sa_column=Column(JSON))
    item_count: int
    snapshot_id: str | None = Field(default=None, max_length=64)
    quality: dict | None = Field(default=None, sa_column=Column(JSON))
    created_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True))
    )


class DatasetItem(SQLModel, table=True):
    """§3.16 dataset_items 数据集版本成员（固定样本清单，同版本样本唯一）"""

    __tablename__ = "dataset_items"
    __table_args__ = (
        UniqueConstraint(
            "dataset_version_id", "sample_id", name="uq_dataset_items_version_sample"
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    dataset_version_id: int = Field(
        foreign_key="dataset_versions.id", index=True
    )
    sample_id: int = Field(foreign_key="samples.id")
    split: str = Field(max_length=8)


class DatasetBuildTask(SQLModel, table=True):
    """§3.22 dataset_build_tasks 数据集构建任务（1:1 关联 jobs）"""

    __tablename__ = "dataset_build_tasks"

    id: int | None = Field(default=None, primary_key=True)
    job_id: int = Field(foreign_key="jobs.id", unique=True)
    dataset_version_id: int = Field(
        foreign_key="dataset_versions.id", index=True
    )
    source: str = Field(max_length=32)
