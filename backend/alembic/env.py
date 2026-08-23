"""Alembic 迁移环境。

- `sqlalchemy.url` 由 `app.core.config.settings.mysql_url` 提供（不在 alembic.ini 写明文密码）。
- `target_metadata` 绑定 `SQLModel.metadata`，含全部 23 张表（`from app.models import *`）。
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlmodel import SQLModel

from app.core.config import settings

# 必须在 import app.models 之前把 backend/ 加入 sys.path 的场景不成立：
# alembic 在 backend/ 下执行，`app` 直接可导入。

# 导入全部模型表类，确保元数据齐全（SQLModel.metadata 收集所有 `table=True` 类）。
from app.models import *  # noqa: E402, F401, F403

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 从 settings 注入 URL（alembic.ini 中 sqlalchemy.url 留空）。
config.set_main_option("sqlalchemy.url", settings.mysql_url)

target_metadata = SQLModel.metadata


def run_migrations_offline() -> None:
    """Offline 模式：只生成 SQL 不连库。"""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # 模型用 DateTime(timezone=True)（渲染 fsp=0），契约要求 DATETIME(6)，
        # 初始迁移手工写成 mysql.DATETIME(fsp=6)。关闭 compare_type 避免后续
        # autogenerate 对每个 datetime 列输出无意义 diff。
        compare_type=False,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Online 模式：连接数据库执行迁移。"""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=False,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
