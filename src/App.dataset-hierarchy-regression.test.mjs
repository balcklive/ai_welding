import assert from 'node:assert/strict';
import fs from 'node:fs';

const app = fs.readFileSync(new URL('./App.tsx', import.meta.url), 'utf8');
const datasetsApi = fs.readFileSync(new URL('./api/datasets.ts', import.meta.url), 'utf8');

assert.match(datasetsApi, /listDatasetVersionItems/);
assert.match(datasetsApi, /\/datasets\/\$\{datasetId\}\/versions\/\$\{versionId\}\/items/);
assert.doesNotMatch(app, /\{ route: 'data-center\/list', label: '数据列表' \}/);
assert.match(app, /label: '数据集'/);
assert.doesNotMatch(app, /route: 'data-center\/list'/);
assert.match(app, /查看当前版本数据/);
assert.match(app, /数据集概览/);
assert.match(app, /listDatasetVersionItems/);
assert.match(app, /所属数据集/);
assert.doesNotMatch(app, /dataset-subtabs/);
