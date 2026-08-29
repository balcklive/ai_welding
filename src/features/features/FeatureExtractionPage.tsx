import { useEffect, useState } from 'react';
import { AlertTriangle, AudioWaveform, Boxes, Check, Database, Download, FileText, Image as ImageIcon, Sigma, Waves, Filter as FilterIcon } from 'lucide-react';
import {
  createFeatureExtractionTask, downloadFeatureExtraction, getFeatureExtraction,
  getLatestFeatureExtraction,
} from '../../api/analysis';
import { getWeld } from '../../api/welds';
import type { FeatureExtraction } from '../../api/types';
import { useJob } from '../../hooks/useJob';
import { PageIntro } from '../../shared/components/PageIntro';
import { Toolbar } from '../../shared/components/Toolbar';

type FeatureTableRow = { name: string; cur: string; vol: string; gas: string; wir: string };
type VisionFeatureRow = { name: string; value: string; desc: string };
type AudioFeatureRow = { name: string; value: string };
type UnifiedFeatureRow = { group: string; dims: number; range: string; tone: string };
const TS_ROWS: [string, string][] = [
  ['mean', '均值'], ['variance', '方差'], ['peak', '峰值'], ['skewness', '偏度'],
  ['kurtosis', '峰度'], ['rms', 'RMS'], ['fft_dominant_freq', 'FFT 主频'], ['wavelet_energy', '小波能量'],
];
function mapTsRows(res: FeatureExtraction) {
  const ts = res.ts_features ?? {};
  return TS_ROWS.map(([key, name]) => {
    const cell = (ch: string) => {
      const v = ts[ch]?.[key];
      if (v == null) return '—';
      return key === 'fft_dominant_freq' ? `${v.toFixed(1)} Hz` : String(Number(v.toFixed(2)));
    };
    return { name, cur: cell('cur'), vol: cell('vol'), gas: cell('gas'), wir: cell('wir') };
  });
}
const VISION_ROWS: [string, string, string][] = [
  ['area', '熔池面积', 'px²'], ['perimeter', '熔池周长', 'px'], ['aspect_ratio', '长宽比', ''],
  ['circularity', '圆形度', ''], ['gray_mean', '灰度均值', ''], ['glcm_contrast', '纹理对比度', ''],
  ['glcm_energy', '纹理能量', ''], ['sobel_gradient', '边缘梯度', ''],
];
const VISION_DESC: Record<string, string> = {
  area: '分割掩膜像素统计', perimeter: '边缘轮廓长度', aspect_ratio: '外接矩形长/宽', circularity: '4πA/P²',
  gray_mean: '熔池区域平均灰度', glcm_contrast: 'GLCM 对比度', glcm_energy: 'GLCM 角二阶矩', sobel_gradient: 'Sobel 梯度均值',
};
function mapVisionRows(res: FeatureExtraction) {
  const v = res.vision_features ?? {};
  return VISION_ROWS.map(([key, name, unit]) => {
    const val = v[key];
    let text = '—';
    if (val != null) text = `${key === 'area' ? Math.round(val).toLocaleString() : String(Number(val.toFixed(2)))}${unit ? ` ${unit}` : ''}`;
    return { name, value: text, desc: VISION_DESC[key] ?? '' };
  });
}
const AUDIO_ROWS: [string, string][] = [
  ['band_energy_low', '频带能量 (0-1kHz)'], ['band_power_high', '频带功率 (1-5kHz)'], ['total_psd', '总功率谱密度'],
  ['spectral_centroid', '质心频率'], ['spectral_rolloff', '频谱滚降'], ['zero_crossing_rate', '过零率'],
];
function mapAudioRows(res: FeatureExtraction) {
  const a = res.audio_features ?? {};
  return AUDIO_ROWS.map(([key, name]) => {
    const val = a[key];
    let text = '—';
    if (val != null) {
      if (key === 'band_energy_low' || key === 'band_power_high') text = `${val.toFixed(1)} dB`;
      else if (key === 'spectral_centroid' || key === 'spectral_rolloff') text = `${(val / 1000).toFixed(2)} kHz`;
      else text = String(Number(val.toFixed(3)));
    }
    return { name, value: text };
  });
}
const unifiedPalette = ['#2c9caf', '#67cdb0', '#f0a34a', '#75add1', '#b89ac4', '#b89ac4', '#d4a05a'];
function mapUnifiedGroups(uv: FeatureExtraction['unified_vector'] | null | undefined) {
  return (uv?.groups ?? []).map((g, i) => ({ group: g.name, dims: g.dims, range: `[${g.range[0]}:${g.range[1]}]`, tone: unifiedPalette[i % unifiedPalette.length] }));
}

export function FeatureExtractionPage({ embedded = false, dataId }: { embedded?: boolean; dataId?: string }) {
  const [normMethod, setNormMethod] = useState('Z-Score');
  const [exportFmt, setExportFmt] = useState('NPY');
  const [versionId, setVersionId] = useState<number | null>(null);
  const [extractionId, setExtractionId] = useState<number | null>(null);
  const [tsRows, setTsRows] = useState<FeatureTableRow[]>([]);
  const [visionRows, setVisionRows] = useState<VisionFeatureRow[]>([]);
  const [audioRows, setAudioRows] = useState<AudioFeatureRow[]>([]);
  const [unified, setUnified] = useState<UnifiedFeatureRow[]>([]);
  const [totalDims, setTotalDims] = useState(0);
  const [extracting, setExtracting] = useState(false);
  const [featureJobId, setFeatureJobId] = useState<string | null>(null);
  const [extractError, setExtractError] = useState<string | null>(null);
  const [modalityStatus, setModalityStatus] = useState<FeatureExtraction['modality_status'] | null>(null);
  const { status: featureJobStatus, result: featureJobResult, error: featureJobError } = useJob<{ extraction_id: number; status: string }>(featureJobId);
  useEffect(() => {
    if (!dataId) return;
    let cancelled = false;
    setFeatureJobId(null);
    setExtracting(false);
    setExtractionId(null); setModalityStatus(null); setTsRows([]); setVisionRows([]); setAudioRows([]); setUnified([]); setTotalDims(0);
    getWeld(dataId).then(async (r) => {
      if (cancelled) return;
      const resolved = r.latest_version_id ?? r.latest_version?.id ?? null;
      setVersionId(resolved);
      if (resolved == null) return;
      const latest = await getLatestFeatureExtraction(resolved);
      if (!cancelled && latest) {
        setExtractionId(latest.id); setTsRows(mapTsRows(latest)); setVisionRows(mapVisionRows(latest)); setAudioRows(mapAudioRows(latest));
        setModalityStatus(latest.modality_status ?? null);
        const mapped = mapUnifiedGroups(latest.unified_vector);
        setUnified(mapped); setTotalDims(latest.unified_vector?.total_dims ?? 0);
        setNormMethod(latest.normalization === 'L2' ? 'L2 范数' : latest.normalization);
      }
    }).catch((err) => { if (!cancelled) { setExtractError('无法加载当前数据或历史提取结果'); console.warn('[features] load failed', err); } });
    return () => { cancelled = true; };
  }, [dataId]);
  useEffect(() => {
    if (featureJobStatus === 'failed') {
      setExtracting(false);
      setExtractError(featureJobError instanceof Error ? featureJobError.message : '特征提取任务失败，请检查真实输入和模态文件后重试。');
      return;
    }
    if (featureJobStatus !== 'succeeded' || featureJobResult?.extraction_id == null) return;
    let cancelled = false;
    getFeatureExtraction(String(featureJobResult.extraction_id)).then((res) => {
      if (cancelled) return;
      setExtractionId(res.id);
      setTsRows(mapTsRows(res));
      setVisionRows(mapVisionRows(res));
      setAudioRows(mapAudioRows(res));
      setModalityStatus(res.modality_status ?? null);
      const mapped = mapUnifiedGroups(res.unified_vector);
      setUnified(mapped);
      setTotalDims(res.unified_vector?.total_dims ?? 0);
      setNormMethod(res.normalization === 'L2' ? 'L2 范数' : res.normalization);
      setExtracting(false);
    }).catch((err) => {
      if (!cancelled) {
        setExtracting(false);
        setExtractError(err instanceof Error ? err.message : '特征提取结果读取失败，请稍后重试。');
      }
    });
    return () => { cancelled = true; };
  }, [featureJobError, featureJobResult, featureJobStatus]);
  const handleExtract = () => {
    if (!dataId || versionId == null) { console.warn('[features] Version has not been resolved; please try again later'); return; }
    setExtracting(true);
    setExtractError(null);
    createFeatureExtractionTask({ weld_id: dataId, version_id: versionId, normalization: normMethod === 'L2 范数' ? 'L2' : normMethod, format: exportFmt })
      .then((res) => setFeatureJobId(res.job_id))
      .catch((err) => { setExtracting(false); setExtractError('特征提取任务创建失败，请检查数据版本和模态文件后重试。'); console.warn('[features] createFeatureExtractionTask failed', err); });
  };
  const modalityLabels: Record<string, string> = { timeseries: '时序', vision: '视觉', audio: '声音' };
  const modalityStatusLabels: Record<string, string> = { generated: '模拟', heuristic: '启发式', missing: '缺失' };
  const fallbackModalities = modalityStatus ? Object.entries(modalityStatus).filter(([, status]) => status !== 'real').map(([name, status]) => `${modalityLabels[name] ?? name}（${modalityStatusLabels[status] ?? status}）`) : [];
  const exportUnified = () => {
    if (extractionId == null) return;
    downloadFeatureExtraction(extractionId, exportFmt).then((res) => {
      if (res.url) window.open(res.url, '_blank', 'noopener,noreferrer');
    }).catch(() => setExtractError('统一特征向量导出失败，请稍后重试'));
  };
  return <div className={embedded ? 'embedded-page feature-extraction-page' : 'page-wrap'}><PageIntro eyebrow="多模态特征工程" title="特征提取" description="从真实输入提取可追溯特征；缺失模态不会被静默当作真实数据。" action={<Toolbar action={extracting ? '提取中…' : '执行提取'} secondary="导出特征集" onAction={handleExtract} exportType="features" exportRefIds={extractionId != null ? [extractionId] : undefined} actionDisabled={extracting || !dataId || versionId == null} />} />{extractError && <div className="alignment-banner bad" role="alert"><AlertTriangle size={15} />{extractError}</div>}{fallbackModalities.length > 0 && <div className="alignment-banner warn" role="status"><AlertTriangle size={15} />{fallbackModalities.join('、')}模态非真实输入，本次结果不可直接用于生产判定。</div>}
    <div className="feature-layout">
      <section className="panel feature-modality-panel">
        <div className="panel-heading"><div><h2>时序信号特征</h2><p>电流 / 电压 / 气体流量 / 送丝速度 · 统计 + 频域 + 时频</p></div><Waves size={17} className="accent-text" /></div>
        {extracting && <p className="dataset-empty-state" role="status">正在计算时序、视觉和声音特征…</p>}<div className="feature-table-wrap">
          <div className="feature-table">
            <div className="ft-row ft-head"><span>特征</span><span style={{ color: '#2c9caf' }}>电流</span><span style={{ color: '#67cdb0' }}>电压</span><span style={{ color: '#f0a34a' }}>气体</span><span style={{ color: '#75add1' }}>送丝</span></div>
            {tsRows.length ? tsRows.map((f) => <div className="ft-row" key={f.name}><span>{f.name}</span><span className="mono">{f.cur}</span><span className="mono">{f.vol}</span><span className="mono">{f.gas}</span><span className="mono">{f.wir}</span></div>) : <div className="feature-empty">执行提取后展示结果</div>}
          </div>
        </div>
        <div className="feature-tags"><span>统计特征</span><span>FFT 频域</span><span>小波时频</span><span>28 维 / 通道</span></div>
      </section>

      <section className="panel feature-modality-panel">
        <div className="panel-heading"><div><h2>熔池视觉特征</h2><p>从图片或视频关键帧提取几何与纹理特征</p></div><ImageIcon size={17} className="accent-text" /></div>
        <div className="vision-feature-grid">
          {visionRows.length ? visionRows.map((f) => <div className="vf-item" key={f.name}><div><strong>{f.name}</strong><small>{f.desc}</small></div><span className="mono">{f.value}</span></div>) : <div className="feature-empty">需要真实图片或视频输入</div>}
        </div>
        <div className="feature-tags"><span>几何特征</span><span>GLCM 纹理</span><span>Sobel 边缘</span><span>8 维</span></div>
      </section>

      <section className="panel feature-modality-panel">
        <div className="panel-heading"><div><h2>声音特征</h2><p>读取 WAV 后计算频带能量、功率谱密度与声学统计</p></div><AudioWaveform size={17} className="accent-text" /></div>
        <div className="audio-feature-list">
          {audioRows.length ? audioRows.map((f) => <div className="af-item" key={f.name}><Sigma size={13} /><span>{f.name}</span><strong className="mono">{f.value}</strong></div>) : <div className="feature-empty">需要真实 WAV 音频输入</div>}
        </div>
        <div className="feature-tags"><span>频带能量</span><span>PSD</span><span>声学统计</span><span>6 维</span></div>
      </section>

      <section className="panel feature-unified-panel">
        <div className="panel-heading"><div><h2>统一特征向量</h2><p>多模态特征拼接后输出，供后续融合层使用</p></div><Boxes size={17} className="accent-text" /></div>
        <div className="unified-summary"><div><span>总维度</span><strong>{totalDims} 维</strong></div><div><span>模态数</span><strong>3</strong></div><div><span>归一化</span><strong>{normMethod}</strong></div><div><span>输出格式</span><strong>.{exportFmt.toLowerCase()}</strong></div></div>
        <div className="unified-vector-bar">
          {unified.length ? unified.map((seg, i) => <div className="uv-seg" key={i} style={{ flexGrow: seg.dims, background: seg.tone }} title={`${seg.group} · ${seg.dims} 维`}><span>{seg.dims}</span></div>) : <div className="feature-empty">暂无统一向量</div>}
        </div>
        <div className="unified-legend">{unified.map((seg, i) => <span key={i}><i style={{ background: seg.tone }} />{seg.group}<small>{seg.range}</small></span>)}</div>
        <div className="unified-config">
          <div className="form-block"><label>归一化方式</label><div className="pp-chips">{['Z-Score', 'Min-Max', 'L2 范数', '无'].map((m) => <button key={m} className={normMethod === m ? 'on' : ''} onClick={() => setNormMethod(m)}>{m}</button>)}</div></div>
          <div className="form-block"><label>输出格式</label><div className="pp-chips">{['NPY', 'CSV', 'JSON', 'PT'].map((f) => <button key={f} className={exportFmt === f ? 'on' : ''} onClick={() => setExportFmt(f)}>{f}</button>)}</div></div>
        </div>
        <button className="full-button" disabled={extractionId == null || extracting} onClick={exportUnified}><Download size={15} />{extractionId == null ? '完成提取后可导出' : '导出统一特征向量'}</button>
      </section>

      <section className="panel feature-pipeline-panel">
        <div className="panel-heading"><div><h2>提取流水线</h2><p>从原始信号到融合向量的处理链路</p></div></div>
        <div className="feature-pipeline">
          <div className="fp-step"><Database size={15} /><span>原始多模态数据</span></div><i>↓</i>
          <div className="fp-step"><FilterIcon size={15} /><span>信号预处理 / 滤波</span></div><i>↓</i>
          <div className="fp-step"><Waves size={15} /><span>分模态特征提取</span></div><i>↓</i>
          <div className="fp-step"><Boxes size={15} /><span>特征拼接 · {totalDims} 维</span></div><i>↓</i>
          <div className="fp-step"><Check size={15} /><span>归一化 · 输出向量</span></div>
        </div>
        <div className="pipeline-note"><FileText size={14} /><span>{extractionId ? '结果已由后端计算并保存，可从当前数据版本追溯。' : '尚未执行提取。执行后才会展示真实计算结果，不使用演示数值。'}</span></div>
      </section>
    </div>
  </div>;
}
/** 训练/验证损失数组 → SVG polyline path（viewBox 0 0 600 250；min→底、max→顶）。 */
