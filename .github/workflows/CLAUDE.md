# CLAUDE.md — .github/workflows/

GitHub Actions 工作流。

- `deploy-docker.yml`：`main` 分支通过前端 lint/typecheck/build 后，用 Buildx 构建镜像并推送到阿里云 ACR，再 SSH 到服务器 pull 指定 commit 镜像。发布先启动禁用 Job executor 的候选容器，在随机 localhost 端口执行 Alembic + `/api/v1/health/ready` 预检；通过后才停止当前容器，将当前容器重命名为 `*-rollback`，启动正式容器并二次 readiness。正式容器失败时自动恢复旧容器；成功后旧容器保留到下一次发布。健康检查显式等待最多 60 秒；部署成功后按镜像 ID 定向清理本仓库旧镜像（只保留当前容器与 rollback 容器在用的两个镜像，并顺带 `docker image prune -f` 清悬空层），防止历次发布堆积；不在 GitHub runner 执行依赖生产 MySQL/MinIO 的后端 pytest；服务器使用 Secrets `SSH_HOST`/`SSH_PORT`/`SSH_USER`/`SSH_PRIVATE_KEY`/`ALIYUN_ACR_USERNAME`/`ALIYUN_ACR_PASSWORD`，以及 Variables `DEPLOY_PATH`/`APP_CONTAINER_NAME`/`HOST_PORT`；默认部署目录为 `/home/wwwroot/code/ai_welding`，默认宿主机端口为 `8223`。**2026-09-05 起扩展**：deploy job 先 scp 上传 `docker-compose.yml` 到部署目录，SSH 内 `docker network create aiwelding-net` + `docker compose up -d` 确保 label-studio/mlflow 辅助服务在跑（幂等、失败不阻断 app 发布），app 各 `docker run` 挂 `--network aiwelding-net`（详见 `docs/superpowers/plans/2026-09-05-compose-deploy.md`）。

- `mirror-3rd-party-images.yml`：**手动触发**（`workflow_dispatch`）把第三方官方镜像搬运到阿里云 ACR。Label Studio（Docker Hub `heartexlabs/label-studio`，默认 `1.23.0`）**必需**——生产服务器直拉 Docker Hub 被 `connection reset`（2026-09-05 实测）；MLflow（GHCR `ghcr.io/mlflow/mlflow`，默认 `3.16.0`，按 digest `e72e134e…` 拉）为**可选**——服务器可直拉 GHCR。跑在 GitHub runner 上（能访问 Docker Hub + 有 `ALIYUN_ACR_*` secrets），推送到同 registry 命名空间 `aliyun_kaka/` 下 `label-studio`/`mlflow`；不进 main 自动发布链。

迁移约束：自动回滚只回滚应用容器，不执行 Alembic downgrade。数据库迁移必须遵循 expand/contract，保证当前版本和上一版本在切换窗口内都兼容升级后的 schema。

历史：`deploy-pages.yml` 与其重复文件 `static-deploy`（GitHub Pages 静态部署）已于 2026-08 删除——项目改为 Docker 私有化部署，Pages 流水线废弃。
