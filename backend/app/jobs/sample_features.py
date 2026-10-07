"""切片级特征提取 Job handler（2026-10）。

`job.result.request = {"split_task_id": <split_tasks DB id>, "normalization": "无", ...}`。
领域逻辑在 `app.services.sample_features.extract_task_features`——逐片落 `sample_features`
行（`sample_id` 唯一，PUT 即 upsert）。

**不建数据版本**：这些特征的自然锚点是分段任务（`split_task_id`），不是焊缝数据版本。
版本的幂等键是 `(action, note, object_keys)`，切片侧没有能区分参数化的产物键，硬造一个
只会让版本链多出一条"这版到底是哪个特征提取"的歧义。改为写**任务级产物**：

    processed/{weld_id}/features/slice-features/{split_task_id}-{params_tag}.json

`params_tag` 带归一化参数（同 `jobs/features.py` 的 `{version_id}-{params_tag}` 理由）：
换参数重跑不能覆盖上一次的记录。产物写失败**只告警**，不让成功的提取变失败。

视觉缺失是**逐片**降级（记 `missing` + 该行 warnings），Job 一律 succeeded，
`job.result.status = "partial"` 表示有片缺了非正式视觉结果。
"""

import hashlib
import io
import json
from datetime import datetime, timezone

from loguru import logger
from sqlmodel import Session

from app.core.audit import write_audit
from app.jobs.executor import register_handler
from app.models.analysis import SplitTask
from app.models.data import DataRecord, DataVersion
from app.models.jobs import Job
from app.services import features, sample_features
from app.services.jobs import mark_succeeded
from app.storage import get_storage


@register_handler("sample_feature_extraction")
def handle(job_id: int, session: Session) -> None:
    job = session.get(Job, job_id)
    if job is None:
        raise ValueError(f"Job does not exist: id={job_id}")
    request = (job.result or {}).get("request") or {}
    split_task_id = request.get("split_task_id")
    if not isinstance(split_task_id, int):
        raise ValueError("sample feature extraction job request is invalid")
    normalization = str(request.get("normalization") or sample_features.CANONICAL_NORMALIZATION)

    task = session.get(SplitTask, split_task_id)
    if task is None:
        raise ValueError("分段任务不存在，无法提取切片特征")

    job.progress = 10
    session.commit()

    result = sample_features.extract_task_features(
        session,
        task,
        normalization=normalization,
        job=job,
        user_id=(job.result or {}).get("user_id"),
    )

    artifact_key = _write_artifact(session, task, normalization)
    result["artifact_key"] = artifact_key

    write_audit(
        session,
        (job.result or {}).get("user_id"),
        "extract",
        "sample_features",
        str(task.id),
        {
            "split_task_id": task.id,
            "status": result["status"],
            "extracted": result["extracted"],
            "total_dims": result["total_dims"],
        },
    )
    mark_succeeded(session, job, result)
    session.commit()


def _write_artifact(session: Session, task: SplitTask, normalization: str) -> str | None:
    """把该任务的切片向量写成一份 JSON 产物（best-effort，失败返回 None）。

    这是**唯一**记录"这次用了哪个归一化"的落盘物——行本身原地 upsert、只留当前值。
    样本按 `Sample.start_time` 排序，与工作台看到的一致。
    """
    version = session.get(DataVersion, task.version_id)
    record = session.get(DataRecord, version.record_id) if version is not None else None
    if record is None:
        return None
    rows = sample_features.ordered_rows(session, task)
    payload = {
        "schema_version": 1,
        "pipeline_version": sample_features.PIPELINE_VERSION,
        "split_task_id": task.id,
        "weld_id": record.weld_id,
        "signal_version_id": rows[0][0].version_id if rows else None,
        "normalization": normalization,
        "total_dims": features.SAMPLE_TOTAL_DIMS,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "samples": [
            {
                "sample_id": feature.sample_id,
                "index": sample.frame_no,
                "start_time": sample.start_time,
                "end_time": sample.end_time,
                "modality_status": feature.source_by_modality or {},
                "warnings": feature.warnings or [],
                "values": (feature.unified_vector or {}).get("values") or [],
            }
            for feature, sample in rows
        ],
    }
    params_tag = hashlib.sha1(normalization.encode("utf-8")).hexdigest()[:8]
    key = (
        f"processed/{record.weld_id}/features/slice-features/"
        f"{task.id}-{params_tag}.json"
    )
    try:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        get_storage().upload_stream(key, io.BytesIO(data), len(data), "application/json")
        return key
    except Exception as exc:  # noqa: BLE001 —— 产物是附加物，不该让成功的提取变失败
        logger.warning("Slice feature artifact upload failed ({}): {}", key, exc)
        return None
