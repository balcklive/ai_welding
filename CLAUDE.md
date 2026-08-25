# CLAUDE.md — 项目根

焊接数据智能分析与 AI 建模平台。面向焊接工艺研究、质量分析、数据治理和 AI 建模。
当前阶段为前端静态原型（Vite + React 18 + TypeScript + Tailwind），页面中统计、图表、核验结果、训练指标等均为演示数据。

## 开发规则（必守）

1. **每个文件夹都必须有 CLAUDE.md**：记录该文件夹内的脚本及每个脚本的主要功能；如有，记录关键坑、边界条件、限制。新建目录时立即补上，改脚本时同步更新。
2. **Python 环境一律用 uv 管理**：`uv venv` / `uv add` / `uv sync` / `uv run`。禁止 `pip install`、`python -m venv`、直接跑系统 python 装包。
3. **敏感信息只放 `.env`**（已被 .gitignore 忽略），不写进代码或文档。仓库里不能出现明文密码/密钥。
4. **复用优先，不重复造轮子**：能用成熟、维护中的开源库的，一律复用；自己只写业务胶水与定制逻辑。复用清单与"刻意不复用"项见 `docs/开发规范.md` §1。
5. **接口调用轮转日志（必守）**：所有 `/api/v1` 调用必须记录请求体、返回体、调用人、调用时间等（loguru 轮转 + 访问日志中间件），规范见 `docs/开发规范.md` §2。

## 技术栈与结构

- 前端在仓库根目录（`src/`），保持现有结构不动。
- 后端独立在 `backend/`（FastAPI + SQLModel + Alembic + uv），**全栈已打通**：后端 Task 1–17 全部实现（含真实 DSP、Job 执行器、MinIO 存储、报告导出），前端各页已接线到 `/api/v1`（登录闸门 + 各域 api 模块）。实现细节见 `backend/CLAUDE.md`；计划与验收见 `docs/superpowers/plans/`。
- 设计文档见 `docs/`：接口契约 `API接口清单.md` · 表结构 `数据库设计.md` · 对象存储 `OSS存储设计.md` · 目录组织 `文件与目录设计.md` · 开发规范 `开发规范.md`。
- 部署目标：私有化服务器，单容器 Docker（多阶段构建，FastAPI 同时服务 `/api` 与前端静态文件）。当前阶段本地跑通、不部署。

## 后端（backend/）

- Python 一律 uv：`cd backend && uv sync && uv run pytest`；运行服务 `uv run uvicorn app.main:app --reload`（`package=false`，非打包安装）。
- **配置读取**：`backend/app/core/config.py` 的 `Settings` 用 `env_file=Path(__file__).resolve().parents[3] / ".env"` 指向**仓库根 `.env`**（与 cwd 无关，勿改成相对 `.env`）。
- **接口轮转日志**：loguru + `backend/app/core/logging.py::AccessLogMiddleware`（纯 ASGI），写 `backend/logs/api.log`（相对目录自动锚定到 backend/ 下），脱敏 password/token/secret，规范见 `docs/开发规范.md` §2。
- 访问日志只覆盖 `/api/v1` 路由；健康检查 `GET /api/v1/health` 返回统一信封 `{code:0,...}`。
- 每目录规则：`backend/CLAUDE.md`、`backend/app/CLAUDE.md` 记录结构与坑，改动同步更新。

## 远程存储

- 已有 MinIO 对象存储（视频/图片/多模态文件，S3 兼容）与 MySQL 数据库，均已验证可用，连接配置在 `.env`（含建议的业务桶/库名）。
- MySQL 业务库 `ai_welding` 与 MinIO 桶 `aiwelding` 已创建，接入后端时直接使用。

## 业务规则要点（详见 README.md）

- "先选数据，再处理数据"上下文模式：**核验/版本/分析**等基于单条焊缝的操作必须先选择一条焊缝数据；**登记（上传新数据）是新建操作，不要求先选**，点"上传数据"直接进登记表单。
- 数据列表以焊缝 ID 去重，只展示最新版本；历史版本走"数据版本"页。
- 后续接入后端时，筛选条件应映射到数据查询接口，而不是前端加载全部数据后过滤。
