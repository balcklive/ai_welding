"""Optional Label Studio integration for annotation tasks.

LS is used through its public SDK (v2) / REST. The business database remains
authoritative for Annotation / Sample / task state; all methods are best-effort
so an unavailable LS cannot fail a domain job (same convention as mlflow.py).

KEY FACTS (2026-09-05, verified against real LS):
- LS PAT (personal access token) is a **refresh-type JWT**; a raw
  `Authorization: Token <PAT>` call returns 401. The official `label-studio-sdk`
  (v2) refreshes internally when given `api_key=<PAT>`, so the adapter should use
  the SDK for task/annotation CRUD rather than raw REST.
- Project mapping (by annotation semantics, NOT source string):
  3 = 目标检测 RectangleLabels (4 缺陷类) -> box
  4 = 熔池/视频帧分割 PolygonLabels (单类熔池; 原 BrushLabels 已改) -> polygon
  5 = 时序分段 TimeSeries (区间分段, 4 缺陷类) -> segment
- Region `type` strings (verified via real annotation round-trip):
  RectangleLabels -> `rectanglelabels`; PolygonLabels -> `polygonlabels`;
  TimeSeriesLabels -> `timeserieslabels`. Coords are 0-100 **percentages** relative
  to `original_width`/`original_height`; labels live in `value.<plurallabel>[0]`.
- Media: MinIO presigned GET, expires TTL ≤ 7 天 (SDK refuses > 7 days). Long TTL
  + 适配层对账刷新. Use `storage.presign_get(key, expires)` directly (NOT the
  `/files/url` route which caps at 1 天) so LS can fetch over the annotation session.
- Annotator: `annotation.completed_by` is a dict (`email`/`username`/`id`); also
  `created_username` = "<email>, <id>". Store the email (同名账号约定).
"""

from __future__ import annotations

from loguru import logger
from typing import Any

from app.core.config import settings
from app.models.analysis import Sample


def _client():
    """Return a label-studio-sdk Client, or None when off / unavailable (best-effort)."""
    if settings.label_studio_mode == "off":
        return None
    if not settings.label_studio_internal_url or not settings.label_studio_api_key:
        logger.warning("Label Studio is configured but internal_url/api_key is missing")
        return None
    try:
        from label_studio_sdk import LabelStudio  # uv add label-studio-sdk

        # PAT 是 refresh JWT；SDK 内部自动 refresh 到 access，故传 api_key=<PAT> 即可。
        return LabelStudio(
            base_url=settings.label_studio_internal_url,
            api_key=settings.label_studio_api_key,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Unable to create Label Studio client: {}", exc)
    return None


def project_for(source: str, kind: str) -> int:
    """按标注语义映射到 LS 项目 id（非 source 字符串）。

    - box(目标检测) → 项目 3；polygon(熔池/视频帧分割) → 项目 4；segment(时序区间) → 项目 5。
    未知 kind 抛 ValueError（路由转 400）。
    """
    if kind == "box":
        return settings.ls_project_detection
    if kind == "polygon":
        return settings.ls_project_segmentation
    if kind == "segment":
        return settings.ls_project_timeseries
    raise ValueError(f"无法为 kind={kind!r} 映射 LS 项目（现支持 box/polygon/segment）")


def media_url(storage, object_key: str) -> str:
    """样本可见媒体 → LS task 用的预签名 GET URL。

    长 TTL（`label_studio_presign_expires`，默认 3 天）覆盖标注会话；上限 7 天。
    走 StorageClient._sign_client（公网）——交到浏览器/外部；服务端拉取无需代理。
    """
    expires = max(60, min(settings.label_studio_presign_expires, 604800))  # ≤ 7 天
    return storage.presign_get(object_key, expires=expires)


def media_field_for(kind: str) -> str:
    """LS task `data` 的媒体字段名：图像类用 `image`，时序用 `csv`（TimeSeries 引用 $csv）。"""
    return "csv" if kind == "segment" else "image"


def create_task(client, project_id: int, data: dict, sample_id: int) -> int | None:
    """在 LS 项目下建一条 task，data 内嵌 sample_id 供回写映射；返回 LS task id，失败 None。

    best-effort：LS 不可达/超时 → 告警返回 None（业务 Job 不炸）。`project=` 为 SDK keyword。
    """
    try:
        task = client.tasks.create(project=project_id, data={**data, "sample_id": sample_id})
        return int(task.id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("LS task create failed (sample={}): {}", sample_id, exc)
        return None


def delete_task(client, task_id: int) -> None:
    """删除 LS task（清理/回滚用）。best-effort：失败仅告警。"""
    try:
        client.tasks.delete(task_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("LS task delete failed (task={}): {}", task_id, exc)


def get_ls_task(client, task_id: int) -> dict | None:
    """按 LS task id 拉取任务（含 annotations）。返回 dict；失败 None。"""
    try:
        task = client.tasks.get(task_id)
        if hasattr(task, "to_dict"):
            return task.to_dict()
        if isinstance(task, dict):
            return task
        return dict(task)
    except Exception as exc:  # noqa: BLE001
        logger.warning("LS task get failed (task={}): {}", task_id, exc)
        return None


def choose_effective_annotation(task_payload: dict) -> dict | None:
    """从 LS task 的 annotations 里挑"有效标注"。

    取最后一条非 cancelled、无结果跳过；草稿（draft_created_at 且有 last_action）也跳过。
    返回单条 annotation（可空）。多标注/审核策略后续再细化（计划 Track A line 68）。
    """
    anns = (task_payload or {}).get("annotations") or []
    if not anns:
        return None
    for ann in reversed(anns):
        if not isinstance(ann, dict):
            continue
        if ann.get("was_cancelled"):
            continue
        if ann.get("draft_created_at") and not ann.get("last_action"):
            # 仅草稿、未提交 → 跳过
            continue
        if ann.get("result"):
            return ann
    return None


def extract_annotator(annotation: dict) -> str:
    """标注用户 → 平台 `Annotation.annotator` 存储值（LS email/username，同名账号约定）。"""
    cb = (annotation or {}).get("completed_by")
    if isinstance(cb, dict):
        name = cb.get("email") or cb.get("username")
        if name:
            return str(name)
        if cb.get("id") is not None:
            return str(cb["id"])
    username = (annotation or {}).get("created_username")
    if username:
        # LS 格式 " xiaofei450@126.com, 1" → 取邮箱/最左段
        return str(username).strip().split(",")[0].strip() or "LabelStudio"
    return "LabelStudio"


def _region_category(region: dict) -> str:
    """从 region `value` 里取标签文本（LS 用 <plurallabels>，兼容历史 labels/choices）。"""
    value = region.get("value") or {}
    for key in ("rectanglelabels", "polygonlabels", "timeserieslabels", "labels", "choices"):
        labels = value.get(key)
        if isinstance(labels, list) and labels:
            return str(labels[0])
    return ""


def convert_region(region: dict, default_w: int = 640, default_h: int = 480) -> dict | None:
    """LS region JSON → 平台 Annotation 几何（按 result.type 分支）。

    平台 `Annotation.kind` 三态：box(rect) / polygon(多边顶点) / segment(区间)。
    LS 坐标为 0-100 **百分比**，以 region `original_width`/`original_height` 为像素参考，
    换算成平台像素空间（平台 box 用 640×480 参考空间、polygon 用 frame_width/height，
    见 annotation.export_video_masks；e2e 用 640×480 图即 exact）。
    返回 None = 无效 region（跳过）。**注意**：不提取 category（`_region_category` 负责）。
    """
    rtype = region.get("type")
    value = region.get("value") or {}
    ow = region.get("original_width") or default_w
    oh = region.get("original_height") or default_h
    scale = lambda pct, dim: round((pct or 0) / 100.0 * dim, 1)  # noqa: E731

    if rtype == "rectanglelabels":  # 目标检测
        box = [
            scale(value.get("x", 0), ow),
            scale(value.get("y", 0), oh),
            scale(value.get("width", 0), ow),
            scale(value.get("height", 0), oh),
        ]
        return {"kind": "box", "box": box}
    if rtype == "polygonlabels":  # 熔池/视频帧分割（PolygonLabels）
        pts = value.get("points") or []
        points = [[scale(px, ow), scale(py, oh)] for px, py in pts]
        return {"kind": "polygon", "points": points}
    if rtype in ("timeserieslabels", "timeseriesrange"):  # 时序分段（TimeSeries 区间）
        return {
            "kind": "segment",
            "start_time": value.get("time"),
            "end_time": value.get("endtime"),
        }
    logger.warning("Unknown LS region type: {}", rtype)
    return None


def refresh_task_media(client, task_id: int, storage, object_key: str, kind: str) -> None:
    """刷新已过期预签名 URL（决策 3 / 验证 §1）：LS task `data` 里的媒体地址更新为新 TTL。

    读取现有 data 后仅替换媒体字段，保留 sample_id 等其它键；best-effort。
    """
    try:
        url = media_url(storage, object_key)
        task = get_ls_task(client, task_id)
        data = dict((task or {}).get("data") or {})
        data[media_field_for(kind)] = url
        client.tasks.update(task_id, data=data)
    except Exception as exc:  # noqa: BLE001
        logger.warning("LS task media refresh failed (task={}): {}", task_id, exc)


def _kind_of_sample(sample: Sample) -> str:
    """样本 → 平台标注 kind（决定映射哪个 LS 项目）。视频帧/视频锚点=polygon；时序=segment；其余=box。"""
    mode = (sample.meta or {}).get("mode") if isinstance(sample, Sample) else (sample.get("meta") or {}).get("mode")
    if mode in ("frame", "video"):
        return "polygon"
    if mode == "signal":
        return "segment"
    return "box"
