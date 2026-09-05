"""label_categories 补第 6 类「熔池」（LS 集成决策 4：文档 6 类/代码 5 类漂移消除）。

熔池是语义分割目标（LS 项目 4 PolygonLabels 单类熔池，颜色 #f032e6 对齐），不是缺陷；
补入 label_categories 使平台类别口径与文档/LS 一致。幂等：`name` 唯一，重复迁移不重复插入。
纯数据迁移（无表结构变更）。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0014"
down_revision: Union[str, Sequence[str], None] = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "INSERT INTO label_categories (name, color) VALUES ('熔池', '#f032e6') "
            "ON DUPLICATE KEY UPDATE name = VALUES(name)"
        )
    )


def downgrade() -> None:
    op.execute("DELETE FROM label_categories WHERE name = '熔池'")
