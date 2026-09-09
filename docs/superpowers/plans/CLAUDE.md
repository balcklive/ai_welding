# CLAUDE.md — docs/superpowers/plans/

存放实现计划（markdown，checkbox 任务拆分）。已完成计划（M0 部署/镜像 mirror）与前提验证报告已归档到上级 `specs/`，见 `specs/CLAUDE.md`。

- `2026-08-29-dataset-management-reference-tasks.md`：数据集管理开源参考改造任务清单（FiftyOne 借界面 / Datumaro 借处理能力 / lakeFS 借版本思想，**均不引入运行时依赖**）。**§零 为迁移路线总原则（借思想·不引依赖：四条硬约束 + 大数据量渲染/预览五条落地原则 + 复用边界），做任何 DM 任务前先读**；DM-01~11 按 P0/P1/P2 分级（P1 增 DM-10 成员列表 keyset 分页、P2 增 DM-11 信号多级抽稀金字塔），每项含参考来源 / 现状 gap / 改造内容 / 涉及文件 / 验收标准；P0 = 标签分布 UI + 训练记快照摘要 + 构建质量/划分类别平衡。**截至 2026-08-29 尚未执行（DM-01~11 代码未落地）；按 2026-09-05 分期限，DM-02（训练快照摘要）已并入一期轨道 B，DM-01/03 归二期 backlog。**
- `2026-09-05-integrate-mlflow-labelstudio-into-main-app.md`：**集成 MLflow 与 LS 到主应用（长期）里程碑路线，一期 = 打通标注+训练全链路**。2026-09-05 评审定案 4 条决策：① M1 含最小前端录入切换（P1 并行，新任务路由 LS、平台只读）；② `annotation_task` 完成语义 =「LS 等待」一等公民态（executor 不抢占，数据集闸门=已回写）；③ 媒体 = MinIO 预签名长 TTL + 对账刷新（LS 不复制媒体）；④ label_categories 补回第 6 类「熔池」。M0 已完成（compose/mirror/server 切换）；**一期·轨道 A**（原 M1）= LS 标注全链路（SDK + 语义项目映射 + 建任务 + webhook/轮询回写 `annotations` + 最小前端录入切换）；**一期·轨道 B**（原 M2）= MLflow 训练链（log_model/register_model + DM-02 快照摘要 + 平台实验/模型视图）；**二期·M3** = DM P0（DM-02 已并入轨道 B）；**长期·M4** = 能力吸收 UI 收敛；含安全收敛。业务库权威 + best-effort + 每 push 仅重部署 app 为总约束。本计划为当前**一期**待执行主线。**2026-09-06 轨道 A 已推进并落地**：SDK + 集成骨架用真实 LS+MySQL+MinIO 走通 e2e，迁移 `0013`/`0014`、离线回归 `tests/test_labelstudio_integration.py` + `test_labelstudio_handler.py`；后端 `mode=on` 推流/等待态/回写驱动完成 + 幂等；前端图像模式 iframe 嵌入 LS；服务器 `.env` 配 `mode=on` + 3 个 LS 项目级 webhook + PAT 轮换，闭环实机验通（图像 bbox→项目3）。**模态集成现状**：仅**图像**完整集成 LS；**视频(项目4)/时序(项目5)媒体未导出，暂走自研画布过渡**——**下一步**（计划文档轨道 A「下一步」）：抽帧图片→项目4 / 时序 CSV→项目5。」
坑/限制：
- 计划中所有字段级契约以 `docs/` 根五份文档为唯一来源；改契约先改文档再同步计划。
- 每任务执行状态以 `<repo-root>/.superpowers/sdd/` 下 ledger 为准（上下文压缩后不依赖记忆）。
