"""标注服务（Task 14）：标注任务 / 样本 / AI 预标注 / 标注保存（模拟）。

实施边界（`docs/开发规范.md` §3.1）：标注 = 真实异步编排 + 模拟结果——Job 生命周期与
`samples`/`annotations` 落库为真，AI 预标注为**确定性模拟**（seed = `sample_id`）。

结构与复用：
- `simulate_annotation(session, task, job)`：标注 handler 的领域逻辑——若来源为
  `split_task`，把该切分任务的样本 `annotation_task_id` 指向本任务，回填 `job.result`。
- 端点辅助：`resolve_*`（job_uid / DB id 双兼容解析，供前端轮询 job_id 直用）、
  `list_label_categories`、`import_samples`、`list_samples`、`get_sample_detail`、
  `pretag_sample`、`save_labels`、payload 序列化。

**confidence 语义**（契约 §3.4）：每条 `Annotation` 行自带 confidence（Numeric(4,3)）；
样本级 `confidence` = 当前标注置信度均值（`_sample_confidence`）。AI 预标注落库
（annotator=`AI预标注`）→ 人工 `save_labels` 覆盖写（annotator=当前用户），未显式给
confidence 的标签沿用先前（预标注）同类别置信度。

坑/边界：
- 写操作（import/pretag/save_labels）**不 commit**——由路由统一 commit（与
  `services/jobs.py` 约定一致）；`simulate_annotation` 内的 commit 是执行器专用 session
  场景（同 alignment 服务）。
- `session.exec(select(聚合))` 返回标量（`.one()` 直接是 int），勿再 `[0]` 下标。
- 样本列表批量预查 annotations（`in_`），避免 per-样本 N+1。
"""

from __future__ import annotations

import random
import time
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal

from sqlmodel import Session, func, select

from app.models.analysis import (
    Annotation,
    AnnotationTask,
    LabelCategory,
    Sample,
    SplitTask,
)
from app.models.jobs import Job
from app.services.jobs import _iso_utc, get_job_by_uid, mark_succeeded

#: 进度逐步递增点（0→100），与 split/alignment handler 一致。
_PROGRESS_STEPS: tuple[int, ...] = (20, 40, 60, 80, 100)
_PROGRESS_SLEEP: float = 0.005

#: 模拟图像尺寸（AI 预标注框坐标落在 640×480 内）。
_IMG_W, _IMG_H = 640, 480


# ── payload 序列化（confidence 语义在此实现） ──────────────────────────


def annotation_payload(a: Annotation) -> dict:
    """单条标注 → JSON（confidence Decimal → float）。"""
    return {
        "id": a.id,
        "sample_id": a.sample_id,
        "category": a.category,
        "box": a.box or [],
        "confidence": float(a.confidence) if a.confidence is not None else None,
        "annotator": a.annotator,
        "created_at": _iso_utc(a.created_at),
        "updated_at": _iso_utc(a.updated_at),
    }


def _sample_confidence(annotations: list[Annotation]) -> float | None:
    """样本级 confidence = 当前标注置信度均值（无标注 → None）。"""
    confs = [float(a.confidence) for a in annotations if a.confidence is not None]
    if not confs:
        return None
    return round(sum(confs) / len(confs), 3)


def sample_payload(sample: Sample, annotations: list[Annotation]) -> dict:
    """样本 → JSON（含 annotations[] 与样本级 confidence）。"""
    return {
        "id": sample.id,
        "split_task_id": sample.split_task_id,
        "annotation_task_id": sample.annotation_task_id,
        "frame_no": sample.frame_no,
        "object_keys": sample.object_keys or [],
        "meta": sample.meta,
        "annotations": [annotation_payload(a) for a in annotations],
        "confidence": _sample_confidence(annotations),
    }


# ── 解析（job_uid / DB id 双兼容） ─────────────────────────────────────


def resolve_annotation_task(session: Session, identifier: str) -> AnnotationTask | None:
    """`task_id` 兼容 job_uid 与 annotation_tasks 表 DB id（前端创建后只拿到 job_id）。

    先按 job_uid 查（type=annotation 才认），再按 int 查 DB id；都不中 → None。
    """
    job = get_job_by_uid(session, identifier)
    if job is not None and job.type == "annotation":
        task = session.exec(
            select(AnnotationTask).where(AnnotationTask.job_id == job.id)
        ).first()
        if task is not None:
            return task
    try:
        return session.get(AnnotationTask, int(identifier))
    except (TypeError, ValueError):
        return None


def resolve_split_task(session: Session, identifier: str) -> SplitTask | None:
    """`split_task_id` 兼容 job_uid 与 split_tasks 表 DB id。同上。"""
    job = get_job_by_uid(session, identifier)
    if job is not None and job.type == "split":
        task = session.exec(
            select(SplitTask).where(SplitTask.job_id == job.id)
        ).first()
        if task is not None:
            return task
    try:
        return session.get(SplitTask, int(identifier))
    except (TypeError, ValueError):
        return None


# ── 查询 ─────────────────────────────────────────────────────────────


def list_label_categories(session: Session) -> list[dict]:
    """`GET /label-categories`：模型口径 5 类（seed），按 id 升序。"""
    cats = session.exec(select(LabelCategory).order_by(LabelCategory.id)).all()
    return [{"id": c.id, "name": c.name, "color": c.color} for c in cats]


def list_samples(
    session: Session, task: AnnotationTask, page: int = 1, page_size: int = 20
) -> tuple[list[dict], int]:
    """标注任务样本分页列表：每样本含 annotations[]（批量预查，防 N+1）。

    返回 (items, total)，item 为 `sample_payload`。调用方（路由）commit。
    """
    total = int(
        session.exec(
            select(func.count(Sample.id)).where(Sample.annotation_task_id == task.id)
        ).one()
    )
    samples = session.exec(
        select(Sample)
        .where(Sample.annotation_task_id == task.id)
        .order_by(Sample.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    ann_map: dict[int, list[Annotation]] = defaultdict(list)
    if samples:
        rows = session.exec(
            select(Annotation)
            .where(Annotation.sample_id.in_([s.id for s in samples]))
            .order_by(Annotation.id)
        ).all()
        for a in rows:
            ann_map[a.sample_id].append(a)
    items = [sample_payload(s, ann_map[s.id]) for s in samples]
    return items, total


def get_sample(session: Session, task: AnnotationTask, sample_id: int) -> Sample | None:
    """样本详情查询：样本必须属于该标注任务，否则 None。"""
    sample = session.get(Sample, sample_id)
    if sample is None or sample.annotation_task_id != task.id:
        return None
    return sample


def get_sample_detail(
    session: Session, task: AnnotationTask, sample_id: int
) -> dict | None:
    """样本 + 最新标注 + 样本级 confidence；不属于该任务 → None。"""
    sample = get_sample(session, task, sample_id)
    if sample is None:
        return None
    anns = list(
        session.exec(
            select(Annotation)
            .where(Annotation.sample_id == sample.id)
            .order_by(Annotation.id)
        ).all()
    )
    return sample_payload(sample, anns)


# ── 导入 ─────────────────────────────────────────────────────────────


def import_samples(
    session: Session,
    task: AnnotationTask,
    source: str,
    object_keys: list[str] | None,
    split_task_id: str | None,
) -> int:
    """把样本加入标注任务（`POST …/import`），返回导入样本数。**不 commit**。

    - `source='files'`：按 `object_keys` 逐条建 `Sample` 行（annotation_task_id=task.id）；
    - `source='split_task'`：把该切分任务的样本 `annotation_task_id` 改指本任务。
    未知 source / 切分任务不存在 → 抛 `ValueError`（路由转 400/404）。
    """
    if source == "files":
        count = 0
        for key in object_keys or []:
            session.add(
                Sample(
                    annotation_task_id=task.id,
                    object_keys=[key],
                    meta={"source": "manual-import"},
                )
            )
            count += 1
        return count
    if source == "split_task":
        split = resolve_split_task(session, split_task_id or "")
        if split is None:
            raise ValueError(f"切分任务不存在: {split_task_id!r}")
        samples = session.exec(
            select(Sample).where(Sample.split_task_id == split.id)
        ).all()
        for s in samples:
            s.annotation_task_id = task.id
            session.add(s)
        return len(samples)
    raise ValueError(f"未知导入来源: {source!r}")


# ── AI 预标注 / 标注保存（替换语义） ───────────────────────────────────


def pretag_sample(
    session: Session, task: AnnotationTask, sample: Sample
) -> list[Annotation]:
    """AI 预标注（同步，确定性模拟）：2 个疑似区域 + 置信度，**替换**样本现有标注。

    seed = `random.Random(sample.id)` → 同样本每次结果一致（测试可复现）。类别从
    label_categories 确定性抽 2 个（不足 2 个取全部）；框坐标落在 640×480 内；
    confidence ∈ [0.72, 0.98]。annotator=`AI预标注`。**不 commit**（路由提交）。
    """
    cats = list(session.exec(select(LabelCategory).order_by(LabelCategory.id)).all())
    names = [c.name for c in cats] or ["正常"]
    rng = random.Random(sample.id)
    picked = rng.sample(names, min(2, len(names)))

    for old in session.exec(
        select(Annotation).where(Annotation.sample_id == sample.id)
    ).all():
        session.delete(old)

    now = datetime.now(timezone.utc)
    new_annotations: list[Annotation] = []
    for name in picked:
        box = [
            rng.randint(10, _IMG_W - 140),
            rng.randint(10, _IMG_H - 110),
            rng.randint(40, 120),
            rng.randint(40, 90),
        ]
        ann = Annotation(
            sample_id=sample.id,
            category=name,
            box=box,
            confidence=Decimal(str(round(rng.uniform(0.72, 0.98), 3))),
            annotator="AI预标注",
            created_at=now,
            updated_at=now,
        )
        session.add(ann)
        new_annotations.append(ann)
    session.flush()
    return new_annotations


def save_labels(
    session: Session,
    task: AnnotationTask,
    sample: Sample,
    labels: list,
    annotator: str,
) -> list[Annotation]:
    """覆盖写样本标注（`POST …/labels`）：删旧插新，annotator=当前用户。**不 commit**。

    confidence 缺省时沿用先前（AI 预标注）同类别置信度（`prev_conf` 在建新行前读取）。
    类别/框坐标合法性由路由预校验（400）。
    """
    existing = session.exec(
        select(Annotation).where(Annotation.sample_id == sample.id)
    ).all()
    prev_conf: dict[str, float | None] = {}
    for a in existing:
        prev_conf[a.category] = (
            float(a.confidence) if a.confidence is not None else None
        )
    for a in existing:
        session.delete(a)

    now = datetime.now(timezone.utc)
    new_annotations: list[Annotation] = []
    for label in labels:
        conf = label.confidence
        if conf is None:
            conf = prev_conf.get(label.category)
        ann = Annotation(
            sample_id=sample.id,
            category=label.category,
            box=label.box,
            confidence=Decimal(str(conf)) if conf is not None else None,
            annotator=annotator,
            created_at=now,
            updated_at=now,
        )
        session.add(ann)
        new_annotations.append(ann)
    session.flush()
    return new_annotations


# ── 标注 handler 领域逻辑 ─────────────────────────────────────────────


def simulate_annotation(session: Session, task: AnnotationTask, job: Job) -> dict:
    """模拟执行一次标注任务，返回写入 `job.result` 的 dict。

    步骤：
    1. 进度逐步 0→100（逐次 commit + 小睡，轮询可见）；
    2. 若来源为 `split_task`：把该切分任务的全部样本 `annotation_task_id` 指向本任务；
    3. `mark_succeeded(job, result)`（source / samples_count / name）。
    commit 由调用方（执行器）在返回后统一提交。
    """
    for progress in _PROGRESS_STEPS:
        job.progress = progress
        session.commit()
        time.sleep(_PROGRESS_SLEEP)

    reassigned = 0
    if task.source == "split_task" and task.split_task_id is not None:
        samples = session.exec(
            select(Sample).where(Sample.split_task_id == task.split_task_id)
        ).all()
        for s in samples:
            s.annotation_task_id = task.id
            session.add(s)
        reassigned = len(samples)

    result = {
        "source": task.source,
        "name": task.name,
        "samples_count": reassigned,
    }
    mark_succeeded(session, job, result)
    return result
