"""模型中心服务（Task 16）：模型 CRUD / 状态流转 / 训练 / 测试 / 推理。

契约 `docs/API接口清单.md` §3.6；业务规则 `docs/数据库设计.md` §3.17–§3.21 与 §5
（训练成功自动生成 `model_versions` + 权重写 MinIO `models/{id}/weights.pt`）。
实施边界 §3.1：训练/测试/推理 = 真实异步编排 + 模拟结果——Job 状态/进度/结果回填、
`model_versions` 落库、权重写 MinIO 均为真，计算内核为演示（指标收敛/损失曲线/
混淆矩阵/预测框为确定性模拟）。

关键设计（坑，改动勿破坏）：
- 训练任务可选 `base_model_id`（→ 新版本挂到该基础版本所属模型）；缺省时自动新建
  一个 `Model`（name=`训练模型-{task.id}`，type=时序分类），保证训练一定有落点。
- 新版本状态恒为 `实验版本`（契约 §3.18），由 `PATCH /models/{id}/versions/{vid}`
  手动流转为生产候选等（状态白名单 生产候选/训练中/实验版本）。
- `model_versions` 表无 `note` 列（文档 §3.18 即无）：PATCH 的 `note` 仅接受不落库，
  与 `dataset_versions.name/note` 同款约定。
- 权重写 MinIO **尽力而为**：失败仅告警（本地 DB 为权威），不使训练失败。
- 指标/损失曲线/预测框一律用 `random.Random(f"train-{task.id}")` 确定性种子，
  同一任务可复现、跨任务有差异。
"""

from __future__ import annotations

import io
import random
import time
from datetime import datetime, timezone

from loguru import logger
from sqlalchemy import func
from sqlmodel import Session, select

from app.models.datasets import DatasetVersion
from app.models.jobs import Job
from app.models.models import (
    InferenceTask,
    Model,
    ModelVersion,
    TestTask,
    TrainingTask,
)
from app.services.jobs import _iso_utc, mark_succeeded

#: 进度逐步递增点（与 split/annotation/dataset_build handler 一致）。
_PROGRESS_STEPS: tuple[int, ...] = (20, 40, 60, 80, 100)
_PROGRESS_SLEEP: float = 0.005

#: 模型版本状态白名单（契约 §3.18 / §3.6 PATCH）。
MODEL_VERSION_STATUSES: tuple[str, ...] = ("生产候选", "训练中", "实验版本")

#: 模拟 GPU 资源占用（前端 ModelRepository 汇总卡，常量演示值）。
GPU_USAGE = 42

#: 权重占位 blob（MinIO `models/{id}/weights.pt`，演示不承载真实模型权重）。
_WEIGHTS_BLOB = b"mock-yolo-weights-placeholder-blob-v1"

_IMAGE_TYPES = {"jpeg", "png", "webp", "bmp"}
_VIDEO_EXTS = {".mp4", ".mov", ".m4v"}
_MODEL_REQUIRED_DIMS = {
    "时序分类": {"Current", "Voltage"},
    "语义分割": {"熔池视频"},
    "多模态回归": {"Current", "Voltage"},
}


# ── 模型 CRUD ────────────────────────────────────────────────────────


def create_model(
    session: Session, name: str, type_: str, description: str | None = None
) -> Model:
    """新建模型仓库条目。同名 → 抛 `ValueError`（路由转 409）。"""
    if session.exec(select(Model).where(Model.name == name)).first() is not None:
        raise ValueError("模型名称已存在")
    model = Model(name=name, type=type_, description=description)
    session.add(model)
    session.flush()
    return model


def list_models(session: Session) -> dict:
    """模型仓库列表 + 汇总：`{summary, models[]}`。

    - summary：`{total, prod_candidates, recent_training, gpu_usage}`（均来自
      `model_versions`/`jobs`；gpu_usage 为常量演示值 42）。
    - models[]：每个模型含其最新版本（按 id 倒序取首条，id 单调=创建顺序）+ 核心指标。
    单条查询取全部版本，避免逐模型 N+1。
    """
    models = session.exec(select(Model).order_by(Model.id)).all()
    latest: dict[int, ModelVersion] = {}
    for v in session.exec(select(ModelVersion).order_by(ModelVersion.id.desc())).all():
        if v.model_id not in latest:
            latest[v.model_id] = v

    prod_candidates = int(
        session.exec(
            select(func.count(ModelVersion.id)).where(
                ModelVersion.status == "生产候选"
            )
        ).one()
    )
    summary = {
        "total": len(models),
        "prod_candidates": prod_candidates,
        "recent_training": _recent_training(session),
        "gpu_usage": GPU_USAGE,
    }
    items = [model_payload(m, latest.get(m.id)) for m in models]
    return {"summary": summary, "models": items}


def get_model(session: Session, model_id: int) -> dict | None:
    """模型详情：模型字段 + 全部版本列表。不存在返回 None。"""
    model = session.get(Model, model_id)
    if model is None:
        return None
    versions = session.exec(
        select(ModelVersion)
        .where(ModelVersion.model_id == model.id)
        .order_by(ModelVersion.id)
    ).all()
    latest = versions[-1] if versions else None
    payload = model_payload(model, latest)
    payload["versions"] = [version_payload(v) for v in versions]
    return payload


def model_payload(model: Model, latest: ModelVersion | None = None) -> dict:
    """模型 → JSON。`latest` 提供时并入最新版本号/指标/状态/权重键。"""
    payload = {
        "id": model.id,
        "name": model.name,
        "type": model.type,
        "description": model.description,
    }
    if latest is not None:
        payload.update(
            {
                "version": latest.version_no,
                "metric": latest.metric,
                "status": latest.status,
                "file_key": latest.file_key,
                "latest_version_id": latest.id,
            }
        )
    return payload


def version_payload(version: ModelVersion) -> dict:
    """模型版本 → JSON（列表/详情/流转共用）。"""
    return {
        "id": version.id,
        "model_id": version.model_id,
        "version_no": version.version_no,
        "metric": version.metric,
        "status": version.status,
        "file_key": version.file_key,
        "created_at": _iso_utc(version.created_at),
    }


# ── 状态流转 ─────────────────────────────────────────────────────────


def update_version_status(
    session: Session,
    model: Model,
    version: ModelVersion,
    status: str | None = None,
    note: str | None = None,
) -> ModelVersion:
    """更新模型版本状态/备注（PATCH）。status 白名单校验，非法抛 `ValueError`。

    `note` 无对应列（文档 §3.18 即无），仅接受不落库（同 dataset_versions.name/note）。
    """
    if status is not None and status not in MODEL_VERSION_STATUSES:
        raise ValueError(f"status 需为 {'/'.join(MODEL_VERSION_STATUSES)}")
    if status is not None:
        version.status = status
    session.add(version)
    return version


# ── 训练任务（异步 handler 领域逻辑） ──────────────────────────────


def run_training(session: Session, task: TrainingTask, job: Job) -> dict:
    """执行一次模拟训练，返回写入 `job.result` 的 dict。**不 commit 终态**（执行器提交）。

    步骤：
    1. 进度逐步 0→100（逐次 commit + 小睡，轮询可见）；
    2. 确定性指标收敛（mAP50≈0.94-0.96 / precision≈0.96 / recall≈0.93，seed=task.id）
       + 损失曲线（train/val 数组，长度=epochs，训练损失递减、验证略高于训练）；
    3. 同事务：生成 `model_versions`（version_no next、status=实验版本、metric、
       file_key=`models/{id}/weights.pt`）→ 权重占位写 MinIO（尽力而为）；
       `base_model_id` 给定时新版本挂到基础版本所属模型，否则自动新建 Model；
    4. 回填 `training_tasks.metrics/loss_curve`；
    5. `mark_succeeded(job, {metrics, loss_curve, model_version})`。
    """
    for progress in _PROGRESS_STEPS:
        job.progress = progress
        session.commit()
        time.sleep(_PROGRESS_SLEEP)

    hyperparams = task.hyperparams or {}
    epochs = max(1, int(hyperparams.get("epochs") or 50))
    rng = random.Random(f"train-{task.id}")
    metrics = {
        "mAP50": round(rng.uniform(0.940, 0.960), 3),
        "precision": round(rng.uniform(0.950, 0.970), 3),
        "recall": round(rng.uniform(0.920, 0.940), 3),
    }
    loss_curve = _loss_curve(epochs, rng)

    model_id = _target_model_id(session, task)
    now = datetime.now(timezone.utc)
    version = ModelVersion(
        model_id=model_id,
        version_no=next_model_version_no(session, model_id),
        metric=metrics,
        status="实验版本",
        created_at=now,
    )
    session.add(version)
    session.flush()
    version.file_key = f"models/{version.id}/weights.pt"
    session.add(version)
    _write_weights(version.file_key)

    task.metrics = metrics
    task.loss_curve = loss_curve
    session.add(task)

    result = {
        "metrics": metrics,
        "loss_curve": loss_curve,
        "model_version": version_payload(version),
        "progress": 100,
    }
    mark_succeeded(session, job, result)
    return result


def active_training_job_uid(session: Session, dataset_version_id: int) -> str | None:
    row = session.exec(
        select(TrainingTask, Job)
        .join(Job, Job.id == TrainingTask.job_id)
        .where(TrainingTask.dataset_version_id == dataset_version_id)
        .order_by(TrainingTask.id.desc())
    ).first()
    if row is None:
        return None
    task, job = row
    return job.job_uid if job.status in {"pending", "running"} else None


def active_inference_job_uid(
    session: Session,
    *,
    model_version_id: int,
    input_key: str,
    input_type: str,
) -> str | None:
    rows = session.exec(
        select(InferenceTask, Job)
        .join(Job, Job.id == InferenceTask.job_id)
        .where(
            InferenceTask.model_version_id == model_version_id,
            InferenceTask.input_key == input_key,
            InferenceTask.input_type == input_type,
        )
        .order_by(InferenceTask.id.desc())
    ).all()
    for _task, job in rows:
        if job.status in {"pending", "running", "succeeded"}:
            return job.job_uid
    return None


def training_logs(task: TrainingTask, job: Job) -> str:
    """训练日志文本（`GET /training-tasks/{task_id}/logs`）。确定性，从任务域字段生成。"""
    hyperparams = task.hyperparams or {}
    epochs = max(1, int(hyperparams.get("epochs") or 50))
    lines = [
        f"[INFO] 训练任务 {job.job_uid} 初始化",
        f"[INFO] epochs={epochs}, batch_size={hyperparams.get('batch_size', 16)}, "
        f"learning_rate={hyperparams.get('learning_rate', 0.001)}, "
        f"val_ratio={hyperparams.get('val_ratio', 0.2)}",
    ]
    curve = task.loss_curve or {}
    train = curve.get("train", [])
    val = curve.get("val", [])
    if task.metrics is not None and train:
        for i in range(min(len(train), len(val), epochs)):
            lines.append(
                f"[INFO] Epoch {i + 1}/{epochs} loss={train[i]:.4f} "
                f"val_loss={val[i]:.4f}"
            )
        m = task.metrics
        lines.append(
            f"[INFO] 训练完成 mAP50={m.get('mAP50')} "
            f"precision={m.get('precision')} recall={m.get('recall')}"
        )
        lines.append("[INFO] 模型已保存至模型仓库（实验版本）")
    else:
        lines.append("[INFO] 等待后台执行器执行...")
    return "\n".join(lines)


# ── 测试任务（异步 handler 领域逻辑） ──────────────────────────────


def run_test(session: Session, task: TestTask, job: Job) -> dict:
    """模拟测试：进度 → metrics + 2×2 混淆矩阵（照 App.tsx ModelTest 数值）。"""
    for progress in _PROGRESS_STEPS:
        job.progress = progress
        session.commit()
        time.sleep(_PROGRESS_SLEEP)

    metrics = {"accuracy": 0.968, "recall": 0.942, "f1": 0.955, "latency_ms": 18}
    confusion_matrix = [[612, 18], [22, 596]]
    task.metrics = metrics
    task.confusion_matrix = confusion_matrix
    session.add(task)

    result = {"metrics": metrics, "confusion_matrix": confusion_matrix}
    mark_succeeded(session, job, result)
    return result


# ── 推理任务（异步 handler 领域逻辑） ──────────────────────────────


def run_inference(session: Session, task: InferenceTask, job: Job) -> dict:
    """模拟推理：进度 → 预测框/类别/置信度/耗时（seed=task.id，确定性）。"""
    for progress in _PROGRESS_STEPS:
        job.progress = progress
        session.commit()
        time.sleep(_PROGRESS_SLEEP)

    rng = random.Random(f"infer-{task.id}")
    labels = ("焊瘤", "气孔", "未熔合")
    boxes: list[list[int]] = []
    categories: list[str] = []
    confidence: list[float] = []
    for i in range(3):
        boxes.append(
            [
                rng.randint(40, 300),
                rng.randint(40, 200),
                rng.randint(30, 120),
                rng.randint(30, 120),
            ]
        )
        categories.append(labels[i % len(labels)])
        confidence.append(round(rng.uniform(0.80, 0.98), 3))
    result = {
        "boxes": boxes,
        "categories": categories,
        "confidence": confidence,
        "latency_ms": rng.randint(12, 25),
    }
    task.result = result
    session.add(task)

    mark_succeeded(session, job, result)
    return result


# ── 内部助手 ─────────────────────────────────────────────────────────


def next_model_version_no(session: Session, model_id: int) -> str:
    """下一版本号：取该模型现有最大 (major, minor) → `v{major}.{minor+1}`；空 → v1.1。"""
    best_major, best_minor = 1, 0
    for value in session.exec(
        select(ModelVersion.version_no).where(ModelVersion.model_id == model_id)
    ).all():
        parsed = _parse_version_no(str(value))
        if parsed is not None and parsed > (best_major, best_minor):
            best_major, best_minor = parsed
    return f"v{best_major}.{best_minor + 1}"


def _parse_version_no(value: str) -> tuple[int, int] | None:
    """解析 `v{major}.{minor}` → (major, minor)；格式不符返回 None。"""
    try:
        major, minor = value.lstrip("vV").split(".", 1)
        return int(major), int(minor)
    except (ValueError, IndexError):
        return None


def _target_model_id(session: Session, task: TrainingTask) -> int:
    """训练产出版本的归属模型：`base_model_id` 给定时挂到其所属模型，否则自动新建 Model。"""
    if task.base_model_id is not None:
        base = session.get(ModelVersion, task.base_model_id)
        if base is not None:
            return base.model_id
    model = Model(
        name=f"训练模型-{task.id or 'auto'}",
        type="时序分类",
        description="训练任务自动创建",
    )
    session.add(model)
    session.flush()
    return model.id


def _loss_curve(epochs: int, rng: random.Random) -> dict:
    """训练/验证损失曲线（长度=epochs）：训练损失递减收敛，验证略高于训练。"""
    train: list[float] = []
    val: list[float] = []
    for i in range(1, epochs + 1):
        progress = i / epochs
        base = 1.2 * (1 - progress) ** 1.5 + 0.12
        train.append(round(base + rng.uniform(-0.03, 0.03), 4))
        val.append(round(base + 0.15 * (1 - progress) ** 0.8 + rng.uniform(-0.02, 0.02), 4))
    return {"train": train, "val": val}


def model_compatible_with_dataset(
    model_type: str,
    dims: dict[str, bool],
    dataset_task: str | None = None,
) -> bool:
    required = _MODEL_REQUIRED_DIMS.get(model_type)
    if required is None:
        return True
    if any(dims.values()):
        return all(dims.get(name, False) for name in required)
    if model_type == "语义分割":
        return dataset_task == "语义分割"
    if model_type == "多模态回归":
        return dataset_task == "多模态回归"
    if model_type == "时序分类":
        return dataset_task != "语义分割"
    return True


def validate_inference_input(input_key: str, input_type: str) -> None:
    from app.storage import get_storage  # 延迟导入，避免启动时触网

    if input_type not in {"image", "video"}:
        raise ValueError("input_type 需为 image 或 video")
    storage = get_storage()
    size = storage.stat_object(input_key)
    if size > 100 * 1024 * 1024:
        raise ValueError("推理输入文件过大：需 ≤ 100MB")
    data = storage.get_object(input_key)
    lower = input_key.lower()
    if input_type == "image":
        kind = _detect_image_type(data)
        if kind is None:
            raise ValueError("推理输入不是有效图片")
        if kind not in _IMAGE_TYPES:
            raise ValueError(f"不支持的图片格式: {kind}")
        if not lower.endswith(tuple(f".{ext}" for ext in (["jpg", "jpeg", "png", "webp", "bmp"]))):
            raise ValueError("推理输入文件扩展名与图片类型不匹配")
        if kind == "jpeg" and not lower.endswith((".jpg", ".jpeg")):
            raise ValueError("推理输入文件扩展名与图片类型不匹配")
    else:
        if not lower.endswith(tuple(_VIDEO_EXTS)):
            raise ValueError("不支持的视频格式")
        if len(data) < 12 or data[4:8] != b"ftyp":
            raise ValueError("推理输入不是有效视频")


def _detect_image_type(data: bytes) -> str | None:
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"RIFF") and len(data) >= 12 and data[8:12] == b"WEBP":
        return "webp"
    if data.startswith(b"BM"):
        return "bmp"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    return None


def _recent_training(session: Session) -> str | None:
    """最近一次已完成的训练任务 finished_at（ISO-8601 UTC）；无 → None。"""
    job = session.exec(
        select(Job)
        .where(Job.type == "training", Job.finished_at.is_not(None))
        .order_by(Job.finished_at.desc(), Job.id.desc())
    ).first()
    return _iso_utc(job.finished_at) if job is not None else None


def _write_weights(file_key: str) -> None:
    """权重占位写 MinIO `models/{id}/weights.pt`。**尽力而为**：失败仅告警。"""
    from app.storage import get_storage  # 延迟导入，避免 services 层启动依赖存储

    try:
        get_storage().upload_stream(
            file_key,
            io.BytesIO(_WEIGHTS_BLOB),
            len(_WEIGHTS_BLOB),
            "application/octet-stream",
        )
    except Exception:  # noqa: BLE001 - 存储不可达不阻断训练（demo 容错）
        logger.opt(exception=True).warning("模型权重写 MinIO 失败（跳过）: {}", file_key)
