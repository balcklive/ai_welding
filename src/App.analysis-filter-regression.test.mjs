import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const source = fs.readFileSync(path.join(__dirname, 'features/analysis/AnalysisWorkspace.tsx'), 'utf8');

test('cutoff is shown in Hz derived from the real sample rate, never ratio × 1000', () => {
  // 回归：归一化频率（相对奈奎斯特 fs/2）曾被 ×1000 当 Hz 显示（0.30 → “300 Hz”）
  assert.doesNotMatch(source, /cutoff\s*\*\s*1000|cutoff2\s*\*\s*1000/);
  assert.match(source, /hzFromRatio\(cutoff, sampleRate\)/);
  assert.match(source, /setSampleRate\(data\.sample_rate/);
  // 采样率未知时不给假数值
  assert.match(source, /采样率未知/);
});

test('each filter type spells out its passband threshold', () => {
  assert.match(source, /passbandText/);
  assert.match(source, /低通：保留 0 – /);
  assert.match(source, /高通：保留 /);
  assert.match(source, /带通：只保留 /);
  assert.match(source, /奈奎斯特/);
});

test('band-pass keeps cutoff < cutoff2 in the UI so the API never sees reversed bounds', () => {
  assert.match(source, /const selectFilterType = /);
  assert.match(source, /ft === '带通' && cutoff >= cutoff2/);
  assert.match(source, /hz >= cutoff2Hz/);
  assert.match(source, /hz, floor|Math\.max\(hz, floor\)/);
});

test('filtering is scoped to the target channel and before/after are both drawn', () => {
  // 只对目标通道请求滤波结果；主波形保持原始信号
  assert.match(source, /channels: \[filterChan\], filter_type: filterType/);
  assert.doesNotMatch(source, /opts\.filter_type = filterType/);
  assert.match(source, /<FilterCompare raw=\{filterChanObj\} filtered=\{filterCompare\}/);
  assert.match(source, /滤波前后对比/);
});
