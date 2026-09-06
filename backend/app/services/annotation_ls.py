"""LS 标注集成服务层：等待态联动 + webhook 处理 + 幂等回写 + 对账/刷新。

业务库（`annotations`/`annotation_tasks`/`annotation_ls_sync`）始终权威；LS 是捕获/执行层。
best-effort（LS 不可达仅告警，不炸业务 Job，同 `integrations/mlflow.py`）。

「LS 等待」态（决策 2）：annotation_tasks.ls_status = 一等公民等待态；Job 在 mode=on 时
置 running（不进 executor 的 pending 领单队列），完成由**回写/对账**驱动，终态不抢占。
`jobs/annotation.py` 在 mode=on 时直接 return（不跑 simulate_annotation）。

Region 坐标/类型按真实验证（`integrations/labelstudio.py`：rectanglelabels/polygonlabels/
timeserieslabels，0-100% → 像素）。注：`session.flush()` 不 commit，commit 由调用方（路由）
统一负责（同 services/annotation.py 约定）。
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import PurePosixPath

from loguru import logger
from sqlmodel import Session, func, select

from app.core.config import settings
from app.integrations import labelstudio as ls
from app.models.analysis import (
    Annotation,
    AnnotationLsSync,
    AnnotationTask,
    Sample,
)
from app.models.jobs import Job
from app.services.jobs import mark_succeeded, _iso_utc


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── 等待态联动 ───────────────────────────────────────────────────────────


def task_to_waiting(session: Session, task: AnnotationTask) -> None:
    """把标注任务置「LS 等待」态（mode=on 时，路由在建任务后调用）。"""
    task.ls_status = "pending_ls"
    session.add(task)


def mark_synced(session: Session, task: AnnotationTask) -> None:
    """样本已回写 → 任务置 synced（由 writeback 对账驱动，非 job 终态）。"""
    task.ls_status = "synced"
    session.add(task)


# ── 建 LS task（创建标注任务后，逐样本推 LS） ────────────────────────────


def push_samples_to_ls(session: Session, task: AnnotationTask, samples: list[Sample]) -> int:
    """为任务的每个样本建 LS task，并写 `annotation_ls_sync` 映射行；返回成功数。

    best-effort：单个样本 LS 失败仅记录，不中断整任务（batch 继续，遗漏交由对账兜底）。
    """
    client = ls._client()
    if client is None:
        logger.info("Label Studio off/unavailable; skip pushing samples (task={})", task.id)
        return 0
    created = 0
    for sample in samples:
        project_id = ls.project_for(task.source, _kind_of(sample))
        data = _media_data_for(sample)
        if data is None:
            logger.warning("sample {} no annotatable media; skip push", sample.id)
            continue
        ls_task_id = ls.create_task(client, project_id, data, sample.id)
        row = session.exec(
            select(AnnotationLsSync).where(
                AnnotationLsSync.annotation_task_id == task.id,
                AnnotationLsSync.sample_id == sample.id,
            )
        ).first()
        if row is None:
            row = AnnotationLsSync(
                annotation_task_id=task.id,
                sample_id=sample.id,
                ls_project_id=project_id,
                sync_status="pending_ls",
            )
            session.add(row)
        if ls_task_id:
            row.ls_task_id = int(ls_task_id)
            row.sync_status = "annotating"
            created += 1
        session.add(row)
    session.flush()
    return created


def _kind_of(sample: Sample) -> str:
    """样本 → 平台标注 kind（`ls._kind_of_sample`：模式 frame/video→polygon；signal→segment；其余→box）。"""
    return ls._kind_of_sample(sample)


def _pick_media_key(keys: list[str], kind: str) -> str | None:
    """从样本 object_keys 里挑可标注媒体：时序取 csv/json，图像取 jpg/png 等；无则取第一个。"""
    targets = (".csv", ".json") if kind == "segment" else (".jpg", ".jpeg", ".png", ".webp", ".bmp")
    for key in keys:
        if PurePosixPath(str(key)).suffix.lower() in targets:
            return str(key)
    return str(keys[0]) if keys else None


def _media_data_for(sample: Sample) -> dict | None:
    """样本可见媒体 → LS task `data`（image|csv: 预签名 URL）。返回 None=无可标注媒体。"""
    keys = sample.object_keys or []
    if not keys:
        return None
    kind = _kind_of(sample)
    key = _pick_media_key(keys, kind)
    if key is None:
        return None
    from app import storage  # 延迟导入便于测试 monkeypatch

    url = ls.media_url(storage.get_storage(), key)
    return {ls.media_field_for(kind): url}


# ── webhook 处理（annotation_created/updated） ─────────────────────────────


def _extract_ls_task_id(payload: dict) -> int | None:
    """从 LS webhook payload 提取 LS task id（兼容直接 task_id / task.id / annotation.task）。"""
    if not isinstance(payload, dict):
        return None
    tid = payload.get("task_id")
    if tid is not None:
        return int(tid)
    task = payload.get("task")
    if isinstance(task, dict) and task.get("id") is not None:
        return int(task["id"])
    ann = payload.get("annotation")
    if isinstance(ann, dict):
        at = ann.get("task")
        if isinstance(at, dict) and at.get("id") is not None:
            return int(at["id"])
        if at is not None:
            return int(at)
    return None


def handle_annotation_event(session: Session, event_type: str, payload: dict) -> dict | None:
    """LS annotation 事件 → 拉该 LS task 标注 → 幂等回写 `annotations` → 任务 synced。

    返回 `{"task_id","samples":N}`（成功）；异常由调用方（路由）计日志，不抛。
    LS task 映射到平台 sample 靠 `annotation_ls_sync.ls_task_id`（或 payload 内嵌 task id）。
    """
    task_id = _extract_ls_task_id(payload)
    if not task_id:
        logger.warning("LS webhook lacks task.id; skipping")
        return None
    sync_row = session.exec(
        select(AnnotationLsSync).where(AnnotationLsSync.ls_task_id == int(task_id))
    ).first()
    if sync_row is None:
        logger.warning("LS task {} not in annotation_ls_sync; skipping", task_id)
        return None
    sample = session.get(Sample, sync_row.sample_id)
    task = session.get(AnnotationTask, sync_row.annotation_task_id)
    if sample is None or task is None:
        logger.warning("LS task {} maps to missing sample/task; skipping", task_id)
        return None

    client = ls._client()
    if client is None:
        logger.warning("LS client unavailable; skip writeback for task {}", task_id)
        return None
    ls_task = ls.get_ls_task(client, int(task_id))
    if ls_task is None:
        logger.warning("LS task {} fetch failed; skip", task_id)
        return None
    annotation = ls.choose_effective_annotation(ls_task)
    if annotation is None:
        logger.info("LS task {} has no effective annotation yet; skip", task_id)
        return None
    converted = _convert_annotation(annotation)
    if not converted:
        logger.info("LS task {} annotation converts to nothing; skip", task_id)
        return None
    annotator = ls.extract_annotator(annotation)
    writeback_annotation(session, sample, converted, annotator)
    sync_row.sync_status = "synced"
    if annotation.get("id") is not None:
        sync_row.ls_annotation_id = int(annotation["id"])
    sync_row.updated_at = _now()
    session.add(sync_row)
    # 任务完成 = 全部样本实际回写（决策 2 / 计划 70 行），不是单个样本回写即终态。
    _maybe_complete_task(session, task)
    session.flush()
    return {"task_id": task_id, "samples": 1}


def _maybe_complete_task(session: Session, task: AnnotationTask) -> bool:
    """该任务所有 `annotation_ls_sync` 行是否均已回写；是则任务 `ls_status=synced` + job succeeded。

    幂等：重复 webhook/重复对账不重复落行（重复时 job 已 succeeded，跳过）。返回是否完成。
    """
    pending = int(
        session.exec(
            select(func.count(AnnotationLsSync.id)).where(
                AnnotationLsSync.annotation_task_id == task.id,
                AnnotationLsSync.sync_status != "synced",
            )
        ).one()
    )
    if pending:
        return False
    task.ls_status = "synced"
    session.add(task)
    job = session.get(Job, task.job_id)
    if job is not None and job.status != "succeeded":
        mark_succeeded(session, job, {"ls_status": "synced", "annotation_task_id": task.id})
    return True


def _gather_task_samples(session: Session, task: AnnotationTask) -> list[Sample]:
    """取任务的样本并归位：`split_task` 来源先把该切分任务样本 `annotation_task_id` 指到本任务。"""
    if task.source == "split_task" and task.split_task_id is not None:
        samples = session.exec(
            select(Sample).where(Sample.split_task_id == task.split_task_id)
        ).all()
        for s in samples:
            s.annotation_task_id = task.id
            session.add(s)
        return samples
    return list(session.exec(select(Sample).where(Sample.annotation_task_id == task.id)).all())


def prepare_ls_task(session: Session, task: AnnotationTask) -> bool:
    """LS 模式（mode=on）下标注 handler 的领域逻辑：归位样本 → 推 LS → 置「LS 等待」态。

    返回 True 表示已进入 LS 等待（job 保持 running，等回写驱动完成）；False 表示 LS client
    不可用，调用方（handler）回退旧模拟路径（best-effort，不炸 job）。**不 mark_succeeded**。
    """
    samples = _gather_task_samples(session, task)
    client = ls._client()
    if client is None:
        logger.warning("[ls.prepare] LS client unavailable; task={} falls back to simulate", task.id)
        return False
    task_to_waiting(session, task)  # ls_status = pending_ls
    push_samples_to_ls(session, task, [s for s in samples if s.object_keys])
    return True


def _convert_annotation(annotation: dict) -> list[dict]:
    """把 LS 单条 annotation 的 result regions 转成平台 annotation payload 列表（含 category）。"""
    out: list[dict] = []
    for region in annotation.get("result") or []:
        if not isinstance(region, dict):
            continue
        geo = ls.convert_region(region)
        if geo is None:
            continue
        out.append({"category": ls._region_category(region), **geo})
    return out


def writeback_annotation(
    session: Session,
    sample: Sample,
    annotations: list[dict],
    annotator: str = "LabelStudio",
) -> int:
    """幂等回写：删旧插新（覆盖写样本标注），annotator=LS 用户名。返回回写条数。

    幂等靠"删旧插新"（同平台 save_labels 语义）：重复事件/重复对账不重复落行；confidence 缺省
    沿用先前同类别值。
    """
    existing = list(session.exec(select(Annotation).where(Annotation.sample_id == sample.id)).all())
    prev_conf: dict[str, float | None] = {}
    for a in existing:
        if a.category not in prev_conf:
            prev_conf[a.category] = float(a.confidence) if a.confidence is not None else None
    for a in existing:
        session.delete(a)

    now = _now()
    written = 0
    for ann in annotations:
        conf = ann.get("confidence")
        if conf is None:
            conf = prev_conf.get(ann.get("category"))
        session.add(
            Annotation(
                sample_id=sample.id,
                category=ann["category"],
                kind=ann["kind"],
                box=ann.get("box"),
                points=ann.get("points"),
                start_time=ann.get("start_time"),
                end_time=ann.get("end_time"),
                confidence=Decimal(str(conf)) if conf is not None else None,
                annotator=annotator,
                created_at=now,
                updated_at=now,
            )
        )
        written += 1
    session.flush()
    return written


# ── 对账/刷新（决策 3，周期循环） ──────────────────────────────────────────


def reconcile_pending(session: Session) -> dict:
    """周期对账兜底：对比 `annotation_ls_sync` 与 LS 项目 tasks，补回写 / 刷新过期预签名URL。

    对 `sync_status=annotating`（已推到 LS、未回写）的行：尝试 `handle_annotation_event` 补回写；
    仍未回写的（可能尚未标注）刷新过期媒体 URL。需一个后台心跳（executor 之外的新循环，
    `JOB_EXECUTOR_ENABLED` 门禁）定时调用；当前由 `POST /labelstudio/sync` 手动触发。
    """
    pending = session.exec(
        select(AnnotationLsSync).where(AnnotationLsSync.sync_status == "annotating")
    ).all()
    client = ls._client()
    if client is None:
        logger.info("[ls.reconcile] LS off/unavailable; pending={}", len(pending))
        return {"pending": len(pending), "synced": 0, "refreshed": 0}
    from app import storage  # 延迟导入便于测试 monkeypatch

    synced = 0
    refreshed = 0
    for row in pending:
        if row.ls_task_id is None:
            continue
        result = handle_annotation_event(session, "reconcile", {"task": {"id": row.ls_task_id}})
        if result:
            synced += 1
            continue
        sample = session.get(Sample, row.sample_id)
        keys = (sample.object_keys or []) if sample else []
        if keys:
            kind = _kind_of(sample) if sample else "box"
            ls.refresh_task_media(client, int(row.ls_task_id), storage.get_storage(), keys[0], kind)
            refreshed += 1
    session.flush()
    logger.info("[ls.reconcile] pending={} synced={} refreshed={}", len(pending), synced, refreshed)
    return {"pending": len(pending), "synced": synced, "refreshed": refreshed}


def to_task_payload(session: Session, task: AnnotationTask) -> dict | None:
    """把 annotation task 的 LS 状态并入 Job 信封（前端「去 LS 标注」入口用）。

    新增 `ls_public_url`（**公网**宿主 URL，浏览器/iframe 可访问，非内网）+ `ls_project_ids`
    （该任务样本映射到的 LS 项目 id，去重，供 iframe 组装项目 URL）。`ls_status=legacy`
    即未走 LS（off / 回退模拟路径），前端据此决定是否嵌入。
    """
    if task is None:
        return None
    projects = session.exec(
        select(AnnotationLsSync.ls_project_id)
        .where(
            AnnotationLsSync.annotation_task_id == task.id,
            AnnotationLsSync.ls_project_id.isnot(None),
        )
        .distinct()
    ).all()
    return {
        "id": task.id,
        "source": task.source,
        "ls_status": task.ls_status,
        "ls_public_url": settings.label_studio_public_url,
        "ls_project_ids": [int(p) for p in projects if p is not None],
        "created_at": _iso_utc(task.created_at),
    }
