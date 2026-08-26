"""确定性信号生成（Task 11）：按 weld_id 生成 4 通道焊接时序信号。

形态复刻 `src/App.tsx` 的 `currentAmp/voltVal/gasVal/wireVal`（起弧 ramp →
稳态 → 收弧 ramp + 两个异常区段低频正弦噪声），采样点数 = duration × sample_rate
（默认 5.42 s × 1000 Hz = 5420 点）。数值被裁剪到各通道量程，与 App.tsx clamp 一致。

事件/异常（与 App.tsx AdvancedWeldAnalysis 一致）：
- events: `{arc:0.42, weld_segment:[0.78,4.28], tail:4.86}`
- anomalies: `[{1.92,2.34,电弧不稳}, {3.58,3.86,飞溅倾向}]`

确定性（坑）：
- 种子 = `zlib.crc32(weld_id)`——**不要用内置 `hash(weld_id)`**：Python 对 str 的
  `hash()` 每次进程启动随机（PYTHONHASHSEED 盐），跨进程/跨运行不可复现。
  crc32 是内容确定的，保证同焊缝每次运行结果一致、测试稳定。
- 种子用于生成该焊缝特有的噪声增益（0.9~1.1）与正弦相位偏移：不同焊缝波形
  形态相同但细节不同，同焊缝完全可复现。
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass, field

import numpy as np

#: 4 通道规格（id/name/unit/量程，对齐 App.tsx channels 常量）。
#: 量程按真实焊接范围放宽（Task 18 数据导入实测：MAG 短路过渡电流峰值 ~530A、
#: 电压峰值 ~70V，超出原演示档 300A/40V）。R5 量程校验与启发式阈值均以此 span 推导，
#: 前端 y 轴经 channel.lo/hi 读取——改这里会同时影响导入校验、事件检测与图表量程。
CHANNEL_SPECS: list[dict] = [
    {"id": "cur", "name": "电流", "unit": "A", "lo": 0.0, "hi": 600.0},
    {"id": "vol", "name": "电压", "unit": "V", "lo": 0.0, "hi": 80.0},
    {"id": "gas", "name": "气体流量", "unit": "L/min", "lo": 0.0, "hi": 60.0},
    {"id": "wir", "name": "送丝速度", "unit": "m/min", "lo": 0.0, "hi": 20.0},
]

#: 焊接事件时间点（s），对齐 App.tsx。
DURATION: float = 5.42
ARC: float = 0.42
WELD_S: float = 0.78
WELD_E: float = 4.28
TAIL: float = 4.86
EVENTS: dict = {
    "arc": ARC,
    "weld_segment": [WELD_S, WELD_E],
    "tail": TAIL,
}
ANOMALIES: list[dict] = [
    {"start": 1.92, "end": 2.34, "type": "电弧不稳"},
    {"start": 3.58, "end": 3.86, "type": "飞溅倾向"},
]


@dataclass
class Channel:
    """单通道信号：values 为 ndarray；lo/hi 量程；mean 为实际均值。"""

    id: str
    name: str
    unit: str
    values: np.ndarray
    lo: float
    hi: float
    mean: float


@dataclass
class SignalBundle:
    """一次生成的完整信号集（4 通道 + 事件 + 异常区段）。

    `source`：`generated`（确定性合成）或 `real`（从导入的真实信号 Parquet 还原）。
    """

    weld_id: str
    duration: float
    sample_rate: int
    channels: list[Channel]
    events: dict = field(default_factory=lambda: dict(EVENTS))
    anomalies: list[dict] = field(default_factory=lambda: list(ANOMALIES))
    source: str = "generated"  # generated | real

    def channel(self, channel_id: str) -> Channel | None:
        return next((c for c in self.channels if c.id == channel_id), None)


def generate_signals(weld_id: str, sample_rate: int = 1000) -> SignalBundle:
    """按 weld_id 确定性生成 4 通道信号（形态复刻 App.tsx）。

    采样点数 = `int(duration × sample_rate)`，t = `linspace(0, duration, n)`。
    返回 `SignalBundle`（values 为 ndarray，序列化由路由 `.tolist()` 处理）。
    """
    rng = np.random.default_rng(_seed(weld_id))
    noise_gain = float(0.9 + 0.2 * rng.random())  # 每焊缝噪声幅度 0.9~1.1
    phi = float(2 * np.pi * rng.random())          # 每焊缝正弦相位偏移

    n = int(DURATION * sample_rate)
    t = np.linspace(0, DURATION, n)
    is_arc, is_weld, is_tail = _segments(t)
    is_anom = _anomaly_mask(t)

    values = {
        "cur": _current_amp(t, is_arc, is_weld, is_tail, is_anom, noise_gain, phi),
        "vol": _volt_val(t, is_arc, is_weld, is_tail, is_anom, noise_gain, phi),
        "gas": _gas_val(t, is_arc, is_tail, is_anom, noise_gain, phi),
        "wir": _wire_val(t, is_arc, is_tail, is_anom, noise_gain, phi),
    }
    channels = [
        Channel(
            id=spec["id"],
            name=spec["name"],
            unit=spec["unit"],
            values=values[spec["id"]],
            lo=spec["lo"],
            hi=spec["hi"],
            mean=round(float(np.mean(values[spec["id"]])), 2),
        )
        for spec in CHANNEL_SPECS
    ]
    return SignalBundle(
        weld_id=weld_id,
        duration=DURATION,
        sample_rate=int(sample_rate),
        channels=channels,
    )


def analysis_result(bundle: SignalBundle) -> dict:
    """模拟分析结果（确定性，源自信号生成器的事件/异常区段）。

    返回 `{stability, segments:{normal, arc_instability, sputter}, anomalies}`：
    - stability = 100 − 异常时长占比×25% 权重 − 小幅确定性抖动（演示值 ≈ 96.8）；
    - segments 由异常区段时长占全程比例算出（`seeded by weld_id` 的抖动同样复现）。
    """
    rng = np.random.default_rng(_seed(bundle.weld_id))
    dur = bundle.duration
    anomalies = [
        {"start": a["start"], "end": a["end"], "type": a["type"]}
        for a in bundle.anomalies
    ]
    total_anom = sum(a["end"] - a["start"] for a in anomalies)
    anom_frac = (total_anom / dur) if dur > 0 else 0.0

    stability = round(
        max(0.0, min(100.0, 100 - anom_frac * 100 * 0.25 + float(rng.uniform(-0.4, 0.4)))),
        2,
    )
    if len(anomalies) >= 2:
        arc_pct = round((anomalies[0]["end"] - anomalies[0]["start"]) / dur * 100, 2)
        sputter_pct = round((anomalies[1]["end"] - anomalies[1]["start"]) / dur * 100, 2)
    else:
        arc_pct = sputter_pct = 0.0
    normal_pct = round(max(0.0, 100 - arc_pct - sputter_pct), 2)

    return {
        "stability": stability,
        "segments": {
            "normal": normal_pct,
            "arc_instability": arc_pct,
            "sputter": sputter_pct,
        },
        "anomalies": anomalies,
    }


# ── 内部实现（复刻 App.tsx 信号形态）───────────────────────────────────


def _seed(weld_id: str) -> int:
    """稳定种子：内容确定的 crc32，跨进程可复现（勿换内置 hash()）。"""
    return zlib.crc32(str(weld_id).encode("utf-8"))


def _segments(t: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """起弧 / 有效焊接段 / 收弧 布尔掩码。"""
    is_arc = t < ARC
    is_weld = (t >= WELD_S) & (t <= WELD_E)
    is_tail = t > TAIL
    return is_arc, is_weld, is_tail


def _anomaly_mask(t: np.ndarray) -> np.ndarray:
    """两个异常区段并集的布尔掩码。"""
    mask = np.zeros(t.shape, dtype=bool)
    for a in ANOMALIES:
        mask |= (t >= a["start"]) & (t <= a["end"])
    return mask


def _current_amp(t, is_arc, is_weld, is_tail, is_anom, gain, phi):
    b = np.full(t.shape, 180.0)
    b[is_arc] = 60 + (t[is_arc] / ARC) * 130
    b[is_tail] = 150 - (t[is_tail] - TAIL) * 90
    noise = (
        np.where(is_anom, np.sin(t * 47 + phi) * 22, np.sin(t * 25 + phi) * 7)
        + np.where(is_anom, np.cos(t * 31 + phi) * 16, np.cos(t * 18 + phi) * 4)
    ) * gain
    drip = np.sin(t * 38 + phi) * np.where(is_weld, 11.0, 0.0)
    return np.clip(b + noise + drip, 0, 300)


def _volt_val(t, is_arc, is_weld, is_tail, is_anom, gain, phi):
    b = np.full(t.shape, 22.4)
    b[is_arc] = 14 + (t[is_arc] / ARC) * 9
    b[is_tail] = 22 - (t[is_tail] - TAIL) * 12
    noise = (
        np.where(is_anom, np.sin(t * 53 + phi) * 3.4, np.sin(t * 22 + phi) * 0.9)
        + np.where(is_anom, np.cos(t * 29 + phi) * 2.6, np.cos(t * 16 + phi) * 0.6)
    ) * gain
    return np.clip(b + noise, 0, 40)


def _gas_val(t, is_arc, is_tail, is_anom, gain, phi):
    b = np.full(t.shape, 18.0)
    b[is_arc] = 12 + (t[is_arc] / ARC) * 6
    b[is_tail] = 18 - (t[is_tail] - TAIL) * 5
    noise = np.where(is_anom, np.sin(t * 13 + phi) * 2.4, np.cos(t * 7 + phi) * 0.6) * gain
    b = b + noise * ~(is_arc | is_tail)  # gas 的噪声只在非起弧/收弧分支
    return np.clip(b, 0, 30)


def _wire_val(t, is_arc, is_tail, is_anom, gain, phi):
    b = np.full(t.shape, 7.0)
    b[is_arc] = 3 + (t[is_arc] / ARC) * 4
    b[is_tail] = 7 - (t[is_tail] - TAIL) * 5
    noise = np.where(is_anom, np.sin(t * 19 + phi) * 1.6, np.cos(t * 11 + phi) * 0.4) * gain
    b = b + noise * ~(is_arc | is_tail)
    return np.clip(b, 0, 12)
