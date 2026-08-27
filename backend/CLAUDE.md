# CLAUDE.md — backend/

后端（FastAPI + SQLModel + Alembic + uv）。当前进度：Task 1（骨架 + 配置 + 日志中间件）+ Task 2（全部 SQLModel 模型 + db 会话 + Alembic 初始迁移）+ Task 3（统一信封 + 异常处理 + v1 路由聚合 + audit + 分页助手）+ Task 4（MinIO 存储客户端）+ Task 5（JWT 认证 + login/me 端点）+ Task 6（启动 seed：管理员 + 演示数据）+ Task 7（通用 Job 服务 + `GET /jobs/{job_id}` 轮询端点）+ Task 8（Dashboard 总览四端点 stats/attributes/distributions/projects）+ Task 9（files 三端点：小文件代理上传 / 大文件预签名直传 / 下载 URL）+ Task 10（welds 核心 CRUD：列表/登记/版本/核验）+ **Task 11（Analysis：candidates / signals / 真实 DSP）已完成** + **Task 12（真实多模态特征提取 + 端点）已完成** + **Task 13（Job 执行器 DB 轮询 + 对齐任务，已真实化：真实信号事件 + ffmpeg 媒体探测/关键帧 + 真实产物）已完成** + **Task 14（切分 + 标注，模拟）已完成** + **Task 15（数据集 + 构建任务 + dimensions/readiness/lineage）已完成** + **Task 16（模型中心 + 训练/测试/推理任务模拟）已完成** + **Task 17（通用报告导出：Jinja2+xhtml2pdf PDF / JSON，写 MinIO）已完成** + **Task 18（真实信号导入：CSV 挂载后自动解析校验 → 启发式事件检测 → MinIO Parquet；DSP 分析优先读真实信号，无则回退生成）已完成**。

## 目录与脚本

- `pyproject.toml`：项目元数据 + 依赖声明（`[tool.uv] package=false`，非打包安装）。依赖变更用 `uv add` 后重新 `uv sync`。
- `.python-version`：`3.12`（uv 据此选/下载解释器）。
- `uv.lock`：`uv sync` 生成的锁文件，勿手改。
- `app/`：应用代码（见 `app/CLAUDE.md`）。`app/models/` 含全部 24 张表类（含 Task 18 的 `signal_ingests`），`app/core/db.py` 提供引擎与会话。
- `app/core/seed.py`：**Task 6**。启动 seed——`seed_all(session)`（幂等，末尾统一 commit）/ `seed_admin` / `seed_demo`。演示数据数值对齐前端 mock（App.tsx weldRows/VersionPanel/Validation/datasetRows/ModelRepository/Annotation）；ORM 写库，SQLite 测试与 MySQL 启动均可用。详见 `app/core/CLAUDE.md`。
- `alembic/`：迁移（见 `alembic/CLAUDE.md`；`0001_initial` 手写，datetime 统一 `DATETIME(6)`；Task 18 新增 `0002_signal_ingests`）。
- `tests/`：pytest 测试（`uv run pytest`，SQLite 内存 + TestClient，不连远程库）。`test_welds.py` 为 Task 10（Welds CRUD），覆盖登记事务/编号递增/列表筛选分页/版本链/核验级联/401；`test_dsp.py` + `test_analysis.py` 为 Task 11（真实 DSP 纯函数 + analysis 端点：candidates/signals/六 mode/result/401）、`test_alignment.py` 为 Task 13（对齐真实化内核：创建→run_job→succeeded + 自动时间对齐版本 / **generated 回退 + 真实信号 ingest + 真实视频 ffmpeg 探测/关键帧** / 失败→failed / 404 / 401）、`test_media_probe.py` 为 **ffmpeg 媒体探测/关键帧单测**（不连 DB）、`test_datasets.py` 为 Task 15（数据集 CRUD / dimensions/readiness / 版本 / **版本成员分页接口 items（total/页切片/真实跨数据集版本→40402）** / 构建任务→按焊缝分组防泄漏 / lineage / 404 / 401）、`test_models.py` 为 Task 2 模型建表/索引一致性 + **Task 16 模型中心 API**（列表汇总/详情/新建 409/状态流转/训练→自动生成实验版本 + weights.pt / 测试→混淆矩阵 / 推理→boxes / 日志 / 404 / 401）、`test_reports.py` 为 **Task 17 通用导出**（validation json→score 93.3 + 15 条规则 / validation pdf→`%PDF` 头 / data-list 全量+按标识过滤 / analysis 通用模板 / 未知 type·format 400 / 实体缺失 404 / 401，monkeypatch `app.storage.get_storage` → FakeStorage）。

## 常用命令

- 安装/同步：`uv sync`
- 测试：`uv run pytest`
- 起服务：`uv run uvicorn app.main:app --reload`（开发期在前端 `npm run dev` 用 Vite proxy 指向 `http://localhost:8000`）
- 迁移：`uv run alembic upgrade head` / `uv run alembic revision --autogenerate -m "..."`（后需连上远程 MySQL）

## 坑/限制

- **配置 `.env` 解析**：`app/core/config.py::Settings` 用 `env_file=Path(__file__).resolve().parents[3] / ".env"` 固定指向**仓库根 `.env`**（config.py → parents[3] = 仓库根），与 cwd 无关。不要改成相对 `.env`，否则在 backend/ 下跑会读不到。
- **访问日志**：loguru 写 `backend/logs/api.log`；`API_LOG_DIR` 为相对值时自动锚定到 `backend/` 下（保证 cwd 无关）。`backend/logs/`、`backend/.venv/` 已被根 `.gitignore` 忽略。
- **中间件只覆盖 `/api/v1`** 路由（开发规范 §2.1）；非 API 路径直接透传不记日志。
- **管理员 seed**：`ADMIN_USERNAME`/`ADMIN_PASSWORD` 在根 `.env`（Task 6 已实现，`app/core/seed.py` 读取）；当前是本地演示默认值 `admin`/`admin123`，生产必须改。
- pytest 能 import `app` 依赖 `tests/__init__.py`（使 backend/ 进入 sys.path）。
