"""模型域实体：模型 / 模型版本 / 训练任务 / 测试任务 / 推理任务。

对应 `docs/数据库设计.md` §3.17–§3.21。
"""

from datetime import datetime

from sqlalchemy import JSON, Column, DateTime, UniqueConstraint
from sqlmodel import Field, SQLModel


class Model(SQLModel, table=True):
    """§3.17 models 模型（无 created_at）"""

    __tablename__ = "models"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(max_length=128)
    type: str = Field(max_length=32)
    description: str | None = Field(default=None, max_length=255)


class ModelVersion(SQLModel, table=True):
    """§3.18 model_versions 模型版本（同一模型内版本号唯一）"""

    __tablename__ = "model_versions"
    __table_args__ = (
        UniqueConstraint(
            "model_id", "version_no", name="uq_model_versions_model_version"
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    model_id: int = Field(foreign_key="models.id", index=True)
    version_no: str = Field(max_length=16)
    metric: dict | None = Field(default=None, sa_column=Column(JSON))
    status: str = Field(max_length=16, default="实验版本")
    file_key: str | None = Field(default=None, max_length=255)
    created_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True))
    )


class TrainingTask(SQLModel, table=True):
    """§3.19 training_tasks 训练任务（1:1 关联 jobs）"""

    __tablename__ = "training_tasks"

    id: int | None = Field(default=None, primary_key=True)
    job_id: int = Field(foreign_key="jobs.id", unique=True)
    dataset_version_id: int = Field(
        foreign_key="dataset_versions.id", index=True
    )
    base_model_id: int | None = Field(
        default=None, foreign_key="model_versions.id"
    )
    hyperparams: dict = Field(sa_column=Column(JSON))
    metrics: dict | None = Field(default=None, sa_column=Column(JSON))
    loss_curve: list | None = Field(default=None, sa_column=Column(JSON))


class TestTask(SQLModel, table=True):
    """§3.20 test_tasks 测试任务（1:1 关联 jobs）"""

    __tablename__ = "test_tasks"

    id: int | None = Field(default=None, primary_key=True)
    job_id: int = Field(foreign_key="jobs.id", unique=True)
    model_version_id: int = Field(
        foreign_key="model_versions.id", index=True
    )
    dataset_version_id: int = Field(
        foreign_key="dataset_versions.id", index=True
    )
    tasks: dict = Field(sa_column=Column(JSON))
    metrics: dict | None = Field(default=None, sa_column=Column(JSON))
    confusion_matrix: dict | None = Field(
        default=None, sa_column=Column(JSON)
    )


class InferenceTask(SQLModel, table=True):
    """§3.21 inference_tasks 推理任务（1:1 关联 jobs）"""

    __tablename__ = "inference_tasks"

    id: int | None = Field(default=None, primary_key=True)
    job_id: int = Field(foreign_key="jobs.id", unique=True)
    model_version_id: int = Field(
        foreign_key="model_versions.id", index=True
    )
    input_type: str = Field(max_length=16)
    input_key: str = Field(max_length=255)
    result: dict | None = Field(default=None, sa_column=Column(JSON))
