import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { DEFAULT_ROUTE, ROUTES, parseHashRoute, routeToHash } from './app/route-url.ts';

const app = readFileSync(new URL('./App.tsx', import.meta.url), 'utf8');
const navigation = readFileSync(new URL('./app/navigation.ts', import.meta.url), 'utf8');

/** 从 `navigation.ts` 的 `Route` 联合类型里抽出全部字面量。 */
const declaredRoutes = (() => {
  // 切到 Route 联合类型之后的**下一个** export const 为止——不要写死成某个具体常量的名字，
  // 否则在两者之间新增常量（如 routeCrumbs）会把它的字面量当成路由（2026-09-14 踩过）。
  const rest = navigation.slice(navigation.indexOf('export type Route ='));
  const union = rest.slice(0, rest.indexOf('export const'));
  return [...union.matchAll(/'([^']+)'/g)].map((match) => match[1]);
})();

// 2026-09-14：浏览器后退无法回到主菜单/上一个子菜单（刷新、分享链接也丢页）的根因是
// 路由只存在 useState 里。修复方式 = 路由与 URL hash 双向同步，以下为行为 + 装配断言。

test('每个 Route 都有对应的 hash 段（新增路由漏登记会在这里和 typecheck 同时报错）', () => {
  assert.deepEqual([...ROUTES].sort(), [...declaredRoutes].sort());
  assert.equal(DEFAULT_ROUTE, 'overview');
});

test('routeToHash 产出规范 hash，且能与 parseHashRoute 往返一致', () => {
  assert.equal(routeToHash('overview'), '#/overview');
  assert.equal(routeToHash('analysis/annotation'), '#/analysis/annotation');
  assert.equal(routeToHash('model-center/inference'), '#/model-center/inference');
  for (const route of ROUTES) {
    assert.equal(parseHashRoute(routeToHash(route)), route);
  }
});

test('parseHashRoute 容忍书写差异，非法输入一律返回 null（由调用方回落）', () => {
  assert.equal(parseHashRoute('#/analysis/annotation'), 'analysis/annotation');
  assert.equal(parseHashRoute('#analysis/annotation'), 'analysis/annotation');
  assert.equal(parseHashRoute('#/data-center/versions/'), 'data-center/versions');
  assert.equal(parseHashRoute('#/analysis/annotation?weld=W-0001'), 'analysis/annotation');
  for (const bad of ['', '#', '#/', '#/nope', '#/data-center', '#/Analysis/Annotation', '#/analysis/annotation/extra']) {
    assert.equal(parseHashRoute(bad), null, `${bad} 应判定为无法识别`);
  }
});

test('AppShell 从 URL 懒初始化路由，并归一化非法 hash', () => {
  assert.match(app, /function resolveInitialRoute\(\): Route \{/);
  assert.match(app, /parseHashRoute\(window\.location\.hash\) \?\? DEFAULT_ROUTE/);
  assert.match(app, /useState<Route>\(resolveInitialRoute\)/);
  // 深链首屏展开所属分组，否则侧栏看不到当前子菜单高亮
  assert.match(app, /new Set\(\[resolveInitialRoute\(\)\.split\('\/'\)\[0\]\]\)/);
  // 首次挂载把空/非法 hash 归一化，避免脏历史被前进/后退反复命中
  assert.match(app, /if \(parseHashRoute\(window\.location\.hash\) !== routeRef\.current\)/);
});

test('navigate 写历史：不同路由 pushState，同一路由不新增历史条目', () => {
  assert.match(app, /const navigate = useCallback\(\(target: Route, options\?: \{ replace\?: boolean \}\)/);
  assert.match(app, /const sameRoute = target === routeRef\.current;/);
  assert.match(app, /if \(options\?\.replace \|\| sameRoute\) window\.history\.replaceState\(\{ route: target \}, '', url\)/);
  assert.match(app, /else window\.history\.pushState\(\{ route: target \}, '', url\)/);
  assert.match(app, /applyRoute\(target\);/);
});

test('浏览器前进/后退与手改地址栏都能回写路由状态', () => {
  assert.match(app, /window\.addEventListener\('popstate', syncFromUrl\)/);
  assert.match(app, /window\.addEventListener\('hashchange', syncFromUrl\)/);
  assert.match(app, /window\.removeEventListener\('popstate', syncFromUrl\)/);
  assert.match(app, /window\.removeEventListener\('hashchange', syncFromUrl\)/);
  // 手改 hash / 前进后退都要展开分组、命中「数据集」时回到列表首页
  assert.match(app, /if \(next === 'data-center\/datasets'\) setDatasetHomeKey\(\(value\) => value \+ 1\)/);
  // 不要用 location.hash 赋值导航（会与上面的监听重复处理）
  assert.doesNotMatch(app, /location\.hash\s*=[^=]/);
});
