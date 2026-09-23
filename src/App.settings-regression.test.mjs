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
  // S2（2026-09-15）：焊机型号/焊接方法也从「严格下拉」改为「下拉候选 + 可自定义输入」——
  // 默认项不足时必须能直接填新值，新值要给出提示并引导补进字典。
  assert.match(registration, /const MACHINE_LIST_ID = 'registration-machine-options'/);
  assert.match(registration, /const WELD_METHOD_LIST_ID = 'registration-weld-method-options'/);
  assert.match(registration, /<datalist id=\{MACHINE_LIST_ID\}>/);
  assert.match(registration, /<datalist id=\{WELD_METHOD_LIST_ID\}>/);
  assert.doesNotMatch(registration, /<select value=\{form\.machine/);
  assert.doesNotMatch(registration, /<select value=\{form\.weld_method/);
  assert.match(registration, /isCustomValue\(optionValues\.machine, form\.machine\)/);
  assert.match(registration, /isCustomValue\(optionValues\.weld_method, form\.weld_method\)/);
  assert.match(registration, /custom-value-hint/);
  // 板材材质/厚度（2026-09-24）：此前是纯文本框，同样接字典候选。
  assert.match(registration, /pick\('material'\)/);
  assert.match(registration, /pick\('thickness'\)/);
  assert.match(registration, /<datalist id=\{MATERIAL_LIST_ID\}>/);
  assert.match(registration, /<datalist id=\{THICKNESS_LIST_ID\}>/);
  // 「下拉不明显」修复：`<input list>` 浏览器不画箭头、只在输入时提示，静置时和文本框一样。
  // 六个候选输入一律带 .combo-input（CSS 补 chevron）并挂 showPicker（点击展开）——
  // 漏一个就退回"看不出能选"，所以按数量钉死，且不许再出现裸的 `<input list=`。
  assert.equal((registration.match(/<input className="combo-input"/g) ?? []).length, 6);
  assert.equal((registration.match(/onClick=\{openCandidateList\}/g) ?? []).length, 6);
  assert.match(registration, /showPicker\?\.\(\)/);
  assert.doesNotMatch(registration, /<input list=\{/);
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
