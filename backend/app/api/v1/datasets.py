"""datasets 域路由（Task 15）：数据集 CRUD / 输入维度 / 适配检查 / 版本 / 构建任务 / 血缘。

端点契约 `docs/API接口清单.md` §3.5；全部需登录（router 级 `Depends(get_current_user)`），
返回统一 `ok(...)` / `err(...)` 信封；领域逻辑在 `app.services.datasets`。

构建任务（`POST …/build-tasks`）走异步 Job：同事务建 pending Job + `dataset_build_tasks`
行 → 返回 `{job_id}`；完整来源（type + annotation_task_id/split_task_id/sample_ids/filters）
经 `create_job(result={"source": ...})` 随 Job 携带（`dataset_build_tasks.source` 仅存类型，
契约 §3.22）。后台执行器跑 `app.jobs.dataset_build` handler；状态经通用 `GET /jobs/{job_id}` 轮询。

错误码：40401=数据集不存在、40402=数据集版本不存在（含版本不属于该数据集）、40900=数据集名称冲突、40000=参数错误。
"""

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func
from sqlmodel import Session, select

from app.api.deps import get_current_user
from app.core.audit import write_audit
from app.core.db import get_session
from app.models.data import DataRecord, User
from app.models.datasets import DatasetBuildTask, DatasetVersion
from app.schemas.common import err, ok, paginate
from app.services import datasets as svc
from app.services.jobs import create_job

router = APIRouter(dependencies=[Depends(get_current_user)])


class DatasetCreate(BaseModel):
    """POST /datasets 请求体（契约 §3.5）：`source?` 为样本来源描述（本期不落库，构建时用）。"""

    name: str
    task: str
    source: object | None = None


class DatasetVersionCreate(BaseModel):
    """POST /datasets/{id}/versions 请求体（契约 §3.5）：`name`/`note` 仅接受不落库。"""

    name: str | None = None
    note: str | None = None


class BuildTaskCreate(BaseModel):
    """POST …/build-tasks 请求体（契约 §3.5）：`source` = DatasetSource（type + 各 id/筛选）。"""

    source: object


# ── 数据集列表 / 新建 / 详情 ─────────────────────────────────────────


@router.get("/datasets")
def list_datasets(session: Session = Depends(get_session)) -> dict:
    """数据集列表（任务类型/样本数/完成度/版本/状态 + 当前版本快照字段）。"""
    return ok(svc.list_datasets(session))


@router.post("/datasets")
def create_dataset(
    body: DatasetCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """新建数据集：`{name, task, source?}` → dataset_no `DS-xxx-序号`，status=标注中。"""
    if not body.name or not body.name.strip():
        return err(40000, "数据集名称不能为空", status=400)
    if not body.task or not body.task.strip():
        return err(40000, "数据集任务类型不能为空", status=400)
    try:
        dataset = svc.create_dataset(session, body.name.strip(), body.task.strip(), body.source)
    except ValueError as exc:  # 同名冲突 → 409（契约 §1.3）
        return err(40900, str(exc), status=409)
    write_audit(
        session,
        current_user.id,
        "create",
        "dataset",
        dataset.dataset_no,
        {"name": dataset.name, "task": dataset.task},
    )
    session.commit()
    session.refresh(dataset)
    return ok(svc.dataset_payload(dataset))


@router.get("/datasets/{dataset_id}")
def get_dataset(dataset_id: str, session: Session = Depends(get_session)) -> dict:
    """数据集详情：样本统计 / 当前版本 / 更新时间（`dataset_id` 兼容 DB id / dataset_no）。"""
    dataset = svc.get_dataset_by_identifier(session, dataset_id)
    if dataset is None:
        return err(40401, "数据集不存在", status=404)
    current = (
        session.get(DatasetVersion, dataset.current_version_id)
        if dataset.current_version_id is not None
        else None
    )
    label_distribution = (
        svc.label_distribution_for_version(session, current.id) if current is not None else {}
    )
    weld_count = session.exec(
        select(func.count(DataRecord.id)).where(DataRecord.dataset_id == dataset.id)
    ).one()
    return ok(svc.dataset_payload(dataset, current, label_distribution=label_distribution, weld_count=int(weld_count)))


# ── 输入维度 / 适配检查 ──────────────────────────────────────────────


@router.get("/datasets/{dataset_id}/dimensions")
def get_dimensions(dataset_id: str, session: Session = Depends(get_session)) -> dict:
    """输入维度状态：7 项，`{name, status(已具备|必需|缺失), required}`。"""
    dataset = svc.get_dataset_by_identifier(session, dataset_id)
    if dataset is None:
        return err(40401, "数据集不存在", status=404)
    return ok(svc.get_dimensions(session, dataset))


@router.get("/datasets/{dataset_id}/readiness")
def get_readiness(dataset_id: str, session: Session = Depends(get_session)) -> dict:
    """模型适配检查：按任务动态返回 `{readiness, checks:[{name, passed}]}`。"""
    dataset = svc.get_dataset_by_identifier(session, dataset_id)
    if dataset is None:
        return err(40401, "数据集不存在", status=404)
    return ok(svc.get_readiness(session, dataset))


# ── 版本 ─────────────────────────────────────────────────────────────


@router.get("/datasets/{dataset_id}/versions")
def list_dataset_versions(
    dataset_id: str, session: Session = Depends(get_session)
) -> dict:
    """数据集版本列表（固定快照：split / item_count / quality / snapshot_id）。"""
    dataset = svc.get_dataset_by_identifier(session, dataset_id)
    if dataset is None:
        return err(40401, "数据集不存在", status=404)
    return ok(svc.list_versions(session, dataset))


@router.post("/datasets/{dataset_id}/versions")
def create_dataset_version(
    dataset_id: str,
    body: DatasetVersionCreate,
    session: Session = Depends(get_session),
) -> dict:
    """新建版本（固定快照占位，不覆盖旧版，保证可复现）：`{name, note?}` → 下一版本号。"""
    dataset = svc.get_dataset_by_identifier(session, dataset_id)
    if dataset is None:
        return err(40401, "数据集不存在", status=404)
    version = svc.create_version(session, dataset, body.name, body.note)
    session.commit()
    session.refresh(version)
    return ok(svc.version_payload(version))


@router.get("/datasets/{dataset_id}/versions/{version_id}")
def get_dataset_version(
    dataset_id: str, version_id: int, session: Session = Depends(get_session)
) -> dict:
    """版本详情：固定样本清单划分 / item_count / quality / snapshot_id。"""
    dataset = svc.get_dataset_by_identifier(session, dataset_id)
    if dataset is None:
        return err(40401, "数据集不存在", status=404)
    version = session.get(DatasetVersion, version_id)
    if version is None or version.dataset_id != dataset.id:
        return err(40402, "数据集版本不存在", status=404)
    return ok(svc.version_payload(version))


@router.get("/datasets/{dataset_id}/versions/{version_id}/items")
def list_dataset_version_items(
    dataset_id: str,
    version_id: int,
    q: str | None = None,
    quality: str | None = None,
    split: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session: Session = Depends(get_session),
) -> dict:
    """数据集版本成员列表：按样本粒度返回固定快照。"""
    dataset = svc.get_dataset_by_identifier(session, dataset_id)
    if dataset is None:
        return err(40401, "数据集不存在", status=404)
    version = session.get(DatasetVersion, version_id)
    if version is None or version.dataset_id != dataset.id:
        return err(40402, "数据集版本不存在", status=404)

    q = q.strip() if q else None
    quality = quality.strip() if quality else None
    split = split.strip() if split else None
    if split not in {None, "train", "val", "test"}:
        return err(40000, "数据划分参数无效", status=400)

    items, total = svc.list_version_items(
        session,
        version,
        q=q,
        quality=quality,
        split=split,
        page=page,
        page_size=page_size,
    )
    return ok(paginate(items, total, page, page_size))


# ── 构建任务（异步 Job，状态经 GET /jobs/{job_id} 轮询） ─────────────


@router.post("/datasets/{dataset_id}/versions/{version_id}/build-tasks")
def create_build_task(
    dataset_id: str,
    version_id: int,
    body: BuildTaskCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """数据集构建任务（**异步**，契约 §3.5）：从切分/标注/手动/筛选样本生成固定版本。

    body `{source}`：DatasetSource（type + annotation_task_id/split_task_id/sample_ids/
    filters）。同事务建 pending Job（result 携带完整 source）+ `dataset_build_tasks` 行，
    返回 `{job_id}`；成功后经 `GET /jobs/{job_id}` 轮询（result 内嵌
    item_count/split/quality/snapshot_id）。
    """
    dataset = svc.get_dataset_by_identifier(session, dataset_id)
    if dataset is None:
        return err(40401, "数据集不存在", status=404)
    if dataset.status != "可训练":
        return err(
            40000,
            "当前数据集仍在标注中，不满足训练数据版本生成要求",
            status=400,
        )
    version = session.get(DatasetVersion, version_id)
    if version is None or version.dataset_id != dataset.id:
        return err(40402, "数据集版本不存在", status=404)

    source_type = _source_type(body.source)
    if source_type is None:
        return err(
            40000,
            f"source.type 需为 {'/'.join(svc.BUILD_SOURCES)}",
            status=400,
        )

    job = create_job(session, type="dataset_build", result={"source": body.source})
    task = DatasetBuildTask(
        job_id=job.id,
        dataset_version_id=version.id,
        source=source_type,
    )
    session.add(task)
    write_audit(
        session,
        current_user.id,
        "create",
        "dataset_build",
        job.job_uid,
        {
            "dataset_id": dataset.id,
            "dataset_no": dataset.dataset_no,
            "dataset_version_id": version.id,
            "source": body.source if isinstance(body.source, dict) else {"type": str(body.source)},
        },
    )
    session.commit()
    return ok({"job_id": job.job_uid})


# ── 血缘 ─────────────────────────────────────────────────────────────


@router.get("/datasets/{dataset_id}/lineage")
def get_lineage(dataset_id: str, session: Session = Depends(get_session)) -> dict:
    """数据血缘：原始焊缝 → 标注任务 → 数据集版本 → 模型训练（4 层节点）。"""
    dataset = svc.get_dataset_by_identifier(session, dataset_id)
    if dataset is None:
        return err(40401, "数据集不存在", status=404)
    return ok(svc.get_lineage(session, dataset))


# ── 内部助手 ─────────────────────────────────────────────────────────


def _source_type(source: object) -> str | None:
    """从 DatasetSource 提取类型字符串；未知/缺省 → None。"""
    if isinstance(source, dict):
        stype = source.get("type")
    elif isinstance(source, str):
        stype = source
    else:
        return None
    stype = str(stype or "")
    return stype if stype in svc.BUILD_SOURCES else None
