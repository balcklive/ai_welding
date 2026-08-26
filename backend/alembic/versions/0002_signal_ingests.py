"""add signal_ingests

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-24

按计划新增 `signal_ingests` 表（§3.24 真实信号导入元数据）：
CSV 原始文件挂载后自动解析 + 校验 + 写 MinIO Parquet 的任务行。

要点：
- datetime 列统一 `mysql.DATETIME(fsp=6)`（模型注解是 DateTime(timezone=True)，迁移手写）。
- JSON 列统一 `mysql.JSON()`。
- `job_id` 1:1（unique）关联 jobs；`(version_id, source_object_key)` 复合唯一保证幂等。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: Union[str, Sequence[str], None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "signal_ingests",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.BigInteger(), nullable=False),
        sa.Column("version_id", sa.BigInteger(), nullable=False),
        sa.Column("source_object_key", sa.String(255), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("sample_rate", sa.Integer(), nullable=True),
        sa.Column("duration", sa.Float(), nullable=True),
        sa.Column("row_count", sa.Integer(), nullable=True),
        sa.Column("column_map", mysql.JSON(), nullable=True),
        sa.Column("validation", mysql.JSON(), nullable=True),
        sa.Column("parquet_key", sa.String(255), nullable=True),
        sa.Column("events", mysql.JSON(), nullable=True),
        sa.Column("anomalies", mysql.JSON(), nullable=True),
        sa.Column("error", mysql.JSON(), nullable=True),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("finished_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
        sa.ForeignKeyConstraint(["version_id"], ["data_versions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", name="uq_signal_ingests_job_id"),
        sa.UniqueConstraint(
            "version_id",
            "source_object_key",
            name="uq_signal_ingests_version_key",
        ),
        mysql_charset="utf8mb4",
    )
    op.create_index(
        "ix_signal_ingests_version_id", "signal_ingests", ["version_id"]
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_signal_ingests_version_id", table_name="signal_ingests")
    op.drop_table("signal_ingests")
