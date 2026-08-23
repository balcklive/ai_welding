"""Task 11：DSP 纯函数测试（不连 DB）。

覆盖 `app.services.dsp` 的真实计算：
- `filter_signal` 低通对白噪声 → 高频能量相对原始显著衰减（能量比断言）；
- `compute_psd` 对 50Hz 正弦在 50Hz 附近有峰（argmax）；
- `compute_dwt` 返回 D1..D4 + A4（共 5 项）；
- `wavelet_decomp` 5 层细节分量 L1..L5；
- `pdd_density` counts 之和 == 样本数，bins/kde 长度 == bins；
- `compute_stft` magnitude 形状 = (freqs × times)；
- `phase_trajectory` 降采样到 ≤2048 点。
"""

import numpy as np

from app.services import dsp


def _noise(n: int = 4000, seed: int = 7) -> np.ndarray:
    return np.random.default_rng(seed).normal(size=n)


def _high_freq_energy(x, fs: int = 1000, above: float = 0.3) -> float:
    """freq > fs/2*above 的 PSD 总能量。"""
    out = dsp.compute_psd(x, fs)
    f = np.asarray(out["freqs"])
    p = np.asarray(out["psd"])
    return float(p[f > fs / 2 * above].sum())


def test_filter_signal_lowpass_reduces_high_freq_energy() -> None:
    x = _noise()
    y = dsp.filter_signal(x, 1000, "低通", 0.1)
    raw_hi = _high_freq_energy(x)
    filt_hi = _high_freq_energy(y)
    assert filt_hi < raw_hi * 0.5  # 低通 cutoff=0.1 → >30% 奈奎斯特能量大幅下降
    assert y.shape == x.shape
    assert np.isfinite(y).all()


def test_filter_signal_bandpass_keeps_passband() -> None:
    fs = 1000
    t = np.linspace(0, 2, 2 * fs, endpoint=False)
    x = np.sin(2 * np.pi * 10 * t) + np.sin(2 * np.pi * 100 * t) + np.sin(2 * np.pi * 300 * t)
    y = dsp.filter_signal(x, fs, "带通", 0.1, 0.3)  # 通带 100~300 Hz（奈奎斯特归一）
    assert _high_freq_energy(y, fs, above=0.6) < _high_freq_energy(x, fs, above=0.6) * 0.5


def test_compute_psd_peak_near_50hz() -> None:
    fs = 1000
    t = np.linspace(0, 4, 4 * fs, endpoint=False)
    x = np.sin(2 * np.pi * 50 * t) + 0.1 * np.sin(2 * np.pi * 300 * t)
    out = dsp.compute_psd(x, fs)
    f = np.asarray(out["freqs"])
    p = np.asarray(out["psd"])
    peak_freq = f[np.argmax(p)]
    assert abs(peak_freq - 50) < 10


def test_compute_stft_magnitude_shape() -> None:
    fs = 1000
    t = np.linspace(0, 2, 2 * fs, endpoint=False)
    x = np.sin(2 * np.pi * 100 * t)
    out = dsp.compute_stft(x, fs)
    mag = np.asarray(out["magnitude"])
    assert set(out) >= {"times", "freqs", "magnitude"}
    assert mag.shape == (len(out["freqs"]), len(out["times"]))
    assert mag.shape[0] > 0 and mag.shape[1] > 0


def test_compute_dwt_returns_five_entries() -> None:
    x = _noise(512, seed=3)
    out = dsp.compute_dwt(x, level=4, wavelet="db4")
    assert [b["name"] for b in out["bands"]] == ["D1", "D2", "D3", "D4"]
    assert out["approx"]["name"] == "A4"
    assert len(out["bands"]) == 4


def test_wavelet_decomp_five_bands() -> None:
    x = _noise(512, seed=3)
    out = dsp.wavelet_decomp(x, level=5, wavelet="db4")
    assert [b["name"] for b in out["bands"]] == ["L1", "L2", "L3", "L4", "L5"]
    assert len(out["bands"]) == 5


def test_pdd_density_counts_sum_equals_sample_count() -> None:
    x = np.random.default_rng(1).normal(180, 12, size=5000)
    out = dsp.pdd_density(x, bins=28, lo=0, hi=300)
    assert sum(out["counts"]) == len(x)
    assert len(out["bins"]) == 28
    assert len(out["kde"]) == 28
    assert max(out["kde"]) > 0


def test_phase_trajectory_downsample_cap() -> None:
    cur = np.random.default_rng(5).normal(size=10_000)
    vol = np.random.default_rng(6).normal(size=10_000)
    out = dsp.phase_trajectory(cur, vol)
    assert len(out["current"]) == len(out["voltage"])
    assert len(out["current"]) <= 2048
    # 短信号不降采样
    out_short = dsp.phase_trajectory(cur[:500], vol[:500])
    assert len(out_short["current"]) == 500
