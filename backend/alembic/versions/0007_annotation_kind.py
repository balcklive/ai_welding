"""annotations 表扩标注几何类型：kind / points / start_time / end_time。

时序区间标注（segment）与视频多边形标注（polygon）复用现有 annotations 表，
`kind` 判别几何类型（box 默认兼容老数据）；新增列均 nullable（points/start_time/
end_time），`kind` 带 server_default='box' 兼容历史行。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0007"
down_revision: Union[str, Sequence[str], None] = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "annotations",
        sa.Column("kind", sa.String(length=16), nullable=False, server_default="box"),
    )
    op.add_column("annotations", sa.Column("points", sa.JSON(), nullable=True))
    op.add_column("annotations", sa.Column("start_time", sa.Double(), nullable=True))
    op.add_column("annotations", sa.Column("end_time", sa.Double(), nullable=True))


def downgrade() -> None:
    op.drop_column("annotations", "end_time")
    op.drop_column("annotations", "start_time")
    op.drop_column("annotations", "points")
    op.drop_column("annotations", "kind")
