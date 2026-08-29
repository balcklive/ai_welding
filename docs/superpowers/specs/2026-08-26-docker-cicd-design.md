# Docker CI/CD 自动部署设计

## 目标
为项目增加基于 GitHub Actions + SSH 的自动部署：代码合并到 `main` 后，在服务器拉取代码、构建 Docker 镜像并替换运行中的容器。

## 方案
采用服务器本地构建方案，不使用 PM2、Docker Compose 或镜像 Registry。Actions 先执行前端和后端验证，验证通过后通过 `appleboy/ssh-action` 登录服务器执行部署。

## Docker 架构
使用多阶段 Dockerfile：

1. Node 20 构建前端 `dist/`。
2. Python 3.12-slim 安装后端依赖并复制前端产物。
3. FastAPI 通过 `uvicorn app.main:app --host 0.0.0.0 --port 8000` 同时提供 API 和静态前端。

服务器项目目录中的 `.env` 通过 Docker `--env-file .env` 注入，禁止提交或覆盖敏感配置。

## 工作流
- 触发：push 到 `main`、`workflow_dispatch`。
- CI：Node 20 执行 `npm ci`、`npm run lint`、`npm run typecheck`、`npm run build`；Python 3.12 使用 uv 执行 `backend` 测试。
- 部署：`git pull --ff-only origin main`、`docker build`、停止并删除旧容器、使用 `--env-file .env` 和端口映射启动新容器。
- 健康检查：容器执行 `/api/v1/health/ready`，要求数据库连接、Alembic revision、关键表和 MinIO 目标桶全部可用；`/health/live` 仅用于判断 Web 进程存活。
- 配置：SSH 信息使用 Secrets；部署目录、容器名、主机端口使用 Variables；默认部署目录为 `/home/wwwroot/code/ai_welding`，默认宿主机端口为 `8223`。

## 失败处理
工作流使用 `set -Eeuo pipefail`。镜像启动前执行 `alembic upgrade head`，迁移失败时 Uvicorn 不启动。发布先以随机 localhost 端口启动候选容器，并强制 `JOB_EXECUTOR_ENABLED=false`；候选 readiness 通过后才释放生产端口。当前生产容器重命名为 rollback 副本，正式容器 readiness 失败时自动恢复。成功发布后 rollback 容器保留到下一次发布。数据库不自动 downgrade，因此迁移必须使用 expand/contract 保持前后两个应用版本兼容。

## 非目标
不新增 Registry 推送、不管理 MySQL/MinIO 生命周期、不把服务器 `.env` 纳入 Git、不删除现有 GitHub Pages 工作流。
