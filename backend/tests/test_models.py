"""Task 2：SQLModel 模型建表 / 写入 / 约束 / JSON 往返。

使用**内存 SQLite** 引擎 + `SQLModel.metadata.create_all`，绝不连远程 MySQL。
覆盖：
1. 23 张表全部建出；
2. User + DataRecord + DataVersion 插入提交成功，`modalities` JSON 往返；
3. 同一 `(record_id, version_no)` 二次插入触发 `IntegrityError`（复合唯一）；
4. `DataRecord.latest_version_id` 可指向已建版本。
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel

from app.models import (
    AuditLog,
    DataRecord,
    DataVersion,
    User,
    ValidationReport,
    ValidationRuleResult,
)


@pytest.fixture()
def engine() -> Engine:
    """每个测试独立的内存 SQLite 引擎（建出全部 23 张表）。

    data_records↔data_versions 环形 FK（latest_version_id / record_id）
    导致 drop_all 无法排序表，故每次用全新引擎避免重复 DROP。
    """
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(eng)
    return eng


def test_all_23_tables_created(engine: Engine) -> None:
    from sqlalchemy import inspect

    tables = set(inspect(engine).get_table_names())
    expected = {
        "users",
        "data_records",
        "data_versions",
        "validation_reports",
        "validation_rule_results",
        "jobs",
        "alignment_tasks",
        "split_tasks",
        "samples",
        "annotation_tasks",
        "annotations",
        "label_categories",
        "feature_extractions",
        "datasets",
        "dataset_versions",
        "dataset_items",
        "models",
        "model_versions",
        "training_tasks",
        "test_tasks",
        "inference_tasks",
        "dataset_build_tasks",
        "audit_logs",
    }
    assert expected <= tables, expected - tables
    assert len(expected) == 23


def test_user_data_record_version_insert_and_json_roundtrip(engine: Engine) -> None:
    with Session(engine) as session:
        user = User(
            username="lin_eng",
            password_hash="hash",
            display_name="林工",
            role="admin",
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        assert user.id is not None

        record = DataRecord(
            weld_id="WLD-20260823-001",
            weld_name="A 型试件",
            registration_no="REG-20260823-001",
            source="产线相机 · 03号",
            modalities=["video", "timeseries"],
            quality="待复核",
        )
        session.add(record)
        session.commit()
        session.refresh(record)
        assert record.modalities == ["video", "timeseries"]

        version = DataVersion(
            record_id=record.id,
            version_no="v1.0",
            action="原始数据",
            object_keys=["raw/video.mp4", "raw/timeseries.csv"],
        )
        session.add(version)
        session.commit()
        session.refresh(version)
        assert version.object_keys == ["raw/video.mp4", "raw/timeseries.csv"]


def test_composite_unique_record_version_raises(engine: Engine) -> None:
    with Session(engine) as session:
        record = DataRecord(
            weld_id="WLD-20260823-002",
            registration_no="REG-20260823-002",
            source="产线相机 · 01号",
        )
        session.add(record)
        session.commit()
        session.refresh(record)

        session.add(
            DataVersion(record_id=record.id, version_no="v1.0", action="原始数据")
        )
        session.commit()

        session.add(
            DataVersion(record_id=record.id, version_no="v1.0", action="人工修正")
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_latest_version_id_can_point_to_created_version(engine: Engine) -> None:
    with Session(engine) as session:
        record = DataRecord(
            weld_id="WLD-20260823-003",
            registration_no="REG-20260823-003",
            source="产线相机 · 01号",
        )
        session.add(record)
        session.commit()
        session.refresh(record)

        version = DataVersion(
            record_id=record.id, version_no="v1.0", action="原始数据"
        )
        session.add(version)
        session.commit()
        session.refresh(version)

        # 反规范化指针：最新版本指向刚建的版本。
        record.latest_version_id = version.id
        session.add(record)
        session.commit()
        session.refresh(record)
        assert record.latest_version_id == version.id


def test_related_rows_insertable(engine: Engine) -> None:
    """审计 + 核验报告 + 核验规则明细同事务可写入（含 DECIMAL/JSON 列）。"""
    from decimal import Decimal

    with Session(engine) as session:
        user = User(
            username="ops",
            password_hash="hash",
            display_name="运维",
            role="viewer",
        )
        record = DataRecord(
            weld_id="WLD-20260823-004",
            registration_no="REG-20260823-004",
            source="手工导入",
        )
        session.add(user)
        session.add(record)
        session.commit()
        session.refresh(record)
        session.refresh(user)

        version = DataVersion(
            record_id=record.id, version_no="v1.0", action="原始数据"
        )
        session.add(version)
        session.commit()
        session.refresh(version)

        session.add(
            AuditLog(
                user_id=user.id,
                action="create",
                resource_type="weld",
                resource_id=record.weld_id,
                detail={"reg": record.registration_no},
            )
        )
        report = ValidationReport(
            version_id=version.id,
            score=Decimal("95.50"),
            passed=14,
            warning=1,
            failed=0,
            duration=Decimal("3.25"),
        )
        session.add(report)
        session.commit()
        session.refresh(report)

        session.add(
            ValidationRuleResult(
                report_id=report.id,
                rule_name="图像文件完整性",
                status="passed",
            )
        )
        session.commit()
