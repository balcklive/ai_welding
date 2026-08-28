"""多模态特征提取（Task 12）：时序 / 视觉 / 声音三类特征 + 42 维统一向量。

契约：`docs/API接口清单.md` §3.4（POST /features/extract）与 §2 `FeatureExtraction`
实体；分组形状对齐 `src/App.tsx` 的 `tsFeatures`/`visionFeatures`/`audioFeatures`/
`unifiedVector`。

**实施边界（§3.1）：特征 = 真实计算**（不是罐头数字）：
- `ts_features(x)`：numpy/scipy/pywt 算统计（均值/方差/峰值/偏度/峰度/RMS）+
  频域（FFT 主频）+ 时频（db1 三层小波细节能量），每通道 8 维。
- `vision_features_from_image(data)`：真实图片 → Otsu/最大连通区域 → skimage
  `regionprops` + `graycomatrix` GLCM + Sobel，几何 4 维 + 纹理 4 维。
- `audio_features_from_wav(data)`：真实 WAV → librosa 声学统计（质心频率/频谱滚降/过零率）+ scipy
  welch 频带能量/功率与总 PSD，6 维。librosa 为本环境已装并选定的复用项
  （pyproject 依赖 `librosa>=0.10`），未退化到合成音频。
- `unify(ts, vis, audio, normalization, format)`：按固定分组顺序拼接
  `时序·电流 8 + 时序·电压 8 + 时序·气体 6 + 时序·送丝 6 + 视觉·几何 4 +
  视觉·纹理 4 + 声音·频带 6 = 42 维`，应用归一化，返回
  `{total_dims, groups, normalization, format, values}`。

统一向量分组（对齐 App.tsx `unifiedVector`，range 为 `[start, end)` 半开区间）：
- 时序·电流 [0,8)   · 时序·电压 [8,16)  · 时序·气体 [16,22)
- 时序·送丝 [22,28) · 视觉·几何 [28,32) · 视觉·纹理 [32,36) · 声音·频带 [36,42)

坑/边界：
- `ts_features` 的 `fft_dominant_freq` 依赖采样率：默认 `fs=1000`（对齐 signals 默认
  采样率），调用方应传入真实 fs；返回 Hz。小波能量 = 三层细节系数平方和（原始尺度，
  与 App.tsx 演示数值无谓比对——那是占位，真实计算值即本函数的输出）。
- 气体/送丝两通道统一向量只取 6 个统计特征（不含 FFT 主频/小波能量）——流速类
  低频缓变信号做频域/时频区分度低，这是对 App.tsx 8+8+6+6 分组的对齐解释。
- 归一化对零方差/零范数向量做退化保护（不除以 0）：Z-Score 退化为中心化，
  Min-Max 退化为全 0，L2 退化为原样。未知方法抛 `ValueError`（路由层先白名单校验）。
- `vision_features` 用 `axis_major_length`/`axis_minor_length`/`intensity_mean`
  （skimage 0.26 新 API，避免 FutureWarning）；Sobel 用 float 图（0~255 尺度），
  否则 uint8 输入会被 skimage 缩放到 0~1，梯度值小得没有意义。
- 所有返回 dict 键为英文（前端映射中文显示名）；数值均为 float，JSON 安全。
"""

from __future__ import annotations

import zlib
from io import BytesIO

import numpy as np
import pywt
from scipy import stats
from skimage import feature, filters, measure
from skimage.morphology import erosion, footprint_rectangle

#: 默认采样率（Hz）。与 `app.services.signals` 的 `_DEFAULT_SAMPLE_RATE` 一致。
DEFAULT_SAMPLE_RATE = 1000
#: 合成音频默认采样率：覆盖声音频带 1-5kHz 需要 Nyquist>5kHz，取标准音频 22.05kHz。
DEFAULT_AUDIO_SAMPLE_RATE = 22050

#: 时序特征顺序（8 维，电流/电压全量；气体/送丝只用前 6 个统计特征）。
TS_FEATURE_KEYS = [
    "mean",
    "variance",
    "peak",
    "skewness",
    "kurtosis",
    "rms",
    "fft_dominant_freq",
    "wavelet_energy",
]
#: 气体/送丝仅取 6 个统计特征（去掉 FFT 主频 / 小波能量两个频域·时频项）。
TS_STAT_KEYS = TS_FEATURE_KEYS[:6]

#: 视觉几何 4 维 / 纹理 4 维。
VISION_GEOMETRY_KEYS = ["area", "perimeter", "aspect_ratio", "circularity"]
VISION_TEXTURE_KEYS = [
    "gray_mean",
    "glcm_contrast",
    "glcm_energy",
    "sobel_gradient",
]

#: 声音频带 6 维。
AUDIO_FEATURE_KEYS = [
    "band_energy_low",
    "band_power_high",
    "total_psd",
    "spectral_centroid",
    "spectral_rolloff",
    "zero_crossing_rate",
]

#: 统一向量分组定义（顺序即拼接顺序），对齐 App.tsx `unifiedVector`。
GROUP_DIMS = [8, 8, 6, 6, 4, 4, 6]
GROUP_NAMES = [
    "时序·电流",
    "时序·电压",
    "时序·气体",
    "时序·送丝",
    "视觉·几何",
    "视觉·纹理",
    "声音·频带",
]
TOTAL_DIMS = sum(GROUP_DIMS)


def ts_features(x, fs: int = DEFAULT_SAMPLE_RATE) -> dict:
    """单通道时序特征（8 维）：均值/方差/峰值/偏度/峰度/RMS/FFT 主频/小波能量。

    `fs` 只用于把 FFT bin 换算成 Hz；默认 1000（对齐 signals 采样率）。
    全部为 numpy/scipy/pywt 真实计算。常量/退化信号 → 偏度/峰度 nan 被转 0。
    """
    x = np.asarray(x, dtype=float)
    if x.size == 0:
        return {k: 0.0 for k in TS_FEATURE_KEYS}
    mean = float(np.mean(x))
    variance = float(np.var(x))
    peak = float(np.max(np.abs(x)))
    rms = float(np.sqrt(np.mean(x**2)))
    return {
        "mean": mean,
        "variance": variance,
        "peak": peak,
        "skewness": float(np.nan_to_num(stats.skew(x))),
        "kurtosis": float(np.nan_to_num(stats.kurtosis(x, fisher=True))),
        "rms": rms,
        "fft_dominant_freq": _fft_dominant_freq(x, fs),
        "wavelet_energy": _wavelet_energy(x),
    }


def vision_features(size: int = 128) -> dict:
    """熔池视觉特征（8 维）：合成熔池二值掩膜 → regionprops + GLCM + Sobel 真实计算。

    几何 4：面积/周长/长宽比/圆形度(4πA/P²)；纹理 4：灰度均值/GLCM 对比度/
    GLCM 能量(角二阶矩)/Sobel 梯度均值。确定性（rng=42 + 固定椭圆参数）。
    """
    rng = np.random.default_rng(42)
    yy, xx = np.mgrid[0:size, 0:size]
    cx = cy = (size - 1) / 2.0
    theta = np.pi / 6  # 固定旋转角 → 长宽比 ≠ 1
    dx, dy = xx - cx, yy - cy
    xr = dx * np.cos(theta) + dy * np.sin(theta)
    yr = -dx * np.sin(theta) + dy * np.cos(theta)
    semi_a = size * 0.28
    semi_b = size * 0.16
    mask = (xr / semi_a) ** 2 + (yr / semi_b) ** 2 <= 1.0

    img_float = np.where(
        mask, 128.0 + rng.normal(0.0, 12.0, size=yy.shape), 0.0
    )
    img_uint8 = np.clip(img_float, 0, 255).astype(np.uint8)

    labels = measure.label(mask)
    props = measure.regionprops(labels, intensity_image=img_float)
    if not props:
        raise RuntimeError("The generated weld-pool mask is empty; regionprops found no objects")
    region = props[0]

    area = float(region.area)
    perimeter = float(region.perimeter)
    major = float(region.axis_major_length)
    minor = float(region.axis_minor_length)
    aspect_ratio = major / minor if minor > 1e-12 else 0.0
    circularity = 4.0 * np.pi * area / (perimeter**2) if perimeter > 1e-12 else 0.0
    gray_mean = float(region.intensity_mean) if region.intensity_mean is not None else 0.0

    glcm = feature.graycomatrix(
        img_uint8,
        distances=[1],
        angles=[0],
        levels=256,
        symmetric=True,
        normed=True,
    )
    glcm_contrast = float(feature.graycoprops(glcm, "contrast")[0, 0])
    glcm_energy = float(feature.graycoprops(glcm, "energy")[0, 0])

    grad = filters.sobel(img_float)  # float 图 0~255 尺度，避免 uint8→0~1 缩放
    sobel_gradient = float(np.mean(grad[mask])) if mask.any() else 0.0

    return {
        "area": area,
        "perimeter": perimeter,
        "aspect_ratio": aspect_ratio,
        "circularity": circularity,
        "gray_mean": gray_mean,
        "glcm_contrast": glcm_contrast,
        "glcm_energy": glcm_energy,
        "sobel_gradient": sobel_gradient,
    }


def vision_features_from_image(data: bytes) -> dict:
    """从真实图片计算视觉特征。

    这是特征工程层的保底分割：使用灰度 Otsu 阈值和最大连通区域。
    生产环境应将这里替换为已审核的熔池分割模型，但不会再用固定合成图像冒充真实输入。
    """
    from PIL import Image

    with Image.open(BytesIO(data)) as image:
        gray = np.asarray(image.convert("L"), dtype=float)
    if gray.size == 0:
        raise ValueError("视觉输入为空")
    threshold = float(filters.threshold_otsu(gray)) if np.ptp(gray) > 1e-12 else float(gray.mean())
    mask = gray > threshold
    labels = measure.label(mask)
    regions = measure.regionprops(labels, intensity_image=gray)
    if not regions:
        raise ValueError("视觉输入未检测到有效熔池区域")
    region = max(regions, key=lambda item: item.area)
    selected = labels == region.label
    perimeter = float(region.perimeter)
    major = float(region.axis_major_length)
    minor = float(region.axis_minor_length)
    return {
        "area": float(region.area),
        "perimeter": perimeter,
        "aspect_ratio": major / minor if minor > 1e-12 else 0.0,
        "circularity": 4.0 * np.pi * float(region.area) / (perimeter**2) if perimeter > 1e-12 else 0.0,
        "gray_mean": float(region.intensity_mean or 0.0),
        "glcm_contrast": _image_glcm(gray, selected, "contrast"),
        "glcm_energy": _image_glcm(gray, selected, "energy"),
        "sobel_gradient": float(np.mean(filters.sobel(gray)[selected])) if selected.any() else 0.0,
    }


def _image_glcm(gray: np.ndarray, mask: np.ndarray, prop: str) -> float:
    """计算真实灰度图的 GLCM 属性，避免把背景纹理计入熔池。"""
    image = np.clip(gray, 0, 255).astype(np.uint8)
    image = np.where(mask, image, 0).astype(np.uint8)
    glcm = feature.graycomatrix(image, distances=[1], angles=[0], levels=256, symmetric=True, normed=True)
    return float(feature.graycoprops(glcm, prop)[0, 0])


def generate_audio(
    weld_id: str,
    sample_rate: int = DEFAULT_AUDIO_SAMPLE_RATE,
    duration: float = 5.42,
) -> tuple[np.ndarray, int]:
    """确定性合成电弧音频（模拟输入，真实特征计算）。

    包络复刻焊接段（起弧 0.42s → 稳态 → 收弧 4.86s 起），叠加 120Hz 嗡鸣 +
    高通嘶声（差分噪声）+ 稀疏飞溅脉冲。种子 = crc32(weld_id) + 固定偏移，
    跨进程可复现（复用 signals.py 的 crc32 方案，勿用内置 hash()）。
    返回 `(audio_ndarray, sample_rate)`。频率内容在 1-5kHz 有能量，供频带特征区分。
    """
    rng = np.random.default_rng(zlib.crc32(str(weld_id).encode("utf-8")) + 7)
    n = int(duration * sample_rate)
    t = np.linspace(0, duration, n)
    env = np.ones(n)
    arc_end = int(0.42 * sample_rate)
    tail_start = int(4.86 * sample_rate)
    env[:arc_end] = np.linspace(0.2, 1.0, arc_end)
    env[tail_start:] = np.linspace(1.0, 0.2, n - tail_start)

    hum = 0.5 * np.sin(2 * np.pi * 120 * t + rng.uniform(0, 2 * np.pi))
    hiss = rng.normal(0, 1, n) * env
    hiss_high = np.diff(hiss, prepend=hiss[0]) * 0.5  # 差分抬高高频
    pulses = (rng.random(n) < 0.002) * rng.normal(0, 2, n) * env
    audio = hum + hiss_high + pulses
    return audio, sample_rate


def audio_features(x, fs: int = DEFAULT_AUDIO_SAMPLE_RATE) -> dict:
    """声音特征（6 维）：频带能量/频带功率/总 PSD + 质心频率/频谱滚降/过零率。

    - `band_energy_low` (0-1kHz)、`band_power_high` (1-5kHz)：对 scipy welch PSD
      积分后取 10·log10，单位 dB（对齐 App.tsx 演示数值）。
    - `total_psd`：welch PSD 均值（无量纲）。
    - `spectral_centroid` / `spectral_rolloff`：librosa，返回 Hz。
    - `zero_crossing_rate`：librosa 过零率（无量纲）。
    空/全零输入 → 全 0（避免 log(0)=-inf 与 NaN）。librosa 为本环境已装复用项。
    """
    x = np.asarray(x, dtype=float)
    if x.size == 0:
        return {k: 0.0 for k in AUDIO_FEATURE_KEYS}
    peak = float(np.max(np.abs(x)))
    if peak <= 1e-12:
        return {k: 0.0 for k in AUDIO_FEATURE_KEYS}
    y = x / peak

    freqs, psd = _welch(y, fs)
    eps = 1e-12
    low = freqs <= 1000.0
    high = (freqs >= 1000.0) & (freqs <= 5000.0)
    band_energy_low = 10.0 * np.log10(
        max(eps, float(np.trapezoid(psd[low], freqs[low]))) if low.any() else eps
    )
    band_power_high = 10.0 * np.log10(
        max(eps, float(np.trapezoid(psd[high], freqs[high]))) if high.any() else eps
    )
    total_psd = float(np.mean(psd))

    centroid = float(
        _librosa_feature("spectral_centroid", y=y, sr=fs)[0].mean()
    )
    rolloff = float(
        _librosa_feature("spectral_rolloff", y=y, sr=fs, roll_percent=0.85)[0].mean()
    )
    zcr = float(_librosa_feature("zero_crossing_rate", y=y)[0].mean())

    return {
        "band_energy_low": float(band_energy_low),
        "band_power_high": float(band_power_high),
        "total_psd": total_psd,
        "spectral_centroid": centroid,
        "spectral_rolloff": rolloff,
        "zero_crossing_rate": zcr,
    }


def audio_features_from_wav(data: bytes) -> dict:
    """读取真实 WAV 文件并计算声音特征。"""
    from scipy.io import wavfile

    fs, audio = wavfile.read(BytesIO(data))
    values = np.asarray(audio)
    if values.ndim > 1:
        values = values.mean(axis=1)
    return audio_features(values, fs=int(fs))


def unify(
    ts: dict,
    vis: dict,
    audio: dict,
    normalization: str = "无",
    format: str = "JSON",
) -> dict:
    """拼接 42 维统一向量并归一化，返回 `{total_dims, groups, normalization, format, values}`。

    `ts` 为 `{通道id: {特征key: 值}}`（由 ts_features 逐通道产出）；
    `vis`/`audio` 为 vision_features/audio_features 产出。分组顺序固定：
    电流 8 → 电压 8 → 气体 6 → 送丝 6 → 几何 4 → 纹理 4 → 声音 6。
    `normalization` ∈ Z-Score | Min-Max | L2 | 无；`format` 透传（NPY/CSV/JSON/PT，
    当前仅存 JSON 元数据，导出由 reports 另行实现）。未知归一化抛 ValueError。
    """
    if normalization not in _NORMALIZATIONS:
        raise ValueError(f"Unknown normalization method: {normalization}")
    raw = _concat_vector(ts, vis, audio)
    if len(raw) != TOTAL_DIMS:
        raise ValueError(
            f"拼接维度 {len(raw)} != 期望 {TOTAL_DIMS}，分组定义与特征键不一致"
        )
    values = _normalize(raw, normalization)

    start = 0
    groups = []
    for name, dims in zip(GROUP_NAMES, GROUP_DIMS):
        groups.append({"name": name, "dims": dims, "range": [start, start + dims]})
        start += dims

    return {
        "total_dims": TOTAL_DIMS,
        "groups": groups,
        "normalization": normalization,
        "format": format,
        "values": [float(v) for v in values],
    }


# ── 内部实现 ──────────────────────────────────────────────────────────


_NORMALIZATIONS = {"Z-Score", "Min-Max", "L2", "无"}


def _fft_dominant_freq(x: np.ndarray, fs: int) -> float:
    """去均值后 rfft 主峰频率（Hz）。忽略 DC bin。"""
    if x.size < 4:
        return 0.0
    spec = np.abs(np.fft.rfft(x - np.mean(x)))
    freqs = np.fft.rfftfreq(x.size, d=1.0 / fs)
    if spec.size < 2:
        return 0.0
    idx = int(np.argmax(spec[1:])) + 1  # 跳过 DC bin
    return float(freqs[idx])


def _wavelet_energy(x: np.ndarray) -> float:
    """db1 三层小波细节系数平方和（原始尺度小波能量）。"""
    if x.size < 8:
        return 0.0
    coeffs = pywt.wavedec(x, "db1", level=3)
    detail = np.concatenate(coeffs[1:]) if len(coeffs) > 1 else np.array([])
    return float(np.sum(np.square(detail)))


def _welch(x: np.ndarray, fs: int) -> tuple[np.ndarray, np.ndarray]:
    """scipy welch PSD（nperseg 自动 ≤ 信号长度）。"""
    from scipy import signal as sp_signal

    nperseg = min(2048, x.size)
    return sp_signal.welch(x, fs=fs, nperseg=nperseg)


def _librosa_feature(name: str, **kwargs) -> np.ndarray:
    """懒加载 librosa（包导入较慢，测试仅用到时才触发）。"""
    import librosa

    return getattr(librosa.feature, name)(**kwargs)


def _concat_vector(ts: dict, vis: dict, audio: dict) -> list[float]:
    """按固定分组顺序拼 42 维原始向量。缺失键按 0 补齐（容忍通道缺席）。"""
    vec: list[float] = []
    cur = ts.get("cur", {})
    vol = ts.get("vol", {})
    gas = ts.get("gas", {})
    wir = ts.get("wir", {})
    for key in TS_FEATURE_KEYS:
        vec.append(cur.get(key, 0.0))
    for key in TS_FEATURE_KEYS:
        vec.append(vol.get(key, 0.0))
    for key in TS_STAT_KEYS:
        vec.append(gas.get(key, 0.0))
    for key in TS_STAT_KEYS:
        vec.append(wir.get(key, 0.0))
    for key in VISION_GEOMETRY_KEYS:
        vec.append(vis.get(key, 0.0))
    for key in VISION_TEXTURE_KEYS:
        vec.append(vis.get(key, 0.0))
    for key in AUDIO_FEATURE_KEYS:
        vec.append(audio.get(key, 0.0))
    return vec


def _normalize(vector: list[float], method: str) -> list[float]:
    """归一化。零方差/零范数退化保护（不除以 0）。"""
    v = np.asarray(vector, dtype=float)
    if method == "Z-Score":
        std = float(v.std())
        if std > 1e-12:
            v = (v - v.mean()) / std
        else:
            v = v - v.mean()
    elif method == "Min-Max":
        lo, hi = float(v.min()), float(v.max())
        if hi - lo > 1e-12:
            v = (v - lo) / (hi - lo)
        else:
            v = np.zeros_like(v)
    elif method == "L2":
        norm = float(np.linalg.norm(v))
        if norm > 1e-12:
            v = v / norm
    # method == "无" → 原样
    return [float(x) for x in v]
