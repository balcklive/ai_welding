"""Task 6：启动 seed 幂等性与演示数据对齐断言（内存 SQLite）。

覆盖：
1. `seed_all` 执行两次 → 各表数量不翻倍（幂等）；label_categories==6（5 缺陷 + 熔池）、welds==4、models==3、datasets==3。
2. 管理员（林工/admin）存在，`verify_password(admin_password)` 为 True。
3. 0248 有 4 个版本（v1.0..v1.3），`latest_version_id` 指向 v1.3。
4. 0248 有 1 条核验报告（93.3/14/1/0/2.8）+ 15 条规则明细，第 9 项「视频帧率稳定性」= warning。
5. 0245（异常）版本链停在 v1.0；标注页演示数据（AN-0248 + 2 样本 + 2 标注）就绪。
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, select

from app.core.config import settings
from app.core.security import verify_password
from app.core.seed import VALIDATION_RULES, seed_all
from app.models import (
    Annotation,
    AnnotationTask,
    AuditLog,
    DataRecord,
    DataVersion,
    Dataset,
    DatasetVersion,
    LabelCategory,
    Model,
    ModelVersion,
    Sample,
    SplitTask,
    User,
    ValidationReport,
    ValidationRuleResult,
)


@pytest.fixture()
def engine() -> Engine:
    """每个测试独立的内存 SQLite 引擎（建出全部 23 张表）。"""
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(eng)
    return eng


def _count(session: Session, model) -> int:
    return len(list(session.exec(select(model)).all()))


def test_seed_all_idempotent(engine: Engine) -> None:
    """seed_all 跑两遍，各类记录数量不翻倍；核心数量符合前端 mock。"""
    with Session(engine) as session:
        seed_all(session)
        counts = {
            LabelCategory: _count(session, LabelCategory),
            DataRecord: _count(session, DataRecord),
            DataVersion: _count(session, DataVersion),
            Model: _count(session, Model),
            ModelVersion: _count(session, ModelVersion),
            Dataset: _count(session, Dataset),
            DatasetVersion: _count(session, DatasetVersion),
            User: _count(session, User),
            ValidationReport: _count(session, ValidationReport),
            ValidationRuleResult: _count(session, ValidationRuleResult),
            SplitTask: _count(session, SplitTask),
            AnnotationTask: _count(session, AnnotationTask),
            Sample: _count(session, Sample),
            Annotation: _count(session, Annotation),
            AuditLog: _count(session, AuditLog),
        }

        seed_all(session)  # 第二次执行：数量不变

        for model, n in counts.items():
            assert _count(session, model) == n, f"{model.__name__} 翻倍: {n}"

        assert counts[LabelCategory] == 6
        assert counts[DataRecord] == 4
        assert counts[Model] == 3
        assert counts[Dataset] == 3


def test_admin_seeded_and_password_verifies(engine: Engine) -> None:
    with Session(engine) as session:
        seed_all(session)
        admin = (
            session.exec(select(User).where(User.username == settings.admin_username)).first()
        )
        assert admin is not None
        assert admin.display_name == "林工"
        assert admin.role == "admin"
        assert verify_password(settings.admin_password, admin.password_hash) is True


def test_weld_0248_four_versions_latest_v13(engine: Engine) -> None:
    with Session(engine) as session:
        seed_all(session)
        record = (
            session.exec(select(DataRecord).where(DataRecord.weld_id == "WLD-20260815-0248")).first()
        )
        assert record is not None
        assert record.quality == "通过"
        versions = session.exec(
            select(DataVersion).where(DataVersion.record_id == record.id)
        ).all()
        assert len(versions) == 4
        assert sorted(v.version_no for v in versions) == ["v1.0", "v1.1", "v1.2", "v1.3"]
        latest = session.get(DataVersion, record.latest_version_id)
        assert latest is not None
        assert latest.version_no == "v1.3"


def test_weld_0248_validation_report_and_15_rules(engine: Engine) -> None:
    with Session(engine) as session:
        seed_all(session)
        report = session.exec(select(ValidationReport)).first()
        assert report is not None
        assert float(report.score) == 93.3
        assert report.passed == 14
        assert report.warning == 1
        assert report.failed == 0
        assert float(report.duration) == 2.8

        rules = session.exec(
            select(ValidationRuleResult).where(
                ValidationRuleResult.report_id == report.id
            ).order_by(ValidationRuleResult.id)
        ).all()
        assert len(rules) == 15
        assert [r.rule_name for r in rules] == VALIDATION_RULES
        assert all(r.status == "passed" for r in rules if r.rule_name != "视频帧率稳定性")
        warning_rule = next(r for r in rules if r.rule_name == "视频帧率稳定性")
        assert warning_rule.status == "warning"


def test_weld_0245_abnormal_chain_stops_at_v10(engine: Engine) -> None:
    with Session(engine) as session:
        seed_all(session)
        record = (
            session.exec(select(DataRecord).where(DataRecord.weld_id == "WLD-20260814-0245")).first()
        )
        assert record is not None
        assert record.quality == "异常"
        versions = session.exec(
            select(DataVersion).where(DataVersion.record_id == record.id)
        ).all()
        assert [v.version_no for v in versions] == ["v1.0"]
        latest = session.get(DataVersion, record.latest_version_id)
        assert latest.version_no == "v1.0"


def test_annotation_demo_present(engine: Engine) -> None:
    """标注页演示数据：AN-0248 标注任务 + 2 个样本 + 2 条标注（焊瘤/气孔）。"""
    with Session(engine) as session:
        seed_all(session)
        task = session.exec(select(AnnotationTask)).first()
        assert task is not None
        assert task.name == "AN-0248"
        samples = session.exec(select(Sample)).all()
        assert len(samples) == 2
        annotations = session.exec(select(Annotation)).all()
        assert len(annotations) == 2
        assert {a.category for a in annotations} == {"焊瘤", "气孔"}
        assert all(a.annotator == "林工" for a in annotations)


def test_datasets_and_models_have_versions(engine: Engine) -> None:
    """每个数据集/模型都有版本，且指针（current_version_id / file_key）就位。"""
    with Session(engine) as session:
        seed_all(session)
        for ds in session.exec(select(Dataset)).all():
            version = session.get(DatasetVersion, ds.current_version_id)
            assert version is not None
            assert version.dataset_id == ds.id
            assert "train" in version.split and "val" in version.split and "test" in version.split
            assert version.quality is not None

        for model in session.exec(select(Model)).all():
            versions = session.exec(
                select(ModelVersion).where(ModelVersion.model_id == model.id)
            ).all()
            assert len(versions) == 1
            assert versions[0].file_key == f"models/{versions[0].id}/weights.pt"
