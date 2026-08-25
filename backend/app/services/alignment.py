"""多模态对齐服务（Task 13）：模拟对齐执行 + 自动生成「时间对齐」版本。

实施边界（`docs/开发规范.md` §3.1）：对齐 = 真实异步编排 + 模拟结果——
Job 状态/进度/结果回填与 MinIO 产物对象键为真，计算内核为演示（无真实特征对齐）。
handler 在 `app/jobs/alignment.py`，本模块是跨域可复用的领域逻辑。

产物结构照 `docs/API接口清单.md` §3.4：
- `events` = `{arc, weld_segment[], tail}`（起弧/有效段/收弧时间点，与 signals 生成器一致）；
- `tracks` = 各模态轨道列表（按任务 modalities 映射 channel，缺失时兜底 video）；
- `assets` = `processed/{weld_id}/align/...` 对象键列表（对齐后视频/轨道/JSON），
  回填 `alignment_tasks.assets`，前端经 `GET /files/{key}/url` 播放。

坑：进度循环里逐次 `session.commit()`（轮询可见），最终事务（版本 + task 域字段 +
job.result）一次 commit；`mark_succeeded` 由本服务调用（沿用 `services/jobs.py` 只改内存、
commit 归调用方 的约定，本服务里的 commit 是执行器专用 session 的场景）。
"""

from __future__ import annotations

import io
import time

from sqlmodel import Session

from app.models.analysis import AlignmentTask
from app.models.data import DataRecord, DataVersion
from app.models.jobs import Job
from app.services.jobs import mark_succeeded
from app.services.welds import create_version, version_payload

#: 对齐事件（起弧/有效段/收弧），与 `services/signals.py` 生成器的 events 一致。
ALIGN_EVENTS: dict = {"arc": 0.42, "weld_segment": [0.78, 4.28], "tail": 4.86}

#: 进度逐步递增点（0→100）。步间 commit + 小睡，让轮询/前端能看到 progress 变化。
_PROGRESS_STEPS: tuple[int, ...] = (20, 40, 60, 80, 100)
_PROGRESS_SLEEP: float = 0.05

#: 模态 → 轨道（channel 名称对齐 signals 生成器 / App.tsx）。
_MODALITY_TRACKS: dict[str, list[dict]] = {
    "video": [{"channel": "video"}],
    "timeseries": [{"channel": "current"}, {"channel": "voltage"}],
    "audio": [{"channel": "audio"}],
    "infrared": [{"channel": "infrared"}],
}

#: 模态 → 对齐产物文件名（`processed/{weld_id}/align/{name}`）。
_MODALITY_ASSETS: dict[str, list[str]] = {
    "video": ["video.mp4"],
    "timeseries": ["current.csv", "voltage.csv"],
    "audio": ["audio.wav"],
    "infrared": ["infrared.avi"],
}


def simulate_alignment(session: Session, task: AlignmentTask, job: Job) -> dict:
    """模拟执行一次对齐任务，返回写入 `job.result` 的 dict。

    步骤：
    1. 进度逐步 0→100（逐次 commit + 小睡，轮询可见）；
    2. 由任务 modalities（缺省取所属焊缝登记 modalities）推导 tracks / assets；
    3. 同事务：新建「时间对齐」`DataVersion`（v1.<n+1>，operator=算法任务）并更新
       `data_records.latest_version_id`（`services.welds.create_version`）；
    4. 回填 `alignment_tasks.events/tracks/assets`；
    5. `mark_succeeded(job, result)`（result = events/tracks/assets/version）。
    commit 由调用方（executor）在返回后统一提交。
    """
    version = session.get(DataVersion, task.version_id)
    if version is None:
        raise ValueError(f"对齐任务引用的版本不存在: version_id={task.version_id}")
    record = session.get(DataRecord, version.record_id)
    if record is None:
        raise ValueError(f"对齐任务引用的焊缝不存在: record_id={version.record_id}")

    for progress in _PROGRESS_STEPS:
        job.progress = progress
        session.commit()
        time.sleep(_PROGRESS_SLEEP)

    modalities = list(task.modalities or record.modalities or [])
    tracks = _build_tracks(modalities)
    assets = _build_assets(record.weld_id, modalities)
    _write_alignment_assets(assets)

    # 同事务：时间对齐版本 + 更新 latest_version_id + 回填 task 域字段。
    aligned_version = create_version(
        session,
        record,
        action="时间对齐",
        note="多模态时间轴对齐（算法任务自动生成）",
        object_keys=assets,
        operator="算法任务",
    )

    task.events = ALIGN_EVENTS
    task.tracks = tracks
    task.assets = assets
    session.add(task)

    result = {
        "events": ALIGN_EVENTS,
        "tracks": tracks,
        "assets": assets,
        "version": version_payload(aligned_version),
    }
    mark_succeeded(session, job, result)
    return result


def _build_tracks(modalities: list[str]) -> list[dict]:
    """按模态映射轨道（保序去重）；无已知模态时兜底 video。"""
    tracks: list[dict] = []
    for mod in modalities:
        for track in _MODALITY_TRACKS.get(mod, []):
            if track not in tracks:
                tracks.append(track)
    return tracks or [{"channel": "video"}]


def _build_assets(weld_id: str, modalities: list[str]) -> list[str]:
    """生成对齐产物对象键（`processed/{weld_id}/align/...`），末尾固定 `tracks.json`。"""
    base = f"processed/{weld_id}/align"
    assets: list[str] = []
    for mod in modalities:
        for name in _MODALITY_ASSETS.get(mod, []):
            key = f"{base}/{name}"
            if key not in assets:
                assets.append(key)
    assets.append(f"{base}/tracks.json")
    return assets


def _write_alignment_assets(assets: list[str]) -> None:
    """把对齐产物占位写入 MinIO；任一写失败则抛错，由执行器把任务标记 failed。"""
    from app.storage import get_storage

    storage = get_storage()
    for key in assets:
        data, content_type = _asset_payload(key)
        storage.upload_stream(key, io.BytesIO(data), len(data), content_type)


def _asset_payload(object_key: str) -> tuple[bytes, str]:
    if object_key.endswith(".json"):
        return b'{"tracks": []}', "application/json"
    if object_key.endswith(".csv"):
        return b"t,value\n0,0\n", "text/csv"
    if object_key.endswith(".mp4"):
        return b"FAKE-MP4", "video/mp4"
    if object_key.endswith(".avi"):
        return b"FAKE-AVI", "video/x-msvideo"
    if object_key.endswith(".wav"):
        return b"RIFFFAKEWAVE", "audio/wav"
    return b"placeholder", "application/octet-stream"
