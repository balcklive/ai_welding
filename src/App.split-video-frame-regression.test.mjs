import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const read = (...parts) => fs.readFileSync(path.join(__dirname, ...parts), 'utf8');

const timelineSource = read('features/alignment/split/MultimodalTimeline.tsx');
const detailSource = read('features/alignment/split/SliceDetailPanel.tsx');
const laneSource = read('features/alignment/split/SeamImageLane.tsx');
const typesSource = read('api/types.ts');
const cssSource = read('index.css');

// 后端：帧时刻的**唯一**换算处 + 预览逐段挂 URL + 产物逐段落盘
const backend = path.join(__dirname, '..', 'backend', 'app');
const splittingPy = fs.readFileSync(path.join(backend, 'services', 'splitting.py'), 'utf8');
const splitJobPy = fs.readFileSync(path.join(backend, 'jobs', 'split.py'), 'utf8');
const analysisPy = fs.readFileSync(path.join(backend, 'api', 'v1', 'analysis.py'), 'utf8');

test('每段卡片渲染**本段自己的**真帧，没有代表帧就写原因', () => {
  // 真帧来自本段的 frame.url —— 不是固定的占位图，也不是全局首帧
  assert.match(timelineSource, /w\.video\.frame\?\.url/);
  assert.match(timelineSource, /<img src=\{w\.video\.frame\.url\}/);
  // 取不到时给**原因**（视频不可用 / 覆盖范围外 / 抽帧失败都由后端给）
  assert.match(timelineSource, /无代表帧：\{w\.video\.frame\?\.reason/);
  // 旧实现是"渐变色块 + 段号"冒充缩略图：那个 `sample-thumb` 里只剩 span 的写法必须已经消失
  assert.doesNotMatch(timelineSource, /<div className="sample-thumb">\s*<span>#\{w\.index\}<\/span>/);
  // 无帧的卡片走浅底空态（不是渐变块）
  assert.match(timelineSource, /sample-thumb-empty/);
});

test('代表帧的取时刻规则在后端只有一处，预览与产物共用', () => {
  // 唯一实现：窗口中点 + 覆盖范围判定（预览抽帧、Job 落盘、manifest 三处都读它）
  assert.match(splittingPy, /def representative_frame_time\(/);
  assert.match(splittingPy, /t_video = \(window\.start \+ window\.end\) \/ 2\.0 - offset/);
  assert.match(splittingPy, /def _frame_part\(/);
  assert.match(splittingPy, /"frame": _frame_part\(window, video, frame_key\)/);
  // Job 必须调同一个函数（各写一份必然漂移：预览给中点、产物给别的帧）
  assert.match(splitJobPy, /splitting\.representative_frame_time\(/);
  assert.match(splitJobPy, /video_frame_key=frame_key/);
  // 帧号/视频轴时刻由服务端算好给前端，前端不自己换算
  assert.doesNotMatch(timelineSource, /frame_no.*\*.*fps/);
});

test('预览接口明确提供代表帧地址：短期 URL + 逐段对象键，二进制不进 JSON', () => {
  assert.match(splittingPy, /def attach_preview_frames\(/);
  assert.match(splittingPy, /storage\.presign_get\(key, expires=PREVIEW_FRAME_EXPIRES_SECONDS\)/);
  assert.match(splittingPy, /PREVIEW_FRAME_EXPIRES_SECONDS = 3600/);
  assert.match(analysisPy, /splitting\.attach_preview_frames\(/);
  // 对象键按（焊缝, 映射哈希, 段号）复用：重复预览覆盖同一批对象，不无限累积
  assert.match(splittingPy, /def _preview_frame_key\(/);
  assert.match(splittingPy, /split-preview\/\{digest\}\/\{index:06d\}\.jpg/);
  // 键只有一处构造：写入与"已抽过"判定必须是同一个键，否则复用永远不命中
  const keyCalls = splittingPy.match(/_preview_frame_key\(weld_id, digest, window\.index\)/g) ?? [];
  assert.equal(keyCalls.length, 2, '拼接与判定都要走 _preview_frame_key');
  // 已落盘的代表帧直接复用：不再下视频、不重跑 ffmpeg（改一次规则就全量重抽会把预览拖死）
  assert.match(splittingPy, /if _object_exists\(storage, key\)/);
  assert.match(splittingPy, /def _object_exists\(/);
  // **不设段数上限**：视频覆盖范围内有多少段就抽多少段，不许按段截断（旧实现的
  // `PREVIEW_FRAME_LIMIT` 会让第 25 段起没有代表帧，那等于凭空少一个模态）
  assert.doesNotMatch(splittingPy, /PREVIEW_FRAME_LIMIT/);
  assert.doesNotMatch(splittingPy, /抽帧上限（\d+ 段）/);
  assert.doesNotMatch(splittingPy, /kept = targets\[:/);
  // 抽帧/上传失败逐段记原因，不伪造图片
  assert.match(splittingPy, /"reason": f"预览抽帧失败：\{exc\}"/);
  assert.match(splittingPy, /"reason": f"代表帧上传失败：\{exc\}"/);
});

test('正式任务的视频样本与预览同一帧：帧落进 object_keys 且用独立键名', () => {
  assert.match(splitJobPy, /def _extract_video_frames\(/);
  assert.match(splitJobPy, /\{int\(frame\['event'\]\):06d\}\.frame\.jpg/);
  assert.match(splitJobPy, /object_keys = \[key for key in \(frame_key, crop_key\) if key\]/);
  // 抽帧失败只告警、样本照常（视频是增强模态）——与焊缝图片裁切同一取舍
  assert.match(splitJobPy, /samples kept without frames/);
});

test('前端类型跟着契约走（帧的时间/帧号/地址都在类型里）', () => {
  assert.match(typesSource, /export interface SplitVideoFrame/);
  assert.match(typesSource, /t_signal\?: number/);
  assert.match(typesSource, /t_video\?: number/);
  assert.match(typesSource, /frame_no\?: number/);
  assert.match(typesSource, /frame\?: SplitVideoFrame/);
});

test('切片详情复用同一帧信息（预览给 URL、产物给对象键）', () => {
  assert.match(detailSource, /window\.video\.frame\?\.available/);
  assert.match(detailSource, /window\.video\.frame\.url/);
  assert.match(detailSource, /window\.video\.frame\.object_key/);
  assert.match(detailSource, /本段无视频代表帧：\{window\.video\.frame\?\.reason/);
});

test('第一批 ROI 行为不回退：无 ROI 仍不铺原图、不参与仍不催标定', () => {
  // 图片轨的 ready 仍必须含 roi（没有 ROI 就没有 px(t) 坐标系）
  const ready = laneSource.match(/const ready = ([^;]+);/);
  assert.ok(ready, 'SeamImageLane 必须显式定义 ready');
  assert.match(ready[1], /projection\.roi/);
  assert.match(laneSource, /projection\.excluded/);
  // 代表帧的样式不覆盖/不删除 ROI 面板用到的类
  assert.match(cssSource, /\.sample-thumb-empty \.sample-thumb-no/);
  assert.match(cssSource, /\.seam-roi-panel/);
});
