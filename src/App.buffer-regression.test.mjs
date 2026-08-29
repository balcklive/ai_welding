import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const source = fs.readFileSync(path.join(__dirname, 'App.tsx'), 'utf8');
const datasetSource = fs.readFileSync(path.join(__dirname, 'features/datasets/DatasetWorkspace.tsx'), 'utf8');
const dataContextSource = fs.readFileSync(path.join(__dirname, 'features/data-context/DataContext.tsx'), 'utf8');

test('Alignment split panel exposes editable buffer seconds and wires them to split API', () => {
  assert.match(source, /bufferSeconds/);
  assert.match(source, /setBufferSeconds/);
  assert.match(source, /type="number"/);
  assert.match(source, /createSplitTask\([^\n]+keep_event_buffer:/s);
  assert.doesNotMatch(source, /createSplitTask\([^\n]+keep_event_buffer:\s*0\.2/s);
});

test('version view buttons open the appropriate detail drawer', () => {
  assert.match(datasetSource, /function VersionDetailDrawer/);
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
