"""reports 域路由（Task 17）：通用报告导出 PDF/JSON。

`POST /api/v1/reports/export` body `{type, ref_ids[], format}` →
为每个 ref_id 装配报告（Jinja2 + xhtml2pdf）写 MinIO `reports/{type}/{ref_id}.pdf|.json` →
`ok({urls:[{ref_id, url}]})`（url 为预签名下载）。

错误码：40000=未知类型/格式、40401=引用实体不存在、40100=未登录。
业务逻辑在 `app.services.reports`。
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.api.deps import get_current_user
from app.core.db import get_session
from app.schemas.common import err, ok
from app.services.reports import (
    EntityNotFoundError,
    FORMATS,
    REPORT_TYPES,
    export_reports,
)

router = APIRouter(dependencies=[Depends(get_current_user)])


class ExportRequest(BaseModel):
    type: str
    ref_ids: list = Field(default_factory=list)
    format: str = "pdf"


@router.post("/reports/export")
def export_report(
    body: ExportRequest,
    session: Session = Depends(get_session),
):
    if body.type not in REPORT_TYPES:
        return err(40000, f"未知报告类型: {body.type}", status=400)
    if body.format not in FORMATS:
        return err(40000, f"未知导出格式: {body.format}", status=400)
    try:
        urls = export_reports(session, body.type, body.ref_ids, body.format)
    except EntityNotFoundError as exc:
        return err(40401, str(exc), status=404)
    return ok({"urls": urls})
