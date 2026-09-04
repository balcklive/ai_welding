"""多模态分析.csv 全列导入回归：16 列（time/Current/Voltage/GasSpeed/WireFeedSpeed/
WeldingSpeed/j1..j6/width/height/square/perimeter）逐点作为通道保留。

覆盖：
- `map_columns`：标准头别名识别（WireFeedSpeed→wir、WeldingSpeed→weld_speed、j1..j6、
  width/height/square/perimeter→pool_*）；
- `validate_signal`：别名未覆盖的可数值列自动收为通道（不再当未知列丢弃），非数值列仍 unknown；
- `to_parquet_bytes` → `_parse_parquet`/`bundle_from_parquet`：Parquet 动态列往返，核心 4 恒在 +
  扩展/自动通道全部还原，通道量程对扩展按实际数据推导；
- `build_field_summary`/`fill_record_params`：导入后字段概览与单值工艺列回填。

纯函数测试，不连 DB / 存储。
"""

import io

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from app.models.analysis import SignalIngest
from app.models.data import DataRecord, DataVersion
from app.services import signal_ingest as svc

_MULTIMODAL_HEADER = [
    "time", "Current", "Voltage", "GasSpeed", "WireFeedSpeed", "WeldingSpeed",
    "j1", "j2", "j3", "j4", "j5", "j6",
    "width", "height", "square", "perimeter",
]


def _multimodal_df(n: int = 2000, fs: int = 1000) -> pd.DataFrame:
    """多模态分析.csv 同构数据（核心 4 在量程内、常量值便于断言代表值）。"""
    t = np.arange(n) / fs
    return pd.DataFrame(
        {
            "time": t,
            "Current": np.full(n, 150.0),
            "Voltage": np.full(n, 22.0),
            "GasSpeed": np.full(n, 15.0),
            "WireFeedSpeed": np.full(n, 15.86),
            "WeldingSpeed": np.full(n, 70.0),
            "j1": np.full(n, -6.1),
            "j2": np.full(n, -19.9),
            "j3": np.full(n, -24.3),
            "j4": np.full(n, -1.72),
            "j5": np.full(n, -42.6),
            "j6": np.full(n, 42.63),
            "width": np.full(n, 40.0),
            "height": np.full(n, 80.0),
            "square": np.full(n, 2000.0),
            "perimeter": np.full(n, 260.0),
        }
    )


def _record_and_version() -> tuple[DataRecord, DataVersion]:
    record = DataRecord(weld_id="WLD-TEST-MM", registration_no="REG-MM-001", source="test")
    version = DataVersion(record_id=1, version_no="v1.0", action="upload")
    version.id = 1
    return record, version


def test_map_columns_multimodal_header_all_recognized():
    cm, unknown = svc.map_columns(_MULTIMODAL_HEADER)
    assert unknown == []
    assert cm["time"] == "time"
    assert cm["cur"] == "Current"
    assert cm["vol"] == "Voltage"
    assert cm["gas"] == "GasSpeed"
    assert cm["wir"] == "WireFeedSpeed"  # 别名补 WireFeedSpeed → wir
    assert cm["weld_speed"] == "WeldingSpeed"
    for i in range(1, 7):
        assert cm[f"j{i}"] == f"j{i}"
    assert cm["pool_width"] == "width"
    assert cm["pool_height"] == "height"
    assert cm["pool_area"] == "square"
    assert cm["pool_perimeter"] == "perimeter"


def test_validate_keeps_all_columns_and_adopts_numeric_unknown():
    df = _multimodal_df()
    # 追加：可数值未知列 tagX（自动保留）+ 非数值列 note（仍 unknown）
    df["tagX"] = np.full(len(df), 3.0)
    df["note"] = "demo"
    result = svc.validate_signal(df)

    assert result["overall"] in ("pass", "warn"), "非数值列仅 warn，不应 fail"
    assert result["fs"] == 1000
    cm = result["column_map"]
    assert cm["weld_speed"] == "WeldingSpeed"
    assert cm["pool_perimeter"] == "perimeter"
    assert cm["tagx"] == "tagX", "可数值未知列应按规范化表头自动保留"
    assert "tagX" not in result["unknown"]
    assert "note" in result["unknown"], "非数值列仍进 unknown（R2 warn）"
    # R3 通道覆盖：time 之外的映射列都是通道
    cover = next(r for r in result["rules"] if r["name"] == "通道覆盖")
    assert cover["status"] == "pass"
    assert "通道" in cover["message"]


def test_parquet_roundtrip_keeps_dynamic_columns():
    df = _multimodal_df()
    record, version = _record_and_version()
    cm, _unknown = svc.map_columns(_MULTIMODAL_HEADER)
    pb = svc.to_parquet_bytes(df, cm, 1000, record, version, 1, "uploads/mm.csv")

    pdf = pq.read_table(io.BytesIO(pb)).to_pandas()
    expected = {"t", "cur", "vol", "gas", "wir", "weld_speed",
                "j1", "j2", "j3", "j4", "j5", "j6",
                "pool_width", "pool_height", "pool_area", "pool_perimeter"}
    assert expected.issubset(set(pdf.columns)), f"缺列: {expected - set(pdf.columns)}"
    assert not pdf["t"].isna().any()

    ingest = SignalIngest(
        sample_rate=1000, duration=float(len(df) / 1000),
        events={}, anomalies=[], status="succeeded",
    )
    bundle = svc.bundle_from_parquet(pb, ingest, record.weld_id)
    ids = [c.id for c in bundle.channels]
    assert ids[:4] == ["cur", "vol", "gas", "wir"], "核心 4 恒在且最前"
    assert "weld_speed" in ids and "j1" in ids and "pool_area" in ids
    cur = bundle.channel("cur")
    assert cur is not None and cur.unit == "A"
    weld = bundle.channel("weld_speed")
    assert weld is not None
    assert abs(weld.values[0] - 70.0) < 1e-6
    # 扩展通道量程按实际数据推导（70 附近），不是 catalog 的宽默认
    assert weld.lo <= 70.0 <= weld.hi and (weld.hi - weld.lo) < 10


def test_field_summary_and_record_params_backfill():
    df = _multimodal_df()
    cm, _unknown = svc.map_columns(_MULTIMODAL_HEADER)
    events = {}  # 空 events → 全段稳态代表值
    summary = svc.build_field_summary(df, cm, events, 1000)
    by_id = {item["id"]: item for item in summary}
    assert by_id["cur"]["value"] == 150.0
    assert by_id["wir"]["value"] == 15.86
    assert by_id["weld_speed"]["value"] == 70.0
    assert by_id["pool_area"]["name"] == "熔池面积"
    assert len(summary) == 15  # 除 time 外 15 个通道都有代表值

    record, _ = _record_and_version()
    svc.fill_record_params(record, df, cm, events, 1000)
    assert record.wire_feed_speed == "15.86"
    assert record.welding_speed == "70.00"
