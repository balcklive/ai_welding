"""分段样本**段级标注**路由（`/api/v1/split-tasks/{task_id}/annotation-samples/*`）。

一期只做段级分类：一个 `Sample`（v3 时间窗样本）= 一个标注对象 = **一个主结论**
（`normal` / `defect` + 主缺陷类别）。没有框/点/掩膜，也没有两级精度。

端点：

- `GET    …/annotation-samples`              样本列表（分页；`filter=unannotated` 只看未标注）+ 进度；
- `GET    …/annotation-samples/{sample_id}`  单样本的当前结论（三模态细节走既有
  `GET /split-tasks/{task_id}/samples/{sample_id}`——媒体/时序各有其主人，不在这里复制一份）；
- `PUT    …/annotation-samples/{sample_id}`  保存结论（**upsert**）；
- `DELETE …/annotation-samples/{sample_id}`  撤销结论（回到未标注）；
- `GET    …/annotation-export`              版本化的标注导出（供数据集构建/离线消费）。

词表（主缺陷类别）的增删改**不在这里**——走 `GET/POST/PATCH/DELETE /settings/options/defect_category`
（写操作仅管理员），本 router 只读启用项。

鉴权：router 级 `Depends(get_current_user)`；审 `create`/`update`/`delete` 落
`audit_logs`（resource_type=`sample_annotation`），与业务写入同事务提交。
错误码：40401=任务/样本不存在、40000=参数或前置条件不满足。
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session, select

from app.api.deps import forbid_unless_record_owned, get_current_user
from app.core.audit import write_audit
from app.core.db import get_session
from app.models.analysis import Sample
from app.models.data import DataRecord, DataVersion, User
from app.schemas.common import err, ok, paginate
from app.services import annotation as annotation_svc
from app.services import sample_annotation as svc

router = APIRouter(dependencies=[Depends(get_current_user)])


class SampleAnnotationUpsert(BaseModel):
    """PUT 请求体：一个主结论。

    `label=normal` 时 `defect_category_id` 必须缺省；`label=defect` 时必须给
    （词表中的**稳定 ID**，不是名字——名字会被改名）。
    """

    label: str
    defect_category_id: int | None = None
    note: str | None = None


def _resolve_task(
    session: Session, task_id: str, current_user: User | None = None
):
    """解析分段任务：不存在 → 404，前置条件不满足 → 400。

    归属校验沿用**分段域**的口径（同 `POST …/split-tasks`）：非管理员只能标注自己登记的
    焊缝，无权 → 403。这里刻意不跟随 `analysis_annotations.py` 那条旧标注线（它没有 owner
    校验）——v3 分段链路从创建任务起就是有 owner 概念的。
    """
    task = annotation_svc.resolve_split_task(session, task_id)
    if task is None:
        return None, err(40401, "分段任务不存在", status=404)
    if current_user is not None:
        version = session.get(DataVersion, task.version_id)
        record = session.get(DataRecord, version.record_id) if version is not None else None
        if record is not None:
            forbid_unless_record_owned(session, current_user, record)
    if reason := svc.task_block_reason(session, task):
        return None, err(40000, reason, status=400)
    return task, None


@router.get("/welds/{weld_id}/segment-annotation-tasks")
def list_segment_annotation_tasks(
    weld_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """该焊缝**可进入标注**的分段任务（已完成 + v3），供标注工作台的入口列表。

    只列已完成且 `rules_version>=3` 的任务；每条带标注进度，工作台据此显示"标了 3/8"。
    这里**不返回样本数据**——选中某个任务后再拉 `annotation-samples`。
    """
    record = session.exec(select(DataRecord).where(DataRecord.weld_id == weld_id)).first()
    if record is None:
        return err(40401, "焊缝不存在", status=404)
    forbid_unless_record_owned(session, current_user, record)
    return ok({"items": svc.list_annotatable_tasks(session, weld_id)})


@router.get("/split-tasks/{task_id}/annotation-samples")
def list_annotation_samples(
    task_id: str,
    page: int = 1,
    page_size: int = 50,
    filter: str = "all",
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """可标注样本列表（分页，按时间窗排序）。

    行**只含导航与进度需要的轻量字段**（时间窗 + 是否已标注 + 结论摘要）——模态清单、
    时序局部数据、媒体对象键走单样本详情端点按需取，否则几百个切片时列表响应必然失控。
    `filter=unannotated` 只看未标注（SQL 侧过滤）。
    """
    if filter not in {"all", "unannotated"}:
        return err(40000, "filter 需为 all / unannotated", status=400)
    task, failure = _resolve_task(session, task_id, current_user)
    if failure is not None:
        return failure
    items, total = svc.list_samples(
        session,
        task,
        page=page,
        page_size=page_size,
        only_unannotated=filter == "unannotated",
    )
    payload = paginate(items, total, max(1, int(page)), max(1, min(svc.MAX_PAGE_SIZE, int(page_size))))
    payload["progress"] = svc.stats(session, task)
    return ok(payload)


@router.get("/split-tasks/{task_id}/annotation-samples/{sample_id}")
def get_sample_annotation(
    task_id: str,
    sample_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """单样本的当前结论（未标注时 `annotation=null`，不是 404——「没标过」是正常状态）。

    样本的三模态细节（`meta` / 局部时序 / 产物对象键）用既有的
    `GET /split-tasks/{task_id}/samples/{sample_id}`，这里不重复返回。
    """
    task, failure = _resolve_task(session, task_id, current_user)
    if failure is not None:
        return failure
    sample = session.get(Sample, sample_id)
    if sample is None or sample.split_task_id != task.id:
        return err(40401, "样本不存在或不属于该任务", status=404)
    return ok({
        "sample_id": sample.id,
        "start_time": sample.start_time,
        "end_time": sample.end_time,
        "annotation": svc.annotation_payload(svc.annotation_of(session, sample.id)),
    })


@router.put("/split-tasks/{task_id}/annotation-samples/{sample_id}")
def save_sample_annotation(
    task_id: str,
    sample_id: int,
    body: SampleAnnotationUpsert,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """保存段级结论（**upsert**：同一样本重复保存是更新，不产生第二行）。

    校验：`label` ∈ {normal, defect}；defect 必须有主缺陷类别且类别存在、未被停用
    （对"本来就引用了该停用类别"的旧标注放行，否则类别一停用历史标注就改不动）；
    normal 必须不带类别；备注 ≤512 字。返回更新后的结论与最新进度。
    """
    task, failure = _resolve_task(session, task_id, current_user)
    if failure is not None:
        return failure
    sample = session.get(Sample, sample_id)
    if sample is None or sample.split_task_id != task.id:
        return err(40401, "样本不存在或不属于该任务", status=404)
    try:
        row = svc.upsert_annotation(
            session,
            sample,
            label=body.label,
            category_id=body.defect_category_id,
            note=body.note,
            user=current_user,
        )
    except svc.SampleAnnotationError as exc:
        return err(40000, str(exc), status=400)
    write_audit(
        session,
        current_user.id,
        "update",
        "sample_annotation",
        f"{task_id}/{sample_id}",
        {
            "label": row.label,
            "defect_category_id": row.defect_category_id,
            "defect_category_name": row.defect_category_name,
        },
    )
    session.commit()
    return ok({
        "annotation": svc.annotation_payload(row),
        "progress": svc.stats(session, task),
    })


@router.delete("/split-tasks/{task_id}/annotation-samples/{sample_id}")
def clear_sample_annotation(
    task_id: str,
    sample_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """撤销结论（回到未标注态）。本来就没有标注 → 40401（不假装删成功）。"""
    task, failure = _resolve_task(session, task_id, current_user)
    if failure is not None:
        return failure
    sample = session.get(Sample, sample_id)
    if sample is None or sample.split_task_id != task.id:
        return err(40401, "样本不存在或不属于该任务", status=404)
    if not svc.clear_annotation(session, sample):
        return err(40401, "该样本尚无标注", status=404)
    write_audit(
        session,
        current_user.id,
        "delete",
        "sample_annotation",
        f"{task_id}/{sample_id}",
        {},
    )
    session.commit()
    return ok({"cleared": True, "progress": svc.stats(session, task)})


@router.get("/split-tasks/{task_id}/annotation-export")
def export_sample_annotations(
    task_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """导出该分段任务的段级标注（版本化 JSON，不含媒体字节）。

    数据集构建消费的就是这个结构：顶层 `schema_version` + 每样本
    `{sample_id, sample_index, start_time, end_time, label, defect_category_id,
    defect_category_name}`。**未标注的样本也会出现**（`label=null`）——"没标"本身
    是有信息的，构建方据此算覆盖率。
    """
    task, failure = _resolve_task(session, task_id, current_user)
    if failure is not None:
        return failure
    return ok(svc.export_payload(session, task))


@router.get("/segment-annotation/categories")
def list_segment_annotation_categories(
    include_inactive: bool = False,
    session: Session = Depends(get_session),
) -> dict:
    """主缺陷词表（供标注工作台渲染候选）。

    默认只给启用项；`include_inactive=1` 时一并返回停用项（历史标注仍引用它们，
    工作台需要显示「已停用」而不是空候选）。增删改走 `/settings/options/defect_category`。
    """
    return ok({
        "categories": svc.list_categories(session, active_only=not include_inactive),
        "schema_version": svc.SCHEMA_VERSION,
    })
