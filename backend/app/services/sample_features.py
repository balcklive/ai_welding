"""切片级特征提取（服务层，2026-10）。

## 与版本级特征提取的分工

`feature_extractions`（§3.13）是**焊缝数据版本级**的 42 维统一向量：整条信号 + 一整张焊缝
照片 + 声音，供人看与报告导出。本模块是**切片级**的 36 维：一个 v3 `Sample`（一个时间窗）
一行，`sample_id` 唯一（PUT 即 upsert），供训练。

**为什么不合成一处**：那张表的版本级端点（`GET /features/latest/{version_id}`）按
`version_id` 取最新一行，切片行也带 `version_id` 就会被当成焊缝级向量返回。

## 36 维怎么来（全部复用 `services.features`）

- 时序 28：按该切片的采样点区间切**父版本信号**的每个通道，逐通道 `ts_features`
  （cur 8 / vol 8 / gas 6 / wir 6）。
- 视觉 8：该切片**自己的代表帧**（`meta.video.frame.object_key`）→ `vision_features_from_image`。
- 声音：**没有**。切片 manifest 自己就写着 `audio.available = False`
  （`splitting.map_window_to_modalities`），音频上传也已在 2026-10 收口拒收——
  没有真实源就不占 6 个维度，而不是拿合成音频凑数。

**归一化存原始值**（`CANONICAL_NORMALIZATION = "无"`）：`features._normalize` 作用在
**单个向量**上，逐切片 Z-Score 会把每片各自减均值、抹掉区分切片的那批量（电流均值/RMS/
气体水平），Min-Max 同理。标准化属于训练侧、应按 train 划分拟合；`normalization` 这一列
只记录导出时用了什么。

## 切片 → 采样点区间

**读 manifest，不要重算**：`splitting._window` 已经把 `ceil(秒 × fs)` 写进
`meta.signal.start_index/end_index`（`map_window_to_modalities`），那才是"切了什么"的
权威记录。只有 manifest 缺这两键（历史/手改）才回落到按 `start_time/end_time` 算。

## 缺失视觉是**逐片**降级，不是整批失败

视频是全站声明的增强模态（同 `_crop_seam_image` / `_extract_video_frames` 的取舍）。
一段抽不到帧就整批失败，等于 45 段里丢 1 帧废掉一整批。故：该片视觉记 `missing` + 把
服务端给的原因写进 `warnings`，**照样落库**；Job 记 `status="partial"`。
只有**整批信号读不回来**（`load_signal_bundle` 抛）才是整批失败——那时 36 维全是 0。

本模块**不 commit**（与其它服务一致），由 handler/路由提交。
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

from sqlalchemy import func as sa_func
from sqlmodel import Session, select

from app.core.config import settings
from app.models.analysis import Sample, SampleFeature, SplitTask
from app.models.data import DataRecord, DataVersion
from app.services import features, signal_ingest, splitting
from app.services.jobs import _iso_utc

#: 特征流水线版本。消费方认它才知道这 36 个数是哪套算法产出的（换算法必须改）。
PIPELINE_VERSION = "sample-features-v1"

#: 落库的**权威**向量一律原始值（理由见模块 docstring）。
CANONICAL_NORMALIZATION = "无"

#: 列表单页上限（与其它工作台一致）。
MAX_PAGE_SIZE = 200

#: 代表帧降采样长边上限。切片级每段各跑一次 `graycomatrix(levels=256)`，
#: 原分辨率下这是主要成本；版本级只跑一次，所以那边不传（默认不降采样）。
VISION_MAX_SIZE = 512

#: 原因码 → 面向用户的措辞。判定在 `splitting.segment_task_block_code`
#: （段级标注用同一份判定、另一套措辞）。
_BLOCK_MESSAGES = {
    "not_segment": "仅支持对 v3 分段任务（时间统一的多模态样本）提取切片特征",
    "not_succeeded": "分段任务尚未成功完成，暂不能提取特征",
}

_MISSING_VISION = "视频模态不可用或该段无代表帧"


class SampleFeatureError(ValueError):
    """切片特征的业务错误（参数/前置条件），由路由统一转 400。"""


class TaskNotExtractable(SampleFeatureError):
    """分段任务不满足切片特征提取的前置条件（未成功 / 非 v3）。"""


# ── 前置条件 ──────────────────────────────────────────────────────────


def block_reason(session: Session, task: SplitTask) -> str | None:
    """不可提取特征的原因；可提取返回 None。"""
    code = splitting.segment_task_block_code(session, task)
    return _BLOCK_MESSAGES.get(code) if code else None


# ── 计算 ──────────────────────────────────────────────────────────────


def _slice_bounds(sample: Sample, total_points: int, fallback_fs: int) -> tuple[int, int]:
    """该切片在父信号里的采样点区间 `[start, end)`。

    **优先读 manifest**（`splitting._window` 已按 `ceil(秒 × fs)` 写好，是"切了什么"的
    权威记录）；缺键才按 `start_time/end_time` 现算。一律 clamp 到 `[0, total_points]`
    ——覆盖 `tail_policy="keep"` 的短尾片，以及任何被手改过的 meta。
    """
    signal = (sample.meta or {}).get("signal") or {}
    start = signal.get("start_index")
    end = signal.get("end_index")
    if not isinstance(start, int) or not isinstance(end, int):
        fs = signal.get("sample_rate")
        fs = int(fs) if isinstance(fs, (int, float)) and fs > 0 else int(fallback_fs)
        start = math.ceil(float(sample.start_time or 0.0) * fs)
        end = math.ceil(float(sample.end_time or 0.0) * fs)
    start = max(0, min(int(start), total_points))
    end = max(start, min(int(end), total_points))
    return start, end


def _vision_inputs(sample: Sample) -> tuple[str | None, str | None]:
    """该切片的视觉来源：返回 `(object_key, 不可用原因)`。

    只认 manifest 的类型化键 `video.frame.object_key`——不按 `object_keys` 后缀猜
    （那是 Job 的写入顺序，不是契约）。
    """
    frame = ((sample.meta or {}).get("video") or {}).get("frame") or {}
    if frame.get("available") is False:
        return None, frame.get("reason") or _MISSING_VISION
    key = frame.get("object_key")
    if not isinstance(key, str) or not key:
        return None, frame.get("reason") or _MISSING_VISION
    return key, None


def _missing_vision() -> dict:
    return {
        key: 0.0
        for key in (*features.VISION_GEOMETRY_KEYS, *features.VISION_TEXTURE_KEYS)
    }


def _vision_features(storage, key: str) -> tuple[dict, str]:
    """一张代表帧 → 8 维视觉特征 + 来源标记（`real` = 走正式视觉服务）。

    异常一律上抛给调用方按片降级——**不在这里吞**，因为"哪一片缺了什么"要写进该行的
    `warnings`，而不是记一条与样本对不上的日志。
    """
    data = storage.get_object(key)
    if settings.feature_vision_provider_url:
        return features.vision_features_from_provider(data, settings.feature_vision_provider_url), "real"
    return features.vision_features_from_image(data, max_size=VISION_MAX_SIZE), "heuristic"


def compute_slice_features(
    bundle,
    sample: Sample,
    *,
    vision: dict,
    vision_status: str,
    warnings: list[str],
) -> dict:
    """一个切片的 36 维行字段（**不碰数据库**，纯计算）。

    `vision` / `vision_status` / `warnings` 由调用方备好——下载与降级策略在
    `extract_task_features` 里，这样单纯的计算可被单独验证。
    """
    start, end = _slice_bounds(sample, len(bundle.channels[0].values) if bundle.channels else 0, bundle.sample_rate)
    ts: dict[str, dict] = {}
    for channel in bundle.channels:
        ts[channel.id] = features.ts_features(channel.values[start:end], fs=bundle.sample_rate)
    unified = features.unify(
        ts, vision, None, CANONICAL_NORMALIZATION, "JSON", include_audio=False
    )
    return {
        "unified_vector": unified,
        "ts_features": ts,
        "vision_features": vision,
        "source_by_modality": {"timeseries": "real", "vision": vision_status},
        "channel_mapping": {
            "start_index": start,
            "end_index": end,
            "sample_rate": bundle.sample_rate,
            "channels": [channel.id for channel in bundle.channels],
        },
        "warnings": warnings,
        "normalization": CANONICAL_NORMALIZATION,
    }


# ── 写：按任务逐片提取 ────────────────────────────────────────────────


def extract_task_features(
    session: Session,
    task: SplitTask,
    *,
    normalization: str = CANONICAL_NORMALIZATION,
    job=None,
    user_id: int | None = None,
    storage=None,
) -> dict:
    """把该分段任务的每个切片提成一行 `SampleFeature`。handler 的领域逻辑。

    进度：每 20 片 `job.progress = …` 并 `session.commit()`（执行器专用 session 场景，
    同 `jobs/split.py`），让轮询看得见。

    失败清理**只删本次写入的行**：重提取失败时上一次的成功结果必须完好——
    整批删掉会让"改个参数重跑失败"变成数据也没了。
    """
    if storage is None:
        from app.storage import get_storage

        storage = get_storage()

    version = session.get(DataVersion, task.version_id)
    if version is None:
        raise SampleFeatureError("分段任务的来源版本不存在，无法提取切片特征")
    record = session.get(DataRecord, version.record_id)
    if record is None:
        raise SampleFeatureError("分段任务的来源登记数据不存在，无法提取切片特征")

    samples = list(
        session.exec(
            select(Sample)
            .where(Sample.split_task_id == task.id)
            .order_by(Sample.start_time, Sample.id)
        ).all()
    )
    if not samples:
        raise SampleFeatureError("该分段任务没有样本，无法提取切片特征")

    # 信号按 manifest 记的源版本取（不是 task.version_id）——manifest 才是
    # "切了什么"的权威记录；下标也全部相对它。整批读不回来才失败。
    signal_version_id = int(
        ((samples[0].meta or {}).get("source") or {}).get("version_id") or task.version_id
    )
    bundle = signal_ingest.load_signal_bundle(session, record.weld_id, signal_version_id)
    if not bundle.channels:
        raise SampleFeatureError("该版本的信号没有可用通道，无法提取切片特征")

    written: list[int] = []
    missing_vision = 0
    heuristic_vision = 0
    now = datetime.now(timezone.utc)
    try:
        for index, sample in enumerate(samples, start=1):
            warnings: list[str] = []
            key, reason = _vision_inputs(sample)
            if key is None:
                vision, vision_status = _missing_vision(), "missing"
                warnings.append(f"视觉缺失：{reason}")
            else:
                try:
                    vision, vision_status = _vision_features(storage, key)
                except Exception as exc:  # noqa: BLE001 —— 增强模态，缺一片不废整批
                    vision, vision_status = _missing_vision(), "missing"
                    warnings.append(f"视觉提取失败（{key}）：{exc}")
            if vision_status == "missing":
                missing_vision += 1
            elif vision_status != "real":
                heuristic_vision += 1

            payload = compute_slice_features(
                bundle, sample, vision=vision, vision_status=vision_status, warnings=warnings
            )
            row = session.exec(
                select(SampleFeature).where(SampleFeature.sample_id == sample.id)
            ).first()
            if row is None:
                row = SampleFeature(sample_id=sample.id, created_at=now)
            row.split_task_id = task.id
            row.version_id = signal_version_id
            row.normalization = normalization
            row.pipeline_version = PIPELINE_VERSION
            row.job_id = job.id if job is not None else None
            row.created_by = user_id
            row.finished_at = now
            for field, value in payload.items():
                setattr(row, field, value)
            session.add(row)
            session.flush()
            if row.id is not None:
                written.append(row.id)

            if job is not None and (index % 20 == 0 or index == len(samples)):
                job.progress = round(index / len(samples) * 100)
                session.commit()
    except Exception:
        # 只回滚本次写入的行；上一次成功的结果必须留着。
        session.rollback()
        _delete_rows(session, written)
        raise

    # `status` 只看**有没有帧**（`missing`）。"真帧 + 自家分割算法"（heuristic）如实记在
    # 每行的 `source_by_modality` 与该计数里，**不**把整批标成 partial——本部署没配正式
    # 视觉服务时按 non-real 算会让每一批都是 partial，那是噪音不是信号。
    status = "partial" if missing_vision else "succeeded"
    return {
        "split_task_id": task.id,
        "sample_count": len(samples),
        "extracted": len(written),
        "missing_vision": missing_vision,
        "heuristic_vision": heuristic_vision,
        "status": status,
        "normalization": normalization,
        "total_dims": features.SAMPLE_TOTAL_DIMS,
        "pipeline_version": PIPELINE_VERSION,
        "signal_version_id": signal_version_id,
    }


def _delete_rows(session: Session, row_ids: list[int]) -> None:
    """删掉给定 id 的切片特征行（best-effort，失败只记日志——不能盖住原始异常）。"""
    from loguru import logger

    if not row_ids:
        return
    try:
        for row in session.exec(
            select(SampleFeature).where(SampleFeature.id.in_(row_ids))
        ).all():
            session.delete(row)
        session.commit()
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        logger.warning("Slice feature rollback cleanup failed: {}", exc)


# ── 读 ────────────────────────────────────────────────────────────────


def feature_payload(row: SampleFeature, sample: Sample | None = None) -> dict:
    """特征行 → 对外载荷（含完整向量，供单样本详情）。"""
    return {
        "sample_id": row.sample_id,
        "split_task_id": row.split_task_id,
        "version_id": row.version_id,
        "index": sample.frame_no if sample is not None else None,
        "start_time": sample.start_time if sample is not None else None,
        "end_time": sample.end_time if sample is not None else None,
        "unified_vector": row.unified_vector,
        "ts_features": row.ts_features,
        "vision_features": row.vision_features,
        "modality_status": row.source_by_modality or {},
        "channel_mapping": row.channel_mapping or {},
        "warnings": row.warnings or [],
        "normalization": row.normalization,
        "pipeline_version": row.pipeline_version,
        "created_at": _iso_utc(row.created_at),
        "finished_at": _iso_utc(row.finished_at),
    }


def _row_payload(sample: Sample, row: SampleFeature | None) -> dict:
    """样本列表行：只给导航与进度需要的**轻量**字段。

    **不带 `values`**——任务几百片时全量向量会把列表响应撑爆（同"全量的是索引，
    不是媒体"的口径）。要数值走单样本详情。
    """
    frame = ((sample.meta or {}).get("video") or {}).get("frame") or {}
    return {
        "sample_id": sample.id,
        "index": sample.frame_no,
        "start_time": sample.start_time,
        "end_time": sample.end_time,
        "extracted": row is not None,
        "normalization": row.normalization if row is not None else None,
        "total_dims": (
            int((row.unified_vector or {}).get("total_dims") or 0) if row is not None else None
        ),
        "modality_status": (row.source_by_modality or {}) if row is not None else None,
        "warnings": (row.warnings or []) if row is not None else [],
        "frame_key": frame.get("object_key"),
        "frame_reason": None if frame.get("object_key") else (frame.get("reason") or _MISSING_VISION),
    }


def _features_for(session: Session, sample_ids: list[int]) -> dict[int, SampleFeature]:
    """批量取特征行（防列表 N+1）。"""
    if not sample_ids:
        return {}
    rows = session.exec(
        select(SampleFeature).where(SampleFeature.sample_id.in_(sample_ids))
    ).all()
    return {row.sample_id: row for row in rows}


def list_features(
    session: Session,
    task: SplitTask,
    *,
    page: int = 1,
    page_size: int = 50,
    only_unextracted: bool = False,
) -> tuple[list[dict], int]:
    """任务内切片的特征状态分页（按时间窗排序）。

    **未提取筛选在 SQL 侧完成**（`sample_features` 左联）——拉全量再在内存里过滤，
    几百片时会随任务规模线性变慢。
    """
    page = max(1, int(page))
    page_size = max(1, min(MAX_PAGE_SIZE, int(page_size)))
    base = select(Sample).where(Sample.split_task_id == task.id)
    count_stmt = (
        select(Sample.id)
        .where(Sample.split_task_id == task.id)
        .outerjoin(SampleFeature, SampleFeature.sample_id == Sample.id)
    )
    if only_unextracted:
        base = base.outerjoin(
            SampleFeature, SampleFeature.sample_id == Sample.id
        ).where(SampleFeature.id.is_(None))
        count_stmt = count_stmt.where(SampleFeature.id.is_(None))
    total = len(session.exec(count_stmt).all())
    rows = session.exec(
        base.order_by(Sample.start_time, Sample.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    features_by_sample = _features_for(session, [row.id for row in rows])
    return [
        _row_payload(row, features_by_sample.get(row.id)) for row in rows
    ], total


def feature_of(session: Session, task: SplitTask, sample_id: int) -> SampleFeature | None:
    """单样本特征行；样本不属于该任务返回 None（由路由转 40401）。"""
    sample = session.get(Sample, sample_id)
    if sample is None or sample.split_task_id != task.id:
        return None
    return session.exec(
        select(SampleFeature).where(SampleFeature.sample_id == sample_id)
    ).first()


def ordered_rows(session: Session, task: SplitTask) -> list[tuple[SampleFeature, Sample]]:
    """该任务的切片特征行（按时间窗排序，与工作台展示一致）。

    任务级产物与手动导出**共用这一处**——两处各写一遍 join，排序口径迟早分叉，
    导出文件的行序就对不上屏幕上的顺序了。
    """
    return list(
        session.exec(
            select(SampleFeature, Sample)
            .join(Sample, Sample.id == SampleFeature.sample_id)
            .where(SampleFeature.split_task_id == task.id)
            .order_by(Sample.start_time, Sample.id)
        ).all()
    )


def features_for_samples(session: Session, sample_ids: list[int]) -> dict[int, dict]:
    """`{sample_id: unified_vector}`——**数据集构建时冻结**的消费者。

    与 `sample_annotation.snapshot_for_samples` 同形：构建只读这一份，之后重跑特征提取
    不会改变已建版本的训练输入。
    """
    if not sample_ids:
        return {}
    rows = session.exec(
        select(SampleFeature).where(SampleFeature.sample_id.in_(sample_ids))
    ).all()
    return {row.sample_id: row.unified_vector for row in rows if row.unified_vector}


def task_progress(session: Session, task: SplitTask) -> dict:
    """该任务的提取进度（一次 group_by，避免逐任务查）。"""
    total = int(
        session.exec(
            select(sa_func.count(Sample.id)).where(Sample.split_task_id == task.id)
        ).one()
    )
    done = int(
        session.exec(
            select(sa_func.count(SampleFeature.id)).where(
                SampleFeature.split_task_id == task.id
            )
        ).one()
    )
    return {
        "total": total,
        "extracted": done,
        "pending": max(0, total - done),
        "progress": round(done / total * 100, 1) if total else 0.0,
    }


def list_extractable_tasks(session: Session, weld_id: str) -> list[dict]:
    """该焊缝可提取切片特征的分段任务（工作台入口列表）。

    "能看到哪些任务"与段级标注工作台**必须是同一份查询**（`splitting`），
    否则两个工作台能进的任务会不一致。
    """
    candidates = splitting.list_completed_segment_tasks(session, weld_id)
    out: list[dict] = []
    for task, job, version in candidates:
        rules = dict(task.rules or {})
        out.append(
            {
                "task_id": job.job_uid,
                "split_task_id": task.id,
                "version_id": version.id,
                "version_no": version.version_no,
                "sample_count": task.sample_count,
                "window_seconds": rules.get("window_seconds"),
                "stride_seconds": rules.get("stride_seconds"),
                "effective_range": rules.get("event_bounds"),
                "finished_at": _iso_utc(job.finished_at),
                "progress": task_progress(session, task),
            }
        )
    return out
