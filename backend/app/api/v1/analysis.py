"""analysis 域路由（Task 11 + Task 12）：分析候选 / 多通道信号 / 真实 DSP 六模式 /
分析结果 / 特征提取。

端点契约见 `docs/API接口清单.md` §3.4；全部需登录（router 级 `Depends(get_current_user)`），
返回统一 `ok(...)` / `err(...)` 信封；信号由 `app.services.signals` 确定性生成、
DSP 由 `app.services.dsp` 真实计算（scipy/pywt/numpy，非罐头数字）。

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
from sqlmodel import Session

from app.api.deps import get_current_user
from app.core.db import get_session
from app.models.analysis import FeatureExtraction
from app.schemas.common import err, ok
from app.services import dsp, features, signals
from app.services import welds as svc
from app.services.jobs import _iso_utc
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
