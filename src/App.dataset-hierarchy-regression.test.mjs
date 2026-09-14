import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const app = fs.readFileSync(new URL('./App.tsx', import.meta.url), 'utf8');
const datasetFeature = fs.readFileSync(new URL('./features/datasets/DatasetWorkspace.tsx', import.meta.url), 'utf8');
const navigation = fs.readFileSync(new URL('./app/navigation.ts', import.meta.url), 'utf8');
const datasetsApi = fs.readFileSync(new URL('./api/datasets.ts', import.meta.url), 'utf8');

const workspace = datasetFeature.slice(datasetFeature.indexOf('export function DatasetWorkspace('), datasetFeature.indexOf('function DatasetDetail('));
const detail = datasetFeature.slice(datasetFeature.indexOf('function DatasetDetail('), datasetFeature.indexOf('function DatasetRecords('));
const records = datasetFeature.slice(datasetFeature.indexOf('function DatasetRecords('), datasetFeature.indexOf('function DatasetSourceRecords('));
const recordDetail = datasetFeature.slice(datasetFeature.indexOf('function DatasetRecordDetail('), datasetFeature.indexOf('function DatasetInputPanel('));

test('dataset browser keeps list, overview, records, and record detail as separate views', () => {
  assert.match(datasetFeature, /type DatasetView = 'list' \| 'overview' \| 'dataset-records' \| 'records' \| 'record-detail'/);
  assert.match(workspace, /useState<DatasetView>\('list'\)/);
  assert.match(workspace, /view === 'list'/);
  assert.match(workspace, /view === 'overview'/);
  assert.match(workspace, /view === 'list'[\s\S]*dataset-table[\s\S]*<\/>\}\{view === 'overview' && dataset && <DatasetDetail/);
});

test('real dataset selection replaces the version id and no-current-version has no fallback', () => {
  assert.match(workspace, /setSelectedVersionId\(selected\?\.currentVersionId \?\? null\)/);
  assert.doesNotMatch(workspace, /setSelectedVersionId\(\(prev\) => prev \?\?/);
  assert.match(detail, /const \[versions, setVersions\] = useState<DatasetVersion\[]>\(\[\]\)/);
  assert.doesNotMatch(detail, /useState<DatasetVersion\[]>\(mockDatasetVersions\)/);
  assert.doesNotMatch(detail, /versions\[0\]\?\.id/);
  // 当前版本标记必须由 currentVersionId 驱动（不得回落到 versions[0]）。
  assert.match(detail, /v\.id === currentVersionId \? <StatusPill>当前<\/StatusPill>/);
  assert.match(detail, /const visibleVersions = versions/);
  // T1：界面文案走术语表（"数据集版本"），不再出现"固定快照"。
  assert.match(detail, /当前数据集还没有\{TERMS\.datasetVersion\}/);
});

test('records use the selected version split totals instead of the current page', () => {
  assert.match(records, /getDatasetVersion\(dataset\.id, String\(versionId\)\)/);
  assert.match(records, /setVersionSummaryUnavailable\(true\)/);
  assert.match(records, /数据集版本信息暂不可用/);
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
  assert.doesNotMatch(navigation, /route: 'data-center\/list'/);
  assert.match(navigation, /label: '数据集'/);
  assert.match(datasetFeature, /查看当前\{TERMS\.datasetVersion\}/);
  assert.match(datasetFeature, /listDatasetVersionItems/);
  assert.doesNotMatch(datasetFeature, /dataset-subtabs/);
});
