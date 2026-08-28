"""生产样本分段任务。

任务只消费成功导入的真实时序信号；目标检测额外消费真实视频并抽取窗口中点帧。
预览和执行共用 ``app.services.splitting`` 的窗口规则，避免数量和边界漂移。
"""

from __future__ import annotations

import io
import json

from loguru import logger
from sqlmodel import Session, select

from app.jobs.executor import register_handler
from app.models.analysis import Sample, SplitTask
from app.models.data import DataRecord, DataVersion
from app.models.jobs import Job
from app.services import media_probe, splitting
from app.services.jobs import mark_succeeded
from app.storage import get_storage


@register_handler("split")
def handle(job_id: int, session: Session) -> None:
    task = session.exec(select(SplitTask).where(SplitTask.job_id == job_id)).first()
    job = session.get(Job, job_id)
    if task is None or job is None:
        raise ValueError(f"Split task does not exist: job_id={job_id}")
    record = session.exec(
        select(DataRecord).join(DataVersion, DataVersion.record_id == DataRecord.id)
        .where(DataVersion.id == task.version_id)
    ).first()
    version = session.get(DataVersion, task.version_id)
    if record is None or version is None:
        raise ValueError("Split task input version does not exist")

    bundle = splitting.load_input(session, record, version)
    rules = dict(task.rules or {})
    bounds = splitting.event_bounds(
        bundle,
        rules.get("event_start"),
        rules.get("event_end"),
        float(rules.get("keep_event_buffer") or 0),
    )
    windows = splitting.build_windows(
        duration=bundle.duration,
        sample_rate=bundle.sample_rate,
        window_frames=int(rules["fixed_rate"]),
        stride_frames=int(rules["stride"]),
        event_bounds=bounds,
    )
    storage = get_storage()
    video_key = next((key for key in version.object_keys or [] if key.lower().endswith((".mp4", ".mov", ".avi", ".mkv", ".webm"))), None)
    video_bytes = storage.get_object(video_key) if task.task_format == "目标检测" and video_key else None
    uploaded: list[str] = []
    try:
        for index, window in enumerate(windows, start=1):
            metadata = {
                "sample_index": index,
                "window_start": window.start,
                "window_end": window.end,
                "frame_start": window.frame_start,
                "frame_end": window.frame_end,
                "source_version_id": version.id,
                "task_format": task.task_format,
            }
            if task.task_format == "目标检测":
                if not video_bytes:
                    raise splitting.SplitInputError("目标检测需要真实视频输入")
                _, frames = media_probe.analyze_video(video_bytes, [(f"sample_{index}", (window.start + window.end) / 2)])
                if not frames:
                    raise splitting.SplitInputError(f"无法抽取第 {index} 个窗口的视频帧")
                image_key = f"processed/{record.weld_id}/split/{task.id}/{index:06d}.jpg"
                image_bytes = frames[0]["bytes"]
                storage.upload_stream(image_key, io.BytesIO(image_bytes), len(image_bytes), "image/jpeg")
                uploaded.append(image_key)
                metadata["image_key"] = image_key
                object_keys = [image_key]
            else:
                csv_key = f"processed/{record.weld_id}/split/{task.id}/{index:06d}.csv"
                csv_bytes = splitting.signal_window_csv(bundle, window)
                storage.upload_stream(csv_key, io.BytesIO(csv_bytes), len(csv_bytes), "text/csv")
                uploaded.append(csv_key)
                object_keys = [csv_key]
            json_key = f"processed/{record.weld_id}/split/{task.id}/{index:06d}.json"
            json_bytes = json.dumps(metadata, ensure_ascii=False, sort_keys=True).encode("utf-8")
            storage.upload_stream(json_key, io.BytesIO(json_bytes), len(json_bytes), "application/json")
            uploaded.append(json_key)
            session.add(Sample(split_task_id=task.id, frame_no=index, object_keys=[*object_keys, json_key], meta=metadata))
            if index % 20 == 0 or index == len(windows):
                job.progress = round(index / len(windows) * 100)
                session.commit()
    except Exception:
        for key in reversed(uploaded):
            try:
                storage.delete_object(key)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to clean split artifact {}: {}", key, exc)
        raise

    task.sample_count = len(windows)
    task.rules = {**rules, "event_bounds": list(bounds)}
    session.add(task)
    result = {
        "sample_count": len(windows),
        "task_format": task.task_format,
        "rules": task.rules,
        "samples": [
            {"id": sample.id, "frame_no": sample.frame_no, "object_keys": sample.object_keys}
            for sample in session.exec(select(Sample).where(Sample.split_task_id == task.id).order_by(Sample.id)).all()[:100]
        ],
    }
    mark_succeeded(session, job, result)
