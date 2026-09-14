"""特征提取 Job handler：执行真实输入读取、特征计算、结果落库与产物文件（T16）。"""

import hashlib
import io
import json
from datetime import datetime, timezone

from loguru import logger

from sqlmodel import Session, select

from app.api.v1.analysis import (
    _load_real_audio_features,
    _load_real_vision_features,
)
from app.core.audit import write_audit
from app.core.config import settings
from app.jobs.executor import register_handler
from app.models.analysis import FeatureExtraction
from app.models.data import DataRecord, DataVersion
from app.models.jobs import Job
from app.services import features, signal_ingest
from app.storage import get_storage
from app.services.jobs import mark_succeeded
from app.services.welds import reuse_or_create_version


@register_handler("feature_extraction")
def handle(job_id: int, session: Session) -> None:
    job = session.get(Job, job_id)
    if job is None:
        raise ValueError(f"Job does not exist: id={job_id}")
    request = (job.result or {}).get("request") or {}
    weld_id = request.get("weld_id")
    version_id = request.get("version_id")
    if not isinstance(weld_id, str) or not isinstance(version_id, int):
        raise ValueError("feature extraction job request is invalid")
    record = session.exec(select(DataRecord).where(DataRecord.weld_id == weld_id)).first()
    version = session.get(DataVersion, version_id)
    if record is None or version is None:
        raise ValueError("特征提取输入数据不存在")

    bundle = signal_ingest.load_signal_bundle(session, weld_id, version_id)
    job.progress = 20
    session.commit()
    ts = {chan.id: features.ts_features(chan.values, fs=bundle.sample_rate) for chan in bundle.channels}
    job.progress = 45
    session.commit()
    vision, vision_source = _load_real_vision_features(version)
    audio, audio_source = _load_real_audio_features(version)
    job.progress = 75
    session.commit()
    normalization = request.get("normalization", "无")
    output_format = request.get("format", "JSON")
    unified = features.unify(ts, vision, audio, normalization, output_format)
    modality_status = {
        "timeseries": "real" if bundle.source == "real" else "generated",
        "vision": vision_source,
        "audio": audio_source,
    }
    unified["modality_status"] = modality_status
    missing = [key for key, value in modality_status.items() if value == "missing"]
    non_production = [key for key, value in modality_status.items() if value != "real" and value != "missing"]
    if (missing and not settings.feature_allow_partial) or (non_production and not settings.feature_allow_heuristic_vision):
        blocked = ", ".join(missing + non_production)
        raise ValueError(f"生产模式禁止使用不完整或非正式模态结果: {blocked}")
    result_status = "partial" if missing or non_production else "succeeded"
    now = datetime.now(timezone.utc)
    extraction = FeatureExtraction(
        job_id=job.id,
        version_id=version_id,
        ts_features=ts,
        vision_features=vision,
        audio_features=audio,
        unified_vector=unified,
        normalization=normalization,
        format=output_format,
        created_at=now,
        started_at=now,
        finished_at=now,
        created_by=(job.result or {}).get("user_id"),
        status=result_status,
        source_by_modality=modality_status,
        input_object_keys=version.object_keys or [],
        sample_rate=bundle.sample_rate,
        sample_count=len(bundle.channels[0].values) if bundle.channels else 0,
        duration=bundle.duration,
        channel_mapping={chan.id: chan.id for chan in bundle.channels},
        missing_modalities=missing + non_production,
        warnings=[f"{key} 模态未使用正式生产算法" for key in non_production] + [f"{key} 模态缺失" for key in missing],
    )
    session.add(extraction)
    session.flush()

    # T16.3：产物落 MinIO——改造前特征提取只落库、**不产文件**，所以"生成数据版本"无处可挂。
    # 写对象是尽力而为（与快照一致）：存储不可达不该让一次成功的提取变成失败任务。
    # 产物键带上**提取参数**的短标签（归一化 / 输出格式）：旧写法 `features/{version_id}.json` 会让
    # "同一源版本换个参数重跑"互相覆盖产物文件，而版本幂等身份是按产物键区分的（R7）——那样两个
    # 内容不同的版本会指向同一个文件。标签用短哈希，避免中文/斜杠进对象键。
    params_tag = hashlib.sha1(f"{normalization}|{output_format}".encode("utf-8")).hexdigest()[:8]
    artifact_key = f"processed/{record.weld_id}/features/{version_id}-{params_tag}.json"
    try:
        artifact = json.dumps(
            {
                "extraction_id": extraction.id,
                "version_id": version_id,
                "status": extraction.status,
                "normalization": normalization,
                "format": output_format,
                "modality_status": modality_status,
                "unified_vector": unified,
                "ts_features": ts,
                "vision_features": vision,
                "audio_features": audio,
                "sample_rate": bundle.sample_rate,
                "sample_count": extraction.sample_count,
                "duration": extraction.duration,
            },
            ensure_ascii=False,
            default=str,
        ).encode("utf-8")
        get_storage().upload_stream(artifact_key, io.BytesIO(artifact), len(artifact), "application/json")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to write feature artifact {}: {}", artifact_key, exc)
        artifact_key = None

    # T16：只有 **succeeded** 才生成正式版本——partial（缺模态/启发式模态）不算正式产物（T16.3）；
    # object_keys 合并源版本文件（否则只挂特征文件会让"读原始信号"断链，T16.2/D18）。
    version_row = None
    if result_status == "succeeded" and artifact_key:
        source_keys = list(version.object_keys or [])
        # T16.3/R7：**同一个源版本 + 同一组提取参数只生成一个「特征提取」版本**。
        # 幂等身份 = (action, note, object_keys)：产物键里带了参数标签（见 artifact_key 的构造），
        # 所以换归一化/输出格式重跑会得到新键 → 建新版本，而任务重入会复用。
        version_row, created = reuse_or_create_version(
            session,
            record,
            action="特征提取",
            note=f"特征提取任务自动生成（{unified.get('total_dims', 0)} 维统一向量）",
            object_keys=[*source_keys, *[key for key in (artifact_key,) if key not in source_keys]],
            operator="算法任务",
        )
        if not created:
            logger.info(
                "Feature extraction reused the existing 特征提取 version {}", version_row.version_no
            )
    write_audit(session, (job.result or {}).get("user_id"), "extract", "feature_extraction", str(extraction.id), {"job_id": job.job_uid, "status": extraction.status})
    mark_succeeded(
        session,
        job,
        {
            "extraction_id": extraction.id,
            "status": extraction.status,
            "artifact_key": artifact_key,
            "version": {"id": version_row.id, "version_no": version_row.version_no} if version_row else None,
        },
    )
    session.commit()
