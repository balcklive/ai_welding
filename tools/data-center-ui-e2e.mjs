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

/** 带步骤名的等待：超时时错误信息直接指出卡在哪一步（批量导航断言时很好用）。 */
const waitForStep = async (page, selector, label) => {
  try {
    await page.waitForSelector(selector, { timeout: 30_000 });
  } catch {
    throw new Error(`等待「${label}」超时（${selector}）`);
  }
};

/** 带步骤名的点击：失败时指出点的是哪一步。 */
const clickStep = async (locator, label) => {
  try {
    await locator.click({ timeout: 20_000 });
  } catch (err) {
    throw new Error(`点击「${label}」失败（${String(err.message).slice(0, 60)}）`);
  }
};

const browser = await chromium.launch();
const ctx = await browser.newContext();
await ctx.addInitScript(() => localStorage.setItem('token', 'data-center-ui-e2e'));
// 注意：`DatasetWorkspace` 用 `dataset_no`（DS-E2E）而不是数字 id 请求详情，
// 所以下面的匹配都按 DS-E2E 写；顺序也要紧——items 在 versions 之前。
await ctx.route(API, (route) => {
  const url = route.request().url();
  const method = route.request().method();
  // 登记页（T4a）：可选项字典 + 提交链路（POST /registrations → 预签名 → 挂载）
  if (/\/settings\/options/.test(url)) return route.fulfill(envelope({ groups: [
    { key: 'machine', label: '焊机型号', description: '', color: null, free_text: false, items: [{ id: 1, value: 'E2E 焊机', color: null, active: true, sort_order: 10 }] },
    { key: 'weld_method', label: '焊接方法', description: '', color: null, free_text: false, items: [{ id: 2, value: 'MAG焊', color: null, active: true, sort_order: 10 }] },
    { key: 'source', label: '数据来源', description: '', color: null, free_text: true, items: [] },
    { key: 'product', label: '产品信息', description: '', color: null, free_text: true, items: [] },
  ] }));
  if (method === 'POST' && /\/registrations\/[^/]+\/raw-files/.test(url)) return route.fulfill(envelope({ id: 4242, version_no: 'v1.0', object_keys: ['raw/e2e-signal.csv'] }));
  if (method === 'POST' && /\/registrations$/.test(url)) return route.fulfill(envelope({ id: 1, weld_id: 'WLD-E2E-0001', registration_no: 'REG-E2E-00001' }));
  if (/\/files\/presign-upload/.test(url)) return route.fulfill(envelope({ object_key: 'raw/e2e-signal.csv', upload_url: 'https://fake.local/put' }));
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
  // 单条样本详情要先于列表规则匹配：否则详情会拿到分页对象，`record.modalities.join` 直接崩。
  if (/\/welds\/WLD-E2E-0001/.test(url)) return route.fulfill(envelope(RECORD));
  if (/\/welds/.test(url)) return route.fulfill(envelope({ items: [RECORD], total: 1, page: 1, page_size: 20 }));
  return route.fulfill(envelope([]));
});

// 预签名直传的 PUT 落在「对象存储」域上：给个空 200，避免登记链路卡在 XHR。
await ctx.route('https://fake.local/**', (route) => route.fulfill({ status: 200, body: '' }));

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

  // T6.1/T6.2：面包屑骨架与用词（含可点回流）
  await page.locator('.page-breadcrumb button', { hasText: '数据集' }).first().click();
  await page.waitForTimeout(600);
  check('面包屑「数据集」可点回列表', await page.locator('.dataset-workspace h2').first().innerText(), '数据集列表');
  await page.locator('.dataset-list-row').first().click();
  await page.waitForSelector('.dataset-detail-grid', { timeout: 30_000 });
  const crumbText = () => page.locator('.page-breadcrumb').first().innerText();
  check('概览面包屑 = 数据管理 / 数据集 / E2E 数据集', (await crumbText()).replace(/\s+/g, ''), '数据管理/数据集/E2E数据集');
  await page.getByRole('button', { name: /查看当前数据集版本/ }).click();
  await page.waitForSelector('.dataset-records-table', { timeout: 30_000 });
  check('成员页面包屑含「数据集版本 v1.1」', (await crumbText()).includes('数据集版本 v1.1'), true);
  check('上下文条用统一 class（.context-bar）', await page.locator('.context-bar').count(), 1);

  // T5 核对项（自包含场景，重新进入以免依赖上面的视图状态）：
  // 成员详情 →「继续处理 → 数据核验」自动带入该条数据（不应落到守卫页）
  // 坑：hash 没变时 goto 同一 URL 不会重载，页面仍停在上一个视图（数据集内部层级是组件 state）
  // → 必须用 reload() 才能回到列表。
  await page.reload({ waitUntil: 'domcontentloaded' });
  await waitForStep(page, '.dataset-list-row', '数据集列表行');
  await clickStep(page.locator('.dataset-list-row').first(), '数据集列表行');
  await waitForStep(page, '.dataset-detail-grid', '数据集概览');
  await clickStep(page.getByRole('button', { name: /查看全部样本/ }), '查看全部样本');
  await waitForStep(page, '.dataset-records-table', '全部样本表');
  await clickStep(page.locator('.dataset-record-row:not(.dataset-record-head)').first(), '全部样本首行');
  await waitForStep(page, '.dataset-record-detail', '成员详情');
  await clickStep(page.locator('.dataset-record-detail button', { hasText: '数据核验' }).first(), '继续处理-数据核验');
  await page.waitForTimeout(1200);
  check('从成员详情进核验：页面已带入该条数据（不是守卫页）', await page.locator('.selection-required').count(), 0);
  check('核验页渲染出结果区', await page.locator('.validation-summary').count(), 1);
  check('顶部选择器已带上该样本', (await page.locator('.selection-switcher select').nth(1).inputValue()), 'WLD-E2E-0001');

  // T5：核验页无数据上下文时的守卫（选择器强调态 + 引导按钮在本页完成）
  // 数据上下文不入 URL，所以"重新回到无上下文状态"只能靠 reload（goto 同一 URL 不会重载）。
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.selection-required', { timeout: 30_000 });
  check('守卫页存在', await page.locator('.selection-required').count(), 1);
  check('顶部选择器置为强调态', await page.locator('.selection-switcher.needs-attention').count(), 1);
  check('选择器给出提示文案', (await page.locator('.selection-switcher-hint').innerText()).includes('本页需要数据上下文'), true);
  const hereBtn = page.getByRole('button', { name: '在本页选择数据' });
  check('S3 按钮文案改为「在本页选择数据」', await hereBtn.count(), 1);
  const hashBefore = await page.evaluate(() => location.hash);
  await hereBtn.click();
  await page.waitForTimeout(400);
  check('点按钮不跳走（仍在本页）', await page.evaluate(() => location.hash), hashBefore);

  // T6.2：登记页面包屑（由框架渲染，位于上下文条之前）
  await page.goto(`${BASE}/#/data-center/registration`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.registration-layout', { timeout: 30_000 });
  check('登记页面包屑 = 数据管理 / 数据登记', (await crumbText()).replace(/\s+/g, ''), '数据管理/数据登记');

  // T4a：无上下文进入 → 先选所属数据集并锁定；默认值可见可识别；提交前汇总确认；成功后三个出口
  await page.reload({ waitUntil: 'domcontentloaded' });
  await waitForStep(page, '.registration-step', '第 1 步：选择所属数据集');
  check('未带上下文时先走「选择所属数据集」步骤', await page.locator('.registration-step').count(), 1);
  await page.locator('.registration-step select').selectOption(String(DATASET.id));
  await clickStep(page.getByRole('button', { name: '确认并填写登记信息' }), '确认所属数据集');
  await waitForStep(page, '.locked-dataset', '所属数据集锁定提示');
  check('锁定后显示只读的所属数据集', (await page.locator('.locked-dataset').innerText()).includes('E2E 数据集'), true);

  // 默认值（字典首项）必须带"默认"标记
  check('默认值字段带「默认」标记', await page.locator('.default-mark').count() > 0, true);
  // 锚定一个带时间列的 CSV：采样率应从文件推导出来（T4.2.1 来源 2）
  const csv = ['time,Current,Voltage,GasSpeed,WireSpeed'];
  for (let i = 0; i < 400; i += 1) csv.push(`${(i / 2000).toFixed(4)},180,22,15,8`);
  await page.locator('.upload-zones input[type="file"]').first().setInputFiles({ name: 'e2e-signal.csv', mimeType: 'text/csv', buffer: Buffer.from(csv.join('\n')) });
  await page.waitForTimeout(600);
  check('从上传的 CSV 推导出采样率默认值', (await page.locator('input[placeholder="10 kHz"]').inputValue()), '2 kHz');
  // 填完必填项 → 提交 → 必须先弹"默认值确认"
  await page.locator('input[placeholder="例如：产线相机 · 03号"]').fill('E2E 产线');
  await page.locator('input[placeholder="输入样本名称（焊缝 / 批次）"]').fill('E2E 样本');
  await clickStep(page.locator('.form-panel .full-button'), '登记数据');
  await waitForStep(page, '.app-dialog', '默认值汇总确认弹窗');
  check('提交前弹出默认值确认（列出仍是默认值的字段）', (await page.locator('.dialog-items li').count()) > 0, true);
  await clickStep(page.getByRole('button', { name: '确认无误，提交' }), '确认无误，提交');
  await waitForStep(page, '.registration-result', '登记结果卡');
  const exits = await page.locator('.registration-result-actions button').allInnerTexts();
  check('结果卡给出三个出口', exits.join('/'), '查看这条数据/继续登记下一条/去数据核验');
  check('结果卡显示登记编号', (await page.locator('.registration-result h2').innerText()).includes('REG-E2E-00001'), true);
  await clickStep(page.getByRole('button', { name: '继续登记下一条' }), '继续登记下一条');
  await waitForStep(page, '.locked-dataset', '继续登记后的表单');
  check('继续登记保留数据集上下文且清空样本名称', await page.locator('input[placeholder="输入样本名称（焊缝 / 批次）"]').inputValue(), '');

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
