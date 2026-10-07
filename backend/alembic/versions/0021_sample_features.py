"""切片级特征提取：新建 `sample_features` + `dataset_items.features`。

背景（2026-10）：此前的特征提取是**焊缝数据版本级**的（`feature_extractions`，§3.13）——
对整条信号逐通道跑统计、拿**一整张**焊缝照片算视觉、加声音，拼 42 维。而训练时又各自
现算一个 8 维（把一张缩略图或一段 CSV/JSON 的所有数字拉平取统计），不落库、不可复现。
两边口径不同、切片跟 42 维也没有任何数据流。

本迁移建**切片级**落库（§3.28 `sample_features`）：一个 v3 `Sample`（一个时间窗）一行，
`sample_id` 唯一（PUT 即 upsert），存 **36 维**——时序 28（cur 8 / vol 8 / gas 6 / wir 6）+
视觉 8（几何 4 / 纹理 4），**无声音组**（切片 manifest 自己就写着 `audio.available = False`）。

**为什么不给 `feature_extractions` 加 `sample_id`**：那张表的版本级端点
（`GET /features/latest/{version_id}`、`/history/{version_id}`）按 `version_id` 取最新一行，
切片行也带 `version_id` 就会被当成焊缝级向量返回。分表让两边口径各自封闭。

同时给 `dataset_items` 加 `features` JSON（**冻结副本**）：训练读它而不是现查
`sample_features`，否则重跑特征提取就会让"同一个版本"训出不同结果。与 `0016` 给
`dataset_items` 加 `annotations` 是同一个理由。

纯 expand 迁移，兼容蓝绿：老代码不读新表/新列；新代码对 NULL 兜底（`features` 为 NULL
⇒ 训练回退旧的 8 维现算口径）。**不回填**——存量分段任务没有切片特征，需要时重跑即可。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision: str = "0021"
down_revision: Union[str, Sequence[str], None] = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sample_features",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("sample_id", sa.BigInteger(), nullable=False),
        sa.Column("split_task_id", sa.BigInteger(), nullable=False),
        sa.Column("version_id", sa.BigInteger(), nullable=False),
        sa.Column("unified_vector", mysql.JSON(), nullable=False),
        sa.Column("ts_features", mysql.JSON(), nullable=False),
        sa.Column("vision_features", mysql.JSON(), nullable=False),
        # NOT NULL 的 JSON 在 MySQL 8.0.13 前不能有默认值 —— 由服务层保证非空。
        sa.Column("source_by_modality", mysql.JSON(), nullable=False),
        sa.Column("channel_mapping", mysql.JSON(), nullable=False),
        sa.Column("warnings", mysql.JSON(), nullable=False),
        sa.Column("normalization", sa.String(length=16), nullable=False),
        sa.Column(
            "pipeline_version",
            sa.String(length=64),
            nullable=False,
            server_default="sample-features-v1",
        ),
        sa.Column("job_id", sa.BigInteger(), nullable=True),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("finished_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.ForeignKeyConstraint(["sample_id"], ["samples.id"], name="fk_sample_features_sample"),
        sa.ForeignKeyConstraint(
            ["split_task_id"], ["split_tasks.id"], name="fk_sample_features_task"
        ),
        sa.ForeignKeyConstraint(
            ["version_id"], ["data_versions.id"], name="fk_sample_features_version"
        ),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], name="fk_sample_features_job"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_sample_features_creator"),
        sa.UniqueConstraint("sample_id", name="uq_sample_features_sample"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )
    for column in ("split_task_id", "version_id", "job_id", "created_by"):
        op.create_index(
            f"ix_sample_features_{column}", "sample_features", [column], unique=False
        )

    op.add_column("dataset_items", sa.Column("features", mysql.JSON(), nullable=True))


def downgrade() -> None:
    # 先删可空列（无外键，随时可丢），再逆序拆新表的索引与表。
    op.drop_column("dataset_items", "features")
    for column in ("created_by", "job_id", "version_id", "split_task_id"):
        op.drop_index(f"ix_sample_features_{column}", table_name="sample_features")
    op.drop_table("sample_features")
