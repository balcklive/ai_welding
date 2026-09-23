"""生产样本分段任务。

只消费成功导入的真实时序信号。**按 `rules_version` 分流**（设计 §3.4）：

- `>= 3`：时间统一的多模态样本——秒级窗口 + 经坐标映射派生各模态引用（`_run_v3`）。
  产物是**多模态样本包**，不再有"目标检测/时序分类"的二选一。
- `<= 2`：历史口径（`_run_legacy`）。保留是为了**让失败的旧任务仍能重试**——
  历史任务不自动重算，但重试时必须按它当时的规则产出，不能拿 v3 去重切。

预览与执行共用 `app.services.splitting` 的窗口算法（`build_time_windows`），
保证"预览 207、执行也是 207"。
"""

from __future__ import annotations

import io
import json
import math

from loguru import logger
from PIL import Image
from sqlmodel import Session, select

from app.jobs.executor import register_handler
from app.models.analysis import Sample, SplitTask
from app.models.data import DataRecord, DataVersion
from app.models.jobs import Job
from app.services import alignment, media_probe, splitting
from app.services.jobs import mark_succeeded
from app.services.welds import reuse_or_create_version
from app.storage import get_storage

#: 旧口径的视频扩展名（v3 的取键在 `splitting.resolve_coordinate_mapping` 里）
_VIDEO_EXTS = (".mp4", ".mov", ".avi", ".mkv", ".webm")


def _rule_seconds(rules: dict, sample_rate: int) -> tuple[float, float]:
    """**旧口径专用**：规则里的窗口长度与步长（秒）。

    `rules_version >= 2` 的任务规则以秒为准（`window_seconds`/`stride_seconds`）；更早的
    任务（没有这两个键）按"采样点数 ÷ 采样率"换算，结果与当时的实现一致，所以旧任务
    重试不会改变分片结果。
    """
    window_seconds = rules.get("window_seconds")
    stride_seconds = rules.get("stride_seconds")
    if window_seconds and stride_seconds:
        return float(window_seconds), float(stride_seconds)
    legacy_window = max(1, int(rules.get("fixed_rate") or 1))
    legacy_stride = max(1, int(rules.get("stride") or legacy_window))
    return legacy_window / sample_rate, legacy_stride / sample_rate


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

    rules = dict(task.rules or {})
    if int(rules.get("rules_version") or 1) >= splitting.RULES_VERSION:
        _run_v3(session, task, job, record, version, rules)
    else:
        _run_legacy(session, task, job, record, version, rules)


# ── v3：时间统一的多模态样本 ─────────────────────────────────────────


def _run_v3(session: Session, task: SplitTask, job: Job, record: DataRecord,
            version: DataVersion, rules: dict) -> None:
    """按 v3 规则切窗并生成多模态样本包（设计 §6.1/§6.3）。

    Job 只负责编排：建 `Sample` 行、上传产物、更新进度、失败回滚；**不做任何时间换算**
    ——换算全在 `splitting.map_window_to_modalities` 里，且预览走的是同一个函数。
    """
    bundle = splitting.load_input(session, record, version)
    mapping = splitting.resolve_coordinate_mapping(session, record, version, bundle)
    if rules.get("mapping_hash") and rules["mapping_hash"] != splitting.mapping_hash(mapping):
        # 建任务之后标定又变了。**照常按当时 token 的规则切**（任务已受理），但如实告警：
        # 这批切片的模态引用与用户确认预览时看到的不完全一致。
        logger.warning(
            "Split task {}: mapping changed after preview ({} -> {}); cutting with current mapping",
            task.id, rules["mapping_hash"], splitting.mapping_hash(mapping),
        )
    bounds = tuple(float(x) for x in (rules.get("event_bounds") or []))
    windows = splitting.build_time_windows(
        duration=bundle.duration,
        sample_rate=bundle.sample_rate,
        window_seconds=float(rules["window_seconds"]),
        stride_seconds=float(rules["stride_seconds"]),
        event_bounds=bounds,
        tail_policy=str(rules.get("tail_policy") or "drop"),
    )
    storage = get_storage()
    base = f"processed/{record.weld_id}/split/{task.id}"
    uploaded: list[str] = []
    # 逐段视频代表帧：与预览走**同一个** `splitting.representative_frame_time`，
    # 所以样本里存的那一帧就是预览里显示的那一帧（设计 §6.2 的"预览 == 产物"）。
    frames = _extract_video_frames(storage, record, task, mapping, windows)
    uploaded.extend(frames.values())
    try:
        for window in windows:
            crop_key = _crop_seam_image(storage, record, task, window, mapping)
            if crop_key:
                uploaded.append(crop_key)
            frame_key = frames.get(window.index)
            manifest = splitting.map_window_to_modalities(
                window,
                mapping=mapping,
                sample_rate=bundle.sample_rate,
                weld_id=record.weld_id,
                version_id=version.id,
                crop_key=crop_key,
                video_frame_key=frame_key,
            )
            object_keys = [key for key in (frame_key, crop_key) if key]
            # 单样本 JSON 让一个切片能独立读取（设计 §6.3），与 manifest.json 的清单互为冗余
            sample_json_key = f"{base}/samples/{window.index:06d}.json"
            sample_json = json.dumps(manifest, ensure_ascii=False, sort_keys=True).encode("utf-8")
            storage.upload_stream(
                sample_json_key, io.BytesIO(sample_json), len(sample_json), "application/json"
            )
            uploaded.append(sample_json_key)
            session.add(Sample(
                split_task_id=task.id,
                frame_no=window.index,
                start_time=window.start,
                end_time=window.end,
                object_keys=[*object_keys, sample_json_key],
                meta=manifest,
            ))
            if window.index % 20 == 0 or window.index == len(windows):
                job.progress = round(window.index / len(windows) * 100)
                session.commit()
    except Exception:
        for key in reversed(uploaded):
            try:
                storage.delete_object(key)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to clean split artifact {}: {}", key, exc)
        raise

    task.sample_count = len(windows)
    task.rules = {**rules, "event_bounds": list(bounds), "sample_count": len(windows)}
    session.add(task)

    slice_rows = session.exec(
        select(Sample).where(Sample.split_task_id == task.id).order_by(Sample.id)
    ).all()
    manifest_key = f"{base}/manifest.json"
    manifest = {
        "schema_version": 3,
        "task_id": task.id,
        "rules_version": splitting.RULES_VERSION,
        "rules": task.rules,
        "source_version_id": version.id,
        "mapping_hash": splitting.mapping_hash(mapping),
        "mapping": mapping,
        "sample_count": len(windows),
        "samples": [
            {
                "sample_id": row.id,
                "sample_index": row.frame_no,
                "start_time": row.start_time,
                "end_time": row.end_time,
                "object_keys": row.object_keys,
            }
            for row in slice_rows
        ],
    }
    manifest_bytes = json.dumps(manifest, ensure_ascii=False, sort_keys=True).encode("utf-8")
    storage.upload_stream(
        manifest_key, io.BytesIO(manifest_bytes), len(manifest_bytes), "application/json"
    )

    source_keys = list(version.object_keys or [])
    segmentation_version, created = reuse_or_create_version(
        session,
        record,
        action="样本分段",
        note=f"分段任务 #{task.id} 自动生成（{len(windows)} 个多模态样本，规则版本 {splitting.RULES_VERSION}）",
        object_keys=[*source_keys, *([manifest_key] if manifest_key not in source_keys else [])],
        operator="算法任务",
    )
    if not created:
        logger.info("Split task {} reused existing 样本分段 version {}", task.id, segmentation_version.version_no)

    mark_succeeded(session, job, {
        "sample_count": len(windows),
        "rules_version": splitting.RULES_VERSION,
        "schema_version": 3,
        "rules": task.rules,
        "mapping_hash": splitting.mapping_hash(mapping),
        "manifest_key": manifest_key,
    })


def _extract_video_frames(storage, record: DataRecord, task: SplitTask, mapping: dict,
                          windows: list) -> dict[int, str]:
    """为每个窗口抽**本段自己的**视频代表帧，返回 `{段号: 对象键}`。

    时刻由 `splitting.representative_frame_time` 给（窗口中点），换算到视频轴由
    `media_probe.analyze_video(seek_offset=)` 做——**预览用的是同一条链路**，所以"预览里
    看到的那一帧"就是"样本里存下来的那一帧"。

    视频是增强模态：整批抽帧失败（视频不可读/超限/ffmpeg 不可用）只告警并返回空，
    样本照常成立，manifest 里 `video.frame` 如实记不可用原因——与 `_crop_seam_image` 同一取舍。
    `ponytail:` 每个窗口一次 ffmpeg 调用（与预览同量级）；窗口上千时改批量 seek 再优化。
    """
    video = (mapping.get("mappings") or {}).get("video") or {}
    video_key = video.get("object_key")
    if not video.get("available") or not video_key:
        return {}
    points = [
        (str(window.index), t)
        for window in windows
        if (t := splitting.representative_frame_time(window, video)) is not None
    ]
    if not points:
        return {}
    try:
        data = storage.get_object(video_key)
        if len(data) > media_probe.MAX_VIDEO_PROBE_BYTES:
            raise ValueError(f"视频 {len(data)} 字节超过抽帧上限 {media_probe.MAX_VIDEO_PROBE_BYTES}")
        _meta, frames = media_probe.analyze_video(
            data, points, seek_offset=float(video.get("offset_seconds") or 0.0)
        )
    except Exception as exc:  # noqa: BLE001 - 增强模态，失败不阻断样本产出
        logger.warning("Split video frame extraction failed, samples kept without frames: {}", exc)
        return {}
    keys: dict[int, str] = {}
    for frame in frames:
        # 键名带 `.frame.jpg` 后缀，避免与同目录的焊缝图片切片 `{段号:06d}.jpg` 互相覆盖
        key = f"processed/{record.weld_id}/split/{task.id}/samples/{int(frame['event']):06d}.frame.jpg"
        try:
            storage.upload_stream(key, io.BytesIO(frame["bytes"]), len(frame["bytes"]), "image/jpeg")
        except Exception as exc:  # noqa: BLE001 - 同上
            logger.warning("Split video frame upload failed for sample {}: {}", frame["event"], exc)
            continue
        keys[int(frame["event"])] = key
    return keys


def _crop_seam_image(storage, record: DataRecord, task: SplitTask, window, mapping: dict) -> str | None:
    """按 ROI 投影裁出本窗的焊缝图片条带，返回对象键；**任何失败只告警返回 None**。

    焊缝图片是增强模态——信号段才是样本主体，缺了它样本仍然成立，故这里刻意不抛：
    让一次图片解码失败把整个分段任务打成 failed，是把可降级的问题升级成了不可用（设计 §6.1）。
    """
    seam = (mapping.get("mappings") or {}).get("seam_image") or {}
    roi = seam.get("roi")
    if not seam.get("available") or not roi:
        return None
    manifest = splitting.map_window_to_modalities(
        window, mapping=mapping, sample_rate=1, weld_id=record.weld_id, version_id=0
    )
    span = manifest["seam_image"].get("spatial_range")
    if not span:
        return None
    roi_x, roi_y = float(roi["x"]), float(roi["y"])
    roi_w, roi_h = float(roi["w"]), float(roi["h"])
    left = max(int(math.floor(min(span["start_px"], span["end_px"]))), int(roi_x))
    right = min(int(math.ceil(max(span["start_px"], span["end_px"]))), int(roi_x + roi_w))
    if right - left < 1:
        return None
    try:
        data = storage.get_object(seam["object_key"])
        with Image.open(io.BytesIO(data)) as image:
            crop = image.convert("RGB").crop((left, int(roi_y), right, int(roi_y + roi_h)))
            buffer = io.BytesIO()
            crop.save(buffer, format="JPEG", quality=88)
        payload = buffer.getvalue()
    except Exception as exc:  # noqa: BLE001 - 图片是增强模态，失败不阻断样本
        logger.warning("Seam image crop failed, sample kept without image: {}", exc)
        return None
    key = f"processed/{record.weld_id}/split/{task.id}/samples/{window.index:06d}.jpg"
    try:
        storage.upload_stream(key, io.BytesIO(payload), len(payload), "image/jpeg")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Seam image upload failed, sample kept without image: {}", exc)
        return None
    return key


# ── <=2：历史口径（保留以便旧任务重试） ──────────────────────────────


def _run_legacy(session: Session, task: SplitTask, job: Job, record: DataRecord,
                version: DataVersion, rules: dict) -> None:
    """历史任务（`rules_version <= 2`）的原有口径，行为**逐字保留**。

    历史任务不自动重算，但 `failed` 的任务允许重试（executor 会清 `active_request_key`）——
    重试必须按它当时的规则产出，不能拿 v3 的多模态样本去覆盖。
    """
    bundle = splitting.load_input(session, record, version)
    bounds = splitting.resolve_effective_range(
        bundle,
        rules.get("event_start"),
        rules.get("event_end"),
        float(rules.get("keep_event_buffer") or 0),
    )
    window_seconds, stride_seconds = _rule_seconds(rules, bundle.sample_rate)
    windows = splitting.build_time_windows(
        duration=bundle.duration,
        sample_rate=bundle.sample_rate,
        window_seconds=window_seconds,
        stride_seconds=stride_seconds,
        event_bounds=(bounds["start"], bounds["end"]),
    )
    storage = get_storage()
    video_key = next(
        (key for key in version.object_keys or [] if str(key).lower().endswith(_VIDEO_EXTS)), None
    )
    video_bytes = storage.get_object(video_key) if task.task_format == "目标检测" and video_key else None
    # 统一坐标：视频零点取该焊缝 v1.0 的标定，走与对齐服务**同一个 resolver**
    seek_offset = alignment.calibration_offset_seconds(
        alignment.resolve_calibration(session, record)
    )
    uploaded: list[str] = []
    try:
        for index, window in enumerate(windows, start=1):
            metadata = {
                "sample_index": index,
                "window_start": window.start,
                "window_end": window.end,
                # 注意：这两个是**信号采样点下标**（历史字段名），视频帧号见 video_frame_no
                "frame_start": window.frame_start,
                "frame_end": window.frame_end,
                "window_seconds": window.window_seconds,
                "source_version_id": version.id,
                "task_format": task.task_format,
                # T11/D16-A：标出产出这条切片的规则版本，供"新旧切片共存"时区分口径。
                "rules_version": rules.get("rules_version", 1),
            }
            # T10：视频帧号取**窗口中点**对应的帧（窗口本身按秒算；没有 fps 就不记）。
            # 统一坐标：窗口的秒是**信号时间**，须先按 `t_video = t_signal - offset` 换算到
            # 视频轴再乘帧率。换算后仍为负说明整段落在视频开始之前 → 本窗没有视频内容，不记。
            fps = rules.get("video_fps")
            if isinstance(fps, (int, float)) and fps > 0:
                v_start = (window.start - seek_offset) * fps
                v_end = (window.end - seek_offset) * fps
                if v_end > 0:
                    metadata["video_frame_start"] = max(0, int(v_start))
                    metadata["video_frame_no"] = max(0, int((v_start + v_end) / 2))
                    metadata["video_frame_end"] = int(v_end)
            if task.task_format == "目标检测":
                if not video_bytes:
                    raise splitting.SplitInputError("目标检测需要真实视频输入")
                _, frames = media_probe.analyze_video(
                    video_bytes,
                    [(f"sample_{index}", (window.start + window.end) / 2)],
                    seek_offset=seek_offset,
                )
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
    task.rules = {**rules, "event_bounds": [bounds["start"], bounds["end"]]}
    session.add(task)

    slice_rows = session.exec(
        select(Sample).where(Sample.split_task_id == task.id).order_by(Sample.id)
    ).all()
    manifest_key = f"processed/{record.weld_id}/split/{task.id}/manifest.json"
    manifest = {
        "task_id": task.id,
        "task_format": task.task_format,
        "rules": task.rules,
        "rules_version": rules.get("rules_version", 1),
        "sample_count": len(windows),
        "slices": [
            {"sample_id": row.id, "frame_no": row.frame_no, "object_keys": row.object_keys}
            for row in slice_rows
        ],
    }
    manifest_bytes = json.dumps(manifest, ensure_ascii=False, sort_keys=True).encode("utf-8")
    storage.upload_stream(manifest_key, io.BytesIO(manifest_bytes), len(manifest_bytes), "application/json")
    source_keys = list(version.object_keys or [])
    segmentation_version, created = reuse_or_create_version(
        session,
        record,
        action="样本分段",
        note=f"分段任务 #{task.id} 自动生成（{len(windows)} 个切片，规则版本 {rules.get('rules_version', 1)}）",
        object_keys=[*source_keys, *[key for key in (manifest_key,) if key not in source_keys]],
        operator="算法任务",
    )
    if not created:
        logger.info(
            "Split task {} reused the existing 样本分段 version {}", task.id, segmentation_version.version_no
        )
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
