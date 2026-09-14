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

//: 登记提交的真实请求体（T4b：断言拆列后的新字段与类型，而不是只看界面渲染）
let registrationBody = null;
//: 是否点过「重新导入」（T4.4）
let reimported = false;

/** 登记链路状态的桩（T4.4）：默认回 `failed`，好断言"失败时可重新导入"这条路。 */
const INGEST_STATE = (status, failedKeys) => ({
  registration_no: 'REG-E2E-00001',
  weld_id: 'WLD-E2E-0001',
  status,
  uploaded_files: 1,
  csv_total: 1,
  csv_failed: failedKeys.map((key) => ({ source_object_key: key, message: '信号列不完整' })),
});

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
  if (method === 'POST' && /\/registrations\/[^/]+\/raw-files/.test(url)) return route.fulfill(envelope({ id: 4242, version_no: 'v1.0', object_keys: ['raw/e2e-signal.csv'], dataset_build: { dataset_version_id: 4244, version_no: 'v1.3', job_id: 'job_e2e_building' } }));
  if (method === 'POST' && /\/registrations$/.test(url)) {
    registrationBody = route.request().postDataJSON();
    return route.fulfill(envelope({ id: 1, weld_id: 'WLD-E2E-0001', registration_no: 'REG-E2E-00001' }));
  }
  if (/\/files\/presign-upload/.test(url)) return route.fulfill(envelope({ object_key: 'raw/e2e-signal.csv', upload_url: 'https://fake.local/put' }));
  // T4.4：登记链路状态——第一次 `importing`（结果卡显示"导入中…"），点重新导入后回 `ready`
  if (/\/registrations\/[^/]+\/reimport/.test(url)) { reimported = true; return route.fulfill(envelope(INGEST_STATE('ready', []))); }
  if (/\/registrations\/[^/]+\/ingest-status/.test(url)) return route.fulfill(envelope(reimported ? INGEST_STATE('ready', []) : INGEST_STATE('failed', ['raw/e2e-signal.csv'])));
  if (/\/datasets\/DS-E2E\/dimensions/.test(url)) return route.fulfill(envelope(DIMENSIONS));
  // 成员表要有行才会渲染表格（空成员时是空态）——这里给 1 条，好断言表头契约。
  if (/\/datasets\/DS-E2E\/versions\/4242\/items/.test(url)) return route.fulfill(envelope({
    items: [{ sample_id: 1, weld_id: 'WLD-E2E-0001', weld_name: 'E2E 样本', registration_no: 'REG-E2E-00001', source: 'E2E 产线', machine: 'E2E 焊机', modalities: ['视频'], quality: '通过', split: 'train', frame_no: 1, created_at: '2026-09-01T10:00:00' }],
    total: 1,
    page: 1,
    page_size: 20,
  }));
  if (/\/datasets\/DS-E2E\/versions\/4242/.test(url)) return route.fulfill(envelope(VERSION));
  // T8：三条版本分别处于 构建中 / 构建失败 / 已完成，用于断言版本行的状态与动作
  if (/\/datasets\/DS-E2E\/versions/.test(url)) return route.fulfill(envelope([
    VERSION,
    { ...VERSION, id: 4243, version_no: 'v1.2', build_status: 'failed', build_job_id: 'job_e2e_failed' },
    { ...VERSION, id: 4244, version_no: 'v1.3', build_status: 'pending', build_job_id: 'job_e2e_building' },
  ]));
  if (/\/jobs\/job_e2e/.test(url)) return route.fulfill(envelope({ id: 'job_e2e_building', type: 'dataset_build', status: 'running', progress: 40, result: null, error: null, created_at: null, finished_at: null }));
  if (/\/datasets\/DS-E2E\/lineage/.test(url)) return route.fulfill(envelope([{ type: 'records', label: '原始样本数据', count: 2, items: [] }]));
  if (/\/datasets\/DS-E2E/.test(url)) return route.fulfill(envelope(DATASET));
  // T9：`?options=1` 是不分页的轻量数组；不带 options 的列表接口回分页对象。
  // 这里顺便用 `q` 验证"搜索真的走了服务端"：不匹配的关键词回空页。
  if (/\/datasets\?.*options=1/.test(url)) return route.fulfill(envelope([{ id: DATASET.id, dataset_no: DATASET.dataset_no, name: DATASET.name, task: DATASET.task, status: DATASET.status, sample_count: DATASET.sample_count, weld_count: DATASET.weld_count, progress: DATASET.progress, current_version_id: DATASET.current_version_id, version: DATASET.version, split: DATASET.split }]));
  if (/\/datasets\?/.test(url) && /q=zzz/.test(url)) return route.fulfill(envelope({ items: [], total: 0, page: 1, page_size: 20 }));
  if (/\/datasets(\?|$)/.test(url)) return route.fulfill(envelope({ items: [DATASET], total: 1, page: 1, page_size: 20 }));
  // 切分页（T10）：版本链 / 信号 / 最近一次对齐任务（视频轨道带 25 fps）
  if (/\/welds\/WLD-E2E-0001\/versions\/4242\/alignment-tasks\/latest/.test(url)) return route.fulfill(envelope({ id: 'job_align_e2e', type: 'alignment', status: 'succeeded', progress: 100, result: { events: { weld_segment: [0, 83] }, event_source: 'real', tracks: [{ channel: 'video', modality: 'video', availability: 'available', aligned: true, metadata: { fps: 25 } }], assets: [] }, error: null, created_at: null, finished_at: null }));
  if (/\/welds\/WLD-E2E-0001\/versions\/4242\/split-preview/.test(url)) return route.fulfill(envelope({ input: { version_id: 4242, duration: 83, sample_rate: 10000, source: 'real', video_fps: 25 }, events: { weld_segment: [0, 83] }, summary: { sample_count: 207, effective_start: 0, effective_end: 83, window_seconds: 0.4, stride_seconds: 0.4, window_frames: 10, stride_frames: 10, window_samples: 4000 }, windows: [] }));
  if (/\/signals/.test(url)) return route.fulfill(envelope({ duration: 83, sample_rate: 10000, source: 'real', events: { weld_segment: [0, 83] }, anomalies: [], channels: [{ id: 'cur', name: '电流', unit: 'A', values: [1, 2, 3], lo: 0, hi: 200, mean: 180 }, { id: 'vol', name: '电压', unit: 'V', values: [1, 2, 3], lo: 0, hi: 30, mean: 22 }] }));
  if (/\/welds\/WLD-E2E-0001\/versions/.test(url)) return route.fulfill(envelope([{ id: 4242, record_id: 7, version_no: 'v1.0', action: '原始数据', operator: null, note: null, object_keys: [], created_at: '2026-09-01T10:00:00' }]));
  if (/\/jobs\/job_align_e2e/.test(url)) return route.fulfill(envelope({ id: 'job_align_e2e', type: 'alignment', status: 'succeeded', progress: 100, result: { events: { arc: 0.2, weld_segment: [0, 83], tail: 82.9 }, event_source: 'real', tracks: [{ channel: 'video', modality: 'video', availability: 'available', aligned: true, metadata: { fps: 25, duration: 83 } }], assets: [] }, error: null, created_at: null, finished_at: null }));
  // 单条样本详情要先于列表规则匹配：否则详情会拿到分页对象，`record.modalities.join` 直接崩。
  if (/\/welds\/WLD-E2E-0001/.test(url)) return route.fulfill(envelope(RECORD));
  // R5：选择器的 `/welds` 是**服务端分页**的——25 条样本分两页，第 51 条之后也必须选得到。
  // 第 1 页塞进 RECORD（顶部选择器的既有断言要用它），其余用合成行补齐。
  if (/\/welds\?/.test(url)) {
    const page = Number(new URL(url).searchParams.get('page') ?? 1);
    const synth = (i) => ({ ...RECORD, weld_id: `WLD-E2E-${1000 + i}`, weld_name: `合成样本 ${i}`, latest_version_id: null, latest_version: null });
    const items = page === 1 ? [RECORD, ...Array.from({ length: 19 }, (_, i) => synth(i))] : Array.from({ length: 5 }, (_, i) => synth(19 + i));
    return route.fulfill(envelope({ items, total: 25, page, page_size: 20 }));
  }
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
  // T9：列表搜索走服务端（关键词不匹配 → 服务端回空页）+ 分页器存在
  check('列表有分页器', await page.locator('.pagination').count() > 0, true);
  await page.locator('.dataset-rule .inline-search input').fill('zzz');
  await page.waitForTimeout(800);
  check('搜索走服务端（无匹配时回空态）', await page.locator('.dataset-empty-state').count() > 0, true);
  await page.locator('.dataset-rule .inline-search input').fill('');
  await page.waitForSelector('.dataset-list-row', { timeout: 30_000 });
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
  // T8：版本列表状态——构建中给状态不给动作、构建失败给「重新构建」
  await page.getByRole('button', { name: '返回概览' }).click();
  await page.waitForSelector('.dataset-version-list', { timeout: 30_000 });
  // 概览是重新挂载的：版本行要等接口回来（容器先于行出现）
  await waitForStep(page, '.dataset-version:nth-child(3)', '版本行');
  const versionRows = await page.locator('.dataset-version').allInnerTexts();
  check('版本行显示「构建中」', versionRows.some((row) => row.includes('构建中')), true);
  check('版本行显示「构建失败」+ 重新构建', versionRows.some((row) => row.includes('构建失败') && row.includes('重新构建')), true);
  const buildingRow = page.locator('.dataset-version.building').first();
  check('构建中的版本行标记为不可进入', await buildingRow.count(), 1);
  await clickStep(buildingRow, '构建中的版本行');
  await page.waitForTimeout(600);
  check('点构建中的版本行不进入切片（仍在概览）', (await page.locator('.dataset-detail-grid').count()), 1);
  await page.getByRole('button', { name: /查看当前数据集版本/ }).click();
  await page.waitForSelector('.dataset-records-table', { timeout: 30_000 });
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
  // T4b/R1：电流与电压是**两个独立输入框**（各自带单位），不再是"180 A / 22 V"一格
  check('电流与电压是拆开的两个输入框', await page.locator('input[placeholder="例如：180"]').count() + await page.locator('input[placeholder="例如：22"]').count(), 2);
  await page.locator('input[placeholder="例如：Q235B"]').fill('Q235');
  await page.locator('input[placeholder="例如：6"]').fill('6');
  await page.locator('input[placeholder="例如：180"]').fill('180');
  await page.locator('input[placeholder="例如：22"]').fill('22');
  await clickStep(page.locator('.form-panel .full-button'), '登记数据');
  await waitForStep(page, '.app-dialog', '默认值汇总确认弹窗');
  check('提交前弹出默认值确认（列出仍是默认值的字段）', (await page.locator('.dialog-items li').count()) > 0, true);
  await clickStep(page.getByRole('button', { name: '确认无误，提交' }), '确认无误，提交');
  // T4b：提交载荷必须是拆列后的新字段（数字）——旧字段不再出现
  check('登记载荷带 current_a = 180（数字）', registrationBody?.current_a, 180);
  check('登记载荷带 voltage_v = 22（数字）', registrationBody?.voltage_v, 22);
  check('登记载荷厚度剥掉单位', registrationBody?.thickness, '6');
  check('登记载荷不再带旧的 current_voltage', 'current_voltage' in (registrationBody ?? {}), false);
  await waitForStep(page, '.registration-result', '登记结果卡');
  const exits = await page.locator('.registration-result-actions button').allInnerTexts();
  check('结果卡给出三个出口', exits.join('/'), '查看这条数据/继续登记下一条/去数据核验');
  check('结果卡显示登记编号', (await page.locator('.registration-result h2').innerText()).includes('REG-E2E-00001'), true);
  await page.waitForTimeout(800);
  check('结果卡显示数据集版本构建状态（T8）', (await page.locator('.registration-result').innerText()).includes('构建中'), true);
  // T4.4：结果卡给出**信号导入**状态（与"登记成功"是两件事），失败时能重新导入
  check('结果卡显示信号导入状态', (await page.locator('.registration-result').innerText()).includes('导入失败'), true);
  check('导入失败时列出失败文件与原因', (await page.locator('.registration-result').innerText()).includes('raw/e2e-signal.csv'), true);
  await clickStep(page.getByRole('button', { name: '重新导入' }), '重新导入');
  await page.waitForTimeout(600);
  check('点「重新导入」调用了后端 reimport 接口', reimported, true);
  check('重新导入后状态回到可分析', (await page.locator('.registration-result').innerText()).includes('可分析'), true);
  await clickStep(page.getByRole('button', { name: '继续登记下一条' }), '继续登记下一条');
  await waitForStep(page, '.locked-dataset', '继续登记后的表单');
  check('继续登记保留数据集上下文且清空样本名称', await page.locator('input[placeholder="输入样本名称（焊缝 / 批次）"]').inputValue(), '');

  // T10：切分页——帧与采样率必须分开（改造前界面显示"10 帧 ≈ 00:00.00"）
  await page.goto(`${BASE}/#/analysis/split`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(500);
  await page.locator('.selection-switcher select').nth(1).selectOption('WLD-E2E-0001');
  await waitForStep(page, '.cut-summary', '切分统计卡');
  // 采样率来自 /signals（异步）——先等它落地，否则会读到 fallback 的 1000 Hz（曾经因此假失败）
  await page.waitForFunction(() => document.body.innerText.includes('10000 Hz'), null, { timeout: 20_000 }).catch(() => {});
  const splitText = await page.locator('.cut-summary').innerText();
  check('切片时长给出帧与秒两个口径', splitText.includes('10 帧') && splitText.includes('0.400 秒'), true);
  check('时序窗口 = 切片秒数 × 时序采样率', (splitText.match(/([\d,]+) 采样点/)?.[1] ?? '无采样点'), '4,000');
  const splitBody = await text();
  check('页面上同时给出视频帧率与时序采样率', `fps=${splitBody.includes('fps')}, hz=${splitBody.includes('10000 Hz')}`, 'fps=true, hz=true');
  // 旧缺陷的原文是「10 帧 ≈ 00:00.00」（把帧当采样点算时长）；时间轴上的 00:00.00 是正常刻度
  check('不再出现"帧 ≈ 时分秒"的换算', splitBody.includes('帧 ≈'), false);
  check('单位选择器存在且当前为帧', await page.locator('.split-control').first().inputValue(), 'frame');

  // R5：分析「选择数据」的卡片是服务端分页的——第 51 条之后要继续可达（原先写死 50 条且没有翻页）
  await page.goto(`${BASE}/#/analysis/select`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.selection-card', { timeout: 30_000 });
  check('选择数据首页只渲染一页（20 条，不是全量）', await page.locator('.selection-card').count(), 20);
  check('还有下一页时给出「加载更多」', (await page.locator('.selection-workspace .selection-load-more').innerText()).includes('共 25'), true);
  await clickStep(page.locator('.selection-workspace .selection-load-more'), '加载更多');
  await page.waitForTimeout(500);
  check('加载更多后第 21–25 条可达', await page.locator('.selection-card').count(), 25);
  check('取完最后一页后按钮消失', await page.locator('.selection-workspace .selection-load-more').count(), 0);

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
