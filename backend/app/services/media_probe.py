"""媒体探测（对齐真实化）：用 imageio-ffmpeg 自带的 ffmpeg 二进制做视频元数据探测
与事件时刻关键帧抽取（不重编码）。

职责边界（对齐内核 `app/services/alignment.py` 的调用方约定）：
- 本模块所有失败以异常表达（ValueError=视频不可解析 / RuntimeError=ffmpeg 不可用），
  由调用方逐模态 try/except 转 unavailable + reason，绝不逃逸到对齐主流程之外；
- 单帧关键帧失败只告警跳过，不中断其余帧；
- imageio-ffmpeg 只带 ffmpeg 不带 ffprobe，元数据从 `ffmpeg -i` 的 stderr 解析
  （无输出参数时退出码 1 但流信息完整，`tests/fixtures/gen_destructive_data.py::gen_mp4`
  是同一二进制的生成端先例）。

坑：subprocess 带 `timeout=30` 兜底（对齐 handler 跑在 executor daemon 线程内，
不能无限等待）；`-ss` 放在 `-i` 前走 fast-seek。
"""

from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

from loguru import logger

#: 视频探测/关键帧的字节上限（与 `signal_ingest` 大文件预检同量级；get_object 全量读内存）。
MAX_VIDEO_PROBE_BYTES = 200 * 1024 * 1024

_FFMPEG_TIMEOUT = 30  # 单次 subprocess 超时（秒）

#: JPEG SOI 魔数——校验 ffmpeg 输出确实是 JPG（伪类型/写失败防御）。
_JPEG_SOI = b"\xff\xd8"


def get_ffmpeg_exe() -> str:
    """懒加载 imageio-ffmpeg 自带 ffmpeg 二进制路径；不可用抛 RuntimeError。"""
    try:
        import imageio_ffmpeg
    except Exception as exc:  # noqa: BLE001 - 调用方转 unavailable
        raise RuntimeError(f"imageio-ffmpeg 不可用: {exc}") from exc
    try:
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"ffmpeg 二进制不可用: {exc}") from exc


def parse_ffmpeg_info(stderr: str) -> dict:
    """从 `ffmpeg -i` 的 stderr 解析 {"duration", "fps", "width", "height"}（缺省 None）。"""
    dur_m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", stderr)
    fps_m = re.search(r"(\d+(?:\.\d+)?)\s*fps", stderr)
    dim_m = re.search(r"(\d{2,5})x(\d{2,5})", stderr)
    duration = None
    if dur_m:
        h, m, s = dur_m.groups()
        duration = int(h) * 3600 + int(m) * 60 + float(s)
    return {
        "duration": duration,
        "fps": float(fps_m.group(1)) if fps_m else None,
        "width": int(dim_m.group(1)) if dim_m else None,
        "height": int(dim_m.group(2)) if dim_m else None,
    }


def analyze_video(
    data: bytes, event_points: list[tuple[str, float]]
) -> tuple[dict, list[dict]]:
    """探测视频元数据并按事件时刻抽关键帧（临时文件只写一次）。

    - `event_points`: `[("arc", 0.42), ...]`，时刻会被钳制到 `[0, duration-0.05]`，
      钳后 <0（视频比事件还短）的跳过；
    - 返回 `(metadata, keyframes)`：metadata 同 `parse_ffmpeg_info`（duration 必有），
      keyframes = `[{"event", "t"(钳后时刻), "bytes"(JPEG, SOI 开头)}]`（仅成功的）。
    - 空数据/时长解析失败抛 ValueError；ffmpeg 不可用抛 RuntimeError。
    """
    if not data:
        raise ValueError("空视频数据")
    ff = get_ffmpeg_exe()
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "probe.mp4"
        path.write_bytes(data)
        meta = _probe_file(ff, path)
        keyframes = _extract_keyframes(ff, path, event_points, meta["duration"])
    return meta, keyframes


def _probe_file(ff: str, path: Path) -> dict:
    """`ffmpeg -i`（无输出参数，退出码 1 属预期）→ stderr 解析元数据。"""
    proc = subprocess.run(
        [str(ff), "-i", str(path)],
        capture_output=True,
        timeout=_FFMPEG_TIMEOUT,
    )
    stderr = proc.stderr.decode("utf-8", errors="replace")
    info = parse_ffmpeg_info(stderr)
    if info["duration"] is None:
        raise ValueError(f"无法解析视频时长（ffmpeg 退出码 {proc.returncode}）")
    return info


def _extract_keyframes(
    ff: str,
    path: Path,
    event_points: list[tuple[str, float]],
    duration: float | None,
) -> list[dict]:
    """逐事件 `ffmpeg -ss {t} -i {in} -frames:v 1 -q:v 2 out.jpg`；单帧失败告警跳过。"""
    out: list[dict] = []
    if duration is None:
        return out
    for event, t in event_points:
        try:
            t = float(t)
        except (TypeError, ValueError):
            logger.warning("关键帧事件时刻非法，跳过: event={} t={}", event, t)
            continue
        if t < 0 or t >= duration:
            # 事件超出视频时长：直接跳过（EOF 附近 -ss 抽不到帧，钳制会静默产出
            # 错误时刻的帧），reason 由调用方按 metadata.keyframes 缺失解读。
            logger.warning("事件时刻超出视频时长，跳过: event={} t={} duration={}", event, t, duration)
            continue
        t_eff = min(t, duration - 0.05)
        out_path = path.with_name(f"frame_{event}.jpg")
        try:
            subprocess.run(
                [
                    str(ff), "-y", "-loglevel", "error",
                    "-ss", f"{t_eff:.3f}", "-i", str(path),
                    "-frames:v", "1", "-q:v", "2", str(out_path),
                ],
                check=True,
                capture_output=True,
                timeout=_FFMPEG_TIMEOUT,
            )
            data = out_path.read_bytes()
        except Exception as exc:  # noqa: BLE001 - 单帧失败不中断其余帧
            logger.warning("关键帧抽取失败: event={} t={} err={}", event, t_eff, exc)
            continue
        if not data.startswith(_JPEG_SOI):
            logger.warning("关键帧输出不是 JPEG，跳过: event={}", event)
            continue
        out.append({"event": event, "t": round(t_eff, 4), "bytes": data})
    return out
