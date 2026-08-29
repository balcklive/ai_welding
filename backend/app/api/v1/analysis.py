"""analysis 域路由（Task 11 ~ Task 14）：分析候选 / 多通道信号 / 真实 DSP 六模式 /
分析结果 / 特征提取 / 对齐任务 / 样本分段任务 / 标注。

端点契约见 `docs/API接口清单.md` §3.4；全部需登录（router 级 `Depends(get_current_user)`），
返回统一 `ok(...)` / `err(...)` 信封；信号必须来自成功导入的真实数据、
DSP 由 `app.services.dsp` 真实计算（scipy/pywt/numpy，非罐头数字）。

Task 13：对齐任务走异步 Job——`POST …/alignment-tasks` 建 pending Job + `alignment_tasks`
行（同事务 commit）返回 `{job_id}`；后台执行器（`app.jobs`，lifespan 启动）跑 handler
（`app.jobs.alignment`，模拟对齐 + 自动生成「时间对齐」版本 + 更新 latest_version_id）；
`GET /alignment-tasks/{task_id}` 返回 Job 信封（result 内嵌 events/tracks/assets）。

样本分段/标注：真实异步编排和真实输入校验：
- 切分 `POST …/split-tasks` 建 pending Job + `split_tasks` 行 → `{job_id}`；
  handler（`app.jobs.split`）按规则生成 `samples` 行 + 回填 sample_count；
  `GET /split-tasks/{task_id}` 返回 Job 信封（result 内嵌 sample_count + samples 前 50 条预览）。
- 标注：`GET /label-categories`；`POST /annotation-tasks` 异步建任务（handler
  `app.jobs.annotation` 把来源切分样本归属到本任务）；`GET /annotation-tasks/{task_id}`
  Job 信封；`POST …/import` 导入样本；`GET …/samples`（分页）与 `GET …/samples/{id}`
  （含样本级 confidence）；`POST …/ai-pretag`（同步确定性 2 区域）；`POST …/labels`
  （覆盖写，annotator=当前用户，类别/box/confidence∈[0,1] 校验，写审计）。
  标注任务相关 `{task_id}` 兼容 job_uid 与 DB id
  （`app.services.annotation.resolve_*`），前端创建后只持有 job_id 即可直接用。

错误码约定（与 welds 域一致）：40401=焊缝/登记/任务/样本不存在、40402=版本不存在、
40000=参数错误。

注意（坑）：
- `channels` 查询参数兼容 `channels[]=cur&channels[]=vol` 与 `channels=cur&channels=vol`
  两种写法——FastAPI 的 `Query` 只绑定其中一种 key，故从 `request.query_params` 手读合并。
- `analysis/result` 是**具体路径**，必须在 `analysis/{mode}` 之前注册，否则会被
  `mode="result"` 吞掉（FastAPI 按注册顺序匹配）。
- 滤波参数 `cutoff/cutoff2` 为 0~1 归一化频率（相对奈奎斯特），`带通` 需两者。
"""

from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
import math

from fastapi import APIRouter, Depends, Request
from loguru import logger
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.models.data import DataRecord, DataVersion
from app.models.jobs import Job

from app.api.deps import forbid_unless_record_owned, get_current_user, owned_weld_ids
from app.core.audit import write_audit
from app.core.db import get_session
from app.models.analysis import (
    AlignmentTask,
    FeatureExtraction,
    SplitTask,
)
from app.models.data import User
from app.schemas.common import err, ok
from app.services import dsp, features, signal_ingest, signals, splitting
from app.services import welds as svc
from app.services.jobs import (
    _iso_utc,
    create_job,
    get_job_by_uid,
    to_job_payload,
)
from app.services.signals import CHANNEL_SPECS
from app.api.v1.analysis_annotations import router as annotation_router

router = APIRouter(dependencies=[Depends(get_current_user)])
router.include_router(annotation_router)

_FILTER_TYPES = {"低通", "高通", "带通"}
_DEFAULT_SAMPLE_RATE = 1000
_NORMALIZATIONS = {"Z-Score", "Min-Max", "L2", "无"}
_FORMATS = {"NPY", "CSV", "JSON", "PT"}
#: 切分任务格式白名单（契约 §3.4）。
_SPLIT_FORMATS = {"目标检测", "时序分类"}


def _feature_request_key(body: "ExtractFeaturesRequest") -> str:
    raw = json.dumps({"weld_id": body.weld_id, "version_id": body.version_id, "normalization": body.normalization, "format": body.format}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
class ExtractFeaturesRequest(BaseModel):
    """POST /features/extract 请求体（契约 §3.4）。"""

    weld_id: str
    version_id: int
    normalization: str = "无"
    format: str = "JSON"


class FeatureDownloadRequest(BaseModel):
    format: str = "JSON"


class AlignmentTaskCreate(BaseModel):
    """POST …/alignment-tasks 请求体（契约 §3.4）。`modalities[]` 空时由服务端按焊缝登记模态兜底。"""

    modalities: list[str] = []


class SplitTaskCreate(BaseModel):
    """POST …/welds/{weld_id}/versions/{version_id}/split-tasks 请求体（契约 §3.4）。

    `fixed_rate`(帧/样本，>=1) 必填；`keep_event_buffer`(±s) 默认 0；`task_format` 默认目标检测。
    """

    fixed_rate: int
    stride: int | None = None
    keep_event_buffer: float = 0.0
    task_format: str = "目标检测"
    event_start: float | None = None
    event_end: float | None = None


class SplitPreviewRequest(SplitTaskCreate):
    """生产样本分段预览参数。"""


# ── 分析候选 ──────────────────────────────────────────────────────────


@router.get("/analysis/candidates")
def list_candidates(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """已登记且核验通过（quality=通过）的可分析焊缝列表（最小载荷）。

    注：分析与标注「选择数据」页已改为数据集优先两级选择，经
    `GET /welds?dataset_id=...` 取第二级（全量焊缝、未通过置灰）；本端点保留兼容。
    """
    records = svc.list_through_welds(session, owned_weld_ids(session, current_user))
    return ok(
        [
            {
                "id": r.id,
                "weld_id": r.weld_id,
                "weld_name": r.weld_name,
                "registration_no": r.registration_no,
                "source": r.source,
                "machine": r.machine,
                "weld_method": r.weld_method,
                "material": r.material,
                "thickness": r.thickness,
                "quality": r.quality,
                "latest_version_id": r.latest_version_id,
            }
            for r in records
        ]
    )


# ── 多通道信号 ────────────────────────────────────────────────────────


@router.get("/welds/{weld_id}/versions/{version_id}/signals")
def get_signals(
    weld_id: str,
    version_id: int,
    request: Request,
    filter_type: str | None = None,
    cutoff: float | None = None,
    cutoff2: float | None = None,
    max_points: int | None = None,
    start: float | None = None,
    end: float | None = None,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """多通道时域波形（电流/电压/气体/送丝）。query `channels[]`、滤波参数可选。

    波形预览抽稀（Overview/Detail 两级加载）：`max_points` 给定时按 **min-max 池化**
    （`signals.downsample_indices`，保留瞬态尖峰）服务端抽稀，且每通道附带 `times[]`
    （秒，与 values 等长——min-max 选点非均匀，前端须按 [t,v] 画点，勿按序号均分）；
    `start`/`end`（秒）给定则只取该时间窗（缩放增量取细节）。不传参数返回全分辨率
    数据（旧调用方/兼容行为不变）。**DSP 分析端点（/analysis/*）不用此抽稀，仍吃全量。**
    滤波给定则对选中通道真实滤波（dsp.filter_signal）。返回
    `{duration, sample_rate, channels:[{id,name,unit,values[],times?,lo,hi,mean}], events, anomalies}`。
    """
    resolved = _resolve_weld_version(session, weld_id, version_id, current_user)
    if resolved is not None:
        return resolved
    if msg := _filter_error(filter_type, cutoff, cutoff2):
        return err(40000, msg, status=400)
    if max_points is not None and not 2 <= max_points <= 20000:
        return err(40000, "max_points 须在 2~20000 之间", status=400)
    if (start is None) != (end is None) or (
        start is not None and end is not None and not 0 <= start < end
    ):
        return err(40000, "start/end 须成对给出且 0 <= start < end", status=400)

    bundle = signal_ingest.load_signal_bundle(session, weld_id, version_id)
    channel_ids = _requested_channels(request)
    for cid in channel_ids:
        if bundle.channel(cid) is None:
            return err(40000, f"未知通道: {cid}", status=400)

    fs = bundle.sample_rate or 1000
    n = len(bundle.channels[0].values) if bundle.channels else 0
    # 时间窗 → 采样下标范围（clamp）；抽稀时每通道附带 times（秒）
    i0, i1 = 0, n
    if start is not None and end is not None:
        i0 = max(0, min(n, int(start * fs)))
        i1 = max(i0, min(n, math.ceil(end * fs)))
    downsample = max_points is not None

    payload_channels = []
    for chan in bundle.channels:
        if channel_ids and chan.id not in channel_ids:
            continue
        values = chan.values
        if filter_type:
            values = dsp.filter_signal(values, fs, filter_type, cutoff, cutoff2)
        values = values[i0:i1]
        item = {
            "id": chan.id,
            "name": chan.name,
            "unit": chan.unit,
            "lo": chan.lo,
            "hi": chan.hi,
            "mean": chan.mean,
        }
        if downsample:
            sel = signals.downsample_indices(values, max_points or 0)
            item["values"] = values[sel].tolist()
            item["times"] = ((i0 + sel) / fs).round(6).tolist()
        else:
            item["values"] = values.tolist()
        payload_channels.append(item)

    return ok(
        {
            "duration": bundle.duration,
            "sample_rate": bundle.sample_rate,
            "channels": payload_channels,
            "events": bundle.events,
            "anomalies": bundle.anomalies,
            "source": bundle.source,
        }
    )


# ── 分析结果（具体路径，先于 {mode} 注册） ─────────────────────────────


@router.get("/welds/{weld_id}/versions/{version_id}/analysis/result")
def get_analysis_result(
    weld_id: str,
    version_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """AI 异常检测结果：焊接稳定度、正常/电弧不稳/飞溅占比、异常区段列表。

    确定性模拟结果（源自信号生成器的事件/异常区段，seeded by weld_id）。
    """
    resolved = _resolve_weld_version(session, weld_id, version_id, current_user)
    if resolved is not None:
        return resolved
    bundle = signal_ingest.load_signal_bundle(session, weld_id, version_id)
    return ok({**signals.analysis_result(bundle), "source": bundle.source})


# ── 单视图分析（mode 分发） ────────────────────────────────────────────


@router.get("/welds/{weld_id}/versions/{version_id}/analysis/{mode}")
def get_analysis_mode(
    mode: str,
    weld_id: str,
    version_id: int,
    channel: str = "cur",
    filter_type: str | None = None,
    cutoff: float | None = None,
    cutoff2: float | None = None,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """单视图分析数据：mode ∈ psd|stft|dwt|wavelet|phase|pdd。

    query `channel`（默认 cur）+ 可选滤波参数（滤波后计算，与信号页联动）。
    未知 mode → 400。phase 需要 cur+vol 两通道，滤波同时作用于两者。
    """
    if mode == "result":  # 防御：/analysis/result 已由具体路由接管
        return err(40000, "未知分析模式: result", status=400)
    resolved = _resolve_weld_version(session, weld_id, version_id, current_user)
    if resolved is not None:
        return resolved
    if msg := _filter_error(filter_type, cutoff, cutoff2):
        return err(40000, msg, status=400)

    bundle = signal_ingest.load_signal_bundle(session, weld_id, version_id)
    fs = bundle.sample_rate

    if mode == "phase":
        cur = bundle.channel("cur")
        vol = bundle.channel("vol")
        if cur is None or vol is None:
            return err(40000, "相图需要电流与电压通道", status=400)
        cur_x, vol_x = cur.values, vol.values
        if filter_type:
            cur_x = dsp.filter_signal(cur_x, fs, filter_type, cutoff, cutoff2)
            vol_x = dsp.filter_signal(vol_x, fs, filter_type, cutoff, cutoff2)
        return ok(dsp.phase_trajectory(cur_x, vol_x))

    chan = bundle.channel(channel)
    if chan is None:
        return err(40000, f"未知通道: {channel}", status=400)
    x = chan.values
    if filter_type:
        x = dsp.filter_signal(x, fs, filter_type, cutoff, cutoff2)

    if mode == "psd":
        return ok(dsp.compute_psd(x, fs))
    if mode == "stft":
        return ok(dsp.compute_stft(x, fs))
    if mode == "dwt":
        return ok(dsp.compute_dwt(x))
    if mode == "wavelet":
        return ok(dsp.wavelet_decomp(x))
    if mode == "pdd":
        return ok(dsp.pdd_density(x, bins=28, lo=chan.lo, hi=chan.hi))
    return err(40000, f"未知分析模式: {mode}，需为 psd|stft|dwt|wavelet|phase|pdd", status=400)


# ── 特征提取（Task 12：真实多模态特征） ────────────────────────────────


@router.post("/features/extract-tasks")
def create_feature_extraction_task(
    body: ExtractFeaturesRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """创建异步特征提取任务；相同输入在运行中/已完成时幂等复用。"""
    if body.normalization not in _NORMALIZATIONS:
        return err(40000, f"normalization 需为 {'/'.join(sorted(_NORMALIZATIONS))}", status=400)
    if body.format not in _FORMATS:
        return err(40000, f"format 需为 {'/'.join(sorted(_FORMATS))}", status=400)
    resolved = _resolve_weld_version(session, body.weld_id, body.version_id, current_user)
    if resolved is not None:
        return resolved
    key = _feature_request_key(body)
    existing = session.exec(select(Job).where(Job.type == "feature_extraction", Job.request_key == key).order_by(Job.id.desc())).first()
    if existing is not None and existing.status in {"pending", "running", "succeeded"}:
        return ok({"job_id": existing.job_uid})
    job = create_job(session, "feature_extraction", {"request": body.model_dump(), "user_id": current_user.id})
    job.request_key = key
    write_audit(session, current_user.id, "create", "feature_extraction_job", job.job_uid, body.model_dump())
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = session.exec(select(Job).where(Job.type == "feature_extraction", Job.request_key == key).order_by(Job.id.desc())).first()
        if existing is not None and existing.status in {"pending", "running", "succeeded"}:
            return ok({"job_id": existing.job_uid})
        return err(40900, "相同特征提取任务正在创建，请稍后重试", status=409)
    return ok({"job_id": job.job_uid})


@router.post("/features/extract")
def extract_features(
    body: ExtractFeaturesRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """执行特征提取（**同步**，契约 §3.4）：时序/视觉/声音特征 + 统一向量 → 落库。

    读取信号/图片或视频关键帧/WAV → 逐模态计算特征 → `unify` 拼接统一向量，
    写 `feature_extractions` 行（含来源状态与 created_at），返回 `ok(extraction)`。
    """
    if body.normalization not in _NORMALIZATIONS:
        return err(
            40000,
            f"normalization 需为 {'/'.join(sorted(_NORMALIZATIONS))}",
            status=400,
        )
    if body.format not in _FORMATS:
        return err(40000, f"format 需为 {'/'.join(sorted(_FORMATS))}", status=400)
    resolved = _resolve_weld_version(session, body.weld_id, body.version_id, current_user)
    if resolved is not None:
        return resolved
    record = svc.get_record_by_weld_id(session, body.weld_id)
    version = svc.get_version(session, body.version_id)

    bundle = signal_ingest.load_signal_bundle(session, body.weld_id, body.version_id)
    ts: dict[str, dict] = {}
    for chan in bundle.channels:
        ts[chan.id] = features.ts_features(chan.values, fs=bundle.sample_rate)
    vis, vision_source = _load_real_vision_features(version)
    audio_feats, audio_source = _load_real_audio_features(version)
    unified = features.unify(ts, vis, audio_feats, body.normalization, body.format)
    unified["modality_status"] = {
        "timeseries": "real" if bundle.source == "real" else "generated",
        "vision": vision_source,
        "audio": audio_source,
    }

    extraction = FeatureExtraction(
        version_id=body.version_id,
        ts_features=ts,
        vision_features=vis,
        audio_features=audio_feats,
        unified_vector=unified,
        normalization=body.normalization,
        format=body.format,
        created_at=datetime.now(timezone.utc),
    )
    session.add(extraction)
    session.flush()
    write_audit(
        session,
        current_user.id,
        "extract",
        "feature_extraction",
        str(extraction.id),
        {"weld_id": body.weld_id, "version_id": body.version_id, "normalization": body.normalization, "format": body.format},
    )
    session.commit()
    session.refresh(extraction)
    return ok(_extraction_payload(extraction, record=record, version=version, bundle_source=bundle.source))


@router.get("/features/latest/{version_id}")
def get_latest_feature_extraction(
    version_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """返回数据版本最近一次提取结果；不存在时返回 null。"""
    version = session.get(DataVersion, version_id)
    if version is None:
        return err(40402, "数据版本不存在", status=404)
    record = session.get(DataRecord, version.record_id)
    if record is None:
        return err(40401, "焊缝数据不存在", status=404)
    try:
        forbid_unless_record_owned(session, current_user, record)
    except Exception:
        return err(40300, "无权限", status=403)
    extraction = session.exec(
        select(FeatureExtraction)
        .where(FeatureExtraction.version_id == version_id)
        .order_by(FeatureExtraction.id.desc())
    ).first()
    return ok(_extraction_payload(extraction, record=record, version=version) if extraction else None)


@router.get("/features/history/{version_id}")
def get_feature_extraction_history(
    version_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """返回数据版本的特征提取历史摘要，供审计/重现选择使用。"""
    version = session.get(DataVersion, version_id)
    if version is None:
        return err(40402, "数据版本不存在", status=404)
    record = session.get(DataRecord, version.record_id)
    if record is None:
        return err(40401, "焊缝数据不存在", status=404)
    try:
        forbid_unless_record_owned(session, current_user, record)
    except Exception:
        return err(40300, "无权限", status=403)
    rows = session.exec(select(FeatureExtraction).where(FeatureExtraction.version_id == version_id).order_by(FeatureExtraction.id.desc())).all()
    return ok([{
        "id": row.id,
        "status": row.status,
        "normalization": row.normalization,
        "format": row.format,
        "algorithm_version": row.algorithm_version,
        "pipeline_version": row.pipeline_version,
        "source_by_modality": row.source_by_modality or {},
        "created_at": _iso_utc(row.created_at),
        "finished_at": _iso_utc(row.finished_at),
    } for row in rows])


@router.post("/features/{extraction_id}/download")
def download_feature_extraction(
    extraction_id: int,
    body: FeatureDownloadRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """将统一向量序列化为真实 JSON/CSV/NPY 文件并返回预签名 URL。"""
    if body.format not in {"JSON", "CSV", "NPY", "PT"}:
        return err(40000, "format 需为 JSON、CSV、NPY 或 PT", status=400)
    extraction = session.get(FeatureExtraction, extraction_id)
    if extraction is None:
        return err(40401, "特征提取记录不存在", status=404)
    version = session.get(DataVersion, extraction.version_id)
    record = session.get(DataRecord, version.record_id) if version else None
    if record is None:
        return err(40401, "焊缝数据不存在", status=404)
    try:
        forbid_unless_record_owned(session, current_user, record)
    except Exception:
        return err(40300, "无权限", status=403)
    values = (extraction.unified_vector or {}).get("values", [])
    if body.format == "JSON":
        content = json.dumps(_extraction_payload(extraction, record=record, version=version), ensure_ascii=False).encode("utf-8")
        suffix, content_type = "json", "application/json"
    elif body.format == "CSV":
        lines = ["index,value"] + [f"{index},{value}" for index, value in enumerate(values)]
        content, suffix, content_type = ("\n".join(lines) + "\n").encode("utf-8"), "csv", "text/csv"
    elif body.format == "NPY":
        buffer = BytesIO()
        import numpy as np

        np.save(buffer, np.asarray(values, dtype=np.float32))
        content, suffix, content_type = buffer.getvalue(), "npy", "application/octet-stream"
    else:
        try:
            import torch
        except ImportError:
            return err(50300, "PT 导出需要部署 PyTorch 运行时", status=503)
        buffer = BytesIO()
        torch.save({"values": torch.tensor(values, dtype=torch.float32), "extraction_id": extraction.id}, buffer)
        content, suffix, content_type = buffer.getvalue(), "pt", "application/octet-stream"
    from app.storage import get_storage

    key = f"processed/{record.weld_id}/features/{extraction.id}.{suffix}"
    storage = get_storage()
    storage.upload_stream(key, BytesIO(content), len(content), content_type)
    write_audit(session, current_user.id, "export", "feature_extraction", str(extraction.id), {"format": body.format, "object_key": key})
    session.commit()
    return ok({"format": body.format, "object_key": key, "url": storage.presign_get(key)})


@router.get("/features/{extraction_id}")
def get_feature_extraction(
    extraction_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """特征提取结果（导出时使用，契约 §3.4）→ `ok(extraction)`。"""
    extraction = session.get(FeatureExtraction, extraction_id)
    if extraction is None:
        return err(40401, "特征提取记录不存在", status=404)
    version = session.get(DataVersion, extraction.version_id)
    record = session.get(DataRecord, version.record_id) if version is not None else None
    if record is not None:
        try:
            forbid_unless_record_owned(session, current_user, record)
        except Exception:
            return err(40300, "无权限", status=403)
    return ok(_extraction_payload(extraction, record=record, version=version))


# ── 对齐任务（Task 13：异步 Job，执行器在后台跑 handler） ───────────────


@router.post("/welds/{weld_id}/versions/{version_id}/alignment-tasks")
def create_alignment_task(
    weld_id: str,
    version_id: int,
    body: AlignmentTaskCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """提交多模态对齐任务（**异步**，契约 §3.4）：建 pending Job + `alignment_tasks` 行。

    同事务 commit，返回 `{job_id}`（job_uid）。成功后（后台执行器）自动生成
    `action=时间对齐` 版本并更新 `latest_version_id`。
    """
    record = svc.get_record_by_weld_id(session, weld_id)
    if record is None:
        return err(40401, "焊缝不存在", status=404)
    try:
        forbid_unless_record_owned(session, current_user, record)
    except Exception:
        return err(40300, "无权限", status=403)
    version = svc.get_version(session, version_id)
    if version is None or version.record_id != record.id:
        return err(40402, "版本不存在", status=404)
    requested_modalities = list(body.modalities or [])
    if msg := _alignment_input_error(record, version, requested_modalities):
        return err(40000, msg, status=400)
    request_key = _alignment_request_key(version.id)
    existing_alignment = _existing_alignment_job_uid(session, version.id)
    if existing_alignment is not None:
        return ok({"job_id": existing_alignment})
    _release_failed_alignment_claims(session, version.id, request_key)
    session.flush()

    try:
        job = create_job(session, type="alignment")
        task = AlignmentTask(
            job_id=job.id,
            version_id=version.id,
            request_key=request_key,
            active_request_key=request_key,
            modalities=list(body.modalities),
        )
        session.add(task)
        session.flush()
        write_audit(
            session,
            current_user.id,
            "create",
            "alignment_task",
            job.job_uid,
            {"weld_id": weld_id, "version_id": version.id, "modalities": list(body.modalities)},
        )
        session.commit()
    except IntegrityError:
        session.rollback()
        existing_alignment = _existing_alignment_job_uid(session, version.id)
        if existing_alignment is not None:
            return ok({"job_id": existing_alignment})
        raise
    return ok({"job_id": job.job_uid})


@router.get("/alignment-tasks/{task_id}")
def get_alignment_task(
    task_id: str,
    session: Session = Depends(get_session),
) -> dict:
    """对齐任务状态/结果（契约 §3.4，轮询 Job 结构）：Job 信封，`result` 内嵌
    `events`/`event_source`/`tracks`/`assets`——tracks 为对齐真实化后的扩展结构
    （每条含 channel/modality/availability/source/aligned/asset/object_key/metadata/reason，
    availability=available|generated|unavailable 部分成功语义）；assets 为真实产物
    （时序 CSV/关键帧 JPG/tracks.json），前端经 `files.getFileUrl` 下载，视频播放
    raw 原始对象（track.object_key）。"""
    job = get_job_by_uid(session, task_id)
    if job is None:
        return err(40401, "任务不存在", status=404)
    payload = to_job_payload(job)
    task = session.exec(
        select(AlignmentTask).where(AlignmentTask.job_id == job.id)
    ).first()
    # 域字段以 alignment_tasks 行（事件/轨道/产物对象键）为准，合并进 result；
    # 仅在对齐产生数据（succeeded）后合并——pending/failed 保持 result=null（契约 §1.5/§6.1）。
    if task is not None and task.events is not None:
        result = dict(payload.get("result") or {})
        result["events"] = task.events
        result["tracks"] = task.tracks
        result["assets"] = task.assets
        payload["result"] = result
    return ok(payload)


@router.get("/welds/{weld_id}/versions/{version_id}/alignment-tasks/latest")
def get_latest_alignment_task(
    weld_id: str,
    version_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """恢复指定焊缝版本最近一次对齐任务，供页面刷新/重新进入时恢复状态。"""
    record = svc.get_record_by_weld_id(session, weld_id)
    if record is None:
        return err(40401, "焊缝不存在", status=404)
    try:
        forbid_unless_record_owned(session, current_user, record)
    except Exception:
        return err(40300, "无权限", status=403)
    version = svc.get_version(session, version_id)
    if version is None or version.record_id != record.id:
        return err(40402, "版本不存在", status=404)

    row = session.exec(
        select(AlignmentTask, Job)
        .join(Job, Job.id == AlignmentTask.job_id)
        .where(AlignmentTask.version_id == version_id)
        .order_by(AlignmentTask.id.desc())
    ).first()
    if row is None:
        return ok(None)

    task, job = row
    payload = to_job_payload(job)
    if task.events is not None:
        result = dict(payload.get("result") or {})
        result["events"] = task.events
        result["tracks"] = task.tracks
        result["assets"] = task.assets
        payload["result"] = result
    return ok(payload)


# ── 切分任务（Task 14：异步 Job，handler 按规则生成样本） ───────────────


@router.post("/welds/{weld_id}/versions/{version_id}/split-preview")
def preview_split_task(
    weld_id: str,
    version_id: int,
    body: SplitPreviewRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """使用生产规则计算预览；不创建任务、不写入样本。"""
    if body.fixed_rate < 1:
        return err(40000, "fixed_rate 需为 >=1 的整数（帧/样本）", status=400)
    stride = body.stride or body.fixed_rate
    if stride < 1:
        return err(40000, "stride 需为 >=1 的整数（帧）", status=400)
    if body.task_format not in _SPLIT_FORMATS:
        return err(40000, f"task_format 需为 {'/'.join(sorted(_SPLIT_FORMATS))}", status=400)
    resolved = _resolve_weld_version(session, weld_id, version_id, current_user)
    if resolved is not None:
        return resolved
    record = svc.get_record_by_weld_id(session, weld_id)
    version = svc.get_version(session, version_id)
    assert record is not None and version is not None
    try:
        bundle = splitting.load_input(session, record, version)
        bounds = splitting.event_bounds(
            bundle, body.event_start, body.event_end,
            body.keep_event_buffer,
        )
        windows = splitting.build_windows(
            duration=bundle.duration,
            sample_rate=bundle.sample_rate,
            window_frames=body.fixed_rate,
            stride_frames=stride,
            event_bounds=bounds,
        )
    except splitting.SplitInputError as exc:
        return err(40000, str(exc), status=400)
    return ok({
        "input": {
            "version_id": version.id,
            "duration": bundle.duration,
            "sample_rate": bundle.sample_rate,
            "source": "real",
        },
        "events": {**(bundle.events or {}), "weld_segment": list(bounds)},
        "summary": {
            "sample_count": len(windows),
            "effective_start": bounds[0],
            "effective_end": bounds[1],
            "window_seconds": body.fixed_rate / bundle.sample_rate,
            "stride_seconds": stride / bundle.sample_rate,
        },
        "windows": [window.__dict__ for window in windows[:100]],
    })


@router.post("/welds/{weld_id}/versions/{version_id}/split-tasks")
def create_split_task(
    weld_id: str,
    version_id: int,
    body: SplitTaskCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """提交数据切分任务（**异步**，契约 §3.4）：建 pending Job + `split_tasks` 行。

    同事务 commit，返回 `{job_id}`。成功后（后台执行器）按规则在 `samples` 表生成样本，
    回填 `SplitTask.sample_count` 与 Job.result（`{sample_count, samples:[...]}`）。
    """
    if body.fixed_rate < 1:
        return err(40000, "fixed_rate 需为 >=1 的整数（帧/样本）", status=400)
    stride = body.stride or body.fixed_rate
    if stride < 1:
        return err(40000, "stride 需为 >=1 的整数（帧）", status=400)
    if body.task_format not in _SPLIT_FORMATS:
        return err(
            40000,
            f"task_format 需为 {'/'.join(sorted(_SPLIT_FORMATS))}",
            status=400,
        )
    resolved = _resolve_weld_version(session, weld_id, version_id, current_user)
    if resolved is not None:
        return resolved

    record = svc.get_record_by_weld_id(session, weld_id)
    assert record is not None  # resolved above
    version = svc.get_version(session, version_id)
    assert version is not None  # resolved above
    if msg := _split_input_error(record, version):
        return err(40000, msg, status=400)
    try:
        bundle = splitting.load_input(session, record, version)
        bounds = splitting.event_bounds(
            bundle, body.event_start, body.event_end,
            body.keep_event_buffer,
        )
    except splitting.SplitInputError as exc:
        return err(40000, str(exc), status=400)

    rules = {
        "fixed_rate": body.fixed_rate,
        "stride": stride,
        "keep_event_buffer": body.keep_event_buffer,
        "event_bounds": list(bounds),
        "event_start": body.event_start,
        "event_end": body.event_end,
        "sample_rate": bundle.sample_rate,
        "duration": bundle.duration,
    }
    request_key = _split_request_key(version_id, rules, body.task_format)
    existing_split = _existing_split_job_uid(session, version_id, rules, body.task_format)
    if existing_split is not None:
        return ok({"job_id": existing_split})
    _release_failed_split_claims(session, version_id, request_key)
    session.flush()

    try:
        job = create_job(session, type="split")
        task = SplitTask(
            job_id=job.id,
            version_id=version_id,
            request_key=request_key,
            active_request_key=request_key,
            rules=rules,
            task_format=body.task_format,
        )
        session.add(task)
        write_audit(
            session,
            current_user.id,
            "create",
            "split_task",
            job.job_uid,
            {
                "weld_id": weld_id,
                "version_id": version_id,
                "fixed_rate": body.fixed_rate,
                "task_format": body.task_format,
            },
        )
        session.commit()
    except IntegrityError:
        session.rollback()
        existing_split = _existing_split_job_uid(session, version_id, rules, body.task_format)
        if existing_split is not None:
            return ok({"job_id": existing_split})
        raise
    return ok({"job_id": job.job_uid})


@router.get("/split-tasks/{task_id}")
def get_split_task(task_id: str, session: Session = Depends(get_session)) -> dict:
    """切分任务状态/结果（契约 §3.4，轮询 Job 结构）：result 内嵌 `sample_count`/`samples`。"""
    job = get_job_by_uid(session, task_id)
    if job is None:
        return err(40401, "任务不存在", status=404)
    payload = to_job_payload(job)
    task = session.exec(
        select(SplitTask).where(SplitTask.job_id == job.id)
    ).first()
    # 域字段以 split_tasks 行的 sample_count 为准（seed 与 handler 都写这里），合并进 result。
    if task is not None and task.sample_count is not None:
        result = dict(payload.get("result") or {})
        result["sample_count"] = task.sample_count
        payload["result"] = result
    return ok(payload)


# ── 内部助手 ──────────────────────────────────────────────────────────


def _resolve_weld_version(
    session: Session,
    weld_id: str,
    version_id: int,
    current_user: User | None = None,
) -> dict | None:
    """按 weld_id + version_id 解析焊缝与版本；缺任一返回 err 信封，否则 None。"""
    record = svc.get_record_by_weld_id(session, weld_id)
    if record is None:
        return err(40401, "焊缝不存在", status=404)
    if current_user is not None:
        try:
            forbid_unless_record_owned(session, current_user, record)
        except Exception:
            return err(40300, "无权限", status=403)
    version = svc.get_version(session, version_id)
    if version is None or version.record_id != record.id:
        return err(40402, "版本不存在", status=404)
    return None


def _extraction_payload(
    e: FeatureExtraction,
    *,
    record=None,
    version: DataVersion | None = None,
    bundle_source: str | None = None,
) -> dict:
    """FeatureExtraction → JSON 载荷（created_at 复用 jobs._iso_utc 序列化）。"""
    payload = {
        "id": e.id,
        "version_id": e.version_id,
        "ts_features": e.ts_features,
        "vision_features": e.vision_features,
        "audio_features": e.audio_features,
        "unified_vector": e.unified_vector,
        "normalization": e.normalization,
        "format": e.format,
        "created_at": _iso_utc(e.created_at),
        "status": e.status,
        "source_by_modality": e.source_by_modality or (e.unified_vector or {}).get("modality_status", {}),
        "input_object_keys": e.input_object_keys or [],
        "algorithm_version": e.algorithm_version,
        "pipeline_version": e.pipeline_version,
        "sample_rate": e.sample_rate,
        "sample_count": e.sample_count,
        "duration": e.duration,
        "channel_mapping": e.channel_mapping or {},
        "missing_modalities": e.missing_modalities or [],
        "warnings": e.warnings or [],
        "error_message": e.error_message,
        "started_at": _iso_utc(e.started_at),
        "finished_at": _iso_utc(e.finished_at),
    }
    stored_status = (e.unified_vector or {}).get("modality_status")
    if isinstance(stored_status, dict):
        payload["modality_status"] = stored_status
    elif record is not None or version is not None or bundle_source is not None:
        payload["modality_status"] = _feature_modality_status(record=record, version=version, bundle_source=bundle_source)
    return payload


def _load_real_vision_features(version: DataVersion) -> tuple[dict, str]:
    """优先读取真实图片/视频关键帧；不可用时返回空特征并明确标记。"""
    from app.storage import get_storage
    from app.core.config import settings

    keys = version.object_keys or []
    image_key = next((k for k in keys if k.lower().endswith((".jpg", ".jpeg", ".png", ".bmp", ".webp"))), None)
    video_key = next((k for k in keys if k.lower().endswith((".mp4", ".mov", ".avi", ".mkv"))), None)
    try:
        storage = get_storage()
        if image_key:
            data = storage.get_object(image_key)
            if settings.feature_vision_provider_url:
                return features.vision_features_from_provider(data, settings.feature_vision_provider_url), "real"
            return features.vision_features_from_image(data), "heuristic"
        if video_key:
            from app.services.media_probe import analyze_video

            _, frames = analyze_video(storage.get_object(video_key), [("first", 0.0)])
            if frames:
                data = frames[0]["bytes"]
                if settings.feature_vision_provider_url:
                    return features.vision_features_from_provider(data, settings.feature_vision_provider_url), "real"
                return features.vision_features_from_image(data), "heuristic"
    except Exception as exc:  # noqa: BLE001 - 单模态失败不应吞掉其它结果
        logger.warning("vision feature extraction unavailable: {}", exc)
    return {key: 0.0 for key in features.VISION_GEOMETRY_KEYS + features.VISION_TEXTURE_KEYS}, "missing"


def _load_real_audio_features(version: DataVersion) -> tuple[dict, str]:
    """读取真实 WAV；文件缺失或解析失败时返回空特征并明确标记。"""
    from app.storage import get_storage

    audio_key = next((k for k in (version.object_keys or []) if k.lower().endswith((".wav", ".wave"))), None)
    if not audio_key:
        return {key: 0.0 for key in features.AUDIO_FEATURE_KEYS}, "missing"
    try:
        return features.audio_features_from_wav(get_storage().get_object(audio_key)), "real"
    except Exception as exc:  # noqa: BLE001 - 单模态失败不应吞掉其它结果
        logger.warning("audio feature extraction unavailable: {}", exc)
        return {key: 0.0 for key in features.AUDIO_FEATURE_KEYS}, "missing"


def _requested_channels(request: Request) -> list[str]:
    """读 `channels[]`（兼容 `channels=`）查询参数，去重保序。"""
    raw = request.query_params.getlist("channels") or request.query_params.getlist("channels[]")
    seen: set[str] = set()
    out: list[str] = []
    for c in raw:
        c = c.strip()
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return out


def _alignment_input_error(
    record, version: DataVersion, requested_modalities: list[str]
) -> str | None:
    available = set(record.modalities or []) | set(_derive_modalities_from_keys(version.object_keys or []))
    required = set(requested_modalities or [])
    if not required:
        required = {m for m in available if m in {"video", "timeseries"}}
    if not required:
        return "缺少可用于对齐的输入：至少需要视频或时序信号文件"
    if "video" in required and "video" not in available:
        return "缺少对齐输入：未找到视频/图像文件"
    if "timeseries" in required and "timeseries" not in available:
        return "缺少对齐输入：未找到时序信号文件"
    return None


def _split_input_error(record, version: DataVersion) -> str | None:
    available = set(record.modalities or []) | set(_derive_modalities_from_keys(version.object_keys or []))
    if "timeseries" not in available:
        return "缺少切分输入：未找到可用的时序信号文件"
    return None


def _derive_modalities_from_keys(object_keys: list[str]) -> list[str]:
    return svc._derive_modalities(object_keys)


def _feature_modality_status(*, record, version: DataVersion | None, bundle_source: str | None) -> dict:
    from app.core.config import settings

    available = set(record.modalities or []) if record is not None else set()
    if version is not None:
        available |= set(_derive_modalities_from_keys(version.object_keys or []))
    return {
        "timeseries": "real" if bundle_source == "real" else "generated",
        # 历史同步记录无法证明已调用正式视觉模型；没有 provider 配置时必须诚实标为启发式。
        "vision": (
            "real"
            if settings.feature_vision_provider_url and ("video" in available or "infrared" in available)
            else "heuristic"
            if "video" in available or "infrared" in available
            else "missing"
        ),
        "audio": "real" if "audio" in available else "missing",
    }


def _existing_alignment_job_uid(session: Session, version_id: int) -> str | None:
    request_key = _alignment_request_key(version_id)
    rows = session.exec(
        select(AlignmentTask, Job)
        .join(Job, Job.id == AlignmentTask.job_id)
        .where(AlignmentTask.version_id == version_id)
        .order_by(AlignmentTask.id.desc())
    ).all()
    for task, job in rows:
        if task.request_key not in {None, request_key}:
            continue
        if job.status in {"pending", "running", "succeeded"}:
            return job.job_uid
    return None


def _release_failed_alignment_claims(session: Session, version_id: int, request_key: str) -> None:
    rows = session.exec(
        select(AlignmentTask, Job)
        .join(Job, Job.id == AlignmentTask.job_id)
        .where(
            AlignmentTask.version_id == version_id,
            AlignmentTask.request_key == request_key,
        )
    ).all()
    for task, job in rows:
        if job.status == "failed" and task.active_request_key is not None:
            task.active_request_key = None
            session.add(task)


def _existing_split_job_uid(
    session: Session,
    version_id: int,
    rules: dict,
    task_format: str,
) -> str | None:
    request_key = _split_request_key(version_id, rules, task_format)
    rows = session.exec(
        select(SplitTask, Job)
        .join(Job, Job.id == SplitTask.job_id)
        .where(SplitTask.version_id == version_id, SplitTask.task_format == task_format)
        .order_by(SplitTask.id.desc())
    ).all()
    for task, job in rows:
        if task.request_key not in {request_key, None}:
            continue
        if task.request_key is None and task.rules != rules:
            continue
        if job.status in {"pending", "running", "succeeded"}:
            return job.job_uid
    return None


def _release_failed_split_claims(session: Session, version_id: int, request_key: str) -> None:
    rows = session.exec(
        select(SplitTask, Job)
        .join(Job, Job.id == SplitTask.job_id)
        .where(SplitTask.version_id == version_id, SplitTask.request_key == request_key)
    ).all()
    for task, job in rows:
        if job.status == "failed" and task.active_request_key is not None:
            task.active_request_key = None
            session.add(task)



def _alignment_request_key(version_id: int) -> str:
    return f"alignment:{version_id}"



def _split_request_key(version_id: int, rules: dict, task_format: str) -> str:
    import hashlib
    import json

    payload = {"version_id": version_id, "rules": rules, "task_format": task_format}
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _filter_error(filter_type: str | None, cutoff: float | None, cutoff2: float | None) -> str | None:
    """校验滤波参数；返回错误信息（无错误返回 None）。"""
    if filter_type is None:
        return None
    if filter_type not in _FILTER_TYPES:
        return f"filter_type 需为 {'/'.join(sorted(_FILTER_TYPES))}"
    if cutoff is None or not 0 < cutoff < 1:
        return "cutoff 需在 (0,1) 范围内"
    if filter_type == "带通":
        if cutoff2 is None or not 0 < cutoff2 < 1:
            return "带通需提供 cutoff2（0<cutoff2<1）"
        if cutoff >= cutoff2:
            return "cutoff 需小于 cutoff2"
    return None
