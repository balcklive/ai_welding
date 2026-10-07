"""切片级特征提取路由（`/api/v1/…/sample-features*`，2026-10）。

一个 v3 `Sample`（一个时间窗）= 一个特征对象 = 一行 **36 维**向量（时序 28 + 视觉 8，
**无声音组**）。与 `feature_extractions`（§3.13，焊缝数据版本级 42 维）是**两条线**：
那条供人看与报告导出，这条供训练。分表的原因见 `models/analysis.SampleFeature`。

端点：

- `GET  /welds/{weld_id}/sample-feature-tasks`              可提取的分段任务（工作台入口列表）；
- `POST /split-tasks/{task_id}/sample-feature-extractions`  建异步提取任务（幂等）；
- `GET  /split-tasks/{task_id}/sample-features`             切片特征状态分页 + 进度；
- `GET  /split-tasks/{task_id}/sample-features/export`      导出行序对齐的 n×36 矩阵（JSON/CSV）；
- `GET  /split-tasks/{task_id}/sample-features/{sample_id}` 单样本完整向量。

**没有同步提取端点**：工作台只读落库行 + 轮询 Job，同步版是第二条代码路径。

鉴权：router 级 `Depends(get_current_user)`；归属沿用**分段域**口径
（`forbid_unless_record_owned`，同 `POST …/split-tasks`）；`{task_id}` 兼容 job_uid 与
`split_tasks` DB id。错误码：40401=任务/样本不存在、40300=无权、40000=参数或前置条件、
40900=并发建任务。
"""

import csv
import hashlib
import io
import json

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.api.deps import forbid_unless_record_owned, get_current_user
from app.core.audit import write_audit
from app.core.db import get_session
from app.models.analysis import Sample, SplitTask
from app.models.data import DataRecord, DataVersion, User
from app.models.jobs import Job
from app.schemas.common import err, ok, paginate
from app.services import annotation as annotation_svc
from app.services import features as features_svc
from app.services import sample_features as svc
from app.services.jobs import create_job
from app.storage import get_storage

router = APIRouter(dependencies=[Depends(get_current_user)])

EXPORT_FORMATS = ("JSON", "CSV")


class SampleFeatureExtractionCreate(BaseModel):
    """POST 请求体。

    `normalization` 只影响**导出文件**：落库的权威向量恒为原始值
    （`services.sample_features.CANONICAL_NORMALIZATION`）——逐切片 Z-Score 会把每片
    各自减均值、抹掉区分切片的那批量，标准化属于训练侧。
    """

    normalization: str = svc.CANONICAL_NORMALIZATION


def _resolve_task(session: Session, task_id: str, current_user: User | None = None):
    """解析分段任务：不存在 → 404，前置条件不满足 → 400。"""
    task = annotation_svc.resolve_split_task(session, task_id)
    if task is None:
        return None, err(40401, "分段任务不存在", status=404)
    if current_user is not None:
        version = session.get(DataVersion, task.version_id)
        record = session.get(DataRecord, version.record_id) if version is not None else None
        if record is not None:
            forbid_unless_record_owned(session, current_user, record)
    if reason := svc.block_reason(session, task):
        return None, err(40000, reason, status=400)
    return task, None


def _record_of(session: Session, task: SplitTask) -> DataRecord | None:
    version = session.get(DataVersion, task.version_id)
    return session.get(DataRecord, version.record_id) if version is not None else None


def _request_key(split_task_id: int, normalization: str) -> str:
    raw = json.dumps(
        {"split_task_id": split_task_id, "normalization": normalization},
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@router.get("/welds/{weld_id}/sample-feature-tasks")
def list_sample_feature_tasks(
    weld_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """该焊缝**可提取切片特征**的分段任务（已完成 + v3），供工作台入口列表。

    与段级标注工作台的入口是**同一份查询**（`splitting.list_completed_segment_tasks`），
    只是各带自己的进度口径——"能看到哪些任务"两处必须一致。
    """
    record = session.exec(select(DataRecord).where(DataRecord.weld_id == weld_id)).first()
    if record is None:
        return err(40401, "焊缝不存在", status=404)
    forbid_unless_record_owned(session, current_user, record)
    return ok({"items": svc.list_extractable_tasks(session, weld_id)})


@router.post("/split-tasks/{task_id}/sample-feature-extractions")
def create_sample_feature_extraction(
    task_id: str,
    body: SampleFeatureExtractionCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """建异步切片特征提取任务；相同入参在运行中/已完成时**幂等复用**同一 Job。"""
    if body.normalization not in features_svc.NORMALIZATIONS:
        return err(
            40000,
            f"normalization 需为 {'/'.join(sorted(features_svc.NORMALIZATIONS))}",
            status=400,
        )
    task, failure = _resolve_task(session, task_id, current_user)
    if failure is not None:
        return failure

    key = _request_key(task.id, body.normalization)
    existing = session.exec(
        select(Job)
        .where(Job.type == "sample_feature_extraction", Job.request_key == key)
        .order_by(Job.id.desc())
    ).first()
    if existing is not None and existing.status in {"pending", "running", "succeeded"}:
        return ok({"job_id": existing.job_uid})

    request = {"split_task_id": task.id, "normalization": body.normalization}
    job = create_job(session, "sample_feature_extraction", {"request": request, "user_id": current_user.id})
    job.request_key = key
    write_audit(session, current_user.id, "create", "sample_feature_job", job.job_uid, request)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = session.exec(
            select(Job)
            .where(Job.type == "sample_feature_extraction", Job.request_key == key)
            .order_by(Job.id.desc())
        ).first()
        if existing is not None and existing.status in {"pending", "running", "succeeded"}:
            return ok({"job_id": existing.job_uid})
        return err(40900, "相同切片特征提取任务正在创建，请稍后重试", status=409)
    return ok({"job_id": job.job_uid})


@router.get("/split-tasks/{task_id}/sample-features")
def list_sample_features(
    task_id: str,
    page: int = 1,
    page_size: int = 50,
    filter: str = "all",
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """切片特征状态分页（按时间窗排序）+ 进度。

    行**只含导航与进度需要的轻量字段**——不含 36 个数值（几百片会把响应撑爆）。
    要数值走单样本详情。未提取的片是 `extracted=false`，**不是 404**。
    """
    if filter not in {"all", "unextracted"}:
        return err(40000, "filter 需为 all / unextracted", status=400)
    task, failure = _resolve_task(session, task_id, current_user)
    if failure is not None:
        return failure
    items, total = svc.list_features(
        session,
        task,
        page=page,
        page_size=page_size,
        only_unextracted=filter == "unextracted",
    )
    payload = paginate(
        items, total, max(1, int(page)), max(1, min(svc.MAX_PAGE_SIZE, int(page_size)))
    )
    payload["progress"] = svc.task_progress(session, task)
    return ok(payload)


# 具体路径**必须注册在 `{sample_id}` 之前**（FastAPI 按顺序匹配，否则 export 会被当成样本 id）。
@router.get("/split-tasks/{task_id}/sample-features/export")
def export_sample_features(
    task_id: str,
    format: str = "JSON",
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """导出该任务的 n×36 矩阵（行序与工作台一致 = `Sample.start_time` 升序）。

    CSV 用位置列名 `f0..f35`：维度**名字**在 JSON 导出的 `groups` 里与单样本详情里，
    这里不另写一份拼接顺序（那就成了第二处定义，迟早与向量对不上）。
    """
    if format not in EXPORT_FORMATS:
        return err(40000, f"format 需为 {'/'.join(EXPORT_FORMATS)}", status=400)
    task, failure = _resolve_task(session, task_id, current_user)
    if failure is not None:
        return failure
    record = _record_of(session, task)
    if record is None:
        return err(40401, "焊缝数据不存在", status=404)
    rows = svc.ordered_rows(session, task)
    if not rows:
        return err(40000, "该任务还没有已提取的切片特征，请先执行提取", status=400)

    groups: list[dict] = []
    samples: list[dict] = []
    for feature, sample in rows:
        vector = feature.unified_vector or {}
        if format == "JSON" and not groups:
            groups = vector.get("groups") or []
        samples.append(
            {
                "sample_id": feature.sample_id,
                "index": sample.frame_no,
                "start_time": sample.start_time,
                "end_time": sample.end_time,
                "modality_status": feature.source_by_modality or {},
                "warnings": feature.warnings or [],
                "values": vector.get("values") or [],
            }
        )

    if format == "JSON":
        content = json.dumps(
            {
                "schema_version": 1,
                "pipeline_version": svc.PIPELINE_VERSION,
                "split_task_id": task.id,
                "weld_id": record.weld_id,
                "normalization": svc.CANONICAL_NORMALIZATION,
                "total_dims": features_svc.SAMPLE_TOTAL_DIMS,
                "groups": groups,
                "samples": samples,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        suffix, content_type = "json", "application/json"
    else:
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(
            ["sample_id", "index", "start_time", "end_time"]
            + [f"f{index}" for index in range(features_svc.SAMPLE_TOTAL_DIMS)]
        )
        for entry in samples:
            writer.writerow(
                [
                    entry["sample_id"],
                    entry["index"],
                    entry["start_time"],
                    entry["end_time"],
                    *entry["values"],
                ]
            )
        content, suffix, content_type = buffer.getvalue().encode("utf-8"), "csv", "text/csv"

    key = f"processed/{record.weld_id}/features/slice-features/exports/{task.id}.{suffix}"
    storage = get_storage()
    storage.upload_stream(key, io.BytesIO(content), len(content), content_type)
    write_audit(
        session,
        current_user.id,
        "export",
        "sample_features",
        str(task.id),
        {"format": format, "object_key": key},
    )
    session.commit()
    return ok({"format": format, "object_key": key, "url": storage.presign_get(key)})


@router.get("/split-tasks/{task_id}/sample-features/{sample_id}")
def get_sample_feature(
    task_id: str,
    sample_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """单样本的完整 36 维向量（含分组定义、逐通道时序特征、视觉特征与逐片 warnings）。

    该样本**还没提取**时返回 `feature=null`（不是 404——「还没跑」是正常状态）；
    样本不属于该任务才 40401。
    """
    task, failure = _resolve_task(session, task_id, current_user)
    if failure is not None:
        return failure
    sample = session.get(Sample, sample_id)
    if sample is None or sample.split_task_id != task.id:
        return err(40401, "样本不存在或不属于该分段任务", status=404)
    row = svc.feature_of(session, task, sample_id)
    return ok(
        {
            "sample_id": sample_id,
            "feature": svc.feature_payload(row, sample) if row is not None else None,
        }
    )
