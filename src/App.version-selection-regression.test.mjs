import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

/**
 * 「计算时手动选数据版本」（2026-10）的静态回归。
 *
 * 背景：分析链 6 个页面原先各自 `getWeld(...).latest_version_id` 写死最新版本，用户没法指定
 * 用哪一版算；同时新建数据版本里上传的加工 CSV 没人读（分析静默回退到 v1.0 的信号）。
 * 本文件钉住两件事：**版本选择的单一来源**与**各页都读它**。
 */

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const read = (relative) => fs.readFileSync(path.join(__dirname, relative), 'utf8');

const source = read('App.tsx');
const dataContextSource = read('features/data-context/DataContext.tsx');
const weldsApiSource = read('api/welds.ts');

/** 读它算哪一版：分析链各页都是 `const versionId = selectedVersionId ?? <自己那条焊缝的最新版>`。
 *
 *  **2026-10 移出**：`features/features/FeatureExtractionPage.tsx` 已被切片级工作台
 *  （`SampleFeatureWorkspace.tsx`）取代——它的单位是**分段任务**而不是焊缝版本，没有
 *  `selectedVersionId` 这个概念，故不属于本清单。 */
const VERSION_SOURCES = [
  'features/analysis/AnalysisWorkspace.tsx',
  'features/alignment/AlignmentWorkspace.tsx',
  'features/alignment/split/SplitWorkspace.tsx',
  'features/annotation/AnnotationWorkspace.tsx',
  'features/validation/ValidationPage.tsx',
];

test('AppShell 持有版本上下文，换样本时回到「跟随最新」', () => {
  assert.match(source, /const \[selectedVersionId, setSelectedVersionId\] = useState<number \| null>\(null\)/);
  // 版本是样本的下级：换样本不能残留上一版的 id
  assert.match(source, /useEffect\(\(\) => \{ setSelectedVersionId\(null\); \}, \[selectedDataId\]\)/);
  // 新建版本后自增，让顶部下拉立刻能看到新版（否则 15s GET 缓存期内选不到）
  assert.match(source, /const \[versionsRefreshKey, setVersionsRefreshKey\] = useState\(0\)/);
});

test('五个页面都从 selectedVersionId 派生，而不是各自写死最新版本', () => {
  for (const relative of VERSION_SOURCES) {
    assert.match(
      read(relative),
      /const versionId = selectedVersionId \?\? /,
      `${relative} 必须由 selectedVersionId 派生计算版本`,
    );
    assert.match(read(relative), /selectedVersionId\?: number \| null/, `${relative} 必须接收 selectedVersionId`);
  }
});

test('版本变了要能重拉：fetch effect 必须把 selectedVersionId 列进依赖', () => {
  // 这页的 fetch effect 原先只依赖 [dataId]（或 [dataId, reloadKey]），单改 versionId 不会重拉
  assert.match(read('features/validation/ValidationPage.tsx'), /\}, \[dataId, reloadKey, selectedVersionId\]\);/);
});

test('上下文条第三级「数据版本」下拉：候选来自 listVersions，默认链尾（= 最新）', () => {
  const switcher = dataContextSource.slice(
    dataContextSource.indexOf('export function SelectionSwitcher('),
    dataContextSource.indexOf('export function SelectionRequired('),
  );
  assert.match(switcher, /数据版本<select value=\{selectedVersionId \?\? latestVersionId \?\? ''\}/);
  assert.match(switcher, /listVersions\(selectedDataId\)/);
  // 刷新键进依赖：刚建的版本要立刻出现在候选里
  assert.match(switcher, /\}, \[selectedDataId, versionsRefreshKey\]\);/);
  // 链尾即最新（list_versions 按 created_at/id 升序），与后端 latest_version_id 指针一致
  assert.match(switcher, /versions\[versions\.length - 1\]\.id/);
});

test('对齐成功后把产物版本回写全局上下文（其他页也要看到这一版）', () => {
  const alignment = read('features/alignment/AlignmentWorkspace.tsx');
  assert.match(alignment, /if \(setSelectedVersionId\) setSelectedVersionId\(alignRes\.version\.id\)/);
});

test('数据版本页能看到导入态、能按版本重排失败导入', () => {
  const panel = dataContextSource.slice(
    dataContextSource.indexOf('function VersionPanel('),
    dataContextSource.indexOf('function VersionCreateDialog('),
  );
  // 链上标出这一版的信号导入结果（加工版建完即排队导入）
  assert.match(panel, /信号导入失败/);
  assert.match(panel, /信号导入中/);
  // 失败行必须可自助恢复：v1.0 的 reimport 够不到加工版，而重复建版会被判重挡掉
  assert.match(panel, /reimportVersionSignals\(dataId, String\(versionId\)\)/);
  // 有版本在导入时轮询版本链，导入完成/失败都看得见
  assert.match(panel, /setInterval/);
  // 建版成功要通知外层刷新版本候选
  assert.match(panel, /onVersionsChanged\?\.\(\)/);
  assert.match(weldsApiSource, /export async function reimportVersionSignals\(/);
});
