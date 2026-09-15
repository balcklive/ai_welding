"""一次性运维：按新的 detect_events 重算已入库的 signal_ingests.events/anomalies。

背景（2026-09-15）：`detect_events` 修了「短路过渡电流纹波把焊接段切碎」——取最长
active 段前先合并间隔 <100ms 的相邻段。但 **events 只在导入时算一次并存进
`signal_ingests` 行**（`load_signal_bundle` 直接读该行，不重算），且
`POST /registrations/{id}/raw-files` 对已存在的 `(version_id, source_object_key)`
一律 409 不重跑。于是线上已有导入仍显示旧结果（如真实 CSV 16.2s 却报「有效焊接段
0.13s」），需要本脚本按新算法重算。

连带重算 `DataRecord` 的 `data_fields` 与 `wire_feed_speed`/`welding_speed`——它们
都取 `events.weld_segment` 作稳态窗口（`_steady_window`），events 变了必然要跟着变。

CSV 从 MinIO 按 `source_object_key` 重读，`column_map`/`sample_rate` 沿用行内已存的
值（与当初导入完全同一套输入），无需重新校验。

用法：`uv run python scripts/backfill_ingest_events.py [--weld WLD-...] [--dry-run]`
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend/ 进 sys.path

from sqlmodel import Session, select  # noqa: E402

from app.core.db import engine  # noqa: E402
from app.models.analysis import SignalIngest  # noqa: E402
from app.models.data import DataRecord, DataVersion  # noqa: E402
from app.services.signal_ingest import (  # noqa: E402
    _parse_csv,
    build_field_summary,
    detect_events,
    fill_record_params,
)


def _fmt(events: dict | None) -> str:
    if not events:
        return "—"
    seg = events.get("weld_segment") or [0, 0]
    return f"起弧 {events.get('arc')} / 焊接段 {seg[0]}–{seg[1]}（{seg[1] - seg[0]:.3f}s）/ 收弧 {events.get('tail')}"


def main(weld: str | None, dry_run: bool) -> int:
    from app.storage import get_storage

    storage = get_storage()
    scanned = changed = 0
    with Session(engine) as session:
        rows = session.exec(
            select(SignalIngest).where(SignalIngest.status == "succeeded")
        ).all()
        for ingest in rows:
            version = session.get(DataVersion, ingest.version_id)
            record = (
                session.get(DataRecord, version.record_id)
                if version is not None and version.record_id
                else None
            )
            weld_id = record.weld_id if record is not None else "?"
            if weld is not None and weld_id != weld:
                continue
            scanned += 1
            if not ingest.column_map or not ingest.sample_rate:
                print(f"[skip] {weld_id} ingest#{ingest.id} 缺 column_map/sample_rate")
                continue

            df, err = _parse_csv(storage.get_object(ingest.source_object_key))
            if df is None:
                print(f"[skip] {weld_id} ingest#{ingest.id} CSV 解析失败：{err}")
                continue

            events, anomalies = detect_events(df, ingest.column_map, ingest.sample_rate)
            if events == (ingest.events or {}) and anomalies == (ingest.anomalies or []):
                print(f"[same] {weld_id} ingest#{ingest.id} 无变化")
                continue

            changed += 1
            print(f"[diff] {weld_id} ingest#{ingest.id}")
            print(f"       旧: {_fmt(ingest.events)}")
            print(f"       新: {_fmt(events)}")
            if dry_run:
                continue

            ingest.events = events
            ingest.anomalies = anomalies
            if record is not None:
                record.data_fields = build_field_summary(
                    df, ingest.column_map, events, ingest.sample_rate
                )
                fill_record_params(record, df, ingest.column_map, events, ingest.sample_rate)
            session.add(ingest)

        if dry_run:
            session.rollback()
        else:
            session.commit()
    print(f"{'[dry-run] ' if dry_run else ''}扫描 {scanned} 条 succeeded，{changed} 条需要更新")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--weld", help="只处理该焊缝 ID（默认全部）")
    parser.add_argument("--dry-run", action="store_true", help="只预览不提交")
    args = parser.parse_args()
    raise SystemExit(main(args.weld, args.dry_run))
