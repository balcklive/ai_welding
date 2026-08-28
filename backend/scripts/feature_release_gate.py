"""特征提取生产发布门禁。

默认只检查配置和运行时依赖，不访问外部系统；加 ``--probe`` 才会执行 MySQL、MinIO
和视觉推理服务探测。命令：``uv run python scripts/feature_release_gate.py --probe``。
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path
from urllib.parse import urlparse
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings


def _check_static() -> list[str]:
    failures: list[str] = []
    if not settings.feature_vision_provider_url:
        failures.append("FEATURE_VISION_PROVIDER_URL 未配置")
    parsed = urlparse(settings.feature_vision_provider_url)
    if settings.feature_vision_provider_url and parsed.scheme not in {"http", "https"}:
        failures.append("FEATURE_VISION_PROVIDER_URL 必须使用 http 或 https")
    for name, value in {
        "MYSQL_HOST": settings.mysql_host,
        "MYSQL_USER": settings.mysql_user,
        "MYSQL_PASSWORD": settings.mysql_password,
        "MINIO_ENDPOINT": settings.minio_endpoint,
        "MINIO_ACCESS_KEY": settings.minio_access_key,
        "MINIO_SECRET_KEY": settings.minio_secret_key,
    }.items():
        if not value:
            failures.append(f"{name} 未配置")
    if getattr(settings, "seed_demo", False):
        failures.append("SEED_DEMO 必须为 false")
    if settings.secret_key in {"", "change-me"}:
        failures.append("SECRET_KEY 仍使用默认值")
    if settings.admin_password in {"", "admin123"}:
        failures.append("ADMIN_PASSWORD 仍使用默认值")
    if importlib.util.find_spec("torch") is None:
        failures.append("当前运行时未安装 PyTorch，PT 导出不可用")
    return failures


def _probe_external() -> list[str]:
    failures: list[str] = []
    try:
        from sqlalchemy import text
        from sqlmodel import Session
        from app.core.db import engine

        with Session(engine) as session:
            session.exec(text("SELECT 1"))
            migration = session.exec(text("SELECT version_num FROM alembic_version")).first()
            current_revision = migration[0] if migration else None
            if current_revision != "0010":
                failures.append(f"数据库迁移版本为 {current_revision or 'unknown'}，要求 0010")
    except Exception as exc:  # noqa: BLE001 - 门禁只输出摘要
        failures.append(f"MySQL 探测失败: {type(exc).__name__}")
    try:
        from app.storage import get_storage

        storage = get_storage()
        # 只读探测；不能复用 upload/presign 的 _ensure_bucket，避免门禁自动创建桶。
        if not storage._client.bucket_exists(storage.bucket):
            failures.append("MinIO bucket 不存在")
    except Exception as exc:  # noqa: BLE001 - 门禁只输出摘要
        failures.append(f"MinIO 探测失败: {type(exc).__name__}")
    if settings.feature_vision_provider_url:
        try:
            request = Request(settings.feature_vision_provider_url, method="HEAD")
            with urlopen(request, timeout=5):  # noqa: S310 - 地址来自显式部署配置
                pass
        except HTTPError as exc:
            # 推理端点不一定实现 HEAD；405 仍说明服务可达，其他状态视为配置/服务异常。
            if exc.code != 405:
                failures.append(f"视觉推理服务探测失败: HTTP {exc.code}")
        except Exception as exc:  # noqa: BLE001 - 门禁只输出摘要
            failures.append(f"视觉推理服务探测失败: {type(exc).__name__}")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description="运行特征提取生产发布门禁")
    parser.add_argument("--probe", action="store_true", help="探测 MySQL 和 MinIO；默认不访问外部系统")
    args = parser.parse_args()
    failures = _check_static()
    if args.probe:
        failures.extend(_probe_external())
    if failures:
        print("FEATURE_RELEASE_GATE=FAIL")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print("FEATURE_RELEASE_GATE=PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
