"""特征提取 Job handler：执行真实输入读取、特征计算和结果落库。"""

from datetime import datetime, timezone

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
from app.services.jobs import mark_succeeded


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
    write_audit(session, (job.result or {}).get("user_id"), "extract", "feature_extraction", str(extraction.id), {"job_id": job.job_uid, "status": extraction.status})
    mark_succeeded(session, job, {"extraction_id": extraction.id, "status": extraction.status})
    session.commit()
