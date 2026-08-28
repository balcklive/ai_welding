# AI 焊接平台全栈开发实现计划（后端 + 前端全链路接线）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 依据 `docs/` 五份设计文档，从零搭建 `backend/`（FastAPI + SQLModel + Alembic + MinIO + 真实 DSP + 异步 Job），并新建 `src/api/` + hooks + 登录页、把 `src/App.tsx` 的 mock 数据源逐页替换为 API 调用，实现前后端全链路打通、本地跑通。

**Architecture:** 后端独立 `backend/`，前端留仓库根 `src/`，通信仅走 HTTP `/api/v1`（开发期 Vite proxy）。契约唯一来源是 `docs/API接口清单.md`；表结构 `docs/数据库设计.md`；对象键 `docs/OSS存储设计.md`；实施原则 `docs/开发规范.md`。异步任务统一 `jobs` 表 + 小型 DB 轮询执行器；信号分析/特征提取为真实 DSP（scipy/pywt/skimage），对齐/切分/训练/测试/推理/预标注为真实编排 + 模拟结果。

**Tech Stack:** 后端 `uv` + FastAPI + SQLModel + Alembic + PyJWT + pwdlib[argon2] + minio + scipy + numpy + PyWavelets + scikit-image + librosa + Jinja2 + xhtml2pdf + loguru + pytest。前端现有 Vite 5 + React 18 + TS + Tailwind，不新增运行时依赖（fetch 代替 axios，条件渲染代替 react-router）。

---

## Global Constraints（所有任务隐式包含）

1. **每目录必有 CLAUDE.md**：新建目录（`backend/`、`backend/app/` 各层、`src/api/`、`src/hooks/`、`src/pages/`、`docs/superpowers/`）即补；改脚本时同步更新。
2. **Python 一律 uv**：`uv venv` / `uv sync` / `uv add` / `uv run`。禁 pip。
3. **敏感信息只进 `.env`**（gitignore）；`.env.example` 同步新增非敏感键。
4. **复用优先**（`docs/开发规范.md` §1）：fastapi-users / tsfresh / 通用任务队列**刻意不复用**。分页与统一信封冲突 → 手写 `paginate()` 助手（约 20 行，属业务胶水，写入 §1.1 刻意不复用清单）。
5. **接口轮转日志（必守）**（§2）：ASGI 中间件 + loguru 轮转，字段见 §2.2，脱敏见 §2.4（`password`/`token`/`secret`/`Authorization` → `***`）。
6. **实施边界**（§3，不得越界）：
   - DSP/特征提取 = 真实计算；对齐/切分/训练/测试/推理/预标注 = 真实 Job 编排 + 模拟结果（Job 状态/结果回填/MinIO 产物为真）。
   - 前端只改数据层、不动 UI 结构；**不重写 App.tsx**；新增最小登录页。
   - **不写 Dockerfile / docker-compose / GitHub Pages workflow**（本地跑通不部署）。
   - 启动自动 seed 管理员（用户名/密码读 `.env`） + 与前端 mock 对齐的演示数据。
   - **本期不支持删除**（无 DELETE 端点）。
7. **契约同步**：改任何接口/表/对象键，须同步三份契约 + 两端代码。
8. **统一信封** `{code, message, data}`；成功 `code=0`。错误带 HTTP 状态码。列表分页 `?page=&page_size=`（max 100），响应 `{items, total, page, page_size}`。筛选一律服务端执行。
9. **时间** ISO 8601 UTC；标识 `WLD-YYYYMMDD-序号` / `REG-YYYYMMDD-序号` / `DS-xxx-序号` / `job_xxx`。
10. **两套缺陷词表勿混用**：总览「缺陷分布」= 统计口径（未焊透/焊穿/夹渣…）；标注「标签类别」= 模型口径（焊瘤/气孔/未熔合/咬边/正常）。
11. **资源 ID 约定**：URL 中 `weld_id` 用业务号（WLD-…）；`job_id` 用 `job_uid`；其余（version/registration/dataset/model/sample/task 等）一律用 DB 自增 BIGINT id。
12. **DB 测试策略**：pytest 用 **SQLite 内存库 + `create_all`**（模型保持可移植），不用远程 MySQL；Alembic 迁移针对 MySQL 生成（`DATETIME(6)` 在迁移中显式渲染），迁移冒烟单独跑真实 MySQL（可选）。前端无测试框架 → 验证 = `tsc typecheck` + `vite build` + `eslint`。
13. **Job 执行器**：FastAPI lifespan 启动后台线程轮询 `jobs`；测试直接调用 `run_job(job_id)` 同步执行（不依赖线程）。

---

## 阶段 A — 后端地基

### Task 1: 后端骨架 + 配置 + 日志中间件

**Files:**
- Create: `backend/pyproject.toml`、`backend/uv.lock`（uv sync 生成）、`backend/.python-version`、`backend/app/__init__.py`、`backend/app/main.py`、`backend/app/core/__init__.py`、`backend/app/core/config.py`、`backend/app/core/logging.py`、`backend/CLAUDE.md`、`backend/app/CLAUDE.md`
- Modify: 根 `.env`（补 `SECRET_KEY`、`ACCESS_TOKEN_EXPIRE_MINUTES`、`API_LOG_DIR/API_LOG_ROTATION/API_LOG_RETENTION`、`ADMIN_USERNAME/ADMIN_PASSWORD`）、根 `.env.example`、根 `.gitignore`（加 `backend/.venv/`、`backend/logs/`、`logs/`）、根 `CLAUDE.md`（补 backend 段）

**Interfaces:**
- Produces: `backend/app/core/config.py::settings`（模块级单例 `Settings`）；`backend/app/main.py::app`（FastAPI 实例，挂 `/api/v1` 前缀 + 日志中间件 + 健康检查 `GET /api/v1/health`）；`backend/app/core/logging.py::AccessLogMiddleware`。

**Steps:**

- [x] 1. 写 `backend/pyproject.toml`（依赖声明；由 `uv sync` 生成 lock）：

```toml
[project]
name = "ai-welding-backend"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
  "fastapi>=0.115", "uvicorn[standard]>=0.30", "sqlmodel>=0.0.22",
  "pydantic-settings>=2.4", "alembic>=1.13", "sqlalchemy>=2.0",
  "pymysql>=1.1", "cryptography>=42.0", "PyJWT>=2.8", "pwdlib[argon2]>=0.2",
  "minio>=7.2", "numpy>=2.0", "scipy>=1.13", "PyWavelets>=1.6",
  "scikit-image>=0.23", "librosa>=0.10", "Jinja2>=3.1", "xhtml2pdf>=0.2.15",
  "loguru>=0.7", "python-multipart>=0.0.9",
]
[dependency-groups]
dev = ["pytest>=8.2", "httpx>=0.27"]
[tool.uv]
package = false
```

- [x] 2. 写 `backend/app/core/config.py`（pydantic-settings，读 `.env`）：

```python
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")
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
        return (f"mysql+pymysql://{self.mysql_user}:{self.mysql_password}"
                f"@{self.mysql_host}:{self.mysql_port}/{self.mysql_database}"
                f"?charset={self.mysql_charset}")

settings = Settings()
```

- [x] 3. 写 `backend/app/core/logging.py`：loguru 配置（`logger.add(settings.api_log_dir + "/api.log", rotation=..., retention=..., level="INFO")`，控制台同步一份）+ ASGI 中间件 `AccessLogMiddleware`，按 `docs/开发规范.md` §2.2 记录：时间(UTC)+耗时ms、调用人（JWT 解出 username，未登录 anonymous）、方法/路径/query、请求体（multipart 只记大小）、返回状态码/返回体（>16KB 截断）、IP、correlation id（取请求头或生成 uuid）；按 §2.4 脱敏。
- [x] 4. 写 `backend/app/main.py`：`app = FastAPI(...)`，`app.add_middleware(AccessLogMiddleware)`，注册 `/api/v1/health`，挂载路由 `include_router(api_router, prefix="/api/v1")`（router 在 Task 3 提供；本任务先用占位空 router 或 health 单端点）。**注意**：配置路径基准为仓库根 `.env`（uv run 在 backend/ 下时需 `--directory` 或 `env_file="../.env"`——以 `.env` 实际位置为准，config 用 `env_file` 指向仓库根 `.env` 绝对路径或通过 `backend/.env`，选一种并写进 CLAUDE.md）。
- [x] 5. 补 `.env` 缺的键与 `.env.example`、`.gitignore`；写 `backend/CLAUDE.md` 与 `backend/app/CLAUDE.md`。
- [x] 6. 写测试 `backend/tests/test_config.py`：断言 `settings.minio_bucket == "aiwelding"`、`settings.mysql_url` 含 `pymysql` 与库名。
- [x] 7. 运行：`cd backend && uv sync && uv run pytest`（预期 PASS）。
- [x] 8. 提交 `chore: scaffold backend with config and logging middleware`。

**测试/验证：** `backend/tests/test_config.py` 过；`uv run uvicorn app.main:app` 可启动，`curl /api/v1/health` 返回 `{"code":0,"message":"ok","data":{"status":"ok"}}`（健康检查用同步响应即可）。

---

### Task 2: SQLModel 全部模型 + DB 会话 + Alembic 初始迁移

**Files:**
- Create: `backend/app/core/db.py`、`backend/app/models/__init__.py`、`backend/app/models/{user,data_record,data_version,validation,validation_rule,job,alignment_task,split_task,sample,annotation_task,annotation,label_category,feature_extraction,dataset,dataset_version,dataset_item,model,model_version,training_task,test_task,inference_task,dataset_build_task,audit_log}.py`（23 个实体文件，可合并为少量文件）、`backend/alembic.ini`、`backend/alembic/env.py`、`backend/alembic/versions/0001_initial.py`

**Interfaces:**
- Produces: `app/core/db.py::engine`（模块级）、`app/core/db.py::SessionLocal`、`app/core/db.py::get_session`（FastAPI 依赖，`yield session`）；`app/models/*` 全部 SQLModel 表类（`__tablename__` 与 `docs/数据库设计.md` §3 表名一致）。
- Consumes: `settings.mysql_url`（Task 1）。

**Steps:**

- [x] 1. 类型映射规则（**逐列对照 `docs/数据库设计.md` §3.1–§3.23**）：
  | 文档列型 | SQLModel/SQLAlchemy |
  |---|---|
  | BIGINT PK | `id: int = Field(primary_key=True)` |
  | VARCHAR(n) | `x: str = Field(max_length=n, nullable=?)` |
  | DATETIME(6) | `x: datetime \| None = Field(default=None, sa_column=Column(DateTime(timezone=True)))`（迁移里渲染成 `DATETIME(6)`） |
  | JSON | `x: dict \| None = Field(default=None, sa_column=Column(JSON))` |
  | DECIMAL(p,s) | `sa_column=Column(Numeric(p, s))` |
  | FK | `Field(foreign_key="表名.id", ...)` |
  | 索引列 | `Field(index=True)` |
  | 唯一约束/复合唯一 | 类内 `__table_args__ = (UniqueConstraint(...), Index(...))` |
  - 每张表列名/类型/约束**照抄**文档 §3 对应小节；表名复数 snake_case。
- [x] 2. 写 `backend/app/core/db.py`：

```python
from sqlmodel import create_engine, Session
from app.core.config import settings

engine = create_engine(settings.mysql_url, pool_pre_ping=True, echo=False)
SessionLocal = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)

def get_session():
    with Session(engine) as session:
        yield session
```

（`sessionmaker` 从 `sqlalchemy.orm` 导入；SQLModel 会话可用 `Session(engine)`。）
- [x] 3. 逐表实现模型，重点核对：`data_records` 含 `weld_id`(UK)、`registration_no`(UK)、`weld_name`、`modalities`(JSON 默认 `[]`)、`quality`(默认 '待复核')、`storage_bytes`、`latest_version_id`(FK→data_versions.id, nullable)；`data_versions` 复合唯一 `(record_id, version_no)`；`jobs` 含 `job_uid`(UK)、`type`、`status`、`progress`、`result`、`error`、`created_at`/`finished_at`；`dataset_versions` 含 `split`(JSON)、`snapshot_id`、`quality`(JSON)；`model_versions` 含 `status` 默认 '实验版本'、`file_key`；`audit_logs` 全字段。`models`(无 created_at)、`annotations`(含 `box` JSON、`confidence` Decimal(4,3))。
- [x] 4. 写 Alembic：`alembic init` 后改 `alembic/env.py` 导入 `app.models` 全部 + `app.core.db.Base` 元数据，`sqlalchemy.url` 用 `settings.mysql_url`；生成 `versions/0001_initial.py`（`--autogenerate`），并把 datetime 列 render 为 `mysql.DATETIME(6)`（autogenerate 后手工调整或预置 type 注解）。
- [x] 5. 测试 `backend/tests/test_models.py`：用 **SQLite 内存**（`create_engine("sqlite://", connect_args={"check_same_thread": False})` + `SQLModel.metadata.create_all`）建表成功；插入 1 条 `User`、1 条 `DataRecord` + `DataVersion`，断言复合唯一冲突抛错；断言 `data_records.modalities` JSON 往返。
- [x] 6. 迁移冒烟（可选、可跳过）：`uv run alembic upgrade head` 对真实 MySQL，`SHOW TABLES` 含 23 张表。
- [x] 7. 写 `backend/app/models/CLAUDE.md`、`backend/app/core/CLAUDE.md`。
- [x] 8. 提交 `feat: add SQLModel entities and alembic initial migration`。

**测试/验证：** `test_models.py` 全绿（SQLite）；迁移脚本对 MySQL 无语法错误（如环境可用则真实执行一次并记录结果）。

---

### Task 3: 统一信封 + 错误处理 + 路由聚合 + audit + 分页助手

**Files:**
- Create: `backend/app/schemas/__init__.py`、`backend/app/schemas/common.py`、`backend/app/api/__init__.py`、`backend/app/api/v1/__init__.py`、`backend/app/api/v1/router.py`、`backend/app/core/audit.py`
- Modify: `backend/app/main.py`（挂 router + 全局异常处理器）

**Interfaces:**
- Produces: `common.ok(data) -> dict`、`common.err(code:int, message:str, detail=None, status:int) -> JSONResponse`；`router.py::api_router`（聚合后续各域 router）；`audit.write_audit(session, user_id, action, resource_type, resource_id, detail=None)`；`common.paginate(query, page, page_size, total) -> dict`。
- Consumes: Task 1/2 的 main/app/models。

**Steps:**

- [x] 1. 写 `schemas/common.py`：

```python
from typing import Any, Generic, TypeVar
from fastapi.responses import JSONResponse

def ok(data: Any) -> dict:
    return {"code": 0, "message": "ok", "data": data}

def err(code: int, message: str, detail: Any = None, status: int = 400) -> JSONResponse:
    body: dict = {"code": code, "message": message}
    if detail is not None:
        body["detail"] = detail
    return JSONResponse(status_code=status, content=body)

def paginate(items: list, total: int, page: int, page_size: int) -> dict:
    return {"items": items, "total": total, "page": page, "page_size": page_size}
```

- [x] 2. `main.py` 注册全局异常处理器：`RequestValidationError` → 422 `err(42200, "参数校验失败", detail=exc.errors())`；`HTTPException` → 按 status（401/403/404/409/500）映射业务码；兜底 `Exception` → 500 `err(50000, "服务内部错误")`（loguru 记 traceback）。
- [x] 3. `router.py`：`api_router = APIRouter()`；为后续域路由 `include_router`（auth/dashboard/welds/analysis/datasets/models/files/jobs/reports —— 各域本任务可先建空文件占位，后续任务填实现，避免 import 断链）。
- [x] 4. `core/audit.py`：`write_audit(...)` 向 `audit_logs` 表插一行（`action` 取 create/update/validate/export 等，`resource_type` 取 weld/dataset/model…）。
- [x] 5. 测试 `backend/tests/test_common.py`：`ok()` 信封形状；`err(40101,...)` 返回 HTTP 401 + body；`paginate` 形状；TestClient 打 `/api/v1/health` 返回信封。
- [x] 6. 提交 `feat: unified envelope, error handlers, audit helper`。

**测试/验证：** `test_common.py` 全绿；`/api/v1/health` 返回 `{code:0,...}`。

---

### Task 4: MinIO 存储客户端

**Files:**
- Create: `backend/app/storage/__init__.py`、`backend/app/storage/client.py`、`backend/app/storage/CLAUDE.md`

**Interfaces:**
- Produces: `storage/client.py::get_storage() -> StorageClient`（懒加载单例）；`StorageClient.presign_put(prefix, filename, size, content_type) -> (object_key, url)`；`StorageClient.upload_stream(key, fileobj, size, content_type)`；`StorageClient.presign_get(object_key, expires=3600) -> str`；`StorageClient.normalize_key(prefix, filename) -> str`。
- Consumes: `settings`（Task 1）。

**Steps:**

- [x] 1. 按 `docs/OSS存储设计.md` §2 键体系实现 `normalize_key`：`{prefix}/{业务标识}/{文件名规范化}`；文件名小写、空格→`_`、去特殊字符、≤255。
- [x] 2. `minio.Minio(endpoint, access_key, secret_key, secure=settings.minio_secure)`；确认桶存在（`bucket_exists` 否则 `make_bucket`）。
- [x] 3. `presign_put`：`client.presigned_put_object(bucket, key, expires=timedelta(minutes=30))`；`presign_get`：`presigned_get_object(bucket, key, expires=timedelta(seconds=expires))`。
- [x] 4. 测试 `backend/tests/test_storage.py`：单测 `normalize_key`（中文名→规范化、超长截断）；`presign_get`/`presign_put` 用 monkeypatch 假 minio 客户端断言参数透传（不连真实 MinIO，除非环境可用）。
- [x] 5. 提交 `feat: MinIO storage client with key normalization`。

**测试/验证：** `test_storage.py` 全绿。真实 MinIO 冒烟（可选）：presign_put 返回 `upload_url` 且可 PUT。

---

### Task 5: 认证（JWT + pwdlib）+ users 端点 + 依赖注入

**Files:**
- Create: `backend/app/core/security.py`、`backend/app/api/deps.py`、`backend/app/api/v1/auth.py`
- Modify: `backend/app/api/v1/router.py`（挂 auth）

**Interfaces:**
- Produces: `security.hash_password(plain) -> str`；`security.verify_password(plain, hash) -> bool`；`security.create_access_token(user) -> str`（JWT，sub=user.id，exp=`access_token_expire_minutes`）；`deps.get_current_user`（FastAPI 依赖 → `User` 或 401）；`auth.py` 端点：
  - `POST /auth/login` body `{username, password}` → `ok({access_token, token_type:"bearer", user:{id,username,display_name,role,avatar}})`；密码错/用户不存在 → 401 `err(40100, "用户名或密码错误")`。
  - `GET /auth/me`（需登录）→ `ok(user)`。
- Consumes: `User` 模型、`get_session`、`settings`。

**Steps:**

- [x] 1. `security.py`：`PasswordHash.recommended()`（pwdlib argon2）+ `create_access_token`/`decode_token`（PyJWT `HS256`）。
- [x] 2. `deps.py`：`get_current_user(session=Depends(get_session), authorization: str = Header(None))`：解析 `Bearer <token>` → decode → 查 `users.id` → 返回 user；失败抛 `HTTPException(401, ...)`（统一信封由 Task 3 handler 兜）。
- [x] 3. `auth.py`：login/me。
- [x] 4. 测试 `backend/tests/test_auth.py`：SQLite 内存建表 + 插一个用户（hash）；`POST /auth/login` 正确 → 200 + token；错误密码 → 401；`GET /auth/me` 带/不带 token。**登录请求体的日志脱敏**：中间件 `POST /auth/login` 只记用户名（§2.4）——在 logging.py 里实现，本任务补断言（可选）。
- [x] 5. 提交 `feat: JWT auth with login/me endpoints`。

**测试/验证：** `test_auth.py` 全绿（用 SQLite 内存 + TestClient 依赖覆盖）。

---

### Task 6: 启动 seed（管理员 + 与前端 mock 对齐的演示数据）

**Files:**
- Create: `backend/app/core/seed.py`、`backend/tests/test_seed.py`
- Modify: `backend/app/main.py`（lifespan 调 seed）

**Interfaces:**
- Produces: `seed.seed_all(session)`（幂等：已存在则跳过）；`seed.seed_admin(session)`；`seed.seed_demo(session)`。
- Consumes: 全部模型、`settings.admin_username/admin_password`。

**Steps:**

- [x] 1. `seed_admin`：若无 `users.username == admin_username` 则插入（`display_name="林工"`、`role="admin"`）。
- [x] 2. `seed_demo`（**数值对齐 `src/App.tsx` 常量 + `docs/API接口清单.md` §2 实体**）：
  - `label_categories`：焊瘤/气孔/未熔合/咬边/正常 + 展示色。
  - 4 条焊缝 `data_records`（照抄 App.tsx `weldRows`：`WLD-20260815-0248` 等，含 `weld_name`/`source`/`machine`/`weld_method`/`material`/`thickness`/`current_voltage`/`sample_rate`/`product`/`modalities`/`quality`/`operator`/`storage_bytes`）。
  - 每条焊缝的版本链：v1.0 原始数据 → v1.1 去噪处理 → v1.2 时间对齐 → v1.3 人工修正（对齐 App.tsx VersionPanel），并维护 `latest_version_id`；v1.0 的 `object_keys` 填 `raw/{registration_no}/...` 示例键。
  - 核验报告：对其中一条焊（如 0248）写 `validation_reports`（score 93.3, passed 14, warning 1, failed 0, duration 2.8）+ 15 条 `validation_rule_results`（规则名照抄 App.tsx `Validation` 组件的 15 项，第 9 项「视频帧率稳定性」= warning）。
  - 3 个 `datasets` + `dataset_versions`（照抄 App.tsx `datasetRows`：DS-DEFECT-001 等，split `{"train":6736,"val":842,"test":842}`、quality JSON）+ `current_version_id`。
  - 3 个 `models` + `model_versions`（照抄 `ModelRepository`：焊接异常检测模型 v1.8 F1 95.5% 生产候选 等）。
  - 1 条 `dataset_build_tasks`/`split_tasks`/`annotation_tasks` + 少量 `samples` + `annotations`（供标注页演示）。
  - `audit_logs` 若干条示例。
- [x] 3. `main.py` lifespan：`with Session(engine) as s: seed_all(s)`。
- [x] 4. 测试 `test_seed.py`（SQLite 内存）：`seed_all` 两次幂等（数量不翻倍）；断言 `label_categories` 5 个、welds 4 条、models 3 个、0248 的 validation_rule_results 15 条。
- [x] 5. 提交 `feat: startup seed with admin and demo data`。

**测试/验证：** `test_seed.py` 全绿；真实 MySQL `seed_all` 可重复执行。

---

## 阶段 B — 后端领域接口（同步域）

> 每个域：路由文件 → service → 测试。CRUD 模式统一：`Depends(get_session)`、`Depends(get_current_user)`（业务接口全部需登录，见 API 清单）、`ok(...)`/`err(...)`。

### Task 7: Jobs（通用 Job 服务 + `GET /jobs/{job_id}`）

**Files:**
- Create: `backend/app/services/__init__.py`、`backend/app/services/jobs.py`、`backend/app/api/v1/jobs.py`、`backend/tests/test_jobs.py`
- Modify: `router.py`（挂 jobs）

**Interfaces:**
- Produces: `jobs.create_job(session, type, result=None) -> Job`（`job_uid=f"job_{uuid4().hex[:8]}"`，status=pending）；`jobs.mark_running/complete/failed(job, ...)`；`jobs.get_job_by_uid(session, uid) -> Job`；端点 `GET /jobs/{job_id}`（job_id=`job_uid`）→ `ok({id,type,status,progress,result,error,created_at,finished_at})`（404 若不存在，业务码 40401）。
- Consumes: `Job` 模型、`get_session`。

**Steps:**

- [x] 1. `services/jobs.py` 实现 CRUD + 状态机（pending→running→succeeded/failed）。
- [x] 2. 端点 `GET /jobs/{job_id}`（返回体形状照 `docs/API接口清单.md` §1.5 的 Job JSON）。
- [x] 3. 测试：`test_jobs.py` 建 job → 断言 `job_uid` 前缀 `job_`、状态流转、`GET /jobs/{uid}` 信封。
- [x] 4. 提交 `feat: unified job service and polling endpoint`。

**测试/验证：** `test_jobs.py` 全绿。

---

### Task 8: Dashboard（stats / attributes / distributions / projects）

**Files:**
- Create: `backend/app/services/dashboard.py`、`backend/app/api/v1/dashboard.py`、`backend/tests/test_dashboard.py`
- Modify: `router.py`（挂 dashboard）

**Interfaces:**
- Produces 四个端点（均需登录）：
  - `GET /dashboard/stats` → `ok({data_total, manufacturer_total, max_storage_bytes, annotated_samples, annotation_completion, ...})`——统计卡四项（数据总量/厂商总量/单条最大容量/已标注样本+完成度），数值从表聚合。
  - `GET /dashboard/attributes` → `ok({weld_methods[], defect_types[], modalities[], sample_rate_tiers[]})`（焊机种类/缺陷种类/多模态种类/采集频率档位——与 App.tsx 属性面板字段对齐）。
  - `GET /dashboard/distributions` → `ok({manufacturers[], transition_types[], welding_types[], defects[], wordcloud[]})`（分布图数据；缺陷用**统计口径**词表含未焊透/焊穿/夹渣等）。
  - `GET /dashboard/projects` → `ok(projects[])`（从 `datasets` 派生：name/status/sample_count/progress/updated_at）。
- Consumes: `data_records`、`datasets`、`samples`/`annotations` 等表。

**Steps:**

- [x] 1. service 聚合查询 + 形状对齐 App.tsx `Overview` 消费的常量（`manufacturers`/`defectTypes`/`wordCloud`/`projects` 等）。
- [x] 2. 四个端点。
- [x] 3. 测试（SQLite + seed_demo）：`stats.data_total == 4`、`projects` 3 条、`attributes.defect_types` 非空、`distributions.defects` 含统计词表。
- [x] 4. 提交 `feat: dashboard stats/attributes/distributions/projects`。

**测试/验证：** `test_dashboard.py` 全绿。

---

### Task 9: Files（upload / presign-upload / url）

**Files:**
- Create: `backend/app/api/v1/files.py`、`backend/tests/test_files.py`

**Interfaces:**
- Produces：
  - `POST /files/upload`（multipart `file`，需登录；小文件 <100MB 代理）→ 存 `uploads/{uuid}/{filename}`（或调用方指定 prefix）→ `ok({object_key, url})`。
  - `POST /files/presign-upload` body `{size, content_type, prefix}` → 校验 `size <= 2GB`（含 100MB 阈值判断由前端选路）→ `ok({object_key, upload_url})`。
  - `GET /files/{object_key}/url?expires=` → `ok({url})`（object_key 含 `/`，路由需 `:path` 或 query 传 key——用 query 传 key 更稳，文档路径含 key 时用 `{object_key:path}`）。
- Consumes: `StorageClient`、`get_session`。

**Steps:**

- [x] 1. 上传（`UploadFile` 流式写入 MinIO）+ 预签名 + 下载 URL。
- [x] 2. 测试（monkeypatch StorageClient）：三端点行为与信封；size>2GB → 400/422。
- [x] 3. 提交 `feat: file upload, presign and download url`。

**测试/验证：** `test_files.py` 全绿；真实 MinIO（可选）小文件上传→GET url→下载字节一致。

---

### Task 10: Welds 数据列表/登记/版本/核验（核心 CRUD）

**Files:**
- Create: `backend/app/services/welds.py`、`backend/app/api/v1/welds.py`、`backend/tests/test_welds.py`

**Interfaces:**
- Produces（端点全对齐 `docs/API接口清单.md` §3.3，均需登录）：
  - `GET /welds` query `{q, source, brand, status, tab, page, page_size}` → 服务端筛选 + 分页，按焊缝 ID 去重、只返回最新版本信息（直接查 `data_records` 含 `latest_version_id`）。`tab` ∈ 全部最新/待核验/已归档/最近。
  - `GET /welds/{weld_id}`（weld_id 业务号）→ 单条详情。
  - `POST /registrations` body（`source`, `collected_at`, `weld_name`, `product`, `machine`, `weld_method`, `material`, `thickness`, `current_voltage`, `sample_rate`）→ 事务内插 `data_records`（生成 `WLD-YYYYMMDD-序号` 与 `REG-YYYYMMDD-序号`，`operator`=当前用户，`modalities=[]`，`quality='待复核'`）+ 插 `data_versions`(v1.0, action=原始数据) + 更新 `latest_version_id` → `ok(registration)`。
  - `GET /registrations/{id}`；`PATCH /registrations/{id}`（部分字段）。
  - `POST /registrations/{id}/raw-files` body `{object_keys[]}` → 回填 v1.0 `data_versions.object_keys` + 累加 `storage_bytes`（调用方传 `storage_bytes` 或按 size 合计；设计里 storage_bytes 由该端点按 key 查 MinIO size 或由 body 提供——**定：body 增加可选 `storage_bytes`，缺省 0**）。
  - `GET /welds/{weld_id}/versions` → 版本链（含 operator/created_at/action）。
  - `GET /welds/{weld_id}/versions/{version_id}`（version_id=DB id）。
  - `POST /welds/{weld_id}/versions` body `{action('去噪处理'|'人工修正'), note?, object_keys[]?}` → 事务内插版本 + 更新 latest_version_id。
  - `POST /welds/{weld_id}/versions/{version_id}/validation`（同步，15 项规则）→ 写 report + rule_results，按规则回写 `data_records.quality`（失败>0→异常、仅警告→待复核、否则→通过）→ `ok(report)`。
  - `GET /welds/{weld_id}/versions/{version_id}/validation` → report + 明细。
- Consumes: `data_records`/`data_versions`/`validation_reports`/`validation_rule_results`、`write_audit`、`get_current_user`、`paginate`。

**Steps:**

- [x] 1. 业务号生成器（`WLD-YYYYMMDD-序号`：同日序号 = 当日 weld_id 数+1；registration 同理）。
- [x] 2. 列表筛选：`q` 匹配 `weld_id`/`registration_no`（LIKE）；`source`/`brand` 精确或前缀；`status` 映射 quality（通过/待复核/异常）；`tab` 映射（最近=按 created_at 排序前 N；待核验=quality='待复核'；已归档=...）；全部分页。
- [x] 3. 登记 + raw-files + 版本 + 核验（核验规则引擎：15 项规则给确定性结果——基于版本/文件存在性 + 部分随机种子，规则名照抄 App.tsx）。
- [x] 4. `POST /registrations`、`POST /welds/{id}/versions`、`POST .../validation` 内调用 `write_audit`。
- [x] 5. 测试 `test_welds.py`：登记事务（record+v1.0+latest 联动）；列表去重与筛选；版本链；核验后 quality 级联（失败>0→异常）。用 SQLite + seed_demo。
- [x] 6. 提交 `feat: welds CRUD, registration, versions, validation`。

**测试/验证：** `test_welds.py` 全绿；`uvicorn` 起服务后 `POST /registrations` 真实返回 `REG-YYYYMMDD-00X`。

---

### Task 11: Analysis — candidates / signals / DSP 真实实现

**Files:**
- Create: `backend/app/services/dsp.py`、`backend/app/services/signals.py`、`backend/app/api/v1/analysis.py`、`backend/tests/test_dsp.py`、`backend/tests/test_analysis.py`

**Interfaces:**
- Produces（对齐 `docs/API接口清单.md` §3.4）：
  - `GET /analysis/candidates` → 已登记且核验通过（quality=通过）的可分析数据列表。
  - `GET /welds/{weld_id}/versions/{version_id}/signals?channels[]=&filter_type=&cutoff=&cutoff2=` → `ok({duration, sample_rate, channels:[{id,name,unit,values[],lo,hi}], events:{arc,weld_segment,tail}, anomalies:[...]})`。信号由 `signals.py` 按 weld 确定性生成（复刻 App.tsx 的起弧/稳态/收弧 + 两个异常区段形态），再按 `filter_type/cutoff` 真实滤波。
  - `GET /welds/{weld_id}/versions/{version_id}/analysis/{mode}?channel=&filter_type=&cutoff=&cutoff2=`，`mode ∈ psd|stft|dwt|wavelet|phase|pdd` → 各返回真实计算数组。
  - `GET /welds/{weld_id}/versions/{version_id}/analysis/result` → `ok({stability, segments:{normal,arc_instability,sputter}, anomalies:[{start,end,type}]})`（模拟结果，区段来自信号生成器的 anomalies）。
- Consumes: `dsp.py`、`signals.py`、`get_session`。

**Steps:**

- [x] 1. `dsp.py`（真实 DSP，输入 np 数组 + 采样率）：
  - `filter_signal(x, fs, kind, cutoff, cutoff2)` → scipy `butter` + `sosfiltfilt`（kind ∈ 低通/高通/带通，cutoff 归一化）。
  - `compute_psd(x, fs)` → `scipy.signal.welch` → `{freqs, psd}`。
  - `compute_stft(x, fs)` → `scipy.signal.stft` → `{times, freqs, magnitude(2D)}`（幅度取 `|Z|`）。
  - `compute_dwt(x, level=4, wavelet='db4')` → `pywt.wavedec` → `{bands:[{name,values}], approx:{name,values}}`（D1..D4 + A4）。
  - `wavelet_decomp(x, level=5)` → 多层细节分量（`pywt.wavedec` 每层重构或系数），`{bands:[{name,values}]}`。
  - `phase_trajectory(cur, vol)` → `{current:[], voltage:[]}`（供 UI 相图）。
  - `pdd_density(x, bins=28)` → `{bins:[], counts:[], kde:[]}`。
- [x] 2. `signals.py`：`generate_signals(weld_id) -> SignalBundle`——确定性（hash(weld_id) 做种子），按 App.tsx `currentAmp/voltVal/gasVal/wireVal` 同形态生成 4 通道、duration 5.42s、sample_rate 默认 1000Hz；含 `events{arc:0.42, weld_segment:[0.78,4.28], tail:4.86}` 与 `anomalies`（[1.92,2.34] 电弧不稳、[3.58,3.86] 飞溅倾向）。采样点数大，前端渲染由 api 层降采样（见 Task 19）。
- [x] 3. 六个 mode 端点（调 dsp + signals，支持滤波参数联动）。
- [x] 4. 测试 `test_dsp.py`：`filter_signal` 对白噪声低频保留/高频衰减（能量比断言）；`compute_psd` 对 50Hz 正弦在 50Hz 有峰；`compute_dwt` 层数=5；`pdd_density` 和为样本数。`test_analysis.py`：candidates 只含通过；signals 4 通道、anomalies 2 个；mode 端点返回形状。
- [x] 5. 提交 `feat: real DSP service and analysis endpoints`。

**测试/验证：** `test_dsp.py`/`test_analysis.py` 全绿。数值要与 App.tsx 演示形态可对应（前端降采样后图形相似）。

---

### Task 12: Feature 提取（真实）+ 端点

**Files:**
- Create: `backend/app/services/features.py`、`backend/tests/test_features.py`
- Modify: `backend/app/api/v1/analysis.py`（加 `/features/extract`、`/features/{extraction_id}`）

**Interfaces:**
- Produces（对齐 `API接口清单.md` §3.4）：
  - `POST /features/extract` body `{weld_id, version_id, normalization, format}`（同步）→ 真实计算三类特征 + 统一向量 → 落 `feature_extractions` 表 → `ok(extraction)`。
  - `GET /features/{extraction_id}` → `ok(extraction)`。
  - 特征形状对齐 App.tsx `tsFeatures`（均值/方差/峰值/偏度/峰度/RMS/FFT主频/小波能量 × 4 通道 = 8×4）、`visionFeatures`（熔池面积/周长/长宽比/圆形度/灰度均值/GLCM 对比度/GLCM 能量/边缘梯度 = 8）、`audioFeatures`（频带能量/功率/PSD/质心频率/频谱滚降/过零率 = 6）、`unifiedVector`（分组维度：8+8+6+6+4+4+6=42 维）。
- Consumes: `dsp.py`、`signals.py`、`skimage.measure.regionprops`/`graycomatrix`、`librosa`、`FeatureExtraction` 模型。

**Steps:**

- [x] 1. `features.py`：
  - `ts_features(x)` → 8 个统计/频域/时频特征（numpy/scipy/pywt）。
  - `vision_features()` → 用模拟掩膜在 skimage 上真实计算 regionprops + GLCM + Sobel（演示数据 → 生成合成熔池二值图）。
  - `audio_features(x)` → librosa：频带能量、spectral centroid/rolloff、过零率、总 PSD。
  - `unify(ts, vis, audio, normalization, format)` → 拼接 42 维 + 归一化（Z-Score/Min-Max/L2/无）+ `format`（NPY/CSV/JSON/PT——当前仅存 JSON 元数据，导出另说）。
- [x] 2. 端点（同步）+ 落库（`created_at`）。
- [x] 3. 测试：`ts_features` 长度 8、`unified_vector.dims == 42`、normalization 生效、`GET /features/{id}` 信封。
- [x] 4. 提交 `feat: real multi-modal feature extraction`。

**测试/验证：** `test_features.py` 全绿。

---

## 阶段 C — 异步任务与模型中心

> 异步统一模式：`POST` 建 `jobs`(pending) + 域任务表(1:1) → 返回 `{job_id}`；轮询 `GET /jobs/{id}`。执行器 `app/jobs/executor.py` 负责状态机与结果回填。

### Task 13: Job 执行器（DB 轮询）+ 对齐任务（模拟）

**Files:**
- Create: `backend/app/jobs/__init__.py`、`backend/app/jobs/executor.py`、`backend/app/jobs/alignment.py`、`backend/app/services/alignment.py`、`backend/tests/test_alignment.py`
- Modify: `backend/app/main.py`（lifespan 启动 executor 线程）、`backend/app/api/v1/analysis.py`（alignment-tasks 端点）

**Interfaces:**
- Produces：
  - `executor.start()/stop()`（后台线程每 ~1s 轮询 pending 的 job，dispatch 到对应 handler）；`executor.run_job(job_uid)`（测试/手动同步执行）。
  - `alignment.handle(job, session)`：模拟（进度 0→100，期间 `session.commit()` 更新 progress）→ 成功：写 `alignment_tasks.events/tracks/assets`（assets 对象键 `processed/{weld_id}/align/...`）→ **事务内自动生成 `data_versions(action=时间对齐)` + 更新 `latest_version_id`** → 回填 `jobs.result`。
  - 端点：`POST /welds/{weld_id}/versions/{version_id}/alignment-tasks` body `{modalities[]}` → `ok({job_id})`；`GET /alignment-tasks/{task_id}`（job_uid）→ Job 信封（含 `assets`）。
- Consumes: Task 7 jobs、Task 10 welds 服务。

**Steps:**

- [x] 1. `executor.py`：线程轮询 + `run_job` 同步入口 + 每域 handler 注册表；异常 → `jobs.error` 记录 + status=failed。
- [x] 2. `alignment.py` handler（模拟对齐；结果结构照 `API接口清单.md` §3.4：events{arc,weld_segment,tail}、tracks[]、assets[]）。
- [x] 3. 端点 + 自动生成时间对齐版本。
- [x] 4. 测试：`run_job` 后 status=succeeded、`alignment_tasks.assets` 非空、**自动多出 v1.4 时间对齐版本且 latest_version_id 更新**、`jobs.result` 有 events。
- [x] 5. 提交 `feat: job executor + alignment task`。

**测试/验证：** `test_alignment.py` 全绿。

### Task 14: Split（切分，模拟）+ Annotation（标注，模拟）

**Files:**
- Create: `backend/app/jobs/split.py`、`backend/app/services/annotation.py`、`backend/app/jobs/annotation.py`、`backend/tests/test_split_annotation.py`
- Modify: `backend/app/api/v1/analysis.py`

**Interfaces:**
- Produces：
  - `POST /welds/{weld_id}/versions/{version_id}/split-tasks` body `{fixed_rate, keep_event_buffer, task_format}` → `{job_id}`；`GET /split-tasks/{task_id}` → Job（result 含 `sample_count`，成功后按固定频率/事件缓冲在 `samples` 表生成样本，`object_keys` 用 `processed/{weld_id}/split/...`）。
  - `GET /label-categories` → `ok(label_categories)`（模型口径 5 类）。
  - `POST /annotation-tasks` body `{source('split_task'|'manual'), split_task_id?, name?}` → `{job_id}`；job 成功时把来源样本的 `annotation_task_id` 指向新任务。
  - `POST /annotation-tasks/{id}/import` body `{source('files'|'split_task'), object_keys[]?, split_task_id?}`。
  - `GET /annotation-tasks/{id}/samples?page=&page_size=` → Page[sample]（含 `annotations`）；`GET /annotation-tasks/{id}/samples/{sample_id}` → sample + 最新 labels + `confidence`（预标注平均置信度，人工修正后取最新）。
  - `POST /annotation-tasks/{id}/samples/{sample_id}/ai-pretag`（同步）→ `ok(annotations[])`（模拟：2 个疑似区域 + 置信度）。
  - `POST /annotation-tasks/{id}/samples/{sample_id}/labels` body `{labels[]}`（category+box）→ 覆盖写 `annotations`（annotator=当前用户）。
  - `GET /annotation-tasks/{task_id}` → Job。
- Consumes: Task 7 jobs、`samples`/`annotations`/`label_categories` 模型。

**Steps:**

- [x] 1. split handler（按规则生成 sample_count + 每样本 frame_no + object_keys）。
- [x] 2. annotation create/import/samples/detail/ai-pretag/labels + label-categories。
- [x] 3. 测试：split 成功生成样本（`sample_count` 回填）；create annotation task 后样本归属更新；ai-pretag 返回 2 个；save label 后可 GET 回读；confidence 语义。
- [x] 4. 提交 `feat: split and annotation tasks`。

**测试/验证：** `test_split_annotation.py` 全绿。

### Task 15: Datasets + 构建任务 + dimensions/readiness/lineage

**Files:**
- Create: `backend/app/services/datasets.py`、`backend/app/jobs/dataset_build.py`、`backend/app/api/v1/datasets.py`、`backend/tests/test_datasets.py`

**Interfaces:**
- Produces（对齐 `API接口清单.md` §3.5）：
  - `GET /datasets`、`POST /datasets`（`{name, task, source?}`）、`GET /datasets/{id}`。
  - `GET /datasets/{id}/dimensions` → `[{name, status('已具备'|'缺失'|'必需'), required}]`（7 维度：Voltage/GasSpeed/Current/Molten_feature/Sound_feature/焊缝照片/熔池视频，按 task 判必需）。
  - `GET /datasets/{id}/readiness` → `{readiness: 可训练|暂不可训练, checks:[{name, passed}]}`（按 task 动态，照 App.tsx `ModelReadiness`）。
  - `GET /datasets/{id}/versions`；`POST /datasets/{id}/versions` `{name, note}` → 新建 dataset_versions（固定快照 vN）；`GET /datasets/{id}/versions/{vid}`。
  - `POST /datasets/{id}/versions/{vid}/build-tasks` body `{source}` → `{job_id}`；job 成功：生成 `dataset_items`（固定样本清单 + split 划分，**按焊缝 ID 分组避免泄漏**）+ 计算 `dataset_versions.quality`（重复率/空标注率/维度缺失）+ `snapshot_id`（`datasets/{dataset_version_id}/{snapshot}.json` 写 MinIO）+ 更新 `datasets.current_version_id`/`sample_count`。
  - `GET /datasets/{id}/lineage` → `[{原始焊缝, 标注任务, 数据集版本, 模型训练}]` 血缘节点。
- Consumes: `samples`/`annotation_tasks`/`dataset_*` 模型、`StorageClient`。

**Steps:**

- [x] 1. CRUD + dimensions/readiness（按 task 规则表，字段照 App.tsx `requiredByTask`/`inputDimensions`）。
- [x] 2. build handler：分片策略 `ORDER BY record_id` 分组 → train/val/test（默认 8:1:1），固定 `dataset_items`；quality 计算；snapshot 写 MinIO。
- [x] 3. lineage：沿 `dataset_items→samples→annotation_tasks→split_tasks→data_records` + `training_tasks→model_versions` 组装。
- [x] 4. 测试：build 后 `dataset_items` 数量正确、split 全 3 类、同焊缝样本不跨 split、quality 有重复率字段；lineage 有 4 层。
- [x] 5. 提交 `feat: datasets, build tasks, dimensions/readiness/lineage`。

**测试/验证：** `test_datasets.py` 全绿。

### Task 16: Models + 训练/测试/推理任务（模拟）

**Files:**
- Create: `backend/app/services/models.py`、`backend/app/api/v1/models.py`、`backend/app/jobs/training.py`、`backend/app/jobs/testing.py`、`backend/app/jobs/inference.py`、`backend/tests/test_models.py`

**Interfaces:**
- Produces（对齐 `API接口清单.md` §3.6）：
  - `GET /models` → `ok({summary:{total, prod_candidates, recent_training}, models[]})`；`GET /models/{id}`；`POST /models` `{name, type, description?}`；`PATCH /models/{id}/versions/{vid}` `{status?, note?}`（状态流转）。
  - `POST /training-tasks` body `{dataset_version_id, base_model_id, epochs, batch_size, learning_rate, val_ratio, ...}` → `{job_id}`；`GET /training-tasks/{task_id}` → Job（result 含 `metrics{mAP50, precision, recall}` + `loss_curve{train[], val[]}` + `progress`）；`GET /training-tasks/{task_id}/logs` → `ok(log_text)`。**训练成功自动生成 `model_versions`（status=实验版本）+ 权重写 `models/{model_version_id}/weights.pt`**。
  - `POST /test-tasks` `{model_version_id, dataset_version_id, tasks[]}` → `{job_id}`；`GET /test-tasks/{task_id}` → Job（result：accuracy/recall/f1/latency + confusion_matrix）。
  - `POST /inference-tasks` `{model_version_id, input, input_type}` → `{job_id}`；`GET /inference-tasks/{task_id}` → Job（result：boxes/categories/confidence/latency）。
- Consumes: Task 7 jobs、Task 15 datasets、`models`/`model_versions`。

**Steps:**

- [x] 1. models CRUD + 状态流转（PATCH 校验状态枚举：生产候选/训练中/实验版本）。
- [x] 2. training handler：模拟训练（进度 + 损失曲线 + 指标收敛）+ 事务内生成 model_version + weights.pt（MinIO）+ 更新模型 summary。
- [x] 3. testing / inference handler（模拟结果，形状照 `ModelTest`/`InferencePanel`）。
- [x] 4. 测试：POST /models 落库；training `run_job` 后 `model_versions` 多一条实验版本 + `file_key` 形如 `models/{id}/weights.pt`；PATCH 流转到生产候选；test 返回混淆矩阵 2×2；inference result 有 boxes。
- [x] 5. 提交 `feat: model center with training/test/inference tasks`。

**测试/验证：** `test_models.py` 全绿。

### Task 17: Reports 导出（通用）

**Files:**
- Create: `backend/app/services/reports.py`、`backend/app/api/v1/reports.py`、`backend/tests/test_reports.py`

**Interfaces:**
- Produces：`POST /reports/export` body `{type('validation'|'analysis'|'annotation'|'features'|'test'|'data-list'), ref_ids[], format('pdf'|'json')}` → 生成报告（Jinja2 模板 + xhtml2pdf）→ 写 `reports/{type}/{ref_id}.pdf` → `ok({url})`（预签名）。format=json 时直接 `reports/{type}/{ref_id}.json`。
- Consumes: `StorageClient`、对应业务表（validation_reports、feature_extractions、test 指标等）。

**Steps:**

- [x] 1. 每类报告的模板 + 数据装配（至少 validation 与 data-list 有真实模板，其余可复用同构模板）。
- [x] 2. 端点。
- [x] 3. 测试：`type=validation, ref_ids=[report_id], format=json` 返回 url；`type=data-list` 返回 url；minio 写入用 monkeypatch。
- [x] 4. 提交 `feat: generic report export`。

**测试/验证：** `test_reports.py` 全绿；真实环境（可选）导出 PDF 可下载。

---

## 阶段 D — 前端接口层与全链路接线

> 前端无测试框架 → 每个任务验证 = `npm run typecheck` + `npm run build` + `npm run lint`（后两项可在任务内运行）。

### Task 18: vite proxy + client.ts + types.ts

**Files:**
- Create: `src/api/CLAUDE.md`、`src/api/client.ts`、`src/api/types.ts`
- Modify: `vite.config.ts`（加 `/api` proxy → `http://localhost:8000`）、`src/CLAUDE.md`

**Interfaces:**
- Produces：
  - `vite.config.ts`：`server: { proxy: { '/api': { target: 'http://localhost:8000', changeOrigin: true } } }`。
  - `client.ts`：`request<T>(path, options) -> Promise<T>`——base `/api/v1`、注入 `Authorization: Bearer <localStorage token>`、解包 `{code,message,data}`、`code!==0` 抛带 message 的 `ApiError`、401 → `clearToken()` + `window.location.reload()`（App 重新挂载即回到登录页）；`setToken(token)`/`getToken()`/`clearToken()`。
  - `types.ts`：全部实体类型（`User, DataRecord, DataVersion, ValidationReport, ValidationRuleResult, Job<T>, AlignmentResult, SplitResult, Sample, Annotation, LabelCategory, FeatureExtraction, Dataset, DatasetVersion, DatasetItem, Project, Model, ModelVersion, TrainingResult, TestResult, InferenceResult, DashboardStats/Attributes/Distributions, Page<T>, SignalData, AnalysisViewData, AnalysisResult, ...`），字段形状照 `docs/API接口清单.md` §2 与 §1.5。
- Consumes: 契约文档（字段名）。

**Steps:**

- [x] 1. `client.ts` 实现（fetch + 信封解包 + 401 处理 + `ApiError`）。不引 axios。
- [x] 2. `types.ts` 逐实体写（与后端响应形状一致；`Page<T>={items,total,page,page_size}`；`Job<T>={id,type,status,progress,result,error,created_at,finished_at}`）。
- [x] 3. `vite.config.ts` proxy。
- [x] 4. 验证：`npm run typecheck` 通过；`npm run build` 通过。
- [x] 5. 提交 `feat: frontend api client and types`。

**测试/验证：** typecheck + build 全绿；启动 vite dev 后 `fetch('/api/v1/health')` 经 proxy 命中后端。

### Task 19: 前端 api 模块（9 个域文件）

**Files:**
- Create: `src/api/auth.ts`、`src/api/dashboard.ts`、`src/api/welds.ts`、`src/api/analysis.ts`、`src/api/datasets.ts`、`src/api/models.ts`、`src/api/files.ts`、`src/api/jobs.ts`、`src/api/reports.ts`

**Interfaces:**
- Produces：**函数签名照 `docs/API接口清单.md` §4.2 逐字实现**（`login`, `getMe`, `getStats`…`exportReport`），一律返回类型化 Promise，路径相对 `/api/v1`。关键签名预览（完整见文档 §4.2）：
  - `welds.ts`: `listWelds(params: WeldListQuery): Promise<Page<DataRecord>>`、`createRegistration(body): Promise<Registration>`、`attachRawFiles(id, objectKeys): Promise<DataVersion>`、`listVersions(weldId)`, `createVersion(weldId, body)`, `runValidation(weldId, versionId)`, `getValidation(...)`。
  - `analysis.ts`: `getSignals(weldId, versionId, opts): Promise<SignalData>`（**前端对 `channels[].values` 做降采样到 ≤512 点**再返回，供图表渲染）、`getAnalysisMode(weldId, versionId, mode, channel, filter?)`、`getAnalysisResult(...)`、`createAlignmentTask/createSplitTask/createAnnotationTask/importAnnotationSamples/listAnnotationSamples/getAnnotationSample/aiPretag/saveAnnotation/extractFeatures/getFeatureExtraction/listCandidates/listLabelCategories`。
  - `datasets.ts`: `listDatasets/createDataset/getDataset/getDimensions/getReadiness/listDatasetVersions/createDatasetVersion/getDatasetVersion/getLineage/createBuildTask`。
  - `models.ts`: `listModels/getModel/createModel/updateModelVersionStatus/createTrainingTask/getTrainingTask/getTrainingLogs/createTestTask/getTestTask/createInferenceTask/getInferenceTask`。
  - `files.ts`: `uploadFile/presignUpload/getFileUrl`；`jobs.ts`: `getJob`；`reports.ts`: `exportReport`；`auth.ts`: `login/getMe`；`dashboard.ts`: `getStats/getAttributes/getDistributions/getProjects`。

**Steps:**

- [x] 1. 依 §4.2 逐文件实现（每个函数一行式 `request(...)` 转发；`WeldListQuery`/`SignalQuery`/`SplitRules`/`FeatureExtractRequest`/`TrainingConfig`/`TestConfig`/`InferenceRequest`/`ExportRequest` 等参数类型在 `types.ts` 补齐）。
- [x] 2. 验证：`npm run typecheck` + `npm run build` + `npm run lint`。
- [x] 3. 提交 `feat: frontend api modules per contract`。

**测试/验证：** typecheck/build/lint 全绿；`npx tsc --noEmit` 无未使用类型。

### Task 20: hooks/useJob + 最小登录页 + App 登录闸门

**Files:**
- Create: `src/hooks/CLAUDE.md`、`src/hooks/useJob.ts`、`src/pages/CLAUDE.md`、`src/pages/Login.tsx`
- Modify: `src/App.tsx`（最外层登录闸门：无 token → 渲染 `<Login/>`，登录成功后渲染现有 `<AppShell/>`；**不重构现有 UI 结构**）

**Interfaces:**
- Produces：
  - `useJob(jobId: string | null, intervalMs=1500)` → `{job, status, progress, error, start, stop}`：轮询 `jobs.getJob`，`succeeded/failed` 停；jobId 空 → 不轮询。返回 `result` 泛型。
  - `Login`：`login(username,password)` 成功 → `setToken(access_token)` + 存储 user → 通知外层。表单两输入 + 提交 + 错误提示（复用 index.css 现有 class，若无可加最小内联样式，**不引 UI 库**）。
  - `App.tsx`：`const [token, setToken] = useState(getToken())`；`if (!token) return <Login onLogin={(t)=>setToken(t)} />`；现有 App 函数体改名 `AppShell`（或包一层），保证布局/导航零改动。

**Steps:**

- [x] 1. `useJob.ts` 实现。
- [x] 2. `Login.tsx` 实现（调 `auth.login`；成功后 `setToken` + `auth.getMe` 存 user 到 localStorage）。
- [x] 3. `App.tsx` 登录闸门（最小侵入：包一层，不改内部组件）。
- [x] 4. 验证：typecheck/build/lint；`npm run dev` 打开 → 无 token 见登录页，登录后见原界面。
- [x] 5. 提交 `feat: login page, auth gate, useJob hook`。

**测试/验证：** typecheck/build/lint 全绿；dev 手动冒烟登录→总览。

### Task 21: 接线「数据总览」+「数据列表/选中上下文」

**Files:**
- Modify: `src/App.tsx`（`Overview`、`ManagementFiltered`、`SelectionContext` 的数据源）

**Approach（本阶段统一模式，后续任务沿用）：**
1. 每个页面组件新增 `useEffect` + `useState`：初始值 = 现有 mock 常量（UI 永不空白），挂载后调 `api.*`，成功 → 替换数据；失败 → 保留 mock（console.warn）。
2. 只在数据层替换：组件 JSX/className/信息架构**不动**。
3. 类型：把现有 `const weldRows = [...]` 等常量改成 `useState<DataRecord[]>(mockWeldRows)` + `listWelds()` 拉取。mock 常量改名 `mockWeldRows` 等并保留为初始态。

**Steps:**

- [x] 1. `Overview`：四统计卡 ← `getStats()`；属性面板 ← `getAttributes()`；分布图 ← `getDistributions()`（适配：`defectTypes` 用统计词表、`manufacturers/transitionTypes/weldingTypes/wordCloud` 映射）；项目卡片 ← `getProjects()`（progress 字符串化、status 映射 tone）。
- [x] 2. `ManagementFiltered`：列表 ← `listWelds({q, source, brand, tab, page, page_size})`（**服务端筛选**：筛选状态变化时重新拉取，删除前端 filter 逻辑）；tab 计数/分页信息从响应 `total` 取；行点击选中不变。
- [x] 3. `SelectionContext`：← `getWeld(selectedDataId)`（展示 source/machine/version/quality）。
- [x] 4. 验证：typecheck/build；dev 起后端 → 总览显示后端 seed 数值、列表 4 条。
- [x] 5. 提交 `feat: wire overview and data list to API`。

**测试/验证：** typecheck/build 全绿；后端运行 + seed 后，总览统计卡显示 `data_total=4` 等后端值。

### Task 22: 接线「数据中心」其余页（登记/核验/版本/数据集）

**Files:**
- Modify: `src/App.tsx`（`Registration`、`Validation`、`VersionPanel`、`DatasetWorkspace`/`DatasetDetail`/`DatasetInputPanel`/`ModelReadiness`/`DatasetTrainingContext`/`DatasetTestingContext`）

**Steps:**

- [x] 1. `Registration`：提交 ← `createRegistration()`（成功后显示生成的 `REG-...`）；文件上传 ← `presignUpload()`（≥100MB）或 `uploadFile()`（<100MB），上传后 ← `attachRawFiles()`；最近登记 ← `listWelds({tab:'recent'})`。
- [x] 2. `Validation`：执行 ← `runValidation(weldId, versionId)`；明细 ← `getValidation()`（15 规则渲染已有组件结构，含 warning 高亮）。
- [x] 3. `VersionPanel`：← `listVersions(selectedDataId)`；「新建版本」（去噪/人工修正）触发 `createVersion`（UI 若有对应入口则接，无则只读）。
- [x] 4. 数据集：列表/详情 ← `listDatasets/getDataset`；维度 ← `getDimensions`；适配检查 ← `getReadiness`；版本 ← `listDatasetVersions`；血缘 ← `getLineage`；新建版本 ← `createDatasetVersion`；构建 ← `createBuildTask`+`useJob`。
- [x] 5. 验证：typecheck/build。
- [x] 6. 提交 `feat: wire data-center pages to API`。

**测试/验证：** typecheck/build 全绿；登记→列表新增一条、核验→quality 级联可见。

### Task 23: 接线「分析」页（选择/对齐/信号分析/切分/标注/特征）

**Files:**
- Modify: `src/App.tsx`（`AnalysisSelect`、`Alignment`、`AdvancedWeldAnalysis`、`Annotation`、`FeatureExtraction`、及图表组件 `PsdChart/StftHeatmap/DwtChart/WaveletDecomp/PhasePlot/PddChart` 的数据输入）

**Steps:**

- [x] 1. `AnalysisSelect`：候选 ← `listCandidates()`。
- [x] 2. `Alignment`（含 splitOnly 变体）：创建 ← `createAlignmentTask/createSplitTask` + `useJob(getAlignmentTask/getSplitTask)`；任务完成渲染 events/tracks/assets（播放用 `getFileUrl`）。
- [x] 3. `AdvancedWeldAnalysis`：信号 ← `getSignals(...)`（channel 开关/滤波参数联动 query）；六种 mode 视图 ← `getAnalysisMode(mode, channel, filter)`，**图表组件输入改为后端计算数组**：`PsdChart` 吃 `{freqs,psd}`、`StftHeatmap` 吃 `{times,freqs,magnitude}`、`DwtChart`/`WaveletDecomp` 吃 `bands[]`、`PhasePlot` 吃 `{current,voltage}`、`PddChart` 吃 `{bins,counts,kde}`——SVG 渲染逻辑保留、只换数据源；分析结果 ← `getAnalysisResult()`（稳定度/三类占比/异常区段）。
- [x] 4. `Annotation`：标签类别 ← `listLabelCategories()`；样本列表/详情 ← `listAnnotationSamples/getAnnotationSample`；AI 预标注 ← `aiPretag`；保存 ← `saveAnnotation`；缩略图用 `getFileUrl`。
- [x] 5. `FeatureExtraction`：提取 ← `extractFeatures`（归一化/格式参数从 UI 读取）；表数据 ← `getFeatureExtraction` 返回的 ts/vision/audio/unified（映射已有 `tsFeatures` 等表结构）。
- [x] 6. 验证：typecheck/build；dev + 后端 → 分析页各 mode 出真实图、标注样本可读。
- [x] 7. 提交 `feat: wire analysis pages to API with real DSP views`。

**测试/验证：** typecheck/build 全绿；`getSignals` 降采样后波形形态与 mock 相似；PSD 主峰在低频。

### Task 24: 接线「模型中心」+ Toolbar 导出 + 收尾

**Files:**
- Modify: `src/App.tsx`（`ModelRepository`、`Training`、`ModelTest`、`InferencePanel`、`Toolbar`）

**Steps:**

- [x] 1. `ModelRepository`：列表/汇总 ← `listModels()`；「新建模型」← `createModel`（如 UI 有入口）；状态流转 ← `updateModelVersionStatus`（UI 有入口则接）。
- [x] 2. `Training`：配置读取当前数据集（`getDataset`）；开始训练 ← `createTrainingTask` + `useJob(getTrainingTask)`；指标/损失曲线 ← Job result（`metrics`/`loss_curve` 渲染进已有 line-chart，把 SVG 固定 path 换为数据驱动）；日志 ← `getTrainingLogs`。
- [x] 3. `ModelTest`：创建 ← `createTestTask` + `useJob(getTestTask)`；指标/混淆矩阵 ← result。
- [x] 4. `InferencePanel`：上传样本 ← `presignUpload`/`uploadFile`；提交 ← `createInferenceTask` + `useJob(getInferenceTask)`；结果框 ← result。
- [x] 5. `Toolbar`「导出报告/导出结果」：← `exportReport`（type 按页面映射），返回 url 后 `window.open`。
- [x] 6. 验证：typecheck/build/lint。
- [x] 7. 提交 `feat: wire model-center and exports to API`。

**测试/验证：** typecheck/build/lint 全绿。

### Task 25: 文档同步 + CLAUDE.md 补全 + 全链路冒烟

**Files:**
- Modify: `docs/开发规范.md`（§1.1 刻意不复用补「分页自写 helper（envelope 冲突）」；如接口/表/键有偏差，同步 `docs/API接口清单.md`/`数据库设计.md`/`OSS存储设计.md`）、`docs/CLAUDE.md`（补实现状态）、`src/CLAUDE.md`（补 api/hooks/pages）、根 `CLAUDE.md`（补 backend 说明）、`README.md`（本地运行段补「后端先起、前端 proxy」）
- Create: `docs/superpowers/CLAUDE.md`、`backend/tests/CLAUDE.md`、`src/hooks/CLAUDE.md` 等按需

**Steps:**

- [x] 1. 走查三份契约与实现差异，有偏差则回写文档（含分页、任何字段/端点改动）。
- [x] 2. 补齐所有新增目录的 CLAUDE.md（backend/ 各层、src/api、src/hooks、src/pages、docs/superpowers、backend/tests）。
- [x] 3. 全链路冒烟：`cd backend && uv run uvicorn app.main:app --reload` + `npm run dev` → 登录 → 逐页点查（总览统计、列表、登记、核验、版本、对齐、信号分析、切分、标注、特征、数据集、模型、训练、测试、推理、导出）；记录结果到计划附录。
- [x] 4. `npm run build` + `backend uv run pytest` 全绿确认。
- [x] 5. 提交 `docs: sync contracts and CLAUDE.md, integration smoke`。

**测试/验证：** 全链路冒烟通过；pytest + build + lint 全绿。

---

## 验证（端到端）

1. **后端单测**：`cd backend && uv run pytest`（SQLite 内存，全绿）。
2. **后端真实启动**：`uv run uvicorn app.main:app --reload`；`curl /api/v1/auth/login -d '{"username":<admin>,"password":<admin>}'` → 拿 token；带 token 打各列表端点。
3. **前端**：`npm run typecheck && npm run build && npm run lint`。
4. **全链路**：dev + 后端同跑，登录 → 五个一级模块逐页冒烟（对应 Task 25）。
5. **契约一致性**：抽查 5 个端点的响应字段与 `docs/API接口清单.md` §3 一致；抽查 `data_records`/`data_versions`/`jobs` 三表与 `数据库设计.md` §3 一致。

## 风险与决策备忘

- **分页自写**（envelope 冲突）——已入刻意不复用清单，计划内同步文档。
- **前端无测试框架**——以 typecheck/build/lint + 手动冒烟作为质量闸门；SDD 任务评审聚焦 spec 合规与代码质量。
- **真实 DSP 数值与 mock 形态**：信号为确定性生成（hash(weld_id) 种子），波形形态对齐 App.tsx；前端 api 层降采样 ≤512 点。
- **登录页**：条件渲染闸门（不加 react-router）。
- **.env**：补 `SECRET_KEY/ACCESS_TOKEN_EXPIRE_MINUTES/API_LOG_*/ADMIN_USERNAME/ADMIN_PASSWORD`，不触碰既有敏感值。
- **DB 测试**：pytest 全走 SQLite 内存，远程 MySQL 仅迁移冒烟（可选）与真实运行验证。

---

## 附录：全链路冒烟记录（2026-08-24 复核）

> Task 25 步骤 3 要求的冒烟结果补录。以下为**实际执行验证**的结果（非文档宣称）。

### 后端

- `cd backend && uv run pytest` → **208 passed**（75s，SQLite 内存 + TestClient）。
- 真实启动 `uv run uvicorn app.main:app`，逐端点冒烟：
  - `GET /api/v1/health` → `{"code":0,"message":"ok","data":{"status":"ok"}}`
  - `POST /auth/login`（admin/admin123）→ 200，签发 JWT；`GET /auth/me` → 返回 admin/林工。
  - `GET /dashboard/stats` → 后端 seed 真实值（`data_total=4`、`annotated_samples=2` 等）。
  - `GET /welds?page=1` → 4 条焊缝，分页字段完整。
  - `GET /analysis/candidates` → 2 条核验通过的候选。
  - `GET /welds/{WLD-…}/versions/{v}/analysis/result` → 真实 DSP：`stability=96.99`、三段占比、2 个异常区段。
  - `GET /welds/{WLD-…}/versions/{v}/signals` → 4 通道（cur/vol/gas/wir）× 5420 点、1kHz。
- 真实 MySQL（182.61.59.135:8206，库 `ai_welding`）：
  - **24 张表齐全**（23 业务表 + `alembic_version`=0001），迁移已应用。
  - seed 数据在库：users=1（admin）、data_records=4、data_versions=13、models=3、model_versions=3、
    label_categories=5、datasets=3、samples=2、validation_rule_results=15、audit_logs=16、jobs=2。

### 对象存储（MinIO）

- **发现并修复一处配置缺陷**：`.env` 的 `MINIO_ENDPOINT` 曾带 `http://` scheme 前缀，
  minio SDK（7.2.20）拒绝该值（`ValueError: path in endpoint is not allowed`），导致所有存储端点 500。
  去掉 scheme（`182.61.59.135:8290`）后复测：
  - `POST /files/presign-upload` → 200，返回 `object_key` + 预签名 PUT URL。
  - `POST /reports/export`（validation/json）→ 200，报告对象 `reports/validation/1.json`（1934 B）**真实写入 MinIO**。
  - `GET /files/{object_key}/url` → 200，返回预签名 GET URL。
  - 桶 `aiwelding` 存在且可列。

### 前端

- `npm run build` ✓（1580 modules，~276 kB JS）。
- `npx tsc -b`（typecheck）✓。
- `npx eslint .`：复核时发现 **14 个 unused-vars 错误**（App.tsx 遗留 `embedded`/`WeldAnalysis`/`SignalChart`/`bars` 等），
  已修复并清零；`npm run lint` 现全绿。
- 计划 Task 25 原本宣称 lint 全绿与实际不符，已在本次复核修正。

### 待办/遗留（非阻塞）

- 根 `CLAUDE.md` 状态已同步为全栈打通；各目录 CLAUDE.md 全覆盖（唯一缺口 `backend/app/templates/reports/`，随本附录补齐）。
- `.env` 属私密文件不入库；生产部署前需改 `SECRET_KEY` 与 `ADMIN_PASSWORD` 默认值。
