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
const offsetPanelSource = read('features/alignment/OffsetCalibrationPanel.tsx');
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

test('视频零点偏移也复用既有 PUT …/calibration，面板自身不发任何网络请求', () => {
  // 标定写入仍然只有一个入口（对齐页父组件的 handleSaveOffset）——面板只回写草稿
  assert.match(analysisApiSource, /export async function updateCalibration\(/);
  assert.match(alignmentSource, /video:\s*\{\s*offset_seconds:/);
  assert.match(alignmentSource, /video: null \}\)/);   // 「清除标定」= 回到未标定
  // 面板是受控组件：不 import 接口层、不自己发请求（否则会出现第二条写入路径）
  assert.doesNotMatch(offsetPanelSource, /updateCalibration|fetch\(|\brequest\(/);
  assert.match(offsetPanelSource, /onDraft/);
  // 后端零改动：校验与手误护栏仍在服务端
  assert.match(alignmentPy, /MAX_ABS_OFFSET_SECONDS/);
  assert.match(alignmentPy, /def validate_calibration_patch\(/);
  assert.match(analysisPy, /class CalibrationUpdate/);
});

test('seek 写入与 onTimeUpdate 回写成对读同一个瞬时偏移（ref），且不重挂事件监听', () => {
  // 两处必须成对：只改一处 → seek 后游标被立刻拨回（历史上出过的坑）
  assert.match(alignmentSource, /Math\.max\(0,\s*next\s*-\s*effectiveOffsetRef\.current\)/);
  assert.match(alignmentSource, /setPlayhead\(ct \+ effectiveOffsetRef\.current\)/);
  assert.match(alignmentSource, /ref=\{videoRef\}/);
  // 拖动草稿即时生效靠 ref；事件委托 effect 的依赖里不得再有偏移量
  // （否则每拖一格滑块就重挂一次 click 监听器）
  const deps = alignmentSource.match(/\}, \[dataId, timelineDur, videoUrl, alignRes\]\);/);
  assert.ok(deps, 'click 委托 effect 的依赖数组不符合预期');
  assert.doesNotMatch(deps[0], /videoOffset/);
  assert.match(alignmentSource, /effectiveOffsetRef\.current = effectiveOffset/);
  // 拖偏移时画面必须跟着游标走（设计 §4.2 的"同屏游标与视频画面同步移动"）——
  // 只改读数不动画面的话，"对比时间戳"就只剩数字，没法目视对准起弧。
  assert.match(alignmentSource, /const handleOffsetDraft = /);
  assert.match(alignmentSource, /Math\.min\(video\.duration, Math\.max\(0, playhead - next\)\)/);
  assert.match(alignmentSource, /onDraft=\{handleOffsetDraft\}/);
});

test('反向标定按 offset = 起弧信号时刻 − 视频当前时刻 反解（后端语义 t_video = t_signal − offset）', () => {
  assert.match(alignmentSource, /events\.arc\s*-\s*video\.currentTime/);
  // 视频未就绪/无事件时挡在点击前，不拿不可靠的 currentTime 算
  assert.match(alignmentSource, /readyState < 1/);
  assert.match(alignmentSource, /Number\.isFinite\(video\.duration\)/);
  assert.match(alignmentSource, /reverseHint/);
});

test('时间戳对照读数与未标定语义：读数来自 <video> 元素，未标定必须说「按 0 计算」', () => {
  // 时长取自视频元素自身（未跑过对齐也拿得到，且与反向标定用同一元素自洽）
  assert.match(alignmentSource, /onLoadedMetadata=\{\(e\) => setVideoDuration/);
  assert.match(alignmentSource, /onDurationChange=\{\(e\) => setVideoDuration/);
  assert.match(offsetPanelSource, /视频当前帧/);
  assert.match(offsetPanelSource, /覆盖残差|按当前帧对齐起弧/);
  // 换算后的信号时刻**本来就可能为负**（t_signal = t_video + offset），不能喂给按非负轴写的 fmt()：
  // 实机验出 fmt(-5) 会渲染成 `-1:55.00`（Math.floor(-5/60) === -1、余数 55）。必须走带符号的 timecode()。
  const derived = offsetPanelSource.match(/视频当前帧 \{timecode\(videoTime\)\} ↔ 信号 \{([^}]+)\}/);
  assert.ok(derived, '读数行必须渲染「视频当前帧 ↔ 信号」');
  assert.match(derived[1], /timecode\(/);
  assert.doesNotMatch(derived[1], /\bfmt\(/);
  assert.match(offsetPanelSource, /const timecode = /);
  assert.match(offsetPanelSource, /n < 0 \? '-' : ''/);
  // 两态分得开，且说清「保存 0 也算已标定」——否则用户会以为没标定
  assert.match(offsetPanelSource, /'已标定' : '未标定（按 0 计算）'/);
  assert.match(offsetPanelSource, /保存后（哪怕保存的是 0）即记为已标定/);
  assert.match(offsetPanelSource, /清除标定/);
});

test('保存失败保留草稿（写操作 catch 只置错误态，不清用户输入）', () => {
  const catchLine = alignmentSource.split('\n').find((line) => line.includes('偏移保存失败'));
  assert.ok(catchLine, 'offset 保存必须有失败分支');
  assert.doesNotMatch(catchLine, /setVideoOffsetDraft|setVideoOffset\(/);
  // 草稿只在成功（.then）里清
  assert.match(alignmentSource, /setVideoOffset\(c\.video\.calibrated \? c\.video\.offset_seconds : 0\);\s*\n\s*setVideoOffsetDraft\(null\);/);
});

test('偏移面板挂在 alignment-aside 顶部（board 的兄弟），不落进 seek 事件委托的作用域', () => {
  assert.match(alignmentSource, /<aside className="alignment-aside"><OffsetCalibrationPanel/);
  // 面板不得出现在 alignment-board 内部（那里挂着点击定位的委托）
  const board = alignmentSource.match(/<section className="panel alignment-board">([\s\S]*?)<\/section>/);
  assert.ok(board, '必须能找到 alignment-board');
  assert.doesNotMatch(board[1], /OffsetCalibrationPanel/);
});

test('分段页的标定摘要只读：状态取自服务端预览，不在前端复算', () => {
  assert.match(rulesPanelSource, /标定状态（只读）/);
  assert.match(rulesPanelSource, /preview\?\.modalities\.seam_image/);
  assert.match(rulesPanelSource, /seam\?\.excluded/);
  assert.match(rulesPanelSource, /前往对齐页框选并保存 ROI|去对齐页改回参与/);
});
