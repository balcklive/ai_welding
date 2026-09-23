import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const read = (...parts) => fs.readFileSync(path.join(__dirname, ...parts), 'utf8');

const videoLaneSource = read('features/alignment/split/VideoTimelineLane.tsx');
const seamLaneSource = read('features/alignment/split/SeamImageLane.tsx');
const timelineSource = read('features/alignment/split/MultimodalTimeline.tsx');
const detailSource = read('features/alignment/split/SliceDetailPanel.tsx');
const workspaceSource = read('features/alignment/split/SplitWorkspace.tsx');
const cssSource = read('index.css');

test('视频轨是「一段一格」的胶片条，不是单个播放器 + 一堆竖线', () => {
  // 一格一段：格内是本段自己的真帧，格宽就是该段在时间轴上的占比
  assert.match(videoLaneSource, /windows\.map\(/);
  assert.match(videoLaneSource, /w\.video\.frame\?\.url/);
  assert.match(videoLaneSource, /const left = pctOf\(w\.start, duration\)/);
  assert.match(videoLaneSource, /pctOf\(w\.end, duration\) - left/);
  // 点格子 = 选段（与下方卡片网格同一入口）
  assert.match(videoLaneSource, /onSelect\(w\.index\)/);
  assert.match(videoLaneSource, /film-cell/);
  // 旧写法（播放器 + 缩略图时间点竖线）必须已经消失：那正是"一张图 + 很多竖线"的来源
  assert.doesNotMatch(videoLaneSource, /\n\s*<video[\s\n]/);
  assert.doesNotMatch(videoLaneSource, /thumbnailTimes|video_thumbnail_times/);
  assert.doesNotMatch(videoLaneSource, /lane-marker/);
  // 取不到帧就写原因，且无帧的格子不是深色占位（深底看着像真有画面）
  assert.match(videoLaneSource, /frame\?\.reason \?\? w\.video\.reason/);
  assert.match(videoLaneSource, /film-cell-empty/);
  assert.doesNotMatch(videoLaneSource, /frame_no.*\*.*fps/);
  // 前端不再消费"视频缩略图时间点"这个字段
  assert.doesNotMatch(timelineSource, /video_thumbnail_times/);
});

test('焊缝图片轨只显示已标定的 ROI，边界按 px(t) 落下而不是按时间百分比', () => {
  // 照片按 roi 反算放大倍率与偏移（ROI 那一块正好铺满轨道）——整张铺满会让 ROI 看不出效果
  assert.match(seamLaneSource, /\(natural\.w \/ roi\.w\) \* 100/);
  assert.match(seamLaneSource, /-\(roi\.x \/ roi\.w\) \* 100/);
  assert.match(seamLaneSource, /\(natural\.h \/ roi\.h\) \* 100/);
  // 边界来自服务端的像素投影区间，不是时间
  assert.match(seamLaneSource, /spatial_range\?\.start_px/);
  assert.match(seamLaneSource, /spatial_range\?\.end_px/);
  assert.match(seamLaneSource, /const pxPct = /);
  assert.doesNotMatch(seamLaneSource, /pctOf\(t, duration\)/);
  assert.doesNotMatch(seamLaneSource, /from '\.\/splitTypes'/);
  // 选中高亮同样按像素区间
  assert.match(seamLaneSource, /pxPct\(selected\.start_px\)/);
  // 只读：分段页不得写标定（与 App.roi-calibration-regression 同一条硬约定）
  assert.doesNotMatch(seamLaneSource, /updateCalibration/);
});

test('Tailwind preflight 被顶掉：照片定位/尺寸必须能压过 img{max-width:100%;height:auto}', () => {
  // 行内给 maxWidth/maxHeight:none，CSS 再兜一层——否则 ROI 裁切算出来的尺寸会被 max-width 截断
  assert.match(seamLaneSource, /maxWidth: 'none', maxHeight: 'none'/);
  assert.match(seamLaneSource, /\.\.\.NO_CLAMP, \.\.\.photo/);
  assert.match(cssSource, /\.seam-lane-photo \{ position:absolute; max-width:none; max-height:none; \}/);
  assert.match(cssSource, /\.lane-track-film \{ height:96px; \}/);
  assert.match(cssSource, /\.film-cell \{/);
});

test('播放器落到选中切片详情面板，seek 与回写两处成对', () => {
  assert.match(detailSource, /<video/);
  assert.match(detailSource, /window\.start - offsetSeconds/);
  assert.match(detailSource, /currentTime \+ offsetSeconds/);
  // 换段重挂载，否则同一个 <video> 不会重新定位到新段起点
  assert.match(detailSource, /key=\{window\.index\}/);
  // 分段页不再自己持有 videoRef / seek：反向换算只在详情面板里做一次
  assert.doesNotMatch(workspaceSource, /onSeek|videoRef/);
});

test('焊缝照片的键取自服务端预览，与对齐页框 ROI 时看的是同一张', () => {
  assert.match(workspaceSource, /seam_image_projection\.object_key/);
  // 扩展名启发式会先撞上对齐产物的关键帧 jpg（processed/…/keyframes/*.jpg）
  assert.doesNotMatch(workspaceSource, /IMAGE_EXTS/);
});
