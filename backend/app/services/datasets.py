"""数据集服务（Task 15）：数据集 CRUD / 输入维度 / 适配检查 / 版本 / 血缘 / 构建任务。

契约 `docs/API接口清单.md` §3.5；业务规则 `docs/数据库设计.md` §5（固定快照、按焊缝 ID
划分避免泄漏、quality 计算）。实施边界 §3.1：构建任务 = 真实异步编排 + 模拟结果——Job
生命周期与 `dataset_items`/`dataset_versions.quality`/快照写 MinIO 为真，样本来源不足时
兜底生成**确定性合成样本**（引用真实登记焊缝），保证 demo 非空。

**写操作不 commit**（由路由/执行器统一提交，与 `services/jobs.py` 约定一致）；仅
`run_build` 内的进度 commit 是执行器专用 session 场景（同 alignment/annotation 服务）。

关键设计（坑，改动勿破坏）：
- `dataset_no`：`DS-{任务类别}-{序号}`，类别 = DEFECT/POOL/QUALITY（对齐 seed），
  序号 = 该类别前缀记录数 + 1（零填充 3 位）。
- 输入维度 7 项与 `src/App.tsx::inputDimensions` 顺序一致；`required` 照 `requiredByTask`
  （目标检测→[Current,Voltage,GasSpeed]、语义分割→[熔池视频]、多模态回归→[Current,Voltage]）。
  维度可用性由**当前版本 dataset_items→samples.object_keys 按扩展名/内容启发式**判定。
- readiness 照 `ModelReadiness`：每任务 4 项检查，全部 passed → 可训练，否则暂不可训练。
- 构建分片：候选样本按 record_id 分组 → 稳定 seed 打乱组序 → 8:1:1 划分，**同焊缝样本
  绝不跨 split**（防泄漏）。组数 <3 时退化为 train / train+test（宁可少分片也不泄漏）。
- 兜底合成样本：来源 gather 为空时，遍历全部登记焊缝各生成 3 个合成 `Sample`（对象键按
  焊缝 modalities 推导），使按焊缝划分的 demo 非空且可测。
- 快照对象键：`datasets/{dataset_version_id}/snapshot.json`；写 MinIO **尽力而为**
  （失败仅告警不使构建失败，本地 DB 为权威）。
- `name`/`note` 请求字段：`dataset_versions` 表无对应列（文档 §3.15 即无），仅接受不落库。
"""

from __future__ import annotations

import io
import json
import random
import time
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal

from loguru import logger
from sqlalchemy import Integer, cast, func, or_
from sqlalchemy.orm import aliased
from sqlmodel import Session, select

from app.models.analysis import (
    Annotation,
    AnnotationTask,
    Sample,
    SplitTask,
)
from app.models.data import DataRecord, DataVersion
from app.models.datasets import Dataset, DatasetBuildTask, DatasetItem, DatasetVersion
from app.models.jobs import Job
from app.models.models import TrainingTask
from app.services.annotation import resolve_annotation_task, resolve_split_task
from app.services.jobs import _iso_utc, mark_succeeded

#: 进度逐步递增点（与 split/annotation handler 一致）。
_PROGRESS_STEPS: tuple[int, ...] = (20, 40, 60, 80, 100)
_PROGRESS_SLEEP: float = 0.005

#: 输入维度（照 App.tsx inputDimensions，顺序一致）。
INPUT_DIMENSIONS: list[str] = [
    "Voltage",
    "GasSpeed",
    "Current",
    "Molten_feature",
    "Sound_feature",
    "焊缝照片",
    "熔池视频",
]

#: 各任务必需维度（照 App.tsx requiredByTask）。
REQUIRED_BY_TASK: dict[str, list[str]] = {
    "目标检测": ["Current", "Voltage", "GasSpeed"],
    "语义分割": ["熔池视频"],
    "多模态回归": ["Current", "Voltage"],
}

#: 各任务模型适配检查项（照 App.tsx ModelReadiness）。
READINESS_CHECKS: dict[str, list[str]] = {
    "目标检测": [
        "Current、Voltage、GasSpeed 均完整",
        "异常区段标签已审核",
        "信号采样率与时间轴一致",
        "按焊缝 ID 完成数据划分",
    ],
    "语义分割": [
        "熔池视频已切分为图像帧",
        "图像与像素级掩膜数量一致",
        "标注审核通过率 ≥ 90%",
        "按焊缝 ID 完成数据划分",
    ],
    "多模态回归": [
        "Current 与 Voltage 时间轴已对齐",
        "至少具备两种输入模态",
        "质量标签完整且无空值",
        "按焊缝 ID 完成数据划分",
    ],
}

#: 任务 → dataset_no 中间段（对齐 seed DATASET_DEMO）。
_TASK_CATEGORY: dict[str, str] = {
    "目标检测": "DEFECT",
    "语义分割": "POOL",
    "多模态回归": "QUALITY",
}

#: 构建任务来源类型白名单（契约 §3.5 DatasetSource.type）。
BUILD_SOURCES: tuple[str, ...] = ("annotation_task", "split_task", "manual", "filter")

_VIDEO_EXTS = (".mp4", ".avi", ".mkv", ".mov")
_IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".bmp")
_AUDIO_EXTS = (".wav", ".mp3", ".flac", ".m4a")
_TS_EXTS = (".csv", ".dat", ".txt")

#: 兜底合成样本：每焊缝生成的样本数（4 焊缝 → 12 样本，按焊缝分组划分仍覆盖 train/val/test）。
_SYNTH_PER_RECORD = 3


# ── 业务号 / 解析 ─────────────────────────────────────────────────────


def next_dataset_no(session: Session, task: str) -> str:
    """`DS-{类别}-{序号}`：序号 = 全库数据集数 + 1（对齐 seed 全局序号 DEFECT-001/POOL-002/QUALITY-003）。"""
    category = _TASK_CATEGORY.get(task, "GEN")
    seq = int(session.exec(select(func.count(Dataset.id))).one()) + 1
    return f"DS-{category}-{seq:03d}"


def get_dataset_by_identifier(session: Session, identifier: str) -> Dataset | None:
    """兼容 DB id / dataset_no 两种标识（对齐 welds.get_record_by_identifier）。"""
    try:
        dataset = session.get(Dataset, int(identifier))
        if dataset is not None:
            return dataset
    except (TypeError, ValueError):
        pass
    return session.exec(
        select(Dataset).where(Dataset.dataset_no == identifier)
    ).first()


# ── 数据集 CRUD ──────────────────────────────────────────────────────


def list_datasets(session: Session) -> list[dict]:
    """数据集列表：批量预查当前版本，避免逐条 N+1。"""
    datasets = session.exec(
        select(Dataset).order_by(Dataset.created_at.desc(), Dataset.id.desc())
    ).all()
    ids = [d.current_version_id for d in datasets if d.current_version_id is not None]
    versions: dict[int, DatasetVersion] = {}
    if ids:
        for v in session.exec(
            select(DatasetVersion).where(DatasetVersion.id.in_(ids))
        ).all():
            versions[v.id] = v
    return [dataset_payload(d, versions.get(d.current_version_id)) for d in datasets]


def create_dataset(
    session: Session, name: str, task: str, source: object | None = None
) -> Dataset:
    """新建数据集（status=标注中、sample_count=0）。同名 → 抛 `ValueError`（路由转 409）。"""
    if session.exec(select(Dataset).where(Dataset.name == name)).first() is not None:
        raise ValueError("数据集名称已存在")
    now = datetime.now(timezone.utc)
    dataset = Dataset(
        dataset_no=next_dataset_no(session, task),
        name=name,
        task=task,
        sample_count=0,
        progress=Decimal("0.00"),
        status="标注中",
        created_at=now,
        updated_at=now,
    )
    session.add(dataset)
    session.flush()
    return dataset


def dataset_payload(
    dataset: Dataset,
    current_version: DatasetVersion | None = None,
    *,
    label_distribution: dict[str, int] | None = None,
) -> dict:
    """数据集 → JSON（列表/详情共用）。"""
    return {
        "id": dataset.id,
        "dataset_no": dataset.dataset_no,
        "name": dataset.name,
        "task": dataset.task,
        "sample_count": dataset.sample_count,
        "progress": float(dataset.progress) if dataset.progress is not None else None,
        "status": dataset.status,
        "current_version_id": dataset.current_version_id,
        "version": current_version.version_no if current_version else None,
        "split": current_version.split if current_version else None,
        "quality": current_version.quality if current_version else None,
        "label_distribution": label_distribution or {},
        "created_at": _iso_utc(dataset.created_at),
        "updated_at": _iso_utc(dataset.updated_at),
    }


# ── 输入维度 / 适配检查 ──────────────────────────────────────────────


def get_dimensions(session: Session, dataset: Dataset) -> list[dict]:
    """7 项输入维度：`{name, status(已具备|必需|缺失), required}`。

    可用性由当前版本样本的 object_keys 启发式判定（视频→熔池视频、图像→焊缝照片/熔池
    特征、时序→Current/Voltage/GasSpeed、音频→Sound_feature）。
    """
    available = _dimension_availability(session, dataset)
    required = set(REQUIRED_BY_TASK.get(dataset.task, []))
    result: list[dict] = []
    for dim in INPUT_DIMENSIONS:
        is_required = dim in required
        is_available = available.get(dim, False)
        if is_available:
            status = "已具备"
        elif is_required:
            status = "必需"
        else:
            status = "缺失"
        result.append({"name": dim, "status": status, "required": is_required})
    return result


def get_readiness(session: Session, dataset: Dataset) -> dict:
    """模型适配检查：`{readiness, checks:[{name, passed}]}`，全部通过 → 可训练。"""
    state = _readiness_state(session, dataset)
    checks = [
        {"name": name, "passed": _check_passed(name, state)}
        for name in READINESS_CHECKS.get(dataset.task, READINESS_CHECKS["目标检测"])
    ]
    readiness = "可训练" if all(c["passed"] for c in checks) else "暂不可训练"
    return {"readiness": readiness, "checks": checks}


def samples_for_version(session: Session, version_id: int) -> list[Sample]:
    """指定数据集版本的所有成员样本（dataset_items→samples）。"""
    return list(
        session.exec(
            select(Sample)
            .join(DatasetItem, DatasetItem.sample_id == Sample.id)
            .where(DatasetItem.dataset_version_id == version_id)
        ).all()
    )


def label_distribution_for_version(session: Session, version_id: int) -> dict[str, int]:
    """指定数据集版本的标签分布（按 annotation.category 计数）。"""
    rows = session.exec(
        select(Annotation.category, func.count(Annotation.id))
        .join(Sample, Sample.id == Annotation.sample_id)
        .join(DatasetItem, DatasetItem.sample_id == Sample.id)
        .where(DatasetItem.dataset_version_id == version_id)
        .group_by(Annotation.category)
        .order_by(Annotation.category)
    ).all()
    return {str(category): int(count) for category, count in rows}


def _current_version_samples(session: Session, dataset: Dataset) -> list[Sample]:
    """当前版本的所有成员样本（dataset_items→samples）。"""
    if dataset.current_version_id is None:
        return []
    return samples_for_version(session, dataset.current_version_id)


def _dimension_availability(session: Session, dataset: Dataset) -> dict[str, bool]:
    """当前版本成员样本的维度可用性（`get_dimensions`/`get_readiness` 用）。"""
    return _dimension_availability_from_samples(_current_version_samples(session, dataset))


def _dimension_availability_from_samples(samples: list[Sample]) -> dict[str, bool]:
    """按样本 `object_keys` 启发式判定各维度可用性（构建 quality 用**当前批样本**）。

    坑：quality 计算在 `datasets.current_version_id` 回填**之前**，若按数据集当前版本查样本
    会拿到 None/旧版本 → 必需维度恒判缺失。故 quality 必须传本次构建的 in-flight 样本。
    """
    available: dict[str, bool] = {d: False for d in INPUT_DIMENSIONS}
    for sample in samples:
        for key in sample.object_keys or []:
            low = key.lower()
            if low.endswith(_VIDEO_EXTS):
                available["熔池视频"] = True
            if low.endswith(_IMAGE_EXTS):
                available["焊缝照片"] = True
            if low.endswith(_IMAGE_EXTS) or "molten" in low:
                available["Molten_feature"] = True
            if low.endswith(_AUDIO_EXTS) or "audio" in low:
                available["Sound_feature"] = True
            if (
                low.endswith(_TS_EXTS)
                or "timeseries" in low
                or "current" in low
                or "voltage" in low
                or "gas" in low
                or "wire" in low
            ):
                available["Current"] = True
                available["Voltage"] = True
                available["GasSpeed"] = True
    return available


def readiness_for_version(
    session: Session,
    dataset: Dataset,
    version: DatasetVersion | None,
) -> dict:
    """指定版本的训练 readiness：供训练/测试服务端闸门复用。"""
    sample_rows = samples_for_version(session, version.id) if version is not None else []
    has_built = bool(sample_rows)
    if version is not None and not has_built and dataset.status == "可训练":
        checks = [
            {"name": name, "passed": True}
            for name in READINESS_CHECKS.get(dataset.task, READINESS_CHECKS["目标检测"])
        ]
        return {"readiness": "可训练", "checks": checks}
    quality = (version.quality or {}) if version else {}
    empty_label_rate = quality.get("empty_label_rate")
    annotation_ok = empty_label_rate is not None and empty_label_rate == 0
    dims = (
        _dimension_availability_from_samples(sample_rows)
        if version is not None
        else _dimension_availability(session, dataset)
    )
    checks = [
        {"name": name, "passed": _check_passed(name, {"dims": dims, "has_built": has_built, "annotation_ok": annotation_ok})}
        for name in READINESS_CHECKS.get(dataset.task, READINESS_CHECKS["目标检测"])
    ]
    readiness = "可训练" if all(c["passed"] for c in checks) else "暂不可训练"
    return {"readiness": readiness, "checks": checks}


def _readiness_state(session: Session, dataset: Dataset) -> dict:
    version = (
        session.get(DatasetVersion, dataset.current_version_id)
        if dataset.current_version_id is not None
        else None
    )
    ready = readiness_for_version(session, dataset, version)
    dims = _dimension_availability(session, dataset)
    return {
        "dims": dims,
        "has_built": any(check["name"] == "按焊缝 ID 完成数据划分" and check["passed"] for check in ready["checks"]),
        "annotation_ok": any(check["name"] in {"异常区段标签已审核", "标注审核通过率 ≥ 90%", "质量标签完整且无空值"} and check["passed"] for check in ready["checks"]),
    }


def _check_passed(name: str, state: dict) -> bool:
    dims: dict[str, bool] = state["dims"]
    if name == "按焊缝 ID 完成数据划分":
        return state["has_built"]
    if name in ("Current、Voltage、GasSpeed 均完整",):
        return all(dims.get(d) for d in ("Current", "Voltage", "GasSpeed"))
    if name in ("Current 与 Voltage 时间轴已对齐",):
        return bool(dims.get("Current") and dims.get("Voltage"))
    if name == "异常区段标签已审核" or name == "标注审核通过率 ≥ 90%" or name == "质量标签完整且无空值":
        return state["annotation_ok"]
    if name == "信号采样率与时间轴一致":
        return bool(dims.get("Current") or dims.get("Voltage"))
    if name == "熔池视频已切分为图像帧":
        return bool(dims.get("熔池视频"))
    if name == "图像与像素级掩膜数量一致":
        return bool(dims.get("焊缝照片"))
    if name == "至少具备两种输入模态":
        return sum(1 for v in dims.values() if v) >= 2
    return False


# ── 版本 ─────────────────────────────────────────────────────────────


def list_versions(session: Session, dataset: Dataset) -> list[dict]:
    return [
        version_payload(v)
        for v in session.exec(
            select(DatasetVersion)
            .where(DatasetVersion.dataset_id == dataset.id)
            .order_by(DatasetVersion.created_at, DatasetVersion.id)
        ).all()
    ]


def create_version(
    session: Session, dataset: Dataset, name: str | None = None, note: str | None = None
) -> DatasetVersion:
    """新建数据集版本（固定快照占位：split 空、item_count 0、无 quality/snapshot）。

    `name`/`note` 仅接受不落库（表结构 §3.15 无对应列）。
    """
    version = DatasetVersion(
        dataset_id=dataset.id,
        version_no=next_dataset_version_no(session, dataset.id),
        split={},
        item_count=0,
        snapshot_id=None,
        quality=None,
        created_at=datetime.now(timezone.utc),
    )
    session.add(version)
    session.flush()
    dataset.updated_at = datetime.now(timezone.utc)
    return version


def next_dataset_version_no(session: Session, dataset_id: int) -> str:
    """`v1.<n>`：现有最大次版本 + 1（空版本集 → v1.1）。"""
    rows = session.exec(
        select(DatasetVersion.version_no).where(DatasetVersion.dataset_id == dataset_id)
    ).all()
    max_minor = 0
    for value in rows:
        try:
            minor = int(str(value).split(".", 1)[1])
        except (IndexError, ValueError):
            continue
        max_minor = max(max_minor, minor)
    return f"v1.{max_minor + 1}"


def version_payload(version: DatasetVersion) -> dict:
    return {
        "id": version.id,
        "dataset_id": version.dataset_id,
        "version_no": version.version_no,
        "split": version.split or {},
        "item_count": version.item_count,
        "snapshot_id": version.snapshot_id,
        "quality": version.quality,
        "created_at": _iso_utc(version.created_at),
    }


def list_version_items(
    session: Session,
    version: DatasetVersion,
    *,
    q: str | None,
    quality: str | None,
    split: str | None,
    page: int,
    page_size: int,
) -> tuple[list[dict], int]:
    """数据集版本成员列表：SQL 侧过滤/计数/分页，按样本粒度返回固定快照成员。"""
    resolved = _version_item_resolved_fields()
    filters = [DatasetItem.dataset_version_id == version.id]
    if split:
        filters.append(DatasetItem.split == split)
    if quality:
        filters.append(resolved["quality"] == quality)
    if q:
        filters.append(
            or_(
                resolved["weld_id"].contains(q),
                resolved["weld_name"].contains(q),
                resolved["registration_no"].contains(q),
            )
        )

    total = int(
        session.exec(
            select(func.count())
            .select_from(DatasetItem)
            .join(Sample, Sample.id == DatasetItem.sample_id)
            .outerjoin(resolved["meta_record"], resolved["meta_record"].id == resolved["meta_record_id"])
            .outerjoin(resolved["meta_weld"], resolved["meta_weld"].weld_id == resolved["meta_weld_id"])
            .outerjoin(SplitTask, SplitTask.id == Sample.split_task_id)
            .outerjoin(resolved["split_version"], resolved["split_version"].id == SplitTask.version_id)
            .outerjoin(resolved["split_record"], resolved["split_record"].id == resolved["split_version"].record_id)
            .outerjoin(AnnotationTask, AnnotationTask.id == Sample.annotation_task_id)
            .outerjoin(resolved["annotation_split"], resolved["annotation_split"].id == AnnotationTask.split_task_id)
            .outerjoin(resolved["annotation_version"], resolved["annotation_version"].id == resolved["annotation_split"].version_id)
            .outerjoin(resolved["annotation_record"], resolved["annotation_record"].id == resolved["annotation_version"].record_id)
            .where(*filters)
        ).one()
    )
    if total == 0:
        return [], 0

    rows = session.exec(
        select(
            DatasetItem.id,
            DatasetItem.sample_id,
            resolved["weld_id"],
            resolved["weld_name"],
            resolved["registration_no"],
            resolved["source"],
            resolved["machine"],
            resolved["modalities"],
            resolved["quality"],
            DatasetItem.split,
            Sample.frame_no,
            resolved["created_at"],
        )
        .join(Sample, Sample.id == DatasetItem.sample_id)
        .outerjoin(resolved["meta_record"], resolved["meta_record"].id == resolved["meta_record_id"])
        .outerjoin(resolved["meta_weld"], resolved["meta_weld"].weld_id == resolved["meta_weld_id"])
        .outerjoin(SplitTask, SplitTask.id == Sample.split_task_id)
        .outerjoin(resolved["split_version"], resolved["split_version"].id == SplitTask.version_id)
        .outerjoin(resolved["split_record"], resolved["split_record"].id == resolved["split_version"].record_id)
        .outerjoin(AnnotationTask, AnnotationTask.id == Sample.annotation_task_id)
        .outerjoin(resolved["annotation_split"], resolved["annotation_split"].id == AnnotationTask.split_task_id)
        .outerjoin(resolved["annotation_version"], resolved["annotation_version"].id == resolved["annotation_split"].version_id)
        .outerjoin(resolved["annotation_record"], resolved["annotation_record"].id == resolved["annotation_version"].record_id)
        .where(*filters)
        .order_by(DatasetItem.sample_id, DatasetItem.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()

    return [
        {
            "id": item_id,
            "sample_id": sample_id,
            "weld_id": weld_id,
            "weld_name": weld_name,
            "registration_no": registration_no,
            "source": source,
            "machine": machine,
            "modalities": list(modalities or []),
            "quality": row_quality,
            "split": row_split,
            "frame_no": frame_no,
            "created_at": _iso_utc(created_at),
        }
        for (
            item_id,
            sample_id,
            weld_id,
            weld_name,
            registration_no,
            source,
            machine,
            modalities,
            row_quality,
            row_split,
            frame_no,
            created_at,
        ) in rows
    ], total


def _version_item_resolved_fields() -> dict[str, object]:
    """构造成员列表的统一解析字段：meta → split_task → annotation_task 三路兜底。"""
    split_version = aliased(DataVersion)
    split_record = aliased(DataRecord)
    annotation_split = aliased(SplitTask)
    annotation_version = aliased(DataVersion)
    annotation_record = aliased(DataRecord)
    meta_record = aliased(DataRecord)
    meta_weld = aliased(DataRecord)
    meta_record_id = cast(Sample.meta["record_id"].as_string(), Integer)
    meta_weld_id = Sample.meta["weld_id"].as_string()
    return {
        "split_version": split_version,
        "split_record": split_record,
        "annotation_split": annotation_split,
        "annotation_version": annotation_version,
        "annotation_record": annotation_record,
        "meta_record": meta_record,
        "meta_weld": meta_weld,
        "meta_record_id": meta_record_id,
        "meta_weld_id": meta_weld_id,
        "weld_id": func.coalesce(
            meta_record.weld_id,
            meta_weld.weld_id,
            split_record.weld_id,
            annotation_record.weld_id,
            meta_weld_id,
        ),
        "weld_name": func.coalesce(
            meta_record.weld_name,
            meta_weld.weld_name,
            split_record.weld_name,
            annotation_record.weld_name,
        ),
        "registration_no": func.coalesce(
            meta_record.registration_no,
            meta_weld.registration_no,
            split_record.registration_no,
            annotation_record.registration_no,
        ),
        "source": func.coalesce(
            meta_record.source,
            meta_weld.source,
            split_record.source,
            annotation_record.source,
        ),
        "machine": func.coalesce(
            meta_record.machine,
            meta_weld.machine,
            split_record.machine,
            annotation_record.machine,
        ),
        "modalities": func.coalesce(
            meta_record.modalities,
            meta_weld.modalities,
            split_record.modalities,
            annotation_record.modalities,
        ),
        "quality": func.coalesce(
            meta_record.quality,
            meta_weld.quality,
            split_record.quality,
            annotation_record.quality,
        ),
        "created_at": func.coalesce(
            meta_record.created_at,
            meta_weld.created_at,
            split_record.created_at,
            annotation_record.created_at,
        ),
    }


# ── 构建任务（异步 handler 领域逻辑） ───────────────────────────────


def run_build(session: Session, build_task: DatasetBuildTask, job: Job) -> dict:
    """执行一次数据集构建，返回写入 `job.result` 的 dict。**不 commit 终态**（执行器提交）。

    步骤：
    1. 进度逐步 0→100（逐次 commit + 小睡，轮询可见）；
    2. 按来源 gather 候选样本（annotation_task/split_task/manual/filter）；空 → 兜底合成；
    3. 按 record_id 分组 → 稳定 seed 打乱 → 8:1:1 划分（同焊缝不跨 split）；
    4. 落 `dataset_items`（固定清单）→ 计算 `quality` → 快照写 MinIO →
       回填 `dataset_versions.split/item_count/quality/snapshot_id`；
    5. 更新 `datasets.current_version_id/sample_count/status(可训练)`；
    6. `mark_succeeded(job, {item_count, split, quality, snapshot_id})`。
    """
    for progress in _PROGRESS_STEPS:
        job.progress = progress
        session.commit()
        time.sleep(_PROGRESS_SLEEP)

    version = session.get(DatasetVersion, build_task.dataset_version_id)
    if version is None:
        raise ValueError(f"数据集版本不存在: id={build_task.dataset_version_id}")
    dataset = session.get(Dataset, version.dataset_id)
    if dataset is None:
        raise ValueError(f"数据集不存在: id={version.dataset_id}")

    source = _build_source(build_task, job)
    samples = _gather_samples(session, source, dataset)
    if not samples:
        samples = _fallback_samples(session)

    # 按焊缝（record_id）分组，避免同焊缝样本跨分片泄漏。
    record_ids: dict[int, int | None] = {}
    for s in samples:
        record_ids[s.id] = _sample_record_id(session, s)
    groups: dict[object, list[Sample]] = defaultdict(list)
    for s in samples:
        groups[record_ids.get(s.id) if record_ids.get(s.id) is not None else ("orphan", s.id)].append(s)
    assignments = _assign_splits(list(groups.keys()))

    # 清掉该版本旧清单（防重复构建）后落新清单。
    for old in session.exec(
        select(DatasetItem).where(DatasetItem.dataset_version_id == version.id)
    ).all():
        session.delete(old)
    item_rows: list[DatasetItem] = []
    for key in groups:
        split = assignments[key]
        for s in groups[key]:
            item_rows.append(
                DatasetItem(dataset_version_id=version.id, sample_id=s.id, split=split)
            )
    for row in item_rows:
        session.add(row)
    session.flush()

    split_counts = {"train": 0, "val": 0, "test": 0}
    for row in item_rows:
        split_counts[row.split] += 1

    quality = _compute_quality(session, dataset, samples, record_ids)
    split_of_sample = {row.sample_id: row.split for row in item_rows}
    snapshot_id, snapshot = _build_snapshot(
        session, dataset, version, samples, record_ids, split_counts, quality, split_of_sample
    )

    version.split = split_counts
    version.item_count = len(item_rows)
    version.quality = quality
    version.snapshot_id = snapshot_id
    session.add(version)

    dataset.current_version_id = version.id
    dataset.sample_count = len(item_rows)
    dataset.status = "可训练" if len(item_rows) > 0 else "标注中"
    dataset.progress = Decimal(str(round((1 - quality["empty_label_rate"]) * 100, 2)))
    dataset.updated_at = datetime.now(timezone.utc)
    session.add(dataset)

    result = {
        "item_count": len(item_rows),
        "split": split_counts,
        "quality": quality,
        "snapshot_id": snapshot_id,
    }
    mark_succeeded(session, job, result)
    return result


def _build_source(build_task: DatasetBuildTask, job: Job) -> object:
    """构建来源：优先取创建时随 Job.result 携带的完整 DatasetSource，缺省用 build_task.source。"""
    initial = job.result if isinstance(job.result, dict) else {}
    source = initial.get("source") or build_task.source
    return source


def _gather_samples(
    session: Session, source: object, dataset: Dataset
) -> list[Sample]:
    """按来源类型 gather 候选样本。来源为空/解析不到 → 返回 []（触发兜底合成）。"""
    if isinstance(source, dict):
        stype = str(source.get("type") or "")
        atid = source.get("annotation_task_id")
        stid = source.get("split_task_id")
        sample_ids = source.get("sample_ids")
        filters = source.get("filters")
    else:
        stype = str(source or "")
        atid = stid = sample_ids = filters = None

    if stype == "annotation_task" and atid:
        task = resolve_annotation_task(session, str(atid))
        if task is not None:
            return list(
                session.exec(select(Sample).where(Sample.annotation_task_id == task.id)).all()
            )
    if stype == "split_task" and stid:
        split = resolve_split_task(session, str(stid))
        if split is not None:
            return list(
                session.exec(select(Sample).where(Sample.split_task_id == split.id)).all()
            )
    if stype == "manual" and sample_ids:
        ids = [int(s) for s in sample_ids if str(s).lstrip("-").isdigit()]
        if ids:
            return list(session.exec(select(Sample).where(Sample.id.in_(ids))).all())
    if stype == "filter":
        return _filter_samples(session, filters or {})
    return []


def _filter_samples(session: Session, filters: dict) -> list[Sample]:
    """按登记字段筛选样本（samples→所属焊缝 record 属性，前缀匹配 source）。"""
    out: list[Sample] = []
    for sample in session.exec(select(Sample)).all():
        record = _sample_record(session, sample)
        if record is not None and _record_matches(record, filters):
            out.append(sample)
    return out


def _record_matches(record: DataRecord, filters: dict) -> bool:
    for key, value in (filters or {}).items():
        if key == "record_id":
            if record.id != int(value):
                return False
        elif key == "weld_id":
            if record.weld_id != str(value):
                return False
        elif key == "source":
            if not str(record.source or "").startswith(str(value)):
                return False
        elif key in ("quality", "weld_method", "machine", "material", "product", "weld_name", "registration_no"):
            if getattr(record, key, None) != value:
                return False
        else:
            return False  # 未知筛选键：严格不匹配
    return True


def _fallback_samples(session: Session) -> list[Sample]:
    """确定性兜底样本集：覆盖全部登记焊缝的合成样本，保证按焊缝划分的 demo 非空。

    - 已有覆盖 ≥2 条焊缝的演示样本 → 直接用（seed 演示场景，非空且不新增样本）；
    - 否则逐登记焊缝生成 `_SYNTH_PER_RECORD` 个合成 `Sample`（对象键按焊缝 modalities 推导）。
    """
    existing = list(session.exec(select(Sample)).all())
    record_ids = {_sample_record_id(session, s) for s in existing}
    record_ids.discard(None)
    if len(record_ids) >= 2:
        return existing

    records = session.exec(select(DataRecord).order_by(DataRecord.id)).all()
    samples: list[Sample] = []
    for i, record in enumerate(records):
        for j in range(_SYNTH_PER_RECORD):
            idx = i * _SYNTH_PER_RECORD + j
            sample = Sample(
                frame_no=j,
                object_keys=_synthetic_keys(record, idx),
                meta={
                    "weld_id": record.weld_id,
                    "record_id": record.id,
                    "synthetic": True,
                },
            )
            session.add(sample)
            session.flush()
            samples.append(sample)
    return samples


def _synthetic_keys(record: DataRecord, idx: int) -> list[str]:
    """按登记 modalities 推导合成样本对象键（决定维度可用性）。"""
    weld_id = record.weld_id
    mods = record.modalities or []
    keys: list[str] = []
    if "video" in mods:
        keys.append(f"processed/{weld_id}/split/synthetic_{idx}.mp4")
    if "timeseries" in mods:
        keys.append(f"processed/{weld_id}/split/synthetic_{idx}.csv")
    if "audio" in mods:
        keys.append(f"processed/{weld_id}/split/synthetic_{idx}.wav")
    if "infrared" in mods:
        keys.append(f"processed/{weld_id}/split/synthetic_{idx}_infrared.png")
    if not keys:
        keys.append(f"processed/{weld_id}/split/synthetic_{idx}.json")
    return keys


def _assign_splits(group_keys: list) -> dict[object, str]:
    """按焊缝分组稳定划分 8:1:1。组数 <3 时退化为 train / train+test（不泄漏）。

    seed=42 → 确定性可复现。同焊缝（一个组）整体进一个分片，绝不拆开。
    """
    keys = list(group_keys)
    random.Random(42).shuffle(keys)
    n = len(keys)
    assignments: dict[object, str] = {}
    if n == 1:
        assignments[keys[0]] = "train"
    elif n == 2:
        assignments[keys[0]] = "train"
        assignments[keys[1]] = "test"
    else:
        test_count = max(1, round(n * 0.1))
        val_count = max(1, round(n * 0.1))
        for i, key in enumerate(keys):
            if i >= n - test_count:
                assignments[key] = "test"
            elif i >= n - test_count - val_count:
                assignments[key] = "val"
            else:
                assignments[key] = "train"
    return assignments


def _compute_quality(
    session: Session,
    dataset: Dataset,
    samples: list[Sample],
    record_ids: dict[int, int | None],
) -> dict:
    """数据集质量：`{repeat_rate, empty_label_rate, dimension_missing_rate}`。

    - repeat_rate：同 (record_id, frame_no) 重复出现占比（合成/切分样本均唯一 → 0）；
    - empty_label_rate：无标注样本占比；
    - dimension_missing_rate：任务必需维度缺失占比。
    """
    total = len(samples)
    seen: dict[tuple, int] = defaultdict(int)
    for s in samples:
        seen[(record_ids.get(s.id), s.frame_no)] += 1
    repeated = total - len(seen)
    repeat_rate = round(repeated / total, 4) if total else 0.0

    annotated: set[int] = set()
    if samples:
        for sample_id in session.exec(
            select(Annotation.sample_id).where(
                Annotation.sample_id.in_([s.id for s in samples])
            )
        ).all():
            annotated.add(sample_id)
    empty = total - len(annotated)
    empty_label_rate = round(empty / total, 4) if total else 0.0

    required = REQUIRED_BY_TASK.get(dataset.task, [])
    dims = _dimension_availability_from_samples(samples)
    missing = sum(1 for d in required if not dims.get(d))
    dimension_missing_rate = round(missing / len(required), 4) if required else 0.0

    return {
        "repeat_rate": repeat_rate,
        "empty_label_rate": empty_label_rate,
        "dimension_missing_rate": dimension_missing_rate,
    }


def _build_snapshot(
    session: Session,
    dataset: Dataset,
    version: DatasetVersion,
    samples: list[Sample],
    record_ids: dict[int, int | None],
    split_counts: dict[str, int],
    quality: dict,
    split_of_sample: dict[int, str],
) -> tuple[str, dict]:
    """快照 JSON 写 MinIO `datasets/{version.id}/snapshot.json`，返回 (snapshot_id, snapshot)。

    写 MinIO **尽力而为**：失败仅告警（本地 DB 为权威），不使构建失败。
    """
    from app.storage import get_storage  # 延迟导入，避免 services 层启动依赖存储

    items = [
        {
            "sample_id": s.id,
            "record_id": record_ids.get(s.id),
            "split": split_of_sample.get(s.id),
            "object_keys": s.object_keys or [],
        }
        for s in samples
    ]
    snapshot = {
        "dataset_id": dataset.id,
        "dataset_no": dataset.dataset_no,
        "dataset_version_id": version.id,
        "version_no": version.version_no,
        "task": dataset.task,
        "item_count": len(samples),
        "split": split_counts,
        "quality": quality,
        "items": items,
    }
    snapshot_id = f"datasets/{version.id}/snapshot.json"
    try:
        data = json.dumps(snapshot, ensure_ascii=False, default=str).encode("utf-8")
        get_storage().upload_stream(
            snapshot_id, io.BytesIO(data), len(data), "application/json"
        )
    except Exception:  # noqa: BLE001 - 存储不可达不阻断构建（demo 容错）
        logger.opt(exception=True).warning(
            "数据集快照写 MinIO 失败（跳过）: {}", snapshot_id
        )
    return snapshot_id, snapshot


# ── 血缘 ─────────────────────────────────────────────────────────────


def get_lineage(session: Session, dataset: Dataset) -> list[dict]:
    """数据血缘：原始焊缝 → 标注任务 → 数据集版本 → 模型训练（4 层）。

    沿当前版本 `dataset_items→samples` 反查 annotation_tasks/split_tasks/data_records，
    另查 `training_tasks→dataset_versions` 引用。
    """
    versions = session.exec(
        select(DatasetVersion)
        .where(DatasetVersion.dataset_id == dataset.id)
        .order_by(DatasetVersion.created_at, DatasetVersion.id)
    ).all()
    version_ids = [v.id for v in versions]
    current_version = (
        session.get(DatasetVersion, dataset.current_version_id)
        if dataset.current_version_id is not None
        else None
    )

    sample_ids: list[int] = []
    if current_version is not None:
        items = session.exec(
            select(DatasetItem).where(
                DatasetItem.dataset_version_id == current_version.id
            )
        ).all()
        sample_ids = [it.sample_id for it in items]

    record_ids: set[int] = set()
    annotation_task_ids: set[int] = set()
    if sample_ids:
        for sample in session.exec(
            select(Sample).where(Sample.id.in_(sample_ids))
        ).all():
            rid = _sample_record_id(session, sample)
            if rid is not None:
                record_ids.add(rid)
            if sample.annotation_task_id is not None:
                annotation_task_ids.add(sample.annotation_task_id)

    records = []
    if record_ids:
        records = session.exec(
            select(DataRecord).where(DataRecord.id.in_(record_ids)).order_by(DataRecord.id)
        ).all()
    annotation_tasks = []
    if annotation_task_ids:
        annotation_tasks = session.exec(
            select(AnnotationTask)
            .where(AnnotationTask.id.in_(annotation_task_ids))
            .order_by(AnnotationTask.id)
        ).all()
    training_tasks = []
    if version_ids:
        training_tasks = session.exec(
            select(TrainingTask)
            .where(TrainingTask.dataset_version_id.in_(version_ids))
            .order_by(TrainingTask.id)
        ).all()

    return [
        {
            "type": "records",
            "label": "原始焊缝数据",
            "count": len(records),
            "items": [r.weld_id for r in records],
        },
        {
            "type": "annotation_tasks",
            "label": "标注任务",
            "count": len(annotation_tasks),
            "items": [
                {"id": t.id, "name": t.name, "source": t.source} for t in annotation_tasks
            ],
        },
        {
            "type": "dataset_versions",
            "label": "数据集版本",
            "count": len(versions),
            "items": [v.version_no for v in versions],
        },
        {
            "type": "training_tasks",
            "label": "模型训练",
            "count": len(training_tasks),
            "items": [
                {"id": t.id, "dataset_version_id": t.dataset_version_id}
                for t in training_tasks
            ],
        },
    ]


# ── 内部：样本 → 所属焊缝（record_id） ──────────────────────────────


def _sample_record(session: Session, sample: Sample) -> DataRecord | None:
    """样本 → 所属焊缝记录。优先 meta，其次 split_task/annotation_task→version→record。"""
    rid = _sample_record_id(session, sample)
    if rid is None:
        return None
    return session.get(DataRecord, rid)


def _sample_record_id(session: Session, sample: Sample) -> int | None:
    """样本 → 所属焊缝 record_id（按焊缝分组划分的依据）。"""
    meta = sample.meta or {}
    rid = meta.get("record_id")
    if rid is not None:
        try:
            return int(rid)
        except (TypeError, ValueError):
            pass
    wid = meta.get("weld_id")
    if wid:
        record = session.exec(
            select(DataRecord).where(DataRecord.weld_id == str(wid))
        ).first()
        if record is not None:
            return record.id
    if sample.split_task_id is not None:
        split = session.get(SplitTask, sample.split_task_id)
        if split is not None:
            version = session.get(DataVersion, split.version_id)
            if version is not None:
                return version.record_id
    if sample.annotation_task_id is not None:
        task = session.get(AnnotationTask, sample.annotation_task_id)
        if task is not None and task.split_task_id is not None:
            split = session.get(SplitTask, task.split_task_id)
            if split is not None:
                version = session.get(DataVersion, split.version_id)
                if version is not None:
                    return version.record_id
    return None
