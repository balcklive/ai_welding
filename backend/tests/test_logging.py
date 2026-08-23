"""Task 1：日志脱敏（开发规范 §2.4）与调用人解析测试。"""

import jwt as pyjwt

from app.core.logging import _caller_from_authorization, _mask, _mask_query


def test_mask_query_sensitive_params() -> None:
    assert _mask_query("page=1&token=abc&page_size=20") == "page=1&token=***&page_size=20"
    assert _mask_query("") == ""


def test_mask_sensitive_keys() -> None:
    payload = {
        "username": "admin",
        "password": "s3cret",
        "nested": {"access_token": "abc", "keep": 1, "list": ["x", {"token": "t"}]},
    }
    masked = _mask(payload)
    assert masked["password"] == "***"
    assert masked["nested"]["access_token"] == "***"
    assert masked["nested"]["keep"] == 1
    assert masked["nested"]["list"][1]["token"] == "***"


def test_caller_from_bearer_token() -> None:
    token = pyjwt.encode(
        {"sub": "welduser"}, key="x" * 64, algorithm="HS256"
    )
    assert _caller_from_authorization(f"Bearer {token}") == "welduser"


def test_caller_anonymous_on_missing_or_invalid() -> None:
    assert _caller_from_authorization(None) == "anonymous"
    assert _caller_from_authorization("Basic dXNlcjpwYXNz") == "anonymous"
    assert _caller_from_authorization("Bearer not.a.jwt") == "anonymous"
