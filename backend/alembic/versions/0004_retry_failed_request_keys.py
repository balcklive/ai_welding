"""allow retry after failed alignment/split tasks

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-25

把 alignment/split 的唯一占位从 `request_key` 拆成：
- `request_key`：逻辑幂等键（可重复，保留失败重试历史）
- `active_request_key`：仅 pending/running/succeeded 占位；failed 置空后允许重试
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: Union[str, Sequence[str], None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("alignment_tasks", sa.Column("active_request_key", sa.String(length=64), nullable=True))
    op.add_column("split_tasks", sa.Column("active_request_key", sa.String(length=64), nullable=True))

    op.execute(
        """
        UPDATE alignment_tasks t
        JOIN jobs j ON j.id = t.job_id
        SET t.active_request_key = t.request_key
        WHERE t.request_key IS NOT NULL
          AND j.status IN ('pending', 'running', 'succeeded')
        """
    )
    op.execute(
        """
        UPDATE split_tasks t
        JOIN jobs j ON j.id = t.job_id
        SET t.active_request_key = t.request_key
        WHERE t.request_key IS NOT NULL
          AND j.status IN ('pending', 'running', 'succeeded')
        """
    )

    op.drop_constraint("uq_alignment_tasks_request_key", "alignment_tasks", type_="unique")
    op.drop_constraint("uq_split_tasks_request_key", "split_tasks", type_="unique")
    op.create_unique_constraint(
        "uq_alignment_tasks_active_request_key",
        "alignment_tasks",
        ["active_request_key"],
    )
    op.create_unique_constraint(
        "uq_split_tasks_active_request_key",
        "split_tasks",
        ["active_request_key"],
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE alignment_tasks
        SET request_key = SHA2(CONCAT(COALESCE(request_key, ''), ':', id), 256)
        WHERE active_request_key IS NULL AND request_key IS NOT NULL
        """
    )
    op.execute(
        """
        UPDATE split_tasks
        SET request_key = SHA2(CONCAT(COALESCE(request_key, ''), ':', id), 256)
        WHERE active_request_key IS NULL AND request_key IS NOT NULL
        """
    )

    op.drop_constraint(
        "uq_split_tasks_active_request_key", "split_tasks", type_="unique"
    )
    op.drop_constraint(
        "uq_alignment_tasks_active_request_key", "alignment_tasks", type_="unique"
    )
    op.create_unique_constraint(
        "uq_alignment_tasks_request_key",
        "alignment_tasks",
        ["request_key"],
    )
    op.create_unique_constraint(
        "uq_split_tasks_request_key",
        "split_tasks",
        ["request_key"],
    )
    op.drop_column("split_tasks", "active_request_key")
    op.drop_column("alignment_tasks", "active_request_key")
