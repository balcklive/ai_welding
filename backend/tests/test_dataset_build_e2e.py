"""数据集构建链路端到端回归（T11，2026-09-14）。

**全部走真实 HTTP 接口 + 真实 Job 执行器（`executor.run_job`）**，不调用任何私有函数：

    登记 POST /registrations → 挂载文件 POST …/raw-files（自动建数据集版本 + 自动构建任务）
    → 信号导入（signal_ingest job）→ 分段 POST …/split-tasks（split job）
    → 构建（dataset_build job）→ 读回 GET /datasets/{id}/versions/{vid}[/items] 断言

覆盖（每条都对应一次真实缺陷或线上实测）：

1. **标注锚点样本不得成为数据集版本成员**（T11）——线上数据集 1 的 8 个成员里 7 个是
   `signal-anchor`/`video-anchor` 锚点，且 `(record_id, frame_no)` 判重把 `frame_no` 为 NULL
   的锚点全塌成一个键，把 `repeat_rate` 假报成 0.75；
2. **只收最近一次成功分段任务的切片**（T11 / D16-A 前置）——旧任务的切片留在库里但不进新版本；
3. **failed 分段不产生成员**；
4. **删除预检与真删一致**（T7）；
5. **登记写 `20K`、CSV 无时间列时靠登记的采样率兜底**（`_parse_fs` 修复）；
6. **挂载响应带出构建任务、版本列表能读出构建状态、重试幂等且不过手工闸门、乱序构建不动指针**（T8）。

隔离手段：内存 SQLite（StaticPool，请求 session 与 Job session 共用同一连接）+ 假 Storage
（内存 dict，不连 MinIO）。执行器 session 通过 monkeypatch `app.jobs.executor.SessionLocal` 指到测试引擎。
"""

import csv
import io
import random
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, select

from app.api.deps import get_current_user
from app.core.db import get_session
from app.main import app
from app.models import User
from app.models.datasets import Dataset, DatasetBuildTask, DatasetVersion
from app.models.jobs import Job
from app.storage.client import StorageClient

client = TestClient(app)

FS = 2000  # 合成信号采样率
ARC, TAIL = 0.2, 0.8  # 焊接段起止（秒）→ 有效区间 0.602s 实测为 [0.199, 0.801]
API = "/api/v1"


class FakeStorage:
    """内存假存储：不连 MinIO（只实现本链路走到的接口）。"""

    normalize_key = staticmethod(StorageClient.normalize_key)
    normalize_filename = staticmethod(StorageClient.normalize_filename)

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put(self, object_key: str, data: bytes) -> None:
        self.objects[object_key] = data

    def upload_stream(self, object_key, fileobj, size, content_type):  # noqa: ANN001
        self.objects[object_key] = fileobj.read()

    def get_object(self, object_key: str) -> bytes:
        if object_key not in self.objects:
            raise FileNotFoundError(object_key)
        return self.objects[object_key]

    def stat_object(self, object_key: str) -> int:
        return len(self.objects.get(object_key, b""))

    def delete_object(self, object_key: str) -> None:
        self.objects.pop(object_key, None)

    def presign_get(self, object_key: str, expires: int = 3600) -> str:
        return f"https://fake.local/{object_key}"

    def presign_put(self, *args, **kwargs) -> str:  # noqa: ANN002, ANN003
        return "https://fake.local/put"

    def check_ready(self) -> None:
        return None


def synthetic_signal_csv(fs: int = FS, seconds: float = 1.0, with_time: bool = True) -> bytes:
    """起弧 0.2s / 收弧 0.8s 的方波焊接信号（实测可过 10 条导入校验与事件检测）。

    `with_time=False` 去掉时间列——此时导入必须靠登记的 `sample_rate` 兜底推采样率（`_parse_fs`）。
    """
    rng = random.Random(7)
    out = io.StringIO(newline="")
    writer = csv.writer(out)
    writer.writerow(["time", "Current", "Voltage", "GasSpeed", "WireSpeed"] if with_time else ["Current", "Voltage", "GasSpeed", "WireSpeed"])
    for index in range(int(fs * seconds)):
        moment = index / fs
        welding = ARC <= moment <= TAIL
        row = (
            (180 + rng.uniform(-5, 5), 22 + rng.uniform(-0.5, 0.5), 15, 8)
            if welding
            else (rng.uniform(0, 0.5), 0.0, 0.2, 0.0)
        )
        cells = [f"{value:.3f}" for value in row]
        writer.writerow([f"{moment:.4f}", *cells] if with_time else cells)
    return out.getvalue().encode()


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
    with Session(engine) as session:
        yield session


@pytest.fixture()
def storage(monkeypatch):
    fake = FakeStorage()
    # 三个模块各自 `from app.storage import get_storage`（有的模块级、有的延迟），都要指到假存储。
    for target in (
        "app.storage.get_storage",
        "app.api.v1.welds.get_storage",
        "app.jobs.split.get_storage",
    ):
        monkeypatch.setattr(target, lambda: fake)
    return fake


@pytest.fixture()
def run_job(monkeypatch, engine):
    """Job 执行器的 session 指到测试引擎，并返回同步执行入口。

    必须返回 **SQLModel 的 Session**（原生 SQLAlchemy Session 没有 `.exec`）。
    """
    from app.jobs.executor import run_job as _run_job

    monkeypatch.setattr(
        "app.jobs.executor.SessionLocal",
        lambda: Session(engine, expire_on_commit=False),
    )
    return _run_job


@pytest.fixture()
def api(db, request):
    app.dependency_overrides[get_session] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: User(
        id=1, username="e2e", password_hash="x", display_name="E2E", role="admin"
    )
    yield client
    app.dependency_overrides.pop(get_session, None)
    app.dependency_overrides.pop(get_current_user, None)


# ── 接口小助手 ───────────────────────────────────────────────────────


def _ok(response):
    payload = response.json()
    assert payload["code"] == 0, payload
    return payload["data"]


def _create_dataset(api, name: str, task: str = "目标检测") -> int:
    return _ok(api.post(f"{API}/datasets", json={"name": name, "task": task}))["id"]


def _register(api, dataset_id: int, weld_name: str, sample_rate: str = "2 kHz") -> dict:
    return _ok(
        api.post(
            f"{API}/registrations",
            json={
                "dataset_id": dataset_id,
                "source": "E2E 产线",
                "collected_at": "2026-09-01T10:00:00",
                "weld_name": weld_name,
                "machine": "E2E 焊机",
                "weld_method": "MAG焊",
                "material": "Q235",
                "thickness": "6mm",
                "current_voltage": "180A/22V",
                "sample_rate": sample_rate,
            },
        )
    )


def _attach(api, record_id: int, keys: list[str], storage_bytes: int = 4096) -> dict:
    """挂载文件：同一事务里会**自动**新建数据集版本 + 构建任务（登记链路的生产路径）。"""
    return _ok(
        api.post(
            f"{API}/registrations/{record_id}/raw-files",
            json={"object_keys": keys, "storage_bytes": storage_bytes},
        )
    )


def _latest_dataset_version(db, dataset_id: int) -> DatasetVersion:
    version = db.exec(
        select(DatasetVersion)
        .where(DatasetVersion.dataset_id == dataset_id)
        .order_by(DatasetVersion.id.desc())
    ).first()
    assert version is not None, "挂载文件应当自动创建数据集版本"
    return version


def _build_job_uid(db, dataset_version_id: int) -> str:
    """按数据集版本取构建任务的 job_uid（T8 起挂载响应已带 `dataset_build.job_id`，这里走库更直接）。"""
    task = db.exec(
        select(DatasetBuildTask).where(
            DatasetBuildTask.dataset_version_id == dataset_version_id
        )
    ).first()
    assert task is not None, "自动构建应当同时创建 DatasetBuildTask"
    job = db.get(Job, task.job_id)
    assert job is not None
    return job.job_uid


def _latest_job_uid(db, job_type: str) -> str:
    job = db.exec(select(Job).where(Job.type == job_type).order_by(Job.id.desc())).first()
    assert job is not None, f"没有 {job_type} 任务"
    return job.job_uid


def _run(db, run_job, job_uid: str) -> Job:
    run_job(job_uid)
    db.expire_all()
    job = db.exec(select(Job).where(Job.job_uid == job_uid)).one()
    return job


def _members(api, dataset_id: int, version_id: int) -> tuple[int, list[int]]:
    page = _ok(
        api.get(f"{API}/datasets/{dataset_id}/versions/{version_id}/items?page_size=100")
    )
    return page["total"], [item["sample_id"] for item in page["items"]]


def _quality(api, dataset_id: int, version_id: int) -> dict:
    return _ok(api.get(f"{API}/datasets/{dataset_id}/versions/{version_id}"))["quality"]


# ── 场景 1：锚点样本不进版本（线上事故复现） ──────────────────────────


def test_video_anchor_never_becomes_a_dataset_member(api, db, storage, run_job):
    """登记 → 挂载视频 → 建视频标注任务（生成锚点）→ 构建：成员只有基础样本，重复率 0。"""
    dataset_id = _create_dataset(api, "E2E 锚点数据集")
    record = _register(api, dataset_id, "E2E 锚点样本")
    storage.put("raw/e2e-demo.mp4", b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64)

    _attach(api, record["id"], ["raw/e2e-demo.mp4"])
    version = _latest_dataset_version(db, dataset_id)

    # 视频锚点标注任务：后端会为它建一条 `meta.source="video-anchor"` 的锚点样本。
    _ok(
        api.post(
            f"{API}/annotation-tasks",
            json={"source": "video", "version_id": record["latest_version_id"], "name": "E2E-AN"},
        )
    )

    job = _run(db, run_job, _build_job_uid(db, version.id))
    assert job.status == "succeeded", job.error

    total, sample_ids = _members(api, dataset_id, version.id)
    assert total == 1, "锚点样本不得成为成员（线上事故：8 个成员里 7 个是锚点）"
    # 唯一成员是引用原始文件的基础样本；repeat_rate 不得被无 frame_no 的样本污染
    assert _quality(api, dataset_id, version.id)["repeat_rate"] == 0.0

    # 再挂一个文件 → 第二次构建：基础样本复用同一条，不堆积新样本
    storage.put("raw/e2e-extra.bin", b"x" * 8)
    _attach(api, record["id"], ["raw/e2e-extra.bin"])
    second = _latest_dataset_version(db, dataset_id)
    assert second.id != version.id
    _run(db, run_job, _build_job_uid(db, second.id))
    assert _members(api, dataset_id, second.id)[1] == sample_ids


# ── 场景 2：只有最近一次成功分段任务的切片进版本（D16-A 前置） ──────────


def test_build_keeps_only_the_latest_succeeded_split_slices(api, db, storage, run_job):
    """导入 → 第一次分段 → 构建（6 切片）→ 第二次分段 → 再构建（12 切片，旧切片留在历史版本）。"""
    dataset_id = _create_dataset(api, "E2E 分段数据集", "时序分类")
    record = _register(api, dataset_id, "E2E 分段样本")
    storage.put("raw/e2e-signal.csv", synthetic_signal_csv())

    _attach(api, record["id"], ["raw/e2e-signal.csv"])
    first_version = _latest_dataset_version(db, dataset_id)

    # 信号导入：CSV 必须真的过校验并落 Parquet，分段才有真实输入
    ingest = _run(db, run_job, _latest_job_uid(db, "signal_ingest"))
    assert ingest.status == "succeeded", ingest.error

    split_body = {
        "keep_event_buffer": 0,
        "task_format": "时序分类",
        "event_start": ARC,
        "event_end": TAIL,
    }
    _ok(api.post(
        f"{API}/welds/{record['weld_id']}/versions/{record['latest_version_id']}/split-tasks",
        json={**split_body, "fixed_rate": 200, "stride": 200},
    ))
    first_split = _run(db, run_job, _latest_job_uid(db, "split"))
    assert first_split.status == "succeeded", first_split.error
    first_slices = first_split.result["sample_count"]
    assert first_slices > 1

    # 构建在分段**之后**执行：应当收到这一次分段任务的切片
    assert _run(db, run_job, _build_job_uid(db, first_version.id)).status == "succeeded"
    total, first_members = _members(api, dataset_id, first_version.id)
    assert total == first_slices
    assert _quality(api, dataset_id, first_version.id)["repeat_rate"] == 0.0

    # 重新分段（不同规则 → 切片数不同），再挂一个文件触发第二次构建
    _ok(api.post(
        f"{API}/welds/{record['weld_id']}/versions/{record['latest_version_id']}/split-tasks",
        json={**split_body, "fixed_rate": 100, "stride": 100},
    ))
    second_split = _run(db, run_job, _latest_job_uid(db, "split"))
    assert second_split.status == "succeeded", second_split.error
    second_slices = second_split.result["sample_count"]
    assert second_slices > first_slices

    storage.put("raw/e2e-trigger.bin", b"y" * 8)
    _attach(api, record["id"], ["raw/e2e-trigger.bin"])
    second_version = _latest_dataset_version(db, dataset_id)
    assert _run(db, run_job, _build_job_uid(db, second_version.id)).status == "succeeded"

    total, second_members = _members(api, dataset_id, second_version.id)
    assert total == second_slices, "只应收到最近一次成功分段的切片"
    assert set(second_members).isdisjoint(first_members), "旧分段任务的切片不得混进新版本"
    assert _quality(api, dataset_id, second_version.id)["repeat_rate"] == 0.0

    # 历史版本不受影响（D16-A：旧切片留在库里、留在已发布的版本里）
    assert _members(api, dataset_id, first_version.id)[1] == first_members


# ── 场景 3：分段失败不得污染成员 ─────────────────────────────────────


def test_failed_split_does_not_feed_members(api, db, storage, run_job):
    """分段任务失败的记录：构建仍只收到基础样本，不因 failed 任务产生任何切片。"""
    dataset_id = _create_dataset(api, "E2E 失败分段", "时序分类")
    record = _register(api, dataset_id, "E2E 失败分段样本")
    storage.put("raw/e2e-fail.csv", synthetic_signal_csv())

    _attach(api, record["id"], ["raw/e2e-fail.csv"])
    assert _run(db, run_job, _latest_job_uid(db, "signal_ingest")).status == "succeeded"

    # 窗口比有效区间还长 → handler 抛 SplitInputError → job failed
    _ok(api.post(
        f"{API}/welds/{record['weld_id']}/versions/{record['latest_version_id']}/split-tasks",
        json={
            "fixed_rate": 999999,
            "stride": 999999,
            "keep_event_buffer": 0,
            "task_format": "时序分类",
            "event_start": ARC,
            "event_end": TAIL,
        },
    ))
    assert _run(db, run_job, _latest_job_uid(db, "split")).status == "failed"

    storage.put("raw/e2e-fail-trigger.bin", b"z" * 8)
    _attach(api, record["id"], ["raw/e2e-fail-trigger.bin"])
    version = _latest_dataset_version(db, dataset_id)
    assert _run(db, run_job, _build_job_uid(db, version.id)).status == "succeeded"

    total, _ = _members(api, dataset_id, version.id)
    assert total == 1, "没有成功的分段任务 → 只收一条基础样本"


# ── 场景 4：登记里写的采样率写法要能被解析（`_parse_fs` 修复回归） ──────


def test_sample_rate_written_without_hz_unit_still_ingests(api, db, storage, run_job):
    """登记写 `20K`（不带 Hz）、CSV 又**没有时间列** → 必须靠登记的采样率兜底。

    旧 `_parse_fs` 的正则强制要求 `Hz`，`20K` 与纯数字都解析成 None → 时间列缺失时采样率推导
    失败（实测线上确有 `sample_rate = '20K'`）。这里从登记一路打到读回信号，断言 20 kHz 生效。
    """
    dataset_id = _create_dataset(api, "E2E 采样率写法", "时序分类")
    record = _register(api, dataset_id, "E2E 无时间列样本", sample_rate="20K")
    storage.put("raw/e2e-no-time.csv", synthetic_signal_csv(fs=20000, seconds=0.6, with_time=False))

    _attach(api, record["id"], ["raw/e2e-no-time.csv"])
    ingest = _run(db, run_job, _latest_job_uid(db, "signal_ingest"))
    assert ingest.status == "succeeded", ingest.error

    signals = _ok(api.get(f"{API}/welds/{record['weld_id']}/versions/{record['latest_version_id']}/signals?max_points=100"))
    assert signals["sample_rate"] == 20000, signals["sample_rate"]


# ── 场景 5：删除预检与实际删除必须一致（T7） ─────────────────────────


def test_delete_impact_matches_actual_delete(api, db, storage, run_job):
    """预检说能删就真能删、说不能删就真会被拒——两者共用同一份引用规则。

    改造前弹窗只能靠前端猜（示例甚至写着"样本 1 仍可删"），而真删时只要还有登记数据就拒绝。
    """
    dataset_id = _create_dataset(api, "E2E 删除预检")
    record = _register(api, dataset_id, "E2E 删除预检样本")
    storage.put("raw/e2e-del.csv", synthetic_signal_csv())
    _attach(api, record["id"], ["raw/e2e-del.csv"])
    version = _latest_dataset_version(db, dataset_id)
    assert _run(db, run_job, _build_job_uid(db, version.id)).status == "succeeded"

    # 有登记样本 → 预检阻塞，真删也必须被拒
    dataset_impact = _ok(api.get(f"{API}/datasets/{dataset_id}/delete-impact"))
    assert dataset_impact["can_delete"] is False
    assert any("登记样本" in reason for reason in dataset_impact["blocking"]), dataset_impact
    assert dataset_impact["counts"]["样本数"] == 1
    denied = api.delete(f"{API}/datasets/{dataset_id}").json()
    assert denied["code"] == 40900, denied

    # 样本已进构建版本（成员引用）→ 预检阻塞，真删同样被拒
    weld_impact = _ok(api.get(f"{API}/welds/{record['weld_id']}/delete-impact"))
    assert weld_impact["can_delete"] is False, weld_impact
    assert any("数据集版本成员引用" in reason for reason in weld_impact["blocking"]), weld_impact
    denied_weld = api.delete(f"{API}/welds/{record['weld_id']}").json()
    assert denied_weld["code"] == 40900, denied_weld

    # 空数据集 → 预检放行，真删成功（且不再整页 reload，由前端局部刷新）
    empty_id = _create_dataset(api, "E2E 可删空数据集")
    empty_impact = _ok(api.get(f"{API}/datasets/{empty_id}/delete-impact"))
    assert empty_impact["can_delete"] is True and empty_impact["blocking"] == []
    assert api.delete(f"{API}/datasets/{empty_id}").json()["code"] == 0


# ── 场景 6：异步构建的状态出口（T8） ─────────────────────────────────


def test_attach_exposes_build_ticket_and_version_build_status(api, db, storage, run_job):
    """挂载响应必须带出自动构建任务；版本列表必须能读出构建状态（否则前端无从轮询/恢复）。"""
    dataset_id = _create_dataset(api, "E2E 构建状态")
    record = _register(api, dataset_id, "E2E 构建状态样本")
    storage.put("raw/e2e-status.bin", b"s" * 8)

    attached = _attach(api, record["id"], ["raw/e2e-status.bin"])
    ticket = attached.get("dataset_build")
    assert ticket is not None, "挂载响应应带出自动构建任务（dataset_build）"
    assert ticket["job_id"].startswith("job_")
    assert ticket["dataset_version_id"] == _latest_dataset_version(db, dataset_id).id

    # 构建前：状态是 pending（前端据此显示"构建中"并禁用查看切片）
    before = _ok(api.get(f"{API}/datasets/{dataset_id}/versions"))
    row = next(item for item in before if item["id"] == ticket["dataset_version_id"])
    assert row["build_status"] == "pending", row
    assert row["build_job_id"] == ticket["job_id"]

    assert _run(db, run_job, ticket["job_id"]).status == "succeeded"
    after = _ok(api.get(f"{API}/datasets/{dataset_id}/versions"))
    row = next(item for item in after if item["id"] == ticket["dataset_version_id"])
    assert row["build_status"] == "succeeded", row


def test_build_retry_is_idempotent_and_bypasses_manual_gate(api, db, storage, run_job):
    """重试端点：不走手工闸门（数据集还是"标注中"也能重试）、已有进行中任务时返回它。"""
    dataset_id = _create_dataset(api, "E2E 构建重试")
    version_id = _ok(api.post(f"{API}/datasets/{dataset_id}/versions", json={}))["id"]
    # 手工建的空版本没有构建任务 → build_status 为空
    manual_row = next(item for item in _ok(api.get(f"{API}/datasets/{dataset_id}/versions")) if item["id"] == version_id)
    assert manual_row["build_status"] is None, manual_row

    first = _ok(api.post(f"{API}/datasets/{dataset_id}/versions/{version_id}/build-tasks/retry"))
    assert first["created"] is True
    second = _ok(api.post(f"{API}/datasets/{dataset_id}/versions/{version_id}/build-tasks/retry"))
    assert second["created"] is False and second["job_id"] == first["job_id"], (first, second)

    # 这个数据集一条登记数据都没有 → 构建会失败（"没有可用于构建数据集的真实样本"），
    # 但**任务确实被创建并执行了**（证明重试没被"可训练"闸门挡住）。
    assert _run(db, run_job, first["job_id"]).status == "failed"


def test_out_of_order_build_does_not_move_the_current_pointer(api, db, storage, run_job):
    """乱序完成的旧构建不得把 current_version_id 指回旧版本（T8 指针守卫）。"""
    dataset_id = _create_dataset(api, "E2E 指针守卫")
    record = _register(api, dataset_id, "E2E 指针守卫样本")
    storage.put("raw/e2e-old.bin", b"o" * 8)
    storage.put("raw/e2e-new.bin", b"n" * 8)

    _attach(api, record["id"], ["raw/e2e-old.bin"])
    old_version = _latest_dataset_version(db, dataset_id)
    old_job = _build_job_uid(db, old_version.id)
    _attach(api, record["id"], ["raw/e2e-new.bin"])
    new_version = _latest_dataset_version(db, dataset_id)
    assert new_version.id > old_version.id

    # 先跑新版本，再跑旧版本：旧任务完成后不能把指针拽回去
    assert _run(db, run_job, _build_job_uid(db, new_version.id)).status == "succeeded"
    assert _run(db, run_job, old_job).status == "succeeded"
    db.expire_all()

    assert db.get(Dataset, dataset_id).current_version_id == new_version.id
    # 旧版本自己的统计仍然落库（只是不动 dataset 指针）
    assert db.get(DatasetVersion, old_version.id).item_count == 1


# ── 场景 7：数据集列表的分页 / 关键字 / 选择器轻量接口（T9） ───────────


def test_dataset_list_pagination_search_and_options(api, db):
    """`GET /datasets` 默认分页 + `q` 过滤；`options=1` 回不分页的轻量列表（D19）。"""
    ids = [_create_dataset(api, f"E2E 分页-{index}") for index in range(3)]

    first = _ok(api.get(f"{API}/datasets?page=1&page_size=2"))
    assert set(first.keys()) == {"items", "total", "page", "page_size"}, first
    assert first["total"] == 3 and len(first["items"]) == 2, first
    second = _ok(api.get(f"{API}/datasets?page=2&page_size=2"))
    assert len(second["items"]) == 1
    # page_size 被钳制到 ≤100
    assert _ok(api.get(f"{API}/datasets?page_size=9999"))["page_size"] == 100

    hit = _ok(api.get(f"{API}/datasets?q=E2E 分页-1"))
    assert hit["total"] == 1 and hit["items"][0]["name"] == "E2E 分页-1", hit
    assert _ok(api.get(f"{API}/datasets?q=不存在的名字"))["total"] == 0

    options = _ok(api.get(f"{API}/datasets?options=1"))
    assert isinstance(options, list) and len(options) >= 3
    assert set(options[0]) == {
        "id", "dataset_no", "name", "task", "status", "sample_count", "weld_count",
        "progress", "current_version_id", "version", "split",
    }, options[0]
    assert all(item["id"] in ids or item["name"].startswith("E2E 分页") for item in options)
