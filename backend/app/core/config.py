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
    # 服务端内网端点（可选）：app/LS/mlflow 与 MinIO 同宿主时，填容器可直连的内网地址
    # （如 docker 网关 172.18.0.1:9000 或宿主私网 IP:9000），让服务端数据面不走公网 hairpin；
    # 留空则服务端数据面回退用 minio_endpoint。**交到浏览器/外部的预签名 URL 恒用 minio_endpoint**。
    minio_server_endpoint: str = ""
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
    # 特征生产闸门：默认禁止部分/启发式模态结果。
    feature_allow_partial: bool = False
    feature_allow_heuristic_vision: bool = False
    feature_vision_provider_url: str = ""
    # MLFLOW-INTEGRATION: 默认内嵌 FastAPI；可切换为 server/off。
    mlflow_mode: str = "embedded"
    mlflow_tracking_uri: str = "sqlite:///./data/mlflow.db"
    mlflow_registry_uri: str = ""
    mlflow_experiment: str = "AI Welding"
    mlflow_artifact_root: str = "s3://aiwelding/mlflow-artifacts"
    mlflow_s3_endpoint_url: str = ""
    torch_cpu_threads: int = 1
    # 候选容器只做迁移与 readiness 预检，不应抢占生产异步任务。
    job_executor_enabled: bool = True

    @property
    def mysql_url(self) -> str:
        # user/password 必须 URL-encode：.env 密码可含 @ 等保留字符，
        # 直接拼入 URL 会让 SQLAlchemy 按第一个 @ 切分，把 host 解析错
        # （如 `root:1qaz@WSX@182...` → host=`WSX@182...`，连接失败）。
        return (f"mysql+pymysql://{quote_plus(self.mysql_user)}:{quote_plus(self.mysql_password)}"
                f"@{self.mysql_host}:{self.mysql_port}/{self.mysql_database}"
                f"?charset={self.mysql_charset}")


settings = Settings()
