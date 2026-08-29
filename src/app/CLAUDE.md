# CLAUDE.md — src/app/

应用级路由与导航配置（2026-08-29 重构自 App.tsx 抽出）。单一来源：侧边栏导航结构、工作区页头文案、路由联合类型都从这里出。

## 文件

- `navigation.ts`：
  - `Route`：全部 15 个路由联合类型（`overview` + `data-center/*` + `analysis/*` + `model-center/*`）。
  - `workspaceHeaders`：三个一级工作区（数据中心/分析与标注/模型中心）的页头 `{eyebrow, title, description}`。
  - `navStructure`：侧边栏导航树（一级模块 + 二级子菜单），图标用 lucide-react。

## 调用链

- 被谁调用：`src/App.tsx`（`AppShell` 渲染侧边栏 ← `navStructure`；`WorkspaceFrame` 按 `route` 取 `workspaceHeaders` 页头，并按 route 懒加载对应 workspace 组件）。
- 调用谁：lucide-react 图标；不依赖具体业务组件。

## 关键规则/坑

- **新增/改名子菜单必须同步三处**：`Route` 联合类型 + `navStructure` + `workspaceHeaders`，并在 `App.tsx` 的 `WorkspaceFrame` 路由分支与懒加载映射里挂对应组件——漏一处即类型错误或死路由。
- 菜单 label 使用业务完整称呼：「焊缝版本」「数据集快照」等，勿用含义不明的「版本」（见 `docs/Playwright 菜单功能测试计划.md` §15）。
- 纯配置模块，勿放组件或业务逻辑。
