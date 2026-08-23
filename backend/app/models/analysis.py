"""分析域实体：对齐 / 切分 / 样本 / 标注 / 标签类别 / 特征提取。

对应 `docs/数据库设计.md` §3.7–§3.13。
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import JSON, Column, DateTime, Numeric
from sqlmodel import Field, SQLModel


class AlignmentTask(SQLModel, table=True):
    """§3.7 alignment_tasks 多模态对齐（1:1 关联 jobs）"""

    __tablename__ = "alignment_tasks"

    id: int | None = Field(default=None, primary_key=True)
    job_id: int = Field(foreign_key="jobs.id", unique=True)
    version_id: int = Field(foreign_key="data_versions.id", index=True)
    modalities: list = Field(default_factory=list, sa_column=Column(JSON))
    events: dict | None = Field(default=None, sa_column=Column(JSON))
    tracks: dict | None = Field(default=None, sa_column=Column(JSON))
    assets: dict | None = Field(default=None, sa_column=Column(JSON))


class SplitTask(SQLModel, table=True):
    """§3.8 split_tasks 数据切分"""

    __tablename__ = "split_tasks"

    id: int | None = Field(default=None, primary_key=True)
    job_id: int = Field(foreign_key="jobs.id", unique=True)
    version_id: int = Field(foreign_key="data_versions.id", index=True)
    rules: dict = Field(sa_column=Column(JSON))
    task_format: str = Field(max_length=32)
    sample_count: int | None = Field(default=None)


class Sample(SQLModel, table=True):
    """§3.9 samples 切分样本"""

    __tablename__ = "samples"

    id: int | None = Field(default=None, primary_key=True)
    split_task_id: int | None = Field(
        default=None, foreign_key="split_tasks.id", index=True
    )
    annotation_task_id: int | None = Field(
        default=None, foreign_key="annotation_tasks.id", index=True
    )
    frame_no: int | None = Field(default=None)
    object_keys: list = Field(default_factory=list, sa_column=Column(JSON))
    meta: dict | None = Field(default=None, sa_column=Column(JSON))


class AnnotationTask(SQLModel, table=True):
    """§3.10 annotation_tasks 标注任务（1:1 关联 jobs）"""

    __tablename__ = "annotation_tasks"

    id: int | None = Field(default=None, primary_key=True)
    job_id: int = Field(foreign_key="jobs.id", unique=True)
    split_task_id: int | None = Field(
        default=None, foreign_key="split_tasks.id", index=True
    )
    name: str | None = Field(default=None, max_length=128)
    source: str = Field(max_length=32)
    created_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True))
    )


class Annotation(SQLModel, table=True):
    """§3.11 annotations 标注结果"""

    __tablename__ = "annotations"

    id: int | None = Field(default=None, primary_key=True)
    sample_id: int = Field(foreign_key="samples.id", index=True)
    category: str = Field(max_length=32)
    box: list | None = Field(default=None, sa_column=Column(JSON))
    confidence: Decimal | None = Field(
        default=None, sa_column=Column(Numeric(4, 3))
    )
    annotator: str | None = Field(default=None, max_length=64)
    created_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True))
    )
    updated_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True))
    )


class LabelCategory(SQLModel, table=True):
    """§3.12 label_categories 标签类别"""

    __tablename__ = "label_categories"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(max_length=32, unique=True)
    color: str | None = Field(default=None, max_length=16)


class FeatureExtraction(SQLModel, table=True):
    """§3.13 feature_extractions 特征提取"""

    __tablename__ = "feature_extractions"

    id: int | None = Field(default=None, primary_key=True)
    version_id: int = Field(foreign_key="data_versions.id", index=True)
    ts_features: dict = Field(sa_column=Column(JSON))
    vision_features: dict = Field(sa_column=Column(JSON))
    audio_features: dict = Field(sa_column=Column(JSON))
    unified_vector: dict = Field(sa_column=Column(JSON))
    normalization: str = Field(max_length=16)
    format: str = Field(max_length=8)
    created_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True))
    )
