# CLAUDE.md — .github/workflows/

GitHub Actions 工作流。

- `deploy-pages.yml`：推送到 `main`（或手动 dispatch）时，用 Node 20 构建前端（`npm ci` + `npm run build`）并把 `dist/` 部署到 GitHub Pages。
- `static-deploy`：与 `deploy-pages.yml` 同尺寸（923B）、疑似内容重复的文件，可能是误复制，待确认后清理。
- `deploy-docker.yml`：`main` 分支通过前端 lint/typecheck/build 后，用 Buildx 构建镜像并推送到阿里云 ACR，再 SSH 到服务器 pull 指定 commit 镜像并替换 FastAPI 容器；不在 GitHub runner 执行依赖生产 MySQL/MinIO 的后端 pytest，也不使用火山 VCR；服务器使用 Secrets `SSH_HOST`/`SSH_PORT`/`SSH_USER`/`SSH_PRIVATE_KEY`/`ALIYUN_ACR_USERNAME`/`ALIYUN_ACR_PASSWORD`，以及 Variables `DEPLOY_PATH`/`APP_CONTAINER_NAME`/`HOST_PORT`；默认部署目录为 `/home/wwwroot/code/ai_welding`，默认宿主机端口为 `8223`。

坑/限制：
- Pages 部署要求仓库在 Settings → Pages 中开启并选择 "GitHub Actions" 作为 Source。
- 触发器：push 到 `main` + `workflow_dispatch`。
- 目前只部署前端静态产物；接入后端后此流程需要调整（后端无法跑在 Pages 上）。
