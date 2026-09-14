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
import json
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
from app.services import signal_ingest
from app.models.analysis import AlignmentTask, Annotation, Sample, SplitTask
from app.models.datasets import Dataset, DatasetBuildTask, DatasetItem, DatasetVersion
from app.models.jobs import Job
from uuid import uuid4
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
    # 清掉 signal_ingest 的**进程内** parquet LRU：它的键是 `processed/{weld_id}/signals/{ingest.id}.parquet`，
    # 而各用例的 weld_id 与 ingest id 会重复（每个用例一套内存库）→ 不清缓存会读到上一个用例的信号
    # （实测表现：83 秒的用例拿到了 1 秒的信号 → 窗口越界）。生产里键含 ingest id，天然唯一。
    signal_ingest._PARQUET_CACHE.clear()
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
    # T4.2：焊机型号 / 焊接方法必须落在系统设置字典里（生产由 `seed_reference_data` 出厂初始化），
    # 测试库同样要有一个字典，否则登记会被 400 挡掉。
    from app.core.seed import seed_reference_data

    seed_reference_data(db)
    db.commit()
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
                # T4.2：这两个字段必须命中系统设置字典（见 `api` fixture 的 seed）
                "machine": "Fronius CMT",
                "weld_method": "MAG焊",
                "material": "Q235",
                "thickness": "6mm",
                # T4b/D7：登记体改为拆分后的新字段（量程校验：电流 1–2000A、电压 1–200V）
                "current_a": 180,
                "voltage_v": 22,
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

    # T10/D15：这个样本只有 CSV、没有视频 → 必须按**秒**切（unit="second"），
    # 0.1 秒窗口 @2kHz = 200 采样点，与旧口径的 200 采样点等价。
    split_body = {
        "unit": "second",
        "keep_event_buffer": 0,
        "task_format": "时序分类",
        "event_start": ARC,
        "event_end": TAIL,
    }
    _ok(api.post(
        f"{API}/welds/{record['weld_id']}/versions/{record['latest_version_id']}/split-tasks",
        json={**split_body, "fixed_rate": 0.1, "stride": 0.1},
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
        json={**split_body, "fixed_rate": 0.05, "stride": 0.05},
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


def test_invalid_split_window_is_rejected_and_does_not_feed_members(api, db, storage, run_job):
    """窗口放不下的切分请求在**创建阶段就被拒**（400），且不会留下任何切片。

    T10 起 `POST …/split-tasks` 会先按同一套规则试算一遍窗口（预览/执行共用
    `splitting.resolve_rule_seconds` + `build_windows`），放不下就 fail fast——比"建个任务
    让它在后台失败"更早给出原因。这里同时确认它不会污染数据集成员。
    """
    dataset_id = _create_dataset(api, "E2E 非法切分窗口", "时序分类")
    record = _register(api, dataset_id, "E2E 非法窗口样本")
    storage.put("raw/e2e-fail.csv", synthetic_signal_csv())

    _attach(api, record["id"], ["raw/e2e-fail.csv"])
    assert _run(db, run_job, _latest_job_uid(db, "signal_ingest")).status == "succeeded"

    # 窗口比整段有效区间（0.602 秒）还长 → 一个完整窗口都放不下
    rejected = api.post(
        f"{API}/welds/{record['weld_id']}/versions/{record['latest_version_id']}/split-tasks",
        json={
            "unit": "second",
            "fixed_rate": 5.0,
            "stride": 5.0,
            "keep_event_buffer": 0,
            "task_format": "时序分类",
            "event_start": ARC,
            "event_end": TAIL,
        },
    ).json()
    assert rejected["code"] == 40000, rejected
    assert "短于一个切片窗口" in rejected["message"], rejected

    # 再挂一个文件触发构建：没有任何切片 → 只收基础样本
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


# ── 场景 8：切分单位（T10）── 帧与采样率必须分开 ─────────────────────


def test_frame_unit_split_uses_video_fps_and_drops_the_tail(api, db, storage, run_job):
    """T10 验收：25 fps + 10 kHz + 83 秒有效区间 + 每切片 10 帧 → **207 个切片**、每个 4000 采样点。

    改造前把"帧"当成采样点：10 帧 = 10 个采样点 = 1 毫秒 → 同一区间会切出 ~8 万个切片。
    有效区间用 `event_start/end` 显式给（0–83 秒），避免依赖启发式事件检测的边界取整。
    视频帧率取自对齐产物里的元数据（真实链路是 ffmpeg 探测后写进 `tracks`）。
    """
    dataset_id = _create_dataset(api, "E2E 帧单位切分", "时序分类")
    record = _register(api, dataset_id, "E2E 帧单位样本", sample_rate="10 kHz")
    storage.put("raw/e2e-83s.csv", synthetic_signal_csv(fs=10000, seconds=83.0))
    _attach(api, record["id"], ["raw/e2e-83s.csv"])
    assert _run(db, run_job, _latest_job_uid(db, "signal_ingest")).status == "succeeded"

    # 对齐产物里带视频帧率（真实链路：ffmpeg 探测 → tracks[].metadata.fps）
    alignment_job = Job(job_uid=f"job_{uuid4().hex[:8]}", type="alignment", status="succeeded")
    db.add(alignment_job)
    db.flush()
    db.add(
        AlignmentTask(
            job_id=alignment_job.id,
            version_id=record["latest_version_id"],
            tracks=[{"channel": "video", "metadata": {"fps": 25.0}}],
        )
    )
    db.commit()

    body = {
        "unit": "frame",
        "fixed_rate": 10,
        "stride": 10,
        "keep_event_buffer": 0,
        "task_format": "时序分类",
        "event_start": 0.0,
        "event_end": 83.0,
    }
    preview = _ok(api.post(
        f"{API}/welds/{record['weld_id']}/versions/{record['latest_version_id']}/split-preview", json=body
    ))
    summary = preview["summary"]
    assert summary["sample_count"] == 207, summary  # 1 + (830000-4000)//4000，尾片丢弃
    assert summary["window_seconds"] == 0.4, summary  # 10 帧 ÷ 25 fps
    assert summary["window_samples"] == 4000, summary  # 0.4 秒 × 10 kHz
    assert summary["window_frames"] == 10, summary
    assert preview["input"]["video_fps"] == 25.0

    # 执行：切片数与预览必须一致，且每个时序切片的 CSV 都是 4000 数据行
    _ok(api.post(
        f"{API}/welds/{record['weld_id']}/versions/{record['latest_version_id']}/split-tasks", json=body
    ))
    job = _run(db, run_job, _latest_job_uid(db, "split"))
    assert job.status == "succeeded", job.error
    assert job.result["sample_count"] == 207 == summary["sample_count"]

    task = db.exec(select(SplitTask).order_by(SplitTask.id.desc())).first()
    first = db.exec(
        select(Sample).where(Sample.split_task_id == task.id).order_by(Sample.id)
    ).first()
    csv_key = next(key for key in first.object_keys if key.endswith(".csv"))
    lines = storage.objects[csv_key].decode("utf-8").strip().splitlines()
    assert len(lines) == 4001, len(lines)  # 1 行表头 + 4000 数据行
    assert first.meta["window_seconds"] == 0.4
    assert first.meta["rules_version"] == 2

    # T16：分段成功后自动生成「样本分段」数据版本，object_keys = 源版本文件 ∪ 产物清单
    versions = _ok(api.get(f"{API}/welds/{record['weld_id']}/versions"))
    split_version = next((v for v in versions if v["action"] == "样本分段"), None)
    assert split_version is not None, [v["action"] for v in versions]
    manifest_key = f"processed/{record['weld_id']}/split/{task.id}/manifest.json"
    assert manifest_key in split_version["object_keys"], split_version["object_keys"]
    assert "raw/e2e-83s.csv" in split_version["object_keys"], "必须合并源版本文件，否则读原始信号会断链"
    manifest = json.loads(storage.objects[manifest_key].decode("utf-8"))
    assert manifest["sample_count"] == 207 and manifest["rules_version"] == 2
    assert len(manifest["slices"]) == 207


def test_second_unit_split_works_without_video(api, db, storage, run_job):
    """D15：没有视频的数据按**秒**切；按帧则明确报错（不猜默认帧率）。"""
    dataset_id = _create_dataset(api, "E2E 秒单位切分", "时序分类")
    record = _register(api, dataset_id, "E2E 秒单位样本", sample_rate="2 kHz")
    storage.put("raw/e2e-2k.csv", synthetic_signal_csv())
    _attach(api, record["id"], ["raw/e2e-2k.csv"])
    assert _run(db, run_job, _latest_job_uid(db, "signal_ingest")).status == "succeeded"

    base = {
        "keep_event_buffer": 0,
        "task_format": "时序分类",
        "event_start": ARC,
        "event_end": TAIL,
    }
    # 按帧：这个版本没有视频 → 400 且说明原因
    by_frame = api.post(
        f"{API}/welds/{record['weld_id']}/versions/{record['latest_version_id']}/split-preview",
        json={**base, "unit": "frame", "fixed_rate": 10, "stride": 10},
    ).json()
    assert by_frame["code"] == 40000 and "帧率" in by_frame["message"], by_frame

    # 按秒：0.1 秒窗口 @2kHz = 200 采样点 → 与旧口径等价
    by_second = _ok(api.post(
        f"{API}/welds/{record['weld_id']}/versions/{record['latest_version_id']}/split-preview",
        json={**base, "unit": "second", "fixed_rate": 0.1, "stride": 0.1},
    ))
    assert by_second["summary"]["window_samples"] == 200
    assert by_second["summary"]["sample_count"] == 6
    assert by_second["summary"]["window_frames"] is None  # 没有 fps 就不编一个帧数


# ── 场景 9：数据集版本冻结标注快照（T16.1） ──────────────────────────


def test_dataset_version_freezes_annotation_snapshot(api, db, storage, run_job):
    """版本构建后删掉标注，同一版本的训练输入**不变**（否则"可复现训练"不成立）。

    可观察的判定方式：构建后把 `annotations` 行**全部删除**再训练——
    冻结生效 → 标签仍来自快照（两类齐全）→ 训练成功；
    没冻住（训练现查 annotations）→ 全部样本退化成"正常"一类 → 训练直接失败。
    """
    dataset_id = _create_dataset(api, "E2E 冻结标注", "时序分类")
    records = []
    for index in range(6):
        record = _register(api, dataset_id, f"E2E 冻结样本-{index}")
        storage.put(f"raw/e2e-freeze-{index}.csv", synthetic_signal_csv())
        _attach(api, record["id"], [f"raw/e2e-freeze-{index}.csv"])
        records.append(record)

    version = _latest_dataset_version(db, dataset_id)
    assert _run(db, run_job, _build_job_uid(db, version.id)).status == "succeeded"

    # 给前三条打「气孔」（缺陷白名单内），后三条打「正常」
    items = db.exec(
        select(DatasetItem).where(DatasetItem.dataset_version_id == version.id).order_by(DatasetItem.id)
    ).all()
    assert len(items) == 6
    for index, item in enumerate(items):
        db.add(Annotation(sample_id=item.sample_id, category="气孔" if index < 3 else "正常", kind="box", box=[1, 1, 2, 2]))
    db.commit()

    # 重新构建一次（新版本）——快照在这次构建时写入
    storage.put("raw/e2e-freeze-trigger.bin", b"t" * 8)
    _attach(api, records[0]["id"], ["raw/e2e-freeze-trigger.bin"])
    fresh_version = _latest_dataset_version(db, dataset_id)
    assert _run(db, run_job, _build_job_uid(db, fresh_version.id)).status == "succeeded"
    db.expire_all()

    snapshots = [
        item.annotations
        for item in db.exec(
            select(DatasetItem).where(DatasetItem.dataset_version_id == fresh_version.id)
        ).all()
    ]
    assert all(snapshot is not None for snapshot in snapshots), snapshots
    frozen_categories = sorted(
        str(entry["category"]) for snapshot in snapshots for entry in snapshot
    )
    assert frozen_categories.count("气孔") == 3 and frozen_categories.count("正常") == 3, frozen_categories

    # **删掉全部标注行**：冻结生效时训练仍能拿到两类；没冻住就会退化成单类而失败
    for annotation in db.exec(select(Annotation)).all():
        db.delete(annotation)
    db.commit()

    _ok(api.post(f"{API}/training-tasks", json={
        "dataset_version_id": fresh_version.id,
        "epochs": 2,
        "batch_size": 2,
        "learning_rate": 0.01,
        "val_ratio": 0.2,
    }))
    trained = _run(db, run_job, _latest_job_uid(db, "training"))
    assert trained.status == "succeeded", trained.error


# ── 场景 10：特征产物落盘与 partial 闸门（T16.3） ────────────────────


def test_partial_feature_extraction_writes_no_version(api, db, storage, run_job, monkeypatch):
    """partial（缺模态 / 启发式模态）的特征提取**不生成数据版本**——产物不算正式。

    这个版本只有 CSV：视觉与音频都缺失。默认（生产设置）直接失败；放开 `feature_allow_partial`
    后任务成功但状态是 `partial`，两种情况下都**不应该**出现「特征提取」版本。
    """
    dataset_id = _create_dataset(api, "E2E 特征闸门", "时序分类")
    record = _register(api, dataset_id, "E2E 特征样本", sample_rate="2 kHz")
    storage.put("raw/e2e-feat.csv", synthetic_signal_csv())
    _attach(api, record["id"], ["raw/e2e-feat.csv"])
    assert _run(db, run_job, _latest_job_uid(db, "signal_ingest")).status == "succeeded"

    body = {"weld_id": record["weld_id"], "version_id": record["latest_version_id"]}
    _ok(api.post(f"{API}/features/extract-tasks", json=body))
    failed = _run(db, run_job, _latest_job_uid(db, "feature_extraction"))
    assert failed.status == "failed", "生产设置下缺模态应当直接失败"
    assert "生产模式禁止使用不完整或非正式模态结果" in str(failed.error), failed.error

    # 放开 partial：任务成功但状态 partial → 仍然不生成版本
    monkeypatch.setattr("app.core.config.settings.feature_allow_partial", True, raising=False)
    _ok(api.post(f"{API}/features/extract-tasks", json=body))
    partial = _run(db, run_job, _latest_job_uid(db, "feature_extraction"))
    assert partial.status == "succeeded", partial.error
    assert partial.result["status"] == "partial", partial.result
    assert partial.result["version"] is None, partial.result

    versions = _ok(api.get(f"{API}/welds/{record['weld_id']}/versions"))
    assert not any(v["action"] == "特征提取" for v in versions), [v["action"] for v in versions]


# ── 场景：登记链路的可恢复状态（T4.4 / R2）────────────────────────────


def test_ingest_status_walks_upload_import_ready(api, db, storage, run_job):
    """待上传 → 导入中 → 可分析：状态全部由后端从已有数据推导，刷新/换设备看到的都一样。"""
    dataset_id = _create_dataset(api, "E2E 状态数据集", "时序分类")
    record = _register(api, dataset_id, "E2E 状态样本")

    # 登记刚建好：v1.0 还没有文件
    state = _ok(api.get(f"{API}/registrations/{record['id']}/ingest-status"))
    assert state["status"] == "awaiting_upload", state
    assert state["uploaded_files"] == 0

    # 挂载 CSV（挂载会自动建 signal_ingest 任务，但执行器还没跑）→ 导入中
    storage.put("raw/e2e-status.csv", synthetic_signal_csv())
    _attach(api, record["id"], ["raw/e2e-status.csv"])
    state = _ok(api.get(f"{API}/registrations/{record['id']}/ingest-status"))
    assert state["status"] == "importing", state
    assert state["csv_total"] == 1

    # 执行导入 → 可分析
    assert _run(db, run_job, _latest_job_uid(db, "signal_ingest")).status == "succeeded"
    state = _ok(api.get(f"{API}/registrations/{record['id']}/ingest-status"))
    assert state["status"] == "ready", state
    assert state["csv_failed"] == []


def test_attach_existing_csv_returns_dedicated_conflict_code(api, db, storage):
    """重复挂载同一个 CSV → 409 且带**独立错误码** 40901。

    前端据此判定"上一次挂载其实成功了、只是响应丢了"，继续进导入态而不是卡在失败
    （按中文文案匹配太脆，所以走错误码）。
    """
    dataset_id = _create_dataset(api, "E2E 重复挂载", "时序分类")
    record = _register(api, dataset_id, "E2E 重复挂载样本")
    storage.put("raw/e2e-dup.csv", synthetic_signal_csv())
    _attach(api, record["id"], ["raw/e2e-dup.csv"])

    second = api.post(
        f"{API}/registrations/{record['id']}/raw-files",
        json={"object_keys": ["raw/e2e-dup.csv"], "storage_bytes": 4096},
    )
    assert second.status_code == 409, second.json()
    assert second.json()["code"] == 40901, second.json()


def test_reimport_requeues_failed_ingest(api, db, storage, run_job):
    """导入失败 → 状态 failed 且给出失败文件 → 「重新导入」清掉 failed 行重新入队 → 可分析。

    这是线上踩过的坑：`signal_ingests` 对 (version_id, source_object_key) 唯一，失败行也会被
    挂载接口的 409 拦掉，于是那个文件**永远卡住**（旧代码解析不了、新代码能解析也一样）。
    """
    dataset_id = _create_dataset(api, "E2E 重新导入", "时序分类")
    record = _register(api, dataset_id, "E2E 重新导入样本")
    # 内容不是合法时序：导入必然失败（第一次执行器跑出来的就是 failed 行）
    storage.put("raw/e2e-bad.csv", b"not,a,signal\n\x00\x01\x02")
    _attach(api, record["id"], ["raw/e2e-bad.csv"])
    failed = _run(db, run_job, _latest_job_uid(db, "signal_ingest"))
    assert failed.status == "failed", failed.result

    state = _ok(api.get(f"{API}/registrations/{record['id']}/ingest-status"))
    assert state["status"] == "failed", state
    assert [item["source_object_key"] for item in state["csv_failed"]] == ["raw/e2e-bad.csv"]

    # 换成能被解析的内容（模拟"旧代码失败的导入，新代码能解析"），再点重新导入
    storage.put("raw/e2e-bad.csv", synthetic_signal_csv())
    state = _ok(api.post(f"{API}/registrations/{record['id']}/reimport"))
    assert state["status"] == "importing", state
    assert state["csv_failed"] == []

    # 重新入队的是**新**任务（旧 job 与其 failed 行已清掉）
    assert _run(db, run_job, _latest_job_uid(db, "signal_ingest")).status == "succeeded"
    assert _ok(api.get(f"{API}/registrations/{record['id']}/ingest-status"))["status"] == "ready"


def test_reimport_without_failed_rows_is_rejected(api, db, storage, run_job):
    """没有失败文件时不该清库：明确 400，别让用户以为"点了就好"。"""
    dataset_id = _create_dataset(api, "E2E 无失败", "时序分类")
    record = _register(api, dataset_id, "E2E 无失败样本")
    storage.put("raw/e2e-ok.csv", synthetic_signal_csv())
    _attach(api, record["id"], ["raw/e2e-ok.csv"])
    assert _run(db, run_job, _latest_job_uid(db, "signal_ingest")).status == "succeeded"

    response = api.post(f"{API}/registrations/{record['id']}/reimport")
    assert response.status_code == 400, response.json()
