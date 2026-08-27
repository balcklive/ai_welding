import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const app = fs.readFileSync(new URL('./App.tsx', import.meta.url), 'utf8');
const datasetsApi = fs.readFileSync(new URL('./api/datasets.ts', import.meta.url), 'utf8');

const workspace = app.slice(app.indexOf('function DatasetWorkspace('), app.indexOf('function DatasetDetail('));
const detail = app.slice(app.indexOf('function DatasetDetail('), app.indexOf('function DatasetInputPanel('));
const records = app.slice(app.indexOf('function DatasetRecords('), app.indexOf('function DatasetRecordDetail('));
const recordDetail = app.slice(app.indexOf('function DatasetRecordDetail('), app.indexOf('function DatasetInputPanel('));

test('dataset browser keeps list, overview, records, and record detail as separate views', () => {
  assert.match(app, /type DatasetView = 'list' \| 'overview' \| 'records' \| 'record-detail'/);
  assert.match(workspace, /useState<DatasetView>\('list'\)/);
  assert.match(workspace, /view === 'list'/);
  assert.match(workspace, /view === 'overview'/);
  assert.match(workspace, /view === 'list'[\s\S]*dataset-table[\s\S]*<\/>\}\{view === 'overview' && dataset && <DatasetDetail/);
});

test('real dataset selection replaces the version id and no-current-version has no fallback', () => {
  assert.match(workspace, /setSelectedVersionId\(selected\?\.currentVersionId \?\? null\)/);
  assert.doesNotMatch(workspace, /setSelectedVersionId\(\(prev\) => prev \?\?/);
  assert.doesNotMatch(detail, /versions\[0\]\?\.id/);
  assert.match(detail, /const visibleVersions = currentVersionId == null \? \[\] : versions/);
  assert.match(detail, /当前数据集尚未创建版本/);
  assert.match(detail, /创建数据集版本/);
});

test('records use the selected version split totals instead of the current page', () => {
  assert.match(records, /getDatasetVersion\(dataset\.id, String\(versionId\)\)/);
  assert.match(records, /const splitTotals = versionSummary\?\.split/);
  assert.doesNotMatch(records, /const splitCounts = rows\.reduce/);
});

test('record detail loads its actual weld and never substitutes a sample id', () => {
  assert.doesNotMatch(workspace, /row\.weld_id \?\? String\(row\.sample_id\)/);
  assert.match(workspace, /if \(!row\.weld_id\) return/);
  assert.match(recordDetail, /getWeld\(weldId\)/);
  assert.match(recordDetail, /登记编号/);
  assert.match(recordDetail, /当前版本/);
  assert.match(recordDetail, /核验状态/);
  assert.match(recordDetail, /所属数据集/);
  assert.match(recordDetail, /所属版本/);
  assert.match(recordDetail, /数据划分/);
});

test('dataset member endpoint remains the scoped source without horizontal tabs', () => {
  assert.match(datasetsApi, /listDatasetVersionItems/);
  assert.match(datasetsApi, /\/datasets\/\$\{datasetId\}\/versions\/\$\{versionId\}\/items/);
  assert.doesNotMatch(app, /route: 'data-center\/list'/);
  assert.match(app, /label: '数据集'/);
  assert.match(app, /查看当前版本数据/);
  assert.match(app, /listDatasetVersionItems/);
  assert.doesNotMatch(app, /dataset-subtabs/);
});
