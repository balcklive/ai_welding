# CLAUDE.md — docs/superpowers/plans/

存放实现计划（markdown，checkbox 任务拆分）。

- `2026-08-23-ai-welding-fullstack.md`：AI 焊接平台全栈开发计划（后端 + 前端全链路接线）。执行用 SDD（subagent-driven-development），任务 brief/report 与 ledger 在 `.superpowers/sdd/2026-08-23-ai-welding-fullstack/`。
- `2026-08-27-annotation-kinds.md`：数据标注升级计划（时序区间标注 + 视频多边形标注）。技术选型已敲定（ECharts / react-image-annotate / 前端截帧+后端导出抽帧 / `annotations.kind` 判别）；`annotations` 表扩 `kind/points/start_time/end_time`，复用现有标注流与端点。

坑/限制：
- 计划中所有字段级契约以 `docs/` 根五份文档为唯一来源；改契约先改文档再同步计划。
- 每任务执行状态以 `<repo-root>/.superpowers/sdd/` 下 ledger 为准（上下文压缩后不依赖记忆）。
