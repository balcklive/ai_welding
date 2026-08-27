"""多模态对齐服务（Task 13，真实化内核）：真实事件/信号 + 真实产物 + 自动生成「时间对齐」版本。

产物结构照 `docs/API接口清单.md` §3.4（tracks 结构为对齐真实化后扩展版）：
- `events` = `{arc, weld_segment[], tail}`——来自真实信号（`signal_ingest.load_signal_bundle`，
  成功导入 CSV 时是 detect_events 的真实启发式结果；无导入回退确定性生成并如实标注
  `event_source="generated"`）；
- `tracks` = 各模态轨道列表，每条含 `availability`（available/generated/unavailable）与
  `reason`——**部分成功语义**：缺失模态不阻塞任务，至少一个模态对齐成功即 succeeded
  （timeseries 兜底恒成立）；
- `assets` = 真实产物对象键（`processed/{weld_id}/align/` 下时序 CSV×2 / 关键帧 JPG /
  tracks.json），回填 `alignment_tasks.assets`，前端经 `GET /files/{key}/url` 下载。
  不再产出 video.mp4/audio.wav 等占位字节——视频前端直接播放 raw 原始对象。

信号版本回退解析（坑）：SignalIngest 挂在 v1.0（原始数据）版本上（`attach_raw_files`
只挂 v1.0），而对齐任务可能在 latest 版本发起——`load_signal_bundle` 按 version_id 查，
直接传 task.version_id 会漏掉真实信号，故先 task.version_id、无 succeeded ingest 则回退 v1.0。

逐模态容错（坑）：seed 演示数据的 raw 对象键在 MinIO 中并不存在，且测试 FakeStorage 只有
upload/delete——视频读取必须 try/except（含 `get_object` 不存在的 AttributeError）降级为
unavailable + reason，否则 seed 路径与现有测试全崩。

坑：进度循环里逐次 `session.commit()`（轮询可见），最终事务（版本 + task 域字段 +
job.result）一次 commit；`mark_succeeded` 由本服务调用（沿用 `services/jobs.py` 只改内存、
commit 归调用方 的约定，本服务里的 commit 是执行器专用 session 的场景）。
"""

from __future__ import annotations

import csv
import io
import json
import math
import time

from loguru import logger
from sqlmodel import Session, select

from app.models.analysis import AlignmentTask, SignalIngest
from app.models.data import DataRecord, DataVersion
from app.models.jobs import Job
from app.services import media_probe, signal_ingest
from app.services.jobs import mark_succeeded
from app.services.welds import (
    _AUDIO_EXTS,
    _IMAGE_EXTS,
    _TS_EXTS,
    _VIDEO_EXTS,
    create_version,
    get_v10_version,
    version_payload,
)

#: 进度递增点（0→100）：20=清单+信号/事件 → 40=视频探测+关键帧 → 60=轨道/产物构建
#: → 80=上传 → 100=mark_succeeded。步间 commit + 小睡，让轮询/前端能看到 progress 变化。
_PROGRESS_STEPS: tuple[int, ...] = (20, 40, 60, 80)
_PROGRESS_SLEEP: float = 0.05

#: 模态 → 轨道（channel 名称对齐 signals 生成器 / App.tsx），保序去重。
_MODALITY_TRACKS: dict[str, list[str]] = {
    "video": ["video"],
    "timeseries": ["current", "voltage"],
    "audio": ["audio"],
    "infrared": ["infrared"],
}

#: 时序 CSV 的通道顺序（对齐 signal_ingest Parquet 列 schema `t,cur,vol,gas,wir`）。
_TS_CHANNEL_IDS: tuple[str, ...] = ("cur", "vol", "gas", "wir")

#: 时序 CSV 单文件最大行数（真实 1kHz 长记录可达百万行，超限按步长抽稀）。
_MAX_TS_ROWS = 100_000


def run_alignment(session: Session, task: AlignmentTask, job: Job) -> dict:
    """真实执行一次对齐任务，返回写入 `job.result` 的 dict。

    步骤（进度语义见 `_PROGRESS_STEPS`）：
    1. 解析输入清单（v1.0 原始文件 + 当前版本 object_keys 按扩展名分模态）；
    2. 信号版本回退解析并加载 `SignalBundle`，events 取真实启发式/生成回退（如实标注）；
    3. 视频元数据探测（ffmpeg）+ 事件时刻关键帧抽取（视频不可用则该轨道 unavailable）；
    4. 构建真实产物（时序 CSV 全量+weld 窗口切片 / 关键帧 JPG / tracks.json）并上传
       MinIO，任一写失败逆序清理已写对象后重抛；
    5. 同事务：新建「时间对齐」`DataVersion`（v1.<n+1>，operator=算法任务）并更新
       `latest_version_id`（`services.welds.create_version`）、回填
       `alignment_tasks.events/tracks/assets`、`mark_succeeded(job, result)`。
    commit 由调用方（executor）在返回后统一提交。
    """
    version = session.get(DataVersion, task.version_id)
    if version is None:
        raise ValueError(f"对齐任务引用的版本不存在: version_id={task.version_id}")
    record = session.get(DataRecord, version.record_id)
    if record is None:
        raise ValueError(f"对齐任务引用的焊缝不存在: record_id={version.record_id}")

    modalities = list(task.modalities or record.modalities or ["video", "timeseries"])

    # ── 20%：输入清单 + 信号/事件 ────────────────────────────────────
    sources = _collect_sources(session, record, version)
    signal_version_id = _signal_version_id(session, record, task, version)
    bundle = signal_ingest.load_signal_bundle(session, record.weld_id, signal_version_id)
    events = _normalize_events(bundle.events)
    _advance(session, job, _PROGRESS_STEPS[0])

    # ── 40%：视频探测 + 关键帧（逐模态容错，失败转 unavailable） ──────
    video_key = sources["video"][0] if sources["video"] else None
    video_data, video_meta, video_error = _load_video(video_key)
    keyframes: list[dict] = []
    if video_data is not None:
        try:
            video_meta, keyframes = media_probe.analyze_video(
                video_data, _event_points(events)
            )
        except (RuntimeError, ValueError) as exc:
            video_error = str(exc)
            logger.warning("视频对齐探测失败（转 unavailable）: weld={} err={}", record.weld_id, exc)
    _advance(session, job, _PROGRESS_STEPS[1])

    # ── 60%：轨道构建 + 产物字节 ─────────────────────────────────────
    tracks = _build_tracks(modalities, sources, bundle, video_key, video_meta,
                           video_error, keyframes)
    payloads = _build_asset_payloads(record.weld_id, bundle, events, tracks, keyframes,
                                     version_id=task.version_id,
                                     source_version_id=signal_version_id)
    _advance(session, job, _PROGRESS_STEPS[2])

    # ── 80%：上传（任一失败逆序清理后重抛） ──────────────────────────
    asset_keys = [key for key, _data, _ct in payloads]
    _write_assets(payloads)
    _advance(session, job, _PROGRESS_STEPS[3])

    # ── 100%：时间对齐版本 + 回填 + succeeded（同最终事务） ───────────
    aligned_version = create_version(
        session,
        record,
        action="时间对齐",
        note="多模态时间轴对齐（算法任务自动生成）",
        object_keys=asset_keys,
        operator="算法任务",
    )

    task.events = events
    task.tracks = tracks
    task.assets = asset_keys
    session.add(task)

    result = {
        "events": events,
        "event_source": bundle.source,
        "tracks": tracks,
        "assets": asset_keys,
        "version": version_payload(aligned_version),
    }
    mark_succeeded(session, job, result)
    return result


def _advance(session: Session, job: Job, progress: int) -> None:
    """进度步进：执行器专用 session 场景，逐次 commit 让轮询可见。"""
    job.progress = progress
    session.commit()
    time.sleep(_PROGRESS_SLEEP)


# ── 输入清单 ─────────────────────────────────────────────────────────


def _collect_sources(
    session: Session, record: DataRecord, version: DataVersion
) -> dict[str, list[str]]:
    """按扩展名把 raw 文件键分模态桶（规则同 `welds._derive_modalities`）。

    原始文件挂 v1.0（`get_v10_version`），合并当前版本 object_keys（兼容对齐直接跑在
    v1.0 / 加工版本带新文件的情况），去重保序。
    """
    keys: list[str] = []
    v10 = get_v10_version(session, record.id)
    if v10 is not None and v10.object_keys:
        keys.extend(v10.object_keys)
    if version.object_keys:
        keys.extend(version.object_keys)
    seen: set[str] = set()
    ordered: list[str] = []
    for key in keys:
        if key not in seen:
            seen.add(key)
            ordered.append(key)

    buckets: dict[str, list[str]] = {"video": [], "timeseries": [], "audio": [], "infrared": []}
    for key in ordered:
        if "/align/" in key.lower():
            # 上次对齐产物（processed/{weld_id}/align/...）不是原始模态源：重复对齐
            # 会把 keyframes/*.jpg 误归红外桶、align CSV 误归时序桶，故一律跳过。
            continue
        low = key.lower()
        if low.endswith(_VIDEO_EXTS):
            buckets["video"].append(key)
        elif low.endswith(_TS_EXTS):
            buckets["timeseries"].append(key)
        elif low.endswith(_AUDIO_EXTS):
            buckets["audio"].append(key)
        elif "infrared" in low or low.endswith(_IMAGE_EXTS) or low.endswith((".seq", ".raw")):
            # 图像（熔池/红外快照）与红外专有格式：无连续时间轴，仅登记元数据。
            buckets["infrared"].append(key)
    return buckets


def _signal_version_id(
    session: Session, record: DataRecord, task: AlignmentTask, version: DataVersion
) -> int:
    """task.version_id 有 succeeded ingest 用之；否则回退 v1.0（raw CSV 挂载处）；再否则原样。"""

    def _has_ingest(vid: int) -> bool:
        return (
            session.exec(
                select(SignalIngest.id).where(
                    SignalIngest.version_id == vid,
                    SignalIngest.status == "succeeded",
                )
            ).first()
            is not None
        )

    if _has_ingest(task.version_id):
        return task.version_id
    v10 = get_v10_version(session, record.id)
    if v10 is not None and v10.id != task.version_id and _has_ingest(v10.id):
        return v10.id
    return task.version_id


# ── 视频 ─────────────────────────────────────────────────────────────


def _load_video(video_key: str | None) -> tuple[bytes | None, dict | None, str | None]:
    """读视频对象字节；任何失败转 `(None, None, reason)` 不阻塞任务。

    逐模态容错（坑）：测试 FakeStorage 可能没有 `get_object`（AttributeError），
    seed 的 raw 键在 MinIO 中可能不存在（S3Error）——一律降级 unavailable。
    """
    if video_key is None:
        return None, None, "未上传视频文件"
    from app.storage import get_storage  # 延迟导入，测试 monkeypatch

    storage = get_storage()
    read = getattr(storage, "get_object", None)
    if read is None:
        return None, None, "存储客户端不支持读取对象（测试环境）"
    try:
        data = read(video_key)
    except Exception as exc:  # noqa: BLE001 - 源对象不可读 → unavailable
        return None, None, f"视频对象不可读: {exc}"
    if not data:
        return None, None, "视频对象为空"
    if len(data) > media_probe.MAX_VIDEO_PROBE_BYTES:
        return None, None, f"视频超过 {media_probe.MAX_VIDEO_PROBE_BYTES // (1024 * 1024)}MB，跳过探测"
    return data, None, None


def _event_points(events: dict) -> list[tuple[str, float]]:
    """关键帧事件表：起弧 / 焊接段起止 / 收弧（defensive 解析，缺失跳过）。"""
    points: list[tuple[str, float]] = []
    if isinstance(events.get("arc"), (int, float)):
        points.append(("arc", float(events["arc"])))
    seg = events.get("weld_segment")
    if isinstance(seg, (list, tuple)) and len(seg) >= 2:
        if isinstance(seg[0], (int, float)):
            points.append(("weld_start", float(seg[0])))
        if isinstance(seg[1], (int, float)):
            points.append(("weld_end", float(seg[1])))
    if isinstance(events.get("tail"), (int, float)):
        points.append(("tail", float(events["tail"])))
    return points


def _normalize_events(events: dict) -> dict:
    """事件 dict JSON 安全化（float 化；weld_segment 定长二元组）。"""
    seg = events.get("weld_segment") or []
    return {
        "arc": float(events.get("arc", 0.0)),
        "weld_segment": [float(seg[0]) if len(seg) > 0 else 0.0,
                         float(seg[1]) if len(seg) > 1 else 0.0],
        "tail": float(events.get("tail", 0.0)),
    }


# ── 轨道构建 ─────────────────────────────────────────────────────────


def _build_tracks(
    modalities: list[str],
    sources: dict[str, list[str]],
    bundle,
    video_key: str | None,
    video_meta: dict | None,
    video_error: str | None,
    keyframes: list[dict],
) -> list[dict]:
    """按任务模态构建轨道列表（保序去重；availability 语义见模块 docstring）。"""
    tracks: list[dict] = []
    seen: set[str] = set()
    for mod in modalities:
        for channel in _MODALITY_TRACKS.get(mod, []):
            if channel in seen:
                continue
            seen.add(channel)
            if mod == "timeseries":
                tracks.append(_timeseries_track(channel, sources, bundle))
            elif mod == "video":
                tracks.append(_video_track(channel, video_key, video_meta, video_error, keyframes))
            elif mod == "audio":
                tracks.append(_registry_track(channel, mod, sources["audio"], "音频"))
            elif mod == "infrared":
                tracks.append(_registry_track(channel, mod, sources["infrared"], "红外"))
    return tracks or [_video_track("video", None, None, "未上传视频文件", [])]


def _timeseries_track(channel: str, sources: dict[str, list[str]], bundle) -> dict:
    """时序轨道：恒对齐成功（real 或 generated 如实标注）；asset 指向切片 CSV。"""
    real = bundle.source == "real"
    return {
        "channel": channel,
        "modality": "timeseries",
        "availability": "available" if real else "generated",
        "source": bundle.source,
        "aligned": True,
        "asset": "processed/-/align/timeseries.csv",  # 由 _build_asset_payloads 回填真实键
        "object_key": sources["timeseries"][0] if sources["timeseries"] else None,
        "metadata": {
            "sample_rate": int(bundle.sample_rate),
            "duration": round(float(bundle.duration), 4),
            "channels": list(_TS_CHANNEL_IDS),
        },
        "reason": None if real else "无真实信号导入，使用确定性生成信号（演示回退）",
    }


def _video_track(
    channel: str,
    video_key: str | None,
    video_meta: dict | None,
    video_error: str | None,
    keyframes: list[dict],
) -> dict:
    """视频轨道：探测+关键帧成功 → available/source=real；否则 unavailable + reason。

    asset 恒为 None——不产出对齐视频（不重编码），前端播放 raw 原始对象。
    """
    base: dict = {
        "channel": channel,
        "modality": "video",
        "availability": "unavailable",
        "source": None,
        "aligned": False,
        "asset": None,
        "object_key": video_key,
        "metadata": None,
        "reason": video_error or "视频对齐未执行",
    }
    if video_meta is None:
        return base
    base["availability"] = "available"
    base["source"] = "real"
    base["aligned"] = True
    base["reason"] = None
    base["metadata"] = {
        "duration": round(float(video_meta["duration"]), 4),
        "fps": video_meta.get("fps"),
        "width": video_meta.get("width"),
        "height": video_meta.get("height"),
        "keyframes": [
            {"event": kf["event"], "t": kf["t"]} for kf in keyframes
        ],
    }
    return base


def _registry_track(channel: str, modality: str, keys: list[str], label: str) -> dict:
    """音频/红外轨道：仅登记元数据（对齐内核未启用，aligned=false），无文件转 unavailable。"""
    if not keys:
        return {
            "channel": channel,
            "modality": modality,
            "availability": "unavailable",
            "source": None,
            "aligned": False,
            "asset": None,
            "object_key": None,
            "metadata": None,
            "reason": f"未上传{label}文件",
        }
    return {
        "channel": channel,
        "modality": modality,
        "availability": "available",
        "source": "real",
        "aligned": False,
        "asset": None,
        "object_key": keys[0],
        "metadata": {"object_key": keys[0]},
        "reason": f"{label}对齐内核未启用，仅登记元数据",
    }


# ── 产物 ─────────────────────────────────────────────────────────────


def _build_asset_payloads(
    weld_id: str,
    bundle,
    events: dict,
    tracks: list[dict],
    keyframes: list[dict],
    version_id: int,
    source_version_id: int,
) -> list[tuple[str, bytes, str]]:
    """构建真实产物 `(object_key, bytes, content_type)` 列表，tracks.json 恒在末尾。"""
    base = f"processed/{weld_id}/align"
    payloads: list[tuple[str, bytes, str]] = []

    full_csv, weld_csv = _timeseries_csvs(bundle)
    payloads.append((f"{base}/timeseries.csv", full_csv, "text/csv"))
    payloads.append((f"{base}/timeseries_weld.csv", weld_csv, "text/csv"))
    ts_asset = f"{base}/timeseries.csv"

    for kf in keyframes:
        payloads.append((f"{base}/keyframes/{kf['event']}.jpg", kf["bytes"], "image/jpeg"))

    # 回填轨道 asset 引用（timeseries 各通道共享切片 CSV；关键帧 asset 写进 video metadata）。
    for track in tracks:
        if track["modality"] == "timeseries":
            track["asset"] = ts_asset
        elif track["modality"] == "video" and track["metadata"]:
            track["metadata"]["keyframes"] = [
                {**kf, "asset": f"{base}/keyframes/{kf['event']}.jpg"} for kf in track["metadata"]["keyframes"]
            ]

    doc = {
        "schema_version": "1",
        "weld_id": weld_id,
        "version_id": version_id,
        "source_version_id": source_version_id,
        "events": events,
        "event_source": bundle.source,
        "signal_source": bundle.source,
        "duration": round(float(bundle.duration), 4),
        "tracks": tracks,
    }
    payloads.append((f"{base}/tracks.json", json.dumps(doc, ensure_ascii=False).encode("utf-8"), "application/json"))
    return payloads


def _timeseries_csvs(bundle) -> tuple[bytes, bytes]:
    """全时长 CSV + weld_segment 窗口切片 CSV（`t,cur,vol,gas,wir`；超限抽稀）。

    内存友好（长记录可达千万点）：不建全量时间轴/布尔掩码，采样率均匀时
    `t = i / fs`，焊接段窗口下标用 `ceil(start*fs) .. floor(end*fs)` 直算，
    与旧 `np.arange(n)/fs + flatnonzero` 选出完全相同的行。
    """
    channels = [bundle.channel(cid) for cid in _TS_CHANNEL_IDS]
    if any(c is None for c in channels):
        raise ValueError(f"信号缺少时序通道: {[c for c in _TS_CHANNEL_IDS if bundle.channel(c) is None]}")
    n = len(channels[0].values)
    if any(len(c.values) != n for c in channels):
        raise ValueError("时序通道长度不一致，无法生成对齐 CSV")
    fs = float(bundle.sample_rate)

    full_idx = list(range(0, n, max(1, -(-n // _MAX_TS_ROWS))))
    seg = events_window(bundle)
    ws = max(0, math.ceil(seg[0] * fs))
    we = min(n - 1, math.floor(seg[1] * fs))
    weld_idx_all = list(range(ws, we + 1))
    weld_idx = (
        weld_idx_all[:: max(1, -(-len(weld_idx_all) // _MAX_TS_ROWS))]
        if weld_idx_all
        else []
    )
    return (
        _csv_bytes(channels, full_idx, fs),
        _csv_bytes(channels, weld_idx, fs),
    )


def events_window(bundle) -> tuple[float, float]:
    """焊接段窗口（异常/缺失时退化为全时长）。"""
    seg = bundle.events.get("weld_segment") or []
    start = float(seg[0]) if len(seg) > 0 else 0.0
    end = float(seg[1]) if len(seg) > 1 else float(bundle.duration)
    return start, end


def _csv_bytes(channels, idxs: list[int], fs: float) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["t", *[c.id for c in channels]])
    for i in idxs:
        writer.writerow([f"{i / fs:.6f}", *[f"{float(c.values[i]):.6f}" for c in channels]])
    return buf.getvalue().encode("utf-8")


def _write_assets(payloads: list[tuple[str, bytes, str]]) -> None:
    """逐个上传产物到 MinIO；任一写失败逆序删除已写对象后重抛（不落库虚假 assets）。"""
    from app.storage import get_storage

    storage = get_storage()
    uploaded: list[str] = []
    try:
        for key, data, content_type in payloads:
            storage.upload_stream(key, io.BytesIO(data), len(data), content_type)
            uploaded.append(key)
    except Exception:
        for key in reversed(uploaded):
            try:
                storage.delete_object(key)
            except Exception:  # noqa: BLE001 - 清理失败只记日志，不覆盖原始异常
                logger.warning("清理对齐产物失败: {}", key)
        raise
