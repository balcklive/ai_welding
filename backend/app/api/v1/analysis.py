"""analysis 域路由（Task 11 + Task 12 + Task 13）：分析候选 / 多通道信号 / 真实 DSP
六模式 / 分析结果 / 特征提取 / 对齐任务。

端点契约见 `docs/API接口清单.md` §3.4；全部需登录（router 级 `Depends(get_current_user)`），
返回统一 `ok(...)` / `err(...)` 信封；信号由 `app.services.signals` 确定性生成、
DSP 由 `app.services.dsp` 真实计算（scipy/pywt/numpy，非罐头数字）。

Task 13：对齐任务走异步 Job——`POST …/alignment-tasks` 建 pending Job + `alignment_tasks`
行（同事务 commit）返回 `{job_id}`；后台执行器（`app.jobs`，lifespan 启动）跑 handler
（`app.jobs.alignment`，模拟对齐 + 自动生成「时间对齐」版本 + 更新 latest_version_id）；
`GET /alignment-tasks/{task_id}` 返回 Job 信封（result 内嵌 events/tracks/assets）。

错误码约定（与 welds 域一致）：40401=焊缝/登记不存在、40402=版本不存在、40000=参数错误。

注意（坑）：
- `channels` 查询参数兼容 `channels[]=cur&channels[]=vol` 与 `channels=cur&channels=vol`
  两种写法——FastAPI 的 `Query` 只绑定其中一种 key，故从 `request.query_params` 手读合并。
- `analysis/result` 是**具体路径**，必须在 `analysis/{mode}` 之前注册，否则会被
  `mode="result"` 吞掉（FastAPI 按注册顺序匹配）。
- 滤波参数 `cutoff/cutoff2` 为 0~1 归一化频率（相对奈奎斯特），`带通` 需两者。
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlmodel import Session, select

from app.api.deps import get_current_user
from app.core.db import get_session
from app.models.analysis import AlignmentTask, FeatureExtraction
from app.schemas.common import err, ok
from app.services import dsp, features, signals
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


class ExtractFeaturesRequest(BaseModel):
    """POST /features/extract 请求体（契约 §3.4）。"""

    weld_id: str
    version_id: int
    normalization: str = "无"
    format: str = "JSON"


class AlignmentTaskCreate(BaseModel):
    """POST …/alignment-tasks 请求体（契约 §3.4）。`modalities[]` 空时由服务端按焊缝登记模态兜底。"""

    modalities: list[str] = []


# ── 分析候选 ──────────────────────────────────────────────────────────


@router.get("/analysis/candidates")
def list_candidates(session: Session = Depends(get_session)) -> dict:
    """选择数据页：已登记且核验通过（quality=通过）的可分析数据列表（最小载荷）。"""
    records = svc.list_through_welds(session)
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
    session: Session = Depends(get_session),
) -> dict:
    """多通道时域波形（电流/电压/气体/送丝）。query `channels[]`、滤波参数可选。

    滤波给定则对选中通道真实滤波（dsp.filter_signal）。返回
    `{duration, sample_rate, channels:[{id,name,unit,values[],lo,hi,mean}], events, anomalies}`。
    """
    resolved = _resolve_weld_version(session, weld_id, version_id)
    if resolved is not None:
        return resolved
    if msg := _filter_error(filter_type, cutoff, cutoff2):
        return err(40000, msg, status=400)

    bundle = signals.generate_signals(weld_id, sample_rate=_DEFAULT_SAMPLE_RATE)
    channel_ids = _requested_channels(request)
    for cid in channel_ids:
        if bundle.channel(cid) is None:
            return err(40000, f"未知通道: {cid}", status=400)

    fs = bundle.sample_rate
    payload_channels = []
    for chan in bundle.channels:
        if channel_ids and chan.id not in channel_ids:
            continue
        values = chan.values
        if filter_type:
            values = dsp.filter_signal(values, fs, filter_type, cutoff, cutoff2)
        payload_channels.append(
            {
                "id": chan.id,
                "name": chan.name,
                "unit": chan.unit,
                "values": values.tolist(),
                "lo": chan.lo,
                "hi": chan.hi,
                "mean": chan.mean,
            }
        )

    return ok(
        {
            "duration": bundle.duration,
            "sample_rate": bundle.sample_rate,
            "channels": payload_channels,
            "events": bundle.events,
            "anomalies": bundle.anomalies,
        }
    )


# ── 分析结果（具体路径，先于 {mode} 注册） ─────────────────────────────


@router.get("/welds/{weld_id}/versions/{version_id}/analysis/result")
def get_analysis_result(
    weld_id: str,
    version_id: int,
    session: Session = Depends(get_session),
) -> dict:
    """AI 异常检测结果：焊接稳定度、正常/电弧不稳/飞溅占比、异常区段列表。

    确定性模拟结果（源自信号生成器的事件/异常区段，seeded by weld_id）。
    """
    resolved = _resolve_weld_version(session, weld_id, version_id)
    if resolved is not None:
        return resolved
    bundle = signals.generate_signals(weld_id, sample_rate=_DEFAULT_SAMPLE_RATE)
    return ok(signals.analysis_result(bundle))


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
) -> dict:
    """单视图分析数据：mode ∈ psd|stft|dwt|wavelet|phase|pdd。

    query `channel`（默认 cur）+ 可选滤波参数（滤波后计算，与信号页联动）。
    未知 mode → 400。phase 需要 cur+vol 两通道，滤波同时作用于两者。
    """
    if mode == "result":  # 防御：/analysis/result 已由具体路由接管
        return err(40000, "未知分析模式: result", status=400)
    resolved = _resolve_weld_version(session, weld_id, version_id)
    if resolved is not None:
        return resolved
    if msg := _filter_error(filter_type, cutoff, cutoff2):
        return err(40000, msg, status=400)

    bundle = signals.generate_signals(weld_id, sample_rate=_DEFAULT_SAMPLE_RATE)
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
) -> dict:
    """执行特征提取（**同步**，契约 §3.4）：时序/视觉/声音特征 + 统一向量 → 落库。

    生成确定性信号 → `features.ts_features` 逐通道（8×4）→ `vision_features`
    （8）→ `generate_audio` + `audio_features`（6）→ `unify` 拼 42 维归一化向量，
    写 `feature_extractions` 行（含 created_at），返回 `ok(extraction)`。
    """
    if body.normalization not in _NORMALIZATIONS:
        return err(
            40000,
            f"normalization 需为 {'/'.join(sorted(_NORMALIZATIONS))}",
            status=400,
        )
    if body.format not in _FORMATS:
        return err(40000, f"format 需为 {'/'.join(sorted(_FORMATS))}", status=400)
    resolved = _resolve_weld_version(session, body.weld_id, body.version_id)
    if resolved is not None:
        return resolved

    bundle = signals.generate_signals(body.weld_id, sample_rate=_DEFAULT_SAMPLE_RATE)
    ts: dict[str, dict] = {}
    for chan in bundle.channels:
        ts[chan.id] = features.ts_features(chan.values, fs=bundle.sample_rate)
    vis = features.vision_features()
    audio, audio_fs = features.generate_audio(body.weld_id)
    audio_feats = features.audio_features(audio, audio_fs)
    unified = features.unify(ts, vis, audio_feats, body.normalization, body.format)

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
    session.commit()
    session.refresh(extraction)
    return ok(_extraction_payload(extraction))


@router.get("/features/{extraction_id}")
def get_feature_extraction(
    extraction_id: int,
    session: Session = Depends(get_session),
) -> dict:
    """特征提取结果（导出时使用，契约 §3.4）→ `ok(extraction)`。"""
    extraction = session.get(FeatureExtraction, extraction_id)
    if extraction is None:
        return err(40401, "特征提取记录不存在", status=404)
    return ok(_extraction_payload(extraction))


# ── 对齐任务（Task 13：异步 Job，执行器在后台跑 handler） ───────────────


@router.post("/welds/{weld_id}/versions/{version_id}/alignment-tasks")
def create_alignment_task(
    weld_id: str,
    version_id: int,
    body: AlignmentTaskCreate,
    session: Session = Depends(get_session),
) -> dict:
    """提交多模态对齐任务（**异步**，契约 §3.4）：建 pending Job + `alignment_tasks` 行。

    同事务 commit，返回 `{job_id}`（job_uid）。成功后（后台执行器）自动生成
    `action=时间对齐` 版本并更新 `latest_version_id`。
    """
    record = svc.get_record_by_weld_id(session, weld_id)
    if record is None:
        return err(40401, "焊缝不存在", status=404)
    version = svc.get_version(session, version_id)
    if version is None or version.record_id != record.id:
        return err(40402, "版本不存在", status=404)
    job = create_job(session, type="alignment")
    task = AlignmentTask(
        job_id=job.id,
        version_id=version.id,
        modalities=list(body.modalities),
    )
    session.add(task)
    session.commit()
    return ok({"job_id": job.job_uid})


@router.get("/alignment-tasks/{task_id}")
def get_alignment_task(
    task_id: str,
    session: Session = Depends(get_session),
) -> dict:
    """对齐任务状态/结果（契约 §3.4，轮询 Job 结构）：Job 信封，`result` 内嵌
    `events`/`tracks`/`assets`（对齐产物对象键，前端经 `files.getFileUrl` 播放）。"""
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


# ── 内部助手 ──────────────────────────────────────────────────────────


def _resolve_weld_version(session: Session, weld_id: str, version_id: int) -> dict | None:
    """按 weld_id + version_id 解析焊缝与版本；缺任一返回 err 信封，否则 None。"""
    record = svc.get_record_by_weld_id(session, weld_id)
    if record is None:
        return err(40401, "焊缝不存在", status=404)
    version = svc.get_version(session, version_id)
    if version is None or version.record_id != record.id:
        return err(40402, "版本不存在", status=404)
    return None


def _extraction_payload(e: FeatureExtraction) -> dict:
    """FeatureExtraction → JSON 载荷（created_at 复用 jobs._iso_utc 序列化）。"""
    return {
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
