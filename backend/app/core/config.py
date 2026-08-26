from pathlib import Path
from urllib.parse import quote_plus

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # env_file 指向仓库根 `.env`：config.py 位于 backend/app/core/，
    # parents[3] = 仓库根（backend/app/core -> app -> backend -> 根），与 cwd 无关。
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[3] / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )
    # MinIO
    minio_endpoint: str = ""
    minio_secure: bool = False
    minio_access_key: str = ""
    minio_secret_key: str = ""
    minio_bucket: str = "aiwelding"
    # MySQL
    mysql_host: str = ""
    mysql_port: int = 8206
    mysql_user: str = ""
    mysql_password: str = ""
    mysql_database: str = "ai_welding"
    mysql_charset: str = "utf8mb4"
    # Auth
    secret_key: str = "change-me"
    access_token_expire_minutes: int = 1440
    admin_username: str = "admin"
    admin_password: str = "admin123"
    # API log
    api_log_dir: str = "logs"
    api_log_rotation: str = "10 MB"
    api_log_retention: int = 5

    @property
    def mysql_url(self) -> str:
        # user/password 必须 URL-encode：.env 密码可含 @ 等保留字符，
        # 直接拼入 URL 会让 SQLAlchemy 按第一个 @ 切分，把 host 解析错
        # （如 `root:1qaz@WSX@182...` → host=`WSX@182...`，连接失败）。
        return (f"mysql+pymysql://{quote_plus(self.mysql_user)}:{quote_plus(self.mysql_password)}"
                f"@{self.mysql_host}:{self.mysql_port}/{self.mysql_database}"
                f"?charset={self.mysql_charset}")


settings = Settings()
