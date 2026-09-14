"""T16.1 数据集版本冻结标注快照：`dataset_items` 增 `annotations` JSON 列。

背景：改造前"数据集版本可复现训练"并不成立——训练时**现查** `Sample` 与 `Annotation`
（`services/torch_training.py::load_real_examples`），而同一数据集的标注在版本构建之后很可能
被继续修改/重标；再加上构建允许清空重建成员，于是"同一个数据集版本、两次训练、不同输入"。

本次把标注**快照**随版本一起冻下来：构建时把该样本的原始类别写进 `dataset_items.annotations`
（`[{category, confidence, kind}]`），训练改为读它、不再查 `annotations` 表。

为什么冻"原始类别"而不是"折叠后的标签"：缺陷白名单（决策 6：只认焊瘤/气孔/未熔合/咬边等
为缺陷，熔池/正常剔除）是**代码里的规则**，冻原始类别后调整白名单仍能对已建版本重新折叠；
冻折叠结果就把规则也一起冻死了。

为什么落在 `dataset_items` 而不是快照 JSON：快照写 MinIO 是**尽力而为**（失败仅告警），
冻结内容不能依赖它；放 DB 里才与成员清单同事务、同权威。

纯 expand 迁移，兼容蓝绿：老代码不读新列，新代码对 NULL 有兜底（回退现查 annotations 表）。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision: str = "0016"
down_revision: Union[str, Sequence[str], None] = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "dataset_items",
        sa.Column("annotations", mysql.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("dataset_items", "annotations")
