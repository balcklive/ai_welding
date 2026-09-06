import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const analysis = fs.readFileSync(path.join(__dirname, 'api', 'analysis.ts'), 'utf8');
const workspace = fs.readFileSync(path.join(__dirname, 'features', 'annotation', 'AnnotationWorkspace.tsx'), 'utf8');
const embed = fs.readFileSync(path.join(__dirname, 'features', 'annotation', 'LabelStudioEmbed.tsx'), 'utf8');

// 一期·轨道 A：前端必须能拿到 LS 同步状态并嵌入 LS 工作台。
test('annotation layer exposes getLabelStudioTask (used by the LS embed)', () => {
  assert.match(analysis, /export async function getLabelStudioTask/);
  assert.match(analysis, /\/labelstudio\/tasks\/\$\{taskId\}/);
});

test('annotation workspace routes an LS-active task to the embedded workbench', () => {
  assert.match(workspace, /useLabelStudioTask/);
  assert.match(workspace, /LabelStudioEmbed/);
  assert.match(workspace, /ls_status === 'pending_ls'/);
});

test('LabelStudioEmbed builds the LS project iframe URL from public url + project ids', () => {
  assert.match(embed, /ls_public_url/);
  assert.match(embed, /ls_project_ids/);
  assert.match(embed, /<iframe/);
});
