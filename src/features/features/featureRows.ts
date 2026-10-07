/**
 * 特征展示行的共用映射（原在 `FeatureExtractionPage.tsx` 内，2026-10 抽出来给
 * 切片级工作台用——展示口径只此一份）。
 *
 * 按**结构形状**取数而不是绑定某个实体：版本级 42 维与切片级 36 维的
 * `ts_features` / `vision_features` / `unified_vector` 同构，映射自然复用。
 * **没有声音组**了：切片级没有真实音频源（见 `backend/app/services/sample_features.py`）。
 */
import type { UnifiedVector } from '../../api/types';

export type FeatureTableRow = { name: string; cur: string; vol: string; gas: string; wir: string };
export type VisionFeatureRow = { name: string; value: string; desc: string };
export type UnifiedFeatureRow = { group: string; dims: number; range: string; tone: string };

export const TS_ROWS: [string, string][] = [
  ['mean', '均值'], ['variance', '方差'], ['peak', '峰值'], ['skewness', '偏度'],
  ['kurtosis', '峰度'], ['rms', 'RMS'], ['fft_dominant_freq', 'FFT 主频'], ['wavelet_energy', '小波能量'],
];

export function mapTsRows(source: { ts_features?: Record<string, Record<string, number>> }) {
  const ts = source.ts_features ?? {};
  return TS_ROWS.map(([key, name]) => {
    const cell = (channel: string) => {
      const value = ts[channel]?.[key];
      if (value == null) return '—';
      return key === 'fft_dominant_freq' ? `${value.toFixed(1)} Hz` : String(Number(value.toFixed(2)));
    };
    return { name, cur: cell('cur'), vol: cell('vol'), gas: cell('gas'), wir: cell('wir') };
  });
}

export const VISION_ROWS: [string, string, string][] = [
  ['area', '熔池面积', 'px²'], ['perimeter', '熔池周长', 'px'], ['aspect_ratio', '长宽比', ''],
  ['circularity', '圆形度', ''], ['gray_mean', '灰度均值', ''], ['glcm_contrast', '纹理对比度', ''],
  ['glcm_energy', '纹理能量', ''], ['sobel_gradient', '边缘梯度', ''],
];

const VISION_DESC: Record<string, string> = {
  area: '分割掩膜像素统计', perimeter: '边缘轮廓长度', aspect_ratio: '外接矩形长/宽', circularity: '4πA/P²',
  gray_mean: '熔池区域平均灰度', glcm_contrast: 'GLCM 对比度', glcm_energy: 'GLCM 角二阶矩', sobel_gradient: 'Sobel 梯度均值',
};

export function mapVisionRows(source: { vision_features?: Record<string, number> }) {
  const vision = source.vision_features ?? {};
  return VISION_ROWS.map(([key, name, unit]) => {
    const value = vision[key];
    let text = '—';
    if (value != null) {
      text = `${key === 'area' ? Math.round(value).toLocaleString() : String(Number(value.toFixed(2)))}${unit ? ` ${unit}` : ''}`;
    }
    return { name, value: text, desc: VISION_DESC[key] ?? '' };
  });
}

export const unifiedPalette = ['#2c9caf', '#67cdb0', '#f0a34a', '#75add1', '#b89ac4', '#d4a05a'];

export function mapUnifiedGroups(unified: UnifiedVector | null | undefined) {
  return (unified?.groups ?? []).map((group, index) => ({
    group: group.name,
    dims: group.dims,
    range: `[${group.range[0]}:${group.range[1]}]`,
    tone: unifiedPalette[index % unifiedPalette.length],
  }));
}
