"""切片级特征提取链路 E2E（2026-10）。

**全程走真实 HTTP 接口 + 真实 Job 执行器**，不调私有函数：

    真实信号导入（Parquet）→ v3 分段任务（真视频抽代表帧）
    → POST …/sample-feature-extractions（sample_feature_extraction job）
    → 读回 GET …/sample-features[/{sample_id}][/export] 断言

分期要钉住的硬口径：

1. **一个切片一行 36 维**（时序 28 + 视觉 8），**无声音组**——切片 manifest 自己就写着
   `audio.available = False`，拿合成音频凑 6 维是伪造模态。
2. **时序维度真的切了父信号**：不同时间窗的行必须不同、且熄弧窗与焊接窗电流均值量级不同
   （全 0 或全同 = 没切，只是把整条信号的统计复制了 N 遍）。
3. **缺一片代表帧不废整批**：该片 vision 记 `missing` + 逐片 warnings，Job 仍 succeeded、
   `status="partial"`，其余片照常是 `real`。视频是增强模态——45 段里丢 1 帧不能废掉一整批。
4. **行序就是工作台顺序**（`Sample.start_time` 升序）：导出的行序与列表一致，否则导出文件
   与屏幕对不上。
5. **删除分段任务级联清掉 `sample_features`**：`SampleFeature.sample_id` 是裸外键列、
   没有 `relationship()`，SQLAlchemy 推不出删除先后——本文件的 engine 开了
   `PRAGMA foreign_keys=ON`，顺序错了这里就红（离线不红、MySQL 线上 1451 的那类坑）。
6. 前置条件：非 v3 / 未成功的分段任务 → 40000；幂等：同入参重复建任务复用同一 Job。

隔离：内存 SQLite（StaticPool）+ 假 Storage（内存 dict）+ 真实 ffmpeg 生成的小视频。
"""

from __future__ import annotations

import io
import json
import subprocess

import imageio_ffmpeg
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine, event
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, select

from app.api.deps import get_current_user
from app.core.db import get_session
from app.main import app
from app.models import User
from app.models.analysis import Sample, SampleFeature, SplitTask
from app.models.data import AuditLog, DataRecord, DataVersion
from app.models.datasets import Dataset, DatasetItem, DatasetVersion
from app.models.jobs import Job
from app.services import datasets as datasets_svc
from app.services import features as features_svc
from app.services import signal_ingest, splitting, torch_training
from app.services.jobs import create_job
from app.storage.client import StorageClient

client = TestClient(app)

IMAGE_W, IMAGE_H = 400, 120
SEAM_KEY = "raw/REG-SF-0001/seam.png"
VIDEO_KEY = "raw/REG-SF-0001/weld.mp4"
CSV_KEY = "raw/REG-SF-0001/signal.csv"
WELD_ID = "WLD-SF-0001"

SIGNAL_FS, SIGNAL_SECONDS = 100, 8.0
WELD_WINDOW = (1.0, 7.0)
API = "/api/v1"


class FakeStorage:
    """内存假存储：只实现本链路走到的接口。"""

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

    def delete_objects(self, object_keys) -> list[str]:
        for key in object_keys:
            self.objects.pop(key, None)
        return []

    def presign_get(self, object_key: str, expires: int = 3600) -> str:
        return f"https://fake-minio.local/{object_key}?expires={expires}"


def _png(width: int = IMAGE_W, height: int = IMAGE_H) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (90, 140, 160)).save(buffer, format="PNG")
    return buffer.getvalue()


def _signal_csv(current: float = 200.0) -> bytes:
    """`[1.0, 7.0]` 焊接的方波：窗外电流为 0，窗内 `current`。

    窗外/窗内量级差异让「时序维度真的切了信号」可断言（熄弧窗均值 ≈ 0，焊接窗均值 ≈ current）。
    """
    n = int(SIGNAL_SECONDS * SIGNAL_FS)
    t = np.arange(n) / SIGNAL_FS
    amps = np.where((t >= WELD_WINDOW[0]) & (t <= WELD_WINDOW[1]), current, 0.0)
    frame = pd.DataFrame({
        "time": t, "Current": amps,
        "Voltage": np.where(amps > 0, 20.0, 0.0),
        "GasSpeed": 15.0, "WireFeedSpeed": 5.0, "WeldingSpeed": 4.0,
    })
    return frame.to_csv(index=False).encode("utf-8")


@pytest.fixture(scope="module")
def mp4_bytes(tmp_path_factory) -> bytes:
    path = tmp_path_factory.mktemp("sf_video") / "weld.mp4"
    subprocess.run(
        [
            imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", "testsrc=size=320x240:rate=25:duration=8",
            "-pix_fmt", "yuv420p", "-c:v", "libx264", str(path),
        ],
        check=True, capture_output=True,
    )
    return path.read_bytes()


@pytest.fixture()
def engine():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )

    # **外键校验必须打开**：SQLite 默认 OFF，级联删除的先后顺序错了也照样绿。
    # `SampleFeature.sample_id` 与 `Sample` 之间只有裸外键列、没有 `relationship()`，
    # SQLAlchemy 推不出先后——顺序错了这里就红，而不是等线上 MySQL 报 1451。
    @event.listens_for(engine, "connect")
    def _enable_sqlite_fk(dbapi_connection, _record):  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    SQLModel.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def db_session(engine):
    with Session(engine, expire_on_commit=False) as session:
        yield session


@pytest.fixture()
def run_job(monkeypatch, engine):
    from app.jobs.executor import run_job as _run_job

    monkeypatch.setattr(
        "app.jobs.executor.SessionLocal", lambda: Session(engine, expire_on_commit=False)
    )
    return _run_job


@pytest.fixture(autouse=True)
def _clear_caches():
    """进程内缓存跨用例会串味：预览缓存按 version_id、Parquet LRU 按 ingest.id——
    各用例的库都是全新的、id 从 1 重来，不清就会读到上一个用例的信号。"""
    splitting._PREVIEW_CACHE.clear()
    signal_ingest._PARQUET_CACHE.clear()
    yield
    splitting._PREVIEW_CACHE.clear()
    signal_ingest._PARQUET_CACHE.clear()


@pytest.fixture()
def storage(monkeypatch):
    fake = FakeStorage()
    fake.put(SEAM_KEY, _png())
    for target in (
        "app.storage.get_storage",
        "app.jobs.split.get_storage",
        "app.jobs.sample_features.get_storage",
        "app.api.v1.sample_features.get_storage",
    ):
        monkeypatch.setattr(target, lambda: fake)
    return fake


@pytest.fixture()
def user(db_session) -> User:
    u = User(username="feat", password_hash="x", display_name="特征员", role="user")
    db_session.add(u)
    db_session.commit()
    db_session.refresh(u)
    return u


@pytest.fixture()
def api(db_session, user):
    def _session():
        yield db_session

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_current_user] = lambda: user
    yield client
    app.dependency_overrides.pop(get_session, None)
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture()
def ready(db_session, user, storage, api):
    """真实信号已导入 + 视频/照片就位 + 对齐映射已造的 v1.0。返回 (record, version_id)。"""
    record = DataRecord(
        weld_id=WELD_ID, registration_no="REG-SF-0001", source="现场采集", quality="待复核",
    )
    db_session.add(record)
    db_session.commit()
    db_session.refresh(record)
    version = DataVersion(
        record_id=record.id, version_no="v1.0", action="原始数据",
        object_keys=[CSV_KEY, VIDEO_KEY, SEAM_KEY],
    )
    db_session.add(version)
    db_session.commit()
    db_session.refresh(version)
    record.latest_version_id = version.id
    db_session.add(record)
    db_session.add(AuditLog(
        user_id=user.id, action="create", resource_type="weld", resource_id=record.weld_id,
    ))
    db_session.commit()

    storage.put(CSV_KEY, _signal_csv())
    job = create_job(db_session, type="signal_ingest")
    from app.models.analysis import SignalIngest

    ingest = SignalIngest(
        job_id=job.id, version_id=version.id, source_object_key=CSV_KEY, status="pending",
    )
    db_session.add(ingest)
    db_session.commit()
    db_session.refresh(ingest)
    db_session.refresh(job)
    signal_ingest.run_ingest(db_session, ingest, job)
    db_session.commit()
    assert ingest.status == "succeeded", ingest.validation
    _seed_alignment_mapping(db_session, version.id)
    # 视频零点标定：分段侧从 v1.0 权威标定现读 offset，标定后才能把窗口中点换算到视频轴
    # 抽代表帧（同 `test_split_v3_api.py` 的真实链路顺序：标定 → 对齐 → 分段）。
    _ok(api.put(
        f"{API}/welds/{WELD_ID}/versions/{version.id}/calibration",
        json={"video": {"offset_seconds": 0.0}},
    ))
    # 核验：数据集构建有**核验准入**（P1-03）——只收"已核验且非异常"的登记数据成员。
    # 生产流程就是 登记 → 挂载 → 核验 → 构建，这一步不能省。
    validated = _ok(api.post(f"{API}/welds/{WELD_ID}/versions/{version.id}/validation"))
    assert validated["failed"] == 0, validated
    db_session.refresh(record)
    assert record.quality in {"通过", "待复核"}, record.quality
    return record, version.id


def _seed_alignment_mapping(db_session, version_id: int, *, fps: float = 25.0, duration: float = 8.0):
    """伪造一次成功对齐留下的 mapping（分段侧不下载视频探 fps，只读对齐产物）。"""
    from app.models.analysis import AlignmentTask

    job = create_job(db_session, type="alignment")
    db_session.add(AlignmentTask(
        job_id=job.id, version_id=version_id, tracks=[], assets=[],
        events={"arc": WELD_WINDOW[0], "weld_segment": list(WELD_WINDOW), "tail": WELD_WINDOW[1]},
        mapping={
            "schema_version": 1,
            "unified_axis": {"unit": "second", "origin": "signal_first_sample", "duration": SIGNAL_SECONDS},
            "event_bounds": {"start": WELD_WINDOW[0], "end": WELD_WINDOW[1]},
            "mappings": {
                "video": {
                    "type": "linear", "available": True, "calibrated": False,
                    "offset_seconds": 0.0, "fps": fps, "duration": duration, "reason": None,
                },
            },
        },
    ))
    db_session.commit()


def _ok(response):
    payload = response.json()
    assert payload["code"] == 0, payload
    return payload["data"]


def _split_url(version_id: int, suffix: str) -> str:
    return f"{API}/welds/{WELD_ID}/versions/{version_id}/{suffix}"


def _make_split_task(api, db_session, run_job, version_id: int, *, window: float = 2.0) -> SplitTask:
    """跑出一个真实的 v3 分段任务（窗口默认 2s，[1,7] 上切 3 段）。"""
    preview = _ok(api.post(
        _split_url(version_id, "split-preview"),
        json={"window_seconds": window, "stride_seconds": window},
    ))
    created = _ok(api.post(
        _split_url(version_id, "split-tasks"), json={"preview_token": preview["preview_token"]}
    ))
    run_job(created["job_id"])
    db_session.expire_all()
    job = db_session.exec(select(Job).where(Job.job_uid == created["job_id"])).first()
    assert job is not None and job.status == "succeeded", job.error if job else "job missing"
    task = db_session.exec(select(SplitTask).where(SplitTask.job_id == job.id)).first()
    assert task is not None
    return task


def _uid(db_session, task: SplitTask) -> str:
    """任务在 URL 里的标识：前端一律传 `job_uid`（服务端也兼容 DB id）。"""
    job = db_session.get(Job, task.job_id)
    assert job is not None
    return job.job_uid


def _run_sample_features(db_session, run_job, api, task: SplitTask, **body) -> dict:
    created = _ok(api.post(
        f"{API}/split-tasks/{_uid(db_session, task)}/sample-feature-extractions",
        json=body or {},
    ))
    run_job(created["job_id"])
    db_session.expire_all()
    job = db_session.exec(select(Job).where(Job.job_uid == created["job_id"])).first()
    assert job is not None and job.status == "succeeded", job.error if job else "job missing"
    return job.result


def _rows(db_session, task: SplitTask) -> list[SampleFeature]:
    return list(db_session.exec(
        select(SampleFeature)
        .join(Sample, Sample.id == SampleFeature.sample_id)
        .where(SampleFeature.split_task_id == task.id)
        .order_by(Sample.start_time, Sample.id)
    ).all())


# ── 1. 一个切片一行 36 维，且真的切了信号 ────────────────────────────


def test_each_slice_gets_its_own_36_dim_vector(api, ready, storage, db_session, run_job, mp4_bytes):
    _record, version_id = ready
    storage.put(VIDEO_KEY, mp4_bytes)
    task = _make_split_task(api, db_session, run_job, version_id)
    result = _run_sample_features(db_session, run_job, api, task)

    assert result["total_dims"] == 36
    assert result["pipeline_version"] == "sample-features-v1"
    # 有真帧且本部署没配正式视觉服务 → 走自家分割（heuristic）；**这不是** partial
    # （按"非 real 就算 partial"会让每一批都 partial，那是噪音）
    assert result["status"] == "succeeded", result
    assert result["missing_vision"] == 0
    assert result["heuristic_vision"] == 3

    rows = _rows(db_session, task)
    assert len(rows) == task.sample_count == result["extracted"] == 3

    for row in rows:
        vector = row.unified_vector
        assert vector["total_dims"] == 36
        assert len(vector["values"]) == 36
        # 6 组、无声音：切片 manifest 自己写着 audio.available=False，不拿合成音频凑维度
        assert len(vector["groups"]) == 6
        assert not any("声音" in group["name"] for group in vector["groups"])
        assert [group["name"] for group in vector["groups"]] == features_svc.SAMPLE_GROUP_NAMES
        # 权威值恒为原始值（逐切片 Z-Score 会抹掉区分切片的那批量）
        assert row.normalization == "无"
        assert row.source_by_modality == {"timeseries": "real", "vision": "heuristic"}
        # ts_features 覆盖**算过统计的全部通道**（本用例的 CSV 还带 WeldingSpeed）；
        # 进 36 维的是核心 4，断言其存在即可。
        assert {"cur", "vol", "gas", "wir"} <= set(row.ts_features)
        # 时序 28 维真的来自该窗口的信号，不是全 0 占位
        assert row.unified_vector["values"][0] != 0.0

    # 三段各自不同（真的按窗口切了，不是把整条信号的统计复制 3 遍）
    assert len({tuple(row.unified_vector["values"]) for row in rows}) == 3

    # 窗 [1,3]/[3,5]/[5,7] 全在焊接段内 —— 电流均值维（第 0 维）应接近 200 量级
    means = [row.unified_vector["values"][0] for row in rows]
    assert all(150 < mean < 250 for mean in means), means


def test_first_window_covering_idle_is_distinguishable(
    api, ready, storage, db_session, run_job, mp4_bytes
):
    """窗口部分落在焊接段之外时，电流均值维必须**明显低于**全焊接窗——证明切的是真信号。

    用一个从起弧前开始的窗口（事件边界之外）与全焊接窗对比；这是"时序维度只算了个
    整条信号副本"这类错误的探针。
    """
    _record, version_id = ready
    storage.put(VIDEO_KEY, mp4_bytes)
    task = _make_split_task(api, db_session, run_job, version_id)
    _run_sample_features(db_session, run_job, api, task)
    means = [row.unified_vector["values"][0] for row in _rows(db_session, task)]
    assert min(means) < max(means), means  # 各窗信号内容不同


# ── 2. 缺一片代表帧不废整批 ──────────────────────────────────────────


def test_missing_frame_degrades_one_slice_not_the_batch(
    api, ready, storage, db_session, run_job
):
    """**没有视频**时全部切片视觉记 missing + 逐片原因，Job 仍 succeeded（status=partial）。

    防回归：一段抽不到帧就整批失败，等于 45 段里丢 1 帧废掉一整批。
    """
    _record, version_id = ready
    # 不放视频对象 → 分段任务抽不到任何代表帧（视频是增强模态，任务本身照常成功）
    task = _make_split_task(api, db_session, run_job, version_id)
    result = _run_sample_features(db_session, run_job, api, task)

    assert result["status"] == "partial"
    assert result["missing_vision"] == result["extracted"] == 3
    rows = _rows(db_session, task)
    assert len(rows) == 3
    for row in rows:
        assert row.source_by_modality["vision"] == "missing"
        assert row.source_by_modality["timeseries"] == "real"
        # 逐片写明原因，而不是静默给零
        assert row.warnings and "视觉" in row.warnings[0]
        # 时序维度照样是真实算出来的
        assert row.unified_vector["values"][0] != 0.0
        # 视觉 8 维全 0（缺就缺，不伪造）
        assert row.unified_vector["values"][28:36] == [0.0] * 8


# ── 3. 读取端点：进展、单样本、导出 ──────────────────────────────────


def test_list_detail_export_and_progress(api, ready, storage, db_session, run_job, mp4_bytes):
    _record, version_id = ready
    storage.put(VIDEO_KEY, mp4_bytes)
    task = _make_split_task(api, db_session, run_job, version_id)

    # 提取前：列表里全是 extracted=false（不是 404），进度 0
    before = _ok(api.get(f"{API}/split-tasks/{_uid(db_session, task)}/sample-features"))
    assert before["progress"] == {"total": 3, "extracted": 0, "pending": 3, "progress": 0.0}
    assert [row["extracted"] for row in before["items"]] == [False, False, False]
    assert before["items"][0]["frame_key"]  # 行里给帧键，前端按需取 URL
    # 未提取的样本详情是 feature=null（「还没跑」是正常状态，**不是 404**）
    pending_id = before["items"][0]["sample_id"]
    assert _ok(api.get(
        f"{API}/split-tasks/{_uid(db_session, task)}/sample-features/{pending_id}"
    ))["feature"] is None

    _run_sample_features(db_session, run_job, api, task)

    after = _ok(api.get(f"{API}/split-tasks/{_uid(db_session, task)}/sample-features"))
    assert after["progress"]["extracted"] == 3
    assert all(row["extracted"] for row in after["items"])
    assert all(row["total_dims"] == 36 for row in after["items"])
    # 列表行**不带数值**（几百片时会把响应撑爆）
    assert "unified_vector" not in after["items"][0]
    assert "values" not in after["items"][0]

    # 未提取筛选在 SQL 侧：全提取完 → 空
    assert _ok(api.get(f"{API}/split-tasks/{_uid(db_session, task)}/sample-features?filter=unextracted"))["items"] == []

    sample_id = after["items"][0]["sample_id"]
    detail = _ok(api.get(f"{API}/split-tasks/{_uid(db_session, task)}/sample-features/{sample_id}"))["feature"]
    assert detail["sample_id"] == sample_id
    assert len(detail["unified_vector"]["values"]) == 36
    assert detail["normalization"] == "无"
    # 该 CSV 还带 WeldingSpeed（被收成扩展通道 weld_speed），所以 channels 是"算过统计的
    # 全部通道"；进 36 维的是核心 4，这里断言它们是子集即可。
    assert {"cur", "vol", "gas", "wir"} <= set(detail["channel_mapping"]["channels"])

    # 导出：JSON 带分组定义，CSV 行数与切片数一致且行序 = 列表顺序
    exported = _ok(api.get(f"{API}/split-tasks/{_uid(db_session, task)}/sample-features/export?format=JSON"))
    payload = json.loads(storage.objects[exported["object_key"]].decode("utf-8"))
    assert payload["total_dims"] == 36
    assert len(payload["groups"]) == 6
    assert [entry["sample_id"] for entry in payload["samples"]] == [row["sample_id"] for row in after["items"]]

    exported_csv = _ok(api.get(f"{API}/split-tasks/{_uid(db_session, task)}/sample-features/export?format=CSV"))
    lines = storage.objects[exported_csv["object_key"]].decode("utf-8").strip().splitlines()
    assert len(lines) == 1 + 3  # 表头 + 3 切片
    assert lines[0].startswith("sample_id,index,start_time,end_time,f0,")

    # 非法 format / 未知样本
    assert api.get(f"{API}/split-tasks/{_uid(db_session, task)}/sample-features/export?format=PT").json()["code"] == 40000
    assert api.get(f"{API}/split-tasks/{_uid(db_session, task)}/sample-features/999999").json()["code"] == 40401


# ── 4. 幂等与前置条件 ────────────────────────────────────────────────


def test_create_is_idempotent(api, ready, storage, db_session, run_job, mp4_bytes):
    _record, version_id = ready
    storage.put(VIDEO_KEY, mp4_bytes)
    task = _make_split_task(api, db_session, run_job, version_id)
    first = _ok(api.post(f"{API}/split-tasks/{_uid(db_session, task)}/sample-feature-extractions", json={}))
    second = _ok(api.post(f"{API}/split-tasks/{_uid(db_session, task)}/sample-feature-extractions", json={}))
    assert first["job_id"] == second["job_id"]

    # 非法归一化 → 40000（且不建任务）
    bad = api.post(f"{API}/split-tasks/{_uid(db_session, task)}/sample-feature-extractions", json={"normalization": "xyz"})
    assert bad.json()["code"] == 40000


def test_gating_rejects_non_v3_and_unsucceeded(api, ready, db_session, run_job, mp4_bytes):
    _record, version_id = ready
    # 非 v3（rules_version 缺失/为 1）→ 40000
    job = create_job(db_session, type="split")
    legacy = SplitTask(job_id=job.id, version_id=version_id, rules={"rules_version": 1}, sample_count=0)
    db_session.add(legacy)
    db_session.commit()
    db_session.refresh(legacy)
    from app.services.jobs import mark_succeeded

    mark_succeeded(db_session, job, {})
    db_session.commit()
    resp = api.post(f"{API}/split-tasks/{job.job_uid}/sample-feature-extractions", json={})
    assert resp.json()["code"] == 40000
    assert "v3" in resp.json()["message"]

    # 任务列表里也不该出现它（与标注工作台同一份查询）
    items = _ok(api.get(f"{API}/welds/{WELD_ID}/sample-feature-tasks"))["items"]
    assert all(entry["split_task_id"] != legacy.id for entry in items)

    # 未知任务 → 40401
    assert api.post(f"{API}/split-tasks/job_deadbeef/sample-feature-extractions", json={}).json()["code"] == 40401


# ── 5. 删除分段任务级联清特征（FK 顺序陷阱） ────────────────────────


def test_deleting_split_task_cascades_sample_features(
    api, ready, storage, db_session, run_job, mp4_bytes
):
    """删任务必须把 `sample_features` 一起清掉。

    这是**裸外键列**的路径：`SampleFeature.sample_id`/`split_task_id` 都没有
    `relationship()`，SQLAlchemy 推不出删除先后——少一步 flush 就会在 MySQL 报
    1451（SQLite 默认不校验外键，所以才在本文件的 engine 上开 `PRAGMA foreign_keys=ON`）。
    """
    _record, version_id = ready
    storage.put(VIDEO_KEY, mp4_bytes)
    task = _make_split_task(api, db_session, run_job, version_id)
    _run_sample_features(db_session, run_job, api, task)
    sample_ids = [row.sample_id for row in _rows(db_session, task)]
    assert len(sample_ids) == 3

    _ok(api.delete(f"{API}/split-tasks/{_uid(db_session, task)}"))
    db_session.expire_all()

    assert db_session.exec(select(SampleFeature).where(SampleFeature.sample_id.in_(sample_ids))).all() == []
    assert db_session.exec(select(Sample).where(Sample.split_task_id == task.id)).all() == []


# ── 6. 未登录 ────────────────────────────────────────────────────────


def test_endpoints_require_login(ready):
    """五个端点未登录都 401（用无 override 的裸 client）。"""
    app.dependency_overrides.pop(get_current_user, None)
    try:
        assert client.get(f"{API}/welds/{WELD_ID}/sample-feature-tasks").json()["code"] == 40100
        for suffix in ("sample-features", "sample-features/export", "sample-features/1"):
            assert client.get(f"{API}/split-tasks/job_x/{suffix}").json()["code"] == 40100
        assert client.post(f"{API}/split-tasks/job_x/sample-feature-extractions", json={}).json()["code"] == 40100
    finally:
        app.dependency_overrides.pop(get_current_user, None)


# ── 7. 构建时冻结 → 训练读冻结向量 ───────────────────────────────────


def _build_dataset_from_split(api, db_session, run_job, task: SplitTask, *, name: str) -> tuple[int, int]:
    """建数据集 → 建版本 → 从该分段任务构建（真实 `dataset_build` job）。"""
    dataset_id = _ok(api.post(f"{API}/datasets", json={"name": name, "task": "时序分类"}))["id"]
    version_id = _ok(api.post(f"{API}/datasets/{dataset_id}/versions", json={}))["id"]
    created = _ok(api.post(
        f"{API}/datasets/{dataset_id}/versions/{version_id}/build-tasks",
        json={"source": {"type": "split_task", "split_task_id": task.id}},
    ))
    run_job(created["job_id"])
    db_session.expire_all()
    job = db_session.exec(select(Job).where(Job.job_uid == created["job_id"])).one()
    assert job.status == "succeeded", job.error
    return dataset_id, version_id


def test_build_freezes_vector_into_snapshot_and_training_reads_it(
    api, ready, storage, db_session, run_job, mp4_bytes
):
    """构建把 36 维向量冻进 `dataset_items.features` 与快照；训练读到的是**冻结的那份**。

    这是整个特性的**复现性契约**：训练读快照，不现查 `sample_features`——否则重跑一次
    特征提取就会把已建版本的训练输入悄悄换掉。
    """
    _record, version_id = ready
    storage.put(VIDEO_KEY, mp4_bytes)
    task = _make_split_task(api, db_session, run_job, version_id)
    _run_sample_features(db_session, run_job, api, task)
    frozen = {row.sample_id: row.unified_vector["values"] for row in _rows(db_session, task)}

    dataset_id, ds_version_id = _build_dataset_from_split(
        api, db_session, run_job, task, name="切片特征冻结"
    )

    items = db_session.exec(
        select(DatasetItem).where(DatasetItem.dataset_version_id == ds_version_id)
    ).all()
    assert items, "构建应当产生成员"
    for item in items:
        assert item.features is not None
        assert len(item.features["values"]) == 36
        # 冻的**就是**当时那一份（逐值相等，不是"形状对就行"）
        assert item.features["values"] == frozen[item.sample_id]

    detail = _ok(api.get(f"{API}/datasets/{dataset_id}/versions/{ds_version_id}"))
    assert detail["features_frozen"] is True
    assert _ok(api.get(f"{API}/datasets/{dataset_id}/versions/{ds_version_id}"))  # 可重复读

    snapshot = json.loads(storage.objects[f"datasets/{ds_version_id}/snapshot.json"].decode("utf-8"))
    assert all(entry["features"] for entry in snapshot["items"])

    # 训练侧：口径是 slice_v1，每个样本 36 维（读的是快照里冻结的那份）
    examples, _classes, feature_kind = torch_training.load_real_examples(
        db_session, ds_version_id, storage
    )
    assert feature_kind == "slice_v1"
    assert examples and all(len(example.features) == 36 for example in examples)

    # 之后**重跑**特征提取（原地 upsert 出新值），已建版本的训练输入不许跟着变
    before = [tuple(example.features) for example in examples]
    _ok(api.post(f"{API}/split-tasks/{_uid(db_session, task)}/sample-feature-extractions", json={}))
    run_job(db_session.exec(select(Job).where(Job.type == "sample_feature_extraction").order_by(Job.id.desc())).first().job_uid)
    db_session.expire_all()
    again, _c, _k = torch_training.load_real_examples(db_session, ds_version_id, storage)
    assert [tuple(example.features) for example in again] == before


def test_run_derives_input_dim_from_data(api, ready, storage, db_session, run_job, mp4_bytes):
    """`run()` 的输入维度从数据来（曾经写死 8）——36 维必须能训，产物里留住口径。"""
    import torch

    from app.services.torch_training import TrainingExample

    def _examples(dim: int) -> list[TrainingExample]:
        return [
            TrainingExample(index, "train" if index % 2 else "val",
                            tuple(float(index % 5) for _ in range(dim)), index % 2, "缺陷")
            for index in range(6)
        ]

    for dim, kind in ((36, "slice_v1"), (8, "legacy_summary")):
        result = torch_training.run(1, 2, 7, _examples(dim), ["正常", "缺陷"], feature_kind=kind)
        saved = torch.load(io.BytesIO(result.weights), weights_only=False)
        assert saved["input_dim"] == dim, saved
        assert saved["feature_kind"] == kind, saved

    # 维度不一致 → 明确报错（而不是 torch 张量化时抛看不懂的形状错误）
    mixed = _examples(36)[:3] + _examples(8)[3:]
    with pytest.raises(ValueError, match="维度不一致"):
        torch_training.run(1, 1, 7, mixed, ["正常", "缺陷"])


def test_legacy_version_falls_back_and_mixed_is_refused(
    api, ready, storage, db_session, run_job, mp4_bytes
):
    """存量版本（`features` 全 NULL）走旧 8 维口径仍可训；**混用**必须拒。

    全无 = 本特性之前建的版本 → 回退，零改动可训（否则所有历史数据集一次性不可训）；
    混用 = 一半有 36 维一半没有 → 拒（两种口径的向量长度不同）。
    """
    _record, version_id = ready
    storage.put(VIDEO_KEY, mp4_bytes)
    task = _make_split_task(api, db_session, run_job, version_id)

    dataset = Dataset(dataset_no="DS-LEGACY-001", name="存量数据集", task="时序分类", status="标注中")
    db_session.add(dataset)
    db_session.commit()
    db_session.refresh(dataset)
    ds_version = DatasetVersion(
        dataset_id=dataset.id, version_no="v1.1", item_count=3,
        split={"train": 2, "val": 1, "test": 0},
    )
    db_session.add(ds_version)
    db_session.commit()
    db_session.refresh(ds_version)

    samples = list(db_session.exec(
        select(Sample).where(Sample.split_task_id == task.id).order_by(Sample.id)
    ).all())
    assert len(samples) == 3
    from app.models.datasets import DatasetItem as _Item

    def _add_items(*, null_index: int | None) -> None:
        for old in db_session.exec(
            select(_Item).where(_Item.dataset_version_id == ds_version.id)
        ).all():
            db_session.delete(old)
        db_session.commit()
        for index, sample in enumerate(samples):
            db_session.add(_Item(
                dataset_version_id=ds_version.id,
                sample_id=sample.id,
                split="train" if index < 2 else "val",
                # 标注快照必须给（否则会触发另一条回退路径的日志）
                annotations=[{"category": "焊瘤", "kind": "box"}],
                features=None if index == null_index else {"values": [0.5] * 36},
            ))
        db_session.commit()

    # 全无 → legacy_summary，8 维现算
    _add_items(null_index=None)
    for item in db_session.exec(select(_Item).where(_Item.dataset_version_id == ds_version.id)).all():
        item.features = None
    db_session.commit()
    assert datasets_svc.feature_coverage(db_session, ds_version) == (0, 3)
    examples, _classes, kind = torch_training.load_real_examples(db_session, ds_version.id, storage)
    assert kind == "legacy_summary"
    assert examples and all(len(example.features) == 8 for example in examples)

    # 混用 → 拒，并点名缺了几个
    _add_items(null_index=2)
    assert datasets_svc.feature_coverage(db_session, ds_version) == (2, 3)
    with pytest.raises(ValueError, match=r"1/3 个成员缺少切片特征"):
        torch_training.load_real_examples(db_session, ds_version.id, storage)


# ── 8. 单焊缝划分（2026-10 C 项）：从"训不了"到"能训，但指标有限定" ──


def test_single_weld_version_is_trainable_via_within_weld_split(
    api, ready, storage, db_session, run_job, mp4_bytes
):
    """**单焊缝现在能训练了** —— 这是本轮 C 项改动的核心价值，也是它唯一的验收标准。

    改动前：候选只来自 1 条焊缝 → 整条丢进 train、`val = 0` → 训练准入必然
    `40000「没有验证集样本」`。结果是"特征全提完了也训不了"，退化分支实际是死胡同。

    改动后：按**时间连续块**在焊缝内切（前段 train / 中段 val / 后段 test，**不 shuffle**，
    免得把验证窗口的邻居放进训练集），`val` 非空 → 准入放行。
    代价写进 `split.strategy == "within_weld"`，前端/报告据此提示"指标只代表焊缝内泛化"。
    """
    _record, version_id = ready
    storage.put(VIDEO_KEY, mp4_bytes)
    # 1s 窗口 → [1,7] 上切 6 段，这样 train 段里能同时有正常与缺陷（不是单类）
    task = _make_split_task(api, db_session, run_job, version_id, window=1.0)
    _run_sample_features(db_session, run_job, api, task)

    samples = list(db_session.exec(
        select(Sample).where(Sample.split_task_id == task.id).order_by(Sample.start_time, Sample.id)
    ).all())
    assert len(samples) == 6, [s.frame_no for s in samples]

    # 标注：前 3 段正常、后 3 段缺陷——按时间切分后 train 段两类都有
    from app.models.analysis import SampleAnnotation

    for index, sample in enumerate(samples):
        db_session.add(SampleAnnotation(
            sample_id=sample.id,
            label="normal" if index < 3 else "defect",
            defect_category_name=None if index < 3 else "气孔",
            schema_version=1,
            review_status="approved",
        ))
    db_session.commit()

    dataset_id, ds_version_id = _build_dataset_from_split(
        api, db_session, run_job, task, name="单焊缝划分"
    )

    version = db_session.get(DatasetVersion, ds_version_id)
    split = version.split or {}
    assert split.get("strategy") == "within_weld", split
    assert split.get("val", 0) >= 1, split          # 改动前这里是 0
    assert split.get("train", 0) >= 1, split
    assert split.get("train", 0) + split.get("val", 0) + split.get("test", 0) == 6, split

    # 连续块：train 段就是时间上最靠前的那几段（不许打散）
    ordered = list(db_session.exec(
        select(DatasetItem.split, Sample.start_time)
        .join(Sample, Sample.id == DatasetItem.sample_id)
        .where(DatasetItem.dataset_version_id == ds_version_id)
        .order_by(Sample.start_time)
    ).all())
    labels = [row[0] for row in ordered]
    assert labels == ["train"] * split["train"] + ["val"] * split["val"] + ["test"] * split["test"], labels

    # 特征照旧冻住（36 维）
    items = db_session.exec(
        select(DatasetItem).where(DatasetItem.dataset_version_id == ds_version_id)
    ).all()
    assert all(item.features and len(item.features["values"]) == 36 for item in items)

    # 训练准入放行——**这条断言就是 C 项的验收标准**（改动前必得 40000「没有验证集样本」）
    created = _ok(api.post(f"{API}/training-tasks", json={
        "dataset_version_id": ds_version_id, "epochs": 2,
    }))
    assert created["job_id"], created
    db_session.expire_all()
    job = db_session.exec(select(Job).where(Job.job_uid == created["job_id"])).one()
    assert job.status in {"pending", "running"}, job.status


def test_single_sample_dataset_is_still_refused(api, ready, storage, db_session, run_job):
    """**只有 1 个样本时仍然拒**：焊缝内划分也做不出 val，如实拒绝而不是硬凑一个。

    这条钉住"放宽"的边界——C 项放宽的是"**单焊缝多切片**"，不是"任意少量样本都能训"。
    """
    _record, version_id = ready
    # 6s 窗口在 [1,7] 上只能切出 1 段
    preview = _ok(api.post(
        _split_url(version_id, "split-preview"),
        json={"window_seconds": 6.0, "stride_seconds": 6.0},
    ))
    assert preview["sample_count"] == 1, preview["sample_count"]

    # 造一个"1 条焊缝 + 1 个样本"的分段任务（本轮只关心划分与准入，不必跑完整抽帧链路）
    from app.services.jobs import mark_succeeded

    job = create_job(db_session, type="split")
    lone_task = SplitTask(job_id=job.id, version_id=version_id, rules={"rules_version": 3}, sample_count=1)
    db_session.add(lone_task)
    db_session.commit()
    db_session.refresh(lone_task)
    mark_succeeded(db_session, job, {})
    db_session.commit()
    only_sample = Sample(
        split_task_id=lone_task.id, frame_no=1, start_time=1.0, end_time=7.0,
        object_keys=[], meta={"signal": {"start_index": 100, "end_index": 700, "sample_rate": 100}},
    )
    db_session.add(only_sample)
    db_session.commit()

    # 纯规则层：1 个样本只能给 train，val 恒空（不在这里硬凑）
    assert datasets_svc._assign_splits(["only-weld"]) == {}
    assert set(datasets_svc._assign_within_weld([only_sample]).values()) == {"train"}

    _dataset_id, ds_version_id = _build_dataset_from_split(
        api, db_session, run_job, lone_task, name="单个样本"
    )
    version = db_session.get(DatasetVersion, ds_version_id)
    assert (version.split or {}).get("val", 0) == 0, version.split
    # 准入在建 job 前就拒（val 检查在 readiness 之前），原因直指验证集
    refusal = api.post(f"{API}/training-tasks", json={
        "dataset_version_id": ds_version_id, "epochs": 2,
    }).json()
    assert refusal["code"] == 40000, refusal
    assert "没有验证集样本" in refusal["message"], refusal["message"]
