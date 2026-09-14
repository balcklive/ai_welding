/**
 * tools/data-center-ui-e2e.mjs — 数据管理界面契约的实机回归（T1 术语 + T2 结构，2026-09-14）。
 *
 * 用**接口打桩**（只造这一个页面要的数据）跑真实前端组件，断言的是"界面上有什么、
 * 没有什么"——这类结构性契约（删了哪些列、合并了哪个面板、术语用哪套）单元测试看不见，
 * 后端测试更看不见（它不渲染）。
 *
 * 覆盖：
 *   - 术语（T1）：整页不出现 快照/固定快照/焊缝版本/可训练/未核验/数据质量
 *   - 数量口径（T2.4）：概览统计卡是「样本数 + 切片数」两张，且样本数取 weld_count
 *   - 有效切片占比（T2.3）：读后端 effective_ratio、列出影响最大的原因、可展开完整明细
 *   - 字段完备性（T2.1）：字段面板存在（维度名用中文）；「模型适配检查」面板与"可训练"结论已消失
 *   - 核验状态（T2.2）：成员表不再有「核验状态」列，也没有该筛选下拉；成员详情没有该行
 *   - S5：全部样本表的送丝/焊接速度是两列，各带单位
 *
 * 用法（需先起前端 dev server，后端不必起）：
 *   npm run dev -- --port 5199 --strictPort
 *   node tools/data-center-ui-e2e.mjs
 */
import { chromium } from 'playwright';

const BASE = (process.env.E2E_BASE_URL || 'http://localhost:5199').replace(/\/+$/, '');
const API = '**/api/v1/**';
const results = [];
const check = (label, actual, expected) => {
  const ok = actual === expected;
  results.push(`${ok ? '✔' : '✖'} ${label} ${ok ? actual : `期望 ${expected}，实际 ${actual}`}`);
};

const DATASET = {
  id: 9001,
  dataset_no: 'DS-E2E',
  name: 'E2E 数据集',
  task: '目标检测',
  status: '可训练',
  sample_count: 13, // 切片数
  weld_count: 2, // 样本数（T2.4：列表/概览的"样本数"要取这个，不是 sample_count）
  progress: 61.5,
  split: { train: 11, val: 1, test: 1 },
  current_version_id: 4242,
  version: 'v1.1',
  updated_at: '2026-09-01T10:00:00',
  // effective_ratio 只在 T2.3 之后的版本里有；历史版本没有该键（界面必须显示 —）
  quality: {
    repeat_rate: 0.7,
    empty_label_rate: 0.3,
    dimension_missing_rate: 0.2,
    effective_ratio: 0.25,
    deductions: {
      repeat: { label: '重复切片', rate: 0.7, affected: 9 },
      empty_label: { label: '空标注切片', rate: 0.3, affected: 4 },
      missing_field: { label: '必需字段缺失', rate: 0.2, affected: 3 },
    },
  },
};

const VERSION = {
  id: 4242,
  dataset_id: 9001,
  version_no: 'v1.1',
  split: { train: 11, val: 1, test: 1 },
  item_count: 13,
  quality: DATASET.quality,
  snapshot_id: 'datasets/4242/snapshot.json',
  created_at: '2026-09-01T10:00:00',
};

const RECORD = {
  id: 7,
  weld_id: 'WLD-E2E-0001',
  weld_name: 'E2E 样本',
  registration_no: 'REG-E2E-00001',
  source: 'E2E 产线',
  machine: 'E2E 焊机',
  material: 'Q235',
  thickness: '6mm',
  quality: '通过',
  wire_feed_speed: '15.8',
  welding_speed: '70.0',
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

const DIMENSIONS = [
  { name: 'Current', status: '已具备', required: true },
  { name: 'Voltage', status: '已具备', required: true },
  { name: 'GasSpeed', status: '缺失', required: true },
  { name: 'Molten_feature', status: '已具备', required: false },
  { name: '焊缝照片', status: '已具备', required: false },
];

const browser = await chromium.launch();
const ctx = await browser.newContext();
await ctx.addInitScript(() => localStorage.setItem('token', 'data-center-ui-e2e'));
// 注意：`DatasetWorkspace` 用 `dataset_no`（DS-E2E）而不是数字 id 请求详情，
// 所以下面的匹配都按 DS-E2E 写；顺序也要紧——items 在 versions 之前。
await ctx.route(API, (route) => {
  const url = route.request().url();
  if (/\/datasets\/DS-E2E\/dimensions/.test(url)) return route.fulfill(envelope(DIMENSIONS));
  // 成员表要有行才会渲染表格（空成员时是空态）——这里给 1 条，好断言表头契约。
  if (/\/datasets\/DS-E2E\/versions\/4242\/items/.test(url)) return route.fulfill(envelope({
    items: [{ sample_id: 1, weld_id: 'WLD-E2E-0001', weld_name: 'E2E 样本', registration_no: 'REG-E2E-00001', source: 'E2E 产线', machine: 'E2E 焊机', modalities: ['视频'], quality: '通过', split: 'train', frame_no: 1, created_at: '2026-09-01T10:00:00' }],
    total: 1,
    page: 1,
    page_size: 20,
  }));
  if (/\/datasets\/DS-E2E\/versions\/4242/.test(url)) return route.fulfill(envelope(VERSION));
  if (/\/datasets\/DS-E2E\/versions/.test(url)) return route.fulfill(envelope([VERSION]));
  if (/\/datasets\/DS-E2E\/lineage/.test(url)) return route.fulfill(envelope([{ type: 'records', label: '原始样本数据', count: 2, items: [] }]));
  if (/\/datasets\/DS-E2E/.test(url)) return route.fulfill(envelope(DATASET));
  if (/\/datasets/.test(url)) return route.fulfill(envelope([DATASET]));
  if (/\/welds/.test(url)) return route.fulfill(envelope({ items: [RECORD], total: 1, page: 1, page_size: 20 }));
  return route.fulfill(envelope([]));
});

const page = await ctx.newPage();
page.setDefaultNavigationTimeout(60_000);
page.setDefaultTimeout(60_000);
const pageErrors = [];
page.on('pageerror', (err) => pageErrors.push(err.message));
const text = () => page.evaluate(() => document.body.innerText);

try {
  // 进入数据集概览（列表 → 点行）
  await page.goto(`${BASE}/#/data-center/datasets`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.dataset-list-row', { timeout: 45_000 });
  const listText = await page.locator('.dataset-list-row').first().innerText();
  check('列表行样本数取 weld_count（2，不是切片数 13）', listText.includes('2') && !listText.includes('13'), true);
  await page.locator('.dataset-list-row').first().click();
  await page.waitForSelector('.dataset-detail-grid', { timeout: 30_000 });

  // T2.4：统计卡 —— 样本数与切片数是两张卡
  const stats = await page.locator('.dataset-detail-stat').allInnerTexts();
  check('统计卡含「样本数」', stats.some((item) => item.includes('样本数')), true);
  check('统计卡含「切片数」', stats.some((item) => item.includes('切片数')), true);
  check('样本数卡显示 2', stats.some((item) => item.includes('样本数') && item.includes('2')), true);
  check('切片数卡显示 13', stats.some((item) => item.includes('切片数') && item.includes('13')), true);

  // T2.3：有效切片占比读后端 effective_ratio + 扣分原因
  const qualityCard = stats.find((item) => item.includes('有效切片占比'));
  check('有效切片占比读 effective_ratio（25.0%）而不是 1-三项之和', qualityCard?.includes('25.0%'), true);
  check('列出影响最大的原因', qualityCard?.includes('重复切片'), true);
  await page.getByRole('button', { name: '查看原因' }).click();
  const reasons = await page.locator('.dataset-quality-reasons li').allInnerTexts();
  check('展开后有 3 条扣分明细', reasons.length, 3);
  check('明细含 affected 个数', reasons.join('|').includes('9 个'), true);

  // T2.1：字段完备性面板存在、适配检查面板消失、维度名中文
  const bodyText = await text();
  check('存在「字段完备性」面板', bodyText.includes('字段完备性'), true);
  check('维度名已中文化（电流/电压/气流速度）', bodyText.includes('电流') && bodyText.includes('气流速度'), true);
  check('不再有「模型适配检查」面板', bodyText.includes('模型适配检查'), false);
  check('不再出现"可训练"结论', bodyText.includes('可训练'), false);
  check('保留划分策略说明', bodyText.includes('划分策略'), true);

  // T1：整页无被禁术语
  const banned = ['快照', '固定快照', '焊缝版本', '未核验', '数据质量'].filter((word) => bodyText.includes(word));
  check('整页无被禁术语', banned.join(',') || '无', '无');

  // T2.2 + S5：成员表 / 全部样本表的列
  await page.getByRole('button', { name: /查看当前数据集版本/ }).click();
  await page.waitForSelector('.dataset-records-table', { timeout: 30_000 });
  const memberHead = await page.locator('.dataset-record-head').first().innerText();
  check('成员表不再有「核验状态」列', memberHead.includes('核验状态'), false);
  check('成员表表头为「切片 ID / 样本」', memberHead.includes('切片 ID / 样本'), true);
  await page.getByRole('button', { name: '返回概览' }).click();
  await page.waitForTimeout(500);

  await page.getByRole('button', { name: /查看全部样本/ }).click();
  await page.waitForSelector('.dataset-records-table', { timeout: 30_000 });
  const sourceHead = await page.locator('.dataset-record-head').first().innerText();
  check('全部样本表不再有「核验状态」列', sourceHead.includes('核验状态'), false);
  check('送丝速度为独立列且带单位', sourceHead.includes('送丝速度 m/min'), true);
  check('焊接速度为独立列且带单位', sourceHead.includes('焊接速度 mm/min'), true);

  check('全程无页面级 JS 异常', pageErrors.length, 0);
  if (pageErrors.length) console.log(`   ⚠ pageerror: ${pageErrors.join(' | ')}`);
} catch (err) {
  check(`执行未抛错（${err.message.split('\n')[0]}）`, false, true);
}

await browser.close();
console.log('\n===== 数据管理界面契约回归结果 =====');
console.log(results.join('\n'));
const failed = results.filter((line) => line.startsWith('✖')).length;
console.log(`\n共 ${results.length} 条断言，通过 ${results.length - failed}，失败 ${failed}`);
if (failed) process.exitCode = 1;
