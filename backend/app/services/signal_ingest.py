"""真实信号导入（Task 18）：CSV 解析 + 校验 + 启发式事件检测 + Parquet 存储 + loader。

数据流：
```
POST /registrations/{id}/raw-files 含 .csv → 自动建 signal_ingest Job + SignalIngest(pending)
  └ 后台 executor → handler → run_ingest(session, ingest, job)
      ├ MinIO get_object(source_key) 读 CSV
      ├ _parse_csv + _validate（10 条 pass/warn/fail 规则）
      ├ overall pass/warn：_detect_events（启发式）→ _write_parquet → 行 succeeded
      └ overall fail / 异常：行 failed + error（不写 Parquet）
DSP/特征/报告 → load_signal_bundle(session, weld_id, version_id)
      ├ 命中 succeeded Parquet → bundle_from_parquet（source="real"）
      └ 否则 → signals.generate_signals（source="generated"）
```

契约要点（勿破，见 docs/API接口清单.md §3.4）：
- `SignalBundle.channels`：**真实信号为"核心 4（恒在）+ 本次 CSV 出现的全部扩展通道"**——
  核心 id 精确 `cur/vol/gas/wir`（DSP 事件/生成/特征只认核心 4），扩展通道（weld_speed/
  j1..j6/pool_* 及自动保留的数值列）逐点保留用于回放/概览；生成回退仍是纯核心 4。
  values 一维 float、长度 = duration × sample_rate；`events`/`anomalies` 结构不变（real 时
  来自启发式）。
- 未知列不再静默丢弃：可数值解析的列由 `map_columns`+`_adopt_numeric_unknowns` 自动按
  规范化表头收为通道并随 Parquet 保留；非数值列才进 `unknown`（R2 warn）。
- 导入成功后回填 `DataRecord`：`data_fields`（字段概览 JSON）+ `wire_feed_speed`/
  `welding_speed`（稳态中位数），供登记列表/详情/表单展示。
- CSV 校验**不并入** welds.py 的 15 条 `VALIDATION_RULES`（seed/测试/前端逐字一致，勿动），
  结果写 `signal_ingests.validation` 与 `job.result`。
- `source` 加法字段：`signals`/`analysis/result` 响应 data 新增 `source`，前端零改动。

坑：
- 确定性：启发式全部基于 CSV 数据本身，无随机，同文件结果可复现（测试可断言）。
- 阈值一律由 `CHANNEL_SPECS` 的 lo/hi（span=hi-lo）推导，不写死绝对数值。
- 存储延迟导入（`from app.storage import get_storage`），测试 monkeypatch。
"""

from __future__ import annotations

import io
import math
import re
from collections import OrderedDict
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from loguru import logger
from sqlmodel import Session, select

from app.models.analysis import SignalIngest
from app.models.data import DataRecord, DataVersion
from app.services import signals
from app.services.jobs import mark_failed, mark_succeeded
from app.services.signals import (
    CHANNEL_CATALOG,
    CHANNEL_SPECS,
    Channel,
    SignalBundle,
    channel_spec,
)

#: 导入文件大小上限（字节），超过直接 fail（防 get_object 全量读爆内存）。
MAX_INGEST_BYTES = 200 * 1024 * 1024

#: CSV 表头别名 → 通道 id（time 为时间列，其余为信号通道）。
#: 扩展字段（多模态分析.csv：焊接速度 / 六轴关节 / 熔池视觉几何）同样给标准别名；
#: 别名未覆盖的可数值列由 `map_columns`/`validate_signal` 按规范化表头自动保留。
_HEADER_ALIASES: dict[str, list[str]] = {
    "time": ["时间", "时间戳", "time", "timestamp", "t"],
    "cur": ["电流", "电流(a)", "电流a", "current", "current(a)", "cur", "i", "ia"],
    "vol": ["电压", "电压(v)", "电压v", "voltage", "voltage(v)", "vol", "u", "uv"],
    "gas": [
        "气体流量",
        "气体流量(l/min)",
        "gas",
        "gas(l/min)",
        "gasflow",
        "gas_flow",
        "g",
        "gasspeed",
        "gas_speed",
        "gasflowspeed",
    ],
    "wir": [
        "送丝速度",
        "送丝速度(m/min)",
        "wire",
        "wire(m/min)",
        "wire_speed",
        "wirefeedspeed",
        "wirefeed",
        "wir",
        "w",
    ],
    "weld_speed": ["焊接速度", "weld_speed", "weldspeed", "weldingspeed", "welding_speed"],
    "j1": ["j1", "关节1", "机器人关节1", "joint1", "axis1"],
    "j2": ["j2", "关节2", "机器人关节2", "joint2", "axis2"],
    "j3": ["j3", "关节3", "机器人关节3", "joint3", "axis3"],
    "j4": ["j4", "关节4", "机器人关节4", "joint4", "axis4"],
    "j5": ["j5", "关节5", "机器人关节5", "joint5", "axis5"],
    "j6": ["j6", "关节6", "机器人关节6", "joint6", "axis6"],
    "pool_width": ["width", "熔池宽度", "池宽", "pool_width", "weld_width", "melt_width"],
    "pool_height": ["height", "熔池高度", "池高", "pool_height", "weld_height", "melt_height"],
    "pool_area": ["square", "area", "熔池面积", "池面积", "pool_area", "weld_area"],
    "pool_perimeter": ["perimeter", "熔池周长", "周长", "pool_perimeter", "weld_perimeter"],
}

#: 核心信号通道（事件检测 / DSP / 生成信号 / 42 维特征只依赖这 4 路，勿改）。
_SIGNAL_IDS = ("cur", "vol", "gas", "wir")


def _norm_header(value: object) -> str:
    """表头归一化：小写、去空格、全角括号→半角（用于别名匹配）。"""
    s = str(value).lower().replace(" ", "").replace("（", "(").replace("）", ")")
    return s.strip()


_ALIAS_TO_CHANNEL: dict[str, str] = {
    _norm_header(a): cid for cid, aliases in _HEADER_ALIASES.items() for a in aliases
}


def map_columns(columns: list[str]) -> tuple[dict[str, str], list[str]]:
    """CSV 列 → 通道映射。返回 `(column_map: {通道id: CSV列名}, unknown: [未知列])`。

    `column_map` 只含识别到的列（含 time）；未知列进 `unknown`（校验 R2 处理）。
    别名未覆盖但**可数值解析**的列由 `validate_signal` 调 `_adopt_numeric_unknowns`
    按规范化表头自动收为通道——保证真实 CSV 的列不被静默丢弃。
    """
    column_map: dict[str, str] = {}
    unknown: list[str] = []
    for col in columns:
        cid = _ALIAS_TO_CHANNEL.get(_norm_header(col))
        if cid is not None and cid not in column_map:
            column_map[cid] = col
        elif cid is None:
            unknown.append(col)
    return column_map, unknown


def _adopt_numeric_unknowns(
    df: pd.DataFrame,
    column_map: dict[str, str],
    unknown: list[str],
) -> None:
    """把 unknown 中可数值解析的列按规范化表头作为额外通道收进 column_map（就地）。"""
    if not unknown:
        return
    retained: list[str] = []
    for col in unknown:
        key = _norm_header(col)
        if not key or key == "time" or key in column_map or key in _ALIAS_TO_CHANNEL:
            retained.append(col)
            continue
        try:
            numeric = pd.to_numeric(df[col], errors="coerce")
        except Exception:  # noqa: BLE001 - 解析不了视为不可导入
            retained.append(col)
            continue
        if numeric.notna().mean() > 0.5:
            column_map[key] = col
        else:
            retained.append(col)
    unknown[:] = retained


def _parse_csv(data: bytes) -> tuple[pd.DataFrame | None, str | None]:
    """解析 CSV 字节。成功返回 (df, None)；失败返回 (None, 错误信息)。"""
    try:
        df = pd.read_csv(io.BytesIO(data))
        if df.empty or len(df.columns) == 0:
            return None, "CSV 为空或无列"
        return df, None
    except Exception as exc:  # noqa: BLE001 - 解析错误统一转校验 fail
        return None, f"CSV 解析失败: {exc}"


def _parse_fs(value: str | None) -> int | None:
    """从登记 `sample_rate` 字符串解析采样率 Hz（"10 kHz"/"1kHz"/"1000"）。"""
    if not value:
        return None
    m = re.search(r"(\d+(?:\.\d+)?)\s*([kK])?[hH][zZ]?", str(value))
    if not m:
        return None
    base = float(m.group(1))
    return int(base * 1000) if m.group(2) else int(base)


def _rule(name: str, status: str, message: str) -> dict:
    return {"name": name, "status": status, "message": message}


def _time_column_to_seconds(col: pd.Series) -> pd.Series:
    """时间列 → 数值秒（供 R6 采样率推导 / R8 重复判断）。

    数值时间戳（epoch 秒/相对秒，旧用法）直接可用；否则按 ISO 8601
    时间戳（如 `2026-06-17T14:22:23.000164Z`）解析并转**相对秒**——
    R6 只用差分推 fs、R9 只用 row_count/fs 算 duration，绝对偏移无所谓，
    故 `(t - t.min()).total_seconds()` 即可，无需保留绝对时刻。
    解析不出的行保留 NaN，由调用方规则判定。
    """
    numeric = pd.to_numeric(col, errors="coerce")
    if numeric.notna().mean() > 0.8:
        return numeric
    t = pd.to_datetime(col, errors="coerce", utc=True)
    if t.notna().any():
        return (t - t.min()).dt.total_seconds()
    return numeric


def validate_signal(
    df: pd.DataFrame | None,
    record: DataRecord | None = None,
) -> dict:
    """10 条校验规则（pass/warn/fail）。返回 `{overall, rules, fs, duration, row_count, column_map, unknown}`。

    - overall = fail>0?fail : warn>0?warn : pass；pass/warn 才写 Parquet。
    - `fs` 优先从时间列推导；无时间列用 `record.sample_rate` 兜底；都无 → None。
    """
    if df is None:
        return {
            "overall": "fail",
            "rules": [_rule("文件读取", "fail", "CSV 无法解析或为空")],
            "fs": None, "duration": 0.0, "row_count": 0,
            "column_map": {}, "unknown": [],
        }
    columns = list(df.columns)
    column_map, unknown = map_columns(columns)
    _adopt_numeric_unknowns(df, column_map, unknown)
    rules: list[dict] = []
    row_count = len(df)

    # R1 文件读取
    rules.append(_rule("文件读取", "pass", f"读取 {row_count} 行"))

    # R2 表头识别（数值未知列已自动保留为通道，unknown 只剩非数值/冲突列）
    if unknown:
        rules.append(_rule("表头识别", "warn", f"非数值未知列已忽略: {', '.join(unknown[:8])}"))
    if not column_map:
        rules.append(_rule("表头识别", "fail", "未识别到任何已知列"))

    # R3 通道覆盖（time 之外的全部映射列都是信号通道）
    signal_items = [(cid, col) for cid, col in column_map.items() if cid != "time"]
    if signal_items:
        names = [col for _, col in signal_items]
        shown = ", ".join(names[:16])
        rules.append(_rule("通道覆盖", "pass", f"识别信号通道 {len(names)} 路: {shown}"))
    else:
        rules.append(_rule("通道覆盖", "fail", "未识别到任何信号通道"))

    # R4 数值类型（全部映射通道列可转 float）
    non_numeric = 0
    for cid, col in signal_items:
        non_numeric += int(
            pd.to_numeric(df[col], errors="coerce").isna().sum() - df[col].isna().sum()
        )
    if non_numeric > 0:
        rules.append(_rule("数值类型", "fail", f"{non_numeric} 个单元格非数值"))
    else:
        rules.append(_rule("数值类型", "pass", "映射列均为数值"))

    # R5 量程（仅对收录量程规格的标准通道做 lo/hi ±10% span 容差）
    out_of_range = 0
    for cid, col in signal_items:
        spec = channel_spec(cid)
        if spec is None:
            continue  # 自动保留的未知数值列无量程定义，不判量程
        span = spec["hi"] - spec["lo"]
        vals = pd.to_numeric(df[col], errors="coerce")
        out_of_range += int(((vals < spec["lo"] - 0.1 * span) | (vals > spec["hi"] + 0.1 * span)).sum())
    if out_of_range == 0:
        rules.append(_rule("量程", "pass", "全部在量程内"))
    elif out_of_range <= max(1, int(row_count * 0.01)):
        rules.append(_rule("量程", "warn", f"{out_of_range} 点超出量程容差"))
    else:
        rules.append(_rule("量程", "fail", f"{out_of_range} 点超出量程容差（>{row_count*0.01:.0f}）"))

    # R6 采样一致性 + 采样率推导
    fs: int | None = None
    time_col = column_map.get("time")
    if time_col:
        t = _time_column_to_seconds(df[time_col]).to_numpy()
        dt = np.diff(t)
        med = float(np.median(dt)) if len(dt) > 0 else 0.0
        if med > 0:
            fs = int(round(1.0 / med))
            bad = int((np.abs(dt - med) > 0.05 * med).sum())
            ratio = bad / len(dt) if len(dt) else 0.0
            if ratio <= 0.01:
                rules.append(_rule("采样一致性", "pass", f"均匀采样 fs≈{fs}Hz"))
            elif ratio <= 0.05:
                rules.append(_rule("采样一致性", "warn", f"时间步长抖动 {bad} 点（取中位数 fs≈{fs}Hz）"))
            else:
                fs = None
                rules.append(_rule("采样一致性", "fail", f"时间步长严重不规则（{bad} 点抖动）"))
        else:
            rules.append(_rule("采样一致性", "fail", "时间列无有效递增差值"))
    else:
        fs = _parse_fs(record.sample_rate if record else None)
        if fs:
            rules.append(_rule("采样一致性", "warn", f"无时间列，采用登记采样率 {fs}Hz"))
        else:
            rules.append(_rule("采样一致性", "fail", "无时间列且无法解析登记采样率"))

    # R7 空值
    nan_total = 0
    for cid, col in signal_items:
        nan_total += int(df[col].isna().sum())
    if nan_total == 0:
        rules.append(_rule("空值", "pass", "无缺失值"))
    elif nan_total <= max(1, int(row_count * 0.01)):
        rules.append(_rule("空值", "warn", f"{nan_total} 个缺失值（前向填充）"))
    else:
        rules.append(_rule("空值", "fail", f"{nan_total} 个缺失值（>{row_count*0.01:.0f}）"))

    # R8 重复时间戳
    dup = 0
    if time_col:
        dup = int(df[time_col].duplicated().sum())
    if dup == 0:
        rules.append(_rule("重复时间戳", "pass", "时间戳无重复"))
    elif dup <= max(1, int(row_count * 0.005)):
        rules.append(_rule("重复时间戳", "warn", f"{dup} 个重复时间戳（去重保留最后）"))
    else:
        rules.append(_rule("重复时间戳", "fail", f"{dup} 个重复时间戳"))

    # R9 最小点数/时长
    duration = (row_count / fs) if fs else 0.0
    if row_count >= 100 and duration >= 0.5:
        rules.append(_rule("最小数据量", "pass", f"{row_count} 行 / {duration:.2f}s"))
    else:
        rules.append(_rule("最小数据量", "fail", f"{row_count} 行 / {duration:.2f}s 不足（需 ≥100 行且 ≥0.5s）"))

    statuses = [r["status"] for r in rules]
    overall = "fail" if "fail" in statuses else ("warn" if "warn" in statuses else "pass")
    return {
        "overall": overall,
        "rules": rules,
        "fs": fs,
        "duration": round(duration, 4),
        "row_count": row_count,
        "column_map": column_map,
        "unknown": unknown,
    }


# ── 启发式 events / anomalies ─────────────────────────────────────────


def _rolling_mean(x: np.ndarray, w: int) -> np.ndarray:
    kernel = np.ones(w) / w
    return np.convolve(x, kernel, mode="same")


def detect_events(
    df: pd.DataFrame, column_map: dict[str, str], fs: int
) -> tuple[dict, list[dict]]:
    """启发式检测起弧/焊接段/收弧（events）与异常区段（anomalies）。

    阈值按信号自身幅度（p95-p10）推导，不写死绝对值，也不依赖 CHANNEL_SPECS
    量程 span——量程按真实物理范围放宽后 span 不再与信号幅度成正比，量程派生会让
    低幅信号（如 TIG 小电流）误判整个焊接段失活。主用电流，缺电流用电压。
    返回真实数据推导的 `events={arc, weld_segment:[s,e], tail}`、
    `anomalies=[{start,end,type}]`。确定性：全部基于数据本身，无随机。
    """
    n = len(df)
    t = (
        _time_column_to_seconds(df[column_map["time"]]).to_numpy()
        if "time" in column_map
        else np.arange(n) / fs
    )
    primary = column_map.get("cur") or column_map.get("vol")
    if primary is None:
        return {}, []
    x = pd.to_numeric(df[primary], errors="coerce").to_numpy(dtype=float)

    baseline = float(np.percentile(x, 10))
    span = max(float(np.percentile(x, 95)) - baseline, 1e-6)
    on_thr = baseline + 0.25 * span
    off_thr = baseline + 0.12 * span
    w = max(3, round(fs * 0.005))
    k = max(2, round(fs * 0.003))
    smooth = _rolling_mean(x, w)
    active = smooth > on_thr

    def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
        runs: list[tuple[int, int]] = []
        i = 0
        while i < len(mask):
            if mask[i]:
                j = i
                while j < len(mask) and mask[j]:
                    j += 1
                if j - i >= k:
                    runs.append((i, j - 1))
                i = j
            else:
                i += 1
        return runs

    runs = _runs(active)
    # events
    arc_t = float(t[runs[0][0]]) if runs else 0.0
    weld_run = max(runs, key=lambda r: r[1] - r[0], default=None)
    if weld_run is not None:
        weld_seg = [round(float(t[weld_run[0]]), 3), round(float(t[weld_run[1]]), 3)]
    else:
        weld_seg = [0.0, round(float(t[-1]), 3)]
    off_after = np.where((t > weld_seg[1]) & (smooth < off_thr))[0]
    tail_t = float(t[off_after[0]]) if len(off_after) else float(t[-1])
    events = {"arc": round(arc_t, 3), "weld_segment": weld_seg, "tail": round(tail_t, 3)}

    # anomalies：仅焊接段内滚动 std 超基准
    anomalies: list[dict] = []
    ws_idx = int(np.searchsorted(t, weld_seg[0]))
    we_idx = int(np.searchsorted(t, weld_seg[1], side="right"))
    if we_idx > ws_idx:
        seg = x[ws_idx:we_idx]
        W = max(3, round(fs * 0.1))
        # 边界过渡区（起弧/收弧 ramp）在居中滚动窗下横跨 idle→active，std 必然虚高，
        # 会产生伪异常段。故只在焊接段内部 [trim, -trim] 判异常，索引回推整段坐标。
        trim = W
        if len(seg) <= 2 * trim:
            return events, []
        inner = seg[trim:-trim]
        rstd = pd.Series(inner).rolling(W, center=True, min_periods=3).std().to_numpy()
        base = float(np.median(rstd[~np.isnan(rstd)])) if np.any(~np.isnan(rstd)) else 0.0
        if base > 0:
            anom_mask = rstd > 1.8 * base
            for s_, e_ in _runs(anom_mask):
                if (e_ - s_) < round(fs * 0.05):
                    continue
                off = ws_idx + trim
                a_idx = np.arange(off + s_, off + e_)
                diff = np.diff(x[a_idx])
                spike = float((np.abs(diff) > 3 * np.std(diff)).mean()) if len(diff) else 0.0
                kind = "飞溅倾向" if (len(diff) and spike > 0.05) else "电弧不稳"
                anomalies.append({
                    "start": round(float(t[a_idx[0]]), 3),
                    "end": round(float(t[a_idx[-1]]), 3),
                    "type": kind,
                })
    # 合并间距过近的相邻段，按时长取前 5
    anomalies.sort(key=lambda a: a["start"])
    merged: list[dict] = []
    for a in anomalies:
        if merged and a["start"] - merged[-1]["end"] < 0.03:
            merged[-1]["end"] = max(merged[-1]["end"], a["end"])
        else:
            merged.append(dict(a))
    merged.sort(key=lambda a: a["end"] - a["start"], reverse=True)
    return events, merged[:5]


# ── Parquet 读写 ──────────────────────────────────────────────────────


def _channel_values(
    df: pd.DataFrame, column_map: dict[str, str], n: int, fs: int
) -> dict[str, np.ndarray]:
    """构建 Parquet 列值：`t` + 核心 4 通道（缺失补零，保兼容）+ 全部额外映射通道。"""
    t = (
        _time_column_to_seconds(df[column_map["time"]]).to_numpy()
        if "time" in column_map
        else np.arange(n) / fs
    )
    data: dict[str, np.ndarray] = {"t": t.astype(float)}
    for cid in _SIGNAL_IDS:
        col = column_map.get(cid)
        data[cid] = (
            pd.to_numeric(df[col], errors="coerce").ffill().fillna(0.0).to_numpy(dtype=float)
            if col
            else np.zeros(n)
        )
    for cid, col in column_map.items():
        if cid == "time" or cid in _SIGNAL_IDS:
            continue
        data[cid] = (
            pd.to_numeric(df[col], errors="coerce").ffill().fillna(0.0).to_numpy(dtype=float)
        )
    return data


def to_parquet_bytes(
    df: pd.DataFrame,
    column_map: dict[str, str],
    fs: int,
    record: DataRecord,
    version: DataVersion,
    ingest_id: int,
    source_key: str,
) -> bytes:
    """按动态列 schema 构建 Parquet 字节并写文件级元数据（schema_version="2"）。

    列 = `t` + 核心 4（恒写，缺失补零）+ 本次 CSV 出现的全部额外通道（weld_speed/
    j1..j6/pool_* 及自动保留的数值列）。旧版（v1，固定 5 列）文件仍可被 `_parse_parquet`
    读取——核心 4 列都存在，无额外列自然返回。
    """
    n = len(df)
    data = _channel_values(df, column_map, n, fs)
    table = pa.Table.from_pydict({k: v for k, v in data.items()})
    real_channels = [cid for cid in column_map if cid != "time"]
    metadata = {
        "schema_version": "2",
        "weld_id": record.weld_id,
        "version_id": str(version.id),
        "signal_ingest_id": str(ingest_id),
        "source_object_key": source_key,
        "sample_rate": str(fs),
        "duration": str(round(n / fs, 4)),
        "channel_ids": ",".join(real_channels),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    table = table.replace_schema_metadata({k.encode(): v.encode() for k, v in metadata.items()})
    buf = io.BytesIO()
    pq.write_table(table, buf)
    return buf.getvalue()


def _data_range(values: np.ndarray) -> tuple[float, float]:
    """按数据实际 min/max 推导 (lo, hi)，供扩展/自动通道回放量程用（pad 5%）。"""
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return 0.0, 1.0
    lo = float(finite.min())
    hi = float(finite.max())
    if hi <= lo:
        pad = max(abs(hi) * 0.05, 1.0)
        return lo - pad, hi + pad
    pad = (hi - lo) * 0.05
    return lo - pad, hi + pad


def _parse_parquet(data: bytes) -> tuple[int, int, dict[str, np.ndarray]]:
    """Parquet 字节 → (点数, 元数据兜底采样率, {通道 id: float64 数组（可写 master）})。

    返回除 `t` 外的**全部存在列**（核心 4 恒在，外加额外/自动通道；缺列不再补零，由
    `_bundle_from_parsed` 对核心通道补零）。master 数组**可写**（pandas 读回可能是只读
    视图，pywt.dwt 要求可写）；调用方直接把 master 交给 DSP 前须自行 `copy()`。
    """
    table = pq.read_table(io.BytesIO(data))
    pdf = table.to_pandas()
    n = len(pdf)
    try:
        fs_meta = int(table.schema.metadata.get(b"sample_rate", b"1000"))
    except (TypeError, ValueError):
        fs_meta = 1000
    cols: dict[str, np.ndarray] = {}
    for c in pdf.columns:
        if str(c) == "t":
            continue
        cols[str(c)] = np.array(pdf[c].to_numpy(dtype=float), dtype=float, copy=True)
    return n, fs_meta, cols


#: 进程内 Parquet 解析 LRU（key=parquet_key）：`load_signal_bundle` 每次请求都重拉
#: MinIO + 反序列化 910k 点是波形缩放增量取数的最大延迟来源，缓存后往返毫秒级。
#: 值为 `_parse_parquet` 结果（master 数组），容量 4 条 × ~29MB（910k×4ch float64）。
_PARQUET_CACHE_MAX = 4
_PARQUET_CACHE: "OrderedDict[str, tuple[int, int, dict[str, np.ndarray]]]" = OrderedDict()


def _cached_parquet(parquet_key: str) -> tuple[int, int, dict[str, np.ndarray]] | None:
    """按 parquet_key 取缓存解析结果；未命中则下载解析并入缓存。存储/解析失败返回 None。"""
    hit = _PARQUET_CACHE.get(parquet_key)
    if hit is not None:
        _PARQUET_CACHE.move_to_end(parquet_key)
        return hit
    try:
        from app.storage import get_storage  # 延迟导入，测试 monkeypatch

        parsed = _parse_parquet(get_storage().get_object(parquet_key))
    except Exception:  # noqa: BLE001 - MinIO 读/解析失败交由调用方回退生成
        return None
    _PARQUET_CACHE[parquet_key] = parsed
    while len(_PARQUET_CACHE) > _PARQUET_CACHE_MAX:
        _PARQUET_CACHE.popitem(last=False)
    return parsed


def _bundle_from_parsed(
    parsed: tuple[int, int, dict[str, np.ndarray]], ingest: SignalIngest, weld_id: str
) -> SignalBundle:
    """`_parse_parquet` 结果 + ingest 行 → SignalBundle（channels 取 master 的可写副本）。

    顺序：核心 4（恒在，缺失补零）→ 收录的扩展通道（在列才含）→ 自动保留的未知通道。
    核心通道量程取 CHANNEL_SPECS；扩展/自动通道量程按数据实际 min/max 推导（_data_range）。
    """
    n, fs_meta, cols = parsed
    fs = ingest.sample_rate or fs_meta
    duration = ingest.duration or (n / fs if fs else n / 1000.0)
    channels: list[Channel] = []

    def _make_channel(channel_id: str, spec: dict | None, values: np.ndarray) -> Channel:
        # copy()：master 在缓存中跨请求共享，DSP（pywt/scipy）约定不可原地改输入，
        # 副本隔离保证缓存不被污染（memcpy ~ms 级，可忽略）。
        values = values.copy()
        if spec is not None and channel_id in _SIGNAL_IDS:
            lo, hi = spec["lo"], spec["hi"]
        else:
            lo, hi = _data_range(values)
        return Channel(
            id=channel_id,
            name=spec["name"] if spec else channel_id,
            unit=spec["unit"] if spec else "",
            values=values,
            lo=lo,
            hi=hi,
            mean=round(float(np.mean(values)), 2),
        )

    for spec in CHANNEL_SPECS:
        values = cols.get(spec["id"])
        if values is None:
            values = np.zeros(n)
        channels.append(_make_channel(spec["id"], spec, values))
    known = {spec["id"] for spec in CHANNEL_CATALOG}
    for spec in CHANNEL_CATALOG:
        cid = spec["id"]
        if cid in _SIGNAL_IDS or cid not in cols:
            continue
        channels.append(_make_channel(cid, spec, cols[cid]))
    for cid, values in cols.items():
        if cid in known:
            continue
        channels.append(_make_channel(cid, None, values))
    return SignalBundle(
        weld_id=weld_id,
        duration=duration,
        sample_rate=fs,
        channels=channels,
        events=ingest.events or {},
        anomalies=ingest.anomalies or [],
        source="real",
    )


def bundle_from_parquet(data: bytes, ingest: SignalIngest, weld_id: str) -> SignalBundle:
    """从 Parquet 字节还原 SignalBundle（source="real"）。events/anomalies 读 ingest 行。"""
    return _bundle_from_parsed(_parse_parquet(data), ingest, weld_id)


# ── loader（DSP/特征/报告统一入口） ───────────────────────────────────


def load_signal_bundle(session: Session, weld_id: str, version_id: int) -> SignalBundle:
    """读取成功导入的真实信号；缺失或损坏时阻断业务，不生成替代信号。"""
    ingest = session.exec(
        select(SignalIngest)
        .where(
            SignalIngest.version_id == version_id,
            SignalIngest.status == "succeeded",
        )
        .order_by(SignalIngest.created_at.desc(), SignalIngest.id.desc())
    ).first()
    if ingest is None:
        version = session.get(DataVersion, version_id)
        if version is not None:
            ingest = session.exec(
                select(SignalIngest)
                .join(DataVersion, DataVersion.id == SignalIngest.version_id)
                .where(
                    DataVersion.record_id == version.record_id,
                    SignalIngest.status == "succeeded",
                )
                .order_by(SignalIngest.created_at.desc(), SignalIngest.id.desc())
            ).first()
    if ingest is None or not ingest.parquet_key:
        raise ValueError("当前版本没有成功导入的真实时序信号")
    parsed = _cached_parquet(ingest.parquet_key)
    if parsed is None:
        raise ValueError("真实时序信号文件读取失败，请重新导入并核验")
    return _bundle_from_parsed(parsed, ingest, weld_id)


def load_real_signal_bundle(
    session: Session, weld_id: str, version_id: int
) -> SignalBundle | None:
    """只读取真实 Parquet；生产任务不得回退到合成信号。"""
    ingest = session.exec(
        select(SignalIngest)
        .where(
            SignalIngest.version_id == version_id,
            SignalIngest.status == "succeeded",
        )
        .order_by(SignalIngest.created_at.desc(), SignalIngest.id.desc())
    ).first()
    if ingest is None:
        version = session.get(DataVersion, version_id)
        if version is not None:
            ingest = session.exec(
                select(SignalIngest)
                .join(DataVersion, DataVersion.id == SignalIngest.version_id)
                .where(
                    DataVersion.record_id == version.record_id,
                    SignalIngest.status == "succeeded",
                )
                .order_by(SignalIngest.created_at.desc(), SignalIngest.id.desc())
            ).first()
    if ingest is None or not ingest.parquet_key:
        return None
    parsed = _cached_parquet(ingest.parquet_key)
    if parsed is None:
        return None
    return _bundle_from_parsed(parsed, ingest, weld_id)


# ── 字段概览（每条焊缝导入字段的稳态代表值） ──────────────────────────


def _steady_window(n: int, events: dict, fs: int) -> tuple[int, int]:
    """取代表值的样本窗：优先焊接段（weld_segment），否则全段。"""
    seg = (events or {}).get("weld_segment") or []
    if len(seg) == 2:
        try:
            start, end = float(seg[0]), float(seg[1])
        except (TypeError, ValueError):
            start = end = None
        if start is not None and end is not None and 0.0 <= start < end:
            i0 = max(0, min(n, int(start * fs)))
            i1 = max(i0, min(n, math.ceil(end * fs)))
            if i1 - i0 >= max(10, n // 100):
                return i0, i1
    return 0, n


def _channel_median(df: pd.DataFrame, col: str, i0: int, i1: int) -> float | None:
    """映射通道列在 [i0,i1) 内有限值的稳健中位数。"""
    vals = pd.to_numeric(df[col], errors="coerce").to_numpy(dtype=float)
    clean = vals[i0:i1]
    clean = clean[np.isfinite(clean)]
    if clean.size == 0:
        return None
    return float(np.median(clean))


def build_field_summary(
    df: pd.DataFrame, column_map: dict[str, str], events: dict, fs: int
) -> list[dict]:
    """每条焊缝导入字段概览 `[{id,name,unit,value}]`（全通道稳态代表值，用于前端展示）。"""
    n = len(df)
    i0, i1 = _steady_window(n, events, fs)
    summary: list[dict] = []
    for cid, col in column_map.items():
        if cid == "time":
            continue
        spec = channel_spec(cid)
        med = _channel_median(df, col, i0, i1)
        if med is None or not np.isfinite(med):
            continue
        summary.append(
            {
                "id": cid,
                "name": spec["name"] if spec else cid,
                "unit": spec["unit"] if spec else "",
                "value": round(med, 4),
            }
        )
    return summary


def fill_record_params(
    record: DataRecord,
    df: pd.DataFrame,
    column_map: dict[str, str],
    events: dict,
    fs: int,
) -> None:
    """导入成功后回填登记单值工艺列（送丝速度/焊接速度，取稳态中位数，2 位小数）。"""
    n = len(df)
    i0, i1 = _steady_window(n, events, fs)
    for cid, attr in (("wir", "wire_feed_speed"), ("weld_speed", "welding_speed")):
        col = column_map.get(cid)
        if col is None:
            continue
        med = _channel_median(df, col, i0, i1)
        if med is not None and np.isfinite(med):
            setattr(record, attr, f"{med:.2f}")


# ── handler 领域逻辑 ──────────────────────────────────────────────────


def run_ingest(session: Session, ingest: SignalIngest, job) -> None:
    """signal_ingest handler 领域逻辑：下载 CSV → 校验 → 启发式 → 写 Parquet → 回填行 + job。

    **自捕获异常**：任何失败把 `signal_ingests.status` 置 failed 并正常返回（executor 的
    failed 兜底会先 rollback 丢弃 handler 写过的行状态，故不能重抛）。
    """
    try:
        from app.storage import get_storage  # 延迟导入，测试 monkeypatch

        storage = get_storage()
        # 大文件预检
        try:
            size = storage.stat_object(ingest.source_object_key)
            if size > MAX_INGEST_BYTES:
                raise ValueError(f"File is too large ({size} B > {MAX_INGEST_BYTES} B limit)")
        except ValueError:
            raise
        except Exception:
            size = 0  # stat 失败不阻塞，get_object 再判

        data = storage.get_object(ingest.source_object_key)
        if len(data) > MAX_INGEST_BYTES:
            raise ValueError(f"File is too large ({len(data)} B > {MAX_INGEST_BYTES} B limit)")

        version = session.get(DataVersion, ingest.version_id)
        if version is None:
            raise ValueError(f"Data version does not exist: {ingest.version_id}")
        record = session.get(DataRecord, version.record_id) if version.record_id else None

        df, err = _parse_csv(data)
        result = validate_signal(df, record)
        validation = {"overall": result["overall"], "rules": result["rules"]}

        if result["overall"] == "fail":
            ingest.status = "failed"
            ingest.validation = validation
            ingest.error = {"message": "CSV 校验未通过", "validation": validation}
            ingest.finished_at = datetime.now(timezone.utc)
            mark_failed(session, job, {"message": "CSV 校验未通过", "validation": validation})
            return

        if df is None or result["fs"] is None:
            raise ValueError("Validation passed but the sample rate is missing; import cannot continue")

        # 校验通过（pass/warn）→ 启发式事件 + 写 Parquet
        events, anomalies = detect_events(df, result["column_map"], result["fs"])
        # 导入成功后回填登记单值工艺列与字段概览（executor 事务统一提交）
        if record is not None:
            record.data_fields = build_field_summary(
                df, result["column_map"], events, result["fs"]
            )
            fill_record_params(record, df, result["column_map"], events, result["fs"])
        session.flush()  # 拿 ingest.id 作 Parquet 键
        parquet_key = f"processed/{record.weld_id}/signals/{ingest.id}.parquet"
        pb = to_parquet_bytes(
            df, result["column_map"], result["fs"], record, version, ingest.id,
            ingest.source_object_key,
        )
        storage.upload_stream(
            parquet_key, io.BytesIO(pb), len(pb), "application/octet-stream"
        )

        ingest.status = "succeeded"
        ingest.sample_rate = result["fs"]
        ingest.duration = result["duration"]
        ingest.row_count = result["row_count"]
        ingest.column_map = result["column_map"]
        ingest.validation = validation
        ingest.parquet_key = parquet_key
        ingest.events = events
        ingest.anomalies = anomalies
        ingest.finished_at = datetime.now(timezone.utc)
        mark_succeeded(
            session, job,
            {
                "source": ingest.source_object_key,
                "parquet_key": parquet_key,
                "sample_rate": result["fs"],
                "duration": result["duration"],
                "row_count": result["row_count"],
                "events": events,
                "anomalies": anomalies,
                "validation": validation,
            },
        )
    except Exception as exc:  # noqa: BLE001 - 自捕获写 failed，勿重抛
        logger.opt(exception=True).warning(
            "signal_ingest failed: {} ({})", ingest.source_object_key, exc
        )
        session.rollback()  # 事务脏则回滚，避免 commit 失败
        ingest = session.get(SignalIngest, ingest.id)
        job = session.get(type(job), job.id)
        if ingest is not None:
            ingest.status = "failed"
            ingest.error = {"message": str(exc)}
            ingest.finished_at = datetime.now(timezone.utc)
        if job is not None:
            mark_failed(session, job, {"message": str(exc)})
