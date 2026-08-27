"""require every weld registration to belong to a dataset"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0006"
down_revision: Union[str, Sequence[str], None] = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add nullable first, backfill legacy rows to the first existing dataset,
    # then enforce the invariant at the database layer as well as the API.
    op.add_column("data_records", sa.Column("dataset_id", sa.BigInteger(), nullable=True))
    op.create_index("ix_data_records_dataset_id", "data_records", ["dataset_id"])
    op.create_foreign_key("fk_data_records_dataset_id", "data_records", "datasets", ["dataset_id"], ["id"])
    op.execute(sa.text("UPDATE data_records SET dataset_id = (SELECT MIN(id) FROM datasets) WHERE dataset_id IS NULL"))
    op.alter_column("data_records", "dataset_id", existing_type=sa.BigInteger(), nullable=False)


def downgrade() -> None:
    op.drop_constraint("fk_data_records_dataset_id", "data_records", type_="foreignkey")
    op.drop_index("ix_data_records_dataset_id", table_name="data_records")
    op.drop_column("data_records", "dataset_id")
