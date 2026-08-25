"""files 域路由（Task 9）：MinIO 上传 / 预签名直传 / 下载 URL。

三个端点均需登录（router 级 `Depends(get_current_user)`）；`/api/v1` 前缀由
main.py 挂载时统一添加。对象键契约见 `docs/OSS存储设计.md` §2/§3：

- 小文件（<100MB）走 `POST /files/upload` 后端代理——流式读取 + 字节计数封顶，
  不整文件载入内存；返回 `{object_key, url}`（url = 预签名 GET）。
- 大文件（≥100MB 且 ≤2GB）走 `POST /files/presign-upload` 预签名直传——返回
  `{object_key, upload_url}`，前端直接 PUT 到 MinIO。
- 播放/下载一律 `GET /files/{object_key}/url` 签发预签名 GET URL（支持 Range）。

契约补充（Task 9 决策，T25 将回写 `docs/API接口清单.md`）：
`presign-upload` 请求体在 `{size, content_type, prefix}` 之外扩展可选
`filename`（默认 `"file"`），`object_key = normalize_key(prefix, filename)`——
调用方无需自行拼文件名，仅需提供包含业务标识的 prefix（如 `raw/REG-...`）。
"""

import tempfile
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Query, UploadFile
from pydantic import BaseModel

from app.api.deps import get_current_user
from app.schemas.common import err, ok
from app.storage import get_storage

router = APIRouter(prefix="/files", dependencies=[Depends(get_current_user)])

#: 小文件代理上传上限（OSS §3.1：<100MB）
MAX_PROXY_UPLOAD_SIZE = 100 * 1024 * 1024
#: 大文件预签名直传上限（OSS §3.2：≤2GB）
MAX_PRESIGN_UPLOAD_SIZE = 2 * 1024 * 1024 * 1024
#: 预签名 GET URL 有效期上限（OSS §4：长视频 24h）
MAX_PRESIGN_GET_EXPIRES = 86400
#: 流式转发分块大小（1MB，SpooledTemporaryFile 以此阈值落盘）
_CHUNK = 1024 * 1024
_UPLOADS_LIFECYCLE = {"policy": "temporary", "retention_days": 30, "prefix": "uploads/"}


class PresignUploadRequest(BaseModel):
    """大文件直传请求体（OSS §3.2）。`filename` 可选，默认 `"file"`。"""

    size: int
    content_type: str
    prefix: str
    filename: str = "file"


def _size_msg() -> str:
    return "文件过大：小文件代理上传需 < 100MB"


def _declared_length(file: UploadFile) -> int | None:
    """尽力从 multipart 部件头取 Content-Length；缺失/非法返回 None。"""
    raw = (file.headers or {}).get("content-length")
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


@router.post("/upload")
def upload_file(file: Annotated[UploadFile, File(...)]) -> object:
    """小文件（<100MB）后端代理上传：流式转发到 MinIO，返回 `{object_key, url}`。

    - object_key 前缀固定 `uploads/{uuid}`（临时上传区，OSS §2）。
    - 有 Content-Length 时先快速拒绝超限；否则读取过程中字节计数封顶。
    """
    storage = get_storage()
    object_key = storage.normalize_key(f"uploads/{uuid4().hex}", file.filename or "")
    content_type = file.content_type or "application/octet-stream"

    declared = _declared_length(file)
    if declared is not None and declared >= MAX_PROXY_UPLOAD_SIZE:
        return err(40000, _size_msg(), status=400)

    spool = tempfile.SpooledTemporaryFile(max_size=_CHUNK)
    try:
        src = file.file
        src.seek(0)
        total = 0
        while True:
            chunk = src.read(_CHUNK)
            if not chunk:
                break
            total += len(chunk)
            if total >= MAX_PROXY_UPLOAD_SIZE:
                return err(40000, _size_msg(), status=400)
            spool.write(chunk)
        spool.seek(0)
        storage.upload_stream(object_key, spool, total, content_type)
    finally:
        spool.close()

    url = storage.presign_get(object_key)
    return ok({"object_key": object_key, "url": url, "lifecycle": dict(_UPLOADS_LIFECYCLE)})


@router.post("/presign-upload")
def presign_upload(body: PresignUploadRequest) -> object:
    """大文件（≥100MB 且 ≤2GB）预签名直传：返回 `{object_key, upload_url}`。

    `size` 需满足 `0 < size ≤ 2GB`（OSS §3.2）；`prefix` 含业务标识
    （如 `raw/REG-...`），`object_key = normalize_key(prefix, filename)`。
    """
    size = body.size
    if not (0 < size <= MAX_PRESIGN_UPLOAD_SIZE):
        return err(40000, "size 需满足 0 < size ≤ 2GB", status=400)
    storage = get_storage()
    try:
        object_key, upload_url = storage.presign_put(
            body.prefix, body.filename, size, body.content_type
        )
    except ValueError as exc:  # prefix 为空等 → normalize_key 抛错
        return err(40000, str(exc), status=400)
    lifecycle = dict(_UPLOADS_LIFECYCLE) if object_key.startswith("uploads/") else None
    return ok({"object_key": object_key, "upload_url": upload_url, "lifecycle": lifecycle})


@router.get("/{object_key:path}/url")
def get_file_url(
    object_key: str,
    expires: Annotated[int | None, Query()] = None,
) -> object:
    """预签名下载/播放 URL（支持 Range）。`expires` 秒，默认 1h，上限 24h。"""
    if not object_key or not object_key.strip():
        return err(40000, "object_key 不能为空", status=400)
    if expires is None:
        expires = 3600
    if not (0 < expires <= MAX_PRESIGN_GET_EXPIRES):
        return err(40000, "expires 需在 1~86400 秒之间", status=400)
    storage = get_storage()
    return ok({"url": storage.presign_get(object_key, expires)})
