import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const app = fs.readFileSync(new URL('./App.tsx', import.meta.url), 'utf8');
const dataContext = fs.readFileSync(new URL('./features/data-context/DataContext.tsx', import.meta.url), 'utf8');
const registrationPage = fs.readFileSync(new URL('./features/registration/RegistrationPage.tsx', import.meta.url), 'utf8');
const types = fs.readFileSync(new URL('./api/types.ts', import.meta.url), 'utf8');

const select = dataContext.slice(dataContext.indexOf('function AnalysisSelect('), dataContext.indexOf('function VersionPanel('));
const registration = registrationPage;
const routesData = app.slice(app.indexOf('const routesRequiringData'), app.indexOf('const isRouteDisabled'));

test('analysis select is dataset-first: dataset dropdown, then welds scoped by dataset_id', () => {
  assert.match(select, /function AnalysisSelect\(/);
  assert.match(select, /listDatasets\(\)/);
  assert.match(select, /selection-dataset-bar/);
  assert.match(select, /所属数据集/);
  assert.match(select, /listWelds\(\{ dataset_id: selectedDatasetId/);
});

test('analysis select lists all welds in the dataset and greys out unvalidated ones', () => {
  // 准入规则：仅核验「异常」置灰不可选，「待复核」可进（上传数据核验出警告即可继续分析）。
  assert.match(select, /disabled=\{row\.quality === '异常'\}/);
  assert.match(select, /selection-card \$\{row\.quality === '异常' \? 'disabled' : ''\}/);
  assert.doesNotMatch(select, /rows\.slice\(0, 3\)/);
  assert.match(select, /该数据集暂无数据，请先在数据管理登记数据。/);
});

test('analysis select no longer consumes the flat candidates endpoint', () => {
  assert.doesNotMatch(select, /listCandidates/);
});

test('registration page inherits and locks the owning dataset (T4.1)', () => {
  // 所属数据集继承自上下文并锁定；无上下文时先走"选择数据集"步骤再锁定（confirmDataset）。
  assert.match(registration, /lockedDatasetId/);
  assert.match(registration, /dataset_id: inheritedDatasetId \?\? 0/);
  assert.match(registration, /const confirmDataset/);
  // 必填校验由 missingFields 驱动：数据集看**锁定值**（不再看 form.dataset_id），来源看表单。
  assert.match(registration, /ok: lockedDatasetId != null/);
  assert.match(registration, /ok: !!form\.source\.trim\(\)/);
});

test('data-center/registration stays out of routesRequiringData (new-registration rule)', () => {
  assert.doesNotMatch(routesData, /data-center\/registration/);
});

test('GET /welds query type exposes dataset_id for server-side filtering', () => {
  assert.match(types, /interface WeldListQuery[\s\S]*dataset_id\?: number;/);
});
