"""分段样本**段级标注**（服务层）。

一期范围（2026-09-22）：只面向 **`rules_version >= 3` 且已成功**的分段任务——一个标注
对象就是一个 `Sample`（= 一个时间窗 + 一个多模态样本包），每段**只有一个主结论**：

- `label = normal`：正常，`defect_category_id` / `defect_category_name` 必须为空；
- `label = defect`：缺陷，**必须**选一个主缺陷类别。

不做框/点/掩膜，也不做两级精度（`annotations` 表那套 `kind` 三态是给旧标注流程用的，
两条线互不影响）。

## 词表与稳定 ID

主缺陷类别存在 `option_items`（`group_key='defect_category'`，见
`services/settings.OPTION_GROUPS`——**复用系统设置那套字典设施**，不新建表）。
本服务只读它，增删改一律走 `api/v1/settings.py`（写操作仅管理员）。

标注行同时存 `defect_category_id`（稳定 ID）与 `defect_category_name`（**当时名称快照**）：
类别改名/停用后历史标注仍按原名展示；已被引用的类别在设置页删除时会被降级为停用
（`settings.reference_count` 对本组按 **id** 统计引用）。

**停用只挡新写入**：修改一条已经引用了停用类别的旧标注（原样保留该类别）是允许的
——否则类别一停用，那条历史标注就再也改不动了（同登记页"编辑时放行与当前值相同"的口径）。

## 数据集构建消费

`snapshot_for_samples` 产出与 `datasets._annotation_snapshots` **同形的冻结快照**
（`{category, confidence, kind, label}`），构建时落进 `dataset_items.annotations`；
训练侧（`torch_training`）优先认 `label`，认不到才按类别白名单折叠——所以词表怎么改
都不会让段级标注在训练里被静默折错。

本模块**不 commit**（与其它服务一致），由路由统一提交。
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlmodel import Session, select

from app.models.analysis import Sample, SampleAnnotation, SplitTask
from app.models.data import DataRecord, DataVersion, User
from app.models.settings import OptionItem
from app.services import splitting
from app.services.jobs import _iso_utc
from app.services.settings import DEFECT_CATEGORY_GROUP

#: 段级标注数据的 schema 版本。数据集构建/导出消费时必须先认这个版本号，
#: 否则将来换 schema 会静默读错。
SCHEMA_VERSION = 1

LABEL_NORMAL = "normal"
LABEL_DEFECT = "defect"
LABELS: tuple[str, ...] = (LABEL_NORMAL, LABEL_DEFECT)

#: 复核态默认值。一期 UI 不暴露复核流程，但列必须有默认值（将来加复核态不必改表）。
DEFAULT_REVIEW_STATUS = "approved"

MAX_NOTE_LENGTH = 512

#: 样本列表单页上限（与其它列表端点口径一致；工作台按页拉取后本地汇总）。
MAX_PAGE_SIZE = 200


class SampleAnnotationError(ValueError):
    """段级标注的业务错误（参数/前置条件），由路由统一转 400。"""


class TaskNotAnnotatable(SampleAnnotationError):
    """分段任务不满足段级标注前置条件（未成功 / 非 v3）。"""


# ── 前置条件与词表 ────────────────────────────────────────────────────


def is_segment_task(task: SplitTask) -> bool:
    """是否 v3 分段任务（`rules_version >= 3`）——段级标注**只**面向它。"""
    return int((task.rules or {}).get("rules_version") or 1) >= splitting.RULES_VERSION


def task_block_reason(session: Session, task: SplitTask) -> str | None:
    """返回不可标注的原因；可标注返回 None。"""
    if not is_segment_task(task):
        return "仅支持对 v3 分段任务（时间统一的多模态样本）做段级标注"
    from app.models.jobs import Job  # 局部导入：仅本函数用

    job = session.get(Job, task.job_id)
    if job is None or job.status != "succeeded":
        return "分段任务尚未成功完成，暂不能标注"
    return None


def list_categories(session: Session, *, active_only: bool = False) -> list[dict]:
    """主缺陷词表（`sort_order` 升序；`active_only` 时只给启用项）。"""
    rows = session.exec(
        select(OptionItem)
        .where(OptionItem.group_key == DEFECT_CATEGORY_GROUP)
        .order_by(OptionItem.sort_order, OptionItem.id)
    ).all()
    return [
        {
            "id": row.id,
            "value": row.value,
            "active": bool(row.active),
            "sort_order": int(row.sort_order or 0),
        }
        for row in rows
        if not active_only or bool(row.active)
    ]


def category_by_id(session: Session, category_id: int) -> OptionItem | None:
    row = session.get(OptionItem, category_id)
    if row is None or row.group_key != DEFECT_CATEGORY_GROUP:
        return None
    return row


# ── 序列化 ────────────────────────────────────────────────────────────


def annotation_payload(row: SampleAnnotation | None, *, sample_id: int | None = None) -> dict | None:
    """标注行 → 对外载荷；未标注返回 None。"""
    if row is None:
        return None
    return {
        "sample_id": row.sample_id,
        "label": row.label,
        "defect_category_id": row.defect_category_id,
        "defect_category_name": row.defect_category_name,
        "note": row.note,
        "schema_version": row.schema_version,
        "review_status": row.review_status,
        "annotator": row.annotator,
        "created_at": _iso_utc(row.created_at),
        "updated_at": _iso_utc(row.updated_at),
    }


def _row_payload(sample: Sample, annotation: SampleAnnotation | None) -> dict:
    """样本列表行：只给导航与进度需要的**轻量**字段，不带 `meta`/产物键。"""
    return {
        "id": sample.id,
        "frame_no": sample.frame_no,
        "start_time": sample.start_time,
        "end_time": sample.end_time,
        "annotated": annotation is not None,
        "label": annotation.label if annotation is not None else None,
        "defect_category_name": (
            annotation.defect_category_name if annotation is not None else None
        ),
    }


# ── 读取 ──────────────────────────────────────────────────────────────


def annotation_of(session: Session, sample_id: int) -> SampleAnnotation | None:
    return session.exec(
        select(SampleAnnotation).where(SampleAnnotation.sample_id == sample_id)
    ).first()


def _annotations_for(session: Session, sample_ids: list[int]) -> dict[int, SampleAnnotation]:
    """批量取标注（防列表 N+1）。"""
    if not sample_ids:
        return {}
    rows = session.exec(
        select(SampleAnnotation).where(SampleAnnotation.sample_id.in_(sample_ids))
    ).all()
    return {row.sample_id: row for row in rows}


def list_samples(
    session: Session,
    task: SplitTask,
    *,
    page: int = 1,
    page_size: int = 50,
    only_unannotated: bool = False,
) -> tuple[list[dict], int]:
    """任务内样本分页（按时间窗排序）。

    **未标注筛选在 SQL 侧完成**（`sample_annotations` 左联）——拉全量再在内存里过滤，
    几千切片时会随任务规模线性变慢。
    """
    page = max(1, int(page))
    page_size = max(1, min(MAX_PAGE_SIZE, int(page_size)))
    base = select(Sample).where(Sample.split_task_id == task.id)
    count_stmt = (
        select(Sample.id)
        .where(Sample.split_task_id == task.id)
        .outerjoin(SampleAnnotation, SampleAnnotation.sample_id == Sample.id)
    )
    if only_unannotated:
        base = base.outerjoin(
            SampleAnnotation, SampleAnnotation.sample_id == Sample.id
        ).where(SampleAnnotation.id.is_(None))
        count_stmt = count_stmt.where(SampleAnnotation.id.is_(None))
    total = len(session.exec(count_stmt).all())
    rows = session.exec(
        base.order_by(Sample.start_time, Sample.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    annotations = _annotations_for(session, [row.id for row in rows])
    return [_row_payload(row, annotations.get(row.id)) for row in rows], total


def _annotated_counts(session: Session, task_ids: list[int]) -> dict[int, int]:
    """任务 → 已标注样本数（一次 group_by，避免逐任务查）。"""
    from sqlalchemy import func as sa_func

    if not task_ids:
        return {}
    rows = session.exec(
        select(Sample.split_task_id, sa_func.count(SampleAnnotation.id))
        .join(SampleAnnotation, SampleAnnotation.sample_id == Sample.id)
        .where(Sample.split_task_id.in_(task_ids))
        .group_by(Sample.split_task_id)
    ).all()
    return {int(task_id): int(count) for task_id, count in rows}


def list_annotatable_tasks(session: Session, weld_id: str) -> list[dict]:
    """该焊缝**已完成且为 v3** 的分段任务（标注工作台的入口列表）。

    只列 `Job.status == 'succeeded'` 且 `rules_version >= 3` 的任务——非 v3 的历史任务
    没有统一时间窗与多模态样本包，段级标注对它们不成立（前置条件见 `task_block_reason`）。
    """
    from sqlalchemy import func as sa_func

    from app.models.jobs import Job

    rows = session.exec(
        select(SplitTask, Job, DataVersion)
        .join(Job, Job.id == SplitTask.job_id)
        .join(DataVersion, DataVersion.id == SplitTask.version_id)
        .join(DataRecord, DataRecord.id == DataVersion.record_id)
        .where(DataRecord.weld_id == weld_id, Job.status == "succeeded")
        .order_by(SplitTask.id.desc())
    ).all()
    candidates = [(task, job, version) for task, job, version in rows if is_segment_task(task)]
    task_ids = [task.id for task, _, _ in candidates]
    totals = {int(tid): int(count) for tid, count in session.exec(
        select(Sample.split_task_id, sa_func.count(Sample.id))
        .where(Sample.split_task_id.in_(task_ids or [0]))
        .group_by(Sample.split_task_id)
    ).all()}
    annotated = _annotated_counts(session, task_ids)
    out: list[dict] = []
    for task, job, version in candidates:
        total = totals.get(task.id, 0)
        done = annotated.get(task.id, 0)
        rules = dict(task.rules or {})
        out.append({
            "task_id": job.job_uid,
            "split_task_id": task.id,
            "version_id": version.id,
            "version_no": version.version_no,
            "sample_count": task.sample_count if task.sample_count is not None else total,
            "window_seconds": rules.get("window_seconds"),
            "stride_seconds": rules.get("stride_seconds"),
            "effective_range": rules.get("event_bounds"),
            "finished_at": _iso_utc(job.finished_at),
            "progress": {
                "total": total,
                "annotated": done,
                "unannotated": total - done,
                "progress": round(done / total * 100, 1) if total else 0.0,
            },
        })
    return out


def stats(session: Session, task: SplitTask) -> dict:
    """标注进度与缺陷分布（工作台顶部与数据集构建的进度口径）。"""
    sample_ids = list(
        session.exec(select(Sample.id).where(Sample.split_task_id == task.id)).all()
    )
    total = len(sample_ids)
    annotations = _annotations_for(session, sample_ids)
    normal = sum(1 for row in annotations.values() if row.label == LABEL_NORMAL)
    defect = sum(1 for row in annotations.values() if row.label == LABEL_DEFECT)
    counter: dict[str | None, int] = {}
    for row in annotations.values():
        if row.label == LABEL_DEFECT:
            key = row.defect_category_name or "未分类"
            counter[key] = counter.get(key, 0) + 1
    return {
        "total": total,
        "annotated": len(annotations),
        "unannotated": total - len(annotations),
        "normal": normal,
        "defect": defect,
        "progress": round(len(annotations) / total * 100, 1) if total else 0.0,
        "defect_distribution": [
            {"name": name, "count": count}
            for name, count in sorted(counter.items(), key=lambda kv: (-kv[1], str(kv[0])))
        ],
    }


# ── 写入 ──────────────────────────────────────────────────────────────


def _validate(
    session: Session,
    *,
    label: str,
    category_id: int | None,
    note: str | None,
    existing: SampleAnnotation | None,
) -> tuple[OptionItem | None, str | None]:
    """校验结论并返回 `(类别行, 规整后的备注)`；不合法抛 `SampleAnnotationError`。"""
    if label not in LABELS:
        raise SampleAnnotationError(f"label 需为 {'/'.join(LABELS)}")
    if note is not None:
        note = note.strip() or None
        if note is not None and len(note) > MAX_NOTE_LENGTH:
            raise SampleAnnotationError(f"备注不能超过 {MAX_NOTE_LENGTH} 字")

    if label == LABEL_NORMAL:
        if category_id is not None:
            raise SampleAnnotationError("结论为「正常」时不能指定缺陷类别")
        return None, note

    if category_id is None:
        raise SampleAnnotationError("结论为「缺陷」时必须选择一个主缺陷类别")
    category = category_by_id(session, category_id)
    if category is None:
        raise SampleAnnotationError("缺陷类别不存在")
    # 停用类别只挡**新写入**：这条标注本来就引用了它（原样保留）时放行，
    # 否则类别一停用，那条历史标注就再也改不动了。
    if not bool(category.active) and (
        existing is None or existing.defect_category_id != category.id
    ):
        raise SampleAnnotationError(f"缺陷类别「{category.value}」已停用，不能用于新建标注")
    return category, note


def upsert_annotation(
    session: Session,
    sample: Sample,
    *,
    label: str,
    category_id: int | None,
    note: str | None,
    user: User,
) -> SampleAnnotation:
    """写入/更新一个样本的段级结论（**upsert**：一个样本恒一行）。

    类别名取**写入当时**的词表值存快照——之后改名/停用都不会改写这条标注的展示。
    """
    existing = annotation_of(session, sample.id)
    category, clean_note = _validate(
        session, label=label, category_id=category_id, note=note, existing=existing
    )
    now = datetime.now(timezone.utc)
    if existing is None:
        existing = SampleAnnotation(
            sample_id=sample.id, created_at=now, schema_version=SCHEMA_VERSION
        )
    existing.label = label
    existing.defect_category_id = category.id if category is not None else None
    existing.defect_category_name = category.value if category is not None else None
    existing.note = clean_note
    existing.review_status = existing.review_status or DEFAULT_REVIEW_STATUS
    existing.annotator = user.display_name or user.username
    existing.annotator_id = user.id
    existing.updated_at = now
    session.add(existing)
    session.flush()
    return existing


def clear_annotation(session: Session, sample: Sample) -> bool:
    """撤销标注（回到未标注态）；本来就没有标注返回 False。"""
    row = annotation_of(session, sample.id)
    if row is None:
        return False
    session.delete(row)
    session.flush()
    return True


# ── 数据集构建 / 导出的消费入口 ────────────────────────────────────────


def annotated_sample_ids(session: Session, sample_ids: list[int]) -> set[int]:
    """这批样本里已标注的 id 集合（构建时的"空标注切片"判定）。"""
    if not sample_ids:
        return set()
    return set(
        session.exec(
            select(SampleAnnotation.sample_id).where(
                SampleAnnotation.sample_id.in_(sample_ids)
            )
        ).all()
    )


def snapshot_for_samples(session: Session, sample_ids: list[int]) -> dict[int, list[dict]]:
    """样本 → 冻结标注快照（与 `datasets._annotation_snapshots` 同形）。

    形状对齐既有 `dataset_items.annotations`：`{category, confidence, kind}`，另加
    段级标注特有的 `label`——训练侧优先认 `label`（`defect`/`normal`），认不到才按类别
    白名单折叠，这样词表里加一个自定义类别也不会把结论折反。
    """
    if not sample_ids:
        return {}
    rows = session.exec(
        select(SampleAnnotation)
        .where(SampleAnnotation.sample_id.in_(sample_ids))
        .order_by(SampleAnnotation.id)
    ).all()
    out: dict[int, list[dict]] = {}
    for row in rows:
        out.setdefault(row.sample_id, []).append(
            {
                "category": row.defect_category_name or "正常",
                "confidence": None,
                "kind": "segment_class",
                "label": row.label,
            }
        )
    return out


def export_payload(session: Session, task: SplitTask) -> dict:
    """段级标注的可迁移导出（数据集构建/离线训练的输入）。

    只导出结论与定位信息（样本 id + 时间窗），**不含媒体字节**——媒体按对象键走
    预签名下载，与其它导出端点同口径。顶层带 `schema_version`，消费方必须先认它。
    """
    version = session.get(DataVersion, task.version_id)
    record = session.get(DataRecord, version.record_id) if version is not None else None
    sample_ids = list(
        session.exec(
            select(Sample.id)
            .where(Sample.split_task_id == task.id)
            .order_by(Sample.start_time, Sample.id)
        ).all()
    )
    annotations = _annotations_for(session, sample_ids)
    rows = session.exec(
        select(Sample).where(Sample.id.in_(sample_ids)).order_by(Sample.start_time, Sample.id)
    ).all()
    return {
        "schema_version": SCHEMA_VERSION,
        "task_id": task.id,
        "weld_id": record.weld_id if record is not None else None,
        "source_version_id": task.version_id,
        "label_vocabulary": [
            {"id": item["id"], "name": item["value"], "active": item["active"]}
            for item in list_categories(session)
        ],
        "sample_count": len(rows),
        "annotated_count": len(annotations),
        "items": [
            {
                "sample_id": row.id,
                "sample_index": row.frame_no,
                "start_time": row.start_time,
                "end_time": row.end_time,
                **(
                    {
                        "label": annotation.label,
                        "defect_category_id": annotation.defect_category_id,
                        "defect_category_name": annotation.defect_category_name,
                        "note": annotation.note,
                        "annotator": annotation.annotator,
                    }
                    if (annotation := annotations.get(row.id)) is not None
                    else {"label": None}
                ),
            }
            for row in rows
        ],
    }
