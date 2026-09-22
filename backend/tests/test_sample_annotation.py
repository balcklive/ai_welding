"""分段样本**段级标注**（2026-09-22）：服务层 + `/split-tasks/{id}/annotation-samples` 端点。

覆盖范围：

1. **关键流程端到端**（真实 HTTP + 真实 DB）：列出可标注样本 → 未标注筛选 → 保存
   （正常/缺陷）→ 进度与缺陷分布 → 撤销 → 版本化导出；
2. **结论约束**：defect 必须给主缺陷类别、normal 必须不带；别的分组的字典 id 不算缺陷类别；
   停用类别挡新写入但放行"本来就引用了它"的旧标注（否则类别一停用那条标注就改不动）；
   备注长度上限与空白归一；
3. **前置条件**：非 v3 分段任务 / 未成功完成的任务一律 400；样本不属于该任务 404；
   未登录 401；撤销一条不存在的标注 404；
4. **词表管理走系统设置**（`/settings/options/defect_category`）：新增/改名/上下移/删除，
   **被标注引用的类别删除时降级为停用**（不能物理删——`sample_annotations` 是按 id 引用的外键）；
5. **数据集构建消费**：跑真实 `dataset_build` job，断言冻结快照落进 `dataset_items.annotations`
   且 `empty_label_rate` 认得出段级标注（两条标注线同一口径）；
6. **训练折叠**：快照里的段级结论带 `label`，优先级高于类别名白名单。

隔离手段同 `test_dataset_build_e2e.py`：内存 SQLite（StaticPool）+ 假 Storage +
执行器 session monkeypatch，不连远程库 / MinIO。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, select

from app.api.deps import get_current_user
from app.core.db import get_session
from app.core.seed import seed_reference_data
from app.main import app
from app.models import User
from app.models.analysis import Annotation, Sample, SampleAnnotation, SplitTask
from app.models.data import DataRecord, DataVersion
from app.models.datasets import Dataset, DatasetBuildTask, DatasetItem, DatasetVersion
from app.models.jobs import Job
from app.models.settings import OptionItem
from app.services import sample_annotation as svc
from app.services.jobs import create_job, mark_succeeded
from app.storage.client import StorageClient

client = TestClient(app)
API = "/api/v1"
#: v3 的窗口秒数（2 秒窗 / 2 秒步长 → 8 秒信号切出 4 个窗口）
WINDOWS = ((0.0, 2.0), (2.0, 4.0), (4.0, 6.0), (6.0, 8.0))


class FakeStorage:
    """内存假存储：只实现数据集构建快照会用到的接口。"""

    normalize_key = staticmethod(StorageClient.normalize_key)
    normalize_filename = staticmethod(StorageClient.normalize_filename)

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def upload_stream(self, object_key, fileobj, size, content_type):  # noqa: ANN001
        self.objects[object_key] = fileobj.read()

    def get_object(self, object_key: str) -> bytes:
        return self.objects[object_key]

    def stat_object(self, object_key: str) -> int:
        return len(self.objects.get(object_key, b""))

    def delete_object(self, object_key: str) -> None:
        self.objects.pop(object_key, None)

    def presign_get(self, object_key: str, expires: int = 3600) -> str:
        return f"https://fake.local/{object_key}"


@pytest.fixture()
def engine():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def db(engine):
    with Session(engine, expire_on_commit=False) as session:
        yield session


@pytest.fixture()
def storage(monkeypatch):
    """假 Storage：数据集构建快照是**尽力而为**的写入，延迟 `from app.storage import
    get_storage`，打在 `app.storage` 这个名字上即可（同 `test_dataset_build_e2e`）。"""
    fake = FakeStorage()
    monkeypatch.setattr("app.storage.get_storage", lambda: fake)
    return fake


@pytest.fixture()
def run_job(monkeypatch, engine):
    from app.jobs.executor import run_job as _run_job

    monkeypatch.setattr(
        "app.jobs.executor.SessionLocal", lambda: Session(engine, expire_on_commit=False)
    )
    return _run_job


@pytest.fixture()
def user(db) -> User:
    row = User(username="labeler", password_hash="x", display_name="标注员", role="admin")
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@pytest.fixture()
def api(db, user):
    """真实 TestClient + 依赖覆盖。缺陷词表由 `_seed_split_task` 初始化，这里不再重复。"""
    app.dependency_overrides[get_session] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    yield client
    app.dependency_overrides.pop(get_session, None)
    app.dependency_overrides.pop(get_current_user, None)


# ── 夹具与助手 ───────────────────────────────────────────────────────


def _ok(response):
    payload = response.json()
    assert payload["code"] == 0, payload
    return payload["data"]


def _category_id(db: Session, name: str) -> int:
    match = next((row for row in svc.list_categories(db) if row["value"] == name), None)
    assert match is not None, f"词表缺少 {name}"
    return match["id"]


def _seed_split_task(
    db: Session,
    *,
    suffix: str = "A",
    rules_version: int = 3,
    status: str = "succeeded",
) -> tuple[SplitTask, list[int]]:
    """建一个（默认成功、v3）分段任务与 4 个时间窗样本，返回 (task, sample_ids)。

    样本按 v3 口径写 `start_time`/`end_time` 与 `schema_version=3` 的 `meta`；
    段级标注只读这两列 + 任务属性，故不必真跑一次分段 job（分段自身的 E2E 见
    `tests/test_split_v3_api.py`）。`suffix` 让一个用例里能建多条焊缝（weld_id 唯一）。

    缺陷词表的出厂默认值在这里初始化（生产由 `seed_reference_data`，同一份默认值）——
    词表是"能标注"的前提，不该由用例各自记得去 seed。
    """
    seed_reference_data(db)
    record = DataRecord(
        weld_id=f"WLD-SEG-{suffix}",
        registration_no=f"REG-SEG-{suffix}",
        source="现场采集",
        quality="通过",
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    version = DataVersion(record_id=record.id, version_no="v1.0", action="原始数据", object_keys=[])
    db.add(version)
    db.commit()
    db.refresh(version)

    job = create_job(db, type="split")
    task = SplitTask(
        job_id=job.id,
        version_id=version.id,
        rules={"rules_version": rules_version, "window_seconds": 2.0, "stride_seconds": 2.0},
        task_format=None,
        sample_count=len(WINDOWS),
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    if status == "succeeded":
        mark_succeeded(db, job, {"sample_count": len(WINDOWS)})
    else:
        job.status = status
    db.add(job)
    db.commit()

    sample_ids: list[int] = []
    for index, (start, end) in enumerate(WINDOWS, start=1):
        sample = Sample(
            split_task_id=task.id,
            frame_no=index,
            start_time=start,
            end_time=end,
            object_keys=[f"processed/{record.weld_id}/split/{task.id}/samples/{index:06d}.json"],
            meta={"schema_version": 3, "sample_index": index},
        )
        db.add(sample)
        db.flush()
        sample_ids.append(sample.id)
    db.commit()
    return task, sample_ids


def _base(db: Session, task: SplitTask) -> str:
    """标注端点路径。用 **job_uid** 寻址——与前端创建任务后拿到的 `job_id` 一致
    （`resolve_split_task` 双解析 job_uid / DB id，这里钉住前者）。"""
    return f"{API}/split-tasks/{db.get(Job, task.job_id).job_uid}/annotation-samples"


# ── 1. 关键流程端到端 ────────────────────────────────────────────────


def test_annotation_flow_end_to_end(api, db) -> None:
    """列表 → 未标注筛选 → 保存 → 进度 → 撤销 → 导出（全部走真实 HTTP 接口）。"""
    task, sample_ids = _seed_split_task(db)
    base = _base(db, task)

    # 词表：出厂 7 类，按 sort_order 升序
    categories = _ok(api.get(f"{API}/segment-annotation/categories"))["categories"]
    assert [c["value"] for c in categories] == [
        "气孔", "未焊透", "焊穿", "咬边", "裂纹", "成形不良", "其他",
    ]

    # 列表：4 个样本、全部未标注
    page = _ok(api.get(base, params={"page": 1, "page_size": 50}))
    assert [item["id"] for item in page["items"]] == sample_ids
    assert all(item["annotated"] is False for item in page["items"])
    assert page["progress"] == {
        "total": 4, "annotated": 0, "unannotated": 4, "normal": 0, "defect": 0,
        "progress": 0.0, "defect_distribution": [],
    }

    # ① 正常：不带缺陷类别
    first = _ok(api.put(f"{base}/{sample_ids[0]}", json={"label": "normal"}))
    assert first["annotation"]["label"] == "normal"
    assert first["annotation"]["defect_category_name"] is None
    assert first["annotation"]["annotator"] == "标注员"
    assert first["progress"]["annotated"] == 1

    # ② 缺陷：必须带主缺陷类别，名称落快照
    pore = _category_id(db, "气孔")
    second = _ok(api.put(
        f"{base}/{sample_ids[1]}",
        json={"label": "defect", "defect_category_id": pore, "note": "收弧处可见气孔"},
    ))
    assert second["annotation"]["defect_category_name"] == "气孔"
    assert second["annotation"]["note"] == "收弧处可见气孔"
    assert second["progress"]["annotated"] == 2
    assert (second["progress"]["normal"], second["progress"]["defect"]) == (1, 1)
    assert second["progress"]["progress"] == 50.0
    assert second["progress"]["defect_distribution"] == [{"name": "气孔", "count": 1}]

    # 未标注筛选（SQL 侧过滤）
    pending = _ok(api.get(base, params={"filter": "unannotated"}))
    assert [item["id"] for item in pending["items"]] == sample_ids[2:]
    assert pending["total"] == 2
    assert pending["progress"]["total"] == 4  # 进度恒按全任务算，不跟着筛选变

    # 单样本详情：未标注是 null，不是 404
    detail = _ok(api.get(f"{base}/{sample_ids[2]}"))
    assert detail["annotation"] is None and detail["start_time"] == 4.0

    # ③ 撤销 → 回到未标注
    cleared = _ok(api.delete(f"{base}/{sample_ids[0]}"))
    assert cleared["cleared"] is True
    assert cleared["progress"]["annotated"] == 1
    assert _ok(api.get(f"{base}/{sample_ids[0]}"))["annotation"] is None

    # ④ 版本化导出：未标注样本也在（label=null），词表随行导出
    export = _ok(api.get(f"{API}/split-tasks/{db.get(Job, task.job_id).job_uid}/annotation-export"))
    assert export["schema_version"] == svc.SCHEMA_VERSION == 1
    assert export["weld_id"] == "WLD-SEG-A"
    assert export["sample_count"] == 4 and export["annotated_count"] == 1
    assert [item["label"] for item in export["items"]] == [None, "defect", None, None]
    assert export["items"][1]["defect_category_name"] == "气孔"
    assert len(export["label_vocabulary"]) == 7


def test_upsert_keeps_one_row_per_sample(api, db) -> None:
    """重复保存是**更新**，一个样本恒一行（`sample_id` 唯一）。"""
    task, sample_ids = _seed_split_task(db)
    base = _base(db, task)
    pore, crack = _category_id(db, "气孔"), _category_id(db, "裂纹")

    _ok(api.put(f"{base}/{sample_ids[0]}", json={"label": "defect", "defect_category_id": pore}))
    updated = _ok(api.put(
        f"{base}/{sample_ids[0]}", json={"label": "defect", "defect_category_id": crack}
    ))
    assert updated["annotation"]["defect_category_name"] == "裂纹"
    rows = db.exec(
        select(SampleAnnotation).where(SampleAnnotation.sample_id == sample_ids[0])
    ).all()
    assert len(rows) == 1

    # 缺陷 → 正常：类别 id 与名称快照必须一起被清掉，不能留残影
    back = _ok(api.put(f"{base}/{sample_ids[0]}", json={"label": "normal"}))
    assert back["annotation"]["defect_category_id"] is None
    assert back["annotation"]["defect_category_name"] is None


# ── 2. 结论约束 ──────────────────────────────────────────────────────


def test_defect_requires_category_and_normal_forbids_it(api, db) -> None:
    task, sample_ids = _seed_split_task(db)
    base = _base(db, task)
    pore = _category_id(db, "气孔")

    missing = api.put(f"{base}/{sample_ids[0]}", json={"label": "defect"})
    assert missing.status_code == 400 and "主缺陷类别" in missing.json()["message"]

    extra = api.put(f"{base}/{sample_ids[0]}", json={"label": "normal", "defect_category_id": pore})
    assert extra.status_code == 400 and "不能指定缺陷类别" in extra.json()["message"]

    unknown_label = api.put(f"{base}/{sample_ids[0]}", json={"label": "maybe"})
    assert unknown_label.status_code == 400
    assert db.exec(select(SampleAnnotation)).all() == []


def test_note_length_and_blank_note(api, db) -> None:
    task, sample_ids = _seed_split_task(db)
    base = _base(db, task)

    too_long = api.put(f"{base}/{sample_ids[0]}", json={"label": "normal", "note": "长" * 513})
    assert too_long.status_code == 400 and "备注" in too_long.json()["message"]

    blank = _ok(api.put(f"{base}/{sample_ids[0]}", json={"label": "normal", "note": "   "}))
    assert blank["annotation"]["note"] is None  # 纯空白归一为空


def test_inactive_category_blocks_new_but_keeps_existing(api, db) -> None:
    """停用类别不能用于**新**标注，但已引用它的旧标注必须还能改。

    否则管理员一停用类别，那条历史标注就永久改不动了（同登记页"编辑时放行与当前值相同"）。
    """
    task, sample_ids = _seed_split_task(db)
    base = _base(db, task)
    pore = _category_id(db, "气孔")

    _ok(api.put(f"{base}/{sample_ids[0]}", json={"label": "defect", "defect_category_id": pore}))
    _ok(api.put(f"{base}/{sample_ids[1]}", json={"label": "defect", "defect_category_id": pore}))

    _ok(api.patch(f"{API}/settings/options/defect_category/{pore}", json={"active": False}))
    rejected = api.put(f"{base}/{sample_ids[2]}", json={"label": "defect", "defect_category_id": pore})
    assert rejected.status_code == 400 and "已停用" in rejected.json()["message"]

    kept = _ok(api.put(
        f"{base}/{sample_ids[0]}",
        json={"label": "defect", "defect_category_id": pore, "note": "复核确认"},
    ))
    assert kept["annotation"]["defect_category_name"] == "气孔"
    assert kept["annotation"]["note"] == "复核确认"

    # 历史展示靠行内快照：类别停用后名字仍在，且设置页仍能看到它（标着停用）
    detail = _ok(api.get(f"{base}/{sample_ids[0]}"))
    assert detail["annotation"]["defect_category_id"] == pore
    assert detail["annotation"]["defect_category_name"] == "气孔"
    listed = _ok(api.get(f"{API}/segment-annotation/categories", params={"include_inactive": 1}))
    assert any(c["id"] == pore and c["active"] is False for c in listed["categories"])
    assert all(c["id"] != pore for c in _ok(api.get(f"{API}/segment-annotation/categories"))["categories"])


def test_category_from_another_group_rejected(api, db) -> None:
    """传一个**别的分组**的 option_items id 不能当缺陷类别用（分组边界不能糊）。"""
    task, sample_ids = _seed_split_task(db)
    foreign = db.exec(select(OptionItem).where(OptionItem.group_key == "machine")).first()
    assert foreign is not None
    response = api.put(
        f"{_base(db, task)}/{sample_ids[0]}",
        json={"label": "defect", "defect_category_id": foreign.id},
    )
    assert response.status_code == 400 and "缺陷类别不存在" in response.json()["message"]


# ── 3. 前置条件与鉴权 ────────────────────────────────────────────────


def test_annotatable_task_list_is_the_workbench_entry(api, db) -> None:
    """工作台入口列表：只列**已完成 + v3** 的任务，且带标注进度。"""
    task, sample_ids = _seed_split_task(db, suffix="A")
    _seed_split_task(db, suffix="B", rules_version=2)      # 历史口径 → 不列
    _seed_split_task(db, suffix="C", status="running")      # 未完成 → 不列

    items = _ok(api.get(f"{API}/welds/WLD-SEG-A/segment-annotation-tasks"))["items"]
    assert len(items) == 1
    entry = items[0]
    assert entry["task_id"] == db.get(Job, task.job_id).job_uid
    assert entry["sample_count"] == 4 and entry["window_seconds"] == 2.0
    assert entry["progress"] == {
        "total": 4, "annotated": 0, "unannotated": 4, "progress": 0.0,
    }

    _ok(api.put(
        f"{_base(db, task)}/{sample_ids[0]}",
        json={"label": "defect", "defect_category_id": _category_id(db, "咬边")},
    ))
    after = _ok(api.get(f"{API}/welds/WLD-SEG-A/segment-annotation-tasks"))["items"][0]
    assert after["progress"]["annotated"] == 1 and after["progress"]["progress"] == 25.0

    assert api.get(f"{API}/welds/WLD-NOPE/segment-annotation-tasks").status_code == 404


def test_non_v3_or_unfinished_task_rejected(api, db) -> None:
    legacy, legacy_samples = _seed_split_task(db, suffix="L", rules_version=2)
    running, running_samples = _seed_split_task(db, suffix="R", status="running")

    for task, sample_ids in ((legacy, legacy_samples), (running, running_samples)):
        base = _base(db, task)
        blocked = api.get(base)
        assert blocked.status_code == 400
        assert api.put(f"{base}/{sample_ids[0]}", json={"label": "normal"}).status_code == 400


def test_missing_task_or_sample_404(api, db) -> None:
    task, sample_ids = _seed_split_task(db)
    other, other_samples = _seed_split_task(db, suffix="B")
    base = _base(db, task)

    assert api.get(f"{API}/split-tasks/job_nope/annotation-samples").status_code == 404
    # 样本属于**另一个**分段任务 → 404（不能跨任务标注）
    assert api.get(f"{base}/{other_samples[0]}").status_code == 404
    assert api.put(f"{base}/{other_samples[0]}", json={"label": "normal"}).status_code == 404
    # 撤销一条不存在的标注 → 404（不假装删成功）
    assert api.delete(f"{base}/{sample_ids[0]}").status_code == 404
    # 非法 filter 值 → 400
    assert api.get(base, params={"filter": "whatever"}).status_code == 400
    assert other is not None


def test_requires_login(db) -> None:
    """未登录一律 401（router 级依赖，读也一样）。"""
    task, _sample_ids = _seed_split_task(db)
    job_uid = db.get(Job, task.job_id).job_uid
    app.dependency_overrides[get_session] = lambda: db
    try:
        assert client.get(f"{API}/split-tasks/{job_uid}/annotation-samples").status_code == 401
        assert client.get(f"{API}/segment-annotation/categories").status_code == 401
        assert client.put(
            f"{API}/split-tasks/{job_uid}/annotation-samples/1", json={"label": "normal"}
        ).status_code == 401
    finally:
        app.dependency_overrides.pop(get_session, None)


# ── 4. 词表管理（系统设置） ──────────────────────────────────────────


def test_defect_vocabulary_managed_through_settings(api, db) -> None:
    """词表增删改走 `/settings/options/defect_category`，读走标注侧端点。

    被标注引用的类别删除时**降级为停用**（不是物理删）——`sample_annotations` 是按 id
    引用的外键，物理删会把它变成悬空引用。
    """
    task, sample_ids = _seed_split_task(db)
    base = _base(db, task)

    created = _ok(api.post(f"{API}/settings/options/defect_category", json={"value": "未熔合"}))
    new_id = created["item"]["id"]
    assert new_id in [c["id"] for c in _ok(api.get(f"{API}/segment-annotation/categories"))["categories"]]

    _ok(api.patch(f"{API}/settings/options/defect_category/{new_id}", json={"value": "未熔合（改）"}))
    names = [c["value"] for c in svc.list_categories(db)]
    assert "未熔合（改）" in names and "未熔合" not in names

    # 未被引用 → 物理删
    assert _ok(api.delete(f"{API}/settings/options/defect_category/{new_id}"))["mode"] == "deleted"

    # 被引用 → 软删（停用），标注行仍指向它、名称快照仍可读
    pore = _category_id(db, "气孔")
    _ok(api.put(f"{base}/{sample_ids[0]}", json={"label": "defect", "defect_category_id": pore}))
    kept = _ok(api.delete(f"{API}/settings/options/defect_category/{pore}"))
    assert kept["mode"] == "deactivated" and kept["references"] == 1
    assert db.get(OptionItem, pore) is not None
    assert _ok(api.get(f"{base}/{sample_ids[0]}"))["annotation"]["defect_category_name"] == "气孔"

    # 排序也走同一套设置接口（整组重排）
    items = _ok(api.post(f"{API}/settings/options/defect_category/{_category_id(db, '其他')}/move",
                         json={"direction": "up"}))["items"]
    assert [item["sort_order"] for item in items] == sorted(item["sort_order"] for item in items)


# ── 5. 数据集构建消费 ────────────────────────────────────────────────


def test_dataset_build_freezes_segment_annotations(api, db, storage, run_job) -> None:
    """构建数据集时把段级标注写进 `dataset_items.annotations` 冻结快照。

    `empty_label_rate` 必须与快照同口径——否则快照里明明有结论的切片会被记成"空标注"。
    """
    task, sample_ids = _seed_split_task(db)
    base = _base(db, task)
    pore = _category_id(db, "气孔")

    _ok(api.put(f"{base}/{sample_ids[0]}", json={"label": "normal"}))
    _ok(api.put(f"{base}/{sample_ids[1]}", json={"label": "defect", "defect_category_id": pore}))

    dataset = Dataset(
        dataset_no="DS-SEG-001", name="段级标注数据集", task="目标检测", status="标注中",
    )
    db.add(dataset)
    db.commit()
    db.refresh(dataset)
    version = DatasetVersion(dataset_id=dataset.id, version_no="v1.1", split={}, item_count=0)
    db.add(version)
    db.commit()
    db.refresh(version)
    job = create_job(
        db, type="dataset_build",
        result={"source": {"type": "split_task", "split_task_id": task.id}},
    )
    db.add(DatasetBuildTask(job_id=job.id, dataset_version_id=version.id, source="split_task"))
    db.commit()

    run_job(job.job_uid)

    db.expire_all()
    items = db.exec(
        select(DatasetItem).where(DatasetItem.dataset_version_id == version.id)
    ).all()
    assert len(items) == len(WINDOWS)
    frozen = {item.sample_id: item.annotations for item in items}
    assert frozen[sample_ids[0]] == [
        {"category": "正常", "confidence": None, "kind": "segment_class", "label": "normal"}
    ]
    assert frozen[sample_ids[1]] == [
        {"category": "气孔", "confidence": None, "kind": "segment_class", "label": "defect"}
    ]
    assert frozen[sample_ids[2]] == []  # 未标注 → 空快照，不是 None（None = 历史版本没冻结）

    refreshed = db.get(DatasetVersion, version.id)
    assert refreshed is not None
    assert (refreshed.quality or {})["empty_label_rate"] == pytest.approx(0.5)  # 4 片里 2 片未标注


# ── 6. 训练折叠与消费入口 ────────────────────────────────────────────


def test_training_folding_prefers_segment_label() -> None:
    """训练折叠优先认段级结论 `label`，词表加自定义类别也不会被折反。"""
    from app.services.torch_training import _is_defect_entry

    # 段级标注：结论权威，类别名不在白名单里也照样是缺陷
    assert _is_defect_entry({"category": "自定义类别", "label": "defect"}) is True
    assert _is_defect_entry({"category": "气孔", "label": "normal"}) is False
    # 旧标注（无 label）：仍按类别白名单折叠
    assert _is_defect_entry({"category": "气孔"}) is True
    assert _is_defect_entry({"category": "熔池"}) is False


def test_snapshot_and_annotated_ids_helpers(db, user) -> None:
    """服务层消费入口：空输入不炸；写入后 id 集合与快照同步。"""
    assert svc.snapshot_for_samples(db, []) == {}
    assert svc.annotated_sample_ids(db, []) == set()

    task, sample_ids = _seed_split_task(db)
    row = svc.upsert_annotation(
        db, db.get(Sample, sample_ids[0]), label="defect",
        category_id=_category_id(db, "焊穿"), note=None, user=user,
    )
    assert row.schema_version == svc.SCHEMA_VERSION == 1
    assert row.review_status == svc.DEFAULT_REVIEW_STATUS  # 复核态预留位有默认值
    db.commit()
    assert svc.annotated_sample_ids(db, sample_ids) == {sample_ids[0]}
    assert svc.snapshot_for_samples(db, sample_ids)[sample_ids[0]][0]["label"] == "defect"


def test_legacy_annotation_line_is_preserved(db, user) -> None:
    """旧 `annotations` 线不受影响：两条线在**冻结快照**里并存，互不覆盖。

    快照构建走 `datasets._annotation_snapshots`（构建时真正调用的那个合并入口），
    段级标注自己的 `snapshot_for_samples` 只负责自己那条线。
    """
    from app.services import datasets as datasets_svc

    _task, sample_ids = _seed_split_task(db)
    db.add(Annotation(sample_id=sample_ids[0], category="焊瘤", kind="box", box=[1, 2, 3, 4]))
    svc.upsert_annotation(
        db, db.get(Sample, sample_ids[0]), label="normal", category_id=None, note=None, user=user
    )
    db.commit()

    entries = datasets_svc._annotation_snapshots(db, [sample_ids[0]])[sample_ids[0]]
    assert {entry["kind"] for entry in entries} == {"box", "segment_class"}
    legacy = next(entry for entry in entries if entry["kind"] == "box")
    assert legacy["category"] == "焊瘤"  # 旧行原样保留，没有被段级标注改写
    # 段级线仍然只认自己那一行（两个入口职责不混）
    assert len(svc.snapshot_for_samples(db, [sample_ids[0]])[sample_ids[0]]) == 1
