/**
 * 对齐页「可拖动的统一轴胶片条」硬约定（2026-10）。
 *
 * 背景：此前"视频的时间 bar"是 `<video controls>` 的原生进度条，量程是视频自己的
 * 0–duration，与信号轴**没有任何几何关系**——两条 bar 叠在一起看起来能对上、实际对不上
 * （实测标尺 left=315/width=790、轨道 left=459/width=646、标尺还左偏 144px）。
 * 现在视频画成统一轴上真实占位的一段（`left = offset`、`width = videoDuration`），拖它改 offset。
 *
 * 本文件钉的是**改错就会坏、且坏了不容易发现**的那几条，不是实现细节。
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const read = (...parts) => fs.readFileSync(path.join(__dirname, ...parts), 'utf8');

const alignmentSource = read('features/alignment/AlignmentWorkspace.tsx');
const filmSource = read('features/alignment/VideoFilmLane.tsx');
const panelSource = read('features/alignment/OffsetCalibrationPanel.tsx');
const analysisApiSource = read('api/analysis.ts');
const typesSource = read('api/types.ts');
const cssSource = read('index.css');

const backendDir = path.join(__dirname, '..', 'backend', 'app');
const alignmentPy = fs.readFileSync(path.join(backendDir, 'services', 'alignment.py'), 'utf8');

test('点击定位的委托必须同时排除播放器轨与胶片轨（否则点一下条会既改 offset 又 seek）', () => {
  // 两处都要排除：closest 判定 与 querySelectorAll 补 tabindex/role
  const selector = '\\.lane-track:not\\(\\.lane-track-video\\):not\\(\\.lane-track-film\\)';
  assert.match(alignmentSource, new RegExp(`closest\\('\\.studio-ruler, ${selector}'\\)`));
  assert.match(alignmentSource, new RegExp(`querySelectorAll\\('\\.studio-ruler, ${selector}'\\)`));
});

test('胶片轨不参与 seek 委托的 effect，且那个 effect 的依赖数组不许变', () => {
  // 依赖数组是这个 effect 的"刻意精简"契约：掺进 videoFrames 会让监听器随拖动重挂
  const delegate = alignmentSource.match(
    /const seek = \(event: Event\) =>([\s\S]*?)\}, \[dataId, timelineDur, videoUrl, alignRes\]\);/,
  );
  assert.ok(delegate, '必须能定位到挂 click 委托的那个 effect');
  assert.doesNotMatch(delegate[1], /getVideoFrames/, '帧请求不得塞进委托 effect');
  // 帧请求是独立 effect，只依赖 [dataId, versionId]
  assert.match(alignmentSource, /getVideoFrames\(dataId, String\(versionId\)\)/);
});

test('条的位置/宽度用不钳的换算——用 pct/pctOf 会说谎', () => {
  // `pct`/`pctOf` 都 Math.min(100, Math.max(0, …))：offset 超出信号时长时条粘在最右，
  // 视频比信号长时宽封顶 100%，把"超出"这个事实藏起来。越界应交给 overflow:hidden 如实裁掉。
  const axisPct = filmSource.match(/const axisPct =([^;]+);/);
  assert.ok(axisPct, '必须有 axisPct');
  assert.doesNotMatch(axisPct[1], /Math\.min|Math\.max/, 'axisPct 必须不钳');
  assert.match(filmSource, /left: axisPct\(offset\), width: axisPct\(videoDuration \?\? 0\)/);
  assert.doesNotMatch(filmSource, /pctOf\(/);
});

test('拖动换算用【轨道】宽而不是条宽，且像素→秒的系数正确', () => {
  assert.match(filmSource, /event\.clientX - drag\.startX/);
  assert.match(filmSource, /const pxPerSec = drag\.trackWidth \/ \(timelineDur \|\| 1\)/);
  assert.match(filmSource, /getBoundingClientRect/);
  // 负面断言：拿条宽换算会在条短于轨道时**过量移动**（拖 100px、条跑 100×(track/bar) px）
  assert.doesNotMatch(filmSource, /stripRef\.current\.(clientWidth|getBoundingClientRect)/);
});

test('手势三件套齐：指针捕获 + move + cancel/up 都清拖动态', () => {
  assert.match(filmSource, /setPointerCapture\(event\.pointerId\)/);
  assert.match(filmSource, /onPointerMove=\{onPointerMove\}/);
  assert.match(filmSource, /onPointerCancel=\{endDrag\}/);
  assert.match(filmSource, /onPointerUp=\{endDrag\}/);
  // pointerId 过滤：多指触摸时第二根手指不能接管
  assert.match(filmSource, /drag\.pointerId !== event\.pointerId/);
  // 图片默认可拖 → 必须 preventDefault + draggable={false}，否则原生 dragstart 抢手势
  assert.match(filmSource, /event\.preventDefault\(\)/);
  assert.match(filmSource, /draggable=\{false\}/);
  // 抖一下不算"有未保存的改动"
  assert.match(filmSource, /if \(Math\.abs\(value - drag\.last\) < 1e-3\) return;/);
});

test('起弧磁吸：阈值是双条件（像素 + 秒），且有迟滞与释放阈值', () => {
  assert.match(filmSource, /Math\.abs\(next - arcSignal\) \* pxPerSec <= limit/);
  assert.match(filmSource, /Math\.abs\(next - arcSignal\) <= SNAP_SECONDS/);
  assert.match(filmSource, /SNAP_RELEASE_PX/);
  assert.match(filmSource, /next = arcSignal;/);
});

test('胶片轨的根是 <div className="lane"> 而不是 <section>（board 的正则切分靠它）', () => {
  assert.match(filmSource, /<div className="lane">/);
  assert.doesNotMatch(filmSource, /<section/);
});

test('面板不再有滑块（拖动取代了它），但仍保留手填与反向标定', () => {
  assert.doesNotMatch(panelSource, /type="range"/);
  assert.doesNotMatch(panelSource, /SLIDER_LIMIT/);
  assert.match(panelSource, /以当前帧对齐起弧/);
  assert.match(panelSource, /offset-value/);
});

test('后端抽帧与 offset 无关：seek_offset 恒 0，键带视频摘要位', () => {
  assert.match(alignmentPy, /seek_offset=0\.0/);
  assert.match(alignmentPy, /def video_frame_times\(/);
  assert.match(alignmentPy, /def video_frame_key\(/);
  // 键里必须有视频鉴别位：没有它，换视频后 _object_exists 会把旧帧判成命中复用
  assert.match(alignmentPy, /_video_digest\(video_key\)/);
  assert.match(alignmentPy, /VIDEO_FRAME_MAX_COUNT/);
  // 截断不许静默
  assert.match(alignmentPy, /logger\.warning\(\s*\n?\s*"Video frames clamped/);
  // 复用 _load_video 的下载前预检，而不是自己读字节后再判
  assert.match(alignmentPy, /_load_video\(video_key\)/);
});

test('接口层与类型跟着契约走', () => {
  assert.match(analysisApiSource, /export async function getVideoFrames\(/);
  assert.match(analysisApiSource, /\/versions\/\$\{versionId\}\/video-frames/);
  assert.match(typesSource, /export interface VideoFrames/);
  assert.match(typesSource, /export interface VideoFrame \{/);
});

test('CSS：标尺与轨道同起点（--lane-label 带 fallback），标记线不吃指针', () => {
  // 三页（对齐/分段/标注）标尺左偏 144px 的根因：.lane 的标签列而标尺没内缩。
  // fallback 是必需的——.lane 还出现在这两个容器之外（SliceDetailPanel / AnnotationRail）
  assert.match(cssSource, /grid-template-columns:var\(--lane-label,132px\) 1fr/);
  assert.match(cssSource, /margin-left:calc\(var\(--lane-label,132px\) \+ 12px\)/);
  assert.match(cssSource, /\.alignment-board \{[^}]*--lane-label:132px/);
  assert.match(cssSource, /\.annot-timeline \{[^}]*--lane-label:132px/);
  // 条上那 1.5px 竖线没有 pointer-events:none 时会吞掉 pointerdown，标记附近抓不住条
  assert.match(cssSource, /\.lane-marker\{[^}]*pointer-events:none/);
  assert.match(cssSource, /\.lane-playhead\{[^}]*pointer-events:none/);
  assert.match(cssSource, /\.video-film-strip \{[^}]*touch-action:none/);
});
