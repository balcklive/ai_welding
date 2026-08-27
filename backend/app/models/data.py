"""核心数据实体：用户 / 焊缝数据 / 数据版本 / 核验报告 / 核验规则 / 审计日志。

对应 `docs/数据库设计.md` §3.1–§3.5、§3.23。列名/类型/约束与文档逐列一致。
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import JSON, Column, DateTime, Index, Numeric, UniqueConstraint
from sqlmodel import Field, SQLModel


class User(SQLModel, table=True):
    """§3.1 users 用户"""

    __tablename__ = "users"

    id: int | None = Field(default=None, primary_key=True)
    username: str = Field(max_length=64, unique=True)
    password_hash: str = Field(max_length=255)
    display_name: str = Field(max_length=64)
    role: str = Field(max_length=32, default="admin")
    avatar: str | None = Field(default=None, max_length=255)
    # NOT NULL 由迁移保证；模型允许 None，时间由服务写入。
    created_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True))
    )


class DataRecord(SQLModel, table=True):
    """§3.2 data_records 焊缝数据登记（一条焊缝 = 一条记录）"""

    __tablename__ = "data_records"

    id: int | None = Field(default=None, primary_key=True)
    weld_id: str = Field(max_length=64, unique=True)
    weld_name: str | None = Field(default=None, max_length=128)
    registration_no: str = Field(max_length=64, unique=True)
    source: str = Field(max_length=64, index=True)
    collected_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True))
    )
    machine: str | None = Field(default=None, max_length=64, index=True)
    weld_method: str | None = Field(default=None, max_length=32)
    material: str | None = Field(default=None, max_length=64)
    thickness: str | None = Field(default=None, max_length=32)
    current_voltage: str | None = Field(default=None, max_length=32)
    sample_rate: str | None = Field(default=None, max_length=32)
    product: str | None = Field(default=None, max_length=128)
    # 每条登记必须归属一个数据集；历史数据通过迁移清理/归属后不允许为空。
    dataset_id: int | None = Field(default=None, foreign_key="datasets.id", index=True)
    # 登记创建时初始 []，挂载原始文件时按文件类型推导回填。
    modalities: list = Field(default_factory=list, sa_column=Column(JSON))
    quality: str = Field(max_length=16, default="待复核", index=True)
    operator: str | None = Field(default=None, max_length=64)
    storage_bytes: int | None = Field(default=None)
    # 反规范化：最新版本指针，指向 data_versions.id；与 data_versions.record_id 构成环形 FK，属预期。
    latest_version_id: int | None = Field(
        default=None, foreign_key="data_versions.id"
    )
    created_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True))
    )
    updated_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True))
    )


class DataVersion(SQLModel, table=True):
    """§3.3 data_versions 数据版本（同焊缝内版本号唯一；加工去重靠 request_key）"""

    __tablename__ = "data_versions"
    __table_args__ = (
        UniqueConstraint(
            "record_id", "version_no", name="uq_data_versions_record_version"
        ),
        UniqueConstraint(
            "record_id", "action", "request_key", name="uq_data_versions_record_action_req"
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    record_id: int = Field(foreign_key="data_records.id", index=True)
    version_no: str = Field(max_length=16)
    action: str = Field(max_length=32)
    operator: str | None = Field(default=None, max_length=64)
    note: str | None = Field(default=None, max_length=255)
    request_key: str | None = Field(default=None, max_length=64)
    object_keys: list | None = Field(default=None, sa_column=Column(JSON))
    created_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), index=True),
    )


class ValidationReport(SQLModel, table=True):
    """§3.4 validation_reports 核验报告"""

    __tablename__ = "validation_reports"

    id: int | None = Field(default=None, primary_key=True)
    version_id: int = Field(foreign_key="data_versions.id", index=True)
    score: Decimal = Field(sa_column=Column(Numeric(5, 2)))
    passed: int = Field(default=0)
    warning: int = Field(default=0)
    failed: int = Field(default=0)
    duration: Decimal | None = Field(
        default=None, sa_column=Column(Numeric(8, 2))
    )
    created_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True))
    )


class ValidationRuleResult(SQLModel, table=True):
    """§3.5 validation_rule_results 核验规则明细（15 项）"""

    __tablename__ = "validation_rule_results"

    id: int | None = Field(default=None, primary_key=True)
    report_id: int = Field(foreign_key="validation_reports.id", index=True)
    rule_name: str = Field(max_length=64)
    status: str = Field(max_length=16)
    message: str | None = Field(default=None, max_length=255)


class AuditLog(SQLModel, table=True):
    """§3.23 audit_logs 审计日志"""

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index(
            "ix_audit_logs_resource_type_resource_id",
            "resource_type",
            "resource_id",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: int | None = Field(default=None, foreign_key="users.id", index=True)
    action: str = Field(max_length=64)
    resource_type: str = Field(max_length=32)
    resource_id: str | None = Field(default=None, max_length=255)
    detail: dict | None = Field(default=None, sa_column=Column(JSON))
    created_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), index=True),
    )
