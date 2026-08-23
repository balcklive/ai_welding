"""MinIO 对象存储客户端（Task 4）。

封装 `minio.Minio` 提供：对象键规范化（`normalize_key`）、预签名直传
（`presign_put`）、后端代理上传（`upload_stream`）、预签名下载/播放
（`presign_get`）。桶与连接信息来自 `app.core.config.settings`
（`MINIO_ENDPOINT`/`MINIO_ACCESS_KEY`/`MINIO_SECRET_KEY`/`MINIO_SECURE`/`MINIO_BUCKET`）。

**惰性**：`get_storage()` 首次调用才构建客户端（懒加载单例）；桶存在性检查
（`bucket_exists` → 否则 `make_bucket`）在各操作首次使用时才触发并记忆，测试
中不调用任何方法则完全不接触网络。

对象键契约见 `docs/OSS存储设计.md` §2：单桶 `aiwelding`，键为
`{类型前缀}/{业务标识}/{规范化文件名}`；文件名小写、空格→`_`、去特殊字符、
长度 ≤255（超长截断尽量保留扩展名）。
"""

from __future__ import annotations

import re
from datetime import timedelta
from typing import BinaryIO

from minio import Minio

from app.core.config import settings

# 文件名中仅允许保留的字符（规范化后为小写字母/数字/点/下划线/连字符）
_UNSAFE_RE = re.compile(r"[^a-z0-9._\-]")
_WS_RE = re.compile(r"\s+")
_SEP_RUN_RE = re.compile(r"[_\-]{2,}")
_LEAD_TRAIL = "._-"
_MAX_FILENAME_LEN = 255
_FALLBACK_NAME = "file"


# ---------------------------------------------------------------------------
# 对象键 / 文件名规范化（模块级函数，StorageClient 以 staticmethod 委托）
# ---------------------------------------------------------------------------


def _normalize_piece(piece: str) -> str:
    """规范化一段文件名（主干或扩展名）：小写、空白→_、去特殊字符、折叠分隔符。"""
    piece = piece.lower()
    piece = _WS_RE.sub("_", piece)
    piece = _UNSAFE_RE.sub("", piece)
    piece = _SEP_RUN_RE.sub("_", piece)
    return piece.strip(_LEAD_TRAIL)


def _truncate_preserving_ext(name: str, max_len: int) -> str:
    """把 `name` 截断到 ≤ max_len，尽量保留最后一个扩展名。"""
    stem, dot, ext = name.rpartition(".")
    if not dot:
        return name[:max_len]
    keep_ext = dot + ext
    if len(keep_ext) >= max_len:
        # 扩展名本身已超限：整体截断（极端情况不保扩展名）
        return name[:max_len]
    return stem[: max_len - len(keep_ext)] + keep_ext


def normalize_filename(filename: str) -> str:
    """规范化文件名：小写、空格→`_`、去 `[a-z0-9._-]` 之外字符、长度 ≤255。

    - 中文/特殊字符直接剔除；若主干被清洗空则回退为 `file`（保留扩展名）。
    - 超长时截断到 255，尽量保留扩展名。
    - 结果不含 `/`、`\\`、`..` 等路径穿越片段，也不会以 `.` 开头（隐藏文件）。
    """
    raw = filename.lower()
    stem, dot, ext = raw.rpartition(".")
    if dot:
        stem = _normalize_piece(stem)
        ext = _normalize_piece(ext)
        if not stem:
            stem = _FALLBACK_NAME
        name = f"{stem}.{ext}" if ext else stem
    else:
        name = _normalize_piece(raw)
    if not name:
        return _FALLBACK_NAME
    if len(name) > _MAX_FILENAME_LEN:
        name = _truncate_preserving_ext(name, _MAX_FILENAME_LEN)
    return name


def normalize_key(prefix: str, filename: str) -> str:
    """生成对象键：`{prefix}/{规范化文件名}`（OSS §2）。

    - `prefix` 为调用方传入的类型前缀 + 业务标识，如 `raw/REG-20260815-00248`、
      `processed/WLD-001/align`、`uploads/<uuid>`；首尾 `/` 会被去除，避免 `//`。
    - `prefix` 为空视为调用错误（会生成非法键），抛 `ValueError`。
    """
    prefix = prefix.strip("/")
    if not prefix:
        raise ValueError("prefix 不能为空：对象键缺少业务前缀")
    return f"{prefix}/{normalize_filename(filename)}"


# ---------------------------------------------------------------------------
# StorageClient
# ---------------------------------------------------------------------------


class StorageClient:
    """MinIO 客户端（Task 4）。桶默认取 `settings.minio_bucket`（`aiwelding`）。

    `client`/`bucket` 参数供测试注入假客户端（生产直接用默认值从 settings 构建）。
    所有读写均走预签名 URL 或后端代理，桶保持私有（OSS §5）。
    """

    def __init__(self, client: Minio | None = None, bucket: str | None = None) -> None:
        self._client = client if client is not None else Minio(
            settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_secure,
        )
        self.bucket = bucket or settings.minio_bucket
        self._bucket_ready = False  # 首次使用才检查桶，之后记忆

    # ---- 对象键（委托模块级函数，语义单一来源） ----

    @staticmethod
    def normalize_key(prefix: str, filename: str) -> str:
        return normalize_key(prefix, filename)

    @staticmethod
    def normalize_filename(filename: str) -> str:
        return normalize_filename(filename)

    # ---- 生命周期 ----

    def _ensure_bucket(self) -> None:
        """首次使用时确认桶存在；不存在则创建（之后记忆不再重复检查）。"""
        if self._bucket_ready:
            return
        if not self._client.bucket_exists(self.bucket):
            self._client.make_bucket(self.bucket)
        self._bucket_ready = True

    # ---- 操作 ----

    def presign_put(
        self, prefix: str, filename: str, size: int, content_type: str
    ) -> tuple[str, str]:
        """生成大文件直传的预签名 PUT URL（OSS §3.2，默认 30 分钟有效）。

        - `prefix`：类型前缀 + 业务标识（如 `raw/REG-...`、`uploads/<uuid>`）。
        - `size`/`content_type`：本方法契约的一部分（Task 9 端点校验 Content-Length
          与类型），预签名本身只按 OSS §3.2 生成带 30 分钟有效期的 PUT URL。
        - 返回 `(object_key, upload_url)`，`object_key` 可直接落库。
        """
        self._ensure_bucket()
        object_key = self.normalize_key(prefix, filename)
        upload_url = self._client.presigned_put_object(
            self.bucket, object_key, expires=timedelta(minutes=30)
        )
        return object_key, upload_url

    def upload_stream(
        self, object_key: str, fileobj: BinaryIO, size: int, content_type: str
    ) -> None:
        """小文件后端代理上传（OSS §3.1，<100MB）：流式转发到 MinIO。

        `object_key` 应为 `normalize_key` 生成的键；`size` 为文件字节数（Content-Length）。
        """
        self._ensure_bucket()
        self._client.put_object(
            self.bucket, object_key, fileobj, size, content_type=content_type
        )

    def presign_get(self, object_key: str, expires: int = 3600) -> str:
        """生成预签名 GET / 播放 URL（OSS §4，默认 1h，支持 Range 拖动播放）。

        `expires` 单位秒；长视频可用更长有效期（如 24h=86400）。
        """
        self._ensure_bucket()
        return self._client.presigned_get_object(
            self.bucket, object_key, expires=timedelta(seconds=expires)
        )


# ---------------------------------------------------------------------------
# 懒加载单例
# ---------------------------------------------------------------------------

_storage: StorageClient | None = None


def get_storage() -> StorageClient:
    """懒加载单例：首次调用构建 `StorageClient`（此时不连网络，仅构造 Minio）。"""
    global _storage
    if _storage is None:
        _storage = StorageClient()
    return _storage
