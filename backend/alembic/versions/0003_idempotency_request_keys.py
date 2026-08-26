"""add request keys for version/alignment/split idempotency

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-25

为版本加工 / 对齐 / 切分新增数据库级自然幂等键：
- data_versions.request_key（配合 record_id+action 复合唯一）
- alignment_tasks.request_key（唯一）
- split_tasks.request_key（唯一）

列保持 nullable，兼容历史脏数据；新代码对新写入行始终填充 request_key。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: Union[str, Sequence[str], None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("data_versions", sa.Column("request_key", sa.String(length=64), nullable=True))
    op.add_column("alignment_tasks", sa.Column("request_key", sa.String(length=64), nullable=True))
    op.add_column("split_tasks", sa.Column("request_key", sa.String(length=64), nullable=True))

    op.create_unique_constraint(
        "uq_data_versions_record_action_req",
        "data_versions",
        ["record_id", "action", "request_key"],
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


def downgrade() -> None:
    op.drop_constraint("uq_split_tasks_request_key", "split_tasks", type_="unique")
    op.drop_constraint("uq_alignment_tasks_request_key", "alignment_tasks", type_="unique")
    op.drop_constraint("uq_data_versions_record_action_req", "data_versions", type_="unique")

    op.drop_column("split_tasks", "request_key")
    op.drop_column("alignment_tasks", "request_key")
    op.drop_column("data_versions", "request_key")
