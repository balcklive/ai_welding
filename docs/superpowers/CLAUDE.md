# CLAUDE.md — docs/superpowers/

superpowers 工作流产物目录。

- `plans/`：**当前实现计划**。仅 `2026-09-05-integrate-mlflow-labelstudio-into-main-app.md`（一期·轨道 A/B 主线）与 `2026-08-29-dataset-management-reference-tasks.md`（二期 DM backlog）；已完成计划（M0 部署/镜像 mirror、前提验证报告）归档到 `specs/`。
- `specs/`：**设计规格 / 已完成计划与报告的存档**——`2026-09-05-mlflow-dataset-annotation-design.md`（集成设计基准）+ `2026-09-05-compose-deploy.md`、`2026-09-05-mirror-third-party-images.md`（M0 已执行）、`2026-09-05-integration-premise-verification.md`（前提验证报告）。旧 08-2x 设计存档（版本抽屉/功能验证/docker-cicd/数据集概览/工具栏/层级/上传改名）已被后续设计取代，2026-09-06 清理删除。

坑/限制：
- 本目录文件为开发工作流产物，非业务契约；业务契约仍在 `docs/` 根（API接口清单/数据库设计/OSS存储设计/开发规范）。
- 计划执行状态以对应实现代码为准；`<repo-root>/.superpowers/sdd/` 为 git-ignored ledger，当前不存在（无活跃 SDD 会话）。
