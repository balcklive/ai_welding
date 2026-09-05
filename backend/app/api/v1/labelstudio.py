"""Label Studio 集成 API：webhook + 手动对账/状态查询。

**注意**：本 router **不**使用其它域 router 的 `dependencies=[Depends(get_current_user)]`
（见 `analysis_annotations.py` 路由级鉴权）。原因：webhook 要被 LS **匿名**调用（无平台 JWT），
改用**共享 secret** 校验（`label_studio_webhook_secret`，不依赖来源 IP）。手动端点单独挂 JWT。
"""

from __future__ import annotations

import secrets as _secrets

from fastapi import APIRouter, Depends, Header
from loguru import logger
from sqlmodel import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.db import get_session
from app.models.data import User
from app.schemas.common import err, ok
from app.services import annotation_ls as svc

router = APIRouter()  # 无全局 JWT（webhook 例外，用 secret）


@router.post("/labelstudio/webhook")
def ls_webhook(
    payload: dict,
    x_ls_secret: str | None = Header(default=None, alias="X-LS-Secret"),
    session: Session = Depends(get_session),
) -> dict:
    """LS annotation 事件回调（`annotation_created`/`updated`）→ 拉标注 → 幂等回写。

    - 校验共享 secret（不匹配 → 401，不依赖来源 IP）；
    - best-effort：LS 已标但回写失败仅记日志，交由对账兜底（幂等，重复事件不重复落行）；
    - 不 commit（写回在 service 内 flush；此处统一 commit，保持"路由提交"约定）。
    """
    secret = settings.label_studio_webhook_secret
    if secret and not _secrets.compare_digest(secret, x_ls_secret or ""):
        logger.warning("LS webhook invalid secret; rejecting")
        return err(40100, "invalid webhook secret", status=401)
    action = (payload or {}).get("action", "")
    try:
        result = svc.handle_annotation_event(session, action, payload)
    except Exception as exc:  # noqa: BLE001 - webhook 回调异常仅告警（对账兜底）
        logger.opt(exception=True).warning("LS webhook handling failed: {}", exc)
        return err(50000, "webhook handling failed", status=500)
    session.commit()
    return ok(result or {"handled": True, "action": action})


@router.get("/labelstudio/tasks/{task_id}")
def ls_task_status(
    task_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """标注任务的 LS 同步状态（前端「去 LS 标注」入口 + 回写状态轮询）。`task_id` 兼容 job_uid。"""
    from app.services.annotation import resolve_annotation_task

    task = resolve_annotation_task(session, task_id)
    if task is None:
        return err(40401, "标注任务不存在", status=404)
    return ok(svc.to_task_payload(task))


@router.post("/labelstudio/sync")
def ls_sync(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """手动触发对账（兜底，避免丢 webhook）；刷新过期预签名 URL。"""
    result = svc.reconcile_pending(session)
    session.commit()
    return ok(result)
