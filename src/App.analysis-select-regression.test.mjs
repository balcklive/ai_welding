import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const app = fs.readFileSync(new URL('./App.tsx', import.meta.url), 'utf8');
const types = fs.readFileSync(new URL('./api/types.ts', import.meta.url), 'utf8');

const select = app.slice(app.indexOf('function AnalysisSelect('), app.indexOf('function VersionPanel('));
const registration = app.slice(app.indexOf('function Registration('), app.indexOf('const CH = 720'));
const routesData = app.slice(app.indexOf('const routesRequiringData'), app.indexOf('const isRouteDisabled'));

test('analysis select is dataset-first: dataset dropdown, then welds scoped by dataset_id', () => {
  assert.match(select, /function AnalysisSelect\(/);
  assert.match(select, /listDatasets\(\)/);
  assert.match(select, /selection-dataset-bar/);
  assert.match(select, /所属数据集/);
  assert.match(select, /listWelds\(\{ dataset_id: selectedDatasetId/);
});

test('analysis select lists all welds in the dataset and greys out unvalidated ones', () => {
  assert.match(select, /disabled=\{row\.quality !== '通过'\}/);
  assert.match(select, /selection-card \$\{row\.quality !== '通过' \? 'disabled' : ''\}/);
  assert.doesNotMatch(select, /rows\.slice\(0, 3\)/);
  assert.match(select, /该数据集暂无登记数据/);
});

test('analysis select no longer consumes the flat candidates endpoint', () => {
  assert.doesNotMatch(select, /listCandidates/);
});

test('registration form picks the owning dataset and defaults the field', () => {
  assert.match(registration, /所属数据集/);
  assert.match(registration, /dataset_id: 0/);
  assert.match(registration, /!form\.dataset_id \|\| !form\.source\.trim\(\)/);
});

test('data-center/registration stays out of routesRequiringData (new-registration rule)', () => {
  assert.doesNotMatch(routesData, /data-center\/registration/);
});

test('GET /welds query type exposes dataset_id for server-side filtering', () => {
  assert.match(types, /interface WeldListQuery[\s\S]*dataset_id\?: number;/);
});
