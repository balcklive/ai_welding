# CLAUDE.md — .github/workflows/

GitHub Actions 工作流。

- `deploy-docker.yml`：`main` 分支通过前端 lint/typecheck/build 后，用 Buildx 构建镜像并推送到阿里云 ACR，再 SSH 到服务器 pull 指定 commit 镜像。发布先启动禁用 Job executor 的候选容器，在随机 localhost 端口执行 Alembic + `/api/v1/health/ready` 预检；通过后才停止当前容器，将当前容器重命名为 `*-rollback`，启动正式容器并二次 readiness。正式容器失败时自动恢复旧容器；成功后旧容器保留到下一次发布。健康检查显式等待最多 60 秒；不在 GitHub runner 执行依赖生产 MySQL/MinIO 的后端 pytest；服务器使用 Secrets `SSH_HOST`/`SSH_PORT`/`SSH_USER`/`SSH_PRIVATE_KEY`/`ALIYUN_ACR_USERNAME`/`ALIYUN_ACR_PASSWORD`，以及 Variables `DEPLOY_PATH`/`APP_CONTAINER_NAME`/`HOST_PORT`；默认部署目录为 `/home/wwwroot/code/ai_welding`，默认宿主机端口为 `8223`。

迁移约束：自动回滚只回滚应用容器，不执行 Alembic downgrade。数据库迁移必须遵循 expand/contract，保证当前版本和上一版本在切换窗口内都兼容升级后的 schema。

历史：`deploy-pages.yml` 与其重复文件 `static-deploy`（GitHub Pages 静态部署）已于 2026-08 删除——项目改为 Docker 私有化部署，Pages 流水线废弃。
