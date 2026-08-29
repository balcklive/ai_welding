import type { SignalChannel } from '../../../api/types';

export const CH = 720; const CW = 220; const AXIS_L = 44; const AXIS_B = 22; const PLOT_W = CH - AXIS_L; const PLOT_H = CW - AXIS_B;
export const dur = 5.42;
export const SAMPLES = 216;
export const t = Array.from({ length: SAMPLES }, (_, i) => (i / (SAMPLES - 1)) * dur);
export function seg(s: number, e: number) { return s <= t[0] ? 0 : e >= dur ? 1 : s / dur; }
export const arc = 0.42; const weldS = 0.78; const weldE = 4.28; const ext = 4.86;
export const isArc = (x: number) => x < arc;
export const isWeld = (x: number) => x >= weldS && x <= weldE;
export const isTail = (x: number) => x > ext;
export const anomalA: [number, number] = [1.92, 2.34];
export const anomalB: [number, number] = [3.58, 3.86];
export const isAnomA = (x: number) => x >= anomalA[0] && x <= anomalA[1];
export const isAnomB = (x: number) => x >= anomalB[0] && x <= anomalB[1];
export const isAnom = (x: number) => isAnomA(x) || isAnomB(x);
export const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));

export function currentAmp(x: number): number {
  let b = 180;
  if (isArc(x)) b = 60 + (x / arc) * 130;
  else if (isTail(x)) b = 150 - (x - ext) * 90;
  else if (isWeld(x)) b = 180;
  const noise = isAnom(x) ? (Math.sin(x * 47) * 22 + Math.cos(x * 31) * 16) : (Math.sin(x * 25) * 7 + Math.cos(x * 18) * 4);
  const drip = Math.sin(x * 38) * (isWeld(x) ? 11 : 0);
  return clamp(b + noise + drip, 0, 300);
}
export function voltVal(x: number): number {
  let b = 22.4;
  if (isArc(x)) b = 14 + (x / arc) * 9;
  else if (isTail(x)) b = 22 - (x - ext) * 12;
  else if (isWeld(x)) b = 22.4;
  const noise = isAnom(x) ? (Math.sin(x * 53) * 3.4 + Math.cos(x * 29) * 2.6) : (Math.sin(x * 22) * 0.9 + Math.cos(x * 16) * 0.6);
  return clamp(b + noise, 0, 40);
}
export function gasVal(x: number): number {
  if (isArc(x)) return clamp(12 + (x / arc) * 6, 0, 30);
  if (isTail(x)) return clamp(18 - (x - ext) * 5, 0, 30);
  const noise = isAnom(x) ? (Math.sin(x * 13) * 2.4) : (Math.cos(x * 7) * 0.6);
  return clamp(18 + noise, 0, 30);
}
export function wireVal(x: number): number {
  if (isArc(x)) return clamp(3 + (x / arc) * 4, 0, 12);
  if (isTail(x)) return clamp(7 - (x - ext) * 5, 0, 12);
  const noise = isAnom(x) ? (Math.sin(x * 19) * 1.6) : (Math.cos(x * 11) * 0.4);
  return clamp(7 + noise, 0, 12);
}

export const sigCur = t.map(currentAmp);
export const sigVol = t.map(voltVal);
export const sigGas = t.map(gasVal);
export const sigWir = t.map(wireVal);

export type Chan = { id: string; name: string; unit: string; color: string; values: number[]; lo: number; hi: number; mean: string };
/** 通道配色（后端不输出颜色，前端按通道 id 映射，与 mock 常量一致）。 */
export const chanColor: Record<string, string> = { cur: '#2c9caf', vol: '#67cdb0', gas: '#f0a34a', wir: '#75add1' };
/** 后端信号通道 → 前端 Chan（values 已由 api 层降采样 ≤512 点）。 */
export function toChan(c: SignalChannel): Chan {
  return { id: c.id, name: c.name, unit: c.unit, color: chanColor[c.id] ?? '#2c9caf', values: c.values, lo: c.lo, hi: c.hi, mean: `${c.mean} ${c.unit}` };
}
export const mockChannels: Chan[] = [
  { id: 'cur', name: '电流', unit: 'A', color: '#2c9caf', values: sigCur, lo: 0, hi: 300, mean: '180 ± 12 A' },
  { id: 'vol', name: '电压', unit: 'V', color: '#67cdb0', values: sigVol, lo: 0, hi: 40, mean: '22.4 ± 1.8 V' },
  { id: 'gas', name: '气体流量', unit: 'L/min', color: '#f0a34a', values: sigGas, lo: 0, hi: 30, mean: '18 L/min' },
  { id: 'wir', name: '送丝速度', unit: 'm/min', color: '#75add1', values: sigWir, lo: 0, hi: 12, mean: '7 m/min' },
];
/** 加载期占位通道：保留通道骨架（名称/配色）但波形为空，避免 mock 波形闪现且不产生 undefined 取值。 */
export const emptyChannels: Chan[] = mockChannels.map((c) => ({ ...c, values: [], mean: '—' }));

export function fmt(s: number) {
  const m = Math.floor(s / 60);
  const r = (s - m * 60).toFixed(2).padStart(5, '0');
  return `${String(m).padStart(2, '0')}:${r}`;
}

/** 通用波形 path 构建（对齐页轨道/原始波形共用）；toPath 为分析页固定视口的委托。 */
export function buildPath(values: number[], lo: number, hi: number, plotW: number, plotH: number, axisL = 0): string {
  const range = hi - lo || 1;
  const n = Math.max(values.length - 1, 1);
  return values.map((v, i) => {
    const px = axisL + (i / n) * plotW;
    const py = (plotH * (1 - (v - lo) / range));
    return `${i === 0 ? 'M' : 'L'}${px.toFixed(1)} ${py.toFixed(1)}`;
  }).join(' ');
}

export function toPath(values: number[], lo: number, hi: number): string {
  return buildPath(values, lo, hi, PLOT_W, PLOT_H, AXIS_L);
}

export { CW, AXIS_L, AXIS_B, PLOT_W, PLOT_H, weldS, weldE, ext };
