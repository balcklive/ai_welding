"""Task 2：SQLModel 模型建表 / 写入 / 约束 / JSON 往返。

使用**内存 SQLite** 引擎 + `SQLModel.metadata.create_all`，绝不连远程 MySQL。
覆盖：
1. 23 张表全部建出，且逐表索引与模型元数据一致（SQLAlchemy inspector）；
2. 手写迁移 `0001_initial.py` 的 create_index 与模型元数据索引完全对齐（防索引漂移）；
3. User + DataRecord + DataVersion 插入提交成功，`modalities` JSON 往返；
4. 同一 `(record_id, version_no)` 二次插入触发 `IntegrityError`（复合唯一）；
5. `DataRecord.latest_version_id` 可指向已建版本。
"""

from pathlib import Path
import time
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, select

import app.jobs.executor as executor_mod
from app.api.deps import get_current_user
from app.core.config import settings
from app.core.db import get_session
from app.core.seed import seed_all
from app.jobs.executor import run_job
from app.main import app
from app.models import (
    Annotation,
    AuditLog,
    DataRecord,
    DataVersion,
    Dataset,
    DatasetItem,
    DatasetVersion,
    Job,
    Model,
    ModelVersion,
    Sample,
    TrainingTask,
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

    insp = inspect(engine)
    tables = set(insp.get_table_names())
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

    # 逐表索引名一致性：模型声明（index=True / Index()）的索引必须已在库里实际建出，
    # 防止模型加了索引但建表/迁移漏掉（例如曾漏掉 ix_validation_rule_results_report_id）。
    for table_name, table in SQLModel.metadata.tables.items():
        model_idx = {ix.name for ix in table.indexes}
        db_idx = {ix["name"] for ix in insp.get_indexes(table_name)}
        assert model_idx <= db_idx, (
            f"{table_name}: 模型声明但 SQLite 未建出 {sorted(model_idx - db_idx)}"
        )


def test_migration_indexes_match_model_metadata() -> None:
    """全部手写迁移的 create_index 必须与模型元数据索引**完全对齐**。

    迁移是手写的（远程 MySQL 不可达），此处直接解析 `versions/*.py` 全部迁移，
    防止模型新增 index=True/Index() 而迁移遗漏（或反之）的索引漂移在 CI 中漏网。
    """
    import re

    versions_dir = Path(__file__).resolve().parents[1] / "alembic" / "versions"
    text = "\n".join(
        p.read_text(encoding="utf-8")
        for p in sorted(versions_dir.glob("*.py"))
        if p.name != "__init__.py"
    )

    mig_indexes: dict[str, set[str]] = {}
    for m in re.finditer(
        r'op\.create_index\(\s*["\']([^"\']+)["\'],\s*["\']([^"\']+)["\'],\s*\[([^\]]*)\]',
        text,
    ):
        name, table = m.group(1), m.group(2)
        mig_indexes.setdefault(table, set()).add(name)

    model_indexes: dict[str, set[str]] = {}
    for table_name, table in SQLModel.metadata.tables.items():
        idx = {ix.name for ix in table.indexes}
        if idx:
            model_indexes[table_name] = idx

    assert mig_indexes == model_indexes, {
        "migration 独有": sorted(set(mig_indexes) - set(model_indexes)),
        "model 独有": sorted(set(model_indexes) - set(mig_indexes)),
        "同表索引差异": {
            t: sorted(model_indexes.get(t, set()) ^ mig_indexes.get(t, set()))
            for t in set(model_indexes) | set(mig_indexes)
            if model_indexes.get(t, set()) != mig_indexes.get(t, set())
        },
    }


def test_alembic_upgrade_online_real_path_executes_0003(monkeypatch) -> None:
    admin_db = settings.mysql_database
    test_db = f"{admin_db}_alembic_{uuid4().hex[:8]}"
    admin_url = settings.mysql_url
    original_db = settings.mysql_database
    root = Path(__file__).resolve().parents[1]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "alembic"))

    admin_engine = create_engine(admin_url.rsplit(f"/{admin_db}?", 1)[0] + "/mysql?charset=utf8mb4")
    with admin_engine.connect() as conn:
        conn.execute(text(f"CREATE DATABASE `{test_db}` CHARACTER SET utf8mb4"))
        conn.commit()

    try:
        monkeypatch.setattr(settings, "mysql_database", test_db)
        command.upgrade(cfg, "0002")
        command.upgrade(cfg, "0003")
        command.upgrade(cfg, "head")

        migrated_engine = create_engine(settings.mysql_url)
        with migrated_engine.connect() as conn:
            assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0005"
            for table_name, expected_columns in {
                "data_versions": {"request_key": "YES"},
                "alignment_tasks": {"request_key": "YES", "active_request_key": "YES"},
                "split_tasks": {"request_key": "YES", "active_request_key": "YES"},
            }.items():
                columns = {
                    row[0]: row[1]
                    for row in conn.execute(
                        text(
                            f"""
                            SELECT column_name, is_nullable
                            FROM information_schema.columns
                            WHERE table_schema = DATABASE()
                              AND table_name = '{table_name}'
                              AND column_name IN ('request_key', 'active_request_key')
                            """
                        )
                    )
                }
                assert columns == expected_columns

            alignment_constraints = {
                row[0]
                for row in conn.execute(
                    text(
                        """
                        SELECT constraint_name
                        FROM information_schema.table_constraints
                        WHERE table_schema = DATABASE()
                          AND table_name = 'alignment_tasks'
                          AND constraint_type = 'UNIQUE'
                        """
                    )
                )
            }
            assert "uq_alignment_tasks_active_request_key" in alignment_constraints
            assert "uq_alignment_tasks_request_key" not in alignment_constraints

            split_constraints = {
                row[0]
                for row in conn.execute(
                    text(
                        """
                        SELECT constraint_name
                        FROM information_schema.table_constraints
                        WHERE table_schema = DATABASE()
                          AND table_name = 'split_tasks'
                          AND constraint_type = 'UNIQUE'
                        """
                    )
                )
            }
            assert "uq_split_tasks_active_request_key" in split_constraints
            assert "uq_split_tasks_request_key" not in split_constraints

            audit_resource_id = conn.execute(
                text(
                    """
                    SELECT character_maximum_length
                    FROM information_schema.columns
                    WHERE table_schema = DATABASE()
                      AND table_name = 'audit_logs'
                      AND column_name = 'resource_id'
                    """
                )
            ).scalar()
            assert audit_resource_id == 255
        migrated_engine.dispose()
    finally:
        settings.mysql_database = original_db
        with admin_engine.connect() as conn:
            conn.execute(text(f"DROP DATABASE IF EXISTS `{test_db}`"))
            conn.commit()
        admin_engine.dispose()


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


# ═════════════════════════════════════════════════════════════════════════
# Task 16：模型中心 API（模型仓库 / 训练 / 测试 / 推理，模拟）
#
# 同 test_datasets.py 基础设施：内存 SQLite + StaticPool + 真实 app TestClient；
# `seed_all` 造演示数据（3 模型 + 3 数据集 + 4 焊缝）后 override `get_session` /
# `get_current_user`；`app.jobs.executor.SessionLocal` 指到同一测试引擎（`run_job`
# 用独立 session，不启动后台轮询线程）；`app.storage.get_storage` → 假存储
# （记录权重写，不连真实 MinIO）。
# ═════════════════════════════════════════════════════════════════════════

client = TestClient(app)

SEED_MODEL_1 = "焊接异常检测模型"  # v1.8 生产候选（model_id=1, version_id=1）
SEED_MODEL_2 = "熔池分割模型"      # v2.1 训练中（model_id=2, version_id=2）
SEED_MODEL_3 = "质量预测模型"      # v0.9 实验版本（model_id=3, version_id=3）


class FakeStorage:
    """记录上传/读取的假存储（断言权重写与推理输入校验，不连 MinIO）。"""

    def __init__(self) -> None:
        self.uploads: list[tuple] = []
        self.blobs: dict[str, bytes] = {}

    def upload_stream(self, object_key, fileobj, size, content_type):
        data = fileobj.read()
        self.uploads.append((object_key, size, content_type, data))
        self.blobs[object_key] = data
        return object_key

    def get_object(self, object_key):
        return self.blobs[object_key]

    def stat_object(self, object_key):
        return len(self.blobs[object_key])


@pytest.fixture()
def db_engine():
    """内存 SQLite + StaticPool：seed 演示数据，每用例全新引擎（环形 FK 不便 drop_all）。"""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        seed_all(session)
    yield engine
    engine.dispose()


@pytest.fixture()
def override_get_session(db_engine):
    """每请求开一个独立 Session（与真实 get_session 语义一致），退出即 close。"""

    def _override():
        with Session(db_engine) as session:
            yield session

    app.dependency_overrides[get_session] = _override
    yield
    app.dependency_overrides.pop(get_session, None)


@pytest.fixture()
def override_get_current_user():
    """假登录：get_current_user 直接返回一个 User，免 seed / 免签 token。"""
    dummy = User(
        id=1,
        username="lin_eng",
        password_hash="not-a-real-hash",
        display_name="林工",
        role="admin",
    )

    def _override() -> User:
        return dummy

    app.dependency_overrides[get_current_user] = _override
    yield
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture()
def executor_sessionlocal(db_engine, monkeypatch):
    """把 executor 的 SessionLocal 指到同一测试引擎（run_job 用独立 session，不启动线程）。"""
    monkeypatch.setattr(
        executor_mod,
        "SessionLocal",
        sessionmaker(bind=db_engine, class_=Session, expire_on_commit=False),
    )


@pytest.fixture()
def fake_storage(monkeypatch):
    """假存储：monkeypatch `app.storage.get_storage`（权重写走这里，不连 MinIO）。"""
    storage = FakeStorage()
    monkeypatch.setattr("app.storage.get_storage", lambda: storage)
    return storage


# ---------- 模型仓库：列表 / 汇总 / 详情 / 新建 ----------


def test_list_models_summary(override_get_session, override_get_current_user) -> None:
    data = client.get("/api/v1/models").json()["data"]
    summary = data["summary"]
    assert summary["total"] == 3
    assert summary["prod_candidates"] == 1  # 仅「焊接异常检测模型」为生产候选
    assert "recent_training" in summary  # 初始无训练任务 → None
    assert summary["recent_training"] is None

    models = data["models"]
    assert len(models) == 3
    names = {m["name"] for m in models}
    assert names == {SEED_MODEL_1, SEED_MODEL_2, SEED_MODEL_3}
    by_name = {m["name"]: m for m in models}
    m1 = by_name[SEED_MODEL_1]
    assert m1["version"] == "v1.8" and m1["status"] == "生产候选"
    assert m1["metric"] == {"f1": 0.955}
    assert m1["latest_version_id"] == m1["id"] or m1["latest_version_id"]
    for m in models:
        assert m["id"] and m["type"]
        assert "metric" in m and "status" in m and "file_key" in m


def test_get_model_detail(override_get_session, override_get_current_user) -> None:
    data = client.get("/api/v1/models/1").json()["data"]
    assert data["name"] == SEED_MODEL_1
    assert data["type"] == "时序分类"
    assert len(data["versions"]) == 1
    version = data["versions"][0]
    assert version["version_no"] == "v1.8"
    assert version["status"] == "生产候选"
    assert version["file_key"] == f"models/{version['id']}/weights.pt"


def test_create_model_and_duplicate(
    override_get_session, override_get_current_user
) -> None:
    resp = client.post(
        "/api/v1/models",
        json={"name": "新缺陷模型", "type": "目标检测", "description": "测试用"},
    )
    assert resp.status_code == 200, resp.text[:300]
    model = resp.json()["data"]
    assert model["id"] and model["name"] == "新缺陷模型"
    assert model["type"] == "目标检测" and model["description"] == "测试用"

    # 同名 → 409 冲突（契约 §1.3）
    resp = client.post("/api/v1/models", json={"name": "新缺陷模型", "type": "目标检测"})
    assert resp.status_code == 409 and resp.json()["code"] == 40900

    # 空名 / 空类型 → 400
    resp = client.post("/api/v1/models", json={"name": "", "type": "目标检测"})
    assert resp.status_code == 400 and resp.json()["code"] == 40000
    resp = client.post("/api/v1/models", json={"name": "x", "type": "  "})
    assert resp.status_code == 400 and resp.json()["code"] == 40000


# ---------- 状态流转 ----------


def test_patch_version_status_flow(
    override_get_session, override_get_current_user
) -> None:
    # 生产候选 → 实验版本
    resp = client.patch("/api/v1/models/1/versions/1", json={"status": "实验版本"})
    assert resp.status_code == 200, resp.text[:300]
    assert resp.json()["data"]["status"] == "实验版本"

    # 实验版本 → 生产候选（带 note，note 不落库但接口接受）
    resp = client.patch(
        "/api/v1/models/1/versions/1",
        json={"status": "生产候选", "note": "跨板材验证通过"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "生产候选"

    # 非法状态 → 400（白名单 生产候选/训练中/实验版本）
    resp = client.patch("/api/v1/models/1/versions/1", json={"status": "已上线"})
    assert resp.status_code == 400 and resp.json()["code"] == 40000

    # 落库确认
    data = client.get("/api/v1/models/1").json()["data"]
    assert data["versions"][0]["status"] == "生产候选"


# ---------- 训练任务（端到端） ----------


def _make_dataset_version(
    db_engine,
    *,
    dataset_no: str,
    task: str = "目标检测",
    sample_keys: list[str] | None = None,
    split: dict | None = None,
    empty_label_rate: float = 0.0,
) -> int:
    sample_keys = sample_keys or ["processed/demo/sample.csv"]
    split = split or {"train": 1, "val": 0, "test": 1}
    with Session(db_engine) as session:
        dataset = Dataset(
            dataset_no=dataset_no,
            name=dataset_no,
            task=task,
            sample_count=len(sample_keys),
            progress=100,
            status="可训练",
        )
        session.add(dataset)
        session.commit()
        session.refresh(dataset)
        version = DatasetVersion(
            dataset_id=dataset.id,
            version_no="v1.1",
            split=split,
            item_count=len(sample_keys),
            quality={
                "repeat_rate": 0.0,
                "empty_label_rate": empty_label_rate,
                "dimension_missing_rate": 0.0,
            },
        )
        session.add(version)
        session.commit()
        session.refresh(version)
        dataset.current_version_id = version.id
        session.add(dataset)
        for idx, key in enumerate(sample_keys):
            sample = Sample(object_keys=[key], meta={"record_id": 1, "idx": idx})
            session.add(sample)
            session.commit()
            session.refresh(sample)
            session.add(
                DatasetItem(
                    dataset_version_id=version.id,
                    sample_id=sample.id,
                    split="train" if idx < max(1, len(sample_keys) - 1) else "test",
                )
            )
            if empty_label_rate == 0.0:
                session.add(Annotation(sample_id=sample.id, category="气孔", box=[1, 2, 3, 4]))
        session.commit()
        return version.id


def _tiny_png_bytes() -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
        b"\x00\x00\x00\x0cIDATx\x9cc```\x00\x00\x00\x04\x00\x01\x0b\xe7\x02\x9d"
        b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )


def _tiny_mp4_bytes() -> bytes:
    return b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom"


def test_training_end_to_end(
    db_engine,
    override_get_session,
    override_get_current_user,
    executor_sessionlocal,
    fake_storage,
) -> None:
    # dataset_version_id=1（seed 焊接缺陷检测集 v1.3），base_model_id=1（焊接异常检测模型 v1.8）
    resp = client.post(
        "/api/v1/training-tasks",
        json={
            "dataset_version_id": 1,
            "base_model_id": 1,
            "epochs": 20,
            "batch_size": 16,
            "learning_rate": 0.001,
            "val_ratio": 0.2,
            "optimizer": "adamw",  # 高级参数 → hyperparams
        },
    )
    assert resp.status_code == 200, resp.text[:300]
    job_id = resp.json()["data"]["job_id"]
    assert job_id.startswith("job_")

    pending = client.get(f"/api/v1/jobs/{job_id}").json()["data"]
    assert pending["type"] == "training" and pending["status"] == "pending"

    run_job(job_id)

    done = client.get(f"/api/v1/training-tasks/{job_id}").json()["data"]
    assert done["status"] == "succeeded"
    assert done["progress"] == 100
    result = done["result"]
    metrics = result["metrics"]
    assert set(metrics) == {"mAP50", "precision", "recall"}
    assert 0.9 <= metrics["mAP50"] <= 0.99
    assert 0.9 <= metrics["precision"] <= 0.99
    assert 0.9 <= metrics["recall"] <= 0.99
    loss_curve = result["loss_curve"]
    assert set(loss_curve) == {"train", "val"}
    assert len(loss_curve["train"]) == 20 and len(loss_curve["val"]) == 20
    assert "model_version" in result
    assert result["model_version"]["status"] == "实验版本"

    with Session(db_engine) as session:
        job_row = session.exec(select(Job).where(Job.job_uid == job_id)).first()
        assert job_row is not None
        task = session.exec(
            select(TrainingTask).where(TrainingTask.job_id == job_row.id)
        ).first()
        assert task is not None
        assert task.hyperparams["epochs"] == 20 and task.hyperparams["optimizer"] == "adamw"
        assert task.metrics == metrics and task.loss_curve == loss_curve

        # 训练成功自动生成 model_versions：实验版本、挂 base model（model 1）、版本号 +1
        mv = session.exec(
            select(ModelVersion)
            .where(ModelVersion.model_id == 1)
            .order_by(ModelVersion.id.desc())
        ).first()
        assert mv is not None and mv.version_no == "v1.9"
        assert mv.status == "实验版本"
        assert mv.metric == metrics
        assert mv.file_key == f"models/{mv.id}/weights.pt"

    # 权重占位已写 MinIO（假存储记录）
    keys = [key for key, *_ in fake_storage.uploads]
    assert any(key.endswith("weights.pt") for key in keys), keys

    # 模型仓库最新版本已更新为 v1.9
    models = client.get("/api/v1/models").json()["data"]["models"]
    by_name = {m["name"]: m for m in models}
    assert by_name[SEED_MODEL_1]["version"] == "v1.9"
    assert by_name[SEED_MODEL_1]["status"] == "实验版本"
    assert by_name[SEED_MODEL_1]["metric"] == metrics


def test_training_rejects_unready_dataset(
    db_engine,
    override_get_session,
    override_get_current_user,
) -> None:
    version_id = _make_dataset_version(
        db_engine,
        dataset_no="DS-UNREADY-001",
        sample_keys=["processed/demo/sample.jpg"],
        split={"train": 1, "val": 0, "test": 0},
        empty_label_rate=1.0,
    )
    resp = client.post("/api/v1/training-tasks", json={"dataset_version_id": version_id})
    assert resp.status_code == 400
    assert resp.json()["code"] == 40000
    assert "暂不可训练" in resp.json()["message"]


def test_training_allows_required_dims_without_optional_modalities(
    db_engine,
    override_get_session,
    override_get_current_user,
) -> None:
    version_id = _make_dataset_version(
        db_engine,
        dataset_no="DS-READY-001",
        sample_keys=["processed/demo/sample.csv", "processed/demo/sample2.csv"],
        split={"train": 1, "val": 0, "test": 1},
        empty_label_rate=0.0,
    )
    resp = client.post("/api/v1/training-tasks", json={"dataset_version_id": version_id})
    assert resp.status_code == 200, resp.text


def test_training_deduplicates_active_job_by_dataset_version(
    db_engine,
    override_get_session,
    override_get_current_user,
) -> None:
    version_id = _make_dataset_version(
        db_engine,
        dataset_no="DS-DEDUP-001",
        sample_keys=["processed/demo/sample.csv", "processed/demo/sample2.csv"],
        split={"train": 1, "val": 0, "test": 1},
        empty_label_rate=0.0,
    )
    first = client.post("/api/v1/training-tasks", json={"dataset_version_id": version_id})
    second = client.post("/api/v1/training-tasks", json={"dataset_version_id": version_id})
    assert first.status_code == 200 and second.status_code == 200
    assert first.json()["data"]["job_id"] == second.json()["data"]["job_id"]


def test_training_without_base_model_creates_new_model(
    db_engine,
    override_get_session,
    override_get_current_user,
    executor_sessionlocal,
    fake_storage,
) -> None:
    """无 base_model_id → 自动新建 Model，训练产出版本挂到新模型。"""
    resp = client.post(
        "/api/v1/training-tasks", json={"dataset_version_id": 1, "epochs": 10}
    )
    assert resp.status_code == 200
    job_id = resp.json()["data"]["job_id"]
    run_job(job_id)

    done = client.get(f"/api/v1/training-tasks/{job_id}").json()["data"]
    assert done["status"] == "succeeded"
    assert done["result"]["model_version"]["status"] == "实验版本"

    with Session(db_engine) as session:
        models = session.exec(select(Model).order_by(Model.id)).all()
        assert len(models) == 4  # 3 seed + 1 自动新建
        auto = models[-1]
        assert auto.name.startswith("训练模型-")
        mv = session.exec(
            select(ModelVersion).where(ModelVersion.model_id == auto.id)
        ).first()
        assert mv is not None and mv.status == "实验版本"
        assert mv.file_key == f"models/{mv.id}/weights.pt"


def test_training_logs(
    db_engine,
    override_get_session,
    override_get_current_user,
    executor_sessionlocal,
    fake_storage,
) -> None:
    resp = client.post(
        "/api/v1/training-tasks",
        json={"dataset_version_id": 1, "base_model_id": 1, "epochs": 20},
    )
    job_id = resp.json()["data"]["job_id"]

    # 执行前：初始化日志可用
    resp = client.get(f"/api/v1/training-tasks/{job_id}/logs")
    assert resp.status_code == 200
    before = resp.json()["data"]
    assert isinstance(before, str) and "初始化" in before
    assert "epochs=20" in before

    run_job(job_id)

    resp = client.get(f"/api/v1/training-tasks/{job_id}/logs")
    after = resp.json()["data"]
    assert "Epoch 1/20" in after
    assert "Epoch 20/20" in after
    assert "mAP50" in after and "模型已保存" in after


# ---------- 测试任务（端到端） ----------


def test_test_task_rejects_incompatible_dataset(
    db_engine,
    override_get_session,
    override_get_current_user,
) -> None:
    version_id = _make_dataset_version(
        db_engine,
        dataset_no="DS-SEG-001",
        task="语义分割",
        sample_keys=["processed/demo/frame.mp4"],
        split={"train": 1, "val": 0, "test": 1},
        empty_label_rate=0.0,
    )
    resp = client.post(
        "/api/v1/test-tasks",
        json={"model_version_id": 1, "dataset_version_id": version_id},
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == 40000


def test_test_task_rejects_missing_test_split(
    db_engine,
    override_get_session,
    override_get_current_user,
) -> None:
    version_id = _make_dataset_version(
        db_engine,
        dataset_no="DS-NOTEST-001",
        sample_keys=["processed/demo/sample.csv"],
        split={"train": 1, "val": 0, "test": 0},
        empty_label_rate=0.0,
    )
    resp = client.post(
        "/api/v1/test-tasks",
        json={"model_version_id": 1, "dataset_version_id": version_id},
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == 40000


def test_test_task_end_to_end(
    db_engine,
    override_get_session,
    override_get_current_user,
    executor_sessionlocal,
    fake_storage,
) -> None:
    resp = client.post(
        "/api/v1/test-tasks",
        json={"model_version_id": 1, "dataset_version_id": 1, "tasks": ["异常分类"]},
    )
    assert resp.status_code == 200, resp.text[:300]
    job_id = resp.json()["data"]["job_id"]
    assert job_id.startswith("job_")

    run_job(job_id)

    done = client.get(f"/api/v1/test-tasks/{job_id}").json()["data"]
    assert done["status"] == "succeeded"
    result = done["result"]
    assert result["confusion_matrix"] == [[612, 18], [22, 596]]
    metrics = result["metrics"]
    assert metrics["accuracy"] == 0.968
    assert metrics["recall"] == 0.942
    assert metrics["f1"] == 0.955
    assert metrics["latency_ms"] == 18

    with Session(db_engine) as session:
        from app.models import TestTask

        job_row = session.exec(select(Job).where(Job.job_uid == job_id)).first()
        task = session.exec(select(TestTask).where(TestTask.job_id == job_row.id)).first()
        assert task is not None
        assert task.tasks == ["异常分类"]
        assert task.confusion_matrix == [[612, 18], [22, 596]]
        assert task.metrics["accuracy"] == 0.968


# ---------- 推理任务（端到端） ----------


def test_inference_rejects_corrupt_or_unsupported_inputs(
    override_get_session,
    override_get_current_user,
    fake_storage,
) -> None:
    fake_storage.blobs["uploads/abc/fake.jpg"] = b"not-really-an-image"
    fake_storage.blobs["uploads/abc/file.gif"] = b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x00\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02L\x01\x00;"
    bad = client.post(
        "/api/v1/inference-tasks",
        json={"model_version_id": 1, "input": "uploads/abc/fake.jpg", "input_type": "image"},
    )
    assert bad.status_code == 400
    assert bad.json()["code"] == 40000

    unsupported = client.post(
        "/api/v1/inference-tasks",
        json={"model_version_id": 1, "input": "uploads/abc/file.gif", "input_type": "image"},
    )
    assert unsupported.status_code == 400
    assert unsupported.json()["code"] == 40000


def test_inference_deduplicates_same_input_key(
    override_get_session,
    override_get_current_user,
    fake_storage,
) -> None:
    fake_storage.blobs["uploads/abc/img.png"] = _tiny_png_bytes()
    first = client.post(
        "/api/v1/inference-tasks",
        json={"model_version_id": 1, "input": "uploads/abc/img.png", "input_type": "image"},
    )
    second = client.post(
        "/api/v1/inference-tasks",
        json={"model_version_id": 1, "input": "uploads/abc/img.png", "input_type": "image"},
    )
    assert first.status_code == 200 and second.status_code == 200
    assert first.json()["data"]["job_id"] == second.json()["data"]["job_id"]


def test_inference_task_end_to_end(
    db_engine,
    override_get_session,
    override_get_current_user,
    executor_sessionlocal,
    fake_storage,
) -> None:
    fake_storage.blobs["uploads/abc/img.png"] = _tiny_png_bytes()
    resp = client.post(
        "/api/v1/inference-tasks",
        json={"model_version_id": 1, "input": "uploads/abc/img.png", "input_type": "image"},
    )
    assert resp.status_code == 200, resp.text[:300]
    job_id = resp.json()["data"]["job_id"]
    assert job_id.startswith("job_")

    run_job(job_id)

    done = client.get(f"/api/v1/inference-tasks/{job_id}").json()["data"]
    assert done["status"] == "succeeded"
    result = done["result"]
    assert isinstance(result["boxes"], list) and len(result["boxes"]) >= 1
    for box in result["boxes"]:
        assert len(box) == 4 and all(isinstance(v, (int, float)) for v in box)
    assert isinstance(result["categories"], list)
    assert len(result["categories"]) == len(result["boxes"])
    assert len(result["confidence"]) == len(result["boxes"])
    assert all(0.0 <= c <= 1.0 for c in result["confidence"])
    assert isinstance(result["latency_ms"], int) and result["latency_ms"] > 0

    with Session(db_engine) as session:
        from app.models import InferenceTask

        job_row = session.exec(select(Job).where(Job.job_uid == job_id)).first()
        task = session.exec(
            select(InferenceTask).where(InferenceTask.job_id == job_row.id)
        ).first()
        assert task is not None
        assert task.input_key == "uploads/abc/img.png" and task.input_type == "image"
        assert task.result == result


# ---------- 404 / 400 ----------


def _wait_for_terminal(job_id: str, path: str = "/api/v1/jobs/{job_id}") -> dict:
    deadline = time.time() + 3
    while time.time() < deadline:
        data = client.get(path.format(job_id=job_id)).json()["data"]
        if data["status"] in {"succeeded", "failed"}:
            return data
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} 未在超时前进入终态")


def test_auto_executor_consumes_training_test_and_inference_jobs(
    db_engine,
    override_get_session,
    override_get_current_user,
    executor_sessionlocal,
    fake_storage,
    monkeypatch,
) -> None:
    version_id = _make_dataset_version(
        db_engine,
        dataset_no="DS-AUTO-001",
        sample_keys=["processed/demo/sample.csv", "processed/demo/sample2.csv"],
        split={"train": 1, "val": 0, "test": 1},
        empty_label_rate=0.0,
    )
    fake_storage.blobs["uploads/abc/auto.png"] = _tiny_png_bytes()
    monkeypatch.setattr(executor_mod, "_POLL_INTERVAL", 0.05)
    executor_mod.stop()
    executor_mod.start()
    try:
        train_job = client.post("/api/v1/training-tasks", json={"dataset_version_id": version_id}).json()["data"]["job_id"]
        test_job = client.post("/api/v1/test-tasks", json={"model_version_id": 1, "dataset_version_id": version_id}).json()["data"]["job_id"]
        infer_job = client.post(
            "/api/v1/inference-tasks",
            json={"model_version_id": 1, "input": "uploads/abc/auto.png", "input_type": "image"},
        ).json()["data"]["job_id"]

        assert _wait_for_terminal(train_job)["status"] == "succeeded"
        assert _wait_for_terminal(test_job)["status"] == "succeeded"
        assert _wait_for_terminal(infer_job)["status"] == "succeeded"
    finally:
        executor_mod.stop()


def test_models_404(override_get_session, override_get_current_user) -> None:
    assert client.get("/api/v1/models/999999").status_code == 404
    assert client.post("/api/v1/models/999999").status_code == 405  # 无此 POST 路由

    # 模型不存在 / 版本不存在 / 跨模型版本 → 404
    resp = client.patch("/api/v1/models/999999/versions/1", json={"status": "实验版本"})
    assert resp.status_code == 404 and resp.json()["code"] == 40401
    resp = client.patch("/api/v1/models/1/versions/999999", json={"status": "实验版本"})
    assert resp.status_code == 404 and resp.json()["code"] == 40402
    resp = client.patch("/api/v1/models/1/versions/2", json={"status": "实验版本"})  # v2 属 model 2
    assert resp.status_code == 404 and resp.json()["code"] == 40402

    # 任务轮询 / 日志：未知 job_uid → 404
    for path in [
        "/api/v1/training-tasks/unknown_job",
        "/api/v1/training-tasks/unknown_job/logs",
        "/api/v1/test-tasks/unknown_job",
        "/api/v1/inference-tasks/unknown_job",
    ]:
        resp = client.get(path)
        assert resp.status_code == 404 and resp.json()["code"] == 40401, path

    # 训练：数据集版本/基础模型版本不存在 → 404
    resp = client.post("/api/v1/training-tasks", json={"dataset_version_id": 999999})
    assert resp.status_code == 404 and resp.json()["code"] == 40401
    resp = client.post(
        "/api/v1/training-tasks", json={"dataset_version_id": 1, "base_model_id": 999999}
    )
    assert resp.status_code == 404 and resp.json()["code"] == 40401

    # 测试 / 推理：模型版本/数据集版本不存在 → 404；空输入 → 400
    resp = client.post("/api/v1/test-tasks", json={"model_version_id": 999999, "dataset_version_id": 1})
    assert resp.status_code == 404 and resp.json()["code"] == 40401
    resp = client.post("/api/v1/test-tasks", json={"model_version_id": 1, "dataset_version_id": 999999})
    assert resp.status_code == 404 and resp.json()["code"] == 40401
    resp = client.post("/api/v1/inference-tasks", json={"model_version_id": 999999, "input": "x", "input_type": "image"})
    assert resp.status_code == 404 and resp.json()["code"] == 40401
    resp = client.post("/api/v1/inference-tasks", json={"model_version_id": 1, "input": " ", "input_type": "image"})
    assert resp.status_code == 400 and resp.json()["code"] == 40000


# ---------- 失败：handler 抛异常 → job failed ----------


def test_training_job_failure_records_error(
    db_engine,
    override_get_session,
    override_get_current_user,
    executor_sessionlocal,
    monkeypatch,
) -> None:
    def _boom(_job_id, _session):
        raise RuntimeError("模拟训练崩溃")

    monkeypatch.setitem(executor_mod.HANDLERS, "training", _boom)
    resp = client.post(
        "/api/v1/training-tasks", json={"dataset_version_id": 1, "base_model_id": 1}
    )
    job_id = resp.json()["data"]["job_id"]
    run_job(job_id)
    data = client.get(f"/api/v1/jobs/{job_id}").json()["data"]
    assert data["status"] == "failed"
    assert data["error"] == {"message": "模拟训练崩溃"}


# ---------- 未登录 ----------


def test_models_endpoints_require_login(db_engine, override_get_session) -> None:
    # 不 override get_current_user：无 Authorization 头 → 401（认证在业务逻辑前抛）。
    cases = [
        ("get", "/api/v1/models", None),
        ("get", "/api/v1/models/1", None),
        ("post", "/api/v1/models", {"name": "x", "type": "目标检测"}),
        ("patch", "/api/v1/models/1/versions/1", {"status": "实验版本"}),
        ("post", "/api/v1/training-tasks", {"dataset_version_id": 1}),
        ("get", "/api/v1/training-tasks/job_x", None),
        ("get", "/api/v1/training-tasks/job_x/logs", None),
        ("post", "/api/v1/test-tasks", {"model_version_id": 1, "dataset_version_id": 1}),
        ("get", "/api/v1/test-tasks/job_x", None),
        (
            "post",
            "/api/v1/inference-tasks",
            {"model_version_id": 1, "input": "x", "input_type": "image"},
        ),
        ("get", "/api/v1/inference-tasks/job_x", None),
    ]
    for method, path, body in cases:
        resp = client.request(method, path, json=body)
        assert resp.status_code == 401, f"{method} {path}: {resp.text[:200]}"
        assert resp.json()["code"] == 40100
