import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('./features/overview/OverviewPage.tsx', import.meta.url), 'utf8');
const overview = source.slice(source.indexOf('export function OverviewPage('), source.indexOf('function StatCard('));

test('overview no longer renders the bottom dataset card section', () => {
  // 2026-09-14：总览底部「数据集」卡片区整体删除（含其跳转与取数代码）。
  assert.doesNotMatch(overview, /<h2>数据集<\/h2>/);
  assert.doesNotMatch(overview, /dataset-grid/);
  assert.doesNotMatch(overview, /dataset-card/);
  assert.doesNotMatch(overview, /displayedDatasets/);
});

test('overview drops the dataset-card navigation handlers and props', () => {
  assert.doesNotMatch(overview, /navigate\('data-center\/datasets'\)/);
  assert.doesNotMatch(overview, /navigate\('analysis\/select'\)/);
  assert.doesNotMatch(overview, /export function OverviewPage\(\{/);
});

test('overview keeps the stats, attribute and distribution panels', () => {
  assert.match(overview, /className="stat-grid"/);
  assert.match(overview, /className="attr-grid"/);
  assert.match(overview, /DonutChart/);
});
