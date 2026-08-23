# CLAUDE.md — backend/alembic/

Alembic 迁移。当前进度：Task 2（初始迁移 `0001_initial`，23 张表）。

## 文件

- `alembic.ini`：`script_location = %(here)s/alembic`；**`sqlalchemy.url` 留空**，由 env.py 从 `settings.mysql_url` 注入，避免明文密码进仓库。
- `env.py`：`from app.models import *`（导入全部 23 个表类）→ `target_metadata = SQLModel.metadata`；`config.set_main_option("sqlalchemy.url", settings.mysql_url)`；`compare_type=False`（原因见下）。
- `script.py.mako`：迁移模板（alembic init 生成）。
- `versions/0001_initial.py`：初始迁移（手写，见"手写迁移的原因"）。

## 常用命令（在 `backend/` 下执行）

- 生成迁移：`uv run alembic revision --autogenerate -m "..."`（需要连上远程 MySQL）
- 应用：`uv run alembic upgrade head`
- 回滚：`uv run alembic downgrade -1`
- 离线渲染 SQL（不连库）：`uv run alembic upgrade head --sql`

## 坑/限制

- **手写迁移的原因**：远程 MySQL（`settings.mysql_host`）在本机不可达，`--autogenerate` 无法对比，故 `0001_initial.py` 按 `docs/数据库设计.md` §3 手写。
- **DATETIME(6) 调整**：模型注解是 `DateTime(timezone=True)`（SQLAlchemy 对 MySQL 渲染 fsp=0），契约要求 `DATETIME(6)`，迁移里**统一手写 `mysql.DATETIME(fsp=6)`**。因此 `env.py` 关闭 `compare_type`，避免后续 autogenerate 对每个 datetime 列报"类型变化"噪音（代价：真实类型变更需人工留意）。
- **JSON 列**：统一 `mysql.JSON()`。
- **环形外键**：`data_records↔data_versions`、`datasets↔dataset_versions` 两处互指 FK，升级里"先建父表 → 建子表 → `op.create_foreign_key` 补指针外键"；降级里**先 `drop_constraint` 拆环形外键**再逆序删表。改迁移时保持该顺序。
- **唯一约束名**：`uq_<table>_<cols>`；索引名 `ix_<table>_<col>`（`ix_audit_logs_resource_type_resource_id` 为复合索引）。新建迁移尽量沿用命名风格。
- **MySQL 限制**：表/索引名 ≤64 字符；JSON 列（8.0.13 前）不能有默认值，NOT NULL JSON 由服务层保证。
- 初始迁移的 `revision = "0001"`（非随机 hex），后续迁移用 `alembic revision` 自动续。
