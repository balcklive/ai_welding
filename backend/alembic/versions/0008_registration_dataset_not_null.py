"""enforce non-null dataset ownership for registrations"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0008"
down_revision: Union[str, Sequence[str], None] = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text("UPDATE data_records SET dataset_id = (SELECT MIN(id) FROM datasets) WHERE dataset_id IS NULL"))
    op.alter_column("data_records", "dataset_id", existing_type=sa.BigInteger(), nullable=False)


def downgrade() -> None:
    op.alter_column("data_records", "dataset_id", existing_type=sa.BigInteger(), nullable=True)
