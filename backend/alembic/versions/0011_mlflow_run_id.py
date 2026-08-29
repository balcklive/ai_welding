"""store the optional MLflow run id on asynchronous jobs"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0011"
down_revision: Union[str, Sequence[str], None] = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("mlflow_run_id", sa.String(length=64), nullable=True))
    op.create_index("ix_jobs_mlflow_run_id", "jobs", ["mlflow_run_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_jobs_mlflow_run_id", table_name="jobs")
    op.drop_column("jobs", "mlflow_run_id")
