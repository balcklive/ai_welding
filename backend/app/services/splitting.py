"""生产样本分段规则与输入校验。

该模块是预览接口和异步执行器共同使用的唯一规则入口。只接受成功导入的真实
时序信号；不生成默认时长、默认事件或合成样本。
"""

from __future__ import annotations

import csv
import io
import math
from dataclasses import dataclass

from sqlmodel import Session

from app.models.data import DataRecord, DataVersion
from app.services import signal_ingest


class SplitInputError(ValueError):
    """输入不满足生产分段前置条件。"""


#: 切分规则版本（T10）：1 = 旧口径「帧 = 采样点」（历史任务的 rules 里没有这个键，按 1 解释），
#: 2 = **秒是唯一基准**（帧只作为界面单位，换算经视频帧率）。写进 `rules` 与切片 `meta`，
#: 供 D16-A 区分新旧切片。
RULES_VERSION = 2


@dataclass(frozen=True)
class SplitWindow:
    """一个切片窗口。

    **`frame_start` / `frame_end` 是信号采样点下标**（字段名是历史遗留，勿按视频帧理解）——
    视频帧号另记在切片 meta 的 `video_frame_no`（取窗口中点换算）。
    """

    index: int
    start: float
    end: float
    frame_start: int
    frame_end: int
    window_seconds: float = 0.0


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


def resolve_rule_seconds(
    *,
    unit: str,
    window_value: float,
    stride_value: float,
    video_fps: float | None,
    sample_rate: int,
) -> tuple[float, float]:
    """把界面上的切分规则换算成**秒**（T10：唯一基准），返回 `(window_seconds, stride_seconds)`。

    **换算只在这一个函数里做**——预览接口与任务接口共用，否则会出现"预览 207、执行 8 万"。

    - `unit="second"`：直接就是秒；
    - `unit="frame"`：必须能拿到视频帧率（`秒 = 帧数 ÷ fps`）；拿不到就报错而不是猜默认值
      （无视频时"帧"没有意义，见 D15）。
    """
    if unit not in ("frame", "second"):
        raise SplitInputError("切分单位只能是 frame（帧）或 second（秒）")
    if window_value <= 0 or stride_value <= 0:
        raise SplitInputError("切片时长与步长必须大于 0")
    if unit == "frame":
        if not video_fps or video_fps <= 0:
            raise SplitInputError(
                "按帧切分需要可用的视频帧率：当前版本没有视频，或帧率探测失败。请改用按秒切分"
            )
        return window_value / video_fps, stride_value / video_fps
    return float(window_value), float(stride_value)


def build_windows(
    *,
    duration: float,
    sample_rate: int,
    window_seconds: float,
    stride_seconds: float,
    event_bounds: tuple[float, float],
) -> list[SplitWindow]:
    """按**秒**计算窗口，采样点由 `秒 × 采样率` 四舍五入推导（T10）。

    **只保留完整窗口**（丢弃不足一个窗口的尾片，D20）：切片采样点数一致，训练侧不用处理不等长。
    非整数帧率（如 29.97）时，秒数由 `帧数 ÷ fps` 得到，不做整数截断，避免累积漂移。
    """
    window_samples = max(1, round(window_seconds * sample_rate))
    stride_samples = max(1, round(stride_seconds * sample_rate))
    start, end = event_bounds
    if start < 0 or end <= start or end > duration:
        raise SplitInputError("事件边界必须位于真实信号时长内，且结束时间大于开始时间")
    total_samples = max(0, math.floor((end - start) * sample_rate))
    if total_samples < window_samples:
        raise SplitInputError("有效事件区间短于一个切片窗口，无法生成切片")
    count = 1 + (total_samples - window_samples) // stride_samples
    return [
        SplitWindow(
            index=i + 1,
            start=start + (i * stride_samples) / sample_rate,
            end=min(end, start + (i * stride_samples + window_samples) / sample_rate),
            frame_start=math.floor(start * sample_rate) + i * stride_samples,
            frame_end=math.floor(start * sample_rate) + i * stride_samples + window_samples,
            window_seconds=window_seconds,
        )
        for i in range(count)
    ]


def event_bounds(
    bundle,
    override_start: float | None,
    override_end: float | None,
    buffer_seconds: float = 0.0,
) -> tuple[float, float]:
    default = (bundle.events or {}).get("weld_segment")
    if override_start is None and override_end is None:
        if not _valid_event_bounds(default):
            bounds = default
        else:
            bounds = [
                max(0.0, float(default[0]) - max(0.0, buffer_seconds)),
                min(float(bundle.duration), float(default[1]) + max(0.0, buffer_seconds)),
            ]
    else:
        bounds = [override_start, override_end]
    if not _valid_event_bounds(bounds):
        raise SplitInputError("需要系统检测或人工调整后的完整事件起止边界")
    return float(bounds[0]), float(bounds[1])


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
