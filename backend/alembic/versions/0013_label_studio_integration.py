"""annotation_tasks 加 ls_status 列 + 新建 annotation_ls_sync 表（Label Studio 集成）。

存量 annotation_tasks 回填 ls_status='legacy'（旧模拟任务从未进 LS）；蓝绿 expand 兼容：
`ADD COLUMN ... NOT NULL DEFAULT 'legacy'` 一条即完成存量回填 + 新行默认 + 旧代码读取不崩
（同计划决策 7 / 验证报告 §4 的迁移结论）。annotation_ls_sync 表存任务样本 ↔ LS task 映射与
回写状态，`(annotation_task_id, sample_id)` 复合唯一幂等。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision: str = "0013"
down_revision: Union[str, Sequence[str], None] = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # annotation_tasks 加「LS 等待/同步」状态列（存量回填 legacy）
    op.add_column(
        "annotation_tasks",
        sa.Column("ls_status", sa.String(length=16), nullable=False, server_default="legacy"),
    )
    op.create_index("ix_annotation_tasks_ls_status", "annotation_tasks", ["ls_status"], unique=False)

    # 新表 annotation_ls_sync
    op.create_table(
        "annotation_ls_sync",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("annotation_task_id", sa.BigInteger(), sa.ForeignKey("annotation_tasks.id"), nullable=False),
        sa.Column("sample_id", sa.BigInteger(), sa.ForeignKey("samples.id"), nullable=False),
        sa.Column("ls_project_id", sa.Integer(), nullable=False),
        sa.Column("ls_task_id", sa.Integer(), nullable=True),
        sa.Column("ls_annotation_id", sa.Integer(), nullable=True),
        sa.Column("sync_status", sa.String(length=16), nullable=False, server_default="pending_ls"),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("updated_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.UniqueConstraint("annotation_task_id", "sample_id", name="uq_annotation_ls_sync_task_sample"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )
    op.create_index("ix_annotation_ls_sync_annotation_task_id", "annotation_ls_sync", ["annotation_task_id"], unique=False)
    op.create_index("ix_annotation_ls_sync_sample_id", "annotation_ls_sync", ["sample_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_annotation_ls_sync_sample_id", table_name="annotation_ls_sync")
    op.drop_index("ix_annotation_ls_sync_annotation_task_id", table_name="annotation_ls_sync")
    op.drop_table("annotation_ls_sync")
    op.drop_index("ix_annotation_tasks_ls_status", table_name="annotation_tasks")
    op.drop_column("annotation_tasks", "ls_status")
