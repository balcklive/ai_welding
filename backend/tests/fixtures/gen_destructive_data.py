"""破坏性测试数据包生成器（网页端交互测试用）。

生成全模态测试数据到 `tests/fixtures/destructive/`（覆盖合法/损坏/边界三类）：

- csv/：合法焊接信号（100 行 ~ 100 万行分档）+ 一套畸形 CSV
- media/：合法 mp4（ffmpeg 测试图卡）/jpg（合成焊缝图）/wav（合成电弧声）
  + 损坏变体（截断 mp4/损坏 jpg/空 wav/伪类型 exe 改名 mp4/解压炸弹 PNG）
- boundary/：0 字节 / 101MB 超限 / 超长文件名 / 路径穿越名

用法（在 backend/ 下）：
    uv run python tests/fixtures/gen_destructive_data.py [输出目录，缺省 tests/fixtures/destructive]

说明：
- 全部确定性生成（固定种子），可重复运行。
- 生成的文件为测试耗材不入库（以本脚本为准）；破坏性测试请用本包 + seed 演示数据，
  不要用真实生产数据。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image
from scipy.io import wavfile

import imageio_ffmpeg

DURATION, FS = 5.0, 1000


# ── 合成信号（确定性，全部在 CHANNEL_SPECS 量程内） ───────────────────


def synth_df(duration: float = DURATION, fs: int = FS, seed: int = 42) -> pd.DataFrame:
    """合法焊接信号：起弧→稳态→收弧 + 两个异常区段。"""
    rng = np.random.default_rng(seed)
    n = int(duration * fs)
    t = np.arange(n) / fs
    cur = np.full(n, 15.0)
    vol = np.full(n, 4.0)
    gas = np.full(n, 15.0)
    wir = np.full(n, 5.0)
    active = (t >= 0.6) & (t <= duration - 0.4)
    cur[active] = 150 + 8 * np.sin(2 * np.pi * 2 * t[active]) + rng.normal(0, 3, active.sum())
    vol[active] = 22 + rng.normal(0, 1, active.sum())
    gas[active] = 15 + rng.normal(0, 0.3, active.sum())
    wir[active] = 5 + rng.normal(0, 0.2, active.sum())
    for a, b in ((1.9, 2.3), (3.5, 3.9)):
        m = (t >= a) & (t <= b)
        cur[m] += rng.normal(0, 18, m.sum())
        vol[m] += rng.normal(0, 3, m.sum())
    return pd.DataFrame(
        {"时间": t, "电流(A)": cur, "电压(V)": vol, "气体流量(L/min)": gas, "送丝速度(m/min)": wir}
    )


def _df_with_non_numeric() -> pd.DataFrame:
    df = synth_df()
    df["电流(A)"] = df["电流(A)"].astype(object)
    df.loc[5, "电流(A)"] = "abc"
    return df


def _df_scaled(current: float) -> pd.DataFrame:
    df = synth_df()
    df["电流(A)"] = current
    return df


def _df_jitter() -> pd.DataFrame:
    df = synth_df()
    rng = np.random.default_rng(9)
    df["时间"] = df["时间"].to_numpy() + rng.uniform(-0.02, 0.02, len(df))
    return df


def _df_dup_ts() -> pd.DataFrame:
    df = synth_df()
    df.loc[10:20, "时间"] = df.loc[10, "时间"]
    return df


# ── 媒体生成 ──────────────────────────────────────────────────────────


def gen_mp4(path: Path, seconds: float = 2.0) -> None:
    """ffmpeg 生成合法 H.264 测试图卡视频（极小体积）。"""
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    subprocess.run(
        [
            ff, "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", f"testsrc=size=320x240:rate=10:duration={seconds}",
            "-pix_fmt", "yuv420p", "-c:v", "libx264", str(path),
        ],
        check=True, capture_output=True,
    )


def gen_jpg(path: Path) -> None:
    """合成焊缝图（暗背景 + 熔池亮斑）。"""
    rng = np.random.default_rng(3)
    img = (rng.random((480, 640, 3)) * 40 + 30).astype(np.uint8)
    cy, cx = 260, 340
    yy, xx = np.ogrid[:480, :640]
    mask = (yy - cy) ** 2 + (xx - cx) ** 2 < 90 ** 2
    img[mask] = np.clip(img[mask].astype(float) * 2.5, 0, 255).astype(np.uint8)
    Image.fromarray(img).save(path, "JPEG", quality=85)


def gen_wav(path: Path) -> None:
    """合成电弧声（噪声包络，2s @ 22050Hz）。"""
    rng = np.random.default_rng(5)
    fs = 22050
    t = np.arange(int(2 * fs)) / fs
    env = 0.2 + 0.8 * (t < 1.8)
    audio = (rng.normal(0, 1, len(t)) * env * 8000).astype(np.int16)
    wavfile.write(path, fs, audio)


def gen_bomb_png(path: Path) -> None:
    """解压炸弹：10000×10000 纯色 PNG——磁盘极小、解码内存 ~300MB。"""
    Image.new("RGB", (10000, 10000), (40, 40, 40)).save(path, "PNG")


def gen_oversize_bin(path: Path, mb: int = 101) -> None:
    """>100MB 占位（触发 presign 直传 / 代理上传拒绝边界）。"""
    with open(path, "wb") as f:
        chunk = b"\x00" * (1024 * 1024)
        for _ in range(mb):
            f.write(chunk)


# ── 主流程 ────────────────────────────────────────────────────────────


def main(out_dir: Path) -> None:
    (out_dir / "csv").mkdir(parents=True, exist_ok=True)
    (out_dir / "media").mkdir(parents=True, exist_ok=True)
    (out_dir / "boundary").mkdir(parents=True, exist_ok=True)

    # 任务表：(输出相对路径, 用途说明, 生成回调)。回调统一接收最终绝对路径。
    tasks: list[tuple[str, str, callable]] = [
        # ── 合法 CSV ──
        ("csv/valid_5s_1khz.csv", "合法基准（5000 行，通过校验 → source=real）",
         lambda p: synth_df().to_csv(p, index=False)),
        ("csv/valid_small_500.csv", "最小通过线（500 行 / 0.5s，刚好满足 R9）",
         lambda p: synth_df(0.5).to_csv(p, index=False)),
        ("csv/valid_large_100k.csv", "大文件（100k 行，100s@1kHz）导入压测",
         lambda p: synth_df(100.0).to_csv(p, index=False)),
        ("csv/valid_huge_1m.csv", "超大文件（1M 行，1000s@1kHz）内存/耗时压测",
         lambda p: synth_df(1000.0).to_csv(p, index=False)),
        # ── 畸形 CSV ──
        ("csv/malformed_non_numeric.csv", "电流列混入 abc → 校验 R4 fail",
         lambda p: _df_with_non_numeric().to_csv(p, index=False)),
        ("csv/malformed_empty.csv", "只有表头无数据 → R1/R9 fail",
         lambda p: p.write_text("时间,电流(A),电压(V)\n", encoding="utf-8")),
        ("csv/malformed_no_header.csv", "无表头 → R2 fail",
         lambda p: p.write_text("0,15,4\n0.001,150,22\n0.002,151,22\n", encoding="utf-8")),
        ("csv/malformed_out_of_range.csv", "电流填 5000A → R5 fail",
         lambda p: _df_scaled(5000.0).to_csv(p, index=False)),
        ("csv/malformed_irregular_time.csv", "时间列严重抖动 → R6 fail",
         lambda p: _df_jitter().to_csv(p, index=False)),
        ("csv/malformed_dup_timestamp.csv", "重复时间戳 → R8 warn/fail",
         lambda p: _df_dup_ts().to_csv(p, index=False)),
        ("csv/malformed_utf8_bom.csv", "UTF-8 BOM 表头 → 解析鲁棒性",
         lambda p: p.write_text(synth_df().to_csv(index=False), encoding="utf-8-sig")),
        ("csv/malformed_utf16.csv", "UTF-16 编码 → 解析鲁棒性",
         lambda p: p.write_text(synth_df().head(50).to_csv(index=False), encoding="utf-16")),
        ("csv/malformed_inconsistent_columns.csv", "列数不一致（坏行）→ 解析鲁棒性",
         lambda p: p.write_text("时间,电流(A),电压(V)\n0,15,4,extra\n0.001,150,22\n", encoding="utf-8")),
        ("csv/malformed_long_line.csv", "超长单行（10 万字符）→ 解析鲁棒性",
         lambda p: p.write_text("时间,电流(A),电压(V)\n0," + "1," * 100000 + "\n", encoding="utf-8")),
        # ── 合法媒体 ──
        ("media/valid_weld.mp4", "合法视频（播放正路）", gen_mp4),
        ("media/valid_weld.jpg", "合法焊缝图（缩略图正路）", gen_jpg),
        ("media/valid_arc.wav", "合法电弧声（下载/播放正路）", gen_wav),
        # ── 损坏媒体 / 伪类型 ──
        ("media/broken_truncated.mp4", "截断 mp4（取合法前 1KB）→ 播放容错",
         lambda p: p.write_bytes((out_dir / "media/valid_weld.mp4").read_bytes()[:1024])),
        ("media/broken_corrupt.jpg", "损坏 jpg（200~400 字节置 0xFF）→ 缩略图容错",
         lambda p: _corrupt_jpg(p, out_dir / "media/valid_weld.jpg")),
        ("media/broken_empty.wav", "空 wav（44 字节 RIFF 头无数据）→ 播放容错",
         lambda p: p.write_bytes(b"RIFF" + b"\x00" * 40)),
        ("media/fake_type_evil.exe.mp4", "伪类型（文本内容改名 .mp4）→ 类型校验",
         lambda p: p.write_text("MZ" + "x" * 1024, encoding="utf-8")),
        ("media/bomb_10000x10000.png", "解压炸弹（10000×10000 纯色）→ 前端/上传内存", gen_bomb_png),
        # ── 边界 ──
        ("boundary/empty_0bytes.csv", "0 字节文件 → 上传/挂载边界",
         lambda p: p.write_bytes(b"")),
        ("boundary/oversize_101MB.bin", "101MB 超代理上传阈值 → presign/拒绝边界", gen_oversize_bin),
        ("boundary/long_filename_" + "a" * 200 + ".csv", "超长文件名（>255）→ normalize_key 截断",
         lambda p: p.write_text("时间,电流(A)\n0,15\n", encoding="utf-8")),
        ("boundary/path_attack_..%2Fetc%2Fpasswd.csv", "路径穿越名（..%2F）→ normalize_key 清洗",
         lambda p: p.write_text("时间,电流(A)\n0,15\n", encoding="utf-8")),
    ]

    manifest: list[tuple[str, str]] = []
    for rel, purpose, fn in tasks:
        p = out_dir / rel
        fn(p)
        manifest.append((rel, purpose))

    lines = ["# 破坏性测试数据包清单（由 gen_destructive_data.py 确定性生成，可重跑）\n"]
    lines.append("\n| 文件 | 用途 |\n|---|---|\n")
    lines += [f"| `{rel}` | {purpose} |\n" for rel, purpose in manifest]
    (out_dir / "MANIFEST.md").write_text("".join(lines), encoding="utf-8")

    total = sum(f.stat().st_size for f in out_dir.rglob("*") if f.is_file())
    print(f"生成完成：{out_dir}，{len(manifest)} 个文件，共 {total / 1024 / 1024:.1f} MB")
    print(f"清单：{out_dir / 'MANIFEST.md'}")


def _corrupt_jpg(path: Path, valid: Path) -> None:
    data = bytearray(valid.read_bytes())
    for i in range(200, min(400, len(data))):
        data[i] = 0xFF
    path.write_bytes(bytes(data))


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "destructive"
    main(out)
