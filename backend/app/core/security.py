"""密码哈希（pwdlib/argon2）与 JWT 签发/解析（PyJWT HS256）（Task 5）。

- `hash_password(plain)` / `verify_password(plain, hash)`：pwdlib `PasswordHash.recommended()`
  （Argon2 默认参数）。`verify` 对无法识别的哈希格式会抛 `UnknownHashError`，
  这里统一捕获并按"不匹配"处理（失败返回 False，不抛异常），避免坏哈希让登录 500。
- `create_access_token(user)`：JWT（HS256），`sub=str(user.id)`、`exp = now + access_token_expire_minutes`、
  `iat = now`。
- `decode_token(token)`：解出 `sub` 并转 int（user id）；任何失败（签名错误/过期/缺 sub/非数字）抛
  `jwt.PyJWTError` 或 `ValueError`，由调用方（`api/deps.py`）统一映射为 401。
"""

import jwt
from datetime import datetime, timedelta, timezone
from typing import Any

from pwdlib import PasswordHash

from app.core.config import settings
from app.models.data import User

_password_hash = PasswordHash.recommended()


def hash_password(plain: str) -> str:
    """Argon2 哈希。"""
    return _password_hash.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """校验明文密码与存储哈希是否匹配。

    哈希格式不可识别（如测试里随手填的 "hash"）按不匹配处理，不抛异常。
    """
    try:
        return _password_hash.verify(plain, hashed)
    except Exception:  # noqa: BLE001 - 哈希格式未知/损坏一律视为不匹配
        return False


def create_access_token(user: User) -> str:
    """为指定用户签发 HS256 JWT。sub=用户 id（str），exp 按 `access_token_expire_minutes`。"""
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": str(user.id),
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_expire_minutes),
    }
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def decode_token(token: str) -> int:
    """解析 JWT 并返回用户 id（int）。

    校验签名与过期；`sub` 缺失或非数字会抛 ValueError；签名/过期等问题抛 jwt.PyJWTError。
    """
    payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
    sub = payload.get("sub")
    if sub is None:
        raise ValueError("token missing sub")
    return int(sub)
