"""系统设置·可选项字典：新建 option_items + label_categories 补 active/sort_order。

背景（2026-09）：数据登记/数据集录入的可选项原先硬编码在前端（焊机型号 3 项、
焊接方法 3 项、数据集任务写死「目标检测」），产品/项目信息为纯自由文本无法约束。
本次把「录入时可选项」字典化，落到 `docs/数据库设计.md` §3.26：

1. 新建 `option_items`（group_key 分组 + (group_key,value) 唯一 + active 软删 + sort_order）；
2. `label_categories` 补 `active` / `sort_order`，纳入同一套「选项组」接口管理——
   标注类别不搬家（LS 集成、`annotations.category` 校验都依赖该表）；
3. 写入出厂默认选项，值与迁移前前端硬编码一致（machine/weld_method/dataset_task），
   `source` 取系统内既有登记示例；`product` 无既有取值，留空由管理员维护。

幂等：INSERT ... ON DUPLICATE KEY UPDATE 保证重复执行不报错、不覆盖管理员改名后的行
（同名行仅刷新 sort_order/active 之外的键，实际为 no-op）。
纯 expand 迁移，兼容蓝绿：老代码不读新表/新列，新代码对缺失项有兜底。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision: str = "0015"
down_revision: Union[str, Sequence[str], None] = "0014"
branch_labels = None
depends_on = None

#: 出厂默认选项（group_key, value, sort_order），与 backend/app/core/seed.py 保持一致。
DEFAULT_OPTION_ITEMS: tuple[tuple[str, str, int], ...] = (
    ("machine", "Fronius CMT", 10),
    ("machine", "OTC FD-V8", 20),
    ("machine", "Panasonic YD-500", 30),
    ("weld_method", "MAG焊", 10),
    ("weld_method", "MIG焊", 20),
    ("weld_method", "TIG焊", 30),
    ("source", "产线相机 · 03号", 10),
    ("source", "实训线 · 02号", 20),
    ("source", "实训线 · 01号", 30),
    ("dataset_task", "目标检测", 10),
    ("dataset_task", "语义分割", 20),
    ("dataset_task", "多模态回归", 30),
)


def upgrade() -> None:
    op.create_table(
        "option_items",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("group_key", sa.String(length=32), nullable=False),
        sa.Column("value", sa.String(length=128), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("updated_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.UniqueConstraint("group_key", "value", name="uq_option_items_group_value"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )
    op.create_index("ix_option_items_group_key", "option_items", ["group_key"], unique=False)
    op.create_index("ix_option_items_active", "option_items", ["active"], unique=False)

    # 标注类别纳入设置管理：sort_order 按既有 id 顺序回填（等价于原来的 id 升序展示）。
    op.add_column(
        "label_categories",
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "label_categories",
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
    )
    op.execute("UPDATE label_categories SET sort_order = id * 10")

    values = ", ".join(
        f"('{group}', '{value}', {order}, 1)" for group, value, order in DEFAULT_OPTION_ITEMS
    )
    op.execute(
        "INSERT INTO option_items (group_key, value, sort_order, active) VALUES "
        f"{values} ON DUPLICATE KEY UPDATE group_key = VALUES(group_key)"
    )


def downgrade() -> None:
    op.drop_column("label_categories", "active")
    op.drop_column("label_categories", "sort_order")
    op.drop_index("ix_option_items_active", table_name="option_items")
    op.drop_index("ix_option_items_group_key", table_name="option_items")
    op.drop_table("option_items")
