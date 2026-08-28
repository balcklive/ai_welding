"""Task 18 回归：ISO 8601 时间戳时间列在 signal_ingest 全链路的解析。

真实数据源（`data/data/SP2026-06-000201/SP2026-06-000201.csv`）时间列为
`YYYY-MM-DDTHH:MM:SS.ffffffZ` 字符串（每行递增 200µs）。旧实现用
`pd.to_numeric` 把 ISO 字符串转成全 NaN → R6「采样一致性」误判 fail、
`detect_events`/Parquet 的 t 列坐标全 NaN。本测试验证 `_time_column_to_seconds`
打通 validate → detect_events → to_parquet_bytes：
- validate：ISO 时间戳 → overall pass、fs≈5000、duration>0、R6 pass；
  纯数值（epoch 秒）时间戳不回归；真实 CSV 走 map_columns 后 R6 pass；
- detect_events：ISO + cur/vol 焊接形态信号，events/anomalies 坐标均非 NaN 有效数值；
- to_parquet_bytes：t 列无 NaN、从相对秒 0 起。

纯函数测试，不连 DB / 存储。
"""

import io
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from app.models.data import DataRecord, DataVersion
from app.services import signal_ingest as svc

_REAL_CSV = (
    Path(__file__).resolve().parents[2]
    / "data" / "data" / "SP2026-06-000201" / "SP2026-06-000201.csv"
)


def _iso_signal_df(
    n: int = 5000,
    dt_s: float = 0.0002,
    start: str = "2026-06-17T14:22:23.000164Z",
) -> pd.DataFrame:
    """构造 200µs 均匀递增的 ISO 8601 时间戳 + 量程内常量信号。"""
    ts = pd.date_range(start, periods=n, freq=pd.Timedelta(seconds=dt_s), tz="UTC")
    t_str = ts.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    return pd.DataFrame(
        {
            "time": t_str,
            "current": np.full(n, 150.0),
            "voltage": np.full(n, 22.0),
            "gas": np.full(n, 15.0),
            "wire": np.full(n, 5.0),
        }
    )


def _numeric_signal_df(n: int = 5000, fs: int = 1000) -> pd.DataFrame:
    """epoch 秒数值时间戳（旧用法），验证不回归。"""
    t = np.arange(n) / fs
    return pd.DataFrame(
        {
            "time": t,
            "current": np.full(n, 150.0),
            "voltage": np.full(n, 22.0),
            "gas": np.full(n, 15.0),
            "wire": np.full(n, 5.0),
        }
    )


def _r6_status(result: dict) -> str:
    return next(r["status"] for r in result["rules"] if r["name"] == "采样一致性")


def test_validate_signal_iso_timestamp_200us():
    df = _iso_signal_df()
    result = svc.validate_signal(df)
    assert result["overall"] == "pass"
    assert result["fs"] == 5000
    assert result["duration"] > 0
    assert result["row_count"] == len(df)
    assert _r6_status(result) == "pass"


def test_validate_signal_numeric_epoch_seconds_no_regression():
    df = _numeric_signal_df()
    result = svc.validate_signal(df)
    assert result["overall"] == "pass"
    assert result["fs"] == 1000
    assert result["duration"] > 0
    assert _r6_status(result) == "pass"


def test_real_csv_iso_time_parses_r6_pass():
    df = pd.read_csv(_REAL_CSV)
    column_map, unknown = svc.map_columns(list(df.columns))
    assert "time" in column_map
    assert "cur" in column_map and "vol" in column_map
    # GasSpeed/tag0/tag1 未被别名识别 → 未知列 → R2 warn，属预期（本用例只关注时间解析）
    assert "gasspeed" in [c.lower() for c in unknown]

    result = svc.validate_signal(df)
    # 时间解析不再是 fail 根因：R6 采样一致性必须 pass，overall 不因时间解析 fail
    assert _r6_status(result) == "pass"
    assert result["overall"] != "fail"
    assert result["fs"] is not None
    assert result["duration"] > 0


def _iso_weld_df(
    n: int = 1000, dt_s: float = 0.001, start: str = "2026-06-17T14:22:23.000164Z"
) -> pd.DataFrame:
    """ISO 时间戳 + 真实形态 cur/vol 信号（fs≈1000）：idle → 焊接段(带不稳定噪声) → 收弧。

    用于验证下游 `detect_events`/`to_parquet_bytes` 在 ISO 时间列下坐标不再 NaN。
    确定性：噪声用固定 RandomState 种子。
    """
    ts = pd.date_range(start, periods=n, freq=pd.Timedelta(seconds=dt_s), tz="UTC")
    t_str = ts.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    t = np.arange(n) * dt_s
    cur = np.full(n, 30.0)
    weld = (t >= 0.2) & (t < 0.9)
    # 不稳定段只占焊接段的小部分：让滚动 std 的基底（中位数）由稳定段主导，
    # 1.8×基底阈值才会被不稳定段的 std 尖峰击穿 → 能真实产出 anomalies。
    unstable = (t >= 0.45) & (t < 0.62)
    rng = np.random.RandomState(42)
    cur[weld] = 250.0 + rng.normal(0, 5, size=weld.sum())
    cur[unstable] += rng.normal(0, 30, size=unstable.sum())
    vol = np.full(n, 22.0)
    return pd.DataFrame({"time": t_str, "current": cur, "voltage": vol})


def _weld_column_map() -> dict[str, str]:
    return {"time": "time", "cur": "current", "vol": "voltage"}


def test_detect_events_iso_time_coords_valid():
    df = _iso_weld_df()
    events, anomalies = svc.detect_events(df, _weld_column_map(), 1000)

    # 旧实现 pd.to_numeric 对 ISO 时间列全 NaN → arc/weld_segment/tail 全是 NaN；
    # 修复后应解析为相对秒的有效数值，且焊接段有正时长。
    arc = events["arc"]
    w0, w1 = events["weld_segment"]
    tail = events["tail"]
    for val in (arc, w0, w1, tail):
        assert np.isfinite(val), f"events 坐标不能是 NaN: {events}"
    assert w0 < w1, f"weld_segment 应有正时长: {events}"
    assert arc >= 0.0 and tail > 0.0

    # 焊接段内注入的不稳定噪声应产出异常段，start/end 同样是有效数值。
    assert anomalies, "注入不稳定噪声后 detect_events 应产出 anomalies"
    for a in anomalies:
        assert np.isfinite(a["start"]) and np.isfinite(a["end"]), f"anomaly 坐标 NaN: {a}"
        assert 0.0 <= a["start"] <= a["end"]


def test_to_parquet_bytes_iso_time_t_no_nan():
    df = _iso_weld_df()
    record = DataRecord(weld_id="WLD-TEST-ISO", registration_no="REG-ISO-001", source="test")
    version = DataVersion(record_id=1, version_no="v1.0", action="upload")
    version.id = 1
    pb = svc.to_parquet_bytes(df, _weld_column_map(), 1000, record, version, 1, "uploads/test.csv")

    pdf = pq.read_table(io.BytesIO(pb)).to_pandas()
    assert not pdf["t"].isna().any(), "Parquet t 列不应有 NaN"
    assert np.isfinite(pdf["t"].to_numpy()).all()
    assert pdf["cur"].notna().all() and pdf["vol"].notna().all()
    assert float(pdf["t"].iloc[0]) == 0.0  # ISO 时间戳解析为相对秒，从 0 起
