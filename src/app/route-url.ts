/**
 * src/app/route-url.ts — 路由 ↔ URL（hash）映射
 *
 * 阶段一（2026-09-14）：把 AppShell 的路由状态接到 URL 上，修复「进入子菜单后
 * 浏览器后退无法回到主菜单/上一个子菜单」以及刷新、收藏、分享链接全部丢页的问题。
 *
 * URL 约定：`#/<route>`，hash 段与 `Route` 字面量逐字一致，例如
 *   - `#/overview`
 *   - `#/data-center/datasets`
 *   - `#/analysis/annotation`
 *
 * 坑（勿改）：
 * - **不要改成 path 路由**（`/analysis/annotation`）。生产由 FastAPI
 *   `app.mount("/", StaticFiles(directory=frontend_dir, html=True))` 托管前端
 *   （backend/app/main.py:108），Starlette 对不存在的路径直接 404（只回退
 *   `404.html`，没有 SPA fallback），path 路由会让刷新/深链 404，必须同时改
 *   后端 catch-all 与反向代理 `try_files`。hash 不经过服务器，部署零改动。
 * - **不要用 `location.hash = ...` 赋值导航**。那会触发 `hashchange`（并可能
 *   连带 `popstate`），与 `App.tsx` 的 URL 监听重复处理；导航一律走
 *   `history.pushState` / `replaceState`。
 * - 本模块只做「URL 字符串 ↔ Route」的纯换算，不碰 DOM、不碰 React。
 */
import type { Route } from './navigation';

/**
 * 路由 → hash 段。用 `satisfies Record<Route, string>` 做编译期穷尽校验：
 * `navigation.ts` 新增路由后若忘记在这里登记，`npm run typecheck` 会直接报错。
 */
const ROUTE_SEGMENTS = {
  overview: 'overview',
  'data-center/datasets': 'data-center/datasets',
  'data-center/registration': 'data-center/registration',
  'data-center/validation': 'data-center/validation',
  'data-center/versions': 'data-center/versions',
  'analysis/select': 'analysis/select',
  'analysis/alignment': 'analysis/alignment',
  'analysis/analysis': 'analysis/analysis',
  'analysis/split': 'analysis/split',
  'analysis/sample-annotation': 'analysis/sample-annotation',
  'analysis/annotation': 'analysis/annotation',
  'analysis/features': 'analysis/features',
  'model-center/dataset-build': 'model-center/dataset-build',
  'model-center/repository': 'model-center/repository',
  'model-center/training': 'model-center/training',
  'model-center/testing': 'model-center/testing',
  'model-center/inference': 'model-center/inference',
  settings: 'settings',
} satisfies Record<Route, string>;

/** 全部可寻址路由（顺序与 `ROUTE_SEGMENTS` 声明顺序一致）。 */
export const ROUTES = Object.keys(ROUTE_SEGMENTS) as Route[];

/** 无法从 URL 得到路由时的回落页。 */
export const DEFAULT_ROUTE: Route = 'overview';

const HASH_TO_ROUTE = new Map<string, Route>(
  (Object.entries(ROUTE_SEGMENTS) as [Route, string][]).map(([route, segment]) => [segment, route]),
);

/** 路由 → 规范 hash（含前导 `#`，可直接交给 pushState/replaceState）。 */
export function routeToHash(route: Route): string {
  return `#/${ROUTE_SEGMENTS[route]}`;
}

/**
 * 解析 hash → 路由；空串、未知段、非法输入一律返回 `null`（由调用方决定回落）。
 * 容忍 `#/analysis/annotation`、`#analysis/annotation`、尾斜杠以及 hash 内 query
 * （`#/analysis/annotation?weld=W-1`，阶段一暂不消费 query，但不要让解析失败）。
 */
export function parseHashRoute(hash: string): Route | null {
  const raw = typeof hash === 'string' ? hash : '';
  const withoutHash = raw.startsWith('#') ? raw.slice(1) : raw;
  const path = withoutHash
    .split('?')[0]
    .split('#')[0]
    .replace(/^\/+/, '')
    .replace(/\/+$/, '');
  if (!path) return null;
  return HASH_TO_ROUTE.get(path) ?? null;
}
