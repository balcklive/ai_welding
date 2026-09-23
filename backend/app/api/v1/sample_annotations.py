"""分段样本**段级标注**路由（`/api/v1/split-tasks/{task_id}/annotation-samples/*`）。

一期只做段级分类：一个 `Sample`（v3 时间窗样本）= 一个标注对象 = **一个主结论**
（`normal` / `defect` + 主缺陷类别）。没有框/点/掩膜，也没有两级精度。

端点：

- `GET    …/annotation-samples`              样本列表（分页；`filter=unannotated` 只看未标注）+ 进度；
- `GET    …/annotation-samples/{sample_id}`  单样本的当前结论（三模态细节走既有
  `GET /split-tasks/{task_id}/samples/{sample_id}`——媒体/时序各有其主人，不在这里复制一份）；
- `PUT    …/annotation-samples/{sample_id}`  保存结论（**upsert**）；
- `DELETE …/annotation-samples/{sample_id}`  撤销结论（回到未标注）；
- `GET    …/annotation-timeline`             **整条焊缝的标注总览时间轴**（全部窗口 + 标注态 +
  媒体 URL + 统一轴分层数据）——工作台主视图，一次拿全，不再逐段翻页；
- `GET    …/annotation-export`              版本化的标注导出（供数据集构建/离线消费）。

词表（主缺陷类别）的增删改**不在这里**——走 `GET/POST/PATCH/DELETE /settings/options/defect_category`
（写操作仅管理员），本 router 只读启用项。

鉴权：router 级 `Depends(get_current_user)`；审 `create`/`update`/`delete` 落
`audit_logs`（resource_type=`sample_annotation`），与业务写入同事务提交。
错误码：40401=任务/样本不存在、40000=参数或前置条件不满足。
"""

from fastapi import APIRouter, Depends
from loguru import logger
from pydantic import BaseModel
from sqlmodel import Session, select

from app.api.deps import forbid_unless_record_owned, get_current_user
from app.core.audit import write_audit
from app.core.db import get_session
from app.models.analysis import Sample, SampleAnnotation
from app.models.data import DataRecord, DataVersion, User
from app.schemas.common import err, ok, paginate
from app.services import annotation as annotation_svc
from app.services import sample_annotation as svc
from app.services import splitting

router = APIRouter(dependencies=[Depends(get_current_user)])

#: 标注总览时间轴一次返回的最大窗口数。真实焊缝 90~200 段，这里给足余量；
#: 超过就**明确报错**而不是截断——截断会让用户以为"这条焊缝只有上限那么多段"。
MAX_TIMELINE_WINDOWS = 2000
#: 时间轴上的媒体 URL 有效期（与预览帧同口径：够看完一遍标注，又不会长期泄露）。
TIMELINE_URL_EXPIRES_SECONDS = 3600


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


def _slot(meta_block: dict, extra: tuple[str, ...] = ()) -> dict:
    """从 manifest 的模态块里抽出前端要用的那几个键。

    完整 `meta` **不进响应**——几百段各带一份 manifest 会撑爆载荷（口径同
    `analysis._split_sample_payload`）。这里只给"能不能用 / 为什么不能用 + 定位信息"。
    """
    payload = {
        "available": bool(meta_block.get("available")),
        "calibrated": bool(meta_block.get("calibrated")),
        "excluded": bool(meta_block.get("excluded")),
        "reason": meta_block.get("reason"),
    }
    payload.update({key: meta_block.get(key) for key in extra})
    return payload


def _timeline_windows(storage, rows: list[Sample], annotations: dict) -> list[dict]:
    """把已落库的 `Sample` 行摊成总览时间轴的窗口列。

    **媒体 URL 只认 `meta` 里的类型化键**（`video.frame.object_key` / `seam_image.crop_key`），
    不去 `object_keys` 里按后缀猜——那是分段 Job 的写入顺序，不是契约。取不到就给 `null`，
    由前端显式说"该段没有帧"，不拿邻段的图顶替。
    """
    out: list[dict] = []
    for row in rows:
        meta = row.meta or {}
        video = meta.get("video") or {}
        seam = meta.get("seam_image") or {}
        annotation = annotations.get(row.id)
        frame_key = (video.get("frame") or {}).get("object_key")
        crop_key = seam.get("crop_key")
        out.append({
            "sample_id": row.id,
            "index": row.frame_no,
            "start": row.start_time,
            "end": row.end_time,
            "annotated": annotation is not None,
            "label": annotation.label if annotation is not None else None,
            "defect_category_name": (
                annotation.defect_category_name if annotation is not None else None
            ),
            "note": annotation.note if annotation is not None else None,
            "frame_url": _presign(storage, frame_key),
            "crop_url": _presign(storage, crop_key),
            "signal": _slot(meta.get("signal") or {}, ("sample_rate",)),
            "video": _slot(video, ("offset_seconds", "fps", "start_frame", "end_frame")),
            "seam_image": _slot(seam, ("spatial_range",)),
        })
    return out


def _presign(storage, object_key) -> str | None:
    """对象键 → 短期可读 URL。**签名失败不抛**：一张图取不到不该让整条时间轴打不开。"""
    if not object_key:
        return None
    try:
        return storage.presign_get(str(object_key), expires=TIMELINE_URL_EXPIRES_SECONDS)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Annotation timeline presign failed for {}: {}", object_key, exc)
        return None


@router.get("/split-tasks/{task_id}/annotation-timeline")
def get_annotation_timeline(
    task_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """整条焊缝的**标注总览时间轴**（标注工作台的主视图）。

    一次给全：① 全部窗口 + 标注态（窗口来自**已落库的 `Sample`**，不重算——标的一定是
    切出来的那一批）；② 每段自己的视频帧 / 焊缝切片短期 URL；③ 统一轴分层数据
    （`build_timeline_layers`，与分段页**同一段代码**产出，两页看到的边界不会漂移）。

    **不下载视频、不跑 ffmpeg、不写任何产物**——与 `split-preview` 的纯计算路径同级成本。
    全量给的是**索引与媒体地址**，不是媒体字节：图片按批由前端懒加载（设计 §4 硬约束③的原意）。
    """
    task, failure = _resolve_task(session, task_id, current_user)
    if failure is not None:
        return failure

    rows = session.exec(
        select(Sample)
        .where(Sample.split_task_id == task.id)
        .order_by(Sample.start_time, Sample.id)
    ).all()
    if not rows:
        return err(40000, "该分段任务没有样本，无法进入标注", status=400)
    if len(rows) > MAX_TIMELINE_WINDOWS:
        # 不静默截断：截断会让用户以为"这条焊缝只有上限那么多段"。
        return err(
            40000,
            f"该任务有 {len(rows)} 段，超过标注时间轴上限 {MAX_TIMELINE_WINDOWS} 段；"
            "请把窗口时长调大后重新分段",
            status=400,
        )

    version = session.get(DataVersion, task.version_id)
    record = session.get(DataRecord, version.record_id) if version is not None else None
    if version is None or record is None:
        return err(40401, "分段任务的来源版本不存在", status=404)

    annotations = {
        row.sample_id: row
        for row in session.exec(
            select(SampleAnnotation).where(
                SampleAnnotation.sample_id.in_([row.id for row in rows])
            )
        ).all()
    }
    # 延迟导入：`get_storage` 是懒加载单例，模块级绑定会绕过测试对 `app.storage` 的 monkeypatch
    # （同 `analysis.py` 的既有写法）。
    from app.storage import get_storage

    storage = get_storage()
    start = float(rows[0].start_time or 0.0)
    end = max(float(row.end_time or 0.0) for row in rows)

    # 时间轴分层数据读不回来时**不假装有波形**：窗口与标注态照常给，波形为空并写明原因。
    # 这与"缺失模态只标记不阻断"是同一条口径——没有波形不该让整条焊缝标不了。
    timeline: dict | None = None
    warnings: list[str] = []
    try:
        bundle = splitting.load_input(session, record, version)
        mapping = splitting.resolve_coordinate_mapping(session, record, version, bundle)
        timeline = splitting.build_timeline_layers(bundle, mapping, start, end)
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"统一时间轴波形不可用：{exc}")

    return ok({
        "task_id": task_id,
        "split_task_id": task.id,
        "version_id": task.version_id,
        "rules": dict(task.rules or {}),
        "progress": svc.stats(session, task),
        "timeline": timeline,
        "windows": _timeline_windows(storage, rows, annotations),
        "warnings": warnings,
    })


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
