/**
 * 分段工作台的纯类型与派生计算（设计 §7.1）。
 *
 * **刻意不在这里算窗口数量**：屏幕上的边界、数量、尾片一律以服务端成功预览为准（§7.1 末段）。
 * 本地只做"输入的形状转换"和"渲染用的坐标换算"，任何与切分规则有关的算术都不复制一份
 * ——复制就会漂移，而漂移的表现是"预览 207、执行 208"这种最难查的 bug。
 */
import type { SplitRules } from '../../../api/types';

export const DEFAULT_WINDOW_SECONDS = 2.0;
export const DEFAULT_STRIDE_SECONDS = 2.0;

/** 用户正在编辑的规则（`draftRules`，§7.2）。 */
export interface RulesDraft {
  windowSeconds: number;
  strideSeconds: number;
  eventStart: number | null;
  eventEnd: number | null;
  keepEventBuffer: boolean;
  bufferSeconds: number;
  tailPolicy: 'drop' | 'keep';
}

export function defaultDraft(): RulesDraft {
  return {
    windowSeconds: DEFAULT_WINDOW_SECONDS,
    strideSeconds: DEFAULT_STRIDE_SECONDS,
    eventStart: null,
    eventEnd: null,
    keepEventBuffer: false,
    bufferSeconds: 0,
    tailPolicy: 'drop',
  };
}

/** 草稿 → 请求体。**唯一**的转换点：`draftKey` 与请求体必须由同一份逻辑产出。 */
export function draftToRules(draft: RulesDraft): SplitRules {
  return {
    window_seconds: draft.windowSeconds,
    stride_seconds: draft.strideSeconds,
    event_start: draft.eventStart ?? undefined,
    event_end: draft.eventEnd ?? undefined,
    keep_event_buffer: draft.keepEventBuffer ? draft.bufferSeconds : 0,
    tail_policy: draft.tailPolicy,
  };
}

/**
 * 草稿指纹：与"最后一次成功预览"的 `rules_hash` 做比对，判断预览是否已过期（§7.2）。
 *
 * 服务端返回的是 `rules_hash`，客户端算不出同一个哈希（那是服务端的 canonical JSON），
 * 所以这里存**请求体本身**做比较——语义一致：请求体没变就不算 stale。
 */
export function draftKey(rules: SplitRules): string {
  return JSON.stringify([
    rules.window_seconds, rules.stride_seconds,
    rules.event_start ?? null, rules.event_end ?? null,
    rules.keep_event_buffer ?? 0, rules.tail_policy ?? 'drop',
  ]);
}

/** 时间(秒) → 轨道百分比。所有轨道共用同一个横轴（§4.4：禁止各轨单独缩放）。 */
export function pctOf(t: number, duration: number): number {
  if (!(duration > 0)) return 0;
  return Math.min(100, Math.max(0, (t / duration) * 100));
}

export function fmtSec(value: number, digits = 2): string {
  return `${value.toFixed(digits)}s`;
}

export function fmtRange(start: number, end: number, digits = 3): string {
  return `${start.toFixed(digits)} – ${end.toFixed(digits)} s`;
}

/**
 * 按**真实时间**构建波形 path。
 *
 * 服务端的 min-max 抽稀是非均匀的（保留瞬态尖峰，见 `signals.downsample_indices`），
 * 所以横坐标必须用每点自带的 `times`，不能按序号均分——按序号画会把尖峰的位置画错。
 */
export function timePath(
  times: number[],
  values: number[],
  lo: number,
  hi: number,
  duration: number,
  width: number,
  height: number,
): string {
  if (!times.length || !values.length || duration <= 0) return '';
  const span = hi - lo || 1;
  let path = '';
  for (let i = 0; i < times.length && i < values.length; i += 1) {
    const x = (Math.min(Math.max(times[i], 0), duration) / duration) * width;
    const y = height * (1 - (values[i] - lo) / span);
    path += `${i === 0 ? 'M' : 'L'}${x.toFixed(1)} ${y.toFixed(1)} `;
  }
  return path.trim();
}

export function trackRange(track: { values: number[] }): [number, number] {
  if (!track.values.length) return [0, 1];
  let lo = Infinity;
  let hi = -Infinity;
  for (const v of track.values) {
    if (v < lo) lo = v;
    if (v > hi) hi = v;
  }
  if (!Number.isFinite(lo) || !Number.isFinite(hi)) return [0, 1];
  if (hi === lo) return [lo - 1, hi + 1];
  return [lo, hi];
}
