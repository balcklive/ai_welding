# CLAUDE.md — .github/workflows/

GitHub Actions 工作流。

- `deploy-pages.yml`：推送到 `main`（或手动 dispatch）时，用 Node 20 构建前端（`npm ci` + `npm run build`）并把 `dist/` 部署到 GitHub Pages。
- `static-deploy`：与 `deploy-pages.yml` 同尺寸（923B）、疑似内容重复的文件，可能是误复制，待确认后清理。

坑/限制：
- Pages 部署要求仓库在 Settings → Pages 中开启并选择 "GitHub Actions" 作为 Source。
- 触发器：push 到 `main` + `workflow_dispatch`。
- 目前只部署前端静态产物；接入后端后此流程需要调整（后端无法跑在 Pages 上）。
