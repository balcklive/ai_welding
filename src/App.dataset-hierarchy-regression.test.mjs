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

test('dataset list numbers every row continuously across pages (S1)', () => {
  // S1（2026-09-15）：列表每行前置序号，且是**跨页连续**的全局序号（与「共 N 条」同口径），
  // 不是每页从 1 重来——否则第 2 页的"第 3 行"和搜索前的"第 3 行"指向不同数据集。
  assert.match(workspace, /rows\.map\(\(item, index\) =>/);
  assert.match(workspace, /dataset-row-index">\{\(listPage - 1\) \* LIST_PAGE_SIZE \+ index \+ 1\}/);
  // 序号列排在最前（图标之前）。
  assert.match(workspace, /dataset-row-index[\s\S]{0,120}dataset-row-icon/);
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
  // T2.2：成员详情的"核验状态"行与右侧徽标已删除——核验状态只在「数据核验」页展示。
  assert.doesNotMatch(recordDetail, /核验状态/);
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
