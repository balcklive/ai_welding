import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

/**
 * 系统设置·可选项字典回归（2026-09）：录入类可选项不得再硬编码在页面里。
 *
 * 断言三件事：① 侧边栏「系统设置」真的能进页面（路由全链路接通）；
 * ② 登记页/数据集页的选项读字典（不再写死品牌与「目标检测」）；
 * ③ 设置页按后端返回的删除 mode 提示，不自行判断能否删。
 */
const app = readFileSync(new URL('./App.tsx', import.meta.url), 'utf8');
const navigation = readFileSync(new URL('./app/navigation.ts', import.meta.url), 'utf8');
const registration = readFileSync(new URL('./features/registration/RegistrationPage.tsx', import.meta.url), 'utf8');
const datasets = readFileSync(new URL('./features/datasets/DatasetWorkspace.tsx', import.meta.url), 'utf8');
const settings = readFileSync(new URL('./features/settings/SettingsPage.tsx', import.meta.url), 'utf8');

test('sidebar 系统设置 entry routes to the settings page', () => {
  assert.match(navigation, /\| 'settings'/);
  assert.match(navigation, /settings: \{ eyebrow/);
  assert.match(app, /features\/settings\/SettingsPage/);
  assert.match(app, /route === 'settings' \? 'active' : ''/);
  assert.match(app, /navigate\('settings'\)/);
  assert.match(app, /route === 'settings'\) content = <SettingsPage \/>/);
});

test('registration page reads options from the dictionary (no hardcoded fallback)', () => {
  assert.match(registration, /listOptionGroups\(\)/);
  assert.match(registration, /pick\('machine'\)/);
  assert.match(registration, /pick\('weld_method'\)/);
  // T3.2/T3.3：字典失败不再回落硬编码值——必须置错误态，并在字典不全时禁止提交。
  assert.doesNotMatch(registration, /const FALLBACK_OPTIONS/);
  assert.match(registration, /setOptionsError\(err\)/);
  assert.match(registration, /datasetsError \|\| optionsError/);
  // 原硬编码下拉项必须消失，改由字典渲染（withCurrent 保留停用/历史值）。
  assert.doesNotMatch(registration, /<option>Fronius CMT<\/option>/);
  assert.doesNotMatch(registration, /<option>MAG焊<\/option>/);
  assert.match(registration, /withCurrent\(optionValues\.machine, form\.machine\)/);
  // 数据来源/产品信息保留自由填写：候选走 datalist。
  assert.match(registration, /<datalist id=\{SOURCE_LIST_ID\}>/);
  assert.match(registration, /<datalist id=\{PRODUCT_LIST_ID\}>/);
});

test('dataset creation takes task type from the dictionary', () => {
  assert.match(datasets, /listOptionGroups\(\)/);
  assert.match(datasets, /group\.key === 'dataset_task'/);
  // T3.2/T3.3：字典失败不再回落硬编码任务类型，改为错误态 + 禁止新建（S7 的 hover 提示也改成页面内提示）。
  assert.doesNotMatch(datasets, /const FALLBACK_DATASET_TASKS/);
  assert.match(datasets, /setTaskOptionsError\(err\)/);
  assert.match(datasets, /Boolean\(taskOptionsError\)/);
  assert.doesNotMatch(datasets, /createDataset\(\{ name, task: '目标检测' \}\)/);
  assert.match(datasets, /createDataset\(\{ name, task: task \?\? taskOptions\[0\] \?\? '' \}\)/);
  assert.match(datasets, /choice=\{taskOptions\.length \?/);
});

test('settings page follows server delete semantics instead of guessing', () => {
  assert.match(settings, /deleteOptionItem/);
  assert.match(settings, /result\.mode === 'deactivated'/);
  assert.match(settings, /result\.references/);
  assert.doesNotMatch(settings, /window\.confirm/);
  // 写操作后重新拉全量分组，避免局部合并导致排序/停用态漂移。
  assert.match(settings, /await load\(\)/);
});
