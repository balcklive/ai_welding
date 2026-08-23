"""models 域路由（Task 16）：模型仓库 / 训练 / 测试 / 推理。

端点契约 `docs/API接口清单.md` §3.6；全部需登录（router 级 `Depends(get_current_user)`），
返回统一 `ok(...)` / `err(...)` 信封；领域逻辑在 `app.services.models`。

训练/测试/推理走异步 Job（实施边界 §3.1：真实异步编排 + 模拟结果）：
- `POST /training-tasks` → 同事务建 pending Job(type=training) + `training_tasks` 行 →
  `{job_id}`；成功后 handler 自动生成 `model_versions`（status=实验版本）+ 权重写
  MinIO `models/{id}/weights.pt`。
- `POST /test-tasks` / `POST /inference-tasks` 同理（type=test / inference）。
状态经通用 `GET /jobs/{job_id}` 或各域 `GET /…-tasks/{task_id}` 轮询（同一套 Job 信封）。

错误码：40401=模型/任务/数据集版本/模型版本不存在、40402=版本不属于该模型、
40900=模型名称冲突、40000=参数错误。
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlmodel import Session, select

from app.api.deps import get_current_user
from app.core.audit import write_audit
from app.core.db import get_session
from app.models.data import User
from app.models.datasets import DatasetVersion
from app.models.jobs import Job
from app.models.models import (
    InferenceTask,
    Model,
    ModelVersion,
    TestTask,
    TrainingTask,
)
from app.schemas.common import err, ok
from app.services import models as svc
from app.services.jobs import create_job, get_job_by_uid, to_job_payload

router = APIRouter(dependencies=[Depends(get_current_user)])


class ModelCreate(BaseModel):
    """POST /models 请求体（契约 §3.6）：新建模型仓库条目。"""

    name: str
    type: str
    description: str | None = None


class ModelVersionUpdate(BaseModel):
    """PATCH /models/{id}/versions/{vid} 请求体（契约 §3.6）：状态/备注（note 不落库）。"""

    status: str | None = None
    note: str | None = None


class TrainingTaskCreate(BaseModel):
    """POST /training-tasks 请求体（契约 §3.6）。`base_model_id` 可选；`extra=allow`
    接收高级参数（epochs/batch_size/learning_rate/val_ratio 之外的任意键进 hyperparams）。"""

    dataset_version_id: int
    base_model_id: int | None = None
    epochs: int | None = None
    batch_size: int | None = None
    learning_rate: float | None = None
    val_ratio: float | None = None
    model_config = ConfigDict(extra="allow")


class TestTaskCreate(BaseModel):
    """POST /test-tasks 请求体（契约 §3.6）：模型版本 + 独立测试集 + 评估任务列表。"""

    model_version_id: int
    dataset_version_id: int
    tasks: list[str] = []


class InferenceTaskCreate(BaseModel):
    """POST /inference-tasks 请求体（契约 §3.6）：模型版本 + 输入样本 + 输入类型。"""

    model_version_id: int
    input: str
    input_type: str


# ── 模型仓库 ─────────────────────────────────────────────────────────


@router.get("/models")
def list_models(session: Session = Depends(get_session)) -> dict:
    """模型仓库列表 + 汇总（总数/生产候选/最近训练/GPU 资源），含各模型最新版本。"""
    return ok(svc.list_models(session))


@router.get("/models/{model_id}")
def get_model(model_id: int, session: Session = Depends(get_session)) -> dict:
    """模型详情：模型字段 + 全部版本列表。"""
    payload = svc.get_model(session, model_id)
    if payload is None:
        return err(40401, "模型不存在", status=404)
    return ok(payload)


@router.post("/models")
def create_model(
    body: ModelCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """新建模型仓库条目（`{name, type, description?}`）；同名 → 409。"""
    if not body.name or not body.name.strip():
        return err(40000, "模型名称不能为空", status=400)
    if not body.type or not body.type.strip():
        return err(40000, "模型类型不能为空", status=400)
    try:
        model = svc.create_model(session, body.name.strip(), body.type.strip(), body.description)
    except ValueError as exc:  # 同名冲突 → 409（契约 §1.3）
        return err(40900, str(exc), status=409)
    write_audit(
        session,
        current_user.id,
        "create",
        "model",
        model.name,
        {"type": model.type, "description": model.description},
    )
    session.commit()
    session.refresh(model)
    return ok(svc.model_payload(model))


@router.patch("/models/{model_id}/versions/{model_version_id}")
def update_model_version_status(
    model_id: int,
    model_version_id: int,
    body: ModelVersionUpdate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """更新模型版本状态/备注（如置为生产候选）；status 白名单校验。"""
    model = session.get(Model, model_id)
    if model is None:
        return err(40401, "模型不存在", status=404)
    version = session.get(ModelVersion, model_version_id)
    if version is None or version.model_id != model.id:
        return err(40402, "模型版本不存在", status=404)
    try:
        version = svc.update_version_status(session, model, version, body.status, body.note)
    except ValueError as exc:  # 非法状态 → 400（契约 §3.6 白名单）
        return err(40000, str(exc), status=400)
    write_audit(
        session,
        current_user.id,
        "update",
        "model_version",
        str(version.id),
        {"model_id": model.id, "version_no": version.version_no, "status": version.status},
    )
    session.commit()
    session.refresh(version)
    return ok(svc.version_payload(version))


# ── 训练任务（异步 Job，状态经 GET /jobs/{job_id} 或 /training-tasks/{id} 轮询） ──


@router.post("/training-tasks")
def create_training_task(
    body: TrainingTaskCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """创建训练任务（**异步**）：`{dataset_version_id, base_model_id?, epochs, ...}`。

    同事务建 pending Job(type=training) + `training_tasks` 行（hyperparams 含高级参数），
    返回 `{job_id}`。成功后 handler 自动生成 `model_versions`（实验版本）+ 权重写 MinIO。
    """
    dataset_version = session.get(DatasetVersion, body.dataset_version_id)
    if dataset_version is None:
        return err(40401, "数据集版本不存在", status=404)
    if body.base_model_id is not None and session.get(ModelVersion, body.base_model_id) is None:
        return err(40401, "基础模型版本不存在", status=404)

    hyperparams = _training_hyperparams(body)
    job = create_job(session, type="training")
    task = TrainingTask(
        job_id=job.id,
        dataset_version_id=body.dataset_version_id,
        base_model_id=body.base_model_id,
        hyperparams=hyperparams,
    )
    session.add(task)
    write_audit(
        session,
        current_user.id,
        "create",
        "training_task",
        job.job_uid,
        {
            "dataset_version_id": body.dataset_version_id,
            "base_model_id": body.base_model_id,
            "hyperparams": hyperparams,
        },
    )
    session.commit()
    return ok({"job_id": job.job_uid})


@router.get("/training-tasks/{task_id}")
def get_training_task(task_id: str, session: Session = Depends(get_session)) -> dict:
    """训练状态/结果（契约 §3.6，轮询 Job 结构）：`result` 内嵌 `metrics{mAP50,
    precision, recall}` + `loss_curve{train, val}` + `model_version` + `progress`。"""
    job = get_job_by_uid(session, task_id)
    if job is None:
        return err(40401, "任务不存在", status=404)
    payload = to_job_payload(job)
    task = session.exec(
        select(TrainingTask).where(TrainingTask.job_id == job.id)
    ).first()
    # 域字段以 training_tasks 行为准合并；仅训练产生数据（succeeded）后合并
    # （pending/failed 保持 result=null，契约 §1.5/§6.1）。
    if task is not None and task.metrics is not None:
        result = dict(payload.get("result") or {})
        result["metrics"] = task.metrics
        result["loss_curve"] = task.loss_curve
        payload["result"] = result
    return ok(payload)


@router.get("/training-tasks/{task_id}/logs")
def get_training_logs(task_id: str, session: Session = Depends(get_session)) -> dict:
    """训练日志文本（契约 §3.6）。"""
    job = get_job_by_uid(session, task_id)
    if job is None:
        return err(40401, "任务不存在", status=404)
    task = session.exec(
        select(TrainingTask).where(TrainingTask.job_id == job.id)
    ).first()
    if task is None:
        return err(40401, "训练任务不存在", status=404)
    return ok(svc.training_logs(task, job))


# ── 测试任务（异步 Job） ──────────────────────────────────────────────


@router.post("/test-tasks")
def create_test_task(
    body: TestTaskCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """创建测试任务（**异步**）：`{model_version_id, dataset_version_id, tasks[]}` → `{job_id}`。"""
    if session.get(ModelVersion, body.model_version_id) is None:
        return err(40401, "模型版本不存在", status=404)
    if session.get(DatasetVersion, body.dataset_version_id) is None:
        return err(40401, "数据集版本不存在", status=404)

    job = create_job(session, type="test")
    task = TestTask(
        job_id=job.id,
        model_version_id=body.model_version_id,
        dataset_version_id=body.dataset_version_id,
        tasks=list(body.tasks),
    )
    session.add(task)
    write_audit(
        session,
        current_user.id,
        "create",
        "test_task",
        job.job_uid,
        {
            "model_version_id": body.model_version_id,
            "dataset_version_id": body.dataset_version_id,
            "tasks": list(body.tasks),
        },
    )
    session.commit()
    return ok({"job_id": job.job_uid})


@router.get("/test-tasks/{task_id}")
def get_test_task(task_id: str, session: Session = Depends(get_session)) -> dict:
    """测试结果（轮询 Job 结构）：`result` 内嵌 `metrics{accuracy, recall, f1,
    latency_ms}` + `confusion_matrix`（2×2）。"""
    job = get_job_by_uid(session, task_id)
    if job is None:
        return err(40401, "任务不存在", status=404)
    payload = to_job_payload(job)
    task = session.exec(
        select(TestTask).where(TestTask.job_id == job.id)
    ).first()
    if task is not None and task.metrics is not None:
        result = dict(payload.get("result") or {})
        result["metrics"] = task.metrics
        result["confusion_matrix"] = task.confusion_matrix
        payload["result"] = result
    return ok(payload)


# ── 推理任务（异步 Job） ──────────────────────────────────────────────


@router.post("/inference-tasks")
def create_inference_task(
    body: InferenceTaskCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """提交推理（**异步**）：`{model_version_id, input, input_type}` → `{job_id}`。"""
    if session.get(ModelVersion, body.model_version_id) is None:
        return err(40401, "模型版本不存在", status=404)
    if not body.input or not body.input.strip():
        return err(40000, "推理输入不能为空", status=400)
    if not body.input_type or not body.input_type.strip():
        return err(40000, "输入类型不能为空", status=400)

    job = create_job(session, type="inference")
    task = InferenceTask(
        job_id=job.id,
        model_version_id=body.model_version_id,
        input_type=body.input_type,
        input_key=body.input,
    )
    session.add(task)
    write_audit(
        session,
        current_user.id,
        "create",
        "inference_task",
        job.job_uid,
        {"model_version_id": body.model_version_id, "input_type": body.input_type},
    )
    session.commit()
    return ok({"job_id": job.job_uid})


@router.get("/inference-tasks/{task_id}")
def get_inference_task(task_id: str, session: Session = Depends(get_session)) -> dict:
    """推理结果（轮询 Job 结构）：`result` 内嵌 `boxes/categories/confidence/latency_ms`。"""
    job = get_job_by_uid(session, task_id)
    if job is None:
        return err(40401, "任务不存在", status=404)
    payload = to_job_payload(job)
    task = session.exec(
        select(InferenceTask).where(InferenceTask.job_id == job.id)
    ).first()
    if task is not None and task.result is not None:
        payload["result"] = task.result
    return ok(payload)


# ── 内部助手 ─────────────────────────────────────────────────────────


def _training_hyperparams(body: TrainingTaskCreate) -> dict:
    """训练超参：已知字段 + 高级参数（extra）合并为 `hyperparams` JSON。"""
    hyperparams: dict = {}
    for key in ("epochs", "batch_size", "learning_rate", "val_ratio"):
        value = getattr(body, key)
        if value is not None:
            hyperparams[key] = value
    for key, value in (body.model_extra or {}).items():
        hyperparams[key] = value
    return hyperparams
