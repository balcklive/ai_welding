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
- 还原出的 `SignalBundle.channels` 必须是 4 通道、id 精确 `cur/vol/gas/wir`、values 一维 float；
  长度 = duration × sample_rate；`events`/`anomalies` 结构不变（real 时来自启发式）。
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
import re
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
from app.services.signals import CHANNEL_SPECS, Channel, SignalBundle

#: 导入文件大小上限（字节），超过直接 fail（防 get_object 全量读爆内存）。
MAX_INGEST_BYTES = 200 * 1024 * 1024

#: CSV 表头别名 → 通道 id（time 为时间列，其余为信号通道）。
_HEADER_ALIASES: dict[str, list[str]] = {
    "time": ["时间", "时间戳", "time", "timestamp", "t"],
    "cur": ["电流", "电流(a)", "电流a", "current", "current(a)", "cur", "i", "ia"],
    "vol": ["电压", "电压(v)", "电压v", "voltage", "voltage(v)", "vol", "u", "uv"],
    "gas": ["气体流量", "气体流量(l/min)", "gas", "gas(l/min)", "gasflow", "gas_flow", "g"],
    "wir": ["送丝速度", "送丝速度(m/min)", "wire", "wire(m/min)", "wire_speed", "wir", "w"],
}

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
    rules: list[dict] = []
    row_count = len(df)

    # R1 文件读取
    rules.append(_rule("文件读取", "pass", f"读取 {row_count} 行"))

    # R2 表头识别
    if unknown:
        rules.append(_rule("表头识别", "warn", f"未知列已忽略: {', '.join(unknown[:8])}"))
    if not column_map:
        rules.append(_rule("表头识别", "fail", "未识别到任何已知列"))

    # R3 通道覆盖
    signal_cols = [column_map[c] for c in _SIGNAL_IDS if c in column_map]
    if signal_cols:
        rules.append(_rule("通道覆盖", "pass", f"识别信号通道: {', '.join(signal_cols)}"))
    else:
        rules.append(_rule("通道覆盖", "fail", "未识别到任何信号通道 (cur/vol/gas/wir)"))

    # R4 数值类型（映射列全部可转 float）
    non_numeric = 0
    for cid in _SIGNAL_IDS:
        if cid in column_map:
            col = column_map[cid]
            non_numeric += int(pd.to_numeric(df[col], errors="coerce").isna().sum() - df[col].isna().sum())
    if non_numeric > 0:
        rules.append(_rule("数值类型", "fail", f"{non_numeric} 个单元格非数值"))
    else:
        rules.append(_rule("数值类型", "pass", "映射列均为数值"))

    # R5 量程（lo/hi ±10% span 容差）
    out_of_range = 0
    for cid in _SIGNAL_IDS:
        if cid in column_map:
            spec = next(s for s in CHANNEL_SPECS if s["id"] == cid)
            span = spec["hi"] - spec["lo"]
            vals = pd.to_numeric(df[column_map[cid]], errors="coerce")
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
        t = pd.to_numeric(df[time_col], errors="coerce").to_numpy()
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
    for cid in _SIGNAL_IDS:
        if cid in column_map:
            nan_total += int(df[column_map[cid]].isna().sum())
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
    返回形状与生成器一致：`events={arc, weld_segment:[s,e], tail}`、
    `anomalies=[{start,end,type}]`。确定性：全部基于数据本身，无随机。
    """
    n = len(df)
    t = (
        pd.to_numeric(df[column_map["time"]], errors="coerce").to_numpy()
        if "time" in column_map
        else np.arange(n) / fs
    )
    primary = column_map.get("cur") or column_map.get("vol")
    if primary is None:
        return signals.EVENTS, []
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
    t = (
        pd.to_numeric(df[column_map["time"]], errors="coerce").to_numpy()
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
    """按列 schema `t,cur,vol,gas,wir` 构建 Parquet 字节并写文件级元数据。"""
    n = len(df)
    data = _channel_values(df, column_map, n, fs)
    table = pa.Table.from_pydict({k: v for k, v in data.items()})
    real_channels = [cid for cid in _SIGNAL_IDS if cid in column_map]
    metadata = {
        "schema_version": "1",
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


def bundle_from_parquet(data: bytes, ingest: SignalIngest, weld_id: str) -> SignalBundle:
    """从 Parquet 字节还原 SignalBundle（source="real"）。events/anomalies 读 ingest 行。"""
    table = pq.read_table(io.BytesIO(data))
    pdf = table.to_pandas()
    fs = ingest.sample_rate or int(table.schema.metadata.get(b"sample_rate", b"1000"))
    duration = ingest.duration or (len(pdf) / fs if fs else len(pdf) / 1000.0)
    channels: list[Channel] = []
    for spec in CHANNEL_SPECS:
        cid = spec["id"]
        # np.array(..., copy=True)：pandas/parquet 读回可能是只读视图，pywt.dwt 要求可写
        values = (
            np.array(pdf[cid].to_numpy(dtype=float), dtype=float, copy=True)
            if cid in pdf.columns
            else np.zeros(len(pdf))
        )
        channels.append(
            Channel(
                id=cid,
                name=spec["name"],
                unit=spec["unit"],
                values=values,
                lo=spec["lo"],
                hi=spec["hi"],
                mean=round(float(np.mean(values)), 2),
            )
        )
    return SignalBundle(
        weld_id=weld_id,
        duration=duration,
        sample_rate=fs,
        channels=channels,
        events=ingest.events or dict(signals.EVENTS),
        anomalies=ingest.anomalies or [],
        source="real",
    )


# ── loader（DSP/特征/报告统一入口） ───────────────────────────────────


def load_signal_bundle(session: Session, weld_id: str, version_id: int) -> SignalBundle:
    """优先读真实信号 Parquet；无成功导入则回退确定性生成（source="generated"）。

    供 `analysis.py` 的 signals/result/mode/features 与 `reports.py` 分析报告调用，
    返回形状与 `signals.generate_signals` 完全一致，前端零改动。
    """
    ingest = session.exec(
        select(SignalIngest)
        .where(
            SignalIngest.version_id == version_id,
            SignalIngest.status == "succeeded",
        )
        .order_by(SignalIngest.created_at.desc(), SignalIngest.id.desc())
    ).first()
    if ingest is None or not ingest.parquet_key:
        return signals.generate_signals(weld_id)
    try:
        from app.storage import get_storage  # 延迟导入，测试 monkeypatch

        data = get_storage().get_object(ingest.parquet_key)
        return bundle_from_parquet(data, ingest, weld_id)
    except Exception:  # noqa: BLE001 - MinIO 读失败回退生成，不阻塞分析
        logger.opt(exception=True).warning(
            "读取真实信号 Parquet 失败，回退生成信号: {}", ingest.parquet_key
        )
        return signals.generate_signals(weld_id)


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
                raise ValueError(f"文件过大（{size} B > {MAX_INGEST_BYTES} B 上限）")
        except ValueError:
            raise
        except Exception:
            size = 0  # stat 失败不阻塞，get_object 再判

        data = storage.get_object(ingest.source_object_key)
        if len(data) > MAX_INGEST_BYTES:
            raise ValueError(f"文件过大（{len(data)} B > {MAX_INGEST_BYTES} B 上限）")

        version = session.get(DataVersion, ingest.version_id)
        if version is None:
            raise ValueError(f"数据版本不存在: {ingest.version_id}")
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
            raise ValueError("校验通过但缺少采样率，无法继续导入")

        # 校验通过（pass/warn）→ 启发式事件 + 写 Parquet
        events, anomalies = detect_events(df, result["column_map"], result["fs"])
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
            "signal_ingest 失败: {} ({})", ingest.source_object_key, exc
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
