"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-08-23

按 `docs/数据库设计.md` §3.1–§3.23 手写初始迁移（远程 MySQL 在本机不可达，无法 autogenerate）。

要点：
- datetime 列统一 `mysql.DATETIME(fsp=6)`（模型注解是 DateTime(timezone=True)，渲染 fsp=0，
  契约要求 DATETIME(6)，故手写；见 alembic/CLAUDE.md）。
- JSON 列统一 `mysql.JSON()`。
- data_records↔data_versions、datasets↔dataset_versions 两处环形 FK：
  先建父表（指针列仅普通列），再建子表，最后 `op.create_foreign_key` 补指针外键。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # --- 根表（无外键依赖） ---
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("username", sa.String(64), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(64), nullable=False),
        sa.Column("role", sa.String(32), nullable=False, server_default="admin"),
        sa.Column("avatar", sa.String(255), nullable=True),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username", name="uq_users_username"),
        mysql_charset="utf8mb4",
    )

    op.create_table(
        "jobs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("job_uid", sa.String(40), nullable=False),
        sa.Column("type", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("result", mysql.JSON(), nullable=True),
        sa.Column("error", mysql.JSON(), nullable=True),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("finished_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_uid", name="uq_jobs_job_uid"),
        mysql_charset="utf8mb4",
    )

    op.create_table(
        "models",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("type", sa.String(32), nullable=False),
        sa.Column("description", sa.String(255), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        mysql_charset="utf8mb4",
    )

    op.create_table(
        "label_categories",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(32), nullable=False),
        sa.Column("color", sa.String(16), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_label_categories_name"),
        mysql_charset="utf8mb4",
    )

    # --- 焊缝数据登记（latest_version_id 外键延后建，环形依赖） ---
    op.create_table(
        "data_records",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("weld_id", sa.String(64), nullable=False),
        sa.Column("weld_name", sa.String(128), nullable=True),
        sa.Column("registration_no", sa.String(64), nullable=False),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("collected_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("machine", sa.String(64), nullable=True),
        sa.Column("weld_method", sa.String(32), nullable=True),
        sa.Column("material", sa.String(64), nullable=True),
        sa.Column("thickness", sa.String(32), nullable=True),
        sa.Column("current_voltage", sa.String(32), nullable=True),
        sa.Column("sample_rate", sa.String(32), nullable=True),
        sa.Column("product", sa.String(128), nullable=True),
        sa.Column("modalities", mysql.JSON(), nullable=False),
        sa.Column("quality", sa.String(16), nullable=False, server_default="待复核"),
        sa.Column("operator", sa.String(64), nullable=True),
        sa.Column("storage_bytes", sa.BigInteger(), nullable=True),
        sa.Column("latest_version_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("updated_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("weld_id", name="uq_data_records_weld_id"),
        sa.UniqueConstraint("registration_no", name="uq_data_records_registration_no"),
        mysql_charset="utf8mb4",
    )

    # --- 数据版本（record_id 外键 → data_records） ---
    op.create_table(
        "data_versions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("record_id", sa.BigInteger(), nullable=False),
        sa.Column("version_no", sa.String(16), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("operator", sa.String(64), nullable=True),
        sa.Column("note", sa.String(255), nullable=True),
        sa.Column("object_keys", mysql.JSON(), nullable=True),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.ForeignKeyConstraint(["record_id"], ["data_records.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "record_id", "version_no", name="uq_data_versions_record_version"
        ),
        mysql_charset="utf8mb4",
    )

    # 补齐 data_records.latest_version_id 环形外键。
    op.create_foreign_key(
        "fk_data_records_latest_version_id",
        "data_records",
        "data_versions",
        ["latest_version_id"],
        ["id"],
    )

    # --- 核验（报告 + 规则明细） ---
    op.create_table(
        "validation_reports",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("version_id", sa.BigInteger(), nullable=False),
        sa.Column("score", sa.Numeric(5, 2), nullable=False),
        sa.Column("passed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("warning", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duration", sa.Numeric(8, 2), nullable=True),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.ForeignKeyConstraint(["version_id"], ["data_versions.id"]),
        sa.PrimaryKeyConstraint("id"),
        mysql_charset="utf8mb4",
    )

    op.create_table(
        "validation_rule_results",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("report_id", sa.BigInteger(), nullable=False),
        sa.Column("rule_name", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("message", sa.String(255), nullable=True),
        sa.ForeignKeyConstraint(["report_id"], ["validation_reports.id"]),
        sa.PrimaryKeyConstraint("id"),
        mysql_charset="utf8mb4",
    )

    # --- 分析任务（1:1 关联 jobs） ---
    op.create_table(
        "alignment_tasks",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.BigInteger(), nullable=False),
        sa.Column("version_id", sa.BigInteger(), nullable=False),
        sa.Column("modalities", mysql.JSON(), nullable=False),
        sa.Column("events", mysql.JSON(), nullable=True),
        sa.Column("tracks", mysql.JSON(), nullable=True),
        sa.Column("assets", mysql.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
        sa.ForeignKeyConstraint(["version_id"], ["data_versions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", name="uq_alignment_tasks_job_id"),
        mysql_charset="utf8mb4",
    )

    op.create_table(
        "split_tasks",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.BigInteger(), nullable=False),
        sa.Column("version_id", sa.BigInteger(), nullable=False),
        sa.Column("rules", mysql.JSON(), nullable=False),
        sa.Column("task_format", sa.String(32), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
        sa.ForeignKeyConstraint(["version_id"], ["data_versions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", name="uq_split_tasks_job_id"),
        mysql_charset="utf8mb4",
    )

    op.create_table(
        "annotation_tasks",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.BigInteger(), nullable=False),
        sa.Column("split_task_id", sa.BigInteger(), nullable=True),
        sa.Column("name", sa.String(128), nullable=True),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
        sa.ForeignKeyConstraint(["split_task_id"], ["split_tasks.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", name="uq_annotation_tasks_job_id"),
        mysql_charset="utf8mb4",
    )

    # --- 样本 + 标注 ---
    op.create_table(
        "samples",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("split_task_id", sa.BigInteger(), nullable=True),
        sa.Column("annotation_task_id", sa.BigInteger(), nullable=True),
        sa.Column("frame_no", sa.Integer(), nullable=True),
        sa.Column("object_keys", mysql.JSON(), nullable=False),
        sa.Column("meta", mysql.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["split_task_id"], ["split_tasks.id"]),
        sa.ForeignKeyConstraint(["annotation_task_id"], ["annotation_tasks.id"]),
        sa.PrimaryKeyConstraint("id"),
        mysql_charset="utf8mb4",
    )

    op.create_table(
        "annotations",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("sample_id", sa.BigInteger(), nullable=False),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("box", mysql.JSON(), nullable=True),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=True),
        sa.Column("annotator", sa.String(64), nullable=True),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("updated_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.ForeignKeyConstraint(["sample_id"], ["samples.id"]),
        sa.PrimaryKeyConstraint("id"),
        mysql_charset="utf8mb4",
    )

    # --- 特征提取 ---
    op.create_table(
        "feature_extractions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("version_id", sa.BigInteger(), nullable=False),
        sa.Column("ts_features", mysql.JSON(), nullable=False),
        sa.Column("vision_features", mysql.JSON(), nullable=False),
        sa.Column("audio_features", mysql.JSON(), nullable=False),
        sa.Column("unified_vector", mysql.JSON(), nullable=False),
        sa.Column("normalization", sa.String(16), nullable=False),
        sa.Column("format", sa.String(8), nullable=False),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.ForeignKeyConstraint(["version_id"], ["data_versions.id"]),
        sa.PrimaryKeyConstraint("id"),
        mysql_charset="utf8mb4",
    )

    # --- 数据集（current_version_id 外键延后建，环形依赖） ---
    op.create_table(
        "datasets",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("dataset_no", sa.String(64), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("task", sa.String(32), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("progress", sa.Numeric(5, 2), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("current_version_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("updated_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dataset_no", name="uq_datasets_dataset_no"),
        mysql_charset="utf8mb4",
    )

    op.create_table(
        "dataset_versions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("dataset_id", sa.BigInteger(), nullable=False),
        sa.Column("version_no", sa.String(16), nullable=False),
        sa.Column("split", mysql.JSON(), nullable=False),
        sa.Column("item_count", sa.Integer(), nullable=False),
        sa.Column("snapshot_id", sa.String(64), nullable=True),
        sa.Column("quality", mysql.JSON(), nullable=True),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.ForeignKeyConstraint(["dataset_id"], ["datasets.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "dataset_id", "version_no", name="uq_dataset_versions_dataset_version"
        ),
        mysql_charset="utf8mb4",
    )

    # 补齐 datasets.current_version_id 环形外键。
    op.create_foreign_key(
        "fk_datasets_current_version_id",
        "datasets",
        "dataset_versions",
        ["current_version_id"],
        ["id"],
    )

    op.create_table(
        "dataset_items",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("dataset_version_id", sa.BigInteger(), nullable=False),
        sa.Column("sample_id", sa.BigInteger(), nullable=False),
        sa.Column("split", sa.String(8), nullable=False),
        sa.ForeignKeyConstraint(["dataset_version_id"], ["dataset_versions.id"]),
        sa.ForeignKeyConstraint(["sample_id"], ["samples.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "dataset_version_id", "sample_id", name="uq_dataset_items_version_sample"
        ),
        mysql_charset="utf8mb4",
    )

    op.create_table(
        "dataset_build_tasks",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.BigInteger(), nullable=False),
        sa.Column("dataset_version_id", sa.BigInteger(), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
        sa.ForeignKeyConstraint(["dataset_version_id"], ["dataset_versions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", name="uq_dataset_build_tasks_job_id"),
        mysql_charset="utf8mb4",
    )

    # --- 模型版本 + 训练/测试/推理任务 ---
    op.create_table(
        "model_versions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("model_id", sa.BigInteger(), nullable=False),
        sa.Column("version_no", sa.String(16), nullable=False),
        sa.Column("metric", mysql.JSON(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="实验版本"),
        sa.Column("file_key", sa.String(255), nullable=True),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.ForeignKeyConstraint(["model_id"], ["models.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "model_id", "version_no", name="uq_model_versions_model_version"
        ),
        mysql_charset="utf8mb4",
    )

    op.create_table(
        "training_tasks",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.BigInteger(), nullable=False),
        sa.Column("dataset_version_id", sa.BigInteger(), nullable=False),
        sa.Column("base_model_id", sa.BigInteger(), nullable=True),
        sa.Column("hyperparams", mysql.JSON(), nullable=False),
        sa.Column("metrics", mysql.JSON(), nullable=True),
        sa.Column("loss_curve", mysql.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
        sa.ForeignKeyConstraint(["dataset_version_id"], ["dataset_versions.id"]),
        sa.ForeignKeyConstraint(["base_model_id"], ["model_versions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", name="uq_training_tasks_job_id"),
        mysql_charset="utf8mb4",
    )

    op.create_table(
        "test_tasks",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.BigInteger(), nullable=False),
        sa.Column("model_version_id", sa.BigInteger(), nullable=False),
        sa.Column("dataset_version_id", sa.BigInteger(), nullable=False),
        sa.Column("tasks", mysql.JSON(), nullable=False),
        sa.Column("metrics", mysql.JSON(), nullable=True),
        sa.Column("confusion_matrix", mysql.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
        sa.ForeignKeyConstraint(["model_version_id"], ["model_versions.id"]),
        sa.ForeignKeyConstraint(["dataset_version_id"], ["dataset_versions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", name="uq_test_tasks_job_id"),
        mysql_charset="utf8mb4",
    )

    op.create_table(
        "inference_tasks",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.BigInteger(), nullable=False),
        sa.Column("model_version_id", sa.BigInteger(), nullable=False),
        sa.Column("input_type", sa.String(16), nullable=False),
        sa.Column("input_key", sa.String(255), nullable=False),
        sa.Column("result", mysql.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
        sa.ForeignKeyConstraint(["model_version_id"], ["model_versions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", name="uq_inference_tasks_job_id"),
        mysql_charset="utf8mb4",
    )

    # --- 审计日志 ---
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("resource_type", sa.String(32), nullable=False),
        sa.Column("resource_id", sa.String(64), nullable=True),
        sa.Column("detail", mysql.JSON(), nullable=True),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        mysql_charset="utf8mb4",
    )

    # --- 非唯一索引（唯一约束已自带索引） ---
    op.create_index("ix_data_records_source", "data_records", ["source"])
    op.create_index("ix_data_records_machine", "data_records", ["machine"])
    op.create_index("ix_data_records_quality", "data_records", ["quality"])
    op.create_index("ix_data_versions_record_id", "data_versions", ["record_id"])
    op.create_index("ix_data_versions_created_at", "data_versions", ["created_at"])
    op.create_index("ix_validation_reports_version_id", "validation_reports", ["version_id"])
    op.create_index("ix_jobs_type", "jobs", ["type"])
    op.create_index("ix_jobs_status", "jobs", ["status"])
    op.create_index("ix_alignment_tasks_version_id", "alignment_tasks", ["version_id"])
    op.create_index("ix_split_tasks_version_id", "split_tasks", ["version_id"])
    op.create_index("ix_samples_split_task_id", "samples", ["split_task_id"])
    op.create_index("ix_samples_annotation_task_id", "samples", ["annotation_task_id"])
    op.create_index("ix_annotation_tasks_split_task_id", "annotation_tasks", ["split_task_id"])
    op.create_index("ix_annotations_sample_id", "annotations", ["sample_id"])
    op.create_index("ix_feature_extractions_version_id", "feature_extractions", ["version_id"])
    op.create_index("ix_dataset_versions_dataset_id", "dataset_versions", ["dataset_id"])
    op.create_index("ix_dataset_items_dataset_version_id", "dataset_items", ["dataset_version_id"])
    op.create_index("ix_model_versions_model_id", "model_versions", ["model_id"])
    op.create_index("ix_training_tasks_dataset_version_id", "training_tasks", ["dataset_version_id"])
    op.create_index("ix_test_tasks_model_version_id", "test_tasks", ["model_version_id"])
    op.create_index("ix_test_tasks_dataset_version_id", "test_tasks", ["dataset_version_id"])
    op.create_index("ix_inference_tasks_model_version_id", "inference_tasks", ["model_version_id"])
    op.create_index(
        "ix_dataset_build_tasks_dataset_version_id", "dataset_build_tasks", ["dataset_version_id"]
    )
    op.create_index("ix_audit_logs_user_id", "audit_logs", ["user_id"])
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"])
    op.create_index(
        "ix_audit_logs_resource_type_resource_id",
        "audit_logs",
        ["resource_type", "resource_id"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    # 先拆两处环形外键，再按依赖逆序删表。
    op.drop_constraint(
        "fk_data_records_latest_version_id", "data_records", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_datasets_current_version_id", "datasets", type_="foreignkey"
    )

    op.drop_table("audit_logs")
    op.drop_table("inference_tasks")
    op.drop_table("test_tasks")
    op.drop_table("training_tasks")
    op.drop_table("model_versions")
    op.drop_table("dataset_build_tasks")
    op.drop_table("dataset_items")
    op.drop_table("dataset_versions")
    op.drop_table("datasets")
    op.drop_table("feature_extractions")
    op.drop_table("annotations")
    op.drop_table("samples")
    op.drop_table("annotation_tasks")
    op.drop_table("split_tasks")
    op.drop_table("alignment_tasks")
    op.drop_table("validation_rule_results")
    op.drop_table("validation_reports")
    op.drop_table("data_versions")
    op.drop_table("data_records")
    op.drop_table("label_categories")
    op.drop_table("models")
    op.drop_table("jobs")
    op.drop_table("users")
