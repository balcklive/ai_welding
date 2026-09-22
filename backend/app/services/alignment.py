"""多模态对齐服务（Task 13，真实化内核）：真实事件/信号 + 真实产物 + 自动生成「时间对齐」版本。

产物结构照 `docs/API接口清单.md` §3.4（tracks 结构为对齐真实化后扩展版）：
- `events` = `{arc, weld_segment[], tail}`——来自真实信号（`signal_ingest.load_signal_bundle`，
  成功导入 CSV 时是 detect_events 的真实启发式结果；无导入回退确定性生成并如实标注
  `event_source="generated"`）；
- `tracks` = 各模态轨道列表，每条含 `availability`（available/generated/unavailable）与
  `reason`——**部分成功语义**：缺失模态不阻塞任务，至少一个模态对齐成功即 succeeded
  （timeseries 兜底恒成立）；
- `assets` = 真实产物对象键（`processed/{weld_id}/align/` 下时序 CSV×2 / 关键帧 JPG /
  mapping.json / tracks.json），回填 `alignment_tasks.assets`，前端经 `GET /files/{key}/url` 下载。
  不再产出 video.mp4/audio.wav 等占位字节——视频前端直接播放 raw 原始对象。

**统一坐标系与模态映射（2026-09-22）**：本服务不再只产"轨道清单"，还产出**可执行的坐标映射**
（`mapping.json` + `alignment_tasks.mapping`）——见 `build_coordinate_mapping`。基准轴是信号
时间轴，视频走 `linear`（人工标定 offset）、焊缝图片走 `arc_length`（焊接速度积分到沿焊缝的
长度比例）。`aligned = available && calibrated`：**未标定的模态不再声称已对齐**（此前视频轨
硬编码 `aligned=True` 是无依据的声明，见设计文档 §1.1）。标定参数（人工）来自源版本的
`data_versions.calibration`；本服务只消费，不写。

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
from datetime import datetime, timezone

import numpy as np
from loguru import logger
from PIL import Image
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

#: 进度递增点（0→100）：20=清单+信号/事件 → 40=视频探测 → 60=坐标映射+关键帧+轨道/产物
#: → 80=上传 → 100=mark_succeeded。步间 commit + 小睡，让轮询/前端能看到 progress 变化。
_PROGRESS_STEPS: tuple[int, ...] = (20, 40, 60, 80)
_PROGRESS_SLEEP: float = 0.05

#: 模态 → 轨道（channel 名称对齐 signals 生成器 / App.tsx），保序去重。
_MODALITY_TRACKS: dict[str, list[str]] = {
    "video": ["video"],
    "timeseries": ["current", "voltage"],
    "audio": ["audio"],
    "infrared": ["infrared"],
    # 焊缝宏观照片：空间模态，沿焊缝长度切分（2026-09-22 从 infrared 桶析出）
    "seam_image": ["seam_image"],
}

#: 时序 CSV 的通道顺序（对齐 signal_ingest Parquet 列 schema `t,cur,vol,gas,wir`）。
_TS_CHANNEL_IDS: tuple[str, ...] = ("cur", "vol", "gas", "wir")

#: 时序 CSV 单文件最大行数（真实 1kHz 长记录可达百万行，超限按步长抽稀）。
_MAX_TS_ROWS = 100_000

# ── 统一坐标系与模态映射（设计 §3.1） ─────────────────────────────────
#
# 基准轴 = 信号时间轴（首采样点为原点）。其他模态各持一条映射，把统一轴上的时刻换算到
# 本模态坐标：视频走 `linear`（offset），焊缝图片走 `arc_length`（沿焊缝的弧长比例）。
# `aligned = available && calibrated`——未标定的模态**不声称已对齐**。
#
# 标定参数（人工）存 `data_versions.calibration`；算出的映射存 `alignment_tasks.mapping`。

#: 弧长折线降采样点数上限（内联进 mapping.json，供分段预览按 t 插值 r）。
_ARC_PROFILE_POINTS = 256


def _downsample_indices(n: int, limit: int) -> np.ndarray:
    """`0..n-1` 的等距下标（含首尾）；`n <= limit` 时原样返回。"""
    if n <= limit:
        return np.arange(n)
    return np.unique(np.linspace(0, n - 1, limit).astype(np.int64))


def position_ratio_at(profile: list[list[float]], t: float) -> float:
    """在弧长折线上线性插值取位置比例 `r(t)`（0..1）。

    折线形如 `[[t, r], ...]`（t 升序）。区间外**钳制到端点、不外推**——窗口越界由调用方
    按「该模态本窗缺失」处理，这里给端点值只是避免 NaN。
    """
    if not profile:
        return 0.0
    if t <= profile[0][0]:
        return float(profile[0][1])
    if t >= profile[-1][0]:
        return float(profile[-1][1])
    lo, hi = 0, len(profile) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if profile[mid][0] <= t:
            lo = mid
        else:
            hi = mid
    t0, r0 = profile[lo]
    t1, r1 = profile[hi]
    if t1 <= t0:
        return float(r1)
    return float(r0 + (r1 - r0) * (t - t0) / (t1 - t0))


def arc_length_profile(
    bundle, event_bounds: tuple[float, float], *, has_scalar_speed: bool
) -> tuple[str, list[list[float]]]:
    """有效焊接区间内的归一化位置比例折线，返回 `(speed_source, profile)`。

    `speed_source` 三级降级（设计 §3.1.2）：

    - `channel`：CSV 含 `weld_speed` 通道 → 积分弧长 `r(t) = L(t) / L_total`，`L(t)=∫v dτ`；
    - `scalar`：无通道但有登记单值 `welding_speed`（稳态中位数）→ 恒速；
    - `none`：两者皆无 → 纯时间比例。

    **`scalar` 与 `none` 的折线完全相同**（都是恒速假设下的时间比例），区别只在如实标注
    用了哪一级依据，故由调用方按数据可得性定 `speed_source`。
    """
    start, end = float(event_bounds[0]), float(event_bounds[1])
    if end <= start:
        # 无效有效区间：退化为零长折线，映射不可用（由调用方的 reason 表达）
        return "none", [[round(start, 6), 0.0], [round(start, 6), 1.0]]

    fs = int(bundle.sample_rate or 0)
    channel = bundle.channel("weld_speed") if fs > 0 else None
    if channel is not None:
        values = np.asarray(channel.values, dtype=float)
        i0 = max(0, math.ceil(start * fs))
        i1 = min(len(values), math.floor(end * fs))
        if i1 - i0 >= 2:
            # 负速度（收弧回抽等）不计入弧长——物理上焊缝不会倒退
            cum = np.cumsum(np.clip(values[i0:i1], 0.0, None)) / fs
            # 平移到区间起点：cumsum 从**首个采样值**起算会让 r(t0)=v0/fs>0，
            # 归零后 r 才是"自有效区间起点的累计弧长占比"（r(t0)=0、r(end)=1）
            cum -= cum[0]
            total = float(cum[-1])
            if total > 0:
                idx = _downsample_indices(len(cum), _ARC_PROFILE_POINTS)
                return "channel", [
                    [round(float(t), 6), round(float(r), 6)]
                    for t, r in zip((i0 + idx) / fs, cum[idx] / total)
                ]

    return (
        "scalar" if has_scalar_speed else "none",
        [[round(start, 6), 0.0], [round(end, 6), 1.0]],
    )


def _normalize_roi(roi) -> dict | None:
    """校验焊缝图片 ROI 形状（x/y/w/h 四个有限数、w/h > 0）；不合法返回 None。

    只校验**形状**；是否落在真实图片范围内由标定写入路径
    （`validate_calibration_patch(image_size=...)`）负责——只有那里拿得到图片宽高。
    """
    if not isinstance(roi, dict):
        return None
    try:
        x, y, w, h = (float(roi[k]) for k in ("x", "y", "w", "h"))
    except (KeyError, TypeError, ValueError):
        return None
    if not all(math.isfinite(v) for v in (x, y, w, h)) or w <= 0 or h <= 0:
        return None
    return {"x": x, "y": y, "w": w, "h": h}


def build_coordinate_mapping(
    *,
    bundle,
    events: dict,
    calibration: dict | None,
    has_scalar_speed: bool,
    video_key: str | None,
    video_meta: dict | None,
    seam_image_key: str | None,
) -> dict:
    """构建统一坐标系与各模态映射（设计 §3.1）。

    标定缺失**不阻断**——对应模态记 `calibrated=false` + reason，分段照常进行但如实标记。
    """
    seg = events.get("weld_segment") or [0.0, 0.0]
    bounds = (float(seg[0]), float(seg[1]))
    cal = calibration if isinstance(calibration, dict) else {}

    maps: dict[str, dict] = {
        # 基准轴自身：恒可用、恒已对齐
        "timeseries": {
            "type": "identity", "available": True, "calibrated": True, "reason": None,
        },
    }

    # ── 视频：linear（t_unified = t_video + offset） ────────────────
    video_cal = cal.get("video") if isinstance(cal.get("video"), dict) else {}
    raw_offset = video_cal.get("offset_seconds")
    calibrated = isinstance(raw_offset, (int, float)) and math.isfinite(float(raw_offset))
    if video_key and video_meta:
        maps["video"] = {
            "type": "linear",
            "available": True,
            "calibrated": calibrated,
            "offset_seconds": float(raw_offset) if calibrated else 0.0,
            "fps": video_meta.get("fps"),
            "duration": (
                round(float(video_meta["duration"]), 6)
                if isinstance(video_meta.get("duration"), (int, float))
                else None
            ),
            "reason": None if calibrated
            else "时间零点未标定：关键帧按视频与信号同零点的假设抽取",
        }
    else:
        maps["video"] = {
            "type": "linear", "available": False, "calibrated": False,
            "offset_seconds": None, "fps": None, "duration": None,
            "reason": "无可用视频文件",
        }

    # ── 焊缝图片：arc_length（沿焊缝长度按比例切分） ─────────────────
    image_cal = cal.get("seam_image") if isinstance(cal.get("seam_image"), dict) else {}
    roi = _normalize_roi(image_cal.get("roi"))
    if seam_image_key:
        speed_source, profile = arc_length_profile(
            bundle, bounds, has_scalar_speed=has_scalar_speed
        )
        maps["seam_image"] = {
            "type": "arc_length",
            "available": True,
            "calibrated": roi is not None,
            "object_key": seam_image_key,
            "roi": roi,
            "speed_source": speed_source,
            "arc_profile": profile,
            "reason": None if roi else "焊缝图片未框选 ROI：无法建立长度↔时间映射",
        }
    else:
        maps["seam_image"] = {
            "type": "arc_length", "available": False, "calibrated": False,
            "object_key": None, "roi": None, "speed_source": None, "arc_profile": None,
            "reason": "无焊缝图片文件",
        }

    maps["audio"] = {
        "type": "none", "available": False, "calibrated": False, "reason": "源未附加",
    }

    return {
        "schema_version": 1,
        "unified_axis": {
            "unit": "second",
            "origin": "signal_first_sample",
            "duration": round(float(bundle.duration), 6),
        },
        "event_bounds": {"start": bounds[0], "end": bounds[1]},
        "mappings": maps,
    }


# ── 标定（calibration）：权威归属 = 焊缝 v1.0 原始版本 ─────────────────
#
# 标定是**人工**输入（视频零点 offset、焊缝图片 ROI），存 `data_versions.calibration`。
# 归属固定钉在 **v1.0 原始版本**：对齐任务可能跑在任意加工版本上，标定若跟着任务版本走，
# 同一条焊缝就会散出多份互相矛盾的标定。v1.0 是每条焊缝唯一且不变的锚点。
#
# 写入**只改 `calibration` 一列**——不碰 `object_keys`、不重算历史 `alignment_tasks.mapping`、
# 不动任何 `split_tasks`。重新标定只影响此后新发起的对齐/分段，历史产物保持当时的口径。

#: `offset_seconds` 的绝对上限（秒）。**手误护栏**（把 `-1.1` 敲成 `-1100`），不是物理约束——
#: 真实零点偏移由现场标定决定，代码不替业务设上限。
MAX_ABS_OFFSET_SECONDS = 3600.0

#: 焊缝照片扩展名（与 `welds._IMAGE_EXTS` 同口径；这里不 import 私有常量）
_SEAM_IMAGE_EXTS: tuple[str, ...] = (".jpg", ".jpeg", ".png", ".bmp")


class CalibrationError(ValueError):
    """标定参数不合法（消息面向用户，由路由转 400）。"""


def seam_image_key(object_keys: list[str] | None) -> str | None:
    """从对象键里挑焊缝照片；跳过上次对齐的产物（`/align/keyframes/*.jpg`）。"""
    for key in object_keys or []:
        low = key.lower()
        if "/align/" not in low and low.endswith(_SEAM_IMAGE_EXTS):
            return key
    return None


def read_image_size(storage, object_key: str) -> tuple[int, int] | None:
    """取图片 `(width, height)`；下载失败或解不开返回 None。

    `Image.open` 只解析**文件头**、不做全图解码，所以取 size 很便宜（代价是仍要下载整个对象）。
    """
    try:
        data = storage.get_object(object_key)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Seam image unreadable for calibration: key={} err={}", object_key, exc)
        return None
    try:
        with Image.open(io.BytesIO(data)) as img:
            return int(img.width), int(img.height)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Seam image undecodable for calibration: key={} err={}", object_key, exc)
        return None


def anchored_calibration(
    session: Session, record: DataRecord
) -> tuple[DataVersion | None, dict]:
    """标定上下文：归属版本（v1.0）+ 当前标定（未标定 → `{}`）。

    **所有读取标定的路径都走这里**（对齐任务、GET/PUT 端点），"读哪份标定"只在这一处定义。
    """
    v10 = get_v10_version(session, record.id)
    raw = v10.calibration if v10 is not None else None
    return v10, (dict(raw) if isinstance(raw, dict) else {})


def resolve_calibration(session: Session, record: DataRecord) -> dict:
    """读该焊缝的权威标定（v1.0 归属）。"""
    return anchored_calibration(session, record)[1]


def calibration_offset_seconds(calibration: dict) -> float:
    """从标定里取视频零点 `offset_seconds`（`t_video = t_signal - offset`）。

    未标定返回 `0.0`——即"视频与信号同零点"的旧假设；此时映射会如实记 `calibrated=false`，
    调用方（分段 Job 等）拿它当地址换算即可，不需要自己判空。
    """
    video = calibration.get("video")
    offset = video.get("offset_seconds") if isinstance(video, dict) else None
    if isinstance(offset, bool) or not isinstance(offset, (int, float)):
        return 0.0
    return float(offset)


def validate_calibration_patch(
    payload: dict, *, image_size: tuple[int, int] | None
) -> dict:
    """校验 PUT 载荷，返回**只含本次给出键**的规范化补丁（合并语义）。

    组值为 `None` 表示清除该组。ROI 必须落在真实图片范围内——`image_size` 为 None 时
    **拒绝**：核实不了的断言不该放行。
    """
    if not isinstance(payload, dict):
        raise CalibrationError("标定载荷必须是对象")
    patch: dict = {}

    if "video" in payload:
        video = payload["video"]
        if video is None:
            patch["video"] = None
        elif isinstance(video, dict):
            offset = video.get("offset_seconds")
            if isinstance(offset, bool) or not isinstance(offset, (int, float)):
                raise CalibrationError("video.offset_seconds 必须是有限数值")
            if not math.isfinite(float(offset)):
                raise CalibrationError("video.offset_seconds 必须是有限数值")
            if abs(float(offset)) > MAX_ABS_OFFSET_SECONDS:
                raise CalibrationError(
                    f"video.offset_seconds 超出 ±{MAX_ABS_OFFSET_SECONDS:g} 秒的手误护栏范围"
                )
            patch["video"] = {"offset_seconds": float(offset)}
        else:
            raise CalibrationError("video 必须是对象或 null")

    if "seam_image" in payload:
        seam = payload["seam_image"]
        if seam is None:
            patch["seam_image"] = None
        elif isinstance(seam, dict):
            roi = _normalize_roi(seam.get("roi"))
            if roi is None:
                raise CalibrationError("seam_image.roi 必须是 {x,y,w,h} 四个有限数且 w/h > 0")
            if image_size is None:
                raise CalibrationError("读不到该焊缝的图片，无法校验 ROI 是否落在图片范围内")
            width, height = image_size
            if (roi["x"] < 0 or roi["y"] < 0
                    or roi["x"] + roi["w"] > width or roi["y"] + roi["h"] > height):
                raise CalibrationError(
                    f"ROI 超出图片范围（图片 {width}×{height}，ROI "
                    f"x={roi['x']:g} y={roi['y']:g} w={roi['w']:g} h={roi['h']:g}）"
                )
            patch["seam_image"] = {"roi": roi}
        else:
            raise CalibrationError("seam_image 必须是对象或 null")

    return patch


def merge_calibration(current: dict, patch: dict) -> dict:
    """把补丁合并进现有标定；值为 `None` 的组被清除。"""
    merged = dict(current)
    for group, value in patch.items():
        if value is None:
            merged.pop(group, None)
        else:
            merged[group] = value
    return merged


def save_calibration(session: Session, v10: DataVersion, calibration: dict) -> None:
    """把标定写到 v1.0 版本（**只改 `calibration` 一列**）。不 commit，由调用方提交。"""
    v10.calibration = calibration or None
    session.add(v10)
    session.flush()


def calibration_payload(v10: DataVersion | None, calibration: dict) -> dict:
    """GET/PUT 共用的响应体：标定原文 + 归属版本 + 两组各自的标定状态。"""
    video = calibration.get("video")
    offset = video.get("offset_seconds") if isinstance(video, dict) else None
    has_offset = isinstance(offset, (int, float)) and not isinstance(offset, bool)
    seam = calibration.get("seam_image")
    roi = _normalize_roi(seam.get("roi")) if isinstance(seam, dict) else None
    return {
        "calibration": calibration,
        "anchored_version_id": v10.id if v10 is not None else None,
        "video": {
            "offset_seconds": float(offset) if has_offset else 0.0,
            "calibrated": has_offset,
        },
        "seam_image": {
            "roi": roi,
            "calibrated": roi is not None,
            "object_key": seam_image_key(v10.object_keys if v10 is not None else None),
        },
    }


def run_alignment(session: Session, task: AlignmentTask, job: Job) -> dict:
    """真实执行一次对齐任务，返回写入 `job.result` 的 dict。

    步骤（进度语义见 `_PROGRESS_STEPS`）：
    1. 解析输入清单（v1.0 原始文件 + 当前版本 object_keys 按扩展名分模态）；
    2. 信号版本回退解析并加载 `SignalBundle`，events 取真实启发式/生成回退（如实标注）；
    3. 视频探测（ffmpeg，只探元信息）→ **建坐标映射**（读 v1.0 标定的 offset）→ 按
       `t_video = t_signal - offset` 抽事件关键帧（视频不可用则该轨道 unavailable）；
    4. 构建真实产物（时序 CSV 全量+weld 窗口切片 / 关键帧 JPG / mapping.json /
       tracks.json）并上传 MinIO，任一写失败逆序清理已写对象后重抛；
    5. 同事务：新建「时间对齐」`DataVersion`（v1.<n+1>，operator=算法任务）并更新
       `latest_version_id`（`services.welds.create_version`）、回填
       `alignment_tasks.events/tracks/assets`、`mark_succeeded(job, result)`。
    commit 由调用方（executor）在返回后统一提交。
    """
    version = session.get(DataVersion, task.version_id)
    if version is None:
        raise ValueError(f"The alignment task references a missing version: version_id={task.version_id}")
    record = session.get(DataRecord, version.record_id)
    if record is None:
        raise ValueError(f"The alignment task references a missing weld: record_id={version.record_id}")

    modalities = list(task.modalities or record.modalities or ["video", "timeseries"])

    # ── 20%：输入清单 + 信号/事件 ────────────────────────────────────
    sources = _collect_sources(session, record, version)
    # 焊缝图片恒入轨：它不参与「要不要跑」的模态选择（无需探测，只是一张参考图），
    # 但用户必须看见它的标定状态——否则把它从 infrared 桶析出后就彻底不可见了。
    if sources["seam_image"] and "seam_image" not in modalities:
        modalities.append("seam_image")
    signal_version_id = _signal_version_id(session, record, task, version)
    bundle = signal_ingest.load_signal_bundle(session, record.weld_id, signal_version_id)
    events = _normalize_events(bundle.events)
    _advance(session, job, _PROGRESS_STEPS[0])

    # ── 40%：视频探测 + 关键帧（逐模态容错，失败转 unavailable） ──────
    video_key = sources["video"][0] if sources["video"] else None
    # 未选择视频模态时不应探测视频对象；远端对象的 stat/get 可能较慢，
    # 且该模态不参与本次任务结果。
    video_data, video_meta, video_error = (
        _load_video(video_key) if "video" in modalities else (None, None, "未纳入视频模态")
    )
    if video_data is not None:
        try:
            # 只探测元信息，不抽帧——抽帧要等映射建好、拿到 offset 之后再按
            # `t_video = t_signal - offset` 定位（设计 §3.1.1）。
            video_meta, _ = media_probe.analyze_video(video_data, [])
        except (RuntimeError, ValueError) as exc:
            video_error = str(exc)
            logger.warning("Video alignment probe failed (marking unavailable): weld={} err={}", record.weld_id, exc)
    _advance(session, job, _PROGRESS_STEPS[1])

    # ── 60%：坐标映射 + 关键帧 + 轨道 + 产物字节 ─────────────────────
    # 顺序是刻意的：先探测拿到 fps/duration → 建映射 → 再用**映射里的 offset** 抽帧。
    # 这样"用哪个 offset"只有映射一处来源，不会出现抽帧与 mapping 记录不一致。
    # 标定统一走 resolver（权威归属 = v1.0 原始版本），不读任务发起版本上的副本。
    calibration = resolve_calibration(session, record)
    mapping = build_coordinate_mapping(
        bundle=bundle,
        events=events,
        calibration=calibration,
        has_scalar_speed=record.welding_speed is not None,
        video_key=video_key,
        video_meta=video_meta,
        seam_image_key=sources["seam_image"][0] if sources["seam_image"] else None,
    )
    keyframes: list[dict] = []
    if video_data is not None and video_meta is not None:
        try:
            seek_offset = float(mapping["mappings"]["video"].get("offset_seconds") or 0.0)
            _, keyframes = media_probe.analyze_video(
                video_data, _event_points(events), seek_offset=seek_offset
            )
        except (RuntimeError, ValueError) as exc:
            # 探测已成功、只是抽帧失败：降级为"无关键帧"，不把整条视频轨打成 unavailable
            logger.warning("Keyframe extraction failed: weld={} err={}", record.weld_id, exc)
    tracks = _build_tracks(modalities, sources, bundle, video_key, video_meta,
                           video_error, keyframes, mapping)
    payloads = _build_asset_payloads(record.weld_id, bundle, events, tracks, keyframes,
                                     version_id=task.version_id,
                                     source_version_id=signal_version_id,
                                     mapping=mapping)
    _advance(session, job, _PROGRESS_STEPS[2])

    # ── 80%：上传（任一失败逆序清理后重抛） ──────────────────────────
    asset_keys = [key for key, _data, _ct in payloads]
    _write_assets(payloads)
    _advance(session, job, _PROGRESS_STEPS[3])

    # ── 100%：时间对齐版本 + 回填 + succeeded（同最终事务） ───────────
    # 加工版本是新的快照，但原始多模态对象仍属于同一条焊缝的数据血缘。
    # 复用对象 key 而不是复制对象，保证后续页面/任务仍能读取源视频、CSV 等原始文件。
    inherited_keys: list[str] = []
    source_v10 = get_v10_version(session, record.id)
    for source in (source_v10, version):
        for key in (source.object_keys if source is not None else []) or []:
            if "/align/" not in key.lower() and key not in inherited_keys:
                inherited_keys.append(key)
    version_object_keys = inherited_keys + [key for key in asset_keys if key not in inherited_keys]
    aligned_version = create_version(
        session,
        record,
        action="时间对齐",
        note="多模态时间轴对齐（算法任务自动生成）",
        object_keys=version_object_keys,
        operator="算法任务",
    )
    # 对齐会生成焊缝的新版本；复制真实信号索引，使后续信号分析/特征提取
    # 继续读取同一份已校验 Parquet，而不是因 latest_version_id 变化误报“信号不可用”。
    source_ingest = session.exec(
        select(SignalIngest)
        .where(
            SignalIngest.version_id == signal_version_id,
            SignalIngest.status == "succeeded",
        )
        .order_by(SignalIngest.created_at.desc(), SignalIngest.id.desc())
    ).first()
    if source_ingest is not None and source_ingest.parquet_key:
        session.add(SignalIngest(
            job_id=job.id,
            version_id=aligned_version.id,
            source_object_key=source_ingest.source_object_key,
            status="succeeded",
            sample_rate=source_ingest.sample_rate,
            duration=source_ingest.duration,
            row_count=source_ingest.row_count,
            column_map=source_ingest.column_map,
            validation=source_ingest.validation,
            parquet_key=source_ingest.parquet_key,
            events=source_ingest.events,
            anomalies=source_ingest.anomalies,
            created_at=datetime.now(timezone.utc),
            finished_at=datetime.now(timezone.utc),
        ))

    task.events = events
    task.tracks = tracks
    task.mapping = mapping
    task.assets = asset_keys
    session.add(task)

    result = {
        "events": events,
        "event_source": bundle.source,
        "tracks": tracks,
        "mapping": mapping,
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

    buckets: dict[str, list[str]] = {
        "video": [], "timeseries": [], "audio": [], "seam_image": [], "infrared": [],
    }
    for key in ordered:
        if "/align/" in key.lower():
            # 上次对齐产物（processed/{weld_id}/align/...）不是原始模态源：重复对齐
            # 会把 keyframes/*.jpg 误归图像桶、align CSV 误归时序桶，故一律跳过。
            continue
        low = key.lower()
        if low.endswith(_VIDEO_EXTS):
            buckets["video"].append(key)
        elif low.endswith(_TS_EXTS):
            buckets["timeseries"].append(key)
        elif low.endswith(_AUDIO_EXTS):
            buckets["audio"].append(key)
        elif low.endswith(_IMAGE_EXTS):
            # 焊缝宏观照片：**空间模态**（沿焊缝长度切分），既不是红外快照也不是视频帧。
            # 2026-09-22 从 infrared 桶析出——此前把它判成"无连续时间轴，仅登记元数据"，
            # 实际它有轴（长度），只是没接到时间轴上（设计 §3.1.2）。
            buckets["seam_image"].append(key)
        elif "infrared" in low or low.endswith((".seq", ".raw")):
            # 红外专有格式：无连续时间轴，仅登记元数据。
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
    # 历史数据可能把成功导入挂在 v1.1 等原始版本，而不是严格的 v1.0；
    # 沿同一焊缝版本链寻找最近成功导入，避免加工版本丢失真实信号来源。
    source = session.exec(
        select(SignalIngest.version_id)
        .join(DataVersion, DataVersion.id == SignalIngest.version_id)
        .where(
            DataVersion.record_id == record.id,
            SignalIngest.status == "succeeded",
        )
        .order_by(SignalIngest.created_at.desc(), SignalIngest.id.desc())
    ).first()
    if source is not None:
        return source
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
        stat = getattr(storage, "stat_object", None)
        if stat is not None:
            size = stat(video_key)
            if size > media_probe.MAX_VIDEO_PROBE_BYTES:
                return None, None, (
                    f"视频超过 {media_probe.MAX_VIDEO_PROBE_BYTES // (1024 * 1024)}MB，"
                    "为避免任务长时间阻塞，跳过视频探测"
                )
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
    mapping: dict | None = None,
) -> list[dict]:
    """按任务模态构建轨道列表（保序去重；availability 语义见模块 docstring）。

    `mapping` 给定时，视频轨的 `aligned` 由映射的 `calibrated` 推导（未标定 → `false`）；
    缺省（无映射）按未标定处理。**视频轨不再无条件声称已对齐**。
    """
    video_calibrated = bool(
        ((mapping or {}).get("mappings") or {}).get("video", {}).get("calibrated")
    )
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
                tracks.append(_video_track(channel, video_key, video_meta, video_error,
                                           keyframes, video_calibrated))
            elif mod == "seam_image":
                seam_key = sources["seam_image"][0] if sources["seam_image"] else None
                tracks.append(_seam_image_track(seam_key, mapping))
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
    calibrated: bool = False,
) -> dict:
    """视频轨道：探测+关键帧成功 → available/source=real；否则 unavailable + reason。

    asset 恒为 None——不产出对齐视频（不重编码），前端播放 raw 原始对象。

    **`aligned` 由标定状态推导（2026-09-22）**：时间零点须由「分析 → 对齐」的标定产出
    （`calibration.video.offset_seconds`）。未标定时 `aligned=false` + reason——关键帧实为按
    `t_video ≡ t_signal` 假设抽取，实测两轴可差 1.1s（2 秒窗口下 = 55% 窗宽），此前硬编码
    `aligned=True` 是无依据的声明（见 docs/多模态时间统一样本分段重构设计方案.md §1.1）。
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
    base["aligned"] = bool(calibrated)
    base["reason"] = (
        None if calibrated else "时间零点未标定：关键帧按视频与信号同零点的假设抽取"
    )
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


def _seam_image_track(key: str | None, mapping: dict | None) -> dict:
    """焊缝图片轨道：可用性与标定状态取自坐标映射的 `seam_image`。

    与 `_registry_track`（音频/红外，恒 `aligned=false`）的区别在于**它有轴**——沿焊缝的
    长度轴，经 `arc_length` 映射接到统一时间轴上，标定 ROI 后 `aligned=true`。
    """
    seam = ((mapping or {}).get("mappings") or {}).get("seam_image") or {}
    if not key:
        return {
            "channel": "seam_image", "modality": "seam_image",
            "availability": "unavailable", "source": None, "aligned": False,
            "asset": None, "object_key": None, "metadata": None,
            "reason": seam.get("reason") or "未上传焊缝图片文件",
        }
    return {
        "channel": "seam_image", "modality": "seam_image",
        "availability": "available", "source": "real",
        "aligned": bool(seam.get("calibrated")),
        "asset": None, "object_key": key,
        "metadata": {"roi": seam.get("roi"), "speed_source": seam.get("speed_source")},
        "reason": seam.get("reason"),
    }


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
    mapping: dict | None = None,
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

    # 坐标映射单独成文（设计 §6.3）：分段任务据它把时间窗换算到视频帧/焊缝图像素。
    # 与 tracks.json 分开——tracks 是界面展示的可用性清单，mapping 是算法输入。
    if mapping is not None:
        payloads.append((
            f"{base}/mapping.json",
            json.dumps(mapping, ensure_ascii=False).encode("utf-8"),
            "application/json",
        ))

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
        raise ValueError(f"Signal bundle is missing time-series channels: {[c for c in _TS_CHANNEL_IDS if bundle.channel(c) is None]}")
    n = len(channels[0].values)
    if any(len(c.values) != n for c in channels):
        raise ValueError("Time-series channel lengths differ; cannot generate aligned CSV")
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
                logger.warning("Failed to clean up alignment artifact: {}", key)
        raise
