"""分段样本段级标注：新建 `sample_annotations` + 缺陷词表出厂项。

背景（2026-09-22，样本分段 v3 之后）：v3 的 `Sample` 已经是"一个时间窗 + 一个多模态
样本包"（迁移 `0019`），但**没有段级结论**——`annotations` 那套是为框/时序区间/多边形
设计的（`kind` 三态、一条样本多行），表达不了"这一段整体是正常还是缺陷"。

故新建 `sample_annotations`（§3.27）：**一个 Sample 一行**（`sample_id` 唯一），
一期只做段级分类，没有框/点/掩膜、没有两级精度：

- `label` = `normal` | `defect`；`defect` 时必须给主缺陷类别，`normal` 时必须为空；
- 缺陷词表的稳定 ID 指向 `option_items`（`group_key='defect_category'`）——复用系统设置
  那套字典设施（分组 + `(group_key,value)` 唯一 + `active` 软删 + `sort_order`），
  **不新建词表表**；`defect_category_name` 是**当时名称快照**，类别改名/停用后历史标注仍可读；
- `review_status` 为将来的复核流程预留（默认 `approved`，一期 UI 不暴露）；
- `schema_version` 是标注数据的 schema 版本，供数据集构建消费时先认版本号。

词表默认 7 类（气孔/未焊透/焊穿/咬边/裂纹/成形不良/其他）。**注意与既有 `label_categories`
（焊瘤/气孔/未熔合/咬边/正常/熔池，模型口径）是两套词表**——后者被 LS 集成与
`POST …/labels` 校验依赖，不能改；这里另起一组，互不影响。

纯 expand 迁移，兼容蓝绿：老代码不读新表；新表无历史行需要回填。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision: str = "0020"
down_revision: Union[str, Sequence[str], None] = "0019"
branch_labels = None
depends_on = None

#: 默认缺陷词表（value, sort_order），与 `backend/app/core/seed.py` 保持一致。
DEFAULT_DEFECT_CATEGORIES: tuple[tuple[str, int], ...] = (
    ("气孔", 10),
    ("未焊透", 20),
    ("焊穿", 30),
    ("咬边", 40),
    ("裂纹", 50),
    ("成形不良", 60),
    ("其他", 70),
)


def upgrade() -> None:
    op.create_table(
        "sample_annotations",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("sample_id", sa.BigInteger(), nullable=False),
        sa.Column("label", sa.String(length=16), nullable=False),
        sa.Column("defect_category_id", sa.BigInteger(), nullable=True),
        sa.Column("defect_category_name", sa.String(length=32), nullable=True),
        sa.Column("note", sa.String(length=512), nullable=True),
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("review_status", sa.String(length=16), nullable=True, server_default="approved"),
        sa.Column("annotator", sa.String(length=64), nullable=True),
        sa.Column("annotator_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("updated_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.ForeignKeyConstraint(["sample_id"], ["samples.id"], name="fk_sample_annotations_sample"),
        sa.ForeignKeyConstraint(
            ["defect_category_id"], ["option_items.id"], name="fk_sample_annotations_category"
        ),
        sa.ForeignKeyConstraint(
            ["annotator_id"], ["users.id"], name="fk_sample_annotations_annotator"
        ),
        sa.UniqueConstraint("sample_id", name="uq_sample_annotations_sample"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )
    op.create_index("ix_sample_annotations_label", "sample_annotations", ["label"], unique=False)
    op.create_index(
        "ix_sample_annotations_defect_category_id",
        "sample_annotations",
        ["defect_category_id"],
        unique=False,
    )
    op.create_index(
        "ix_sample_annotations_review_status",
        "sample_annotations",
        ["review_status"],
        unique=False,
    )
    op.create_index(
        "ix_sample_annotations_annotator_id",
        "sample_annotations",
        ["annotator_id"],
        unique=False,
    )

    values = ", ".join(
        f"('defect_category', '{value}', {order}, 1)"
        for value, order in DEFAULT_DEFECT_CATEGORIES
    )
    op.execute(
        "INSERT INTO option_items (group_key, value, sort_order, active) VALUES "
        f"{values} ON DUPLICATE KEY UPDATE group_key = VALUES(group_key)"
    )


def downgrade() -> None:
    # 顺序要紧：**先删表再删词表项**。反过来的话，只要还有标注行引用着 `defect_category`
    # 的某个 option_items，DELETE 就会被外键拦下（回滚一半失败）。
    op.drop_index("ix_sample_annotations_annotator_id", table_name="sample_annotations")
    op.drop_index("ix_sample_annotations_review_status", table_name="sample_annotations")
    op.drop_index(
        "ix_sample_annotations_defect_category_id", table_name="sample_annotations"
    )
    op.drop_index("ix_sample_annotations_label", table_name="sample_annotations")
    op.drop_table("sample_annotations")

    # 出厂词表项：只删**出厂那 7 条**，管理员在设置页自己加的不动（同名项若已被改名也留着）。
    values = ", ".join(f"'{value}'" for value, _ in DEFAULT_DEFECT_CATEGORIES)
    op.execute(
        "DELETE FROM option_items WHERE group_key = 'defect_category' "
        f"AND value IN ({values})"
    )
