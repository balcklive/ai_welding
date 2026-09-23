"""生产样本分段规则与输入校验（**v3：时间统一的多模态样本**）。

本模块是**预览接口与异步执行器共用的唯一规则入口**（设计 §6.1）。只接受成功导入的真实
时序信号；不生成默认时长、默认事件或合成样本。

v3 口径（设计 §3.2/§3.3）：

- **秒是唯一切分单位**。采样点、视频帧、焊缝图片像素都是经坐标映射**派生**出来的、
  只写进 manifest 的信息，**不得反向成为切分规则**。
- 窗口算法只有一处（`build_time_windows`），预览与 Job 共用——否则会出现"预览 207、执行 8 万"。
- 预览与创建任务之间用 `preview_token` 建立"所见即所得"：token 是**规则 + 源版本 + 有效边界 +
  映射哈希**的不可变摘要，创建时服务端据此重建窗口，客户端不能另交一套规则或标定。

历史兼容：`rules_version <= 2` 的旧任务仍由 `jobs/split.py` 的旧分支按其原规则读取，
本模块只负责 v3。
"""

from __future__ import annotations

import base64
import csv
import hashlib
import hmac
import io
import json
import math
import time
from dataclasses import dataclass

from loguru import logger
from sqlmodel import Session

from app.core.config import settings
from app.models.data import DataRecord, DataVersion
from app.services import signal_ingest, signals

#: 切分规则版本（设计 §3.4）。1 = 旧口径「帧 = 采样点」；2 = 秒为唯一基准（帧仅作界面单位）；
#: **3 = 时间统一的多模态样本**（秒级固定窗口 + 经坐标映射派生各模态引用）。
#: 写进 `rules` 与切片 `meta`，供新旧切片共存时区分口径。
RULES_VERSION = 3

#: 默认窗口时长 / 步长（设计 §2.3）：默认不重叠。
DEFAULT_WINDOW_SECONDS = 2.0
DEFAULT_STRIDE_SECONDS = 2.0

#: 尾片策略：`drop` 不生成不足一个完整时长的末尾窗口（默认）；`keep` 保留不等长尾片。
TAIL_POLICIES = ("drop", "keep")

#: 浮点容差：窗口边界比较统一用它，避免 `2.0 <= 2.0` 因累加误差判假。
_EPS = 1e-9

#: 预览令牌有效期（秒）。短期凭证——规则/映射一变就该重新预览。
PREVIEW_TOKEN_TTL_SECONDS = 900.0

#: 预览响应的分层数据上限（设计 §6.4）：时序 ≤1200 点/轨、视频缩略图 ≤80 张。
_PREVIEW_SIGNAL_POINTS = 1200
_PREVIEW_VIDEO_THUMBS = 80

#: 代表帧短期 URL 的有效期（秒）。预览响应本身有 60s 缓存，URL 比缓存活得久即可。
PREVIEW_FRAME_EXPIRES_SECONDS = 3600

#: 预览结果短期缓存（设计 §6.4）：key = (version_id, rules_hash, mapping_hash)。
#: 命中的是"同一规则反复编辑"的重复请求，省掉每次重算全量信号的 min-max 池化
#: （910k 点约 300ms）。ponytail: 进程内 dict + TTL，多 worker 各自一份；
#: 真到需要跨进程共享时换 Redis，`build_preview` 的调用方不用改。
_PREVIEW_CACHE: dict[tuple, tuple[float, dict]] = {}
_PREVIEW_CACHE_TTL = 60.0


class SplitInputError(ValueError):
    """输入不满足生产分段前置条件（消息面向用户，由路由转 400）。"""


@dataclass(frozen=True)
class SplitWindow:
    """一个时间窗（**秒**）。

    `frame_start` / `frame_end` 是**信号采样点下标**（字段名是历史遗留，勿按视频帧理解），
    由 `秒 × 采样率` 向上取整派生（设计 §3.2）；视频帧号与图片像素另经坐标映射换算，
    只写进样本 manifest。
    """

    index: int
    start: float
    end: float
    frame_start: int
    frame_end: int
    window_seconds: float = 0.0

    @property
    def duration(self) -> float:
        return self.end - self.start


# ── 输入 ─────────────────────────────────────────────────────────────


def load_input(session: Session, record: DataRecord, version: DataVersion):
    """加载真实信号；没有成功导入时直接阻断。"""
    try:
        bundle = signal_ingest.load_real_signal_bundle(session, record.weld_id, version.id)
    except Exception as exc:  # noqa: BLE001
        raise SplitInputError(f"真实时序信号读取失败：{exc}") from exc
    if bundle is None or bundle.source != "real":
        raise SplitInputError("当前版本没有成功导入的真实时序信号，无法进行生产样本分段")
    if not bundle.duration or bundle.duration <= 0 or bundle.sample_rate <= 0:
        raise SplitInputError("真实时序信号缺少有效时长或采样率")
    events = bundle.events or {}
    if not _valid_event_bounds(events.get("weld_segment")):
        raise SplitInputError("当前版本未检测到有效焊接事件，无法进行生产样本分段")
    return bundle


def resolve_effective_range(
    bundle,
    override_start: float | None,
    override_end: float | None,
    buffer_seconds: float = 0.0,
) -> dict:
    """事件边界 + 人工修正 + 缓冲 → **可审计的有效区间**（设计 §6.1）。

    返回 `{start, end, source, buffer_seconds}`：`source` 记的是 `detected`（用系统检测的
    焊接段）还是 `manual`（用户改过起止），便于事后追溯这批切片是按哪条边界切的。
    """
    default = (bundle.events or {}).get("weld_segment")
    if override_start is None and override_end is None:
        if not _valid_event_bounds(default):
            bounds = default
        else:
            pad = max(0.0, float(buffer_seconds))
            bounds = [
                max(0.0, float(default[0]) - pad),
                min(float(bundle.duration), float(default[1]) + pad),
            ]
        source = "detected"
    else:
        bounds = [override_start, override_end]
        source = "manual"
    if not _valid_event_bounds(bounds):
        raise SplitInputError("需要系统检测或人工调整后的完整事件起止边界")
    start, end = float(bounds[0]), float(bounds[1])
    if start < 0 or end > float(bundle.duration):
        raise SplitInputError("有效事件区间必须落在真实信号时长内")
    return {
        "start": start,
        "end": end,
        "source": source,
        "buffer_seconds": float(buffer_seconds or 0.0),
    }


def validate_rules(
    *, window_seconds, stride_seconds, tail_policy: str
) -> tuple[float, float, str]:
    """校验秒级规则并返回规范化后的 `(window_seconds, stride_seconds, tail_policy)`。

    **按帧切分入口已废弃**（设计 §2.3：秒是唯一切分单位），故这里不再有单位换算——
    帧只作为界面上的派生展示。
    """
    try:
        window = float(window_seconds)
        stride = float(stride_seconds)
    except (TypeError, ValueError):
        raise SplitInputError("切片时长与步长必须是数字") from None
    if not math.isfinite(window) or not math.isfinite(stride):
        raise SplitInputError("切片时长与步长必须是有限数值")
    if window <= 0 or stride <= 0:
        raise SplitInputError("切片时长与步长必须大于 0")
    policy = str(tail_policy or "drop")
    if policy not in TAIL_POLICIES:
        raise SplitInputError(f"尾片策略只能是 {' / '.join(TAIL_POLICIES)}")
    return window, stride, policy


# ── 唯一的窗口算法 ───────────────────────────────────────────────────


def build_time_windows(
    *,
    duration: float,
    sample_rate: int,
    window_seconds: float,
    stride_seconds: float,
    event_bounds: tuple[float, float],
    tail_policy: str = "drop",
) -> list[SplitWindow]:
    """按**秒**计算窗口（设计 §3.2）——预览与 Job **共用的唯一实现**。

    ```text
    window_i.start = E_start + i × S
    window_i.end   = window_i.start + W
    ```

    仅当 `window_i.end <= E_end` 时产生完整窗口；`tail_policy="keep"` 时额外保留一个
    截到 `E_end` 的尾片（不等长）。窗口用半开区间 `[start, end)` 表示，避免相邻切片
    对边界资源重复归属。
    """
    if sample_rate <= 0:
        raise SplitInputError("真实时序信号缺少有效采样率")
    start, end = float(event_bounds[0]), float(event_bounds[1])
    if start < 0 or end <= start or end > duration + _EPS:
        raise SplitInputError("事件边界必须位于真实信号时长内，且结束时间大于开始时间")
    if window_seconds <= 0 or stride_seconds <= 0:
        raise SplitInputError("切片时长与步长必须大于 0")
    if end - start < window_seconds - _EPS:
        raise SplitInputError("有效事件区间短于一个切片窗口，无法生成切片")

    windows: list[SplitWindow] = []
    index = 0
    while True:
        w_start = start + index * stride_seconds
        w_end = w_start + window_seconds
        if w_end <= end + _EPS:
            windows.append(_window(len(windows) + 1, w_start, min(w_end, end), sample_rate, window_seconds))
        else:
            if tail_policy == "keep" and w_start < end - _EPS:
                windows.append(_window(len(windows) + 1, w_start, end, sample_rate, window_seconds))
            break
        index += 1
    return windows


def _window(index: int, start: float, end: float, sample_rate: int, window_seconds: float) -> SplitWindow:
    """按设计 §3.2 的取整口径由秒派生采样点下标（`ceil`，非四舍五入）。"""
    return SplitWindow(
        index=index,
        start=start,
        end=end,
        frame_start=math.ceil(start * sample_rate),
        frame_end=math.ceil(end * sample_rate),
        window_seconds=window_seconds,
    )


# ── 多模态样本包（设计 §3.3） ────────────────────────────────────────


def map_window_to_modalities(
    window: SplitWindow,
    *,
    mapping: dict,
    sample_rate: int,
    weld_id: str,
    version_id: int,
    crop_key: str | None = None,
    video_frame_key: str | None = None,
) -> dict:
    """经坐标映射为一个窗口生成样本包 manifest（**纯函数，不做 IO**）。

    这是唯一把"秒"换算到各模态坐标的地方：采样点由 `秒 × 采样率` 派生，视频帧号按
    `t_video = t_signal - offset` 换算，焊缝图片像素按弧长比例投影。任一模态越界即记
    `available=false` + reason，**不伪造内容**（设计 §3.2 末段）。
    """
    maps = mapping.get("mappings") or {}
    manifest = {
        "schema_version": 3,
        "sample_index": window.index,
        "time_range": {
            "start": round(window.start, 6),
            "end": round(window.end, 6),
            "duration": round(window.duration, 6),
        },
        "source": {
            "weld_id": weld_id,
            "version_id": version_id,
            "mapping_hash": mapping_hash(mapping),
        },
        "signal": {
            "available": True,
            "sample_rate": sample_rate,
            "start_index": window.frame_start,
            "end_index": window.frame_end,
            "channels": list(_TS_CHANNEL_IDS),
        },
        "video": _video_part(window, maps.get("video") or {}, video_frame_key),
        "seam_image": _seam_image_part(window, maps.get("seam_image") or {}, crop_key),
        "audio": {"available": False, "reason": "source_not_attached"},
    }
    return manifest


def representative_frame_time(window: SplitWindow, video: dict) -> float | None:
    """本段**代表帧**在信号轴上的时刻（默认取窗口中点）；落在视频覆盖范围外返回 None。

    **预览与正式产物共用这一处**——两处各写一份换算迟早会漂移，而它们本该是同一条规则：
    屏幕上看到的代表帧，就是样本里存下来的那一张。
    这里只回答"取哪一刻"（信号轴时刻）；`t_video = t_signal - offset` 的换算由
    `media_probe.analyze_video(..., seek_offset=)` 统一执行。
    """
    fps = video.get("fps")
    if not video.get("available") or not isinstance(fps, (int, float)) or fps <= 0:
        return None
    offset = float(video.get("offset_seconds") or 0.0)
    t_video = (window.start + window.end) / 2.0 - offset
    if t_video < 0.0:
        return None
    duration = video.get("duration")
    if isinstance(duration, (int, float)) and t_video >= float(duration) - _EPS:
        return None
    return (window.start + window.end) / 2.0


def _frame_part(window: SplitWindow, video: dict, frame_key: str | None) -> dict:
    """代表帧在 manifest 里的形状（**时间 + 帧号 + 对象键**，不含字节）。"""
    t_signal = representative_frame_time(window, video)
    if t_signal is None:
        return {
            "available": False,
            "reason": "代表帧（窗口中点）落在视频覆盖范围之外：本段视频内容只覆盖部分窗口",
        }
    offset = float(video.get("offset_seconds") or 0.0)
    fps = float(video["fps"])
    return {
        "available": True,
        "t_signal": round(t_signal, 6),
        "t_video": round(t_signal - offset, 6),
        "frame_no": int(max(0.0, t_signal - offset) * fps),
        "object_key": frame_key,
    }


def _video_part(window: SplitWindow, video: dict, frame_key: str | None = None) -> dict:
    """视频模态：`t_video = t_signal - offset`（设计 §3.1.1）。"""
    if not video.get("available"):
        reason = video.get("reason") or "无可用视频文件"
        return {"available": False, "reason": reason, "frame": {"available": False, "reason": reason}}
    fps = video.get("fps")
    if not isinstance(fps, (int, float)) or fps <= 0:
        reason = video.get("reason") or "视频帧率不可测"
        return {"available": False, "reason": reason, "frame": {"available": False, "reason": reason}}
    offset = float(video.get("offset_seconds") or 0.0)
    v_duration = video.get("duration")
    coverage_end = min(
        window.end - offset,
        float(v_duration) if isinstance(v_duration, (int, float)) else float("inf"),
    )
    if coverage_end <= _EPS or window.start - offset >= coverage_end - _EPS:
        # 整个窗口落在视频覆盖范围之外——该模态在本窗内缺失，不伪造帧号
        reason = "该时间窗落在视频覆盖范围之外"
        return {
            "available": False,
            "object_key": video.get("object_key"),
            "reason": reason,
            "frame": {"available": False, "reason": reason},
        }
    # 部分重叠时把起点钳到 0：不记不存在的负帧号
    start_frame = math.ceil(max(window.start - offset, 0.0) * fps)
    end_frame = math.ceil(coverage_end * fps)
    # 首/中/末三帧（设计 §4.4）；只保留换算到视频轴后**确实在覆盖范围内**的那些——
    # 抽不到的帧不该出现在 manifest 里，否则下游会以为有据可查。
    candidates = (window.start, (window.start + window.end) / 2, max(window.start, window.end - 1.0 / float(fps)))
    keyframes = [
        {"at": round(float(t), 6)}
        for t in candidates
        if 0.0 <= float(t) - offset < coverage_end - _EPS
    ]
    return {
        "available": True,
        "object_key": video.get("object_key"),
        "fps": float(fps),
        "calibrated": bool(video.get("calibrated")),
        "offset_seconds": offset,
        "start_frame": start_frame,
        "end_frame": max(start_frame, end_frame),
        "keyframes": keyframes,
        "frame": _frame_part(window, video, frame_key),
    }


def _seam_image_part(window: SplitWindow, seam: dict, crop_key: str | None) -> dict:
    """焊缝图片模态：沿 ROI 长边按弧长比例投影（设计 §3.1.2）。"""
    if not seam.get("available"):
        return {"available": False, "reason": seam.get("reason") or "无焊缝图片文件"}
    if seam.get("excluded"):
        # 用户明确选择「不对焊缝图片进行分段」（标定 `seam_image.excluded`）：样本里如实记
        # 不可用 + 原因。与"没框 ROI"是两件事——后者是未完成的标定，前者是已完成的决定。
        return {
            "available": False,
            "excluded": True,
            "object_key": seam.get("object_key"),
            "reason": seam.get("reason")
            or "已选择不对焊缝图片进行分段：该模态不参与样本",
        }
    roi = seam.get("roi")
    profile = seam.get("arc_profile")
    if not roi or not profile:
        return {
            "available": False,
            "object_key": seam.get("object_key"),
            "reason": seam.get("reason") or "焊缝图片未框选 ROI：无法建立长度↔时间映射",
        }
    # 延迟导入：`alignment` 依赖 `welds`/`signal_ingest`，模块级互相 import 会绕圈
    from app.services.alignment import position_ratio_at

    width = float(roi["w"])
    start_px = float(roi["x"]) + position_ratio_at(profile, window.start) * width
    end_px = float(roi["x"]) + position_ratio_at(profile, window.end) * width
    return {
        "available": True,
        "object_key": seam.get("object_key"),
        "roi": roi,
        "spatial_range": {"start_px": round(start_px, 3), "end_px": round(end_px, 3)},
        "speed_source": seam.get("speed_source"),
        "crop_key": crop_key,
    }


_TS_CHANNEL_IDS: tuple[str, ...] = ("cur", "vol", "gas", "wir")

#: 视频扩展名（与 `welds._VIDEO_EXTS` 同口径；这里不 import 私有常量）
_VIDEO_EXTS: tuple[str, ...] = (".mp4", ".mov", ".avi", ".mkv", ".webm")


def resolve_coordinate_mapping(session: Session, record, version, bundle) -> dict:
    """分段所需的坐标映射（设计 §5.3），**预览与 Job 共用**。

    **不下载视频**——fps/duration 取该焊缝**最近一次对齐任务**已探测并存下的元信息；
    从未对齐过则视频模态记不可用并给出原因，**不阻断分段**（§4.6）。

    标定与焊缝图片 ROI 每次都从 **v1.0 权威标定**现读，所以改完标定下次预览就生效、
    不必先重跑对齐；映射哈希随之变化，旧 `preview_token` 自然失效（§5.4）。
    """
    from app.services import alignment  # 延迟导入：alignment 依赖 welds/signal_ingest

    calibration = alignment.resolve_calibration(session, record)
    latest = alignment.latest_alignment_mapping(session, record) or {}
    stored_video = (latest.get("mappings") or {}).get("video") or {}
    fps = stored_video.get("fps")
    video_key = next(
        (key for key in (version.object_keys or []) if key.lower().endswith(_VIDEO_EXTS)),
        None,
    )
    return alignment.build_coordinate_mapping(
        bundle=bundle,
        events=bundle.events or {},
        calibration=calibration,
        has_scalar_speed=record.welding_speed is not None,
        video_key=video_key,
        video_meta={"duration": stored_video.get("duration"), "fps": fps} if fps else None,
        video_reason="视频元信息未知：该焊缝尚未运行对齐任务，无法确定帧率与时长",
        seam_image_key=alignment.seam_image_key(version.object_keys),
    )


# ── 哈希与预览令牌 ───────────────────────────────────────────────────


def rules_hash(rules: dict) -> str:
    """规则摘要（进 preview_token 与 manifest，用于"所见即所得"比对）。"""
    return _digest(rules)


def mapping_hash(mapping: dict | None) -> str:
    """映射摘要——标定或视频元信息一变，哈希就变，旧 token 随之失效。"""
    return _digest(mapping or {})


def _digest(payload) -> str:
    body = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]


def sign_preview_token(payload: dict) -> str:
    """把载荷签成短期令牌（HMAC-SHA256，无状态）。

    载荷自带 `expires_at`，服务端不需要存任何东西就能判过期与篡改。
    """
    body = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    sig = hmac.new(_token_secret(), body, hashlib.sha256).digest()
    return f"spv_{_b64(body)}.{_b64(sig)}"


def verify_preview_token(token: str) -> dict:
    """校验预览令牌并返回载荷；格式错/签名不符/过期一律抛 `SplitInputError`。"""
    if not isinstance(token, str) or not token.startswith("spv_"):
        raise SplitInputError("预览令牌格式不正确，请重新预览后再创建任务")
    try:
        body_b64, sig_b64 = token[4:].split(".", 1)
        body = _unb64(body_b64)
        signature = _unb64(sig_b64)
    except Exception as exc:  # noqa: BLE001 - 任何解码失败都归为格式错
        raise SplitInputError("预览令牌格式不正确，请重新预览后再创建任务") from exc
    expected = hmac.new(_token_secret(), body, hashlib.sha256).digest()
    if not hmac.compare_digest(signature, expected):
        raise SplitInputError("预览令牌校验失败，请重新预览后再创建任务")
    try:
        payload = json.loads(body.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise SplitInputError("预览令牌内容无法解析，请重新预览后再创建任务") from exc
    if float(payload.get("expires_at") or 0) < time.time():
        raise SplitInputError("预览已过期，请重新预览后再创建任务")
    return payload


def _token_secret() -> bytes:
    return (settings.secret_key or "change-me").encode("utf-8")


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


# ── 预览 ─────────────────────────────────────────────────────────────


def build_preview(
    *,
    bundle,
    mapping: dict,
    rules: dict,
    windows: list[SplitWindow],
    effective_range: dict,
    weld_id: str,
    version_id: int,
) -> dict:
    """组装 §5.3 的预览响应（**只读**，不创建任务、不写任何产物）。

    分层数据按 §6.4 设上限：时序 ≤1200 点/轨、视频缩略图 ≤80 张、图片投影带是单张照片
    加边界线（无额外分块请求）。媒体一律给对象键/短期签名 URL，**禁止把原始字节塞进 JSON**。
    """
    rules_digest = rules_hash(rules)
    cache_key = (version_id, rules_digest, mapping_hash(mapping))
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    start = float(effective_range["start"])
    end = float(effective_range["end"])
    overlap = max(0.0, float(rules["window_seconds"]) - float(rules["stride_seconds"]))
    payload = {
        # token 必须**自带完整规则**：创建端只收 token，凭它重建窗口（§5.4）。
        # 签名保证规则不可被客户端篡改，rules_hash 再兜一层"服务端读到的还是这套"。
        "preview_token": sign_preview_token({
            "weld_id": weld_id,
            "version_id": version_id,
            "rules": dict(rules),
            "rules_hash": rules_digest,
            "mapping_hash": mapping_hash(mapping),
            "event_bounds": [start, end],
            "expires_at": time.time() + PREVIEW_TOKEN_TTL_SECONDS,
        }),
        "rules": dict(rules),
        "rules_hash": rules_digest,
        "mapping_hash": mapping_hash(mapping),
        "effective_range": {"start": round(start, 6), "end": round(end, 6)},
        "window_seconds": float(rules["window_seconds"]),
        "stride_seconds": float(rules["stride_seconds"]),
        "overlap_seconds": round(overlap, 6),
        "overlap_ratio": round(overlap / float(rules["window_seconds"]), 6) if rules["window_seconds"] else 0.0,
        "tail_policy": rules["tail_policy"],
        "sample_count": len(windows),
        "windows": [
            _preview_window(w, mapping, bundle.sample_rate, weld_id, version_id)
            for w in windows
        ],
        "timeline": build_timeline_layers(bundle, mapping, start, end),
        "modalities": _preview_modalities(mapping),
        "warnings": preview_warnings(mapping, rules, windows),
    }
    _cache_put(cache_key, payload)
    return payload


def _preview_window(
    window: SplitWindow, mapping: dict, sample_rate: int, weld_id: str, version_id: int
) -> dict:
    """单个窗口的预览摘要——复用正式 manifest 的映射逻辑，保证"预览 == 产物"。"""
    manifest = map_window_to_modalities(
        window, mapping=mapping, sample_rate=sample_rate, weld_id=weld_id, version_id=version_id
    )
    return {
        "index": window.index,
        "start": round(window.start, 6),
        "end": round(window.end, 6),
        "duration": round(window.duration, 6),
        "signal": manifest["signal"],
        "video": manifest["video"],
        "seam_image": {k: v for k, v in manifest["seam_image"].items() if k != "crop_key"},
    }


def build_timeline_layers(bundle, mapping: dict, start: float, end: float) -> dict:
    """统一时间轴的分层数据（设计 §5.3）：事件、降采样时序、视频缩略图时间点、图片投影。

    公开给两处消费：分段页的 `split-preview`，以及标注页的 `annotation-timeline`——
    两页看到的时间轴必须由**同一段代码**产出，否则"标注时看到的边界"会与"预览时的边界"漂移。
    `start`/`end` 只决定波形取哪一段，调用方各自给（预览给有效区间，标注给样本的首尾）。
    """
    fs = int(bundle.sample_rate)
    i0 = max(0, math.ceil(start * fs))
    i1 = min(
        min((len(channel.values) for channel in bundle.channels), default=0),
        math.floor(end * fs),
    )
    tracks = []
    for channel in bundle.channels:
        values = channel.values[i0:i1] if i1 > i0 else channel.values[:0]
        idx = signals.downsample_indices(values, _PREVIEW_SIGNAL_POINTS) if len(values) else []
        tracks.append({
            "id": channel.id,
            "name": channel.name,
            "unit": channel.unit,
            "times": [round((i0 + int(i)) / fs, 6) for i in idx],
            "values": [round(float(values[int(i)]), 6) for i in idx],
        })

    video = mapping.get("mappings", {}).get("video") or {}
    thumb_times: list[float] = []
    if video.get("available") and isinstance(video.get("fps"), (int, float)) and video["fps"] > 0:
        offset = float(video.get("offset_seconds") or 0.0)
        # 只取落在视频覆盖范围内的时刻：缩略图取不到帧就没有意义
        v_lo = max(start - offset, 0.0) + offset
        v_hi = end
        v_duration = video.get("duration")
        if isinstance(v_duration, (int, float)):
            v_hi = min(v_hi, v_duration + offset)
        span = v_hi - v_lo
        if span > _EPS:
            count = min(_PREVIEW_VIDEO_THUMBS, max(1, int(span * float(video["fps"])) + 1))
            thumb_times = [
                round(v_lo + span * n / max(1, count - 1), 6) for n in range(count)
            ] if count > 1 else [round(v_lo, 6)]

    seam = mapping.get("mappings", {}).get("seam_image") or {}
    return {
        "duration": round(float(bundle.duration), 6),
        "events": bundle.events or {},
        "signal": {"sample_rate": fs, "tracks": tracks},
        "video_thumbnail_times": thumb_times,
        "seam_image_projection": {
            "available": bool(seam.get("available") and seam.get("roi") and not seam.get("excluded")),
            "excluded": bool(seam.get("excluded")),
            "object_key": seam.get("object_key"),
            "roi": seam.get("roi"),
            "speed_source": seam.get("speed_source"),
            "reason": seam.get("reason"),
        },
    }


def attach_preview_frames(
    payload: dict,
    *,
    storage,
    weld_id: str,
    mapping: dict,
    windows: list[SplitWindow],
) -> dict:
    """给预览的每个窗口挂上**本段自己的**视频代表帧短期 URL（原地改 `payload` 后返回）。

    预览**必须真的下视频抽帧**——"这一段画面长什么样"只有真帧能回答，占位渐变或全局首帧
    都是在骗人。**窗口有多少就抽多少**（不设段数上限）：视频覆盖范围内的每一段都要有自己的帧，
    按段截断等于让后半段凭空少一个模态。代价是一次预览要下视频 + 跑 N 次 ffmpeg。
    ① 对象键按（焊缝, 映射哈希, 段号）复用，重复预览覆盖同一批对象、不累积；
    ② 给的是**短期预签名 URL**，二进制不进 JSON；
    ③ **已有对象直接复用，不再重抽**——分段页每改一次规则就预览一次，全量重抽（45 段 = 一次
    下视频 + 45 次进程）会把页面拖到几十秒；对象既已按（映射哈希, 段号）落定，重抽只会得到
    同一张图。
    任一段抽不到/传不上去，就把该段的 `frame` 置不可用并写原因，**不伪造图片**。
    """
    from app.services import media_probe  # 延迟导入：ffmpeg 二进制探测较慢，预览非必然用到

    video = (mapping.get("mappings") or {}).get("video") or {}
    video_key = video.get("object_key")
    rows = payload.get("windows") or []
    if not video.get("available") or not video_key or not rows:
        return payload  # 窗口里的 frame 已由 _video_part 写明不可用原因

    kept = [
        (window, row)
        for window, row in zip(windows, rows)
        if (row.get("video") or {}).get("frame", {}).get("available")
    ]
    if not kept:
        return payload

    offset = float(video.get("offset_seconds") or 0.0)
    digest = mapping_hash(mapping)
    pending: list[tuple] = []
    for window, row in kept:
        key = _preview_frame_key(weld_id, digest, window.index)
        if _object_exists(storage, key):
            row["video"]["frame"]["object_key"] = key
            row["video"]["frame"]["url"] = storage.presign_get(key, expires=PREVIEW_FRAME_EXPIRES_SECONDS)
        else:
            pending.append((window, row))
    if not pending:
        return payload  # 全部命中：不下视频、不跑 ffmpeg

    try:
        data = storage.get_object(video_key)
        if len(data) > media_probe.MAX_VIDEO_PROBE_BYTES:
            raise ValueError(
                f"视频 {len(data) // (1024 * 1024)}MB 超过预览抽帧上限"
                f"（{media_probe.MAX_VIDEO_PROBE_BYTES // (1024 * 1024)}MB）"
            )
        _meta, frames = media_probe.analyze_video(
            data,
            [(str(window.index), float(row["video"]["frame"]["t_signal"])) for window, row in pending],
            seek_offset=offset,
        )
    except Exception as exc:  # noqa: BLE001 - 抽帧失败只影响代表帧，预览其余部分照常
        logger.warning("Preview video frame extraction failed for {}: {}", weld_id, exc)
        # 只改这次真的没抽到的段：命中复用的那些帧不能被一次失败连坐清掉
        for _window, row in pending:
            row["video"]["frame"] = {"available": False, "reason": f"预览抽帧失败：{exc}"}
        return payload

    extracted = {str(frame["event"]): frame for frame in frames}
    for window, row in pending:
        frame = row["video"]["frame"]
        got = extracted.get(str(window.index))
        if got is None:
            row["video"]["frame"] = {"available": False, "reason": "该时刻未能抽出视频帧"}
            continue
        key = _preview_frame_key(weld_id, digest, window.index)
        try:
            storage.upload_stream(key, io.BytesIO(got["bytes"]), len(got["bytes"]), "image/jpeg")
            frame["object_key"] = key
            frame["url"] = storage.presign_get(key, expires=PREVIEW_FRAME_EXPIRES_SECONDS)
        except Exception as exc:  # noqa: BLE001 - 同上：单段失败不拖垮预览
            logger.warning("Preview frame upload failed for {}#{}: {}", weld_id, window.index, exc)
            row["video"]["frame"] = {"available": False, "reason": f"代表帧上传失败：{exc}"}
    return payload


def _preview_frame_key(weld_id: str, digest: str, index: int) -> str:
    """预览代表帧的对象键：按（焊缝, 映射哈希, 段号）稳定，所以能当"已抽过"的判据。"""
    return f"processed/{weld_id}/split-preview/{digest}/{index:06d}.jpg"


def _object_exists(storage, key: str) -> bool:
    """对象是否已存在且非空（`stat_object` 只取元数据，不拉字节）。

    判定不了（存储不支持 stat / 网络抖动）一律按"不存在"处理——多抽一次只是慢，
    拿一张不存在的图的 URL 去渲染是错。长度为 0 的对象当不存在：空 JPEG 本来就渲染不出来。
    """
    try:
        return storage.stat_object(key) > 0
    except Exception:  # noqa: BLE001
        return False


def _preview_modalities(mapping: dict) -> dict:
    """各模态的可用性、标定状态与原因（供预览页只读展示；标定不可在此编辑）。"""
    maps = mapping.get("mappings") or {}
    return {
        key: {
            "available": bool(value.get("available")),
            "calibrated": bool(value.get("calibrated")),
            "excluded": bool(value.get("excluded")),
            "reason": value.get("reason"),
            "speed_source": value.get("speed_source"),
        }
        for key, value in maps.items()
    }


def preview_warnings(mapping: dict, rules: dict, windows: list[SplitWindow]) -> list[str]:
    """不阻断、但用户必须知晓的问题（设计 §4.6）。"""
    warnings: list[str] = []
    maps = mapping.get("mappings") or {}
    video = maps.get("video") or {}
    if video.get("available") and not video.get("calibrated"):
        warnings.append("视频时间零点未标定：关键帧按视频与信号同零点的假设抽取，请前往对齐页标定。")
    if not video.get("available"):
        warnings.append(f"视频模态不可用：{video.get('reason') or '无可用视频文件'}。分段仍可继续。")
    seam = maps.get("seam_image") or {}
    if seam.get("excluded"):
        warnings.append("焊缝图片已选择不参与分段：本次只生成时序/视频样本。")
    elif seam.get("available") and not seam.get("calibrated"):
        warnings.append("焊缝图片未框选 ROI：该模态在样本中标记为不可用，请前往对齐页标定。")
    if not seam.get("excluded"):
        if seam.get("speed_source") == "scalar":
            warnings.append("焊缝图片按焊接速度稳态中位数映射，未使用逐点速度。")
        elif seam.get("speed_source") == "none":
            warnings.append("焊缝图片未使用真实焊接速度，按时间比例映射。")
    overlap = float(rules["window_seconds"]) - float(rules["stride_seconds"])
    if overlap > _EPS:
        ratio = overlap / float(rules["window_seconds"]) * 100
        warnings.append(f"步长小于时长，相邻切片重叠 {overlap:.2f} 秒（{ratio:.0f}%）。")
    if rules.get("tail_policy") == "keep" and windows and windows[-1].duration < float(rules["window_seconds"]) - _EPS:
        warnings.append(f"已保留不等长尾片（{windows[-1].duration:.2f} 秒）。")
    return warnings


def _cache_get(key: tuple):
    hit = _PREVIEW_CACHE.get(key)
    if hit is None:
        return None
    stamped, payload = hit
    if time.time() - stamped > _PREVIEW_CACHE_TTL:
        _PREVIEW_CACHE.pop(key, None)
        return None
    return payload


def _cache_put(key: tuple, payload: dict) -> None:
    # ponytail: 无上限增长；预览缓存键随(版本,规则,映射)组合增长，条目很小且 TTL 60s，
    # 真出现无界增长再加 LRU 上限。
    _PREVIEW_CACHE[key] = (time.time(), payload)


# ── 产物（供 Job 使用） ──────────────────────────────────────────────


def signal_window_csv(bundle, window: SplitWindow) -> bytes:
    """将真实信号窗口序列化为可校验 CSV。"""
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    channel_map = {channel.id: channel for channel in bundle.channels}
    writer.writerow(["time", "current", "voltage", "gas", "wire"])
    for offset in range(window.frame_end - window.frame_start):
        idx = window.frame_start + offset
        values = [channel_map[key].values[idx] for key in ("cur", "vol", "gas", "wir")]
        writer.writerow([f"{window.start + offset / bundle.sample_rate:.6f}", *[f"{float(v):.9g}" for v in values]])
    return output.getvalue().encode("utf-8")


def _valid_event_bounds(value) -> bool:
    return (
        isinstance(value, (list, tuple))
        and len(value) == 2
        and all(isinstance(item, (int, float)) and not isinstance(item, bool) for item in value)
        and float(value[1]) > float(value[0])
    )
