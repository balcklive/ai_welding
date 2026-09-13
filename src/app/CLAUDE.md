# CLAUDE.md — src/app/

应用级路由与导航配置（2026-08-29 重构自 App.tsx 抽出）。单一来源：侧边栏导航结构、工作区页头文案、路由联合类型都从这里出。

## 文件

- `navigation.ts`：
  - `Route`：全部 16 个路由联合类型（`overview` + `data-center/*` + `analysis/*` + `model-center/*`）。
  - `workspaceHeaders`：三个一级工作区（数据管理/分析与标注/模型中心）的页头 `{eyebrow, title, description}`。
  - `navStructure`：侧边栏导航树（一级模块 + 二级子菜单），图标用 lucide-react。
- `route-url.ts`（阶段一 2026-09-14）：
  - `ROUTE_SEGMENTS`：路由 → hash 段的字典，用 `satisfies Record<Route, string>` 做**编译期穷尽校验**——`navigation.ts` 新增路由后忘记登记，`npm run typecheck` 直接报错。
  - `ROUTES` / `DEFAULT_ROUTE`：全部可寻址路由 + 回落页（`overview`）。
  - `routeToHash(route)` → `#/analysis/annotation`；`parseHashRoute(hash)` → 路由或 `null`（容忍 `#/x`、尾斜杠、hash 内 query，未知段/空串一律 `null`，由调用方回落）。

## 调用链

- 被谁调用：`src/App.tsx`（`AppShell` 渲染侧边栏 ← `navStructure`；`WorkspaceFrame` 按 `route` 取 `workspaceHeaders` 页头，并按 route 懒加载对应 workspace 组件）；`route-url.ts` 被 `App.tsx` 的 `resolveInitialRoute`、`navigate`、`popstate`/`hashchange` 监听使用；`src/App.routing-regression.test.mjs` 直接 import 它跑真实换算断言。
- 调用谁：lucide-react 图标（`navigation.ts`）；`route-url.ts` 只 `import type`，无运行时依赖（Node 24 类型擦除可直接加载）。

## 关键规则/坑

- **新增/改名子菜单必须同步三处**：`Route` 联合类型 + `navStructure` + `workspaceHeaders`，并在 `App.tsx` 的 `WorkspaceFrame` 路由分支与懒加载映射里挂对应组件——漏一处即类型错误或死路由。
- **路由的 URL 契约（阶段一）**：地址形如 `#/<route>`，`route` 的唯一来源是 URL hash——浏览器前进/后退、刷新、收藏、分享链接全部以它为准。`navigate()` 用 `history.pushState`；**同一路由只 `replaceState`**（避免重复点击撑大历史栈，同时保留「已在该子菜单时再点一次 = 回数据集列表」的手势）；`popstate` 与 `hashchange` 都回写 state 并展开所属一级分组（漏了会出现「页面切了但侧栏还是折叠的」）。`Route` 新增后必须同步 `ROUTE_SEGMENTS`（`satisfies` 会拦住漏项）。
- **坑：不要改成 path 路由**（`/analysis/annotation`）。生产由 FastAPI `app.mount("/", StaticFiles(directory=frontend_dir, html=True))` 托管（backend/app/main.py:108），Starlette 对不存在的路径直接 404（只回退 `404.html`，没有 SPA fallback），path 路由会让刷新/深链 404——要改必须同时加后端 catch-all 与反向代理 `try_files`。另：**不要用 `location.hash = ...` 赋值导航**，会与 `App.tsx` 的 `hashchange` 监听重复处理。
- 菜单 label 使用业务完整称呼：「焊缝版本」「数据集快照」等，勿用含义不明的「版本」（见 `docs/Playwright 菜单功能测试计划.md` §15）。
- 纯配置模块，勿放组件或业务逻辑。
