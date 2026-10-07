import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

/**
 * **切片级特征提取**（2026-10）的静态回归。
 *
 * 背景：此前特征提取是"焊缝的一版数据一份 42 维"（供人看），而训练时又各自现算一个
 * 8 维（一张缩略图或一段 CSV 的数字统计）、不落库。两边口径不同、切片跟 42 维也没有
 * 任何数据流。这次改成**一个切片一份 36 维**、落库、构建时冻进快照、训练读冻结值。
 *
 * 本文件钉住的是"静态可查、但一旦被改回去就会静默产生错误数据"的硬口径：
 * 维度与分组只有一处定义、切片不许有声音组、训练输入维度从数据来、页面无 mock 初始态、
 * 隐藏的归一化语义（存原始值）、以及分段页的入口不许绕开路由助手。
 */

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.join(__dirname, '..');
const read = (relative) => fs.readFileSync(path.join(__dirname, relative), 'utf8');
const readBackend = (relative) => fs.readFileSync(path.join(REPO, 'backend', relative), 'utf8');

const app = read('App.tsx');
const workspace = read('features/features/SampleFeatureWorkspace.tsx');
const featureRows = read('features/features/featureRows.ts');
const api = read('api/sampleFeatures.ts');
const splitWorkspace = read('features/alignment/split/SplitWorkspace.tsx');
const splitPanel = read('features/alignment/split/SplitRulesPanel.tsx');

const featuresPy = readBackend('app/services/features.py');
const sampleFeaturesPy = readBackend('app/services/sample_features.py');
const torchPy = readBackend('app/services/torch_training.py');
const datasetsPy = readBackend('app/services/datasets.py');

test('路由：analysis/features 换成切片级工作台，且**不传 selectedVersionId**', () => {
  assert.match(app, /import\('\.\/features\/features\/SampleFeatureWorkspace'\)/);
  assert.match(
    app,
    /route === 'analysis\/features'\)[\s\S]{0,120}?<SampleFeatureWorkspace embedded dataId=\{selectedDataId\} \/> : <SelectionRequired/,
  );
  // 单位是**分段任务**而不是焊缝版本——带上 selectedVersionId 就意味着又在按版本算了。
  // 按**签名**断言而不是按关键字：文件里提到这个词（注释解释"为什么没有它"）不算违规。
  assert.match(
    workspace,
    /export function SampleFeatureWorkspace\(\{ dataId \}: \{ embedded\?: boolean; dataId\?: string \}\)/,
  );
  assert.doesNotMatch(app, /<SampleFeatureWorkspace[^>]*selectedVersionId/);
  // 已被取代的版本级页面不该留下
  assert.equal(fs.existsSync(path.join(__dirname, 'features/features/FeatureExtractionPage.tsx')), false);
});

test('36 维：分组定义只有一处，切片级是"去掉声音组的同一份定义"', () => {
  assert.match(featuresPy, /SAMPLE_GROUP_DIMS\s*=\s*GROUP_DIMS\[:-1\]/);
  assert.match(featuresPy, /SAMPLE_GROUP_NAMES\s*=\s*GROUP_NAMES\[:-1\]/);
  assert.match(featuresPy, /SAMPLE_TOTAL_DIMS\s*=\s*sum\(SAMPLE_GROUP_DIMS\)/);
  // 只有一处 `def unify(`——切片级靠 include_audio 参数化，不是 fork 出第二个函数
  assert.equal((featuresPy.match(/^def unify\(/gm) ?? []).length, 1);
  assert.match(featuresPy, /include_audio: bool = True/);
  // 切片调用点必须显式关掉声音组（不关就成 42 维，且塞进 6 个合成音频维度）
  assert.match(sampleFeaturesPy, /include_audio=False/);
  // 切片向量恒为原始值：逐切片 Z-Score 会把每片各自减均值、抹掉区分切片的那批量
  assert.match(sampleFeaturesPy, /CANONICAL_NORMALIZATION\s*=\s*"无"/);
  assert.match(sampleFeaturesPy, /normalization: str = CANONICAL_NORMALIZATION/);
});

test('切片页没有音频面板（切片 manifest 自己写着 audio.available=False）', () => {
  assert.doesNotMatch(workspace, /AUDIO_ROWS|mapAudioRows|audio_features|声音·频带/);
  assert.doesNotMatch(featureRows, /AUDIO_ROWS|mapAudioRows|声音·频带/);
  // 请求体里不许出现音频相关字段（按字段名断言，注释里解释"为什么没有声音组"不算）
  assert.doesNotMatch(api, /audio_features|audio_key|"audio"|'audio'/);
});

test('页面无 mock 初始态：初始一律空 + loading，失败走 ErrorState', () => {
  assert.match(workspace, /<ErrorState scene=/);
  // 初始态必须是空集合 / null，而不是任何"演示初始值"——本页此前是全局 mock 禁令的
  // 唯一例外（"特征表刻意保留 mock 初始"），本版起退休（见 `src/CLAUDE.md`）。
  assert.match(workspace, /useState<SampleFeatureTask\[\]>\(\[\]\)/);
  assert.match(workspace, /useState<SampleFeatureRow\[\]>\(\[\]\)/);
  assert.match(workspace, /useState<SampleFeatureDetail \| null>\(null\)/);
  // 失败分支只清空 + 报错，不塞回演示数据
  assert.match(workspace, /setRows\(\[\]\)/);
  assert.match(workspace, /切片加载中…/);
});

test('训练输入维度从数据来，不再写死 8；口径记进权重文件', () => {
  assert.doesNotMatch(torchPy, /nn\.Linear\(8,/);
  assert.match(torchPy, /input_dim = len\(examples\[0\]\.features\)/);
  assert.match(torchPy, /nn\.Linear\(input_dim, 16\)/);
  assert.match(torchPy, /"input_dim": input_dim/);
  assert.match(torchPy, /"feature_kind": feature_kind/);
  // 全有 / 全无 / 混用三态：混用必须**拒**（两种口径的向量长度不同）
  assert.match(torchPy, /feature_kind = "slice_v1"/);
  assert.match(torchPy, /feature_kind = "legacy_summary"/);
  assert.match(torchPy, /缺少切片特征/);
});

test('构建时把向量冻进成员行与快照（复现性：改特征不得改动已建版本）', () => {
  assert.match(datasetsPy, /features=features_by_sample\.get\(s\.id\)/);
  assert.match(datasetsPy, /"features": features_by_sample\.get\(s\.id\)/);
  assert.match(datasetsPy, /def features_frozen\(/);
  // 训练准入要能区分"全无"（存量，放行走旧口径）与"混用"（拒）
  assert.match(datasetsPy, /def feature_coverage\(/);
});

test('分段页的入口走路由助手，不直接改 window.location.hash', () => {
  assert.match(splitPanel, /去提取切片特征/);
  assert.match(splitWorkspace, /onGoToFeatures=\{done \? goToFeatures : undefined\}/);
  assert.match(splitWorkspace, /navigate\('analysis\/features'\)/);
  // `window.location.hash` 绕开 history.pushState 的同路由 replaceState 语义
  assert.doesNotMatch(splitWorkspace, /window\.location\.hash/);
});

test('api 模块与工作台对齐后端契约（task_id 用 job_uid、导出走任务级接口）', () => {
  assert.match(api, /listSampleFeatureTasks\(weldId: string\)/);
  assert.match(api, /`\/welds\/\$\{weldId\}\/sample-feature-tasks`/);
  assert.match(api, /createSampleFeatureExtraction\(/);
  assert.match(api, /`\/split-tasks\/\$\{taskId\}\/sample-features`/);
  assert.match(api, /`\/split-tasks\/\$\{taskId\}\/sample-features\/export`/);
  // 不要沿用版本级那条按 extraction_id 读 feature_extractions 的导出
  assert.doesNotMatch(workspace, /downloadFeatureExtraction|getLatestFeatureExtraction/);
});
