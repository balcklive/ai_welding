import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('./App.tsx', import.meta.url), 'utf8');
const toolbar = readFileSync(new URL('./shared/components/Toolbar.tsx', import.meta.url), 'utf8');
const workspace = source.slice(source.indexOf('function WorkspaceFrame('), source.indexOf('function SelectionSwitcher('));

 test('upload action is available only after entering dataset detail', () => {
  assert.match(workspace, /const \[isDatasetDetail, setIsDatasetDetail\]/);
  assert.match(workspace, /onDetailChange=\{setIsDatasetDetail\}/);
  assert.match(workspace, /route === 'data-center\/datasets' && isDatasetDetail/);
  assert.match(workspace, /DatasetWorkspace navigate=\{navigate\} onDetailChange=\{setIsDatasetDetail\}/);
  assert.match(toolbar, /action\?: string/);
  assert.match(toolbar, /action &&/);
});

test('report export reserves a popup synchronously and exposes failures', () => {
  assert.match(toolbar, /window\.open\('', '_blank'\)/);
  assert.match(toolbar, /setExportError/);
  assert.match(toolbar, /exporting/);
  assert.match(toolbar, /popup\.location\.href = url/);
});
