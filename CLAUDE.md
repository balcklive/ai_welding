# CLAUDE.md — 项目根

焊接工艺分析和建模机器学习平台。面向焊接工艺研究、质量分析、数据治理和 AI 建模。
当前阶段已从前端静态原型进入真实系统功能验收阶段：前后端 API、MySQL、MinIO、登录、异步 Job、报告导出和主要业务页面已打通；信号导入、起收弧识别、特征提取和报告支持真实数据链路。部分切分、标注、训练、测试、推理算法仍为演示/模拟计算，但任务编排、状态持久化、结果回填和产物关联按真实系统实现。

## 开发规则（必守）

1. **每个文件夹都必须有 CLAUDE.md**：记录该文件夹内的脚本及每个脚本的主要功能；如有，记录关键坑、边界条件、限制。新建目录时立即补上，改脚本时同步更新。
2. **Python 环境一律用 uv 管理**：`uv venv` / `uv add` / `uv sync` / `uv run`。禁止 `pip install`、`python -m venv`、直接跑系统 python 装包。
3. **敏感信息只放 `.env`**（已被 .gitignore 忽略），不写进代码或文档。仓库里不能出现明文密码/密钥。
4. **复用优先，不重复造轮子**：能用成熟、维护中的开源库的，一律复用；自己只写业务胶水与定制逻辑。复用清单与"刻意不复用"项见 `docs/开发规范.md` §1。
5. **接口调用轮转日志（必守）**：所有 `/api/v1` 调用必须记录请求体、返回体、调用人、调用时间等（loguru 轮转 + 访问日志中间件），规范见 `docs/开发规范.md` §2。
6. **推送前本地门禁（必守）**：`.husky/pre-push` 会在 `git push` 前执行 `npm run lint && npm run typecheck && npm run build`（与 CI `deploy-docker.yml` validate 步骤一致），任一失败即中断推送。改前端代码后推送前请先通过该门禁；如需手动核对，运行 `npm run lint && npm run typecheck`。

## 技术栈与结构

- 前端在仓库根目录（`src/`），保持现有结构不动。站点 logo/favicon 资源在 `public/`（`logo-mark.png` 圆标 + `logo.png` 完整图），由 `scripts/make_logo_assets.py` 从 `data/logo.png` 生成（黑底转透明）；侧边栏/登录页品牌标与 `index.html` favicon 均引用它。
- 后端独立在 `backend/`（FastAPI + SQLModel + Alembic + uv），**全栈主要业务链路已打通**：包含真实信号处理、Job 执行器、MinIO 存储、报告导出和前端各域 `/api/v1` 接线（登录闸门 + 各域 API 模块）。实现细节见 `backend/CLAUDE.md`；计划与验收见 `docs/superpowers/plans/`。
- 设计文档见 `docs/`：接口契约 `API接口清单.md` · 表结构 `数据库设计.md` · 对象存储 `OSS存储设计.md` · 目录组织 `文件与目录设计.md` · 开发规范 `开发规范.md`。
- 部署目标：私有化服务器，**多服务 Docker 编排（2026-09-05 起）**。主应用 `app` 仍为**单容器蓝绿 `docker run`**（多阶段构建，FastAPI 同时服务 `/api` 与前端静态）；`docker-compose.yml` 额外编排 **label-studio**（人工标注工作台，宿主 8224）与 **mlflow**（独立 Tracking Server，宿主 8225）两个阶段性子系统，三者在外部网络 `aiwelding-net` 上互通（app 以 `http://mlflow:5000` 访问）。`Dockerfile` 负责构建 app 镜像；`.github/workflows/deploy-docker.yml` 在 `main` 校验通过后由 GitHub Actions 构建并推送阿里云 ACR，再通过 SSH：上传 compose → 确保 `aiwelding-net` + compose 辅助服务在跑 → app 蓝绿 `docker run --network aiwelding-net`。服务器需：Docker compose 插件（wwwroot 用户级 `~/.docker/cli-plugins`）、项目 `.env`（含 `MLFLOW_MODE=server` + `MLFLOW_TRACKING_URI=http://mlflow:5000`）。详见 `docs/superpowers/specs/2026-09-05-compose-deploy.md`。

## 后端（backend/）

- Python 一律 uv：`cd backend && uv sync && uv run pytest`；运行服务 `uv run uvicorn app.main:app --reload`（`package=false`，非打包安装）。
- **Label Studio 集成（一期·轨道 A，2026-09-06 已走通 e2e）**：`label-studio-sdk`（v2.1.1）+ `backend/app/integrations/labelstudio.py` + `services/annotation_ls.py` + `api/v1/labelstudio.py`（webhook secret 鉴权 + `/labelstudio/tasks/{id}` + `/labelstudio/sync`）。LS region 类型实为 `rectanglelabels`/`polygonlabels`/`timeserieslabels`（0-100% 坐标以 `original_width/height` 换算像素），项目映射 box→3 / polygon→4(PolygonLabels 熔池) / segment→5。`LABEL_STUDIO_MODE=on` 时新标注任务路由 LS、等待态不被 executor 抢占、完成由回写驱动——**已落地**：`app/jobs/annotation.py` handler `mode=on` 走 `annotation_ls.prepare_ls_task`（归位样本→推流→置 `pending_ls`，job 保持 running）、回写后 `_maybe_complete_task`（全部样本回写才任务 synced + job succeeded），`off`/不可达回退模拟。**前端（2026-09-09 调整：不把 LS 工作台嵌入主应用）**：图像标注**不再 iframe 嵌 LS**——`LabelStudioEmbed.tsx` 已删除，主应用用自己的 Annotorious 画布标注并 `saveAnnotation` 直写；`src/hooks/useLabelStudioTask.ts` 仍存在，仅用 `ls_status` 感知任务是否已被推到 LS（`pending_ls`/`annotating` 时 job 保持 running），借 `ls_active` 放宽「加载样本」闸门。后端 LS 仅在容器间内网通信，主应用端用户不接触 LS。**模态集成现状**：仅**图像**完整集成 LS（bbox→项目3，闭环验通）；**视频(polygon→项目4)/时序(segment→项目5)仅为映射/convert/项目就绪，媒体未导出**（锚点/帧/信号样本无 `object_keys` → 不推 LS），暂走主应用自研画布过渡——**下一步**已列入计划（抽帧图片 / 时序 CSV 导出，见计划文档轨道 A「下一步」）。真实全链路（真样本→推 LS→回写→幂等）见 `backend/scripts/premise_validation/e2e_ls_roundtrip.py`；离线回归 `tests/test_labelstudio_integration.py` + `tests/test_labelstudio_handler.py`。迁移 `0013`（ls_status + annotation_ls_sync）、`0014`（熔池类）；契约已同步 `docs/数据库设计.md`。
- **配置读取**：`backend/app/core/config.py` 的 `Settings` 用 `env_file=Path(__file__).resolve().parents[3] / ".env"` 指向**仓库根 `.env`**（与 cwd 无关，勿改成相对 `.env`）。
- **接口轮转日志**：loguru + `backend/app/core/logging.py::AccessLogMiddleware`（纯 ASGI），写 `backend/logs/api.log`（相对目录自动锚定到 backend/ 下），脱敏 password/token/secret，规范见 `docs/开发规范.md` §2。
- 访问日志只覆盖 `/api/v1` 路由；健康检查 `GET /api/v1/health` 返回统一信封 `{code:0,...}`。
- 每目录规则：`backend/CLAUDE.md`、`backend/app/CLAUDE.md` 记录结构与坑，改动同步更新。

## 远程存储

- 已有 MinIO 对象存储（视频/图片/多模态文件，S3 兼容）与 MySQL 数据库，均已验证可用，连接配置在 `.env`（含建议的业务桶/库名）。
- MySQL 业务库 `ai_welding` 与 MinIO 桶 `aiwelding` 已创建，接入后端时直接使用。

## 业务规则要点（详见 README.md）

- "先选数据，再处理数据"上下文模式：**核验/版本/分析**等基于单条焊缝的操作必须先选择一条焊缝数据；**数据登记（曾名数据上传）是新建操作，不要求先选**，点"登记数据"直接进登记表单。
- 数据列表以焊缝 ID 去重，只展示最新版本；历史版本走"数据版本"页。
- 后续接入后端时，筛选条件应映射到数据查询接口，而不是前端加载全部数据后过滤。
- **录入可选项走「系统设置」字典（2026-09）**：数据登记/数据集录入里的可选项（数据厂家·焊机型号、焊接方法、数据来源、产品·项目信息、数据集任务类型、标注缺陷类别）不再硬编码在页面，统一由侧边栏「系统设置」页维护（`option_items` 表 + `label_categories.active`，接口 `GET/POST/PATCH/DELETE /settings/options`，写操作仅管理员）。**删除被历史数据引用的选项会自动转为「停用」**——录入时不再可选，历史台账仍按原值显示；改名/停用不回填历史数据。契约 §3.8，设计见 `docs/API接口清单.md` §3.8 与 `docs/数据库设计.md` §3.26。
