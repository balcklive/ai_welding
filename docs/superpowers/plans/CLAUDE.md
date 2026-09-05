# CLAUDE.md — docs/superpowers/plans/

存放实现计划（markdown，checkbox 任务拆分）。

- `2026-08-29-dataset-management-reference-tasks.md`：数据集管理开源参考改造任务清单（FiftyOne 借界面 / Datumaro 借处理能力 / lakeFS 借版本思想，**均不引入运行时依赖**）。**§零 为迁移路线总原则（借思想·不引依赖：四条硬约束 + 大数据量渲染/预览五条落地原则 + 复用边界），做任何 DM 任务前先读**；DM-01~11 按 P0/P1/P2 分级（P1 增 DM-10 成员列表 keyset 分页、P2 增 DM-11 信号多级抽稀金字塔），每项含参考来源 / 现状 gap / 改造内容 / 涉及文件 / 验收标准；P0 = 标签分布 UI + 训练记快照摘要 + 构建质量/划分类别平衡。**截至 2026-08-29 尚未执行（DM-01~11 代码未落地）；按 2026-09-05 分期限，DM-02（训练快照摘要）已并入一期轨道 B，DM-01/03 归二期 backlog。**
- `2026-09-05-mirror-third-party-images.md`：**第三方镜像 mirror 到 ACR + 服务器验证实施计划**（2026-09-05 生产机实测：LS/Docker Hub 直拉被 reset → 必须 mirror；MLflow/GHCR 直拉 + smoke 通过 → 无需 mirror）。交付 `mirror-3rd-party-images.yml` workflow 草稿；含版本 pin（LS 1.23.0 / MLflow 3.16.0）与服务器验证清单。上游依据：spec `docs/superpowers/specs/2026-09-05-mlflow-dataset-annotation-design.md` §4。
- `2026-09-05-compose-deploy.md`：**Docker Compose 部署实施计划**（LS + MLflow 辅助服务 + 外部网络 `aiwelding-net`，**保留 app 单容器蓝绿**）。A 段 = 仓库 compose/`.env.example` + 服务器起 LS/MLflow 并验证（app 不动）；B 段（A3/A4）= app 切 MLflow server + attach 网络 + deploy workflow 同步 compose。配套 `docker-compose.yml`（仓库根）、pin LS ACR `1.23.0` / MLflow GHCR digest `e72e134e…`。
- `2026-09-05-integrate-mlflow-labelstudio-into-main-app.md`：**集成 MLflow 与 LS 到主应用（长期）里程碑路线，一期 = 打通标注+训练全链路**。2026-09-05 评审定案 4 条决策：① M1 含最小前端录入切换（P1 并行，新任务路由 LS、平台只读）；② `annotation_task` 完成语义 =「LS 等待」一等公民态（executor 不抢占，数据集闸门=已回写）；③ 媒体 = MinIO 预签名长 TTL + 对账刷新（LS 不复制媒体）；④ label_categories 补回第 6 类「熔池」。M0 已完成（compose/mirror/server 切换）；**一期·轨道 A**（原 M1）= LS 标注全链路（SDK + 语义项目映射 + 建任务 + webhook/轮询回写 `annotations` + 最小前端录入切换）；**一期·轨道 B**（原 M2）= MLflow 训练链（log_model/register_model + DM-02 快照摘要 + 平台实验/模型视图）；**二期·M3** = DM P0（DM-02 已并入轨道 B）；**长期·M4** = 能力吸收 UI 收敛；含安全收敛。业务库权威 + best-effort + 每 push 仅重部署 app 为总约束。本计划为当前**一期**待执行主线。

坑/限制：
- 计划中所有字段级契约以 `docs/` 根五份文档为唯一来源；改契约先改文档再同步计划。
- 每任务执行状态以 `<repo-root>/.superpowers/sdd/` 下 ledger 为准（上下文压缩后不依赖记忆）。
