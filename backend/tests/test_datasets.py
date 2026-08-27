"""Task 15：数据集 + 构建任务 + dimensions/readiness/lineage。

内存 SQLite + StaticPool + 真实 app TestClient（同 test_split_annotation.py）。
`seed_all` 造演示数据（3 数据集 / 4 焊缝）后 override `get_session` / `get_current_user`；
把 `app.jobs.executor.SessionLocal` 指到同一测试引擎（`run_job` 用独立 session，**不启动**
后台轮询线程）；`app.storage.get_storage` → 假存储（记录快照写，不连真实 MinIO）。

覆盖：
- 列表 3 条 seed；新建（dataset_no `DS-xxx-序号`、状态 标注中、sample_count 0、同名 409）；
- 输入维度 7 项 + 各任务必需维度 + 状态枚举；readiness 形状（4 项 checks）；
- 版本新建 → 版本号递增（v1.1 → v1.2）；
- 构建任务（**空来源 → 兜底合成样本**）：run_job → succeeded、dataset_items 落库、
  split 覆盖 train/val/test、**同焊缝样本不跨 split（防泄漏）**、quality 含重复率、
  snapshot_id 落库 + MinIO 快照写入、dataset.current_version_id/sample_count/status 更新；
- 构建任务（**真实切分样本**）：单焊缝 → 全部进 train（不泄漏）；
- lineage 4 层节点（records/annotation_tasks/dataset_versions/training_tasks）；
- 404（数据集/版本/非法来源 400）、401（10 端点全验证）、构建失败 → job failed。
"""

import inspect
import json
import time
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, select

import app.jobs.executor as executor_mod
from app.api.deps import get_current_user
from app.core.db import get_session
from app.core.seed import seed_all
from app.jobs.executor import run_job
from app.main import app
from app.models import (
    Annotation,
    DataRecord,
    DataVersion,
    Dataset,
    DatasetItem,
    DatasetVersion,
    Job,
    Sample,
    SplitTask,
    User,
)
from app.services import datasets as datasets_svc

client = TestClient(app)

WELD_0248 = "WLD-20260815-0248"
FIXED_RATE = 25
SPLIT_SAMPLE_COUNT = 5420 // FIXED_RATE  # 5.42s × 1000Hz = 5420 帧

INPUT_DIMENSIONS = [
    "Voltage",
    "GasSpeed",
    "Current",
    "Molten_feature",
    "Sound_feature",
    "焊缝照片",
    "熔池视频",
]


class FakeStorage:
    """记录 upload_stream 的假存储（断言快照写入，不连 MinIO）。"""

    def __init__(self) -> None:
        self.uploads: list[tuple] = []

    def upload_stream(self, object_key, fileobj, size, content_type):
        data = fileobj.read()
        self.uploads.append((object_key, size, content_type, data))
        return object_key


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
def unauthenticated_client(override_get_session):
    """清掉登录依赖后提供同一个 TestClient，用于 401 覆盖。"""
    app.dependency_overrides.pop(get_current_user, None)
    yield client


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
    """假存储：monkeypatch `app.storage.get_storage`（快照写走这里，不连 MinIO）。"""
    storage = FakeStorage()
    monkeypatch.setattr("app.storage.get_storage", lambda: storage)
    return storage


# ── 小助手 ────────────────────────────────────────────────────────────


def _dataset_version_id(dataset_id: int = 1) -> int:
    versions = client.get(f"/api/v1/datasets/{dataset_id}/versions").json()["data"]
    assert versions, f"dataset {dataset_id} has no versions"
    return versions[0]["id"]


def _version_id_by_no(weld_id, version_no="v1.0"):
    versions = client.get(f"/api/v1/welds/{weld_id}/versions").json()["data"]
    for v in versions:
        if v["version_no"] == version_no:
            return v["id"]
    raise AssertionError(f"{version_no} not found for {weld_id}")


def _create_split_task(weld_id, version_id, fixed_rate=FIXED_RATE, task_format="目标检测"):
    resp = client.post(
        f"/api/v1/welds/{weld_id}/versions/{version_id}/split-tasks",
        json={"fixed_rate": fixed_rate, "keep_event_buffer": 0.2, "task_format": task_format},
    )
    assert resp.status_code == 200, resp.text[:300]
    job_id = resp.json()["data"]["job_id"]
    assert job_id.startswith("job_")
    return job_id


def _split_row(db_engine, split_job_id):
    from app.models.analysis import SplitTask
    from app.models.jobs import Job

    with Session(db_engine) as session:
        job = session.exec(select(Job).where(Job.job_uid == split_job_id)).first()
        assert job is not None
        return session.exec(select(SplitTask).where(SplitTask.job_id == job.id)).first()


def _create_dataset(name="测试数据集", task="目标检测"):
    resp = client.post("/api/v1/datasets", json={"name": name, "task": task})
    assert resp.status_code == 200, resp.text[:300]
    return resp.json()["data"]


def _create_version(dataset_id, name="快照"):
    resp = client.post(
        f"/api/v1/datasets/{dataset_id}/versions", json={"name": name, "note": "note"}
    )
    assert resp.status_code == 200, resp.text[:300]
    return resp.json()["data"]


def _create_build_task(dataset_id, version_id, source):
    resp = client.post(
        f"/api/v1/datasets/{dataset_id}/versions/{version_id}/build-tasks",
        json={"source": source},
    )
    assert resp.status_code == 200, resp.text[:300]
    job_id = resp.json()["data"]["job_id"]
    assert job_id.startswith("job_")
    return job_id


# ---------- 列表 / 新建 ----------


def test_list_datasets_seeded(override_get_session, override_get_current_user) -> None:
    data = client.get("/api/v1/datasets").json()["data"]
    assert len(data) == 3
    names = {d["name"] for d in data}
    assert names == {"焊接缺陷检测集", "熔池分割数据集", "工艺质量预测集"}
    for d in data:
        assert d["task"] in ("目标检测", "语义分割", "多模态回归")
        assert d["sample_count"] > 0
        assert d["status"] in ("标注中", "可训练")
        assert d["version"]  # 当前版本号
        assert d["current_version_id"] is not None


def test_create_dataset_and_duplicate_name(
    override_get_session, override_get_current_user
) -> None:
    data = _create_dataset(name="新建缺陷数据集", task="目标检测")
    assert data["dataset_no"].startswith("DS-DEFECT-")
    assert data["status"] == "标注中"
    assert data["sample_count"] == 0
    assert data["task"] == "目标检测"
    assert data["current_version_id"] is None

    # 同名 → 409 冲突（契约 §1.3）
    resp = client.post("/api/v1/datasets", json={"name": "新建缺陷数据集", "task": "目标检测"})
    assert resp.status_code == 409 and resp.json()["code"] == 40900

    # 空名称 → 400
    resp = client.post("/api/v1/datasets", json={"name": "", "task": "目标检测"})
    assert resp.status_code == 400 and resp.json()["code"] == 40000


def test_get_dataset_detail(override_get_session, override_get_current_user) -> None:
    ds = _create_dataset(name="详情测试集", task="多模态回归")
    data = client.get(f"/api/v1/datasets/{ds['id']}").json()["data"]
    assert data["id"] == ds["id"]
    assert data["name"] == "详情测试集"
    assert data["status"] == "标注中"
    assert data["label_distribution"] == {}
    assert "updated_at" in data
    # dataset_no 作标识同样可查
    by_no = client.get(f"/api/v1/datasets/{ds['dataset_no']}").json()["data"]
    assert by_no["id"] == ds["id"]


def test_dataset_detail_includes_label_distribution(
    db_engine, override_get_session, override_get_current_user
) -> None:
    with Session(db_engine) as session:
        dataset = Dataset(
            dataset_no="DS-TEST-LABEL-001",
            name="标签分布测试集",
            task="目标检测",
            sample_count=2,
            progress=0,
            status="可训练",
        )
        session.add(dataset)
        session.commit()
        session.refresh(dataset)
        version = DatasetVersion(
            dataset_id=dataset.id,
            version_no="v1.1",
            split={"train": 1, "val": 0, "test": 1},
            item_count=2,
        )
        session.add(version)
        session.commit()
        session.refresh(version)
        dataset.current_version_id = version.id
        sample1 = Sample(object_keys=["processed/a.jpg"], meta={"record_id": 1})
        sample2 = Sample(object_keys=["processed/b.jpg"], meta={"record_id": 1})
        session.add(sample1)
        session.add(sample2)
        session.commit()
        session.refresh(sample1)
        session.refresh(sample2)
        session.add(DatasetItem(dataset_version_id=version.id, sample_id=sample1.id, split="train"))
        session.add(DatasetItem(dataset_version_id=version.id, sample_id=sample2.id, split="test"))
        session.add(Annotation(sample_id=sample1.id, category="气孔", box=[1, 2, 3, 4]))
        session.add(Annotation(sample_id=sample2.id, category="气孔", box=[1, 2, 3, 4]))
        session.add(Annotation(sample_id=sample2.id, category="咬边", box=[2, 3, 4, 5]))
        session.commit()

    data = client.get("/api/v1/datasets/DS-TEST-LABEL-001").json()["data"]
    assert data["label_distribution"] == {"气孔": 2, "咬边": 1}


# ---------- 输入维度 / 适配检查 ----------


def test_dimensions_7_required_per_task(
    override_get_session, override_get_current_user
) -> None:
    data = client.get("/api/v1/datasets/1/dimensions").json()["data"]
    assert len(data) == 7
    assert [d["name"] for d in data] == INPUT_DIMENSIONS
    required = {d["name"] for d in data if d["required"]}
    assert required == {"Current", "Voltage", "GasSpeed"}  # 目标检测
    assert all(d["status"] in ("已具备", "缺失", "必需") for d in data)
    assert all(isinstance(d["required"], bool) for d in data)


def test_readiness_shape(override_get_session, override_get_current_user) -> None:
    data = client.get("/api/v1/datasets/1/readiness").json()["data"]
    assert data["readiness"] in ("可训练", "暂不可训练")
    assert len(data["checks"]) == 4
    assert all("name" in c and isinstance(c["passed"], bool) for c in data["checks"])


# ---------- 版本 ----------


def test_create_version_increments(
    override_get_session, override_get_current_user
) -> None:
    ds = _create_dataset(name="版本测试集", task="语义分割")
    v1 = _create_version(ds["id"])
    assert v1["version_no"] == "v1.1"
    assert v1["split"] == {} and v1["item_count"] == 0
    v2 = _create_version(ds["id"])
    assert v2["version_no"] == "v1.2"

    versions = client.get(f"/api/v1/datasets/{ds['id']}/versions").json()["data"]
    assert [v["version_no"] for v in versions] == ["v1.1", "v1.2"]

    # 版本详情
    detail = client.get(f"/api/v1/datasets/{ds['id']}/versions/{v1['id']}").json()["data"]
    assert detail["version_no"] == "v1.1"
    assert "snapshot_id" in detail and "quality" in detail


def test_dataset_version_items_are_scoped_and_filterable(
    db_engine, override_get_session, override_get_current_user
) -> None:
    dataset = _create_dataset(name="成员分页测试集", task="目标检测")
    version = _create_version(dataset["id"])
    with Session(db_engine) as session:
        weld_0248 = session.exec(
            select(DataRecord).where(DataRecord.weld_id == WELD_0248)
        ).one()
        weld_0246 = session.exec(
            select(DataRecord).where(DataRecord.weld_id == "WLD-20260814-0246")
        ).one()
        data_version_0248 = session.exec(
            select(DataVersion).where(DataVersion.record_id == weld_0248.id)
        ).first()
        data_version_0246 = session.exec(
            select(DataVersion).where(DataVersion.record_id == weld_0246.id)
        ).first()
        jobs = [
            Job(job_uid="job_dataset_items_rel_0248", type="split", status="succeeded", progress=100),
            Job(job_uid="job_dataset_items_rel_0246", type="split", status="succeeded", progress=100),
        ]
        session.add_all(jobs)
        session.flush()
        split_0248 = SplitTask(
            job_id=jobs[0].id,
            version_id=data_version_0248.id,
            rules={"fixed_rate": 25},
            task_format="目标检测",
            sample_count=2,
        )
        split_0246 = SplitTask(
            job_id=jobs[1].id,
            version_id=data_version_0246.id,
            rules={"fixed_rate": 25},
            task_format="目标检测",
            sample_count=1,
        )
        session.add_all([split_0248, split_0246])
        session.flush()
        samples = [
            Sample(split_task_id=split_0248.id, object_keys=["processed/page/1.jpg"], frame_no=11),
            Sample(split_task_id=split_0248.id, object_keys=["processed/page/2.jpg"], frame_no=12),
            Sample(split_task_id=split_0246.id, object_keys=["processed/page/3.jpg"], frame_no=13),
        ]
        session.add_all(samples)
        session.commit()
        for sample in samples:
            session.refresh(sample)
        session.add_all(
            [
                DatasetItem(dataset_version_id=version["id"], sample_id=samples[0].id, split="train"),
                DatasetItem(dataset_version_id=version["id"], sample_id=samples[1].id, split="train"),
                DatasetItem(dataset_version_id=version["id"], sample_id=samples[2].id, split="test"),
            ]
        )
        session.commit()

    page1 = client.get(
        f"/api/v1/datasets/{dataset['id']}/versions/{version['id']}/items",
        params={"split": "train", "quality": "通过", "q": "0248", "page": 1, "page_size": 1},
    )
    assert page1.status_code == 200
    payload1 = page1.json()["data"]
    assert set(payload1) == {"items", "total", "page", "page_size"}
    assert payload1["total"] == 2
    assert payload1["page"] == 1
    assert payload1["page_size"] == 1
    assert len(payload1["items"]) == 1
    assert payload1["items"][0]["sample_id"] > 0
    assert payload1["items"][0]["weld_id"] == WELD_0248
    assert payload1["items"][0]["split"] == "train"
    assert payload1["items"][0]["quality"] == "通过"
    assert payload1["items"][0]["frame_no"] == 11
    assert all("weld_id" in item and "registration_no" in item for item in payload1["items"])
    assert all(
        set(item) >= {
            "sample_id",
            "weld_id",
            "weld_name",
            "registration_no",
            "source",
            "machine",
            "modalities",
            "quality",
            "split",
            "frame_no",
            "created_at",
        }
        for item in payload1["items"]
    )

    page2 = client.get(
        f"/api/v1/datasets/{dataset['id']}/versions/{version['id']}/items",
        params={"split": "train", "quality": "通过", "q": "0248", "page": 2, "page_size": 1},
    )
    assert page2.status_code == 200
    payload2 = page2.json()["data"]
    assert payload2["total"] == 2
    assert payload2["page"] == 2
    assert payload2["page_size"] == 1
    assert len(payload2["items"]) == 1
    assert payload2["items"][0]["sample_id"] > payload1["items"][0]["sample_id"]
    assert payload2["items"][0]["weld_id"] == WELD_0248
    assert payload2["items"][0]["split"] == "train"
    assert payload2["items"][0]["quality"] == "通过"
    assert payload2["items"][0]["frame_no"] == 12


def test_dataset_version_items_rejects_cross_dataset_version(
    override_get_session, override_get_current_user
) -> None:
    other_version_id = _dataset_version_id(2)
    response = client.get(f"/api/v1/datasets/1/versions/{other_version_id}/items")
    assert response.status_code == 404
    assert response.json()["code"] == 40402


def test_dataset_version_items_requires_auth(unauthenticated_client) -> None:
    response = unauthenticated_client.get("/api/v1/datasets/1/versions/1/items")
    assert response.status_code == 401
    assert response.json()["code"] == 40100


def test_dataset_version_item_filter_source_uses_relational_paths_not_json_operators() -> None:
    source = inspect.getsource(datasets_svc.list_version_items) + inspect.getsource(
        datasets_svc._version_item_record_filter
    )
    assert '.meta[' not in source
    assert 'as_integer' not in source
    assert 'as_string' not in source


def test_decode_version_item_payload_handles_json_strings_and_defaults() -> None:
    item = datasets_svc._version_item_payload(
        row={
            "id": 9,
            "sample_id": 7,
            "frame_no": 21,
            "split": "val",
            "meta": '{"record_id": 101, "weld_id": "META-WELD-01"}',
            "split_weld_id": None,
            "split_weld_name": None,
            "split_registration_no": None,
            "split_source": None,
            "split_machine": None,
            "split_modalities": '["video", "audio"]',
            "split_quality": None,
            "split_created_at": None,
            "annotation_weld_id": None,
            "annotation_weld_name": None,
            "annotation_registration_no": None,
            "annotation_source": None,
            "annotation_machine": None,
            "annotation_modalities": None,
            "annotation_quality": None,
            "annotation_created_at": None,
        },
        meta_record_by_id={101: {"weld_name": "元数据焊缝", "registration_no": "REG-101", "source": "产线A"}},
        meta_record_by_weld_id={},
    )
    assert item == {
        "id": 9,
        "sample_id": 7,
        "weld_id": "META-WELD-01",
        "weld_name": "元数据焊缝",
        "registration_no": "REG-101",
        "source": "产线A",
        "machine": None,
        "modalities": ["video", "audio"],
        "quality": None,
        "split": "val",
        "frame_no": 21,
        "created_at": None,
    }


def test_decode_version_item_payload_prefers_meta_record_and_normalizes_created_at() -> None:
    created_at = datetime(2026, 8, 27, 10, 11, 12, tzinfo=timezone.utc)
    item = datasets_svc._version_item_payload(
        row={
            "id": 3,
            "sample_id": 2,
            "frame_no": None,
            "split": "train",
            "meta": {"record_id": "55", "weld_id": "META-WELD-55"},
            "split_weld_id": "SPLIT-WELD",
            "split_weld_name": "切分焊缝",
            "split_registration_no": "REG-SPLIT",
            "split_source": "切分来源",
            "split_machine": "切分设备",
            "split_modalities": ["timeseries"],
            "split_quality": "待复核",
            "split_created_at": None,
            "annotation_weld_id": "ANN-WELD",
            "annotation_weld_name": "标注焊缝",
            "annotation_registration_no": "REG-ANN",
            "annotation_source": "标注来源",
            "annotation_machine": "标注设备",
            "annotation_modalities": ["video"],
            "annotation_quality": "异常",
            "annotation_created_at": None,
        },
        meta_record_by_id={
            55: {
                "weld_id": "META-REC-55",
                "weld_name": "元数据记录",
                "registration_no": "REG-055",
                "source": "元数据来源",
                "machine": "元数据设备",
                "modalities": '["current", "voltage"]',
                "quality": "通过",
                "created_at": created_at,
            }
        },
        meta_record_by_weld_id={},
    )
    assert item["weld_id"] == "META-REC-55"
    assert item["weld_name"] == "元数据记录"
    assert item["registration_no"] == "REG-055"
    assert item["source"] == "元数据来源"
    assert item["machine"] == "元数据设备"
    assert item["modalities"] == ["current", "voltage"]
    assert item["quality"] == "通过"
    assert item["created_at"] == "2026-08-27T10:11:12Z"


# ---------- 构建任务（空来源 → 兜底合成样本，覆盖多焊缝 8:1:1） ----------


def test_build_task_end_to_end(
    db_engine,
    override_get_session,
    override_get_current_user,
    executor_sessionlocal,
    fake_storage,
) -> None:
    ds = _create_dataset(name="构建测试集", task="目标检测")
    version = _create_version(ds["id"])
    job_id = _create_build_task(
        ds["id"], version["id"], {"type": "manual", "sample_ids": []}
    )

    pending = client.get(f"/api/v1/jobs/{job_id}").json()["data"]
    assert pending["type"] == "dataset_build"
    assert pending["status"] == "pending"

    run_job(job_id)

    done = client.get(f"/api/v1/jobs/{job_id}").json()["data"]
    assert done["status"] == "succeeded"
    assert done["progress"] == 100
    result = done["result"]
    assert result["item_count"] > 0
    # split 覆盖 train/val/test
    assert set(result["split"]) == {"train", "val", "test"}
    assert all(result["split"][k] > 0 for k in ("train", "val", "test"))
    assert "repeat_rate" in result["quality"]
    assert "empty_label_rate" in result["quality"]
    assert "dimension_missing_rate" in result["quality"]
    # 兜底合成样本含时序（.csv）→ 目标检测必需维度 Current/Voltage/GasSpeed 全具备 → 缺失率 0
    # （回归：quality 必须用本次构建的 in-flight 样本判维度，而非 current_version_id）。
    assert result["quality"]["dimension_missing_rate"] == 0.0
    assert result["snapshot_id"] == f"datasets/{version['id']}/snapshot.json"

    # dataset_items 落库：split 全三类、同焊缝样本绝不跨 split（防泄漏）
    with Session(db_engine) as session:
        items = session.exec(
            select(DatasetItem).where(DatasetItem.dataset_version_id == version["id"])
        ).all()
        assert len(items) == result["item_count"]
        assert {i.split for i in items} == {"train", "val", "test"}
        per_record: dict[int, set] = {}
        for it in items:
            sample = session.get(Sample, it.sample_id)
            assert sample is not None
            rid = sample.meta["record_id"]
            per_record.setdefault(rid, set()).add(it.split)
        for rid, splits in per_record.items():
            assert len(splits) == 1, f"record {rid} 跨 split: {splits}"

        # 数据集状态更新
        ds_row = session.get(Dataset, ds["id"])
        assert ds_row.current_version_id == version["id"]
        assert ds_row.sample_count == result["item_count"]
        assert ds_row.status == "可训练"
        version_row = session.get(DatasetVersion, version["id"])
        assert version_row.snapshot_id == result["snapshot_id"]
        assert version_row.split == result["split"]
        assert version_row.item_count == result["item_count"]
        assert version_row.quality == result["quality"]

    # 快照 JSON 已写 MinIO（假存储记录），且 quality 与 DB 一致（含修正后的维度缺失率）
    assert len(fake_storage.uploads) == 1
    key, size, ctype, data = fake_storage.uploads[0]
    assert key == f"datasets/{version['id']}/snapshot.json"
    assert ctype == "application/json"
    assert size == len(data) > 0
    snapshot = json.loads(data.decode("utf-8"))
    assert snapshot["quality"] == result["quality"]
    assert snapshot["quality"]["dimension_missing_rate"] == 0.0


# ---------- 构建任务（真实切分样本：单焊缝全进 train，不泄漏） ----------


def test_build_from_split_task(
    db_engine,
    override_get_session,
    override_get_current_user,
    executor_sessionlocal,
    fake_storage,
) -> None:
    vid = _version_id_by_no(WELD_0248)
    split_job_id = _create_split_task(WELD_0248, vid)
    run_job(split_job_id)
    split = _split_row(db_engine, split_job_id)

    ds = _create_dataset(name="切分构建集", task="目标检测")
    version = _create_version(ds["id"])
    job_id = _create_build_task(
        ds["id"], version["id"], {"type": "split_task", "split_task_id": split_job_id}
    )
    run_job(job_id)

    done = client.get(f"/api/v1/jobs/{job_id}").json()["data"]
    assert done["status"] == "succeeded"
    assert done["result"]["item_count"] == SPLIT_SAMPLE_COUNT
    # 单焊缝（0248）→ 全部进 train，不泄漏
    assert done["result"]["split"]["train"] == SPLIT_SAMPLE_COUNT
    assert done["result"]["split"]["val"] == 0
    assert done["result"]["split"]["test"] == 0

    with Session(db_engine) as session:
        items = session.exec(
            select(DatasetItem).where(DatasetItem.dataset_version_id == version["id"])
        ).all()
        assert len(items) == SPLIT_SAMPLE_COUNT
        assert all(i.split == "train" for i in items)
        # 全部样本来自该切分任务
        sample_ids = [i.sample_id for i in items]
        samples = session.exec(select(Sample).where(Sample.id.in_(sample_ids))).all()
        assert all(s.split_task_id == split.id for s in samples)


# ---------- 血缘 ----------


def test_auto_executor_consumes_dataset_build_job(
    db_engine,
    override_get_session,
    override_get_current_user,
    executor_sessionlocal,
    fake_storage,
    monkeypatch,
) -> None:
    ds = _create_dataset(name="自动构建测试集", task="目标检测")
    version = _create_version(ds["id"])
    job_id = _create_build_task(ds["id"], version["id"], {"type": "manual", "sample_ids": []})
    monkeypatch.setattr(executor_mod, "_POLL_INTERVAL", 0.05)
    executor_mod.stop()
    executor_mod.start()
    try:
        deadline = time.time() + 3
        data = None
        while time.time() < deadline:
            data = client.get(f"/api/v1/jobs/{job_id}").json()["data"]
            if data["status"] in {"succeeded", "failed"}:
                break
            time.sleep(0.05)
        assert data is not None and data["status"] == "succeeded"
    finally:
        executor_mod.stop()


def test_fixed_snapshot_old_version_remains_reproducible(
    db_engine,
    override_get_session,
    override_get_current_user,
    executor_sessionlocal,
    fake_storage,
) -> None:
    with Session(db_engine) as session:
        s1 = Sample(object_keys=["processed/demo/a.csv"], meta={"record_id": 1})
        s2 = Sample(object_keys=["processed/demo/b.csv"], meta={"record_id": 1})
        session.add(s1)
        session.add(s2)
        session.commit()
        session.refresh(s1)
        session.refresh(s2)
        sid1, sid2 = s1.id, s2.id

    ds = _create_dataset(name="固定快照测试集", task="目标检测")
    v1 = _create_version(ds["id"])
    job1 = _create_build_task(ds["id"], v1["id"], {"type": "manual", "sample_ids": [sid1]})
    run_job(job1)
    detail_v1 = client.get(f"/api/v1/datasets/{ds['id']}/versions/{v1['id']}").json()["data"]

    v2 = _create_version(ds["id"])
    job2 = _create_build_task(ds["id"], v2["id"], {"type": "manual", "sample_ids": [sid1, sid2]})
    run_job(job2)
    detail_v1_again = client.get(f"/api/v1/datasets/{ds['id']}/versions/{v1['id']}").json()["data"]
    detail_v2 = client.get(f"/api/v1/datasets/{ds['id']}/versions/{v2['id']}").json()["data"]

    assert detail_v1_again == detail_v1
    assert detail_v1_again["item_count"] == 1
    assert detail_v2["item_count"] == 2
    assert detail_v1_again["snapshot_id"] != detail_v2["snapshot_id"]


def test_lineage_4_nodes(
    db_engine,
    override_get_session,
    override_get_current_user,
    executor_sessionlocal,
    fake_storage,
) -> None:
    ds = _create_dataset(name="血缘测试集", task="目标检测")
    version = _create_version(ds["id"])
    job_id = _create_build_task(
        ds["id"], version["id"], {"type": "manual", "sample_ids": []}
    )
    run_job(job_id)

    lineage = client.get(f"/api/v1/datasets/{ds['id']}/lineage").json()["data"]
    assert len(lineage) == 4
    assert [n["type"] for n in lineage] == [
        "records",
        "annotation_tasks",
        "dataset_versions",
        "training_tasks",
    ]
    # 构建后：原始焊缝 > 0、数据集版本 == 1；标注/训练无
    assert lineage[0]["count"] > 0
    assert lineage[1]["count"] == 0
    assert lineage[2]["count"] == 1
    assert lineage[3]["count"] == 0


def test_lineage_unbuilt_still_4(override_get_session, override_get_current_user) -> None:
    ds = _create_dataset(name="未构建血缘", task="多模态回归")
    lineage = client.get(f"/api/v1/datasets/{ds['id']}/lineage").json()["data"]
    assert len(lineage) == 4
    assert lineage[0]["count"] == 0
    assert lineage[2]["count"] == 0


# ---------- 404 / 400 ----------


def test_datasets_404(override_get_session, override_get_current_user) -> None:
    for path in [
        "/api/v1/datasets/999999",
        "/api/v1/datasets/999999/dimensions",
        "/api/v1/datasets/999999/readiness",
        "/api/v1/datasets/999999/versions",
        "/api/v1/datasets/999999/versions/1",
        "/api/v1/datasets/999999/lineage",
    ]:
        resp = client.get(path)
        assert resp.status_code == 404 and resp.json()["code"] == 40401, path

    # 版本不属于数据集 → 40402
    resp = client.get("/api/v1/datasets/1/versions/999999")
    assert resp.status_code == 404 and resp.json()["code"] == 40402

    # 构建任务：数据集/版本不存在
    resp = client.post(
        "/api/v1/datasets/999999/versions/1/build-tasks",
        json={"source": {"type": "manual"}},
    )
    assert resp.status_code == 404 and resp.json()["code"] == 40401
    resp = client.post(
        "/api/v1/datasets/1/versions/999999/build-tasks",
        json={"source": {"type": "manual"}},
    )
    assert resp.status_code == 404 and resp.json()["code"] == 40402

    # 非法来源类型 → 400
    resp = client.post(
        "/api/v1/datasets/1/versions/1/build-tasks",
        json={"source": {"type": "bad_source"}},
    )
    assert resp.status_code == 400 and resp.json()["code"] == 40000


# ---------- 失败：handler 抛异常 → job failed ----------


def test_build_job_failure_records_error(
    db_engine,
    override_get_session,
    override_get_current_user,
    executor_sessionlocal,
    monkeypatch,
) -> None:
    def _boom(_job_id, _session):
        raise RuntimeError("模拟构建崩溃")

    monkeypatch.setitem(executor_mod.HANDLERS, "dataset_build", _boom)
    ds = _create_dataset(name="失败构建", task="目标检测")
    version = _create_version(ds["id"])
    job_id = _create_build_task(ds["id"], version["id"], {"type": "manual"})
    run_job(job_id)
    data = client.get(f"/api/v1/jobs/{job_id}").json()["data"]
    assert data["status"] == "failed"
    assert data["error"] == {"message": "模拟构建崩溃"}


# ---------- 未登录 ----------


def test_datasets_endpoints_require_login(db_engine, override_get_session) -> None:
    # 不 override get_current_user：无 Authorization 头 → 401（认证在业务逻辑前抛）。
    cases = [
        ("get", "/api/v1/datasets", None),
        ("post", "/api/v1/datasets", {"name": "x", "task": "目标检测"}),
        ("get", "/api/v1/datasets/1", None),
        ("get", "/api/v1/datasets/1/dimensions", None),
        ("get", "/api/v1/datasets/1/readiness", None),
        ("get", "/api/v1/datasets/1/versions", None),
        ("post", "/api/v1/datasets/1/versions", {"name": "v"}),
        ("get", "/api/v1/datasets/1/versions/1", None),
        (
            "post",
            "/api/v1/datasets/1/versions/1/build-tasks",
            {"source": {"type": "manual"}},
        ),
        ("get", "/api/v1/datasets/1/lineage", None),
    ]
    for method, path, body in cases:
        resp = client.request(method, path, json=body)
        assert resp.status_code == 401, f"{method} {path}: {resp.text[:200]}"
        assert resp.json()["code"] == 40100
