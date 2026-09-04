"""data_records 扩展登记数据字段：wire_feed_speed / welding_speed / data_fields。

配合客户多模态分析.csv 导入：送丝速度、焊接速度为单值工艺列（可表单录入/导入稳态
回填），data_fields 为导入字段概览 JSON（全通道稳态代表值）。三列均 nullable，历史行不受影响。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0012"
down_revision: Union[str, Sequence[str], None] = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "data_records",
        sa.Column("wire_feed_speed", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "data_records",
        sa.Column("welding_speed", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "data_records",
        sa.Column("data_fields", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("data_records", "data_fields")
    op.drop_column("data_records", "welding_speed")
    op.drop_column("data_records", "wire_feed_speed")
