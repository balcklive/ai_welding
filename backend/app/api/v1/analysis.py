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
- 滤波参数 `cutoff/cutoff2` 为 0~1 归一化频率（**相对奈奎斯特频率 fs/2**，与 scipy
  `butter` 不传 fs 的默认一致），`带通` 需两者且 `cutoff < cutoff2`。换算：
  **Hz = cutoff × fs/2**（真实数据 fs 常见 5k/20k，因此 0.3 是 1500/3000 Hz 而不是 300 Hz；
  前端滑杆按 Hz 呈现即取 `sample_rate` 换算）。滤波后返回的 `lo/hi/mean` 按滤波后序列重算
  （`_series_range`），PDD 直方图量程同理。
"""

from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
import math

import numpy as np
from fastapi import APIRouter, Depends, Request
from loguru import logger
from pydantic import BaseModel
from sqlalchemy import func
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
    Sample,
    SplitTask,
)
from app.models.data import User
from app.schemas.common import err, ok, paginate
from app.services import alignment, annotation, dsp, features, signal_ingest, signals, splitting
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
#: **v3 起已废弃**（设计 §3.4）：切分不再产出"目标检测/时序分类"的二选一产物，新任务
#: `split_tasks.task_format` 写 NULL。历史任务仍按原值读取（见 `jobs/split._run_legacy`）。
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


class CalibrationUpdate(BaseModel):
    """PUT …/calibration 请求体（契约 §3.4）。

    **合并语义**：只更新给出的组，省略的组保持原值，显式 `null` 清除该组。

    - `video.offset_seconds`：视频零点在信号轴上的时刻，`t_video = t_signal - offset`；
    - `seam_image.roi`：焊缝照片上包住焊缝条带的轴对齐矩形 `{x,y,w,h}`（像素）；
    - `seam_image.excluded`：`true` = 用户**明确选择**「不对焊缝图片进行分段」，该模态在
      分段预览与样本 manifest 中一律记 `available=false` + 原因（只生成时序/视频样本）。
      与"没框 ROI"（未完成的标定）是两件事，引导文案也不同。给 `excluded=true` 时不需要
      ROI，因而也不下载图片做越界校验。
    """

    video: dict | None = None
    seam_image: dict | None = None


class SplitTaskCreate(BaseModel):
    """POST …/welds/{weld_id}/versions/{version_id}/split-tasks 请求体（契约 §5.4）。

    **只接受预览令牌**。禁止客户端另交一套规则或标定——服务端用 token 里签过的规则与
    映射哈希重建窗口，否则"所见即所得"失效（客户端可以显示一套、实际切另一套）。
    """

    preview_token: str


class SplitPreviewRequest(BaseModel):
    """POST …/split-preview 请求体（契约 §5.3 / §2.3）。

    **秒是唯一切分单位**（按帧入口已废弃，设计 §2.3）；默认 2.0 秒时长 / 2.0 秒步长，
    即默认不重叠。**不含任何标定参数**——映射恒从源版本 `calibration` 与对齐产物读取，
    标定只能在对齐页修改（§4.3）。
    """

    window_seconds: float = splitting.DEFAULT_WINDOW_SECONDS
    stride_seconds: float = splitting.DEFAULT_STRIDE_SECONDS
    event_start: float | None = None
    event_end: float | None = None
    keep_event_buffer: float = 0.0
    #: 尾片策略：`drop`（默认，不生成不足一个完整时长的末尾窗口）/ `keep`（保留不等长尾片）。
    tail_policy: str = "drop"


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
    滤波给定则对选中通道真实滤波（dsp.filter_signal；`cutoff/cutoff2` 为相对奈奎斯特的
    归一化频率，Hz = cutoff × sample_rate/2），此时 `lo/hi/mean` 按**滤波后**序列重算。
    返回
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
        if filter_type:
            # 滤波改均值/幅度：量程必须按滤波后序列重算，否则高通/带通信号会被按
            # 原始量程（电流 0–600）画成贴边直线，前端"滤波前后对比"必然失真。
            lo, hi, mean = _series_range(values)
            item["lo"], item["hi"], item["mean"] = lo, hi, mean
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
        if filter_type:
            # 滤波后信号均值/幅度都变了，直方图量程必须按滤波后序列取；
            # 否则高通信号（均值≈0）会全部落进原始量程（如电流 0–600）的第 0 个 bin。
            lo, hi, _ = _series_range(x)
            return ok(dsp.pdd_density(x, bins=28, lo=lo, hi=hi))
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


@router.get("/welds/{weld_id}/versions/{version_id}/calibration")
def get_calibration(
    weld_id: str,
    version_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """读该焊缝的**权威标定**（契约 §3.4）。

    标定归属固定钉在 **v1.0 原始版本**上——对齐任务可能跑在任意加工版本，标定若跟着任务
    版本走，同一条焊缝会散出多份互相矛盾的标定。故 `version_id` 只用于归属校验，任何属于
    该焊缝的版本都读到同一份标定。
    """
    resolved = _resolve_weld_version(session, weld_id, version_id, current_user)
    if resolved is not None:
        return resolved
    record = svc.get_record_by_weld_id(session, weld_id)
    v10, calibration = alignment.anchored_calibration(session, record)
    return ok(alignment.calibration_payload(v10, calibration))


@router.put("/welds/{weld_id}/versions/{version_id}/calibration")
def put_calibration(
    weld_id: str,
    version_id: int,
    body: CalibrationUpdate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """写标定（归属 v1.0 原始版本），写审计（契约 §3.4）。

    **只改 `calibration` 一列**——不碰 `object_keys`、不重算历史 `alignment_tasks.mapping`、
    不动任何 `split_tasks`；重新标定只影响此后新发起的对齐/分段，历史产物保持当时口径。
    ROI 必须落在焊缝照片的真实像素范围内，故给出 ROI 时会下载图片读一次宽高。
    """
    resolved = _resolve_weld_version(session, weld_id, version_id, current_user)
    if resolved is not None:
        return resolved
    record = svc.get_record_by_weld_id(session, weld_id)
    v10, current = alignment.anchored_calibration(session, record)
    if v10 is None:
        return err(40000, "该焊缝没有 v1.0 原始版本，无法保存标定", status=400)
    patch_fields = body.model_dump(exclude_unset=True)

    # 只有本次确实给了 ROI 才去下载图片取宽高——GET 与仅改 offset 的 PUT 不付这个成本。
    image_size = None
    roi_given = (
        isinstance(patch_fields.get("seam_image"), dict)
        and patch_fields["seam_image"].get("roi") is not None
    )
    if roi_given:
        image_key = alignment.seam_image_key(v10.object_keys)
        if image_key is None:
            return err(40000, "该焊缝没有焊缝图片，无法标定 ROI", status=400)
        from app.storage import get_storage

        image_size = alignment.read_image_size(get_storage(), image_key)
        if image_size is None:
            return err(40000, f"焊缝图片不可读（{image_key}），无法校验 ROI 范围", status=400)

    try:
        patch = alignment.validate_calibration_patch(patch_fields, image_size=image_size)
    except alignment.CalibrationError as exc:
        return err(40000, str(exc), status=400)

    merged = alignment.merge_calibration(current, patch)
    alignment.save_calibration(session, v10, merged)
    write_audit(
        session,
        current_user.id,
        "update",
        "calibration",
        str(v10.id),
        {"weld_id": weld_id, "calibration": merged},
    )
    session.commit()
    return ok(alignment.calibration_payload(v10, merged))


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
    """按秒级规则计算预览（契约 §5.3）：**只读**，不创建任务、不写入任何产物。

    预览与正式生成共用 `splitting.build_time_windows`，保证边界、数量、尾片处理完全一致。
    返回的 `preview_token` 是创建任务的**唯一凭证**——客户端不能另交一套规则。
    """
    resolved = _resolve_weld_version(session, weld_id, version_id, current_user)
    if resolved is not None:
        return resolved
    record = svc.get_record_by_weld_id(session, weld_id)
    version = svc.get_version(session, version_id)
    assert record is not None and version is not None
    try:
        window_seconds, stride_seconds, tail_policy = splitting.validate_rules(
            window_seconds=body.window_seconds,
            stride_seconds=body.stride_seconds,
            tail_policy=body.tail_policy,
        )
        bundle = splitting.load_input(session, record, version)
        mapping = splitting.resolve_coordinate_mapping(session, record, version, bundle)
        effective_range = splitting.resolve_effective_range(
            bundle, body.event_start, body.event_end, body.keep_event_buffer
        )
        windows = splitting.build_time_windows(
            duration=bundle.duration,
            sample_rate=bundle.sample_rate,
            window_seconds=window_seconds,
            stride_seconds=stride_seconds,
            event_bounds=(effective_range["start"], effective_range["end"]),
            tail_policy=tail_policy,
        )
        preview = splitting.build_preview(
            bundle=bundle,
            mapping=mapping,
            rules=_split_rules(
                body, window_seconds, stride_seconds, tail_policy, bundle
            ),
            windows=windows,
            effective_range=effective_range,
            weld_id=weld_id,
            version_id=version_id,
        )
        # 逐段代表帧：预览必须给出**本段自己的**画面（占位图不算数）。**视频覆盖范围内的每一段
        # 都要有自己的帧**（不设段数上限），抽帧结果按段挂短期 URL；某段真的抽不到就逐段记不可用
        # 并写明原因，不伪造、也不拿别的段顶替。
        from app.storage import get_storage

        return ok(splitting.attach_preview_frames(
            preview,
            storage=get_storage(),
            weld_id=weld_id,
            mapping=mapping,
            windows=windows,
        ))
    except splitting.SplitInputError as exc:
        return err(40000, str(exc), status=400)


@router.post("/welds/{weld_id}/versions/{version_id}/split-tasks")
def create_split_task(
    weld_id: str,
    version_id: int,
    body: SplitTaskCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """提交分段任务（**异步**，契约 §5.4）：**只接受预览令牌**。

    服务端用 token 里签过的规则与映射哈希**重建**窗口。token 绑定焊缝/版本，并校验规则、
    有效事件区间与标定/映射自预览以来**是否已变更**——变更即 409 要求重新预览。否则
    客户端屏幕上的一套边界与实际切出来的会不一致，"所见即所得"失效。
    """
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
        token = splitting.verify_preview_token(body.preview_token)
    except splitting.SplitInputError as exc:
        return err(40000, str(exc), status=400)
    if str(token.get("weld_id")) != weld_id or str(token.get("version_id")) != str(version_id):
        return err(40000, "预览令牌与当前焊缝/版本不匹配，请重新预览", status=400)

    rules = dict(token.get("rules") or {})
    try:
        window_seconds, stride_seconds, tail_policy = splitting.validate_rules(
            window_seconds=rules.get("window_seconds"),
            stride_seconds=rules.get("stride_seconds"),
            tail_policy=rules.get("tail_policy", "drop"),
        )
        bundle = splitting.load_input(session, record, version)
        mapping = splitting.resolve_coordinate_mapping(session, record, version, bundle)
        effective_range = splitting.resolve_effective_range(
            bundle,
            rules.get("event_start"),
            rules.get("event_end"),
            float(rules.get("keep_event_buffer") or 0.0),
        )
        windows = splitting.build_time_windows(
            duration=bundle.duration,
            sample_rate=bundle.sample_rate,
            window_seconds=window_seconds,
            stride_seconds=stride_seconds,
            event_bounds=(effective_range["start"], effective_range["end"]),
            tail_policy=tail_policy,
        )
    except splitting.SplitInputError as exc:
        return err(40000, str(exc), status=400)

    # ── "所见即所得"闸门：预览之后源数据/标定变了就不能照切 ─────────────
    if splitting.rules_hash(rules) != token.get("rules_hash"):
        return err(40900, "切分规则已变更，请重新预览后再创建任务", status=409)
    if splitting.mapping_hash(mapping) != token.get("mapping_hash"):
        return err(40900, "标定或坐标映射已变更，请重新预览后再创建任务", status=409)
    token_bounds = [round(float(x), 6) for x in (token.get("event_bounds") or [])]
    if token_bounds != [round(effective_range["start"], 6), round(effective_range["end"], 6)]:
        return err(40900, "有效事件区间已变更，请重新预览后再创建任务", status=409)

    stored_rules = {
        **rules,
        "rules_version": splitting.RULES_VERSION,
        "window_seconds": window_seconds,
        "stride_seconds": stride_seconds,
        "tail_policy": tail_policy,
        "event_bounds": [effective_range["start"], effective_range["end"]],
        "effective_range_source": effective_range["source"],
        "mapping_hash": splitting.mapping_hash(mapping),
        "sample_rate": bundle.sample_rate,
        "duration": bundle.duration,
        "sample_count": len(windows),
    }
    # `task_format` 对 v3 无意义（§3.4 废弃），故传 None；幂等键随之只依赖版本 + 规则。
    request_key = _split_request_key(version_id, stored_rules, None)
    existing_split = _existing_split_job_uid(session, version_id, stored_rules, None)
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
            rules=stored_rules,
            task_format=None,
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
                "rules_version": splitting.RULES_VERSION,
                "window_seconds": window_seconds,
                "stride_seconds": stride_seconds,
                "tail_policy": tail_policy,
                "sample_count": len(windows),
                "mapping_hash": stored_rules["mapping_hash"],
            },
        )
        session.commit()
    except IntegrityError:
        session.rollback()
        existing_split = _existing_split_job_uid(session, version_id, stored_rules, None)
        if existing_split is not None:
            return ok({"job_id": existing_split})
        raise
    return ok({"job_id": job.job_uid})


@router.get("/split-tasks/{task_id}")
def get_split_task(task_id: str, session: Session = Depends(get_session)) -> dict:
    """切分任务状态/结果（契约 §5.5，轮询 Job 结构）。

    `result` 额外给出 `rules_version` / `schema_version` / `mapping_hash`，供前端区分 v3 与
    历史（≤2）任务——**历史任务只在"历史切分任务"里只读展示，不在新页面伪装成新格式**
    （设计 §3.4）。
    """
    job = get_job_by_uid(session, task_id)
    if job is None:
        return err(40401, "任务不存在", status=404)
    payload = to_job_payload(job)
    task = session.exec(
        select(SplitTask).where(SplitTask.job_id == job.id)
    ).first()
    # 域字段以 split_tasks 行为准（seed 与 handler 都写这里），合并进 result。
    if task is not None:
        result = dict(payload.get("result") or {})
        rules = dict(task.rules or {})
        result["sample_count"] = task.sample_count
        result["rules_version"] = rules.get("rules_version", 1)
        result["schema_version"] = 3 if rules.get("rules_version") == splitting.RULES_VERSION else None
        result["mapping_hash"] = rules.get("mapping_hash")
        payload["result"] = result
    return ok(payload)


@router.get("/split-tasks/{task_id}/samples")
def list_split_samples(
    task_id: str,
    page: int = 1,
    page_size: int = 20,
    session: Session = Depends(get_session),
) -> dict:
    """任务样本分页（契约 §5.5）。

    **不返回完整高频时序数组或大尺寸图片**——列表只给时间窗与各模态**摘要**，否则几百个
    切片时首屏必然失控。高频数据与完整 manifest 走单样本详情端点按需取。
    """
    task = annotation.resolve_split_task(session, task_id)
    if task is None:
        return err(40401, "任务不存在", status=404)
    page = max(1, int(page))
    page_size = max(1, min(100, int(page_size)))
    total = session.exec(
        select(func.count()).select_from(Sample).where(Sample.split_task_id == task.id)
    ).one()
    rows = session.exec(
        select(Sample)
        .where(Sample.split_task_id == task.id)
        # 按时间窗排序（v3 的 `start_time` 就是窗口起点）；历史任务该列为 NULL，回落到 id
        .order_by(Sample.start_time, Sample.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return ok(paginate(
        [_split_sample_payload(row) for row in rows], int(total), page, page_size
    ))


@router.get("/split-tasks/{task_id}/samples/{sample_id}")
def get_split_sample(
    task_id: str,
    sample_id: int,
    session: Session = Depends(get_session),
) -> dict:
    """单样本详情（契约 §5.5）：时间窗、各模态摘要、**该窗内的时序局部数据**。

    高频时序只在这里按需返回且已降采样（≤600 点/通道）；切片产物（图片/CSV）只给对象键，
    由前端换预签名 URL 按需下载——**不把媒体字节塞进 JSON**。
    """
    task = annotation.resolve_split_task(session, task_id)
    if task is None:
        return err(40401, "任务不存在", status=404)
    sample = session.get(Sample, sample_id)
    if sample is None or sample.split_task_id != task.id:
        return err(40401, "样本不存在或不属于该任务", status=404)
    payload = _split_sample_payload(sample)
    payload["meta"] = sample.meta
    payload["time_series"] = _sample_time_series(session, task, sample)
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
    task_format: str | None,
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



def _split_request_key(version_id: int, rules: dict, task_format: str | None) -> str:
    import hashlib
    import json

    payload = {"version_id": version_id, "rules": rules, "task_format": task_format}
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ── 分段：规则 / 样本载荷 ────────────────────────────────────────────

#: 单样本详情里的时序局部数据上限（点/通道）。
_SAMPLE_DETAIL_POINTS = 600


def _split_rules(
    body: SplitPreviewRequest,
    window_seconds: float,
    stride_seconds: float,
    tail_policy: str,
    bundle,
) -> dict:
    """进 `preview_token` 与 `split_tasks.rules` 的规则原文（**秒是唯一基准**）。"""
    return {
        "rules_version": splitting.RULES_VERSION,
        "window_seconds": window_seconds,
        "stride_seconds": stride_seconds,
        "tail_policy": tail_policy,
        "keep_event_buffer": float(body.keep_event_buffer or 0.0),
        "event_start": body.event_start,
        "event_end": body.event_end,
        "sample_rate": bundle.sample_rate,
        "duration": float(bundle.duration),
    }


def _split_sample_payload(sample) -> dict:
    """样本摘要（供列表）。**不含完整 `meta`**——几百条切片带完整 manifest 会撑爆列表响应。"""
    meta = sample.meta or {}
    schema_version = meta.get("schema_version")
    payload = {
        "id": sample.id,
        "frame_no": sample.frame_no,
        "start_time": sample.start_time,
        "end_time": sample.end_time,
        "schema_version": schema_version,
        "object_keys": list(sample.object_keys or []),
        "modalities": {},
    }
    # v3 才有统一的多模态结构；历史样本（≤2）的 meta 是旧形状，不硬套
    if schema_version == 3:
        payload["modalities"] = {
            key: {
                "available": bool((meta.get(key) or {}).get("available")),
                "calibrated": bool((meta.get(key) or {}).get("calibrated")),
                "reason": (meta.get(key) or {}).get("reason"),
            }
            for key in ("signal", "video", "seam_image", "audio")
        }
    return payload


def _sample_time_series(session: Session, task, sample) -> list[dict]:
    """该窗口内的时序局部数据（降采样，≤`_SAMPLE_DETAIL_POINTS` 点/通道）。

    读不到信号时返回空列表——详情页仍应能打开，只是明确标出波形不可用。
    """
    if sample.start_time is None or sample.end_time is None:
        return []
    version = session.get(DataVersion, task.version_id)
    record = session.get(DataRecord, version.record_id) if version is not None else None
    if record is None:
        return []
    try:
        bundle = splitting.load_input(session, record, version)
    except splitting.SplitInputError as exc:
        logger.warning("Split sample detail: signal unavailable: {}", exc)
        return []
    fs = int(bundle.sample_rate)
    i0 = max(0, math.ceil(float(sample.start_time) * fs))
    i1 = max(i0, math.floor(float(sample.end_time) * fs))
    tracks = []
    for channel in bundle.channels:
        values = channel.values[i0:i1]
        idx = signals.downsample_indices(values, _SAMPLE_DETAIL_POINTS) if len(values) else []
        tracks.append({
            "id": channel.id,
            "name": channel.name,
            "unit": channel.unit,
            "times": [round((i0 + int(i)) / fs, 6) for i in idx],
            "values": [round(float(values[int(i)]), 6) for i in idx],
        })
    return tracks


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


def _series_range(values) -> tuple[float, float, float]:
    """序列的 `(lo, hi, mean)`，量程按数据自身 min/max 加 5% 余量（`mean` 保留 2 位）。

    用途：滤波后的量程/均值回填。核心通道的原始量程固定在 `CHANNEL_SPECS`（电流 0–600、
    电压 0–700），对滤波后信号不再成立——高通/带通去均值后按原始量程绘制会贴边成直线，
    PDD 直方图会全挤进首 bin。与 `signal_ingest._data_range` 同口径。
    """
    arr = np.asarray(values, dtype=float)
    if arr.size == 0:
        return 0.0, 1.0, 0.0
    mean = round(float(np.mean(arr)), 2)
    lo = float(np.min(arr))
    hi = float(np.max(arr))
    if hi <= lo:  # 常值序列：防除零，给一个可见量程
        pad = max(abs(hi) * 0.05, 1.0)
        return lo - pad, hi + pad, mean
    pad = (hi - lo) * 0.05
    return lo - pad, hi + pad, mean
