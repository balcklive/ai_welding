/**
 * 分段样本标注（段级分类，2026-09-22；**2026-09-23 改为总览打标流**）回归。
 *
 * 钉住几条**改错就会静默出问题**的约定：
 * 1. 路由三处同步（`navigation.ts` / `route-url.ts` / `App.tsx`）——漏一处即死路由或类型错；
 * 2. 三个模态共用**同一个 Sample 的时间窗**，前端不得自造时间轴；
 * 3. 视频 seek 必须做 `t_video = t_signal − offset` 换算（与分段页同一口径）；
 * 4. `normal` 必须发 `defect_category_id: null`，`defect` 必须选类别才能提交；
 * 5. 词表走系统设置（`defect_category` 分组），工作台只读、不本地维护词表；
 * 6. **全量的是索引，不是媒体**：窗口与标注态由 `annotation-timeline` 一次拿全，
 *    但只有当前批次的切片会挂 `<img>`（`loading="lazy"`）；
 * 7. 读操作失败置错误态，不回 mock 兜底。
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
const railSource = read('features/annotation/segment/AnnotationRail.tsx');
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

test('窗口与三模态全部来自服务端的同一条时间轴，前端不自造也不重算', () => {
  // 窗口集合与标注态由聚合端点一次给出——不在前端按规则算窗口（算一份就会漂移）
  assert.match(apiSource, /\/split-tasks\/\$\{taskId\}\/annotation-timeline/);
  assert.match(workspaceSource, /getAnnotationTimeline\(target\)/);
  assert.match(workspaceSource, /timeline\?\.windows/);
  // 批次边界取自服务端给的窗口起止，不是本地算出来的时刻
  assert.match(workspaceSource, /const boundaries = batch\.map/);
  assert.doesNotMatch(workspaceSource, /build_time_windows/);
  // 三模态的可用性各自读该窗口的模态槽（缺失只标记，不阻断），不另开时间轴
  assert.match(railSource, /row\.signal\.available/);
  assert.match(railSource, /row\.video\.available/);
  assert.match(railSource, /row\.seam_image\.available/);
  // 一条时间轴上的窗口列是**同一个**选中项驱动的：不存在"各轨独立选中"
  assert.match(workspaceSource, /const \[selectedId, setSelectedId\]/);
  assert.match(workspaceSource, /onClick=\{\(\) => setSelectedId\(row\.sample_id\)\}/);
});

test('视频 seek 做 t_video = t_signal − offset 换算（与分段页同口径）', () => {
  assert.match(workspaceSource, /video\.currentTime = Math\.max\(0, current\.start - offset\)/);
  assert.match(workspaceSource, /offset_seconds/);
  // 换窗口要重挂载播放器，否则同一个 <video> 不会重新定位到新窗起点
  assert.match(railSource, /key=\{row\.sample_id\}/);
});

test('段级结论：normal 清空类别，defect 必须选类别才能提交', () => {
  assert.match(
    workspaceSource,
    /defect_category_id: verdict\.label === 'defect' \? verdict\.categoryId : null/,
  );
  assert.match(railSource, /const draftInvalid = draft\.label === 'defect' && draft\.categoryId == null/);
  assert.match(railSource, /disabled=\{busy \|\| draftInvalid\}/);
  // 切成「正常」时立刻丢掉已选类别，避免残影提交
  assert.match(railSource, /label: 'normal', categoryId: null/);
});

test('入口默认只进最近一次成功的分段任务，历史任务折叠', () => {
  // 服务端按 SplitTask.id desc 返回，首个即最近一次成功——**不在前端自己排序**
  assert.match(workspaceSource, /const latest = tasks\[0\] \?\? null/);
  assert.match(workspaceSource, /const history = tasks\.slice\(1\)/);
  // 历史任务默认收起：卡片只在展开后才渲染（否则"折叠"只是视觉上的）
  assert.match(workspaceSource, /aria-expanded=\{showHistory\}/);
  assert.match(workspaceSource, /\{showHistory && \(/);
  assert.match(workspaceSource, /历史分段任务（\{history\.length\}）/);
});

test('词表由系统设置维护，工作台只读（不本地增删）', () => {
  // 词表读的是标注侧只读端点；增删改只在设置页（settings/options/defect_category）
  assert.match(apiSource, /'\/segment-annotation\/categories'/);
  assert.doesNotMatch(apiSource, /settings\/options/);
  assert.match(workspaceSource, /listSegmentCategories\(true\)/); // 含停用项，历史标注才显示得出
  assert.match(railSource, /「系统设置 → 分段样本缺陷词表」/);
});

test('全量的是索引不是媒体：窗口一次拿全，切片只挂当前批次', () => {
  // 批次切片的唯一入口是 BATCH_SIZE，且只取当前那一段
  assert.match(workspaceSource, /const BATCH_SIZE = 20/);
  assert.match(workspaceSource, /windows\.slice\(batchIndex \* BATCH_SIZE/);
  // 切片图一律懒加载——批次之外的窗口不渲染任何 <img>
  assert.match(workspaceSource, /loading="lazy"/);
  // 旧的分页口径（每页 page_size、翻页把选中项带到新页）已随列表一起删除
  assert.doesNotMatch(workspaceSource, /PAGE_SIZE|pendingSelectRef/);
  assert.doesNotMatch(workspaceSource, /page_size/);
  // 全局条铺的是**全部**窗口（一窗一格），批次只是它的一个窗口
  assert.match(workspaceSource, /annot-strip/);
  assert.match(workspaceSource, /windows\.map\(\(row\) => \(/);
});

test('标注行不依赖任何模态是否可用', () => {
  // 结论落在窗口列上，所以这条轨永远渲染；图/视频取不到只让对应胶片轨走空态
  assert.match(workspaceSource, /annot-mark-lane/);
  assert.match(workspaceSource, /annot-mark-row/);
  // 波形读不回来时时间轴为 null，此时仍要给出窗口与标注态（服务端 warnings 如实带回）
  assert.match(workspaceSource, /timeline\?\.warnings\.map/);
});

test('快捷键：←/→ 换窗口，N 标正常 —— 只在文本输入控件里放行', () => {
  assert.match(workspaceSource, /event\.key === 'ArrowLeft'/);
  assert.match(workspaceSource, /event\.key === 'ArrowRight'/);
  // **按钮不在放行名单里**：点窗口列后焦点就在那个按钮上，"点一格再按 N"必须还能用
  assert.match(workspaceSource, /closest\('input, textarea, select, \[contenteditable="true"\]'\)/);
  assert.doesNotMatch(workspaceSource, /closest\('input, textarea, select, button/);
});

test('读操作失败置错误态，不回落 mock（全站禁令）', () => {
  assert.match(workspaceSource, /setLoadError\(errorText\(err, '标注时间轴读取失败'\)\)/);
  assert.match(workspaceSource, /setTasksError\(errorText\(err, '分段任务列表读取失败'\)\)/);
  assert.doesNotMatch(workspaceSource, /mock/i);
  assert.doesNotMatch(railSource, /mock/i);
});

test('分段成功后给出进入标注工作台的入口', () => {
  assert.match(splitPanelSource, /onGoToAnnotation/);
  assert.match(splitPanelSource, /去标注这批样本（分段样本标注）/);
});
