# CLAUDE.md — .husky/

Git 本地钩子目录（husky v9）。`core.hooksPath` 指向 `.husky/_`，仓库内共享；`npm install` 时经 `package.json` 的 `prepare: husky` 自动启用。

- `pre-push`：**推送前本地门禁**。执行 `npm run lint && npm run typecheck && npm run build`，与 GitHub Actions `deploy-docker.yml` 的 `validate` 步骤（lint → typecheck → build）保持一致。任一失败即中断 push，防止推送到远端（含 main）的代码触发 CI 报错。
- `_/`：husky 生成的 shim（软链/占位脚本）目录，勿手改。

坑/限制：
- `husky init` 默认生成的 `pre-commit` 样例是 `npm test`，而本项目**没有 `test` 脚本**，会直接破坏提交，已删除。本项目门禁只做在 push 阶段（CI 按 push 触发），commit 不做校验。
- 如需调整门禁命令，同步更新 `.husky/pre-push` 与 `deploy-docker.yml` 的 validate 步骤，保持两者一致。
