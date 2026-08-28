"""add traceability metadata to feature extractions"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0009"
down_revision: Union[str, Sequence[str], None] = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = [
        sa.Column("job_id", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="succeeded"),
        sa.Column("source_by_modality", sa.JSON(), nullable=True),
        sa.Column("input_object_keys", sa.JSON(), nullable=True),
        sa.Column("algorithm_version", sa.String(length=64), nullable=False, server_default="feature-pipeline-v2"),
        sa.Column("pipeline_version", sa.String(length=64), nullable=False, server_default="feature-extraction-v2"),
        sa.Column("sample_rate", sa.Integer(), nullable=True),
        sa.Column("sample_count", sa.Integer(), nullable=True),
        sa.Column("duration", sa.Float(), nullable=True),
        sa.Column("channel_mapping", sa.JSON(), nullable=True),
        sa.Column("missing_modalities", sa.JSON(), nullable=True),
        sa.Column("warnings", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.String(length=1024), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
    ]
    for column in columns:
        op.add_column("feature_extractions", column)
    op.create_index("ix_feature_extractions_job_id", "feature_extractions", ["job_id"])
    op.create_index("ix_feature_extractions_status", "feature_extractions", ["status"])
    op.create_index("ix_feature_extractions_created_by", "feature_extractions", ["created_by"])


def downgrade() -> None:
    for name in ("created_by", "finished_at", "started_at", "error_message", "warnings", "missing_modalities", "channel_mapping", "duration", "sample_count", "sample_rate", "pipeline_version", "algorithm_version", "input_object_keys", "source_by_modality", "status", "job_id"):
        op.drop_column("feature_extractions", name)
