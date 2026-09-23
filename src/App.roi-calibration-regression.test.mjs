import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const read = (...parts) => fs.readFileSync(path.join(__dirname, ...parts), 'utf8');

const analysisApiSource = read('api/analysis.ts');
const typesSource = read('api/types.ts');
const editorSource = read('features/alignment/SeamRoiEditor.tsx');
const alignmentSource = read('features/alignment/AlignmentWorkspace.tsx');
const laneSource = read('features/alignment/split/SeamImageLane.tsx');
const rulesPanelSource = read('features/alignment/split/SplitRulesPanel.tsx');
const workspaceSource = read('features/alignment/split/SplitWorkspace.tsx');
const timelineSource = read('features/alignment/split/MultimodalTimeline.tsx');
const detailSource = read('features/alignment/split/SliceDetailPanel.tsx');

// 后端：标定写入与"是否参与"的唯一权威（复用既有 PUT 契约，不新增平行接口）
const backendDir = path.join(__dirname, '..', 'backend', 'app');
const alignmentPy = fs.readFileSync(path.join(backendDir, 'services', 'alignment.py'), 'utf8');
const splittingPy = fs.readFileSync(path.join(backendDir, 'services', 'splitting.py'), 'utf8');
const analysisPy = fs.readFileSync(path.join(backendDir, 'api', 'v1', 'analysis.py'), 'utf8');

test('ROI 写入复用既有 PUT …/calibration 契约，不新增平行接口', () => {
  assert.match(analysisApiSource, /export async function updateCalibration\(/);
  assert.match(analysisApiSource, /`\/welds\/\$\{weldId\}\/versions\/\$\{versionId\}\/calibration`[\s\S]*?method: 'PUT'/);
  assert.match(typesSource, /export interface CalibrationUpdate/);
  // 写入只有一个入口：对齐页；分段页不得出现写标定的调用
  assert.doesNotMatch(rulesPanelSource, /updateCalibration/);
  assert.doesNotMatch(laneSource, /updateCalibration/);
  assert.doesNotMatch(workspaceSource, /updateCalibration/);
});

test('ROI 校验留在服务端：前端把鼠标位置换算回原始像素，不自己放宽范围', () => {
  // 前端只做显示尺寸 → 原始像素的等比换算（naturalWidth/Height），范围校验由后端比图片宽高
  assert.match(editorSource, /el\.naturalWidth/);
  assert.match(editorSource, /el\.naturalHeight/);
  assert.match(editorSource, /rect\.width/);
  // 白框不产生退化 ROI（服务端只校验范围，0 宽高会一路流进坐标映射）
  assert.match(editorSource, /MIN_ROI_PX/);
  assert.match(alignmentPy, /ROI 超出图片范围/);
});

test('未框选 ROI 时不在分段页展示整张焊缝原图，而是给去对齐页的引导', () => {
  // 投影图只在 ready 分支内渲染，ready 必须含 roi —— 没有 ROI 就没有 px(t) 坐标系
  const ready = laneSource.match(/const ready = ([^;]+);/);
  assert.ok(ready, 'SeamImageLane 必须显式定义 ready');
  assert.match(ready[1], /projection\.roi/);
  assert.match(laneSource, /href="#\/analysis\/alignment"/);
  assert.match(laneSource, /框选并保存 ROI/);
});

test('「不对焊缝图片进行分段」是显式选择，与「还没框 ROI」分开表达', () => {
  // 前端：按钮写 excluded 位，且不参与时不再催用户去标定
  assert.match(editorSource, /不对焊缝图片进行分段/);
  assert.match(editorSource, /excluded: true/);
  assert.match(editorSource, /projection|excluded/);
  assert.match(laneSource, /projection\.excluded/);
  assert.match(laneSource, /notParticipating && !projection\.excluded/);
  // 后端：excluded 走独立分支，不需要 ROI、也不下载图片做越界校验
  assert.match(alignmentPy, /excluded = image_cal\.get\("excluded"\) is True/);
  assert.match(alignmentPy, /SEAM_EXCLUDED_REASON/);
  assert.match(splittingPy, /if seam\.get\("excluded"\)/);
  assert.match(analysisPy, /excluded/);
});

test('图片模态不可用不阻断分段，且预览与正式任务共用同一份 manifest 逻辑', () => {
  // 预览窗口直接复用正式 manifest 的映射逻辑——"预览 == 产物"的技术基础
  assert.match(splittingPy, /"seam_image": _seam_image_part\(/);
  assert.match(splittingPy, /manifest = map_window_to_modalities\(/);
  // 不可用只记 reason，不抛错（时序/视频样本照常生成）
  assert.match(splittingPy, /"available": False, "reason"/);
  // 标定每次从 v1.0 权威标定现读，改完标定下次预览即生效
  assert.match(splittingPy, /alignment\.resolve_calibration\(session, record\)/);
  assert.match(alignmentPy, /def anchored_calibration\(/);
});

test('图片模态在分段预览与切片详情里标「未参与」，而不是含糊的"暂时没有"', () => {
  // 切片卡片：可用 / 明确不参与 / 其它不可用 三态分开
  assert.match(timelineSource, /图片未参与/);
  assert.match(timelineSource, /w\.seam_image\.excluded/);
  // 切片详情（样本 manifest 的界面读法）：不可用前缀由 excluded 决定
  assert.match(detailSource, /missingLabel=\{window\.seam_image\.excluded \? '未参与本轮分段'/);
  assert.match(detailSource, /missingLabel \?\? '不可用'/);
  // 后端 manifest 的同一事实（原因由服务端给，前端不自己编）
  assert.match(splittingPy, /"excluded": True,/);
});

test('分段页的标定摘要只读：状态取自服务端预览，不在前端复算', () => {
  assert.match(rulesPanelSource, /标定状态（只读）/);
  assert.match(rulesPanelSource, /preview\?\.modalities\.seam_image/);
  assert.match(rulesPanelSource, /seam\?\.excluded/);
  assert.match(rulesPanelSource, /前往对齐页框选并保存 ROI|去对齐页改回参与/);
});
