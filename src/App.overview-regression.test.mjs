import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('./App.tsx', import.meta.url), 'utf8');
const overview = source.slice(source.indexOf('function Overview('), source.indexOf('function StatCard('));

test('overview uses dataset terminology and links to all datasets', () => {
  assert.match(overview, /<h2>数据集<\/h2>/);
  assert.match(overview, /共 \{filteredProjects\.length\} 个数据集/);
  assert.match(overview, /navigate\('data-center\/datasets'\)/);
  assert.match(overview, /const displayedDatasets = filteredProjects\.slice\(0, 6\)/);
  assert.match(overview, /displayedDatasets\.map/);
  assert.doesNotMatch(overview, /<h2>数据项目<\/h2>/);
});
