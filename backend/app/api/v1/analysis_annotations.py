"""Annotation API routes extracted from the analysis domain."""

from datetime import datetime, timezone
from io import BytesIO
import json

from fastapi import APIRouter, Depends
from loguru import logger
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.api.deps import get_current_user
from app.core.audit import write_audit
from app.core.db import get_session
from app.models.analysis import AnnotationTask, LabelCategory, Sample, SplitTask
from app.models.data import DataVersion, User
from app.models.jobs import Job
from app.schemas.common import err, ok, paginate
from app.services import annotation
from app.services.jobs import create_job, get_job_by_uid, to_job_payload

router = APIRouter(dependencies=[Depends(get_current_user)])

_ANNOTATION_SOURCES = {"split_task", "manual", "signal", "video"}
_IMPORT_SOURCES = {"files", "split_task"}
_VIDEO_EXTENSIONS = (".mp4", ".avi", ".mkv", ".mov", ".webm")


def _is_video_key(key: str) -> bool:
    return key.lower().endswith(_VIDEO_EXTENSIONS)


def _browser_friendly_video_key(session: Session, video_key: str) -> str:
    """Return a transcoded browser preview when a media-prep job produced one."""
    try:
        preps = session.exec(
            select(Job)
            .where(Job.type == "media_prep", Job.status == "succeeded")
            .order_by(Job.id.desc())
        ).all()
    except Exception:
        return video_key
    for prep in preps:
        result = prep.result or {}
        if result.get("object_key") == video_key:
            preview = result.get("preview_key")
            return preview if isinstance(preview, str) and preview else video_key
    return video_key


class AnnotationTaskCreate(BaseModel):
    """POST /annotation-tasks 请求体（契约 §3.4）。`source` 必填；从切分样本需给 `split_task_id`；`signal` 需给 `version_id`。"""

    source: str
    split_task_id: str | None = None
    version_id: int | None = None
    name: str | None = None


class AnnotationImportRequest(BaseModel):
    """POST /annotation-tasks/{task_id}/import 请求体（契约 §3.4）。"""

    source: str
    object_keys: list[str] | None = None
    split_task_id: str | None = None


class LabelItem(BaseModel):
    """单条标注：类别 + 几何（按 `kind` 分支）+ 可选置信度（缺省沿用先前 AI 预标注值）。

    - kind=box（默认）：`box` = [x, y, w, h] 目标检测框；
    - kind=segment：`start_time`/`end_time` = 时序区间起点/终点（秒）；
    - kind=polygon：`points` = 多边形顶点 [[x,y],…]（≥3）。
    """

    category: str
    kind: str = "box"
    box: list | None = None
    points: list | None = None
    start_time: float | None = None
    end_time: float | None = None
    confidence: float | None = None


class SaveLabelsRequest(BaseModel):
    """POST …/labels 请求体（契约 §3.4）：`labels[]` 覆盖写样本标注。"""

    labels: list[LabelItem]


# ── 标注（Task 14：异步任务创建 + 同步预标注/保存） ─────────────────────


@router.get("/label-categories")
def list_label_categories(session: Session = Depends(get_session)) -> dict:
    """缺陷标签类别（模型口径 6 类，契约 §3.4）：焊瘤/气孔/未熔合/咬边/正常 + 熔池（视频语义分割单类）。"""
    return ok(annotation.list_label_categories(session))


@router.post("/annotation-tasks")
def create_annotation_task(
    body: AnnotationTaskCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """创建标注任务（**异步**，契约 §3.4）：建 pending Job + `annotation_tasks` 行。

    同事务 commit，返回 `{job_id}`。成功后（后台执行器）若来源为 split_task，
    把该切分任务的样本 `annotation_task_id` 指向本任务；`signal` 来源在创建时同步
    生成 1 个信号锚点样本（`meta.mode='signal'`，波形区间标注的挂载点）；`video`
    来源同步生成 1 个视频锚点样本（`meta.mode='video'` + `video_key`，多边形区域标注
    的视频播放挂载点，帧样本经 `POST …/frames` 追加）。
    """
    if body.source not in _ANNOTATION_SOURCES:
        return err(
            40000,
            f"source 需为 {'/'.join(sorted(_ANNOTATION_SOURCES))}",
            status=400,
        )
    split_id = None
    if body.source == "split_task":
        split = annotation.resolve_split_task(session, body.split_task_id or "")
        if split is None:
            return err(40401, "切分任务不存在", status=404)
        split_id = split.id
    signal_anchor: dict | None = None
    video_anchor: dict | None = None
    if body.source == "signal":
        if body.version_id is None:
            return err(40000, "signal 来源需提供 version_id", status=400)
        version = session.get(DataVersion, body.version_id)
        if version is None:
            return err(40402, "版本不存在", status=404)
        record = session.get(DataRecord, version.record_id)
        signal_anchor = {
            "weld_id": record.weld_id if record is not None else None,
            "version_id": body.version_id,
        }
    elif body.source == "video":
        if body.version_id is None:
            return err(40000, "video 来源需提供 version_id", status=400)
        version = session.get(DataVersion, body.version_id)
        if version is None:
            return err(40402, "版本不存在", status=404)
        record = session.get(DataRecord, version.record_id)
        video_key = next(
            (k for k in (version.object_keys or []) if _is_video_key(k)), None
        )
        if video_key is None:
            return err(40000, "所选版本不包含可标注视频", status=400)
        video_anchor = {
            "weld_id": record.weld_id if record is not None else None,
            "version_id": body.version_id,
            # 原始视频常为浏览器不可解码编码（如 mpeg4）：媒体预处理（media_prep job）
            # 转出的 H.264+faststart 预览版优先；未转码/转码失败回退原始 key
            # （前端 <video> onError 有明确不可播提示）。
            "video_key": _browser_friendly_video_key(session, video_key),
            "source_video_key": video_key,
        }

    job = create_job(session, type="annotation")
    task = AnnotationTask(
        job_id=job.id,
        split_task_id=split_id,
        name=body.name,
        source=body.source,
        created_at=datetime.now(timezone.utc),
    )
    session.add(task)
    if signal_anchor is not None:
        session.flush()  # 分配 task.id
        session.add(
            Sample(
                annotation_task_id=task.id,
                meta={"mode": "signal", "source": "signal-anchor", **signal_anchor},
            )
        )
    if video_anchor is not None:
        session.flush()  # 分配 task.id
        session.add(
            Sample(
                annotation_task_id=task.id,
                meta={"mode": "video", "source": "video-anchor", **video_anchor},
            )
        )
    write_audit(
        session,
        current_user.id,
        "create",
        "annotation_task",
        job.job_uid,
        {
            "source": body.source,
            "split_task_id": body.split_task_id,
            "version_id": body.version_id,
            "name": body.name,
        },
    )
    session.commit()
    return ok({"job_id": job.job_uid})


@router.get("/annotation-tasks/{task_id}")
def get_annotation_task(task_id: str, session: Session = Depends(get_session)) -> dict:
    """标注任务整体状态/进度（契约 §3.4，轮询 Job 结构）。`task_id` 为 job_uid。"""
    job = get_job_by_uid(session, task_id)
    if job is None:
        return err(40401, "任务不存在", status=404)
    return ok(to_job_payload(job))


@router.post("/annotation-tasks/{task_id}/import")
def import_annotation_samples(
    task_id: str,
    body: AnnotationImportRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """导入额外样本到标注任务（契约 §3.4）。`task_id` 兼容 job_uid 与 DB id。

    - source=`files`：按 `object_keys[]` 建新 `Sample` 行；
    - source=`split_task`：把该切分任务的样本改指本任务。
    返回 `ok({imported})`。
    """
    if body.source not in _IMPORT_SOURCES:
        return err(
            40000,
            f"source 需为 {'/'.join(sorted(_IMPORT_SOURCES))}",
            status=400,
        )
    task = annotation.resolve_annotation_task(session, task_id)
    if task is None:
        return err(40401, "标注任务不存在", status=404)
    if body.source == "files" and not body.object_keys:
        return err(40000, "files 导入需提供 object_keys[]", status=400)
    if body.source == "split_task":
        if not body.split_task_id or annotation.resolve_split_task(
            session, body.split_task_id
        ) is None:
            return err(40401, "切分任务不存在", status=404)
    try:
        imported = annotation.import_samples(
            session, task, body.source, body.object_keys, body.split_task_id
        )
    except ValueError as exc:  # noqa: BLE001 - 未知来源等由服务抛出的业务错误
        return err(40000, str(exc), status=400)
    write_audit(
        session,
        current_user.id,
        "update",
        "annotation_task",
        task_id,
        {"source": body.source, "imported": imported},
    )
    session.commit()
    return ok({"imported": imported})


@router.get("/annotation-tasks/{task_id}/samples")
def list_annotation_samples(
    task_id: str,
    page: int = 1,
    page_size: int = 20,
    session: Session = Depends(get_session),
) -> dict:
    """标注样本列表（契约 §3.4，分页）：每样本含 annotations[] 与样本级 confidence。"""
    task = annotation.resolve_annotation_task(session, task_id)
    if task is None:
        return err(40401, "标注任务不存在", status=404)
    page = max(1, page)
    page_size = min(max(1, page_size), 100)  # §1.4：page_size 最大 100
    items, total = annotation.list_samples(session, task, page, page_size)
    return ok(paginate(items, total, page, page_size))


@router.get("/annotation-tasks/{task_id}/samples/{sample_id}")
def get_annotation_sample(
    task_id: str,
    sample_id: int,
    session: Session = Depends(get_session),
) -> dict:
    """单个样本详情（契约 §3.4）：样本 + 最新标注 + 样本级 `confidence`。"""
    task = annotation.resolve_annotation_task(session, task_id)
    if task is None:
        return err(40401, "标注任务不存在", status=404)
    payload = annotation.get_sample_detail(session, task, sample_id)
    if payload is None:
        return err(40401, "样本不存在或不属于该任务", status=404)
    return ok(payload)


@router.post("/annotation-tasks/{task_id}/samples/{sample_id}/ai-pretag")
def ai_pretag_sample(
    task_id: str,
    sample_id: int,
    session: Session = Depends(get_session),
) -> dict:
    """AI 预标注（**同步**，契约 §3.4）：确定性模拟 2 个疑似区域 + 置信度，**替换**现有标注。

    seed = `sample_id` → 同样本每次结果一致。落库（annotator=AI预标注），前端随后
    `POST …/labels` 覆盖写为人工标注。
    """
    task = annotation.resolve_annotation_task(session, task_id)
    if task is None:
        return err(40401, "标注任务不存在", status=404)
    sample = annotation.get_sample(session, task, sample_id)
    if sample is None:
        return err(40401, "样本不存在或不属于该任务", status=404)
    new_annotations = annotation.pretag_sample(session, task, sample)
    session.commit()
    return ok([annotation.annotation_payload(a) for a in new_annotations])


@router.post("/annotation-tasks/{task_id}/samples/{sample_id}/labels")
def save_annotation_labels(
    task_id: str,
    sample_id: int,
    body: SaveLabelsRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """保存/更新标注（**同步**，契约 §3.4）：`labels[]` 覆盖写样本标注，annotator=当前用户。

    类别必须在 label_categories（400）；confidence 缺省沿用先前（AI 预标注）同类别值。
    写审计（`update`）后提交。
    """
    task = annotation.resolve_annotation_task(session, task_id)
    if task is None:
        return err(40401, "标注任务不存在", status=404)
    sample = annotation.get_sample(session, task, sample_id)
    if sample is None:
        return err(40401, "样本不存在或不属于该任务", status=404)
    cats = {c.name for c in session.exec(select(LabelCategory)).all()}
    for label in body.labels:
        if label.category not in cats:
            return err(40000, f"未知标签类别: {label.category}", status=400)
        # 按 kind 分支校验几何字段（box/segment/polygon），未知 kind → 400。
        kind = label.kind
        if kind == "box":
            box = label.box
            if not (
                isinstance(box, list)
                and len(box) == 4
                and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in box)
            ):
                return err(40000, "box 需为 [x, y, w, h] 数值数组", status=400)
        elif kind == "segment":
            start, end = label.start_time, label.end_time
            if (
                start is None
                or end is None
                or isinstance(start, bool)
                or isinstance(end, bool)
                or not (0 <= start < end)
            ):
                return err(40000, "segment 需 start_time/end_time 且 0 <= start < end（秒）", status=400)
        elif kind == "polygon":
            points = label.points
            if not (
                isinstance(points, list)
                and len(points) >= 3
                and all(
                    isinstance(p, list)
                    and len(p) == 2
                    and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in p)
                    for p in points
                )
            ):
                return err(40000, "polygon 需 points 至少 3 个 [x, y] 顶点", status=400)
        else:
            return err(40000, f"未知标注类型 kind: {kind}", status=400)
        # confidence 列是 Numeric(4,3)，越界（如 >=10）会触发 MySQL DataError → 500；
        # 给定时必须在 [0,1]，否则 400（不落库）。
        conf = label.confidence
        if conf is not None and not (0 <= conf <= 1):
            return err(40000, "置信度需在 0~1 之间", status=400)

    new_annotations = annotation.save_labels(
        session, task, sample, body.labels, _operator(current_user)
    )
    write_audit(
        session,
        current_user.id,
        "update",
        "annotation",
        f"{task_id}/{sample_id}",
        {"labels": [l.category for l in body.labels]},
    )
    session.commit()
    return ok([annotation.annotation_payload(a) for a in new_annotations])


class AnnotationFrameCreate(BaseModel):
    """POST /annotation-tasks/{task_id}/frames 请求体（视频标注帧锚点）。

    `frame_width`/`frame_height` 为捕获帧的像素尺寸（视频自然分辨率），导出掩膜时据此
    把多边形像素坐标缩放到 ffmpeg 抽帧实际尺寸。
    """

    timestamp: float
    frame_width: int | None = None
    frame_height: int | None = None


@router.post("/annotation-tasks/{task_id}/frames")
def create_annotation_frame(
    task_id: str,
    body: AnnotationFrameCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """为视频标注任务创建帧样本锚点（`meta.mode='frame'` + `timestamp`），**同步**。

    weld_id/version_id/video_key 从任务的视频锚点样本（`meta.mode='video'`）继承；
    之后前端用既有 `POST …/samples/{sample_id}/labels`（kind='polygon'）给该帧保存多边形。
    写审计（`create`）后提交，返回 `{sample_id}`。
    """
    task = annotation.resolve_annotation_task(session, task_id)
    if task is None:
        return err(40401, "标注任务不存在", status=404)
    if task.source != "video":
        return err(40000, "仅视频标注任务可创建帧样本", status=400)
    ts = body.timestamp
    if isinstance(ts, bool) or not isinstance(ts, (int, float)) or ts < 0:
        return err(40000, "timestamp 需为非负数值（秒）", status=400)
    fw, fh = body.frame_width, body.frame_height
    if (fw is not None and (not isinstance(fw, int) or fw <= 0)) or (
        fh is not None and (not isinstance(fh, int) or fh <= 0)
    ):
        return err(40000, "frame_width/frame_height 需为正整数", status=400)
    anchors = session.exec(
        select(Sample).where(Sample.annotation_task_id == task.id)
    ).all()
    video_meta = next(
        ((s.meta or {}) for s in anchors if (s.meta or {}).get("mode") == "video"), {}
    )
    if not video_meta.get("video_key"):
        return err(40000, "视频标注任务缺少有效视频锚点", status=400)
    sample = Sample(
        annotation_task_id=task.id,
        meta={
            "mode": "frame",
            "timestamp": ts,
            "weld_id": video_meta.get("weld_id"),
            "version_id": video_meta.get("version_id"),
            "video_key": video_meta.get("video_key"),
            "frame_width": fw,
            "frame_height": fh,
        },
    )
    session.add(sample)
    session.flush()
    write_audit(
        session,
        current_user.id,
        "create",
        "annotation_sample",
        f"{task_id}/frame",
        {"timestamp": ts},
    )
    session.commit()
    return ok({"sample_id": sample.id})


@router.post("/annotation-tasks/{task_id}/export")
def export_annotation_artifacts(
    task_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """导出标注产物（**同步**）：video → 帧图+掩膜 PNG；signal → segment JSON 标签。

    写 MinIO `processed/{weld_id}/annotate/...`，返回 `{type, count, items}`。
    写审计（`export`）后提交。
    """
    task = annotation.resolve_annotation_task(session, task_id)
    if task is None:
        return err(40401, "标注任务不存在", status=404)
    from app.storage import get_storage  # noqa: PLC0415 - 延迟导入便于测试 monkeypatch

    storage = get_storage()
    try:
        result = annotation.export_annotations(session, task, storage)
    except ValueError as exc:
        # 不支持来源（如 manual）→ 400
        return err(40000, str(exc), status=400)
    except Exception as exc:  # noqa: BLE001 - 导出失败统一 500，不泄漏内部异常
        logger.warning("[annotation.export] Export failed: task_id={} err={}", task_id, exc)
        return err(50000, "标注导出失败", status=500)
    write_audit(
        session,
        current_user.id,
        "export",
        "annotation",
        task_id,
        {"type": result.get("type"), "count": result.get("count")},
    )
    session.commit()
    return ok(result)


def _operator(user: User) -> str:
    """服务端取当前登录用户作 annotator/operator（优先展示名，对齐 seed 林工）。"""
    return user.display_name or user.username
