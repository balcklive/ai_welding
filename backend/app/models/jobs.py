"""§3.6 jobs 异步任务（统一生命周期）"""

from datetime import datetime

from sqlalchemy import JSON, Column, DateTime
from sqlmodel import Field, SQLModel


class Job(SQLModel, table=True):
    __tablename__ = "jobs"

    id: int | None = Field(default=None, primary_key=True)
    job_uid: str = Field(max_length=40, unique=True)
    request_key: str | None = Field(default=None, max_length=128, index=True, unique=True)
    mlflow_run_id: str | None = Field(default=None, max_length=64, index=True)  # MLFLOW-INTEGRATION
    type: str = Field(max_length=32, index=True)
    status: str = Field(max_length=16, index=True)
    progress: int = Field(default=0)
    result: dict | None = Field(default=None, sa_column=Column(JSON))
    error: dict | None = Field(default=None, sa_column=Column(JSON))
    created_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True))
    )
    finished_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True))
    )
