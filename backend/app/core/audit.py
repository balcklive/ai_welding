"""审计日志写入辅助（Task 3）。

`write_audit(...)` 向 `audit_logs` 表（`AuditLog`，见 `app/models/data.py` §3.23）
插入一行审计记录，`created_at` 取 UTC 当前时间（timezone-aware）。

**注意**：本函数只 `session.add` + `session.flush`，**不 commit**，
由调用方在自己的事务里统一 commit（保证审计与业务变更同事务、原子提交）。
flush 后返回的 `entry.id` 已可用。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlmodel import Session

from app.models.data import AuditLog


def _sanitize_detail(value: Any) -> Any:
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if any(token in str(key).lower() for token in ("password", "token", "secret")):
                out[key] = "***"
            else:
                out[key] = _sanitize_detail(item)
        return out
    if isinstance(value, list):
        return [_sanitize_detail(item) for item in value]
    return value


def write_audit(
    session: Session,
    user_id: int | None,
    action: str,
    resource_type: str,
    resource_id: str | None = None,
    detail: dict[str, Any] | None = None,
) -> AuditLog:
    """插入一行审计日志并返回该行对象（未提交）。

    - `action`：如 create/update/validate/export/delete…（存 `audit_logs.action`）。
    - `resource_type`：如 weld/dataset/model…（存 `audit_logs.resource_type`）。
    - `resource_id`：资源标识（字符串，可选）。
    - `detail`：任意 JSON 可序列化 dict（可选）。
    """
    entry = AuditLog(
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        detail=_sanitize_detail(detail) if detail is not None else None,
        created_at=datetime.now(timezone.utc),
    )
    session.add(entry)
    session.flush()
    return entry
