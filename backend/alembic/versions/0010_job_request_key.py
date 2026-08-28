"""add idempotency key for asynchronous jobs"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0010"
down_revision: Union[str, Sequence[str], None] = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("request_key", sa.String(length=128), nullable=True))
    op.create_index("ix_jobs_request_key", "jobs", ["request_key"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_jobs_request_key", table_name="jobs")
    op.drop_column("jobs", "request_key")
