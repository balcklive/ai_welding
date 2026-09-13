/**
 * tools/browser-history-e2e.mjs — 浏览器前进/后退 + 刷新 + 深链的实机回归（阶段一）。
 *
 * 覆盖 2026-09-14 修复的问题：路由只存在 useState 时，进入子菜单后按浏览器后退
 * 会直接跳出整个应用（或把用户扔到空白页），刷新/分享链接也永远回到总览。
 *
 * 用法（需先起前端 dev server；后端可选，页面在无后端时走加载失败态但仍可断言路由）：
 *   npm run dev -- --port 5199 --strictPort
 *   node tools/browser-history-e2e.mjs
 *   E2E_BASE_URL=http://localhost:4173 node tools/browser-history-e2e.mjs   # 指定地址（如 vite preview）
 *
 * 失败时打印逐条断言并以退出码 1 结束，可直接接进 CI。
 */
import { chromium } from 'playwright';

const BASE = (process.env.E2E_BASE_URL || 'http://localhost:5199').replace(/\/+$/, '');
const results = [];

const check = (label, actual, expected) => {
  const ok = actual === expected;
  results.push({ ok, label, detail: ok ? `${actual}` : `期望 ${expected}，实际 ${actual}` });
  return ok;
};

const skip = (label, note) => results.push({ ok: true, label, detail: `（跳过：${note}）` });

const readState = (page) => page.evaluate(() => ({
  hash: location.hash,
  active: document.querySelector('.nav-subitem.active')?.textContent?.trim() ?? null,
  activeTop: document.querySelector('.nav-item.active span')?.textContent?.trim() ?? null,
  // 总览页不在 WorkspaceFrame 内（没有 .workspace-page-head），回落到任意 h1
  h1: document.querySelector('.workspace-page-head h1')?.textContent?.trim()
    ?? document.querySelector('h1')?.textContent?.trim() ?? null,
  historyLength: history.length,
}));

/** 展开一级分组（子菜单已展开时不点，避免被折叠回去）。 */
async function openGroup(page, groupLabel, childLabel) {
  const child = page.getByRole('button', { name: childLabel, exact: true });
  if (!(await child.isVisible())) {
    await page.getByRole('button', { name: groupLabel, exact: true }).click();
    await page.waitForTimeout(150);
  }
  await child.click();
  await page.waitForTimeout(700);
}

const browser = await chromium.launch();
const ctx = await browser.newContext();
// 绕过登录闸门（后端不可用时也不影响路由断言）。
await ctx.addInitScript(() => localStorage.setItem('token', 'browser-history-e2e'));

async function scenario(name, run) {
  const page = await ctx.newPage();
  // vite dev 首次加载要现场转换 lucide-react（optimizeDeps.exclude），给足导航超时
  page.setDefaultNavigationTimeout(60_000);
  page.setDefaultTimeout(60_000);
  const pageErrors = [];
  page.on('pageerror', (err) => pageErrors.push(err.message));
  try {
    await run(page);
    check(`${name} · 无页面级 JS 异常`, pageErrors.length, 0);
    if (pageErrors.length) console.log(`   ⚠ ${name} pageerror: ${pageErrors.join(' | ')}`);
  } catch (err) {
    check(`${name} · 执行未抛错`, `异常：${err.message}`, '无异常');
  } finally {
    await page.close();
  }
}

// 预热：冷启动时首次导航可能耗时数十秒，先单独加载一次，避免把冷启动算作失败。
{
  const warm = await ctx.newPage();
  warm.setDefaultNavigationTimeout(60_000);
  await warm.goto(`${BASE}/`, { waitUntil: 'domcontentloaded' });
  await warm.waitForSelector('.nav-item');
  await warm.close();
}

// 1) 深链：URL 直接指向子菜单
await scenario('深链进入子菜单', async (page) => {
  await page.goto(`${BASE}/#/model-center/repository`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.nav-subitem', { timeout: 15000 });
  await page.waitForTimeout(500);
  const state = await readState(page);
  check('  深链 URL 保留', state.hash, '#/model-center/repository');
  check('  深链命中子菜单高亮', state.active, '模型资产');
});

// 2) 主菜单 → 子菜单 A → 子菜单 B → 后退回 A → 再后退回上一级 → 前进回 A
await scenario('后退/前进可在主菜单与子菜单间往返', async (page) => {
  await page.goto(`${BASE}/`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.nav-item', { timeout: 15000 });
  await page.waitForTimeout(500);
  const initial = await readState(page);
  check('  初始 URL 归一化为总览', initial.hash, '#/overview');

  await openGroup(page, '数据管理', '数据集');
  check('  进入「数据集」', (await readState(page)).active, '数据集');
  await page.getByRole('button', { name: '数据核验', exact: true }).click();
  await page.waitForTimeout(700);
  check('  进入「数据核验」', (await readState(page)).active, '数据核验');
  await page.getByRole('button', { name: '焊缝版本', exact: true }).click();
  await page.waitForTimeout(700);
  check('  进入「焊缝版本」', (await readState(page)).active, '焊缝版本');

  await page.goBack();
  await page.waitForTimeout(700);
  let state = await readState(page);
  check('  后退一次回到上一个子菜单', state.active, '数据核验');
  check('  后退后 URL 同步', state.hash, '#/data-center/validation');

  await page.goBack();
  await page.waitForTimeout(700);
  state = await readState(page);
  check('  再后退回到「数据集」', state.hash, '#/data-center/datasets');
  check('  再后退命中子菜单高亮', state.active, '数据集');

  await page.goForward();
  await page.waitForTimeout(700);
  state = await readState(page);
  check('  前进回到「数据核验」', state.active, '数据核验');
  check('  前进后 URL 同步', state.hash, '#/data-center/validation');
});

// 3) 刷新后停留在原路由
await scenario('刷新停留在原路由', async (page) => {
  await page.goto(`${BASE}/#/analysis/annotation`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.nav-subitem', { timeout: 15000 });
  await page.waitForTimeout(500);
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(900);
  const state = await readState(page);
  check('  刷新后 URL 不变', state.hash, '#/analysis/annotation');
  check('  刷新后仍在数据标注', state.active, '数据标注');
  check('  刷新后页头正确', state.h1, '分析与标注');
});

// 4) 非法 hash 归一化，且不污染历史
await scenario('非法 hash 归一到总览', async (page) => {
  await page.goto(`${BASE}/#/nope/whatever`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.nav-item', { timeout: 15000 });
  await page.waitForTimeout(600);
  const state = await readState(page);
  check('  非法 hash 被替换为总览', state.hash, '#/overview');
  check('  页面回落总览', state.h1, '数据总览');
});

// 5) 重复点击同一子菜单不新增历史条目
await scenario('重复点击同一子菜单不撑大历史栈', async (page) => {
  await page.goto(`${BASE}/#/model-center/training`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.nav-subitem', { timeout: 15000 });
  await page.waitForTimeout(600);
  const before = (await readState(page)).historyLength;
  await page.getByRole('button', { name: '新建训练', exact: true }).click();
  await page.waitForTimeout(300);
  await page.getByRole('button', { name: '新建训练', exact: true }).click();
  await page.waitForTimeout(300);
  check('  history 长度不变', (await readState(page)).historyLength, before);
});

// 6) 快速连点不同子菜单（对应验收清单 UI-005）：URL、高亮不得错位
await scenario('快速连点子菜单后 URL 与高亮一致', async (page) => {
  await page.goto(`${BASE}/#/model-center/repository`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.nav-subitem', { timeout: 15000 });
  await page.waitForTimeout(600);
  for (const label of ['新建训练', '测试评估', '模型资产', '推理验证']) {
    await page.getByRole('button', { name: label, exact: true }).click();
  }
  await page.waitForTimeout(900);
  const state = await readState(page);
  check('  连点后 URL = 最后一个子菜单', state.hash, '#/model-center/inference');
  check('  连点后高亮 = 最后一个子菜单', state.active, '推理验证');
});

// 7) 登录闸门不吞掉目标路由（未登录 → 登录 → 回到原目标页）
await scenario('登录前后不丢目标路由', async () => {
  const anonCtx = await browser.newContext();
  const anon = await anonCtx.newPage();
  anon.setDefaultNavigationTimeout(60_000);
  try {
    await anon.goto(`${BASE}/#/model-center/repository`, { waitUntil: 'domcontentloaded' });
    await anon.waitForSelector('.login-card', { timeout: 15_000 });
    check('  未登录时显示登录页', await anon.locator('.login-card').isVisible(), true);
    check('  登录期间 URL 保留目标路由', await anon.evaluate(() => location.hash), '#/model-center/repository');
    // 模拟登录成功（写入 token 后重挂载；401 触发的 reload 也是这条路径）
    await anon.evaluate(() => localStorage.setItem('token', 'browser-history-e2e'));
    await anon.reload({ waitUntil: 'domcontentloaded' });
    await anon.waitForSelector('.nav-subitem', { timeout: 15_000 });
    await anon.waitForTimeout(600);
    const state = await anon.evaluate(() => ({
      active: document.querySelector('.nav-subitem.active')?.textContent?.trim() ?? null,
      hash: location.hash,
    }));
    check('  登录后落在原目标子菜单', state.active, '模型资产');
    check('  登录后 URL 不变', state.hash, '#/model-center/repository');
  } finally {
    await anonCtx.close();
  }
});

// 8) 同路由手势保留：已在数据集列表时再点「数据集」不新增历史条目、且回到列表首页
await scenario('数据集子菜单「再点一次回列表」手势保留', async (page) => {
  await page.goto(`${BASE}/#/data-center/datasets`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.dataset-workspace', { timeout: 15_000 });
  // 等列表进入终态（有行或明确空态）再判断，避免把「还在加载」误判成「没有数据」
  await page.waitForSelector('.dataset-list-row, .dataset-empty-state', { timeout: 15_000 }).catch(() => {});
  await page.waitForTimeout(300);
  const rows = page.locator('.dataset-list-row');
  if (!(await rows.count())) {
    skip('  数据集下钻手势', '当前数据源没有数据集行');
    return;
  }
  const before = (await readState(page)).historyLength;
  await rows.first().click();
  await page.waitForTimeout(800);
  check('  点行进入数据集概览', (await page.locator('.dataset-breadcrumb').first().innerText()).includes('概览'), true);
  await page.getByRole('button', { name: '数据集', exact: true }).click();
  await page.waitForTimeout(800);
  const state = await readState(page);
  check('  再点「数据集」回到列表', (await page.locator('.dataset-workspace h2').first().innerText()).trim(), '数据集列表');
  check('  手势不新增历史条目', state.historyLength, before);
  check('  手势后 URL 仍是数据集路由', state.hash, '#/data-center/datasets');
});

await browser.close();

const failed = results.filter((item) => !item.ok);
console.log('\n===== 浏览器历史回归结果 =====');
for (const item of results) console.log(`${item.ok ? '✔' : '✖'} ${item.label} ${item.detail}`);
console.log(`\n共 ${results.length} 条断言，通过 ${results.length - failed.length}，失败 ${failed.length}`);
if (failed.length) process.exitCode = 1;
