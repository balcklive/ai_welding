"""media_probe 单元测试（不连 DB）：ffmpeg 元数据探测 + 关键帧抽取。

mp4 用 imageio-ffmpeg 自带二进制生成（复刻 `tests/fixtures/gen_destructive_data.gen_mp4`），
探测/抽取走同一条 ffmpeg 链路，端到端验证真实解析。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import imageio_ffmpeg
import pytest

from app.services import media_probe

FPS, W, H, DURATION = 10, 320, 240, 2.0


def _gen_mp4(path: Path, seconds: float = DURATION) -> None:
    subprocess.run(
        [
            imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error",
            "-f", "lavfi", "-i",
            f"testsrc=size={W}x{H}:rate={FPS}:duration={seconds}",
            "-pix_fmt", "yuv420p", "-c:v", "libx264", str(path),
        ],
        check=True, capture_output=True,
    )


@pytest.fixture(scope="module")
def mp4_bytes(tmp_path_factory) -> bytes:
    path = tmp_path_factory.mktemp("media") / "weld.mp4"
    _gen_mp4(path)
    return path.read_bytes()


def test_parse_ffmpeg_info_duration_fps_resolution() -> None:
    stderr = (
        "Input #0, mov,mp4,m4a,3gp,3g2,mj2, from 'x.mp4':\n"
        "  Duration: 00:00:02.00, start: 0.000000, bitrate: N/A\n"
        "  Stream #0:0: Video: h264, yuv420p, 320x240, 10 fps, 10 tbr, 10240 tbn\n"
    )
    info = media_probe.parse_ffmpeg_info(stderr)
    assert info["duration"] == pytest.approx(2.0)
    assert info["fps"] == pytest.approx(10.0)
    assert info["width"] == 320
    assert info["height"] == 240


def test_parse_ffmpeg_info_missing_fields_are_none() -> None:
    info = media_probe.parse_ffmpeg_info("至少有个 Duration: 00:01:05.500")
    assert info["duration"] == pytest.approx(65.5)
    assert info["fps"] is None
    assert info["width"] is None and info["height"] is None


def test_probe_video_bytes_on_generated_mp4(mp4_bytes: bytes) -> None:
    meta, _ = media_probe.analyze_video(mp4_bytes, [])
    assert meta["duration"] == pytest.approx(DURATION, abs=0.2)
    assert meta["fps"] == pytest.approx(FPS, abs=0.5)
    assert meta["width"] == W and meta["height"] == H


def test_analyze_video_empty_or_garbage_raises() -> None:
    with pytest.raises(ValueError):
        media_probe.analyze_video(b"", [])
    with pytest.raises(ValueError):
        media_probe.analyze_video(b"MZ" + b"x" * 1024, [])  # 伪类型文本


def test_extract_keyframes_skips_events_beyond_duration(mp4_bytes: bytes) -> None:
    _meta, keyframes = media_probe.analyze_video(
        mp4_bytes, [("arc", 0.4), ("weld_start", 1.0), ("tail", 9.9)]
    )
    # tail=9.9s 超出 2s 视频 → 跳过（EOF 附近 -ss 抽不到帧，钳制会产出错误时刻的帧）
    assert [kf["event"] for kf in keyframes] == ["arc", "weld_start"]
    assert all(kf["bytes"].startswith(b"\xff\xd8") for kf in keyframes)
    assert keyframes[0]["t"] == pytest.approx(0.4, abs=0.15)


def test_extract_keyframes_negative_timestamp_skipped(mp4_bytes: bytes) -> None:
    _meta, keyframes = media_probe.analyze_video(mp4_bytes, [("too_early", -1.0)])
    assert keyframes == []


def test_get_ffmpeg_exe_missing_raises(monkeypatch) -> None:
    import sys

    monkeypatch.setitem(sys.modules, "imageio_ffmpeg", None)
    with pytest.raises(RuntimeError):
        media_probe.get_ffmpeg_exe()
