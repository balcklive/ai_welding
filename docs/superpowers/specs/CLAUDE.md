# CLAUDE.md — docs/superpowers/specs/

设计规格 / 已完成计划与报告的存档目录，无脚本。当前为集成 MLflow 与 Label Studio 的整套设计档案。

- `2026-09-05-mlflow-dataset-annotation-design.md`：**MLflow + LS 集成设计基准**（spec §3/§4），被 `plans/2026-09-05-integrate-mlflow-labelstudio-into-main-app.md` 与 `docs/机器学习平台集成进展与方向.md` 引用。
- `2026-09-05-compose-deploy.md`：M0 **Docker Compose 部署实施计划**（LS+MLflow 辅助服务 + `aiwelding-net`，保留 app 单容器蓝绿）——已执行，归档。
- `2026-09-05-mirror-third-party-images.md`：M0 **第三方镜像 mirror 到 ACR 实施计划**——已执行，归档。
- `2026-09-05-integration-premise-verification.md`：**「待核实前提」逐项实测报告**（预签名 TTL / 熔池折叠 / 掩膜→轮廓 / 迁移回填 / iframe embed / 项目4 模板），归档。

坑/限制：
- 本目录为开发工作流产物（设计/计划/报告档案），非业务契约；业务契约仍在 `docs/` 根（API接口清单/数据库设计/OSS存储设计/开发规范）。
- 计划执行状态以对应实现代码为准；`<repo-root>/.superpowers/sdd/` 为 git-ignored ledger（无活跃 SDD 会话）。
- 旧 08-2x 设计存档（版本抽屉/功能验证/docker-cicd/数据集概览/工具栏/层级/上传改名）已被后续设计取代，2026-09-06 清理删除；对应功能以当前代码与 `docs/` 根契约为准。
