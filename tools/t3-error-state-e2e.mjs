/**
 * tools/t3-error-state-e2e.mjs — T3「废除演示数据兜底」的实机验收（2026-09-14）。
 *
 * 验收标准（docs/数据管理改造技术实施方案.md T3 / §8）：
 *   ① 接口不可用时页面显示错误态 + 重试；
 *   ② 页面上不出现任何数字化演示结果（旧 mock 的字面量一个都不能剩）。
 *
 * 两种模拟方式：
 *   - **断网模式**：`page.route('**\/api\/v1\/**', route.abort())` 模拟后端停机——所有请求
 *     网络失败（client.ts 兜底为 status 0），覆盖不需要先选数据的页面。
 *   - **拦截模式**：只放行 `/datasets` 与 `/welds`（喂最小真实形状），其余 abort——这样才能
 *     先选中一条样本、再进「数据核验」看它的错误态（该页有"未选数据"守卫，纯断网只会看到引导）。
 *
 * 用法（需先起前端 dev server）：
 *   npm run dev -- --port 5199 --strictPort
 *   node tools/t3-error-state-e2e.mjs
 *   E2E_BASE_URL=http://localhost:4173 node tools/t3-error-state-e2e.mjs
 *
 * 失败逐条打印并以退出码 1 结束，可直接接进 CI。
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

/** T3.2 删掉的那些演示数据里出现过的字面量——一个都不该再出现在页面上。 */
const DEMO_STRINGS = [
  '焊接缺陷检测集', '熔池分割数据集', '工艺质量预测集', // mockDatasetRows / fallbackDatasetOptions
  'DS-DEFECT-001', 'DS-POOL-002', 'DS-QUALITY-003',
  '8,420', '5,680', '2,140', '96.8%', '91.2%',
  'WLD-20260815-0248', 'WLD-20260815-0247', 'WLD-20260814-0246', // mockWeldRows / mockDatasetItemRows
  '93.3', '视频帧率存在轻微波动', // ValidationPage 演示报告
  'Fronius CMT', 'OTC FD-V8', 'Panasonic YD-500', // RegistrationPage FALLBACK_OPTIONS
  '1,086', // mockLineage
];

const bodyText = (page) => page.evaluate(() => document.body.innerText);

/** 断言整页不含任何演示数据字面量。 */
async function assertNoDemoData(page, scope) {
  const text = await bodyText(page);
  const hits = DEMO_STRINGS.filter((needle) => text.includes(needle));
  check(`${scope} · 页面无演示数据字面量`, hits.join('|') || '无', '无');
}

/** 断言出现统一错误态 + 重试按钮。 */
async function assertErrorState(page, scope, minCount = 1) {
  const count = await page.locator('.error-state').count();
  check(`${scope} · 出现错误态卡片（≥${minCount}）`, count >= minCount ? `是(${count})` : `否(${count})`, `是(${count})`);
  check(`${scope} · 错误态有 role=alert`, await page.locator('.error-state[role="alert"]').count() > 0, true);
  check(`${scope} · 提供重试按钮`, await page.getByRole('button', { name: '重试' }).count() > 0, true);
  check(`${scope} · 无"演示/占位"数字残留（表格为空）`, await page.locator('.dataset-list-row, .dataset-record-row').count(), 0);
}

const browser = await chromium.launch();
const ctx = await browser.newContext();
// 绕过登录闸门（App 只按 localStorage.token 判定；后端不可用不影响进入工作区）。
await ctx.addInitScript(() => localStorage.setItem('token', 't3-error-state-e2e'));

/** 展开一级分组后点子菜单。 */
async function openGroup(page, groupLabel, childLabel) {
  const child = page.getByRole('button', { name: childLabel, exact: true });
  if (!(await child.isVisible())) {
    await page.getByRole('button', { name: groupLabel, exact: true }).click();
    await page.waitForTimeout(150);
  }
  await child.click();
  await page.waitForTimeout(700);
}

async function scenario(name, run) {
  const page = await ctx.newPage();
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

// 预热：vite dev 冷启动首次导航可能数十秒，不预热会把冷启动误判为失败。
{
  const warm = await ctx.newPage();
  warm.setDefaultNavigationTimeout(60_000);
  await warm.goto(`${BASE}/`, { waitUntil: 'domcontentloaded' });
  await warm.waitForSelector('.nav-item', { timeout: 60_000 });
  await warm.close();
}

// ── 断网模式：后端停机 ────────────────────────────────────────────────
const offlineCtx = await browser.newContext();
await offlineCtx.addInitScript(() => localStorage.setItem('token', 't3-error-state-e2e'));
await offlineCtx.route('**/api/v1/**', (route) => route.abort());
const offline = await offlineCtx.newPage();
offline.setDefaultNavigationTimeout(60_000);
offline.setDefaultTimeout(60_000);

// 1) 数据集列表
await scenario('数据集列表（后端停机）', async () => {
  const page = offline;
  await page.goto(`${BASE}/#/data-center/datasets`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.dataset-workspace', { timeout: 30_000 });
  await page.waitForSelector('.error-state', { timeout: 30_000 });
  await assertErrorState(page, '数据集列表', 1);
  await assertNoDemoData(page, '数据集列表');
  // 重试不得把页面打崩：点完仍应停在错误态。
  await page.getByRole('button', { name: '重试' }).first().click();
  await page.waitForTimeout(1200);
  check('数据集列表 · 重试后仍为错误态（不崩）', await page.locator('.error-state').count() > 0, true);
});

// 2) 数据登记
await scenario('数据登记（后端停机）', async () => {
  const page = offline;
  await page.goto(`${BASE}/#/data-center/registration`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.registration-layout', { timeout: 30_000 });
  await page.waitForSelector('.error-state', { timeout: 30_000 });
  // 三块数据各自独立报错：数据集下拉 / 最近登记 / 可选项字典。
  await assertErrorState(page, '数据登记', 3);
  await assertNoDemoData(page, '数据登记');
  // T3.3：字典与数据集都不可用时禁止提交。
  check('数据登记 · 提交按钮禁用（aria-disabled）', await page.locator('.full-button').first().getAttribute('aria-disabled'), 'true');
  // 该按钮刻意不用原生 disabled（要能接收点击并给出缺失原因），Playwright 会把 aria-disabled
  // 当作不可点击而一直等待——这里强制点击，验证的正是"禁用态被点"这条路径。
  await page.locator('.full-button').first().click({ force: true });
  await page.waitForTimeout(400);
  check('数据登记 · 点击禁用按钮给出原因', await page.locator('.toolbar-error').count() > 0, true);
});

// 3) 分析「选择数据」
await scenario('分析选择数据（后端停机）', async () => {
  const page = offline;
  await page.goto(`${BASE}/#/analysis/select`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.selection-workspace', { timeout: 30_000 });
  await page.waitForSelector('.error-state', { timeout: 30_000 });
  check('分析选择数据 · 无可选卡片', await page.locator('.selection-card').count(), 0);
  await assertNoDemoData(page, '分析选择数据');
});

// ── 拦截模式：只放行 /datasets 与 /welds，其余照旧停机 ─────────────────
const mockRecord = {
  weld_id: 'WLD-E2E-0001',
  weld_name: 'E2E 测试样本',
  registration_no: 'REG-E2E-00001',
  source: 'E2E 产线',
  machine: 'E2E 焊机',
  material: 'Q235',
  quality: '通过',
  modalities: ['视频', '时序'],
  dataset_id: 9001,
  collected_at: '2026-09-01T10:00:00',
  created_at: '2026-09-01T10:00:00',
  latest_version_id: 4242,
  latest_version: { id: 4242, version_no: 'v1.0', object_keys: [] },
};
const envelope = (data) => ({
  status: 200,
  contentType: 'application/json',
  body: JSON.stringify({ code: 0, message: 'ok', data }),
});

const partialCtx = await browser.newContext();
await partialCtx.addInitScript(() => localStorage.setItem('token', 't3-error-state-e2e'));
await partialCtx.route('**/api/v1/**', (route) => {
  const url = route.request().url();
  if (/\/api\/v1\/(datasets|welds)(\?|$)/.test(url)) {
    const data = url.includes('/welds')
      ? { items: [mockRecord], total: 1, page: 1, page_size: 20 }
      : [{ id: 9001, dataset_no: 'DS-E2E', name: 'E2E 数据集', task: '目标检测', status: '标注中', sample_count: 1, progress: 0, split: {}, current_version_id: 4242, weld_count: 1 }];
    return route.fulfill(envelope(data));
  }
  return route.abort();
});

// 4) 数据核验：先用顶部选择器选中一条样本（T5 的恢复路径），再让该页的接口全部失败
await scenario('数据核验（选中样本后后端停机）', async () => {
  const page = await partialCtx.newPage();
  page.setDefaultNavigationTimeout(60_000);
  page.setDefaultTimeout(60_000);
  // 直接深链进核验页：无数据上下文 → 走 T5 的守卫引导（这是预期，不是错误态）。
  await page.goto(`${BASE}/#/data-center/validation`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.selection-required', { timeout: 30_000 });
  check('数据核验 · 未选数据时给引导（而非白屏/假数据）', await page.locator('.selection-required').count(), 1);

  // 用页顶选择器补上上下文（数据上下文不入 URL，深链/重载后必须能这样恢复）。
  const selects = page.locator('.selection-switcher select');
  await selects.nth(1).selectOption('WLD-E2E-0001');
  await page.waitForTimeout(1200);
  await page.waitForSelector('.validation-summary', { timeout: 30_000 });
  await page.waitForSelector('.error-state', { timeout: 30_000 });
  check('数据核验 · 评分显示占位符而非演示分数', await page.locator('.score-ring strong').innerText(), '—');
  check('数据核验 · 规则区无演示规则', await page.locator('.validation-rule').count(), 0);
  check('数据核验 · S12 无报告时禁用导出', await page.locator('.page-toolbar .outline-button').first().isDisabled(), true);
  await assertNoDemoData(page, '数据核验');
  await page.close();
});

await browser.close();
await offlineCtx.close();
await partialCtx.close();

const failed = results.filter((item) => !item.ok);
console.log('\n===== T3 错误态实机验收结果 =====');
for (const item of results) console.log(`${item.ok ? '✔' : '✖'} ${item.label} ${item.detail}`);
console.log(`\n共 ${results.length} 条断言，通过 ${results.length - failed.length}，失败 ${failed.length}`);
if (failed.length) process.exitCode = 1;
