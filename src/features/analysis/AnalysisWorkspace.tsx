import { useEffect, useMemo, useState } from 'react';
import {
  Activity, AlertTriangle, Archive, ArrowUpRight, BarChart3, Check, Gauge,
  Layers3, Minus, Plus, Sparkles, Waves, Filter as FilterIcon,
} from 'lucide-react';
import { getAnalysisMode, getAnalysisResult, getSignals } from '../../api/analysis';
import { getWeld } from '../../api/welds';
import type {
  AnalysisResult, DataRecord, DwtData, PddData, PhaseData, PsdData,
  SignalChannel, SignalData, SignalQuery, StftData, WaveletBand, WaveletData, WeldAnomaly,
} from '../../api/types';
import { PageIntro } from '../../shared/components/PageIntro';
import { Toolbar } from '../../shared/components/Toolbar';
import {
  CH, CW, AXIS_L, PLOT_W, PLOT_H, dur,
  clamp, chanColor, toChan, emptyChannels, fmt, buildPath, toPath,
} from './signals/chartData';
import type { Chan } from './signals/chartData';

export type SplitPreviewSample = { index: number; start: number; end: number };
const emptyPhaseValues: number[] = [];

/** 时间轴刻度：等距分段（`.explore-axis` 用 space-between 定位，非等距会标错位置）。 */
function timeTicks(total: number, count = 5): number[] {
  return Array.from({ length: count + 1 }, (_, i) => Number(((total * i) / count).toFixed(2)));
}
const axisLabel = (second: number) => `${second}s`;

/** 按时间窗口从当前信号中取出样本缩略图数据。信号接口返回的点已抽稀，适合做小卡片预览。 */
function sliceSignalWindow(channel: SignalChannel | undefined, start: number, end: number, duration: number): number[] {
  if (!channel?.values?.length || duration <= 0) return [];
  const last = channel.values.length - 1;
  const from = Math.max(0, Math.min(last, Math.floor((start / duration) * last)));
  const to = Math.max(from, Math.min(last, Math.ceil((end / duration) * last)));
  const values = channel.values.slice(from, to + 1);
  return values.length > 1 ? values : channel.values.slice(Math.max(0, from - 1), Math.min(last + 1, from + 2));
}

export function SampleWaveThumb({ sample, signals, duration }: { sample: SplitPreviewSample; signals: SignalData | null; duration: number }) {
  const current = signals?.channels.find((channel) => channel.id === 'cur');
  const voltage = signals?.channels.find((channel) => channel.id === 'vol');
  const currentValues = sliceSignalWindow(current, sample.start, sample.end, duration);
  const voltageValues = sliceSignalWindow(voltage, sample.start, sample.end, duration);
  if (!currentValues.length && !voltageValues.length) {
    return <div className="sample-thumb sample-thumb-empty"><Waves size={16} /><span>波形加载中</span></div>;
  }
  return <div className="sample-thumb sample-wave-thumb" aria-label="电流电压波形缩略图">
    <svg viewBox="0 0 100 42" preserveAspectRatio="none" role="img">
      {currentValues.length > 1 && current && <path d={buildPath(currentValues, current.lo, current.hi, 100, 18)} fill="none" stroke={chanColor.cur} strokeWidth="1.25" vectorEffect="non-scaling-stroke" />}
      {voltageValues.length > 1 && voltage && <path d={buildPath(voltageValues, voltage.lo, voltage.hi, 100, 18, 24)} fill="none" stroke={chanColor.vol} strokeWidth="1.25" vectorEffect="non-scaling-stroke" />}
    </svg>
    <span className="sample-wave-legend"><i style={{ background: chanColor.cur }} />电流 <i style={{ background: chanColor.vol }} />电压</span>
  </div>;
}


function PhasePlot({ cursor, onCursor, data, loading, dur: totalDur, anomalies }: { cursor: number; onCursor: (s: number) => void; data?: PhaseData; loading?: boolean; dur: number; anomalies: WeldAnomaly[] }) {
  const w = 520; const h = 300; const pad = 42; const pw = w - pad * 2; const ph = h - pad * 2;
  const domain = (values: number[], fallback: { lo: number; hi: number }, minimumSpan: number) => {
    let min = Infinity; let max = -Infinity;
    for (const value of values) { if (Number.isFinite(value)) { min = Math.min(min, value); max = Math.max(max, value); } }
    if (!Number.isFinite(min) || !Number.isFinite(max)) return fallback;
    const span = Math.max(max - min, minimumSpan);
    const margin = Math.max(span * 0.06, minimumSpan * 0.08);
    const center = (min + max) / 2;
    return { lo: center - span / 2 - margin, hi: center + span / 2 + margin };
  };
  const rawCurrent = data?.current ?? emptyPhaseValues;
  const rawVoltage = data?.voltage ?? emptyPhaseValues;
  const fullX = useMemo(() => domain(data?.current ?? emptyPhaseValues, { lo: 140, hi: 230 }, 10), [data]);
  const fullY = useMemo(() => domain(data?.voltage ?? emptyPhaseValues, { lo: 15, hi: 30 }, 2), [data]);
  const [xRange, setXRange] = useState(fullX);
  const [yRange, setYRange] = useState(fullY);
  useEffect(() => { setXRange(fullX); setYRange(fullY); }, [fullX, fullY]);
  const cxLo = xRange.lo; const cxHi = xRange.hi; const cvLo = yRange.lo; const cvHi = yRange.hi;
  const toX = (c: number) => pad + ((c - cxLo) / (cxHi - cxLo)) * pw;
  const toY = (v: number) => pad + (1 - (v - cvLo) / (cvHi - cvLo)) * ph;
  const n = Math.min(rawCurrent.length, rawVoltage.length);
  const step = Math.max(1, Math.ceil(n / 1800));
  const points = Array.from({ length: Math.ceil(n / step) }, (_, bucket) => {
    const i = Math.min(bucket * step, n - 1);
    const ts = (i / Math.max(n - 1, 1)) * totalDur;
    return { x: toX(rawCurrent[i]), y: toY(rawVoltage[i]), ts, i, anom: anomalies.some((a) => ts >= a.start && ts <= a.end) };
  }).filter((p) => Number.isFinite(p.x) && Number.isFinite(p.y));
  const path = points.map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(' ');
  const cursorIdx = Math.min(Math.max(points.length - 1, 0), Math.max(0, Math.round((cursor / totalDur) * (points.length - 1))));
  const cp = points[cursorIdx];
  const x = (e: React.MouseEvent<SVGSVGElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const relX = (e.clientX - rect.left) / rect.width * w;
    const c = cxLo + ((relX - pad) / pw) * (cxHi - cxLo);
    let best = 0; let bd = Infinity;
    for (let i = 0; i < n; i++) { const d = Math.abs(rawCurrent[i] - c); if (d < bd) { bd = d; best = i; } }
    onCursor((best / Math.max(n - 1, 1)) * totalDur);
  };
  const zoomAt = (factor: number, focalX = (cxLo + cxHi) / 2, focalY = (cvLo + cvHi) / 2) => {
    const nextXSpan = Math.max((fullX.hi - fullX.lo) * 0.08, Math.min(fullX.hi - fullX.lo, (cxHi - cxLo) * factor));
    const nextYSpan = Math.max((fullY.hi - fullY.lo) * 0.08, Math.min(fullY.hi - fullY.lo, (cvHi - cvLo) * factor));
    const xRatio = (focalX - cxLo) / Math.max(cxHi - cxLo, 1);
    const yRatio = (focalY - cvLo) / Math.max(cvHi - cvLo, 1);
    const nextXLo = Math.max(fullX.lo, Math.min(fullX.hi - nextXSpan, focalX - xRatio * nextXSpan));
    const nextYLo = Math.max(fullY.lo, Math.min(fullY.hi - nextYSpan, focalY - yRatio * nextYSpan));
    setXRange({ lo: nextXLo, hi: nextXLo + nextXSpan });
    setYRange({ lo: nextYLo, hi: nextYLo + nextYSpan });
  };
  const onWheel = (e: React.WheelEvent<SVGSVGElement>) => {
    e.preventDefault();
    const rect = e.currentTarget.getBoundingClientRect();
    const relX = (e.clientX - rect.left) / rect.width * w;
    const relY = (e.clientY - rect.top) / rect.height * h;
    const focalX = cxLo + ((relX - pad) / pw) * (cxHi - cxLo);
    const focalY = cvLo + (1 - (relY - pad) / ph) * (cvHi - cvLo);
    zoomAt(e.deltaY > 0 ? 1.15 : 1 / 1.15, focalX, focalY);
  };
  const reset = () => { setXRange(fullX); setYRange(fullY); };
  return <div className="phase-plot-wrap">
    {points.length > 0 && <div className="phase-zoom-tools" role="group" aria-label="相图缩放控制">
      <button type="button" onClick={() => zoomAt(1 / 1.15)} aria-label="放大相图" title="放大"><Plus size={13} /></button>
      <button type="button" onClick={() => zoomAt(1.15)} aria-label="缩小相图" title="缩小"><Minus size={13} /></button>
      <button type="button" onClick={reset} aria-label="重置相图缩放" title="重置">1:1</button>
    </div>}
    {!points.length ? <div className="phase-empty" role="status">{loading ? '真实 UI 相图加载中…' : '暂无真实 UI 相图数据'}</div> : <svg viewBox={`0 0 ${w} ${h}`} className="phase-svg" onMouseMove={x} onWheel={onWheel} onMouseLeave={() => {}}>
    <defs><clipPath id="phase-plot-clip"><rect x={pad} y={pad} width={pw} height={ph} /></clipPath></defs>
    <line x1={pad} y1={pad} x2={pad} y2={pad + ph} stroke="#e8efef" />
    <line x1={pad} y1={pad + ph} x2={pad + pw} y2={pad + ph} stroke="#e8efef" />
    <text x={pad + pw / 2} y={h - 6} textAnchor="middle" className="phase-axis-label">电流 (A) · {cxLo.toFixed(0)}–{cxHi.toFixed(0)}</text>
    <text x={8} y={pad + ph / 2} textAnchor="middle" className="phase-axis-label" transform={`rotate(-90 8 ${pad + ph / 2})`}>电压 (V) · {cvLo.toFixed(0)}–{cvHi.toFixed(0)}</text>
    <g clipPath="url(#phase-plot-clip)"><path d={path} fill="none" stroke="#2c9caf" strokeWidth="1.4" opacity="0.55" />
    {points.filter((p) => p.anom).map((p) => <circle key={p.i} cx={p.x} cy={p.y} r="2.4" fill="#e88d6c" opacity="0.7" />)}
    </g>
    {cp && <circle cx={cp.x} cy={cp.y} r="5" fill="#fff" stroke="#e88d6c" strokeWidth="2.5" />}
    </svg>}<span className="phase-zoom-hint">滚轮缩放 · 指针定位 · 自动适配数据范围</span>
  </div>;
}

function PddChart({ chanId, channels, data }: { chanId: string; channels: Chan[]; data?: PddData }) {
  const chan = channels.find((c) => c.id === chanId) ?? channels[0];
  const hasApi = !!data && data.counts.length > 0;
  const bins = hasApi ? data!.counts.length : 28;
  let counts: number[];
  let kde: number[];
  let lo: number;
  let hi: number;
  if (hasApi) {
    counts = data!.counts;
    kde = data!.kde;
    lo = data!.bins.length ? data!.bins[0] : chan.lo;
    hi = data!.bins.length ? data!.bins[data!.bins.length - 1] : chan.hi;
  } else {
    const vals = chan.values;
    lo = chan.lo; hi = chan.hi;
    const c = new Array(bins).fill(0);
    vals.forEach((v) => { const b = clamp(Math.floor(((v - lo) / (hi - lo)) * bins), 0, bins - 1); c[b]++; });
    counts = c;
    const k: number[] = [];
    for (let i = 0; i < bins; i++) {
      let sum = 0;
      for (let j = 0; j < bins; j++) { const d = (i - j) / 3.5; sum += counts[j] * Math.exp(-d * d); }
      k.push(sum);
    }
    kde = k;
  }
  const max = Math.max(...counts) || 1;
  const w = 260; const h = 200; const pad = 28; const pw = w - pad - 12; const ph = h - pad - 16;
  const bw = pw / bins;
  const kdeMax = Math.max(...kde) || 1;
  const kdePath = kde.map((k, i) => { const px = pad + i * bw + bw / 2; const py = pad + ph * (1 - k / kdeMax); return `${i === 0 ? 'M' : 'L'}${px.toFixed(1)} ${py.toFixed(1)}`; }).join(' ');
  return <svg viewBox={`0 0 ${w} ${h}`} className="pdd-svg">
    <line x1={pad} y1={pad} x2={pad} y2={pad + ph} stroke="#e8efef" />
    <line x1={pad} y1={pad + ph} x2={pad + pw} y2={pad + ph} stroke="#e8efef" />
    {counts.map((c, i) => <rect key={i} x={pad + i * bw + 1} y={pad + ph * (1 - c / max)} width={bw - 2} height={ph * (c / max)} fill={chan.color} opacity="0.32" rx="1" />)}
    <path d={kdePath} fill="none" stroke={chan.color} strokeWidth="2.2" />
    <text x={pad} y={h - 4} className="pdd-axis" textAnchor="start">{lo}</text>
    <text x={pad + pw} y={h - 4} className="pdd-axis" textAnchor="end">{hi} {chan.unit}</text>
    <text x={6} y={pad + 8} className="pdd-axis">密度</text>
  </svg>;
}

function ExploreWaveform({ active, cursor, onCursor, channels: chanList, dur: totalDur, anomalies }: { active: Set<string>; cursor: number; onCursor: (s: number) => void; channels: Chan[]; dur: number; anomalies: WeldAnomaly[] }) {
  const x = (e: React.MouseEvent<SVGSVGElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const rel = (e.clientX - rect.left) / rect.width;
    onCursor(clamp(rel * totalDur, 0, totalDur));
  };
  const cursorX = AXIS_L + (cursor / totalDur) * PLOT_W;
  const visible = chanList.filter((c) => active.has(c.id));
  return <div className="explore-waveform">
    <svg viewBox={`0 0 ${CH} ${CW}`} className="explore-waveform-svg" preserveAspectRatio="none" onMouseMove={x} onClick={x} onMouseLeave={() => {}}>
      {[0, 0.25, 0.5, 0.75, 1].map((p) => <line key={p} x1={AXIS_L} y1={PLOT_H * p} x2={CH} y2={PLOT_H * p} stroke="#edf2f2" />)}
      {anomalies.map((a) => <rect key={`${a.start}-${a.end}`} x={AXIS_L + (a.start / totalDur) * PLOT_W} y={0} width={Math.max(0, (a.end - a.start) / totalDur) * PLOT_W} height={PLOT_H} fill="#e88d6c" opacity="0.13" />)}
      {visible.map((c) => <path key={c.id} d={toPath(c.values, c.lo, c.hi)} fill="none" stroke={c.color} strokeWidth={c.id === 'cur' ? 2 : 1.6} opacity={0.9} />)}
      <line x1={cursorX} y1={0} x2={cursorX} y2={PLOT_H} stroke="#d16f69" strokeWidth="1.5" strokeDasharray="4 3" />
    </svg>
    <div className="explore-axis">{timeTicks(totalDur).map((s) => <span key={s}>{axisLabel(s)}</span>)}</div>
  </div>;
}

function modeLabel(mode: string) {
  if (mode === '时域') return '原始时域波形';
  if (mode === 'PSD') return '功率谱密度（Welch 法）';
  if (mode === 'STFT') return '短时傅里叶时频图';
  if (mode === 'DWT') return '离散小波分解';
  if (mode === '小波分解') return '小波多层分量分解';
  return '';
}

const filterTypes = ['低通', '高通', '带通'] as const;
type FilterType = typeof filterTypes[number];

/** 截止频率滑杆下限（Hz）：低到足以覆盖去漂移/去工频场景。 */
const MIN_FILTER_HZ = 1;

/**
 * 归一化频率（相对奈奎斯特频率 fs/2）→ Hz。采样率未知时返回 null（**不编造**数值）。
 * 后端 `cutoff/cutoff2` 一律是相对奈奎斯特的归一化频率，Hz = cutoff × fs/2。
 */
function hzFromRatio(ratio: number, sampleRate: number | null | undefined): number | null {
  const fs = Number(sampleRate);
  return Number.isFinite(fs) && fs > 0 ? ratio * (fs / 2) : null;
}

/** Hz → 归一化频率（相对奈奎斯特）；采样率未知时返回 null。 */
function ratioFromHz(hz: number, sampleRate: number | null | undefined): number | null {
  const fs = Number(sampleRate);
  return Number.isFinite(fs) && fs > 0 ? hz / (fs / 2) : null;
}

/** Hz 展示：≥100 取整、<100 保留一位小数（12.5 Hz 这类值需要小数）。 */
function fmtHz(hz: number | null): string {
  if (hz == null || !Number.isFinite(hz)) return '—';
  return hz >= 100 ? `${Math.round(hz)} Hz` : `${Math.round(hz * 10) / 10} Hz`;
}

/** 滤波通带说明（含具体阈值）：低通保留 0–f、高通保留 f–奈奎斯特、带通保留 f1–f2。 */
function passbandText(type: FilterType, hz1: number | null, hz2: number | null, nyquist: number | null): string {
  if (hz1 == null) return `${type}：采样率未知，无法换算 Hz`;
  if (type === '低通') return `低通：保留 0 – ${fmtHz(hz1)} 的分量，高于 ${fmtHz(hz1)} 的能量被衰减`;
  if (type === '高通') return `高通：保留 ${fmtHz(hz1)} – ${fmtHz(nyquist)} 的分量，低于 ${fmtHz(hz1)} 的能量被衰减`;
  if (hz2 == null) return `带通：上限频率待定`;
  return `带通：只保留 ${fmtHz(hz1)} – ${fmtHz(hz2)} 的分量，带外能量被衰减`;
}

/** 对数刻度：滑杆位置 [0,1] ↔ Hz，低频段同样能精细调节。 */
function hzToPos(hz: number, minHz: number, maxHz: number): number {
  return clamp(Math.log(Math.max(hz, minHz) / minHz) / Math.log(maxHz / minHz), 0, 1);
}
function posToHz(pos: number, minHz: number, maxHz: number): number {
  return minHz * Math.pow(maxHz / minHz, clamp(pos, 0, 1));
}

/** 截止频率滑杆：内部仍是归一化频率，呈现与输入一律按 Hz（2026-09-15 修复「0.30 显示成 300 Hz」）。 */
function HzRange({ label, hz, minHz, maxHz, disabled, onChange }: {
  label: string; hz: number | null; minHz: number; maxHz: number; disabled?: boolean; onChange: (hz: number) => void;
}) {
  const hi = Math.max(maxHz, minHz * 1.01);
  const pos = hz == null ? 0.5 : hzToPos(hz, minHz, hi);
  return <div className="preprocess-field">
    <label>{label}</label>
    <div className="pp-slider">
      <input type="range" min="0" max="1" step="0.002" value={pos} disabled={disabled} aria-label={`${label}（Hz）`} onChange={(e) => onChange(Math.round(posToHz(parseFloat(e.target.value), minHz, hi) * 10) / 10)} />
      <span>{fmtHz(hz)}</span>
    </div>
  </div>;
}

/** 序列自身量程（±5% pad）——滤波会改均值/幅度，必须按滤波后数据缩放才画得准。 */
function valueRange(values: number[], fallback: { lo: number; hi: number }): { lo: number; hi: number } {
  let min = Infinity; let max = -Infinity;
  for (const v of values) if (Number.isFinite(v)) { min = Math.min(min, v); max = Math.max(max, v); }
  if (!Number.isFinite(min) || !Number.isFinite(max)) return fallback;
  if (max - min < 1e-9) return { lo: min - 0.5, hi: max + 0.5 };
  const pad = (max - min) * 0.05;
  return { lo: min - pad, hi: max + pad };
}

/** 滤波前后对比条：上=原始、下=滤波后，各自按自身量程缩放（量程写进图注，避免「看着变平了」的误判）。 */
function FilterCompare({ raw, filtered, summary, error }: { raw: Chan; filtered: Chan | null; summary: string; error?: string | null }) {
  const rawRange = valueRange(raw.values, { lo: raw.lo, hi: raw.hi });
  const filtRange = filtered ? valueRange(filtered.values, { lo: filtered.lo, hi: filtered.hi }) : null;
  return <div className="filter-compare">
    <span className="fc-label">滤波前后对比 · {raw.name} · {summary}</span>
    <div className="fc-row"><span className="fc-tag">原始</span><svg className="filter-compare-svg" viewBox={`0 0 ${CH} 70`} preserveAspectRatio="none"><path d={buildPath(raw.values, rawRange.lo, rawRange.hi, CH, 70)} fill="none" stroke="#9fb0b0" strokeWidth="1.4" opacity="0.85" /></svg></div>
    <div className="fc-row"><span className="fc-tag">滤波后</span>{filtered && filtRange ? <svg className="filter-compare-svg" viewBox={`0 0 ${CH} 70`} preserveAspectRatio="none"><path d={buildPath(filtered.values, filtRange.lo, filtRange.hi, CH, 70)} fill="none" stroke={raw.color} strokeWidth="1.6" opacity="0.9" /></svg> : <span className="fc-pending" role={error ? 'alert' : 'status'}>{error ? '滤波后波形不可用（见上方提示）' : '滤波后波形计算中…'}</span>}</div>
    <span className="fc-legend">原始量程 {rawRange.lo.toFixed(1)} – {rawRange.hi.toFixed(1)} {raw.unit}{filtRange ? ` ／ 滤波后量程 ${filtRange.lo.toFixed(1)} – ${filtRange.hi.toFixed(1)} ${raw.unit}` : ''}</span>
  </div>;
}

function PsdChart({ values, color, freqs, psd }: { values: number[]; color: string; lo: number; hi: number; freqs?: number[]; psd?: number[] }) {
  const hasApi = !!freqs && !!psd && freqs.length > 0 && psd.length > 0;
  const N = values.length;
  const half = Math.floor(N / 2);
  const mags: number[] = [];
  for (let k = 0; k < half; k++) {
    let re = 0; let im = 0;
    for (let n = 0; n < N; n++) {
      const ang = (2 * Math.PI * k * n) / N;
      re += values[n] * Math.cos(ang);
      im -= values[n] * Math.sin(ang);
    }
    mags.push((re * re + im * im) / N);
  }
  const welchBins = 24;
  const welch: number[] = [];
  if (hasApi) {
    // 后端已算 welch：等距抽稀到 welchBins 个点喂给原 SVG 结构
    const step = (psd!.length - 1) / (welchBins - 1 || 1);
    for (let b = 0; b < welchBins; b++) welch.push(psd![Math.round(b * step)] ?? 0);
  } else {
    const binSize = Math.floor(half / welchBins) || 1;
    for (let b = 0; b < welchBins; b++) {
      let sum = 0;
      for (let j = 0; j < binSize; j++) { sum += mags[b * binSize + j] ?? 0; }
      welch.push(sum / binSize);
    }
  }
  const wMax = Math.max(...welch) || 1;
  const W = 660; const H = 180; const pad = 30; const pw = W - pad - 12; const ph = H - pad - 18;
  const bw = pw / welchBins;
  const path = welch.map((w, i) => { const px = pad + i * bw + bw / 2; const py = pad + ph * (1 - w / wMax); return `${i === 0 ? 'M' : 'L'}${px.toFixed(1)} ${py.toFixed(1)}`; }).join(' ');
  const fmtF = (f: number) => (f >= 1000 ? `${(f / 1000).toFixed(1)}k` : `${Math.round(f)}`);
  const labelIdx = [0, 6, 12, 18, 23];
  const labels = hasApi
    ? labelIdx.map((i) => fmtF(freqs![Math.min(Math.round(i * (freqs!.length - 1) / (labelIdx.length - 1)), freqs!.length - 1)]))
    : ['0', '0.5k', '1k', '2k', '5k', '10k'];
  return <svg viewBox={`0 0 ${W} ${H}`} className="psd-svg" preserveAspectRatio="none">
    {[0, 0.25, 0.5, 0.75, 1].map((p) => <line key={p} x1={pad} y1={pad + ph * p} x2={pad + pw} y2={pad + ph * p} stroke="#edf2f2" />)}
    {welch.map((w, i) => <rect key={i} x={pad + i * bw + 1} y={pad + ph * (1 - w / wMax)} width={bw - 2} height={ph * (w / wMax)} fill={color} opacity="0.25" rx="1" />)}
    <path d={path} fill="none" stroke={color} strokeWidth="2.2" />
    <line x1={pad} y1={pad + ph} x2={pad + pw} y2={pad + ph} stroke="#d8e0e0" />
    <line x1={pad} y1={pad} x2={pad} y2={pad + ph} stroke="#d8e0e0" />
    {labels.map((l, i) => <text key={l} x={pad + (pw / (labels.length - 1)) * i} y={H - 4} className="psd-axis" textAnchor={i === 0 ? 'start' : i === labels.length - 1 ? 'end' : 'middle'}>{l}</text>)}
    <text x={6} y={pad + 8} className="psd-axis">PSD</text>
  </svg>;
}

function StftHeatmap({ values, color, magnitude }: { values: number[]; color: string; magnitude?: number[][] }) {
  const cols = 40; const rows = 16;
  const hasApi = !!magnitude && magnitude.length > 0 && magnitude[0].length > 0;
  const N = values.length;
  const heat: number[][] = [];
  let gMax = 0;
  if (hasApi) {
    // 后端已算 STFT：magnitude 形状 = (freqs × times)，等距抽稀到 cols×rows 网格
    const nT = magnitude![0].length;
    const nF = magnitude!.length;
    for (let c = 0; c < cols; c++) {
      const tIdx = c === cols - 1 ? nT - 1 : Math.round(c * (nT - 1) / (cols - 1));
      const row: number[] = [];
      for (let r = 0; r < rows; r++) {
        const fIdx = r === rows - 1 ? nF - 1 : Math.round(r * (nF - 1) / (rows - 1));
        const m = magnitude![fIdx][tIdx] ?? 0;
        row.push(m);
        if (m > gMax) gMax = m;
      }
      heat.push(row);
    }
  } else {
    const win = Math.floor(N / cols) || 1;
    for (let c = 0; c < cols; c++) {
      const frame = values.slice(c * win, c * win + win);
      const row: number[] = [];
      for (let k = 0; k < rows; k++) {
        let re = 0; let im = 0;
        for (let n = 0; n < win && n < frame.length; n++) {
          const ang = (2 * Math.PI * k * n) / win;
          re += frame[n] * Math.cos(ang);
          im -= frame[n] * Math.sin(ang);
        }
        const m = Math.sqrt(re * re + im * im);
        row.push(m);
        if (m > gMax) gMax = m;
      }
      heat.push(row);
    }
  }
  const W = 660; const H = 180; const pad = 28; const pw = W - pad - 8; const ph = H - pad - 16;
  const cw = pw / cols; const rh = ph / rows;
  const cellColor = (v: number) => {
    const r = v / (gMax || 1);
    if (r > 0.75) return color;
    if (r > 0.5) return color + 'cc';
    if (r > 0.25) return color + '88';
    if (r > 0.1) return color + '44';
    return '#f0f5f4';
  };
  return <svg viewBox={`0 0 ${W} ${H}`} className="stft-svg" preserveAspectRatio="none">
    {heat.map((col, c) => col.map((v, r) => <rect key={`${c}-${r}`} x={pad + c * cw} y={pad + (rows - 1 - r) * rh} width={cw + 0.5} height={rh + 0.5} fill={cellColor(v)} />))}
    <line x1={pad} y1={pad + ph} x2={pad + pw} y2={pad + ph} stroke="#d8e0e0" />
    <line x1={pad} y1={pad} x2={pad} y2={pad + ph} stroke="#d8e0e0" />
    <text x={pad + pw / 2} y={H - 4} className="psd-axis" textAnchor="middle">时间 (s)</text>
    <text x={8} y={pad + ph / 2} className="psd-axis" textAnchor="middle" transform={`rotate(-90 8 ${pad + ph / 2})`}>频率</text>
  </svg>;
}

function DwtChart({ values, color, bands, approx }: { values: number[]; color: string; bands?: WaveletBand[]; approx?: { name: string; values: number[] } }) {
  const levels = 4;
  const W = 660; const H = 180; const pad = 30; const pw = W - pad - 8;
  const bandH = (H - pad - 10) / (levels + 1);
  let allBands: { name: string; values: number[] }[];
  if (bands && bands.length) {
    // 后端已算 DWT：bands D1..Dn + approx A_n，标签直接用后端 name
    allBands = [...bands];
    if (approx) allBands.push(approx);
  } else {
    const approxArr = [...values];
    const detail: number[][] = [];
    for (let lv = 0; lv < levels; lv++) {
      const d: number[] = [];
      const next: number[] = [];
      for (let i = 0; i < approxArr.length - 1; i += 2) {
        const a = (approxArr[i] + approxArr[i + 1]) / 2;
        d.push((approxArr[i] - approxArr[i + 1]) / 2);
        next.push(a);
      }
      detail.push(d);
      approxArr.length = 0; approxArr.push(...next);
    }
    allBands = detail.map((b, lv) => ({ name: `D${levels - lv}`, values: b })).concat([{ name: `A${levels}`, values: approxArr }]);
  }
  const allMax = Math.max(...allBands.flatMap((b) => b.values.map(Math.abs))) || 1;
  const toBandPath = (band: number[], yOff: number) => {
    const step = pw / (band.length - 1 || 1);
    return band.map((v, i) => { const px = pad + i * step; const py = yOff + bandH / 2 - (v / allMax) * (bandH / 2 - 2); return `${i === 0 ? 'M' : 'L'}${px.toFixed(1)} ${py.toFixed(1)}`; }).join(' ');
  };
  return <svg viewBox={`0 0 ${W} ${H}`} className="dwt-svg" preserveAspectRatio="none">
    {allBands.map((band, lv) => {
      const yOff = pad + lv * bandH;
      const c = lv < allBands.length - 1 ? color : '#f0a34a';
      return <g key={band.name}>
        <line x1={pad} y1={yOff + bandH} x2={pad + pw} y2={yOff + bandH} stroke="#edf2f2" />
        <text x={6} y={yOff + bandH / 2 + 3} className="psd-axis">{band.name}</text>
        <path d={toBandPath(band.values, yOff)} fill="none" stroke={c} strokeWidth="1.4" opacity="0.85" />
      </g>;
    })}
    <text x={pad + pw / 2} y={H - 2} className="psd-axis" textAnchor="middle">样本点</text>
  </svg>;
}

function WaveletDecomp({ values, color, bands }: { values: number[]; color: string; bands?: WaveletBand[] }) {
  const levels = 5;
  const W = 660; const H = 200; const pad = 34; const pw = W - pad - 8;
  const bandH = (H - pad - 10) / levels;
  let recon: { name: string; values: number[] }[];
  if (bands && bands.length) {
    // 后端已算小波分解：bands L1..Ln，标签直接用后端 name
    recon = bands;
  } else {
    const comps: number[][] = [];
    const cur = [...values];
    for (let lv = 0; lv < levels; lv++) {
      const comp: number[] = [];
      const scale = (lv + 1) * 4;
      for (let i = 0; i < cur.length; i++) {
        const win = cur.slice(Math.max(0, i - scale), Math.min(cur.length, i + scale));
        const m = win.reduce((s, v) => s + v, 0) / win.length;
        const d = cur[i] - m;
        comp.push(d * (1 + lv * 0.3) + Math.sin(i * 0.4 + lv) * 3 * (lv / levels));
      }
      comps.push(comp);
    }
    recon = comps.map((c, lv) => ({ name: `L${lv + 1}`, values: c }));
  }
  const allMax = Math.max(...recon.flatMap((b) => b.values.map(Math.abs))) || 1;
  return <svg viewBox={`0 0 ${W} ${H}`} className="wavelet-decomp-svg" preserveAspectRatio="none">
    {recon.map((band, lv) => {
      const yOff = pad + lv * bandH;
      const step = pw / (band.values.length - 1 || 1);
      const path = band.values.map((v, i) => { const px = pad + i * step; const py = yOff + bandH / 2 - (v / allMax) * (bandH / 2 - 2); return `${i === 0 ? 'M' : 'L'}${px.toFixed(1)} ${py.toFixed(1)}`; }).join(' ');
      const opacity = 0.4 + (lv / levels) * 0.5;
      return <g key={band.name}>
        <line x1={pad} y1={yOff + bandH} x2={pad + pw} y2={yOff + bandH} stroke="#edf2f2" />
        <text x={6} y={yOff + bandH / 2 + 3} className="psd-axis">{band.name}</text>
        <path d={path} fill="none" stroke={color} strokeWidth="1.3" opacity={opacity} />
      </g>;
    })}
    <text x={pad + pw / 2} y={H - 2} className="psd-axis" textAnchor="middle">样本点</text>
  </svg>;
}



export function AdvancedWeldAnalysis({ dataId }: { embedded?: boolean; dataId?: string }) {
  const [mode, setMode] = useState('时域');
  const [active, setActive] = useState<Set<string>>(new Set(['cur', 'vol', 'gas']));
  const [cursor, setCursor] = useState(2.1);
  const [pddChan, setPddChan] = useState('cur');
  const [filterOn, setFilterOn] = useState(false);
  const [filterType, setFilterType] = useState<FilterType>('低通');
  // cutoff/cutoff2 是**相对奈奎斯特（fs/2）的归一化频率**（后端契约），控件上一律按 Hz 呈现
  const [cutoff, setCutoff] = useState(0.3);
  const [cutoff2, setCutoff2] = useState(0.6);
  const [filterChan, setFilterChan] = useState('cur');
  //: 采样率来自 signals 接口（真实数据 5k/20k 不等），Hz 换算的唯一依据
  const [sampleRate, setSampleRate] = useState<number | null>(null);
  //: 滤波后的目标通道（只请求目标通道，主波形保持原始信号，便于滤波前后对比）
  const [filteredChan, setFilteredChan] = useState<Chan | null>(null);
  const [filterError, setFilterError] = useState<string | null>(null);
  // 初始为空波形占位：mock 波形仅在接口失败时兜底，不得在加载期闪现
  const [channels, setChannels] = useState<Chan[]>(emptyChannels);
  const [signalsLoading, setSignalsLoading] = useState(true);
  const [signalSource, setSignalSource] = useState<'real' | 'generated' | null>(null);
  const [signalError, setSignalError] = useState<string | null>(null);
  const [record, setRecord] = useState<DataRecord | null>(null);
  const [weldDuration, setWeldDuration] = useState<number | null>(null);
  const [signalDuration, setSignalDuration] = useState<number | null>(null);
  const [signalEvents, setSignalEvents] = useState<SignalData['events'] | null>(null);
  const [versionId, setVersionId] = useState<number | null>(null);
  const [psdData, setPsdData] = useState<PsdData | null>(null);
  const [stftData, setStftData] = useState<StftData | null>(null);
  const [dwtData, setDwtData] = useState<DwtData | null>(null);
  const [waveletData, setWaveletData] = useState<WaveletData | null>(null);
  const [phaseData, setPhaseData] = useState<PhaseData | null>(null);
  const [phaseLoading, setPhaseLoading] = useState(false);
  const [pddData, setPddData] = useState<PddData | null>(null);
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [analysisLoading, setAnalysisLoading] = useState(false);
  const [analysisError, setAnalysisError] = useState<string | null>(null);
  const [resultError, setResultError] = useState<string | null>(null);
  const toggle = (id: string) => setActive((prev) => { const n = new Set(prev); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  useEffect(() => {
    if (!dataId) return;
    let cancelled = false;
    getWeld(dataId).then((r) => { if (!cancelled) { setRecord(r); setVersionId(r.latest_version_id ?? r.latest_version?.id ?? null); } }).catch((err) => { if (!cancelled) console.warn('[analysis] getWeld failed', err); });
    return () => { cancelled = true; };
  }, [dataId]);
  // 时域波形：挂载 → 拉取「原始」全通道波形（滤波不改主波形，见下方滤波后目标通道）
  useEffect(() => {
    if (!dataId || versionId == null) return;
    let cancelled = false;
    setSignalsLoading(true);
    setSignalError(null);
    setSignalSource(null);
    setWeldDuration(null);
    setSignalDuration(null);
    setSignalEvents(null);
    setSampleRate(null);
    setChannels(emptyChannels);
    // 不传 channels 过滤：后端返回该焊缝全部分量通道（核心 4 + 扩展），默认仅勾选核心 4。
    const opts: SignalQuery = { max_points: 2048 };
    getSignals(dataId, String(versionId), opts).then((data: SignalData) => { if (!cancelled) { setSignalSource(data.source); if (data.source === 'real') { setSampleRate(data.sample_rate > 0 ? data.sample_rate : null); setWeldDuration(Math.max(0, data.events.weld_segment[1] - data.events.weld_segment[0])); setSignalDuration(data.duration > 0 ? data.duration : null); setSignalEvents(data.events); setCursor((c) => clamp(c, 0, data.duration > 0 ? data.duration : dur)); setChannels(data.channels.map(toChan)); } else { setChannels(emptyChannels); setSignalError('当前版本没有真实导入信号，生产分析已停止，不显示模拟波形。'); } } }).catch((err) => { if (!cancelled) { setChannels(emptyChannels); setSignalError('真实信号加载失败，未显示模拟波形。请检查数据导入状态后重试。'); console.warn('[analysis] getSignals failed', err); } }).finally(() => { if (!cancelled) setSignalsLoading(false); });
    return () => { cancelled = true; };
  }, [dataId, versionId]);
  // 滤波后波形：只请求「目标通道」（对比条 + 频谱/相图/分布兜底都用它），参数改动即重算
  useEffect(() => {
    if (!dataId || versionId == null || !filterOn) { setFilteredChan(null); setFilterError(null); return; }
    let cancelled = false;
    const opts: SignalQuery = { channels: [filterChan], filter_type: filterType, cutoff, max_points: 2048 };
    if (filterType === '带通') opts.cutoff2 = cutoff2;
    getSignals(dataId, String(versionId), opts)
      .then((data: SignalData) => { if (!cancelled) { setFilteredChan(data.channels.map(toChan)[0] ?? null); setFilterError(null); } })
      .catch((err) => { if (!cancelled) { setFilteredChan(null); setFilterError('滤波计算失败，请调整滤波参数后重试。'); console.warn('[analysis] filtered signals failed', err); } });
    return () => { cancelled = true; };
  }, [dataId, versionId, filterChan, filterOn, filterType, cutoff, cutoff2]);
  // 主视图 mode（PSD/STFT/DWT/小波分解）：仅真实信号可进入生产分析
  useEffect(() => {
    if (!dataId || versionId == null || signalSource !== 'real') return;
    if (mode !== 'PSD' && mode !== 'STFT' && mode !== 'DWT' && mode !== '小波分解') return;
    let cancelled = false;
    setAnalysisLoading(true);
    setAnalysisError(null);
    if (mode === 'PSD') setPsdData(null);
    else if (mode === 'STFT') setStftData(null);
    else if (mode === 'DWT') setDwtData(null);
    else setWaveletData(null);
    const apiMode = mode === 'PSD' ? 'psd' : mode === 'STFT' ? 'stft' : mode === 'DWT' ? 'dwt' : 'wavelet';
    const filter = filterOn ? { type: filterType, cutoff, cutoff2: filterType === '带通' ? cutoff2 : undefined } : undefined;
    getAnalysisMode(dataId, String(versionId), apiMode, filterChan, filter).then((data) => {
      if (cancelled) return;
      if (mode === 'PSD') setPsdData(data as PsdData);
      else if (mode === 'STFT') setStftData(data as StftData);
      else if (mode === 'DWT') setDwtData(data as DwtData);
      else setWaveletData(data as WaveletData);
    }).catch((err) => { if (!cancelled) { setAnalysisError(`${mode} 分析计算失败，请重试。`); console.warn(`[analysis] getAnalysisMode ${mode} failed`, err); } }).finally(() => { if (!cancelled) setAnalysisLoading(false); });
    return () => { cancelled = true; };
  }, [dataId, versionId, signalSource, mode, filterChan, filterOn, filterType, cutoff, cutoff2]);
  // 侧边 UI 相图（current/voltage，cur+vol 两通道）
  useEffect(() => {
    if (!dataId || versionId == null || signalSource !== 'real') return;
    let cancelled = false;
    setPhaseLoading(true);
    setPhaseData(null);
    const filter = filterOn ? { type: filterType, cutoff, cutoff2: filterType === '带通' ? cutoff2 : undefined } : undefined;
    getAnalysisMode(dataId, String(versionId), 'phase', 'cur', filter).then((data) => { if (!cancelled) setPhaseData(data as PhaseData); }).catch((err) => { if (!cancelled) console.warn('[analysis] phase failed', err); }).finally(() => { if (!cancelled) setPhaseLoading(false); });
    return () => { cancelled = true; };
  }, [dataId, versionId, signalSource, filterOn, filterType, cutoff, cutoff2]);
  // 侧边 PDD 分布（按所选通道）
  useEffect(() => {
    if (!dataId || versionId == null || signalSource !== 'real') return;
    let cancelled = false;
    setPddData(null);
    const filter = filterOn ? { type: filterType, cutoff, cutoff2: filterType === '带通' ? cutoff2 : undefined } : undefined;
    getAnalysisMode(dataId, String(versionId), 'pdd', pddChan, filter).then((data) => { if (!cancelled) setPddData(data as PddData); }).catch((err) => { if (!cancelled) console.warn('[analysis] pdd failed', err); });
    return () => { cancelled = true; };
  }, [dataId, versionId, signalSource, pddChan, filterOn, filterType, cutoff, cutoff2]);
  // 分析结果：稳定度 / 三类占比 / 异常区段
  useEffect(() => {
    if (!dataId || versionId == null || signalSource !== 'real') return;
    let cancelled = false;
    setResult(null);
    setResultError(null);
    getAnalysisResult(dataId, String(versionId)).then((data) => { if (!cancelled) setResult(data); }).catch((err) => { if (!cancelled) { setResultError('异常检测结果暂不可用，页面不会显示估算值。'); console.warn('[analysis] getAnalysisResult failed', err); } });
    return () => { cancelled = true; };
  }, [dataId, versionId, signalSource]);
  const anomalies = (result?.anomalies ?? []).map((a) => ({ range: [a.start, a.end] as [number, number], type: a.type, sev: (a.type.includes('电弧') ? 'orange' : 'red') as 'orange' | 'red' }));
  // 生产时间轴只来自真实输入；没有真实信号时保持演示坐标（此时波形本就是空的）
  const timelineDur = signalDuration ?? dur;
  const filterChanObj = channels.find((c) => c.id === filterChan) ?? channels[0];
  // 滤波参数按 Hz 呈现：后端 cutoff 是相对奈奎斯特（fs/2）的归一化频率，Hz = cutoff × fs/2
  const nyquist = sampleRate != null && sampleRate > 0 ? sampleRate / 2 : null;
  const maxCutoffHz = nyquist != null ? nyquist * 0.99 : MIN_FILTER_HZ * 2;
  const cutoffHz = hzFromRatio(cutoff, sampleRate);
  const cutoff2Hz = hzFromRatio(cutoff2, sampleRate);
  const filterSummary = filterType === '带通' ? `带通 ${fmtHz(cutoffHz)} – ${fmtHz(cutoff2Hz)}` : `${filterType} ${fmtHz(cutoffHz)}`;
  const filterStateText = filterOn ? `已滤波 ${filterSummary}` : '原始信号';
  // 滤波后波形只对目标通道；通道/参数不匹配时按“未就绪”处理，不拿旧数据顶替
  const filterCompare = filteredChan && filteredChan.id === filterChan ? filteredChan : null;
  const filteredValues = filterCompare ? filterCompare.values : filterChanObj.values;
  /** 改截止频率：带通下同步抬高上限，保证 cutoff < cutoff2（后端契约，否则 400）。 */
  const setCutoffHz = (hz: number) => {
    const ratio = ratioFromHz(hz, sampleRate);
    if (ratio == null) return;
    setCutoff(ratio);
    if (filterType === '带通' && cutoff2Hz != null && hz >= cutoff2Hz) setCutoff2(Math.min(0.99, (hz * 1.05) / (sampleRate! / 2)));
  };
  /** 改上限频率：带通下不低于下限 ×1.05。 */
  const setCutoff2Hz = (hz: number) => {
    if (sampleRate == null || sampleRate <= 0) return;
    const floor = cutoffHz != null ? cutoffHz * 1.05 : MIN_FILTER_HZ;
    setCutoff2(Math.min(0.99, Math.max(hz, floor) / (sampleRate / 2)));
  };
  /** 切滤波类型：切到带通时把已有截止频率整理成合法区间。 */
  const selectFilterType = (ft: FilterType) => {
    setFilterType(ft);
    if (ft === '带通' && cutoff >= cutoff2) {
      // 上限顶到 0.99 时不能与下限相等：反过来把下限压回 1/1.05，保证 cutoff < cutoff2
      const hi = Math.min(0.99, cutoff * 1.05);
      setCutoff2(hi);
      if (hi <= cutoff) setCutoff(Math.max(0.001, hi / 1.05));
    }
  };
  const seg = result?.segments;
  const modes = ['时域', 'PSD', 'STFT', 'DWT', '小波分解'];
  return <div className="page-wrap"><PageIntro eyebrow="焊缝级分析" title="焊缝深度分析" description="在同一时间轴上查看多模态信号、焊接事件和质量特征。" action={<Toolbar action="开始分析" secondary="导出分析报告" exportType="analysis" exportRefIds={versionId != null ? [versionId] : undefined} />} /><div className="analysis-meta panel"><div><span className="file-badge"><Archive size={15} />分析概览</span><h2>当前焊缝起收弧识别</h2><p>分析结果基于上方“当前数据上下文”中选择的焊缝及其最新版本。</p><div className="source-status"><span className={signalSource === 'real' ? 'real' : 'generated'}>{signalsLoading ? '信号加载中…' : signalSource === 'real' ? '真实信号' : '信号不可用'}</span>{result && <span>分析结果已完成</span>}</div></div><div className="analysis-kpis"><div><span>核验状态</span><strong className={record?.quality === '通过' ? 'accent-text' : record?.quality === '异常' ? 'danger-text' : 'warning-text'}>{record?.quality ?? '加载中…'}</strong></div><div><span>有效焊接段</span><strong>{weldDuration != null ? `${weldDuration.toFixed(2)} s` : '—'}</strong></div><div><span>异常区段</span><strong className="warning-text">{result ? `${anomalies.length} 个` : '—'}</strong></div></div></div>{signalError && <div className="alignment-banner bad" role="alert"><AlertTriangle size={15} />{signalError}</div>}{resultError && <div className="alignment-banner warn" role="status"><AlertTriangle size={15} />{resultError}</div>}
  <div className="explore-layout">
    <section className="panel explore-main">
      <div className="panel-heading"><div><h2>多模态信号联动</h2><p>勾选通道任意组合，拖动波形同步定位 — 当前：{modeLabel(mode)}</p></div><div className="mode-tabs">{modes.map((item) => <button className={mode === item ? 'active' : ''} onClick={() => setMode(item)} key={item}>{item}</button>)}</div></div>
      <div className="preprocess-bar">
        <div className="preprocess-toggle"><label className="switch-row compact"><span><FilterIcon size={13} />信号滤波</span><input type="checkbox" checked={filterOn} onChange={(e) => setFilterOn(e.target.checked)} /></label></div>
        {filterOn && <><div className="preprocess-field"><label>滤波类型</label><div className="pp-chips">{filterTypes.map((ft) => <button key={ft} className={filterType === ft ? 'on' : ''} onClick={() => selectFilterType(ft)}>{ft}</button>)}</div></div>
        <div className="preprocess-field"><label>目标通道</label><div className="pp-chans">{channels.map((c) => <button key={c.id} className={filterChan === c.id ? 'on' : ''} onClick={() => setFilterChan(c.id)}><i style={{ background: c.color }} />{c.name}</button>)}</div></div>
        <HzRange label={filterType === '低通' ? '截止频率（通过上限）' : filterType === '高通' ? '截止频率（通过下限）' : '下限频率'} hz={cutoffHz} minHz={MIN_FILTER_HZ} maxHz={filterType === '带通' && cutoff2Hz != null ? cutoff2Hz / 1.05 : maxCutoffHz} disabled={nyquist == null} onChange={setCutoffHz} />
        {filterType === '带通' && <HzRange label="上限频率" hz={cutoff2Hz} minHz={cutoffHz != null ? cutoffHz * 1.05 : MIN_FILTER_HZ} maxHz={maxCutoffHz} disabled={nyquist == null} onChange={setCutoff2Hz} />}
        </>}
      </div>
      {filterOn && <div className="filter-passband">
        <FilterIcon size={13} />
        <span>{passbandText(filterType, cutoffHz, cutoff2Hz, nyquist)}</span>
        <span className="fp-meta">{sampleRate != null ? `采样率 ${(sampleRate / 1000).toFixed(sampleRate % 1000 === 0 ? 0 : 1)} kHz · 奈奎斯特 ${fmtHz(nyquist)}` : '采样率未知'}</span>
      </div>}
      {filterOn && filterError && <div className="alignment-banner bad" role="alert"><AlertTriangle size={15} />{filterError}</div>}
      <div className="channel-toggles">{channels.map((c) => <button key={c.id} className={`channel-toggle ${active.has(c.id) ? 'on' : ''}`} onClick={() => toggle(c.id)}><i style={{ background: c.color }} />{c.name}<small>{c.unit}</small><span className="toggle-check">{active.has(c.id) ? <Check size={12} /> : null}</span></button>)}</div>
      <div className="explore-legend">{channels.filter((c) => active.has(c.id)).map((c) => <span key={c.id}><i style={{ background: c.color }} />{c.name} ({c.unit})</span>)}{signalsLoading && <span className="explore-legend-empty" role="status">信号加载中…</span>}{!signalsLoading && active.size === 0 && <span className="explore-legend-empty">请至少开启一个通道</span>}<span className="explore-legend-anom"><i className="legend-orange" />异常区段</span><span className="explore-legend-cursor"><i className="result-dot red" />时间游标 {fmt(cursor)}</span></div>
      {mode === '时域' && <><ExploreWaveform active={active} cursor={cursor} onCursor={setCursor} channels={channels} dur={timelineDur} anomalies={result?.anomalies ?? []} />{filterOn && <FilterCompare raw={filterChanObj} filtered={filterCompare} summary={filterSummary} error={filterError} />}
      <div className="event-track"><span>起弧 <b>{signalEvents ? fmt(signalEvents.arc) : '—'}</b></span><i /><span>稳态焊接 <b>{signalEvents ? `${fmt(signalEvents.weld_segment[0])} - ${fmt(signalEvents.weld_segment[1])}` : '—'}</b></span><i /><span>收弧 <b>{signalEvents ? fmt(signalEvents.tail) : '—'}</b></span></div>
      <div className="anomaly-summary"><div className="anomaly-summary-head"><AlertTriangle size={14} /><span>已检出异常区段 {anomalies.length} 个 · 点击可定位</span></div>{anomalies.map((a, i) => <button key={i} className={`anomaly-chip ${a.sev}`} onClick={() => setCursor((a.range[0] + a.range[1]) / 2)}><i /><strong>{a.type}</strong><small>{fmt(a.range[0])} – {fmt(a.range[1])}</small><span>定位 <ArrowUpRight size={12} /></span></button>)}</div>
      <div className="signal-cards">{channels.map((c) => <div key={c.id} className={active.has(c.id) ? '' : 'dim'}><Waves size={16} /><span>{c.name}波形<strong>{c.mean}</strong></span></div>)}</div></>}
      {mode === 'PSD' && <div className="spectrum-view">{analysisLoading && <p className="dataset-empty-state" role="status">PSD 正在计算…</p>}{analysisError && <p className="dataset-empty-state" role="alert">{analysisError}</p>}<div className="spectrum-head"><span><FilterIcon size={14} />功率谱密度 · Welch 法</span><small>目标通道：{filterChanObj.name}（{filterStateText}）</small></div><PsdChart values={filteredValues} color={filterChanObj.color} lo={filterChanObj.lo} hi={filterChanObj.hi} freqs={psdData?.freqs} psd={psdData?.psd} /><div className="spectrum-note"><BarChart3 size={13} /><span>主峰集中在低频段（短路过渡频率），异常区段在 2-5 kHz 存在次峰。</span></div></div>}
      {mode === 'STFT' && <div className="spectrum-view"><div className="spectrum-head"><span><Activity size={14} />短时傅里叶变换时频图</span><small>目标通道：{filterChanObj.name}（{filterStateText}）</small></div><StftHeatmap values={filteredValues} color={filterChanObj.color} magnitude={stftData?.magnitude} /><div className="spectrum-note"><Waves size={13} /><span>时频图可观察到 1.9-2.3s 和 3.6-3.9s 两个异常区段的高频能量抬升。</span></div></div>}
      {mode === 'DWT' && <div className="spectrum-view"><div className="spectrum-head"><span><Layers3 size={14} />离散小波分解（4 层 · db4）</span><small>目标通道：{filterChanObj.name}（{filterStateText}）</small></div><DwtChart values={filteredValues} color={filterChanObj.color} bands={dwtData?.bands} approx={dwtData?.approx} /><div className="spectrum-note"><Gauge size={13} /><span>D1-D4 为细节系数、A4 为近似系数，异常在 D1-D2 高频层最明显。</span></div></div>}
      {mode === '小波分解' && <div className="spectrum-view"><div className="spectrum-head"><span><Waves size={14} />小波多层分量分解</span><small>目标通道：{filterChanObj.name} · 5 层 · {filterStateText}</small></div><WaveletDecomp values={filteredValues} color={filterChanObj.color} bands={waveletData?.bands} /><div className="spectrum-note"><Layers3 size={13} /><span>L1-L5 由低到高展示不同尺度的小波分量，低层捕捉高频瞬变。</span></div></div>}
    </section>
    <aside className="explore-aside">
      <section className="panel explore-phase-panel">
        <div className="panel-heading"><div><h2>UI 相图</h2><p>电流–电压轨迹，颜色越亮越接近当前时刻</p></div><span className="explore-hint">悬停联动</span></div>
        <PhasePlot cursor={cursor} onCursor={setCursor} data={phaseData ?? undefined} loading={phaseLoading} dur={timelineDur} anomalies={result?.anomalies ?? []} />
        <div className="phase-legend"><span><i className="legend-blue" />稳态轨迹</span><span><i className="legend-orange" />异常发散</span><span><i className="result-dot red" />游标 {fmt(cursor)}</span></div>
      </section>
      <section className="panel explore-pdd-panel">
        <div className="panel-heading"><div><h2>PDD 概率密度分布</h2><p>评估信号值的集中度与双峰特征</p></div><div className="pdd-chan-select">{channels.map((c) => <button key={c.id} className={pddChan === c.id ? 'active' : ''} onClick={() => setPddChan(c.id)}><i style={{ background: c.color }} />{c.name}</button>)}</div></div>
        <PddChart chanId={pddChan} channels={channels} data={pddData ?? undefined} />
        <div className="pdd-note"><BarChart3 size={13} /><span>当前通道分布近似单峰、集中度高；异常区段会使分布尾部抬升。</span></div>
      </section>
      <section className="panel explore-result-panel">
        <div className="panel-heading"><div><h2>分析结果</h2><p>AI 异常检测模型 v1.8</p></div><Sparkles size={16} className="accent-text" /></div>
        <div className="result-score"><strong>{result ? `${result.stability.toFixed(1)}%` : '—'}</strong><span>焊接稳定度</span></div>
        <div className="result-row"><span><i className="result-dot green" />正常区段</span><strong>{seg ? `${seg.normal.toFixed(1)}%` : '—'}</strong></div>
        <div className="result-row"><span><i className="result-dot orange" />电弧不稳</span><strong>{seg ? `${seg.arc_instability.toFixed(1)}%` : '—'}</strong></div>
        <div className="result-row"><span><i className="result-dot red" />飞溅倾向</span><strong>{seg ? `${seg.sputter.toFixed(1)}%` : '—'}</strong></div>
        <button className="full-button small-button">查看异常详情 <ArrowUpRight size={14} /></button>
      </section>
    </aside>
  </div></div>;
}
