/**
 * 对齐页「可拖动胶片条」实机回归（2026-10）。
 *
 * 这些断言**静态测试钉不住**——它们依赖真实布局几何（标尺与轨道是否同起点）与真实手势
 * （拖动是否零网络、磁吸是否吸附），而且**要连真实后端**（真视频、真标定）。
 *
 * ```bash
 * node tools/alignment-film-e2e.mjs                     # 默认 http://localhost:8223
 * E2E_BASE_URL=http://182.61.59.135:8223 node tools/alignment-film-e2e.mjs
 * ```
 *
 * 账号从**仓库根 `.env` 的 `ADMIN_USERNAME`/`ADMIN_PASSWORD`** 读（环境变量优先）——
 * 不把明文密码写进仓库。登录走接口拿 token 直接塞 localStorage，比驱动登录表单稳。
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.join(__dirname, '..');

/** 从 .env 读一个键（不引 dotenv，就两行）。 */
function envValue(key) {
  if (process.env[key]) return process.env[key];
  try {
    const line = fs.readFileSync(path.join(REPO, '.env'), 'utf8')
      .split(/\r?\n/).find((l) => l.startsWith(`${key}=`));
    return line ? line.slice(key.length + 1).trim() : null;
  } catch {
    return null;
  }
}

// 与 `browser-history-e2e.mjs` 同一约定：用 E2E_BASE_URL 指定目标（端口与部署目标一致）
const BASE = process.env.E2E_BASE_URL || 'http://localhost:8223';
/** `mm:ss.xx` → 秒。页面上的读数与标尺都是这个格式。 */
const seconds = (t) => {
  const [m, s] = t.trim().split(':');
  return Number(m) * 60 + Number(s);
};

const results = [];
function check(name, ok, detail = '') {
  results.push({ name, ok, detail });
  console.log(`${ok ? '  ✓' : '  ✗'} ${name}${detail ? `  — ${detail}` : ''}`);
}

/** 标尺与每条轨道的几何：左偏与宽度差（本轮修的 144px 就是这里）。 */
async function rulerGeometry(page) {
  return page.evaluate(() => {
    const ruler = document.querySelector('.studio-ruler');
    if (!ruler) return null;
    const r = ruler.getBoundingClientRect();
    const tracks = [...document.querySelectorAll('.lane-track')].map((t) => {
      const b = t.getBoundingClientRect();
      return { left: b.left, width: b.width };
    });
    return { ruler: { left: r.left, width: r.width }, tracks };
  });
}

async function selectContext(page) {
  await page.getByLabel('数据集').selectOption({ index: 1 });
  await page.waitForTimeout(1200);
  await page.locator('select').filter({ hasText: '请选择一条样本' }).selectOption({ index: 1 });
  await page.waitForTimeout(6000);
}

async function main() {
  const username = envValue('ADMIN_USERNAME');
  const password = envValue('ADMIN_PASSWORD');
  if (!username || !password) {
    console.error('读不到 ADMIN_USERNAME / ADMIN_PASSWORD（.env 或环境变量）');
    process.exit(2);
  }

  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
  const page = await context.newPage();

  // 登录：直接拿 token 塞 localStorage（key 见 src/api/client.ts）
  const res = await context.request.post(`${BASE}/api/v1/auth/login`, {
    data: { username, password },
  });
  const body = await res.json();
  if (body.code !== 0) {
    console.error('登录失败', body);
    process.exit(2);
  }
  await page.goto(BASE);
  await page.evaluate((token) => localStorage.setItem('token', token), body.data.access_token);

  // ── 1. 三页标尺与轨道同起点（核心视觉修复） ──────────────────────────
  console.log('\n[1] 标尺与轨道同 left / 同宽（对齐页 · 分段页 · 标注页）');
  for (const route of ['analysis/alignment', 'analysis/split', 'analysis/sample-annotation']) {
    await page.goto(`${BASE}/#/${route}`);
    await page.waitForTimeout(1500);
    await selectContext(page);
    const geo = await rulerGeometry(page);
    if (!geo) {
      check(`${route} 有标尺`, false, '页面没有 .studio-ruler（可能未选数据）');
      continue;
    }
    const worst = geo.tracks.reduce((acc, t) => Math.max(
      acc, Math.abs(t.left - geo.ruler.left), Math.abs(t.width - geo.ruler.width),
    ), 0);
    check(`${route} 标尺与全部轨道对齐`, worst <= 1.5, `最大偏差 ${worst.toFixed(1)}px`);
  }

  // ── 2. 胶片条渲染 ──────────────────────────────────────────────────
  console.log('\n[2] 胶片条渲染');
  let framesRequests = 0;
  page.on('request', (req) => {
    if (req.url().includes('/video-frames')) framesRequests += 1;
  });
  await page.goto(`${BASE}/#/analysis/alignment`);
  await page.waitForTimeout(1500);
  await selectContext(page);
  const cellCount = await page.locator('.video-film-strip .film-cell').count();
  const imgCount = await page.locator('.video-film-strip .film-cell img').count();
  check('胶片条有帧格', cellCount >= 8, `${cellCount} 格，其中 ${imgCount} 格有图`);
  check('/video-frames 只请求一次', framesRequests === 1, `实际 ${framesRequests}`);

  // 页面上读起弧 / 总时长（都是 mm:ss.xx）
  const [arcText, , , durText] = await page.locator('.studio-events b').allTextContents();
  const arc = seconds(arcText);
  const duration = seconds(durText);
  check('读得到起弧与总时长', Number.isFinite(arc) && duration > 0, `arc=${arc} dur=${duration}`);

  // ── 3. 拖动：改 offset 且**零网络**；点一下条不 seek ─────────────────
  console.log('\n[3] 拖动与点击语义');
  const strip = page.locator('.video-film-strip');
  const track = page.locator('.lane-track-film');
  const stripBox = await strip.boundingBox();
  const trackBox = await track.boundingBox();
  const pxPerSec = trackBox.width / duration;

  let netDuringDrag = 0;
  page.on('request', (req) => {
    if (req.url().includes('/calibration') || req.url().includes('/video-frames')) netDuringDrag += 1;
  });
  const before = await page.inputValue('#offset-value');

  // 点一下条（不移动）→ 不该产生"有未保存的改动"，也不该 seek
  const playheadBefore = await page.evaluate(() => document.querySelector('.lane-playhead')?.style.left ?? null);
  await page.mouse.click(stripBox.x + stripBox.width / 2, stripBox.y + stripBox.height / 2);
  await page.waitForTimeout(400);
  const afterClick = await page.inputValue('#offset-value');
  const playheadAfter = await page.evaluate(() => document.querySelector('.lane-playhead')?.style.left ?? null);
  check('点条不改偏移', afterClick === before, `${before} → ${afterClick}`);
  check('点条不 seek（游标不动）', playheadBefore === playheadAfter, `${playheadBefore} → ${playheadAfter}`);

  // 拖动 +80px → offset 应增加 80/pxPerSec 秒，且全程不发请求
  await page.mouse.move(stripBox.x + stripBox.width / 2, stripBox.y + stripBox.height / 2);
  await page.mouse.down();
  for (let dx = 10; dx <= 80; dx += 10) {
    await page.mouse.move(stripBox.x + stripBox.width / 2 + dx, stripBox.y + stripBox.height / 2);
    await page.waitForTimeout(20);
  }
  await page.mouse.up();
  await page.waitForTimeout(400);
  const dragged = Number(await page.inputValue('#offset-value'));
  check('拖动改了偏移', Math.abs(dragged - Number(before)) > 0.3, `${before} → ${dragged}`);
  check('拖动零网络请求', netDuringDrag === 0, `实际 ${netDuringDrag}`);

  // ── 4. 起弧磁吸 ────────────────────────────────────────────────────
  console.log('\n[4] 起弧磁吸');
  // 先把偏移挪远，再拖到距目标 6px 处松手（≤14px 阈值 → 吸附）
  await page.fill('#offset-value', (arc + 1.2).toFixed(2));
  await page.waitForTimeout(300);
  const now = Number(await page.inputValue('#offset-value'));
  const targetDx = (arc - now) * pxPerSec - 6;
  const box2 = await strip.boundingBox();
  await page.mouse.move(box2.x + 20, box2.y + box2.height / 2);
  await page.mouse.down();
  await page.mouse.move(box2.x + 20 + targetDx, box2.y + box2.height / 2, { steps: 12 });
  await page.mouse.up();
  await page.waitForTimeout(400);
  const snapped = Number(await page.inputValue('#offset-value'));
  check('拖到起弧附近会吸附', Math.abs(snapped - arc) <= 0.01, `期望 ${arc}，实际 ${snapped}`);

  // 再拖到 30px 之外（> 释放阈值）→ 不该吸附
  const box3 = await strip.boundingBox();
  await page.mouse.move(box3.x + 20, box3.y + box3.height / 2);
  await page.mouse.down();
  await page.mouse.move(box3.x + 20 + 30, box3.y + box3.height / 2, { steps: 8 });
  await page.mouse.up();
  await page.waitForTimeout(400);
  const free = Number(await page.inputValue('#offset-value'));
  check('拖远了不吸附', Math.abs(free - arc) > 0.01, `实际 ${free}`);

  // ── 5. 保存 → 刷新后帧不再重取 ────────────────────────────────────
  console.log('\n[5] 保存与缓存');
  const beforeSave = framesRequests;
  await page.getByRole('button', { name: '保存偏移量' }).click();
  await page.waitForTimeout(2500);
  const savedBadge = await page.locator('.alignment-aside .track-availability').first().textContent();
  check('保存后标为已标定', savedBadge.includes('已标定'), savedBadge.trim());

  await page.goto(`${BASE}/#/analysis/alignment`);
  await page.waitForTimeout(1200);
  await selectContext(page);
  const persisted = Number(await page.inputValue('#offset-value'));
  check('刷新后偏移仍在（服务端权威）', Math.abs(persisted - free) <= 0.02, `期望 ${free}，实际 ${persisted}`);
  check('刷新后帧只再取一次（命中缓存）', framesRequests - beforeSave === 2, `新增 ${framesRequests - beforeSave}`);

  // 还原：把标定退回未标定，别把验证用的偏移留在记录上
  await page.getByRole('button', { name: '清除标定' }).click();
  await page.waitForTimeout(2000);
  const cleared = await page.locator('.alignment-aside .track-availability').first().textContent();
  check('清除标定还原未标定', cleared.includes('未标定'), cleared.trim());

  await browser.close();

  const failed = results.filter((r) => !r.ok);
  console.log(`\n${results.length - failed.length}/${results.length} 通过`);
  if (failed.length) {
    console.log('失败项：');
    for (const f of failed) console.log(`  - ${f.name} (${f.detail})`);
    process.exit(1);
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
