"""analysis 域路由（Task 11 ~ Task 14）：分析候选 / 多通道信号 / 真实 DSP 六模式 /
分析结果 / 特征提取 / 对齐任务 / 切分任务 / 标注。

端点契约见 `docs/API接口清单.md` §3.4；全部需登录（router 级 `Depends(get_current_user)`），
返回统一 `ok(...)` / `err(...)` 信封；信号由 `app.services.signals` 确定性生成、
DSP 由 `app.services.dsp` 真实计算（scipy/pywt/numpy，非罐头数字）。

Task 13：对齐任务走异步 Job——`POST …/alignment-tasks` 建 pending Job + `alignment_tasks`
行（同事务 commit）返回 `{job_id}`；后台执行器（`app.jobs`，lifespan 启动）跑 handler
（`app.jobs.alignment`，模拟对齐 + 自动生成「时间对齐」版本 + 更新 latest_version_id）；
`GET /alignment-tasks/{task_id}` 返回 Job 信封（result 内嵌 events/tracks/assets）。

Task 14：切分/标注（实施边界 §3.1 = 真实异步编排 + 模拟结果）：
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
    AnnotationTask,
    FeatureExtraction,
    LabelCategory,
    Sample,
    SplitTask,
)
from app.models.data import User
from app.schemas.common import err, ok, paginate
from app.services import annotation, dsp, features, signal_ingest, signals
from app.services import welds as svc
from app.services.jobs import (
    _iso_utc,
    create_job,
    get_job_by_uid,
    to_job_payload,
)
from app.services.signals import CHANNEL_SPECS

router = APIRouter(dependencies=[Depends(get_current_user)])

_FILTER_TYPES = {"低通", "高通", "带通"}
_DEFAULT_SAMPLE_RATE = 1000
_NORMALIZATIONS = {"Z-Score", "Min-Max", "L2", "无"}
_FORMATS = {"NPY", "CSV", "JSON", "PT"}
#: 切分任务格式 / 标注来源 / 导入来源白名单（契约 §3.4）。
_SPLIT_FORMATS = {"目标检测", "图像分类", "语义分割", "时序分类"}
#: 标注来源：split_task=切分样本 / manual=手动 / signal=时序信号（信号锚点样本，供波形区间标注）/
#: video=熔池视频（视频锚点样本 + 帧样本，供多边形区域标注）。
_ANNOTATION_SOURCES = {"split_task", "manual", "signal", "video"}
_IMPORT_SOURCES = {"files", "split_task"}
#: 视频扩展名（识别版本 object_keys 里的可标注视频）。
_VIDEO_EXTENSIONS = (".mp4", ".avi", ".mkv", ".mov", ".webm")


def _is_video_key(key: str) -> bool:
    return key.lower().endswith(_VIDEO_EXTENSIONS)


def _browser_friendly_video_key(session: Session, video_key: str) -> str:
    """视频原始 key → 浏览器可播放的 key（media_prep 转码预览版优先）。

    查该 object_key 最新一条 succeeded 的 media_prep Job（登记挂载视频时自动创建，
    转码预览版写 `processed/{weld_id}/video/`；结果 JSON 里带 object_key/preview_key）。
    未转码 / 已转码原始即浏览器友好（preview_key==object_key）/ 查询失败一律回退原始 key。
    数量级小（每个视频一条 job），结果 JSON 在 Python 侧解析，跨 MySQL/SQLite 可用。
    """
    try:
        preps = session.exec(
            select(Job)
            .where(Job.type == "media_prep", Job.status == "succeeded")
            .order_by(Job.id.desc())
        ).all()
    except Exception:  # noqa: BLE001 - 查询异常不阻塞锚点创建，回退原始 key
        return video_key
    for prep in preps:
        result = prep.result or {}
        if result.get("object_key") == video_key:
            preview = result.get("preview_key")
            return preview if isinstance(preview, str) and preview else video_key
    return video_key


class ExtractFeaturesRequest(BaseModel):
    """POST /features/extract 请求体（契约 §3.4）。"""

    weld_id: str
    version_id: int
    normalization: str = "无"
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


class AnnotationTaskCreate(BaseModel):
    """POST /annotation-tasks 请求体（契约 §3.4）。`source` 必填；从切分样本需给 `split_task_id`；`signal` 需给 `version_id`。"""

    source: str
    split_task_id: str | None = None
    version_id: int | None = None
    name: str | None = None


class AnnotationImportRequest(BaseModel):
    """POST /annotation-tasks/{task_id}/import 请求体（契约 §3.4）。"""

    source: str
    object_keys: list[str] | None = None
    split_task_id: str | None = None


class LabelItem(BaseModel):
    """单条标注：类别 + 几何（按 `kind` 分支）+ 可选置信度（缺省沿用先前 AI 预标注值）。

    - kind=box（默认）：`box` = [x, y, w, h] 目标检测框；
    - kind=segment：`start_time`/`end_time` = 时序区间起点/终点（秒）；
    - kind=polygon：`points` = 多边形顶点 [[x,y],…]（≥3）。
    """

    category: str
    kind: str = "box"
    box: list | None = None
    points: list | None = None
    start_time: float | None = None
    end_time: float | None = None
    confidence: float | None = None


class SaveLabelsRequest(BaseModel):
    """POST …/labels 请求体（契约 §3.4）：`labels[]` 覆盖写样本标注。"""

    labels: list[LabelItem]


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


# ── 切分任务（Task 14：异步 Job，handler 按规则生成样本） ───────────────


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
    resolved = _resolve_weld_version(session, weld_id, version_id)
    if resolved is not None:
        return resolved

    record = svc.get_record_by_weld_id(session, weld_id)
    assert record is not None  # resolved above
    version = svc.get_version(session, version_id)
    assert version is not None  # resolved above
    if msg := _split_input_error(record, version):
        return err(40000, msg, status=400)

    rules = {
        "fixed_rate": body.fixed_rate,
        "stride": stride,
        "keep_event_buffer": body.keep_event_buffer,
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


# ── 标注（Task 14：异步任务创建 + 同步预标注/保存） ─────────────────────


@router.get("/label-categories")
def list_label_categories(session: Session = Depends(get_session)) -> dict:
    """缺陷标签类别（模型口径 6 类，契约 §3.4）：焊瘤/气孔/未熔合/咬边/正常 + 熔池（视频语义分割单类）。"""
    return ok(annotation.list_label_categories(session))


@router.post("/annotation-tasks")
def create_annotation_task(
    body: AnnotationTaskCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """创建标注任务（**异步**，契约 §3.4）：建 pending Job + `annotation_tasks` 行。

    同事务 commit，返回 `{job_id}`。成功后（后台执行器）若来源为 split_task，
    把该切分任务的样本 `annotation_task_id` 指向本任务；`signal` 来源在创建时同步
    生成 1 个信号锚点样本（`meta.mode='signal'`，波形区间标注的挂载点）；`video`
    来源同步生成 1 个视频锚点样本（`meta.mode='video'` + `video_key`，多边形区域标注
    的视频播放挂载点，帧样本经 `POST …/frames` 追加）。
    """
    if body.source not in _ANNOTATION_SOURCES:
        return err(
            40000,
            f"source 需为 {'/'.join(sorted(_ANNOTATION_SOURCES))}",
            status=400,
        )
    split_id = None
    if body.source == "split_task":
        split = annotation.resolve_split_task(session, body.split_task_id or "")
        if split is None:
            return err(40401, "切分任务不存在", status=404)
        split_id = split.id
    signal_anchor: dict | None = None
    video_anchor: dict | None = None
    if body.source == "signal":
        if body.version_id is None:
            return err(40000, "signal 来源需提供 version_id", status=400)
        version = session.get(DataVersion, body.version_id)
        if version is None:
            return err(40402, "版本不存在", status=404)
        record = session.get(DataRecord, version.record_id)
        signal_anchor = {
            "weld_id": record.weld_id if record is not None else None,
            "version_id": body.version_id,
        }
    elif body.source == "video":
        if body.version_id is None:
            return err(40000, "video 来源需提供 version_id", status=400)
        version = session.get(DataVersion, body.version_id)
        if version is None:
            return err(40402, "版本不存在", status=404)
        record = session.get(DataRecord, version.record_id)
        video_key = next(
            (k for k in (version.object_keys or []) if _is_video_key(k)), None
        )
        if video_key is None:
            return err(40000, "所选版本不包含可标注视频", status=400)
        video_anchor = {
            "weld_id": record.weld_id if record is not None else None,
            "version_id": body.version_id,
            # 原始视频常为浏览器不可解码编码（如 mpeg4）：媒体预处理（media_prep job）
            # 转出的 H.264+faststart 预览版优先；未转码/转码失败回退原始 key
            # （前端 <video> onError 有明确不可播提示）。
            "video_key": _browser_friendly_video_key(session, video_key),
            "source_video_key": video_key,
        }

    job = create_job(session, type="annotation")
    task = AnnotationTask(
        job_id=job.id,
        split_task_id=split_id,
        name=body.name,
        source=body.source,
        created_at=datetime.now(timezone.utc),
    )
    session.add(task)
    if signal_anchor is not None:
        session.flush()  # 分配 task.id
        session.add(
            Sample(
                annotation_task_id=task.id,
                meta={"mode": "signal", "source": "signal-anchor", **signal_anchor},
            )
        )
    if video_anchor is not None:
        session.flush()  # 分配 task.id
        session.add(
            Sample(
                annotation_task_id=task.id,
                meta={"mode": "video", "source": "video-anchor", **video_anchor},
            )
        )
    write_audit(
        session,
        current_user.id,
        "create",
        "annotation_task",
        job.job_uid,
        {
            "source": body.source,
            "split_task_id": body.split_task_id,
            "version_id": body.version_id,
            "name": body.name,
        },
    )
    session.commit()
    return ok({"job_id": job.job_uid})


@router.get("/annotation-tasks/{task_id}")
def get_annotation_task(task_id: str, session: Session = Depends(get_session)) -> dict:
    """标注任务整体状态/进度（契约 §3.4，轮询 Job 结构）。`task_id` 为 job_uid。"""
    job = get_job_by_uid(session, task_id)
    if job is None:
        return err(40401, "任务不存在", status=404)
    return ok(to_job_payload(job))


@router.post("/annotation-tasks/{task_id}/import")
def import_annotation_samples(
    task_id: str,
    body: AnnotationImportRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """导入额外样本到标注任务（契约 §3.4）。`task_id` 兼容 job_uid 与 DB id。

    - source=`files`：按 `object_keys[]` 建新 `Sample` 行；
    - source=`split_task`：把该切分任务的样本改指本任务。
    返回 `ok({imported})`。
    """
    if body.source not in _IMPORT_SOURCES:
        return err(
            40000,
            f"source 需为 {'/'.join(sorted(_IMPORT_SOURCES))}",
            status=400,
        )
    task = annotation.resolve_annotation_task(session, task_id)
    if task is None:
        return err(40401, "标注任务不存在", status=404)
    if body.source == "files" and not body.object_keys:
        return err(40000, "files 导入需提供 object_keys[]", status=400)
    if body.source == "split_task":
        if not body.split_task_id or annotation.resolve_split_task(
            session, body.split_task_id
        ) is None:
            return err(40401, "切分任务不存在", status=404)
    try:
        imported = annotation.import_samples(
            session, task, body.source, body.object_keys, body.split_task_id
        )
    except ValueError as exc:  # noqa: BLE001 - 未知来源等由服务抛出的业务错误
        return err(40000, str(exc), status=400)
    write_audit(
        session,
        current_user.id,
        "update",
        "annotation_task",
        task_id,
        {"source": body.source, "imported": imported},
    )
    session.commit()
    return ok({"imported": imported})


@router.get("/annotation-tasks/{task_id}/samples")
def list_annotation_samples(
    task_id: str,
    page: int = 1,
    page_size: int = 20,
    session: Session = Depends(get_session),
) -> dict:
    """标注样本列表（契约 §3.4，分页）：每样本含 annotations[] 与样本级 confidence。"""
    task = annotation.resolve_annotation_task(session, task_id)
    if task is None:
        return err(40401, "标注任务不存在", status=404)
    page = max(1, page)
    page_size = min(max(1, page_size), 100)  # §1.4：page_size 最大 100
    items, total = annotation.list_samples(session, task, page, page_size)
    return ok(paginate(items, total, page, page_size))


@router.get("/annotation-tasks/{task_id}/samples/{sample_id}")
def get_annotation_sample(
    task_id: str,
    sample_id: int,
    session: Session = Depends(get_session),
) -> dict:
    """单个样本详情（契约 §3.4）：样本 + 最新标注 + 样本级 `confidence`。"""
    task = annotation.resolve_annotation_task(session, task_id)
    if task is None:
        return err(40401, "标注任务不存在", status=404)
    payload = annotation.get_sample_detail(session, task, sample_id)
    if payload is None:
        return err(40401, "样本不存在或不属于该任务", status=404)
    return ok(payload)


@router.post("/annotation-tasks/{task_id}/samples/{sample_id}/ai-pretag")
def ai_pretag_sample(
    task_id: str,
    sample_id: int,
    session: Session = Depends(get_session),
) -> dict:
    """AI 预标注（**同步**，契约 §3.4）：确定性模拟 2 个疑似区域 + 置信度，**替换**现有标注。

    seed = `sample_id` → 同样本每次结果一致。落库（annotator=AI预标注），前端随后
    `POST …/labels` 覆盖写为人工标注。
    """
    task = annotation.resolve_annotation_task(session, task_id)
    if task is None:
        return err(40401, "标注任务不存在", status=404)
    sample = annotation.get_sample(session, task, sample_id)
    if sample is None:
        return err(40401, "样本不存在或不属于该任务", status=404)
    new_annotations = annotation.pretag_sample(session, task, sample)
    session.commit()
    return ok([annotation.annotation_payload(a) for a in new_annotations])


@router.post("/annotation-tasks/{task_id}/samples/{sample_id}/labels")
def save_annotation_labels(
    task_id: str,
    sample_id: int,
    body: SaveLabelsRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """保存/更新标注（**同步**，契约 §3.4）：`labels[]` 覆盖写样本标注，annotator=当前用户。

    类别必须在 label_categories（400）；confidence 缺省沿用先前（AI 预标注）同类别值。
    写审计（`update`）后提交。
    """
    task = annotation.resolve_annotation_task(session, task_id)
    if task is None:
        return err(40401, "标注任务不存在", status=404)
    sample = annotation.get_sample(session, task, sample_id)
    if sample is None:
        return err(40401, "样本不存在或不属于该任务", status=404)
    cats = {c.name for c in session.exec(select(LabelCategory)).all()}
    for label in body.labels:
        if label.category not in cats:
            return err(40000, f"未知标签类别: {label.category}", status=400)
        # 按 kind 分支校验几何字段（box/segment/polygon），未知 kind → 400。
        kind = label.kind
        if kind == "box":
            box = label.box
            if not (
                isinstance(box, list)
                and len(box) == 4
                and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in box)
            ):
                return err(40000, "box 需为 [x, y, w, h] 数值数组", status=400)
        elif kind == "segment":
            start, end = label.start_time, label.end_time
            if (
                start is None
                or end is None
                or isinstance(start, bool)
                or isinstance(end, bool)
                or not (0 <= start < end)
            ):
                return err(40000, "segment 需 start_time/end_time 且 0 <= start < end（秒）", status=400)
        elif kind == "polygon":
            points = label.points
            if not (
                isinstance(points, list)
                and len(points) >= 3
                and all(
                    isinstance(p, list)
                    and len(p) == 2
                    and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in p)
                    for p in points
                )
            ):
                return err(40000, "polygon 需 points 至少 3 个 [x, y] 顶点", status=400)
        else:
            return err(40000, f"未知标注类型 kind: {kind}", status=400)
        # confidence 列是 Numeric(4,3)，越界（如 >=10）会触发 MySQL DataError → 500；
        # 给定时必须在 [0,1]，否则 400（不落库）。
        conf = label.confidence
        if conf is not None and not (0 <= conf <= 1):
            return err(40000, "置信度需在 0~1 之间", status=400)

    new_annotations = annotation.save_labels(
        session, task, sample, body.labels, _operator(current_user)
    )
    write_audit(
        session,
        current_user.id,
        "update",
        "annotation",
        f"{task_id}/{sample_id}",
        {"labels": [l.category for l in body.labels]},
    )
    session.commit()
    return ok([annotation.annotation_payload(a) for a in new_annotations])


class AnnotationFrameCreate(BaseModel):
    """POST /annotation-tasks/{task_id}/frames 请求体（视频标注帧锚点）。

    `frame_width`/`frame_height` 为捕获帧的像素尺寸（视频自然分辨率），导出掩膜时据此
    把多边形像素坐标缩放到 ffmpeg 抽帧实际尺寸。
    """

    timestamp: float
    frame_width: int | None = None
    frame_height: int | None = None


@router.post("/annotation-tasks/{task_id}/frames")
def create_annotation_frame(
    task_id: str,
    body: AnnotationFrameCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """为视频标注任务创建帧样本锚点（`meta.mode='frame'` + `timestamp`），**同步**。

    weld_id/version_id/video_key 从任务的视频锚点样本（`meta.mode='video'`）继承；
    之后前端用既有 `POST …/samples/{sample_id}/labels`（kind='polygon'）给该帧保存多边形。
    写审计（`create`）后提交，返回 `{sample_id}`。
    """
    task = annotation.resolve_annotation_task(session, task_id)
    if task is None:
        return err(40401, "标注任务不存在", status=404)
    if task.source != "video":
        return err(40000, "仅视频标注任务可创建帧样本", status=400)
    ts = body.timestamp
    if isinstance(ts, bool) or not isinstance(ts, (int, float)) or ts < 0:
        return err(40000, "timestamp 需为非负数值（秒）", status=400)
    fw, fh = body.frame_width, body.frame_height
    if (fw is not None and (not isinstance(fw, int) or fw <= 0)) or (
        fh is not None and (not isinstance(fh, int) or fh <= 0)
    ):
        return err(40000, "frame_width/frame_height 需为正整数", status=400)
    anchors = session.exec(
        select(Sample).where(Sample.annotation_task_id == task.id)
    ).all()
    video_meta = next(
        ((s.meta or {}) for s in anchors if (s.meta or {}).get("mode") == "video"), {}
    )
    if not video_meta.get("video_key"):
        return err(40000, "视频标注任务缺少有效视频锚点", status=400)
    sample = Sample(
        annotation_task_id=task.id,
        meta={
            "mode": "frame",
            "timestamp": ts,
            "weld_id": video_meta.get("weld_id"),
            "version_id": video_meta.get("version_id"),
            "video_key": video_meta.get("video_key"),
            "frame_width": fw,
            "frame_height": fh,
        },
    )
    session.add(sample)
    session.flush()
    write_audit(
        session,
        current_user.id,
        "create",
        "annotation_sample",
        f"{task_id}/frame",
        {"timestamp": ts},
    )
    session.commit()
    return ok({"sample_id": sample.id})


@router.post("/annotation-tasks/{task_id}/export")
def export_annotation_artifacts(
    task_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """导出标注产物（**同步**）：video → 帧图+掩膜 PNG；signal → segment JSON 标签。

    写 MinIO `processed/{weld_id}/annotate/...`，返回 `{type, count, items}`。
    写审计（`export`）后提交。
    """
    task = annotation.resolve_annotation_task(session, task_id)
    if task is None:
        return err(40401, "标注任务不存在", status=404)
    from app.storage import get_storage  # noqa: PLC0415 - 延迟导入便于测试 monkeypatch

    storage = get_storage()
    try:
        result = annotation.export_annotations(session, task, storage)
    except ValueError as exc:
        # 不支持来源（如 manual）→ 400
        return err(40000, str(exc), status=400)
    except Exception as exc:  # noqa: BLE001 - 导出失败统一 500，不泄漏内部异常
        logger.warning("[annotation.export] Export failed: task_id={} err={}", task_id, exc)
        return err(50000, "标注导出失败", status=500)
    write_audit(
        session,
        current_user.id,
        "export",
        "annotation",
        task_id,
        {"type": result.get("type"), "count": result.get("count")},
    )
    session.commit()
    return ok(result)


# ── 内部助手 ──────────────────────────────────────────────────────────


def _operator(user: User) -> str:
    """服务端取当前登录用户作 annotator/operator（优先展示名，对齐 seed 林工）。"""
    return user.display_name or user.username


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

    keys = version.object_keys or []
    image_key = next((k for k in keys if k.lower().endswith((".jpg", ".jpeg", ".png", ".bmp", ".webp"))), None)
    video_key = next((k for k in keys if k.lower().endswith((".mp4", ".mov", ".avi", ".mkv"))), None)
    try:
        storage = get_storage()
        if image_key:
            return features.vision_features_from_image(storage.get_object(image_key)), "real"
        if video_key:
            from app.services.media_probe import analyze_video

            _, frames = analyze_video(storage.get_object(video_key), [("first", 0.0)])
            if frames:
                return features.vision_features_from_image(frames[0]["bytes"]), "real"
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
    available = set(record.modalities or []) if record is not None else set()
    if version is not None:
        available |= set(_derive_modalities_from_keys(version.object_keys or []))
    return {
        "timeseries": "real" if bundle_source == "real" else "generated",
        "vision": "real" if "video" in available or "infrared" in available else "missing",
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


