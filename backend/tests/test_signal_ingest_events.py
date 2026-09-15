"""`detect_events` 焊接段提取回归（纯函数，不连 DB/存储）。

背景：短路过渡 MAG 的电流纹波让平滑电流每隔几十毫秒短暂跌破阈值，`active` 掩码被
≤5ms 的空隙切碎。旧实现直接取"最长连续 active 段"，于是真实 CSV（16.2s、fs≈2064）
被切成 265 段、最长仅 0.142s —— 页面「有效焊接段」显示 0.13s、后半段整段没有标记。
修复后先合并间隔 < 100ms 的相邻段再取最长。
"""

import numpy as np
import pandas as pd

from app.services import signal_ingest as svc

_CM = {"time": "time", "cur": "current"}


def _rippled_weld_df(
    fs: int = 1000,
    idle_s: float = 2.0,
    weld_s: float = 5.0,
    tail_idle_s: float = 2.0,
    ripple_hz: float = 20.0,
) -> pd.DataFrame:
    """idle → 焊接段（每 1/ripple_hz 秒跌破阈值 4ms）→ idle。

    idle 电流 30A、焊接段 250A 带 ±12A 纹波；每 50ms 插入 4ms 的 40A 陷波，
    复刻短路过渡纹波对阈值判定的切碎效果。
    """
    n = int((idle_s + weld_s + tail_idle_s) * fs)
    t = np.arange(n) / fs
    x = np.full(n, 30.0)
    weld = (t >= idle_s) & (t < idle_s + weld_s)
    x[weld] = 250.0 + 12.0 * np.sin(2 * np.pi * 300 * t[weld])
    period = max(1, round(fs / ripple_hz))
    notch = np.where((np.arange(n) % period) < max(1, round(fs * 0.004)))[0]
    x[np.intersect1d(notch, np.where(weld)[0])] = 40.0
    return pd.DataFrame({"time": t, "current": x})


def test_detect_events_merges_short_ripple_gaps():
    df = _rippled_weld_df()
    events, _ = svc.detect_events(df, _CM, 1000)

    w0, w1 = events["weld_segment"]
    # 修复前：最长段只有 4ms（陷波间隔）→ 焊接段时长 ≈ 0
    assert w1 - w0 > 4.0, f"焊接段被纹波切碎: {events}"
    assert abs(w0 - 2.0) < 0.1 and abs(w1 - 7.0) < 0.1, f"焊接段边界失准: {events}"
    assert abs(events["arc"] - 2.0) < 0.1  # 起弧 = leading idle 结束处
    assert events["tail"] > 7.0


def test_merge_runs_keeps_far_apart_segments_separate():
    """间隔 ≥ 容差的段不得被合并（两条焊缝不能粘成一条）。"""
    merged = svc._merge_runs([(0, 10), (20, 30), (1000, 1010)], gap=100)
    assert merged == [(0, 30), (1000, 1010)]
