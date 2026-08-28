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


@dataclass(frozen=True)
class SplitWindow:
    index: int
    start: float
    end: float
    frame_start: int
    frame_end: int


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


def build_windows(
    *, duration: float, sample_rate: int, window_frames: int, stride_frames: int,
    event_bounds: tuple[float, float],
) -> list[SplitWindow]:
    if window_frames < 1 or stride_frames < 1:
        raise SplitInputError("窗口长度和步长必须为大于 0 的整数采样点")
    start, end = event_bounds
    if start < 0 or end <= start or end > duration:
        raise SplitInputError("事件边界必须位于真实信号时长内，且结束时间大于开始时间")
    total_frames = max(0, math.floor((end - start) * sample_rate))
    if total_frames < window_frames:
        raise SplitInputError("有效事件区间短于一个样本窗口，无法生成生产样本")
    count = 1 + (total_frames - window_frames) // stride_frames
    return [
        SplitWindow(
            index=i + 1,
            start=start + (i * stride_frames) / sample_rate,
            end=min(end, start + (i * stride_frames + window_frames) / sample_rate),
            frame_start=math.floor(start * sample_rate) + i * stride_frames,
            frame_end=math.floor(start * sample_rate) + i * stride_frames + window_frames,
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
