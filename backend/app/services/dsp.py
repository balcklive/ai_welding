"""真实 DSP 服务（Task 11）：信号滤波与频谱/时频/小波分析。

全部为纯函数，输入 `numpy` 数组 + 采样率，输出 JSON 安全的 Python 结构
（numpy → list 一律走 `.tolist()`）。实现边界（`docs/开发规范.md` §3.1）：
分析必须是**真实计算**（scipy / PyWavelets / numpy），不是罐头数字。

契约对齐 `docs/API接口清单.md` §3.4（`GET …/analysis/{mode}`）。

关键约定（坑/边界，改这里时勿破坏）：
- `cutoff`/`cutoff2` 为 **0~1 的归一化频率（相对奈奎斯特 fs/2）**，与 scipy
  `butter` 不传 fs 的默认约定一致；`带通` 需同时给 `cutoff < cutoff2`。
- 滤波统一 `butter(4, …)` + `sosfiltfilt`（零相位，无相位失真），
  要求输入 ≥ 30 点（sosfiltfilt 默认 padlen ≈ 15，需 `len > 2*padlen`）。
- DWT 用 `pywt.wavedec(x, wavelet, level)`：返回 `[cA_n, cD_n, …, cD_1]`，
  即 `coeffs[0]` 是最末层近似、`coeffs[level]` 是最细层细节 D1。
  输出按 D1→Dn（高频→低频）排序，与 App.tsx DwtChart/WaveletDecomp 展示一致。
- `phase_trajectory` 降采样到 ≤2048 点（UI 相图绘制量级）。
- `pdd_density` 复刻 App.tsx PddChart 的直方图 + 高斯核密度
  （kde[i] = Σ_j counts[j]·exp(-((i-j)/3.5)²)，相对尺度即可，前端按 max 归一化）。
"""

from __future__ import annotations

import numpy as np
import pywt
from scipy.signal import butter, sosfiltfilt, stft, welch

#: 支持的滤波类型（与前端 filterTypes 逐字一致）。
FILTER_KINDS: tuple[str, ...] = ("低通", "高通", "带通")


def filter_signal(x, fs: float, kind: str, cutoff: float, cutoff2: float | None = None) -> np.ndarray:
    """零相位 Butterworth 滤波（低通/高通/带通）。

    - `kind` ∈ 低通|高通|带通；`cutoff`（带通时还有 `cutoff2`）为 0~1 归一化频率
      （相对奈奎斯特频率），需满足 0 < cutoff < 1、带通时 cutoff < cutoff2 < 1。
    - 返回与输入等长的滤波后 ndarray。
    """
    x = np.asarray(x, dtype=float)
    if x.ndim != 1 or x.size < 31:
        raise ValueError("Filtering requires a one-dimensional signal with at least 31 samples")
    if kind not in FILTER_KINDS:
        raise ValueError(f"kind must be one of {'/'.join(FILTER_KINDS)}; got {kind!r}")
    if cutoff is None or not 0 < float(cutoff) < 1:
        raise ValueError("cutoff must be in the range (0, 1)")
    if kind == "带通":
        if cutoff2 is None or not 0 < float(cutoff2) < 1:
            raise ValueError("Band-pass filtering requires cutoff2 in the range (0, 1)")
        if float(cutoff) >= float(cutoff2):
            raise ValueError("cutoff must be less than cutoff2")
        sos = butter(4, [float(cutoff), float(cutoff2)], btype="bandpass", output="sos")
    else:
        sos = butter(
            4,
            float(cutoff),
            btype="highpass" if kind == "高通" else "lowpass",
            output="sos",
        )
    return sosfiltfilt(sos, x)


def compute_psd(x, fs: float) -> dict:
    """功率谱密度（scipy.signal.welch）→ `{freqs:[], psd:[]}`。"""
    x = np.asarray(x, dtype=float)
    freqs, psd = welch(x, fs=float(fs))
    return {"freqs": freqs.tolist(), "psd": psd.tolist()}


def compute_stft(x, fs: float) -> dict:
    """短时傅里叶变换（scipy.signal.stft）→ `{times:[], freqs:[], magnitude:2D}`。

    magnitude 形状 = (len(freqs) × len(times))，值为 |Z|。
    """
    x = np.asarray(x, dtype=float)
    freqs, times, z = stft(x, fs=float(fs))
    return {
        "times": times.tolist(),
        "freqs": freqs.tolist(),
        "magnitude": np.abs(z).tolist(),
    }


def compute_dwt(x, level: int = 4, wavelet: str = "db4") -> dict:
    """离散小波分解（pywt.wavedec）→ `{bands:[D1..Dn], approx:{A_n}}`。

    D1 最细层（高频）→ Dn 最粗层细节；A_n 为最末层近似系数。
    """
    x = np.asarray(x, dtype=float)
    coeffs = pywt.wavedec(x, wavelet, level=level)
    bands = [
        {"name": f"D{i + 1}", "values": coeffs[level - i].tolist()}
        for i in range(level)
    ]
    return {
        "bands": bands,
        "approx": {"name": f"A{level}", "values": coeffs[0].tolist()},
    }


def wavelet_decomp(x, level: int = 5, wavelet: str = "db4") -> dict:
    """小波多层分量分解（wavedec 各层细节系数）→ `{bands:[L1..Ln]}`。

    L1 捕捉高频瞬变（最细层 D1）→ Ln 低频尺度，与 App.tsx WaveletDecomp 一致。
    """
    x = np.asarray(x, dtype=float)
    coeffs = pywt.wavedec(x, wavelet, level=level)
    bands = [
        {"name": f"L{i + 1}", "values": coeffs[level - i].tolist()}
        for i in range(level)
    ]
    return {"bands": bands}


def phase_trajectory(cur, vol, max_points: int = 2048) -> dict:
    """电流–电压相图轨迹 → `{current:[], voltage:[]}`（降采样到 ≤2048 点）。"""
    cur = np.asarray(cur, dtype=float)
    vol = np.asarray(vol, dtype=float)
    n = min(cur.size, vol.size)
    cur, vol = cur[:n], vol[:n]
    if n > max_points:
        idx = np.linspace(0, n - 1, max_points, dtype=int)
        cur, vol = cur[idx], vol[idx]
    return {"current": cur.tolist(), "voltage": vol.tolist()}


def pdd_density(x, bins: int = 28, lo: float | None = None, hi: float | None = None) -> dict:
    """概率密度分布（直方图 + 高斯 KDE）→ `{bins:[], counts:[], kde:[]}`。

    复刻 App.tsx PddChart：bin 下标 `floor((v-lo)/(hi-lo)*bins)` 并裁剪到 [0,bins-1]；
    kde[i] = Σ_j counts[j]·exp(-((i-j)/3.5)²)。`counts` 之和 == 样本数。
    `lo`/`hi` 缺省取信号 min/max（路由一般传通道的量程 lo/hi）。
    """
    x = np.asarray(x, dtype=float)
    if lo is None:
        lo = float(np.min(x))
    if hi is None:
        hi = float(np.max(x))
    if hi <= lo:
        hi = lo + 1.0  # 常值信号：防除零，直方图落在单个 bin
    span = hi - lo
    idx = np.floor(((x - lo) / span) * bins).astype(int)
    idx = np.clip(idx, 0, bins - 1)
    counts = np.zeros(bins, dtype=int)
    np.add.at(counts, idx, 1)

    bin_centers = lo + (np.arange(bins) + 0.5) * (span / bins)
    kde = np.zeros(bins, dtype=float)
    for i in range(bins):
        d = (np.arange(bins) - i) / 3.5
        kde[i] = float(np.sum(counts * np.exp(-d * d)))

    return {
        "bins": bin_centers.tolist(),
        "counts": counts.tolist(),
        "kde": kde.tolist(),
    }
