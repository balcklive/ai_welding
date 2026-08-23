"""数据库引擎与会话（Task 2）。

- `engine`：MySQL 引擎（`settings.mysql_url`），模块级单例。
- `SessionLocal`：`sessionmaker` 工厂，`expire_on_commit=False`。
- `get_session`：FastAPI 依赖，`yield` 一个 `Session`。

注意：测试禁用本模块的 MySQL 引擎，改用内存 SQLite（见 `tests/test_models.py`）。
"""

from sqlalchemy.orm import sessionmaker
from sqlmodel import Session, create_engine

from app.core.config import settings

engine = create_engine(settings.mysql_url, pool_pre_ping=True, echo=False)
SessionLocal = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)


def get_session():
    """FastAPI 依赖：每请求一个 Session，请求结束自动关闭。"""
    with Session(engine) as session:
        yield session
