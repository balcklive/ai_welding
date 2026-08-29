# CLAUDE.md — docs/superpowers/plans/

存放实现计划（markdown，checkbox 任务拆分）。

- `2026-08-29-dataset-management-reference-tasks.md`：数据集管理开源参考改造任务清单（FiftyOne 借界面 / Datumaro 借处理能力 / lakeFS 借版本思想，**均不引入运行时依赖**）。**§零 为迁移路线总原则（借思想·不引依赖：四条硬约束 + 大数据量渲染/预览五条落地原则 + 复用边界），做任何 DM 任务前先读**；DM-01~11 按 P0/P1/P2 分级（P1 增 DM-10 成员列表 keyset 分页、P2 增 DM-11 信号多级抽稀金字塔），每项含参考来源 / 现状 gap / 改造内容 / 涉及文件 / 验收标准；P0 = 标签分布 UI + 训练记快照摘要 + 构建质量/划分类别平衡。**截至 2026-08-29 尚未执行（DM-01~11 代码未落地），为当前唯一待执行计划。**

坑/限制：
- 计划中所有字段级契约以 `docs/` 根五份文档为唯一来源；改契约先改文档再同步计划。
- 每任务执行状态以 `<repo-root>/.superpowers/sdd/` 下 ledger 为准（上下文压缩后不依赖记忆）。
