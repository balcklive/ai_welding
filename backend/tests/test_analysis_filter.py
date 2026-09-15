"""滤波口径回归（`app.api.v1.analysis`）。

背景：起收弧识别页的截止频率滑杆曾把**归一化频率**当 Hz 显示（`cutoff × 1000`，
0.30 → “300 Hz”），而 `cutoff` 是**相对奈奎斯特 fs/2** 的归一化频率
（fs=5000 → 0.30 = 750 Hz；fs=20000 → 0.30 = 3000 Hz）。换算：`Hz = cutoff × fs/2`。

滤波后信号均值/幅度都会变，因此：
- `GET …/signals`（带 filter）与 PDD 直方图的 `lo/hi/mean` 必须按**滤波后**序列重算
  （`_series_range`），否则高通信号会被按原始量程（电流 0–600）画成贴边直线、
  PDD 全部挤进首 bin。
"""

import numpy as np

from app.api.v1.analysis import _filter_error, _series_range
from app.services import dsp


def test_series_range_recenters_highpass_signal() -> None:
    """fs=5000、高通 0.30（=750 Hz）→ 去均值后的量程必须跨 0，而非沿用 0–600。"""
    fs = 5000
    t = np.linspace(0, 4, 4 * fs, endpoint=False)
    raw = 180.0 + np.sin(2 * np.pi * 20 * t) + np.sin(2 * np.pi * 300 * t)
    filt = dsp.filter_signal(raw, fs, "高通", 0.30)
    lo, hi, mean = _series_range(filt)
    assert lo < 0 < hi  # 原始量程 0–600 对滤波后信号完全不适用
    assert lo <= float(np.min(filt)) and hi >= float(np.max(filt))
    assert abs(mean - float(np.mean(filt))) < 0.01


def test_series_range_handles_constant_and_empty_signal() -> None:
    """常值/空序列必须给可绘制量程（防除零），不留 inf/nan。"""
    for values in ([7.0, 7.0, 7.0], []):
        lo, hi, mean = _series_range(values)
        assert np.isfinite([lo, hi, mean]).all()
        assert hi > lo


def test_filter_error_rejects_out_of_range_and_reversed_band() -> None:
    """归一化频率必须落在 (0,1) 且带通 cutoff < cutoff2（前端滑杆据此兜底）。"""
    assert _filter_error("低通", 0.3, None) is None
    assert _filter_error("带通", 0.3, 0.6) is None
    assert _filter_error("低通", 1.0, None) is not None
    assert _filter_error("带通", 0.6, 0.3) is not None
    assert _filter_error("带通", 0.3, None) is not None
    assert _filter_error("陷波", 0.3, None) is not None
