"""Task 1：配置加载测试（backend/app/core/config.py）。"""

from app.core.config import settings


def test_minio_bucket_default() -> None:
    assert settings.minio_bucket == "aiwelding"


def test_mysql_url_contains_pymysql_and_db() -> None:
    assert "pymysql" in settings.mysql_url
    assert "ai_welding" in settings.mysql_url
