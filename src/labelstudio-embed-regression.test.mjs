import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const analysis = readFileSync(new URL('./api/analysis.ts', import.meta.url), 'utf8');
const workspace = readFileSync(new URL('./features/annotation/AnnotationWorkspace.tsx', import.meta.url), 'utf8');
const hook = readFileSync(new URL('./hooks/useLabelStudioTask.ts', import.meta.url), 'utf8');

// 一期·轨道 A 现状（2026-09-09 起）：主应用**不**内嵌 LS 工作台（LabelStudioEmbed.tsx 已删除），
// 只通过 ls_status 感知任务是否被推到 LS，借 ls_active 放宽「加载样本」闸门。
// 本文件原先断言已删除的 iframe 组件，会必然报错，故按当前契约重写。
test('annotation layer exposes getLabelStudioTask', () => {
  assert.match(analysis, /export async function getLabelStudioTask/);
  assert.match(analysis, /\/labelstudio\/tasks\/\$\{taskId\}/);
});

test('annotation workspace only consumes ls_status to gate the sample loader', () => {
  assert.match(workspace, /useLabelStudioTask/);
  assert.match(workspace, /ls_status === 'pending_ls'/);
  assert.match(workspace, /annotating/);
  // 不允许再出现 iframe 容器式嵌入
  assert.doesNotMatch(workspace, /LabelStudioEmbed/);
  assert.doesNotMatch(workspace, /<iframe/);
});

test('useLabelStudioTask polls while LS-active and stops on terminal states', () => {
  assert.match(hook, /ls_status === 'synced'\) return;/);
  assert.match(hook, /ls_status === 'legacy' && jobDone\) return;/);
});
