# CLAUDE.md — tools/

一次性/本地辅助脚本（不入运行时，不参与打包）。用 uv 管理 Python 环境（`uv run <script>`）。

## 文件

- `generate_training_signal.py`：生成确定性训练信号 fixture——写 `data/synthetic_training_signal.csv`（500 行，0.5s，列 `time/Current/Voltage/GasSpeed/WireSpeed`，起弧 0.10~0.44s 内电流/电压有值、其余 0），供 Playwright 训练流程用真实 CSV 导入。纯标准库（csv/math/pathlib），无第三方依赖。
- `browser-history-e2e.mjs`：浏览器历史回归（Node + Playwright，阶段一 2026-09-14）。断言深链、后退/前进往返、刷新停留原路由、非法 hash 归一化、重复点击不撑大历史栈、快速连点子菜单不错位（验收清单 UI-005）。任一断言失败退出码 1。
- `data-center-ui-e2e.mjs`：**数据管理界面契约回归（T1 术语 + T2 结构，2026-09-14）**。用**接口打桩**（只造这一个页面要的数据）跑真实组件，断言"界面上有什么、没有什么"——这类结构性契约后端测试看不见（它不渲染）。21 条断言：列表行样本数取 `weld_count`（不是切片数）；概览统计卡是「样本数 + 切片数」两张；有效切片占比读后端 `effective_ratio`（25.0%，**不是** `1-三项之和`）、列出影响最大的原因、展开 3 条明细含 `affected`；「字段完备性」面板存在且维度名中文、「模型适配检查」面板与"可训练"结论已消失、保留划分策略；整页无被禁术语；成员表/全部样本表都不再有「核验状态」列，送丝/焊接速度为两列带单位。**两个坑**：`DatasetWorkspace` 用 `dataset_no`（不是数字 id）请求详情，打桩路径要按它写（否则详情返回错形状 → 页面直接崩）；成员表空成员时是空态、不渲染表格，要断言表头就得先给一条成员。
- `t3-error-state-e2e.mjs`：**T3 错误态实机验收**（2026-09-14）。两种模拟：① **断网模式** `route.abort()` 全量模拟后端停机 → 数据集列表 / 数据登记 / 分析「选择数据」三页断言 `ErrorState` + 重试 + 表格为空 + **整页无任何旧演示数据字面量**（`DEMO_STRINGS` 白名单式反查，含 8,420 / 93.3 / Fronius CMT / WLD-20260815-0248 等）；② **拦截模式**只放行 `/datasets` 与 `/welds`，其余照旧停机 → 先进入数据核验页并用页顶选择器补上下文（T5 恢复路径），再断言该页错误态、评分占位 `—`、无演示规则、S12 导出禁用。24 条断言。

## 调用链

- 被谁调用：手动/验收脚本调用；`browser-history-e2e.mjs` 需先起前端（`npm run dev -- --port 5199 --strictPort`），用 `E2E_BASE_URL` 指定其它地址（默认 `http://localhost:5199`）。
- 调用谁：`generate_training_signal.py` 无依赖；`browser-history-e2e.mjs` 用 devDependencies 里的 `playwright`（浏览器已装），通过 `localStorage.token` 绕过登录闸门，后端可不起（页面走加载失败态，路由断言仍有效）。

## 关键规则/坑

- 输出路径锚定仓库根 `data/`（`parents[1]`），与 cwd 无关。
- 脚本目的明确、无副作用的工具放本目录；需长期维护的生成器再考虑迁入 `backend/tests/fixtures/` 或 `app/services`。
- `browser-history-e2e.mjs` 里有一段**预热加载**：vite dev 把 `lucide-react` 排除在预打包外，冷启动首次导航可能数十秒，不预热会把冷启动误判成失败。脚本用 `.nav-subitem.active` 文本 + `location.hash` 断言，比断言页头更稳（数据管理各子页共用同一页头）。
