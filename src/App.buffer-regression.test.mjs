import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const source = fs.readFileSync(path.join(__dirname, 'App.tsx'), 'utf8');
const datasetSource = fs.readFileSync(path.join(__dirname, 'features/datasets/DatasetWorkspace.tsx'), 'utf8');
const dataContextSource = fs.readFileSync(path.join(__dirname, 'features/data-context/DataContext.tsx'), 'utf8');
const versionDrawerSource = fs.readFileSync(path.join(__dirname, 'features/versions/VersionDetailDrawer.tsx'), 'utf8');
// v3 起分段页是独立工作台（设计 §7.1），不再是 AlignmentWorkspace 的 splitOnly 形态
const splitPanelSource = fs.readFileSync(path.join(__dirname, 'features/alignment/split/SplitRulesPanel.tsx'), 'utf8');
const splitWorkspaceSource = fs.readFileSync(path.join(__dirname, 'features/alignment/split/SplitWorkspace.tsx'), 'utf8');
const splitTypesSource = fs.readFileSync(path.join(__dirname, 'features/alignment/split/splitTypes.ts'), 'utf8');
const analysisApiSource = fs.readFileSync(path.join(__dirname, 'api/analysis.ts'), 'utf8');

test('分段页暴露可编辑的缓冲秒数，并按准确数值进规则', () => {
  assert.match(splitPanelSource, /bufferSeconds/);
  assert.match(splitPanelSource, /type="number"/);
  // 关闭缓冲必须传 0、开启时传准确数值——不能像改造前那样硬编码常量
  assert.match(splitTypesSource, /keep_event_buffer: draft\.keepEventBuffer \? draft\.bufferSeconds : 0/);
});

test('创建任务只提交 preview_token，规则由服务端从令牌重建（v3 §5.4）', () => {
  assert.match(analysisApiSource, /body: \{ preview_token: previewToken \}/);
  // 前端不得再把规则对象直接交给创建接口——那会让"所见即所得"失效
  assert.doesNotMatch(splitWorkspaceSource, /createSplitTask\([^)]*keep_event_buffer/);
  assert.doesNotMatch(splitWorkspaceSource, /createSplitTask\([^)]*window_seconds/);
});

test('version view buttons open the appropriate detail drawer', () => {
  assert.match(versionDrawerSource, /function VersionDetailDrawer/);
  assert.match(dataContextSource, /<VersionDetailDrawer mode="weld"/);
  assert.match(dataContextSource, /onClick=\{\(\) => setSelectedVersionId\(String\(version\.id\)\)\}/);
  assert.match(datasetSource, /<VersionDetailDrawer mode="dataset"/);
  assert.match(datasetSource, /onClick=\{\(\) => setSelectedVersion\(v\)\}/);
});

test('data version panel exposes create and validation actions backed by APIs', () => {
  const panel = dataContextSource.slice(dataContextSource.indexOf('function VersionPanel('), dataContextSource.indexOf('function VersionCreateDialog('));
  assert.match(panel, /createVersion\(dataId/);
  assert.match(panel, /presignUpload\([\s\S]*prefix: `processed\/\$\{dataId\}`/);
  assert.match(panel, /runValidation\(dataId, String\(versionId\)\)/);
  assert.match(panel, /新建数据版本/);
  assert.match(panel, /执行核验/);
});
