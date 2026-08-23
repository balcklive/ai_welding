"""loguru 轮转日志配置 + ASGI 访问日志中间件。

规范依据：docs/开发规范.md §2（轮转 + 记录项 §2.2 + 脱敏 §2.4）。
访问日志写 backend/logs/api.log（相对目录自动锚定到 backend/，与 cwd 无关），
控制台同步一份；脱敏规则：键名含 password/token/secret 的值、Authorization 头一律 ***。
"""
from __future__ import annotations

import json
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode

import jwt as pyjwt
from loguru import logger

from app.core.config import settings

#: 返回体日志截断上限（字节），默认 16 KB（开发规范 §2.2）
MAX_BODY_LOG_BYTES = 16 * 1024
#: 非 multipart 请求体完整记录的安全上限
MAX_REQUEST_BODY_LOG_BYTES = 1024 * 1024

#: backend/ 目录（相对日志目录的锚点）
_BACKEND_DIR = Path(__file__).resolve().parents[2]

_setup_done = False


def setup_logging() -> None:
    """配置 loguru：控制台 + 轮转文件（backend/logs/api.log）。幂等。"""
    global _setup_done
    if _setup_done:
        return
    _setup_done = True

    logger.remove()  # 移除默认 handler，避免重复
    logger.add(
        sys.stderr,
        level="INFO",
        format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | {message}",
    )
    log_dir = Path(settings.api_log_dir)
    if not log_dir.is_absolute():
        log_dir = _BACKEND_DIR / log_dir
    logger.add(
        str(log_dir / "api.log"),
        rotation=settings.api_log_rotation,
        retention=settings.api_log_retention,
        level="INFO",
        encoding="utf-8",
        enqueue=True,
        backtrace=False,
        diagnose=False,
    )


def _is_sensitive_key(key: str) -> bool:
    k = key.lower()
    return any(term in k for term in ("password", "token", "secret"))


def _mask(value: Any) -> Any:
    """§2.4 脱敏：键名含 password/token/secret 的值替换为 ***。"""
    if isinstance(value, dict):
        return {k: ("***" if _is_sensitive_key(k) else _mask(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [_mask(v) for v in value]
    return value


def _caller_from_authorization(authorization: str | None) -> str:
    """从 Authorization 头尽力解出调用人（不校验 JWT 有效性），失败/缺失 → anonymous。"""
    if not authorization:
        return "anonymous"
    try:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token:
            return "anonymous"
        payload = pyjwt.decode(
            token, options={"verify_signature": False}, algorithms=["HS256"]
        )
        sub = payload.get("sub")
        if sub is None:
            return "anonymous"
        return str(sub)
    except Exception:  # noqa: BLE001 - 尽力而为，任何失败都回退 anonymous
        return "anonymous"


def _headers_dict(scope: dict) -> dict[str, str]:
    return {
        k.decode("latin-1").lower(): v.decode("latin-1")
        for k, v in scope.get("headers", [])
    }


def _mask_query(query: str) -> str:
    """§2.4：query 中键名含 password/token/secret 的参数值脱敏。"""
    if not query:
        return query
    masked = [
        (k, "***" if _is_sensitive_key(k) else v)
        for k, v in parse_qsl(query, keep_blank_values=True)
    ]
    return urlencode(masked, safe="*")


class AccessLogMiddleware:
    """纯 ASGI 中间件：记录全部 /api/v1 请求的访问日志。

    记录项见 §2.2：时间(UTC)+耗时ms / 调用人 / method-path-query /
    请求体（multipart 只记大小）/ 返回状态码与返回体（>16KB 截断）/
    客户端 IP / correlation id。
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if not path.startswith("/api/v1"):  # §2.1：只覆盖 /api/v1 路由
            await self.app(scope, receive, send)
            return

        headers = _headers_dict(scope)
        correlation_id = headers.get("x-correlation-id") or uuid.uuid4().hex
        start = time.perf_counter()
        method = scope.get("method", "")
        query = _mask_query(scope.get("query_string", b"").decode("utf-8", errors="replace"))

        request_size = 0
        request_body = b""
        is_multipart = headers.get("content-type", "").startswith("multipart/")

        async def receive_wrapper() -> dict:
            nonlocal request_size, request_body
            message = await receive()
            if message["type"] == "http.request":
                chunk = message.get("body", b"") or b""
                request_size += len(chunk)
                if not is_multipart and len(request_body) < MAX_REQUEST_BODY_LOG_BYTES:
                    request_body += chunk
            return message

        status = 0
        response_body = b""
        response_total = 0

        async def send_wrapper(message: dict) -> None:
            nonlocal status, response_body, response_total
            if message["type"] == "http.response.start":
                status = message.get("status", 0)
                # 回写 correlation id，便于前端串联请求
                hdrs = list(message.get("headers", []))
                hdrs.append((b"x-correlation-id", correlation_id.encode("ascii")))
                message["headers"] = hdrs
            elif message["type"] == "http.response.body":
                chunk = message.get("body", b"") or b""
                response_total += len(chunk)
                if len(response_body) < MAX_BODY_LOG_BYTES:
                    response_body += chunk[: MAX_BODY_LOG_BYTES - len(response_body)]
            await send(message)

        try:
            await self.app(scope, receive_wrapper, send_wrapper)
        except Exception:
            # 未捕获异常：仍记录一条日志（status 可能为 0），随后照常抛出
            duration_ms = (time.perf_counter() - start) * 1000.0
            self._log(
                correlation_id=correlation_id,
                method=method,
                path=path,
                query=query,
                caller=_caller_from_authorization(headers.get("authorization")),
                client_ip=self._client_ip(scope, headers),
                status=status or 500,
                duration_ms=duration_ms,
                request_size=request_size,
                request_body=request_body,
                is_multipart=is_multipart,
                response_body=response_body,
                response_total=response_total,
            )
            raise

        duration_ms = (time.perf_counter() - start) * 1000.0
        self._log(
            correlation_id=correlation_id,
            method=method,
            path=path,
            query=query,
            caller=_caller_from_authorization(headers.get("authorization")),
            client_ip=self._client_ip(scope, headers),
            status=status,
            duration_ms=duration_ms,
            request_size=request_size,
            request_body=request_body,
            is_multipart=is_multipart,
            response_body=response_body,
            response_total=response_total,
        )

    @staticmethod
    def _client_ip(scope: dict, headers: dict[str, str]) -> str:
        forwarded = headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
        client = scope.get("client")
        return client[0] if client else ""

    @staticmethod
    def _log(
        *,
        correlation_id: str,
        method: str,
        path: str,
        query: str,
        caller: str,
        client_ip: str,
        status: int,
        duration_ms: float,
        request_size: int,
        request_body: bytes,
        is_multipart: bool,
        response_body: bytes,
        response_total: int,
    ) -> None:
        request_info: Any
        if is_multipart:
            request_info = {"multipart_size": request_size}
        else:
            parsed = _try_json(request_body)
            request_info = _mask(parsed) if isinstance(parsed, (dict, list)) else {"raw_size": request_size}

        resp_json = _try_json(response_body)
        if isinstance(resp_json, (dict, list)):
            response_info: Any = _mask(resp_json)
        else:
            response_info = response_body.decode("utf-8", errors="replace") or None

        truncated = response_total > MAX_BODY_LOG_BYTES
        if truncated:
            response_info = {
                "truncated": True,
                "bytes_total": response_total,
                "preview": response_info,
            }

        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "correlation_id": correlation_id,
            "user": caller,
            "method": method,
            "path": path,
            "query": query,
            "client_ip": client_ip,
            "status": status,
            "duration_ms": round(duration_ms, 2),
            "request": request_info,
            "response": response_info,
        }
        logger.info("API access: {}", json.dumps(record, ensure_ascii=False, default=str))


def _try_json(raw: bytes) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
