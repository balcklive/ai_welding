"""统一响应信封与分页助手（Task 3）。

- `ok(data)`：成功信封 `{"code":0,"message":"ok","data":data}`。
- `err(code, message, detail, status)`：错误信封 `{"code","message","detail?"}`（HTTP 状态码自定义）。
- `paginate(items, total, page, page_size)`：分页载荷 `{"items","total","page","page_size"}`。

后续各域路由统一返回 `ok(...)` / `err(...)`，错误码约定见 `docs/API接口清单.md`。
"""

from typing import Any, Generic, TypeVar
from fastapi.responses import JSONResponse


def ok(data: Any) -> dict:
    return {"code": 0, "message": "ok", "data": data}


def err(code: int, message: str, detail: Any = None, status: int = 400) -> JSONResponse:
    body: dict = {"code": code, "message": message}
    if detail is not None:
        body["detail"] = detail
    return JSONResponse(status_code=status, content=body)


def paginate(items: list, total: int, page: int, page_size: int) -> dict:
    return {"items": items, "total": total, "page": page, "page_size": page_size}
