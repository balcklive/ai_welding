/**
 * 分段样本标注（段级分类，2026-09-22）回归。
 *
 * 钉住几条**改错就会静默出问题**的约定：
 * 1. 路由三处同步（`navigation.ts` / `route-url.ts` / `App.tsx`）——漏一处即死路由或类型错；
 * 2. 三个模态共用**同一个 Sample 的时间窗**，前端不得自造时间轴；
 * 3. 视频 seek 必须做 `t_video = t_signal − offset` 换算（与分段页同一口径）；
 * 4. `normal` 必须发 `defect_category_id: null`，`defect` 必须选类别才能提交；
 * 5. 词表走系统设置（`defect_category` 分组），工作台只读、不本地维护词表；
 * 6. 读操作失败置错误态，不回 mock 兜底。
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const read = (relative) => fs.readFileSync(path.join(__dirname, relative), 'utf8');

const appSource = read('App.tsx');
const navigationSource = read('app/navigation.ts');
const routeUrlSource = read('app/route-url.ts');
const workspaceSource = read('features/annotation/segment/SampleAnnotationWorkspace.tsx');
const apiSource = read('api/sampleAnnotations.ts');
const splitPanelSource = read('features/alignment/split/SplitRulesPanel.tsx');

test('新路由在导航 / hash 映射 / WorkspaceFrame 三处都登记（漏一处即死路由）', () => {
  assert.match(navigationSource, /'analysis\/sample-annotation'/);
  assert.match(navigationSource, /\{ route: 'analysis\/sample-annotation', label: '分段样本标注' \}/);
  assert.match(routeUrlSource, /'analysis\/sample-annotation': 'analysis\/sample-annotation'/);
  assert.match(appSource, /import\('\.\/features\/annotation\/segment\/SampleAnnotationWorkspace'\)/);
  assert.match(
    appSource,
    /route === 'analysis\/sample-annotation'\)[\s\S]{0,80}?<SampleAnnotationWorkspace dataId=\{selectedDataId\} \/> : <SelectionRequired/,
  );
});

test('三个模态共用同一个 Sample 时间窗，不在前端另造时间轴', () => {
  // 窗口起止只来自该样本（服务端切分时定下），不是各模态各自的时刻
  assert.match(workspaceSource, /detail\?\.start_time/);
  assert.match(workspaceSource, /detail\.modalities\?\.signal/);
  assert.match(workspaceSource, /detail\.modalities\?\.video/);
  assert.match(workspaceSource, /detail\.modalities\?\.seam_image/);
  // 详情与结论都由当前的 currentId 取——不存在"各轨独立选中"
  assert.match(workspaceSource, /getSplitSample\(taskId, currentId\)/);
});

test('视频 seek 做 t_video = t_signal − offset 换算（与分段页同口径）', () => {
  assert.match(workspaceSource, /video\.currentTime = Math\.max\(0, detail\.start_time - offset\)/);
  assert.match(workspaceSource, /offset_seconds/);
});

test('段级结论：normal 清空类别，defect 必须选类别才能提交', () => {
  assert.match(
    workspaceSource,
    /defect_category_id: draft\.label === 'defect' \? draft\.categoryId : null/,
  );
  assert.match(workspaceSource, /const draftInvalid = draft\.label === 'defect' && draft\.categoryId == null/);
  assert.match(workspaceSource, /disabled=\{busy \|\| draftInvalid\}/);
  // 切成「正常」时立刻丢掉已选类别，避免残影提交
  assert.match(workspaceSource, /label: 'normal', categoryId: null/);
});

test('词表由系统设置维护，工作台只读（不本地增删）', () => {
  // 词表读的是标注侧只读端点；增删改只在设置页（settings/options/defect_category）
  assert.match(apiSource, /'\/segment-annotation\/categories'/);
  assert.doesNotMatch(apiSource, /settings\/options/);
  assert.match(workspaceSource, /listSegmentCategories\(true\)/); // 含停用项，历史标注才显示得出
  assert.match(workspaceSource, /「系统设置 → 分段样本缺陷词表」/);
});

test('列表分页拉取、翻页时把选中项带到新页（不缓存全量切片）', () => {
  assert.match(workspaceSource, /page_size: PAGE_SIZE/);
  assert.match(workspaceSource, /pendingSelectRef/);
  assert.doesNotMatch(workspaceSource, /page_size: 1000/);
});

test('读操作失败置错误态，不回落 mock（全站禁令）', () => {
  assert.match(workspaceSource, /setListError\(errorText\(err, '样本列表读取失败'\)\)/);
  assert.match(workspaceSource, /setTasksError\(errorText\(err, '分段任务列表读取失败'\)\)/);
  assert.doesNotMatch(workspaceSource, /mock/i);
});

test('分段成功后给出进入标注工作台的入口', () => {
  assert.match(splitPanelSource, /onGoToAnnotation/);
  assert.match(splitPanelSource, /去标注这批样本（分段样本标注）/);
});
