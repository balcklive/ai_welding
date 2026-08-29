import { useEffect, useMemo, useRef, useState } from 'react';
import { Archive, Check, ChevronDown, Image as ImageIcon, MoreHorizontal, Play, Plus, SlidersHorizontal, Sparkles, Upload, Waves, Zap } from 'lucide-react';
import * as echarts from 'echarts';
import {
  aiPretag, createAnnotationFrame, createAnnotationTask, getAnnotationSample,
  getSignals, importAnnotationSamples, listAnnotationSamples,
  listLabelCategories, saveAnnotation,
} from '../../api/analysis';
import { getFileUrl } from '../../api/files';
import { getVersion, getWeld, listVersions } from '../../api/welds';
import type {
  Annotation as AnnotationLabel, LabelCategory, LabelItem, Sample, SignalData,
} from '../../api/types';
import { useJob } from '../../hooks/useJob';
import { AnnotoriousImageEditor } from '../../components/annotation/AnnotoriousImageEditor';
import type { ImageEditorAnnotation } from '../../components/annotation/AnnotoriousImageEditor';
import { InfoRow } from '../../shared/components/InfoRow';
import { PageIntro } from '../../shared/components/PageIntro';
import { fmt } from '../analysis/signals/chartData';

const mockLabelCategories: LabelCategory[] = [
  { id: 1, name: '焊瘤', color: null },
  { id: 2, name: '气孔', color: null },
  { id: 3, name: '未熔合', color: null },
  { id: 4, name: '咬边', color: null },
  { id: 5, name: '正常', color: null },
];
export function AnnotationWorkspace({ embedded = false, dataId }: { embedded?: boolean; dataId?: string }) {
  const [mode, setMode] = useState<string>('image');
  const [saved, setSaved] = useState(false);
  const [selectedLabels, setSelectedLabels] = useState(['焊瘤', '气孔']);
  // 初始为空：标签类别加载完成前不闪现 mock 类别，mock 仅作失败兜底
  const [labels, setLabels] = useState<LabelCategory[]>([]);
  const [taskId, setTaskId] = useState<string | null>(null);
  const [sample, setSample] = useState<Sample | null>(null);
  const [sampleImg, setSampleImg] = useState('');
  const [sampleImgError, setSampleImgError] = useState(false);
  const [aiBoxes, setAiBoxes] = useState<AnnotationLabel[]>([]);
  const [imageTool, setImageTool] = useState<'box' | 'polygon'>('box');
  const [imageEditorKey, setImageEditorKey] = useState(0);
  const [imageDraft, setImageDraft] = useState<ImageEditorAnnotation[]>([]);
  // 初始为 0：样本总数在接口返回前不得显示 mock 值 1209
  const [totalSamples, setTotalSamples] = useState(0);
  const creatingRef = useRef<string | null>(null);
  const { status: jobStatus } = useJob<unknown>(taskId);
  const toggleLabel = (label: string) => setSelectedLabels((current) => current.includes(label) ? current.filter((item) => item !== label) : [...current, label]);
  useEffect(() => {
    let cancelled = false;
    listLabelCategories().then((list) => { if (!cancelled && list.length) setLabels(list); }).catch((err) => { if (!cancelled) { setLabels(mockLabelCategories); console.warn('[annotation] listLabelCategories failed', err); } });
    return () => { cancelled = true; };
  }, []);
  // 只从当前焊缝版本导入真实图片对象，禁止创建无样本的演示任务。
  useEffect(() => {
    if (!dataId || creatingRef.current === dataId) return;
    let cancelled = false;
    creatingRef.current = dataId;
    setSample(null); setSampleImg(''); setSampleImgError(false); setAiBoxes([]); setImageDraft([]); setTotalSamples(0); setTaskId(null);
    getWeld(dataId).then((weld) => {
      const imageKey = (weld.latest_version?.object_keys ?? []).find((key) => /\.(jpe?g|png|webp|bmp)$/i.test(key));
      if (!imageKey) throw new Error('当前版本没有真实图片对象');
      // 媒体预览不依赖标注任务，先拿 URL 显示图片，任务在后台准备样本。
      getFileUrl(imageKey).then((r) => { if (!cancelled) setSampleImg(r.url); }).catch((err) => {
        if (!cancelled) { setSampleImgError(true); console.warn('[annotation] image preview failed', err); }
      });
      return createAnnotationTask({ source: 'manual', name: `真实图像标注 · ${weld.weld_id}` }).then((res) => importAnnotationSamples(res.job_id, { source: 'files', object_keys: [imageKey] }).then(() => res));
    }).then((res) => { if (!cancelled) setTaskId(res.job_id); }).catch((err) => { if (!cancelled) console.warn('[annotation] real image sample unavailable', err); if (creatingRef.current === dataId) creatingRef.current = null; });
    return () => { cancelled = true; };
  }, [dataId]);
  useEffect(() => {
    if (!taskId || jobStatus !== 'succeeded') return;
    let cancelled = false;
    listAnnotationSamples(taskId, 1).then((page) => {
      if (cancelled) return;
      setTotalSamples(page.total || 0);
      const first = page.items[0];
      if (!first) return;
      getAnnotationSample(taskId, String(first.id)).then((s) => {
        if (cancelled) return;
      setSample(s);
      setAiBoxes(s.annotations ?? []);
      setImageDraft((s.annotations ?? []).flatMap<ImageEditorAnnotation>((annotation, index) => annotation.kind === 'polygon'
        ? [{ id: String(annotation.id ?? index), category: annotation.category, kind: 'polygon' as const, box: [], points: annotation.points }]
        : annotation.box.length === 4
          ? [{ id: String(annotation.id ?? index), category: annotation.category, kind: 'box' as const, box: annotation.box, points: [] }]
          : []));
        if (s.object_keys && s.object_keys.length) {
          getFileUrl(s.object_keys[0]).then((r) => { if (!cancelled) setSampleImg(r.url); }).catch((err) => { if (!cancelled) { setSampleImgError(true); console.warn('[annotation] getFileUrl failed', err); } });
        }
      }).catch((err) => { if (!cancelled) console.warn('[annotation] getAnnotationSample failed', err); });
    }).catch((err) => { if (!cancelled) console.warn('[annotation] listAnnotationSamples failed', err); });
    return () => { cancelled = true; };
  }, [taskId, jobStatus]);
  const handleAiPretag = () => {
    if (!taskId || !sample) return;
    aiPretag(taskId, String(sample.id)).then((anns) => {
      setAiBoxes(anns);
      setImageDraft(anns.flatMap<ImageEditorAnnotation>((annotation, index) => annotation.kind === 'polygon'
        ? [{ id: String(annotation.id ?? index), category: annotation.category, kind: 'polygon' as const, box: [], points: annotation.points }]
        : annotation.box.length === 4
          ? [{ id: String(annotation.id ?? index), category: annotation.category, kind: 'box' as const, box: annotation.box, points: [] }]
          : []));
      setSaved(false);
    }).catch((err) => console.warn('[annotation] aiPretag failed', err));
  };
  const handleSave = () => {
    if (mode === 'image') {
      if (!taskId || !sample) return;
      const labelsToSave: LabelItem[] = imageDraft.map((annotation) => annotation.kind === 'polygon'
        ? { category: annotation.category, kind: 'polygon', points: annotation.points.map(([x, y]) => [Math.round(x), Math.round(y)]) }
        : { category: annotation.category, kind: 'box', box: annotation.box.map((value) => Math.round(value)) });
      saveAnnotation(taskId, String(sample.id), labelsToSave).then(() => {
        setSaved(true);
        setAiBoxes(labelsToSave.map((label, index) => ({ id: index, sample_id: sample.id, category: label.category, kind: label.kind ?? 'box', box: label.box ?? [], points: label.points ?? [], start_time: null, end_time: null, confidence: null, annotator: '当前用户', created_at: null, updated_at: null })));
      }).catch((err) => console.warn('[annotation] image annotation save failed', err));
      return;
    }
    if (!taskId || !sample) { setSaved(true); return; }
    const boxes = aiBoxes.map((b) => ({ category: b.category, box: b.box, confidence: b.confidence }));
    const labelsToSave: LabelItem[] = selectedLabels.length
      ? selectedLabels.map((cat) => { const ex = boxes.find((b) => b.category === cat); return { category: cat, box: ex && ex.box.length === 4 ? ex.box : [128, 182, 186, 106], confidence: ex?.confidence ?? null }; })
        : boxes.map((b) => ({ category: b.category, box: b.box }));
    saveAnnotation(taskId, String(sample.id), labelsToSave).then(() => setSaved(true)).catch((err) => { console.warn('[annotation] saveAnnotation failed', err); setSaved(true); });
  };
  const frameLabel = sample?.frame_no != null ? String(sample.frame_no).padStart(4, '0') : '—';
  const confidence = sample?.confidence != null ? `${(sample.confidence * 100).toFixed(1)}%` : '—';
  if (mode === 'image') {
    return <div className={embedded ? 'embedded-page' : 'page-wrap'}>
      <PageIntro eyebrow="数据生产线" title="数据标注" description="支持目标检测框与熔池语义分割轮廓标注。" action={<button className="primary-button" onClick={handleSave}>{saved ? <Check size={16} /> : <Plus size={16} />}{saved ? '已保存' : '保存标注'}</button>} />
      <div className="annotation-mode-bar"><button className="selected"><ImageIcon size={14} />图像标注</button><button onClick={() => setMode('signal')}><Waves size={14} />时序标注</button><button onClick={() => setMode('video')}><Play size={14} />视频标注</button></div>
      <section className="panel annotation-board"><div className="board-toolbar"><div><span className="file-badge"><Archive size={15} />{sample ? <>样本 {frameLabel} / {totalSamples.toLocaleString()}</> : '样本加载中…'}</span><h2>图像目标检测 / 熔池分割</h2></div><div className="toolbar-actions"><button className="icon-button" onClick={handleAiPretag} title="AI 预标注" disabled={!sample}><SlidersHorizontal size={17} /></button><button className="select-button" onClick={() => { setImageTool(imageTool === 'box' ? 'polygon' : 'box'); setImageEditorKey((k) => k + 1); }}>{imageTool === 'box' ? '目标检测框' : '熔池轮廓'} <ChevronDown size={14} /></button></div></div>
        <div className="annotation-image-editor">{sampleImg && !sampleImgError ? <><AnnotoriousImageEditor key={`${imageEditorKey}-${sample?.id ?? 'empty'}`} src={sampleImg} annotations={imageDraft} tool={imageTool === 'box' ? 'rectangle' : 'polygon'} defaultLabel={selectedLabels[0] ?? '正常'} onChange={(next) => { setImageDraft(next); setSaved(false); }} /></> : <div className="selection-required"><ImageIcon size={23} /><h2>{sampleImgError ? '图片暂时无法预览' : '真实图片加载中'}</h2><p>{sampleImgError ? '请检查对象存储连接后重试。' : '图片正在加载，加载完成后可直接绘制。'}</p></div>}</div>
        <div className="stage-tip">拖拽绘制目标检测框；切换为“熔池轮廓”后点击多个顶点并闭合。标注可移动、缩放和删除，完成后点击页面顶部“保存标注”。</div>
      </section>
    </div>;
  }
  return <div className={embedded ? 'embedded-page' : 'page-wrap'}><PageIntro eyebrow="数据生产线" title="数据标注" description="为模型准备高质量训练样本，支持多模态协同标注。" action={<><button className="outline-button"><Upload size={16} />导入数据</button><button className="primary-button" onClick={handleSave}>{saved ? <Check size={16} /> : <Plus size={16} />}{saved ? '已保存' : '保存标注'}</button></>} /><div className="annotation-mode-bar"><button className={mode === 'signal' ? 'selected' : ''} onClick={() => setMode('signal')}><Waves size={14} />时序标注</button><button className={mode === 'video' ? 'selected' : ''} onClick={() => setMode('video')}><Play size={14} />视频标注</button><button className={mode === 'image' ? 'selected' : ''} onClick={() => setMode('image')}><ImageIcon size={14} />图像标注</button></div>{mode === 'signal' ? <AnnotationSignal dataId={dataId} embedded={embedded} onBack={() => setMode('image')} /> : mode === 'video' ? <AnnotationVideo dataId={dataId} embedded={embedded} onBack={() => setMode('image')} /> : <div className="annotation-layout"><section className="panel annotation-board"><div className="board-toolbar"><div><span className="file-badge"><Archive size={15} />{sample ? <>样本 {frameLabel} / {totalSamples.toLocaleString()}</> : '样本加载中…'}</span><h2>焊接件 · 视觉质检样本</h2></div><div className="toolbar-actions"><button className="icon-button" onClick={handleAiPretag} title="AI 预标注" disabled={!sample}><SlidersHorizontal size={17} /></button><button className="select-button">图像标注 <ChevronDown size={14} /></button></div></div><div className="image-stage">{sampleImg && !sampleImgError ? <img src={sampleImg} alt="真实待标注焊接样本" onError={() => setSampleImgError(true)} /> : <div className="selection-required"><ImageIcon size={23} /><h2>{sampleImgError ? '图片暂时无法预览' : '真实图片加载中'}</h2><p>{sampleImgError ? '请检查对象存储连接后重试。' : '当前版本没有可用的真实图片样本。'}</p></div>}{aiBoxes.length ? aiBoxes.map((a, i) => { const [bx, by, bw, bh] = a.box.length === 4 ? a.box : [128, 182, 186, 106]; return <div key={a.id ?? i} className="annotation-box" style={{ left: `${(bx / 640) * 100}%`, top: `${(by / 480) * 100}%`, width: `${(bw / 640) * 100}%`, height: `${(bh / 480) * 100}%` }}><span>{a.category} {a.confidence != null ? <b>{a.confidence.toFixed(2)}</b> : null}</span></div>; }) : null}<div className="stage-tip">{aiBoxes.length ? <><Sparkles size={14} />AI 已预标注 {aiBoxes.length} 个区域</> : '暂无标注数据'}</div></div><div className="board-footer"><div className="thumb-strip"><>{sampleImg && !sampleImgError && <img className="thumb-active" src={sampleImg} alt="当前样本缩略图" onError={() => setSampleImgError(true)} />}</></div><div className="pagination">{sample ? <span>当前样本</span> : null}</div></div></section><aside className="annotation-side"><section className="panel label-panel"><div className="panel-heading"><div><h2>标签类别</h2><p>选择需要应用的缺陷标签</p></div><button className="more-button"><MoreHorizontal size={18} /></button></div><div className="label-options">{labels.map((label, index) => <button className={`label-chip ${selectedLabels.includes(label.name) ? 'chosen' : ''}`} onClick={() => toggleLabel(label.name)} key={label.name}><i className={`chip-dot chip-${index % 5}`} />{label.name}<span>{selectedLabels.includes(label.name) ? <Check size={14} /> : '+'}</span></button>)}</div></section><section className="panel annotation-info"><div className="panel-heading"><div><h2>标注信息</h2><p>当前样本的详细信息</p></div></div><InfoRow label="数据来源" value={sample ? '真实对象存储图片' : '—'} /><InfoRow label="采集时间" value={sample ? '真实数据记录' : '—'} /><InfoRow label="标注人员" value={sample ? '当前用户' : '—'} /><InfoRow label="置信度" value={sample ? confidence : '—'} accent /></section><div className="ai-card"><div className="ai-card-icon"><Zap size={17} /></div><div><strong>智能标注建议</strong><p>{aiBoxes.length ? `已为你识别 ${aiBoxes.length} 个疑似缺陷区域，建议确认后提交。` : '暂无 AI 标注建议'}</p></div></div></aside></div>}</div>;
}
/** 时序标注模式：ECharts 波形 + 点击设起点/终点选缺陷区间（kind=segment）+ 区间列表 + 保存。
 *
 * 流程：选中焊缝 → getWeld 取最新版本 → createAnnotationTask(source='signal', version_id)
 * → useJob 轮询成功 → listAnnotationSamples 取信号锚点样本 → getSignals 拉四通道波形 →
 * 波形上点击设起点/终点 → 选缺陷类别生成区间 → saveAnnotation(kind='segment') 覆盖写保存。
 */
function AnnotationSignal({ dataId, onBack }: { embedded?: boolean; dataId?: string; onBack: () => void }) {
  // 初始为空：mock 类别仅作失败兜底（见下方 catch），不闪现
  const [labels, setLabels] = useState<LabelCategory[]>([]);
  const [taskId, setTaskId] = useState<string | null>(null);
  const [sample, setSample] = useState<Sample | null>(null);
  const [versionId, setVersionId] = useState<number | null>(null);
  const [signal, setSignal] = useState<SignalData | null>(null);
  const [segments, setSegments] = useState<AnnotationLabel[]>([]);
  const [draft, setDraft] = useState<{ start: number | null; end: number | null }>({ start: null, end: null });
  // dataZoom 视口（百分比）：窗口请求重渲染时保持用户当前缩放位置
  const [zoomPct, setZoomPct] = useState({ start: 0, end: 100 });
  const [saved, setSaved] = useState(false);
  const [weldImg, setWeldImg] = useState('');
  const taskCreatedRef = useRef(false);
  const { status: jobStatus } = useJob<unknown>(taskId);
  const chartElRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    let cancelled = false;
    listLabelCategories().then((list) => { if (!cancelled && list.length) setLabels(list); }).catch((err) => { setLabels(mockLabelCategories); console.warn('[annotation.signal] listLabelCategories failed', err); });
    return () => { cancelled = true; };
  }, []);

  // 解析选中焊缝最新版本并创建 signal 标注任务（best-effort）
  // StrictMode 开发模式会「挂载→cleanup→再挂载」跑两次 effect：一次性闸门必须放在异步
  // resolve 之后（而非同步开头），否则第 1 次置 true → 第 2 次提前 return → 任务永不创建。
  useEffect(() => {
    if (!dataId) return;
    let cancelled = false;
    getWeld(dataId).then((w) => {
      if (cancelled) return;
      const vid = w.latest_version_id;
      if (vid == null) return;
      setVersionId(vid);
      if (taskCreatedRef.current) return;
      taskCreatedRef.current = true;
      createAnnotationTask({ source: 'signal', version_id: vid, name: 'AN-时序' }).then((res) => { if (!cancelled) setTaskId(res.job_id); }).catch((err) => console.warn('[annotation.signal] createAnnotationTask failed', err));
    }).catch((err) => console.warn('[annotation.signal] getWeld failed', err));
    return () => { cancelled = true; };
  }, [dataId]);

  // 任务成功后加载信号锚点样本与既有区间标注
  useEffect(() => {
    if (!taskId || jobStatus !== 'succeeded') return;
    let cancelled = false;
    listAnnotationSamples(taskId, 1).then((page) => {
      if (cancelled) return;
      const first = page.items[0];
      if (!first) return;
      getAnnotationSample(taskId, String(first.id)).then((s) => {
        if (cancelled) return;
        setSample(s);
        setSegments(s.annotations ?? []);
      }).catch((err) => console.warn('[annotation.signal] getAnnotationSample failed', err));
    }).catch((err) => console.warn('[annotation.signal] listAnnotationSamples failed', err));
    return () => { cancelled = true; };
  }, [taskId, jobStatus]);

  // 拉取多通道信号：Overview/Detail 两级加载——首屏全程概览（服务端 min-max 抽稀
  // 2048 点，防 910k 点全量 ~26MB 响应在公网拖 50s+）；dataZoom 缩放停止后按可见
  // 时间窗增量请求高分辨率细节（start/end + 4096 点）。stale 响应用递增 token 丢弃。
  const fetchTokenRef = useRef(0);
  const fetchSignalWindow = (start: number | null, end: number | null) => {
    if (!dataId || versionId == null) return;
    const token = ++fetchTokenRef.current;
    const query = start != null && end != null
      ? { max_points: 4096, start: Math.max(0, start), end }
      : { max_points: 2048 };
    getSignals(dataId, String(versionId), query)
      .then((sig) => { if (token === fetchTokenRef.current) setSignal(sig); })
      .catch((err) => console.warn('[annotation.signal] getSignals failed', err));
  };
  useEffect(() => {
    fetchTokenRef.current += 1; // 焊缝/版本切换：作废在途窗口请求
    setZoomPct({ start: 0, end: 100 });
    fetchSignalWindow(null, null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dataId, versionId]);

  // 焊缝图片参考（版本原始文件里取一张图像）
  useEffect(() => {
    if (!dataId || versionId == null) return;
    let cancelled = false;
    getVersion(dataId, String(versionId)).then((v) => {
      if (cancelled) return;
      const img = (v.object_keys ?? []).find((k) => /\.(jpe?g|png|webp|bmp)$/i.test(k));
      if (!img) return;
      getFileUrl(img).then((r) => { if (!cancelled) setWeldImg(r.url); }).catch(() => {});
    }).catch(() => {});
    return () => { cancelled = true; };
  }, [dataId, versionId]);

  const dur = signal?.source === 'real' ? signal.duration : 0;
  const channels = useMemo(() => signal?.source === 'real' ? signal.channels : [], [signal]);
  const anomalies = useMemo(() => signal?.source === 'real' ? signal.anomalies : [], [signal]);
  const fmtT = (t: number | null | undefined) => (t == null ? '—' : `${t.toFixed(2)}s`);

  // ECharts 渲染 + 点击选段（起点 → 终点）+ 缩放增量取数
  useEffect(() => {
    const el = chartElRef.current;
    if (!el || !channels.length) return;
    const chart = echarts.init(el);
    const gridHeight = 96;
    const segData = [
      ...anomalies.map((a) => [{ xAxis: a.start, itemStyle: { color: '#e88d6c', opacity: 0.1 } }, { xAxis: a.end }]),
      ...segments.map((s) => [{ xAxis: s.start_time ?? 0, itemStyle: { color: '#2c9caf', opacity: 0.18 } }, { xAxis: s.end_time ?? 0 }]),
      ...(draft.start != null && draft.end != null ? [{ xAxis: draft.start, itemStyle: { color: '#f0a34a', opacity: 0.28 } }, { xAxis: draft.end }] : []),
    ];
    // 服务端抽稀（max_points）时带 times 坐标（min-max 选点非均匀）→ 按 [t,v] 画点；
    // 全量响应（旧路径）退回序号均分。x 轴恒为绝对时间 [0, dur]，窗口数据只覆盖
    // 可视区间，dataZoom 视口保持不动。
    const seriesData = (c: { values: number[]; times?: number[] }) => c.times && c.times.length === c.values.length
      ? c.times.map((t, j) => [t, c.values[j]])
      : c.values.map((v, j) => [j / Math.max(c.values.length - 1, 1) * dur, v]);
    const option: echarts.EChartsOption = {
      animation: false,
      tooltip: { trigger: 'axis' },
      legend: { data: channels.map((c) => c.name), top: 0 },
      dataZoom: [
        { type: 'inside', start: zoomPct.start, end: zoomPct.end },
        { type: 'slider', bottom: 6, height: 16, start: zoomPct.start, end: zoomPct.end },
      ],
      grid: channels.map((_, i) => ({ left: 64, right: 28, top: 30 + i * (gridHeight + 14), height: gridHeight })),
      xAxis: channels.map((_, i) => ({ type: 'value', gridIndex: i, min: 0, max: dur, boundaryGap: [0, 0], axisLabel: { show: i === channels.length - 1 } })),
      yAxis: channels.map((c, i) => ({ type: 'value', gridIndex: i, name: `${c.name} (${c.unit})`, min: c.lo, max: c.hi, axisLabel: { fontSize: 10 } })),
      series: channels.map((c, i) => ({
        name: c.name,
        type: 'line',
        xAxisIndex: i,
        yAxisIndex: i,
        showSymbol: false,
        lineStyle: { width: 1.2 },
        data: seriesData(c),
        markArea: { silent: true, data: segData as never },
      })),
    };
    chart.setOption(option, true);
    chart.on('click', (params) => {
      const raw = params.value;
      const t = Array.isArray(raw) ? Number(raw[0]) : Number.NaN;
      if (!Number.isFinite(t)) return;
      setDraft((d) => {
        if (d.start == null) return { start: t, end: null };
        if (d.end == null) return t > d.start ? { start: d.start, end: t } : { start: t, end: null };
        return { start: t, end: null };
      });
    });
    // 缩放停止（300ms 防抖）后按可见窗口增量取细节；拉回全程则取回概览
    let zoomTimer: number | undefined;
    chart.on('datazoom', () => {
      window.clearTimeout(zoomTimer);
      zoomTimer = window.setTimeout(() => {
        const dz = (chart.getOption() as { dataZoom?: { start?: number; end?: number }[] }).dataZoom?.[0];
        if (!dz || dur <= 0) return;
        const startPct = dz.start ?? 0;
        const endPct = dz.end ?? 100;
        setZoomPct({ start: startPct, end: endPct });
        if (endPct - startPct >= 98) {
          fetchSignalWindow(null, null);
        } else {
          fetchSignalWindow((startPct / 100) * dur, (endPct / 100) * dur);
        }
      }, 300);
    });
    return () => { window.clearTimeout(zoomTimer); chart.dispose(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [channels, dur, anomalies, segments, draft, zoomPct]);

  const commitSegment = (cat: string) => {
    if (draft.start == null || draft.end == null) return;
    const now = Date.now();
    setSegments((cur) => [...cur, {
      id: -now,
      sample_id: sample?.id ?? 0,
      category: cat,
      kind: 'segment',
      box: [],
      points: [],
      start_time: draft.start,
      end_time: draft.end,
      confidence: null,
      annotator: '我',
      created_at: null,
      updated_at: null,
    }]);
    setDraft({ start: null, end: null });
  };
  const removeSegment = (id: number) => setSegments((cur) => cur.filter((s) => s.id !== id));
  const handleSave = () => {
    if (!taskId || !sample) return;
    const labelsToSave: LabelItem[] = segments.map((s) => ({
      category: s.category,
      kind: 'segment',
      start_time: s.start_time,
      end_time: s.end_time,
      confidence: s.confidence ?? undefined,
    }));
    saveAnnotation(taskId, String(sample.id), labelsToSave).then(() => setSaved(true)).catch((err) => { console.warn('[annotation.signal] saveAnnotation failed', err); });
  };

  return (
    <div className="annotation-signal-layout">
      <section className="panel annotation-signal-board">
        <div className="board-toolbar">
          <div><span className="file-badge"><Waves size={15} />时序标注 · {dataId ?? '未选择'}</span><h2>{channels.length ? '四通道焊接信号（电流/电压/气体/送丝）' : '加载信号中…'}</h2></div>
          <div className="toolbar-actions"><button className="outline-button" onClick={onBack}><ImageIcon size={14} />图像标注</button><button className="primary-button" onClick={handleSave} disabled={!segments.length || !sample}>{saved ? <Check size={16} /> : <Plus size={16} />}{saved ? '已保存' : '保存标注'}</button></div>
        </div>
        <div className="signal-legend"><span><i style={{ background: '#2c9caf' }} />已标区间</span><span><i style={{ background: '#f0a34a' }} />待确认</span><span><i style={{ background: '#e88d6c' }} />AI 异常提示</span></div>
        <div className="signal-stage">{signal?.source === 'generated' ? <div className="selection-required"><Waves size={23} /><h2>真实时序数据不可用</h2><p>当前版本的 CSV 导入校验未通过，已阻止展示模拟波形。</p></div> : <div ref={chartElRef} className="annotation-signal-chart" style={{ width: '100%', height: 440 }} />}</div>
        <div className="signal-stage-tip">{signal?.source === 'real' ? '点击真实波形设起点 → 再点设终点 → 选择缺陷类型；拖动底部滑块缩放时间轴，放大后自动加载高分辨率细节。' : '正在加载真实时序数据，模拟波形不会用于标注。'}</div>
        {draft.start != null && draft.end != null && (
          <div className="label-options signal-cat-options"><span className="signal-cat-hint">为 {fmtT(draft.start)}–{fmtT(draft.end)} 选择缺陷类型：</span>{labels.map((label, index) => <button key={label.name} className={`label-chip ${index % 5}`} onClick={() => commitSegment(label.name)}><i className={`chip-dot chip-${index % 5}`} />{label.name}</button>)}<button className="ghost-button" onClick={() => setDraft({ start: null, end: null })}>取消</button></div>
        )}
      </section>
      <aside className="annotation-signal-side">
        <section className="panel label-panel"><div className="panel-heading"><div><h2>焊缝图片参考</h2><p>当前版本视觉样本</p></div></div>{weldImg ? <img src={weldImg} alt="真实焊缝图片参考" className="signal-weld-img" /> : <p className="signal-empty">当前版本没有真实图片对象。</p>}</section>
        <section className="panel annotation-info"><div className="panel-heading"><div><h2>缺陷区间</h2><p>{segments.length} 段</p></div></div>{segments.length === 0 ? <p className="signal-empty">尚无区间标注。在波形上点击起点与终点添加。</p> : segments.map((s) => <div className="signal-seg-row" key={s.id}><span className="signal-seg-cat">{s.category}</span><span className="signal-seg-time">{fmtT(s.start_time)}–{fmtT(s.end_time)}</span><button className="ghost-button" onClick={() => removeSegment(s.id)}>删</button></div>)}</section>
      </aside>
    </div>
  );
}
/** 视频标注模式：熔池视频播放器 + 帧捕获 → Annotorious 画多边形（kind='polygon'）。
 *
 * 流程：选中焊缝 → getWeld 取最新版本 → createAnnotationTask(source='video', version_id)
 * → useJob 成功 → 取视频锚点样本（meta.video_key → getFileUrl 播放）→ 播放/定位 → 捕获当前帧
 * （canvas 按视频自然分辨率取帧）→ Annotorious 画多边形（像素坐标，`key` 变化重挂载
 * 重置每帧）→ 点标注器自带保存（onExit）→ 归一化 × 帧宽高转像素 → createAnnotationFrame 建帧样本
 * → saveAnnotation(kind='polygon', category='熔池')。已标注帧在侧栏展示。
 */
function AnnotationVideo({ dataId, onBack }: { embedded?: boolean; dataId?: string; onBack: () => void }) {
  const [taskId, setTaskId] = useState<string | null>(null);
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const [frameImage, setFrameImage] = useState<string | null>(null);
  const [frameW, setFrameW] = useState(1280);
  const [frameH, setFrameH] = useState(720);
  const [currentTime, setCurrentTime] = useState(0);
  const [saved, setSaved] = useState(false);
  const [savedFrames, setSavedFrames] = useState<{ timestamp: number; sample_id: number; count: number }[]>([]);
  const [captureKey, setCaptureKey] = useState(0);
  const [frameDraft, setFrameDraft] = useState<ImageEditorAnnotation[]>([]);
  const [videoError, setVideoError] = useState<string | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const taskDataIdRef = useRef<string | null>(null);
  const sampleByTime = useRef<Map<number, number>>(new Map());
  const { status: jobStatus } = useJob<unknown>(taskId);

  // 选择版本链中最新的含视频版本并创建任务；信号处理等最新版本可能不再携带视频对象。
  useEffect(() => {
    if (!dataId) return;
    if (taskDataIdRef.current !== dataId) {
      setTaskId(null);
      setVideoUrl(null);
      setFrameImage(null);
      setSaved(false);
      setSavedFrames([]);
      setVideoError(null);
      sampleByTime.current.clear();
    }
    let cancelled = false;
    listVersions(dataId).then((versions) => {
      if (cancelled) return;
      const version = [...versions].reverse().find((v) =>
        (v.object_keys ?? []).some((key) => /\.(mp4|avi|mkv|mov|webm)$/i.test(key)),
      );
      if (!version) return;
      const videoKey = (version.object_keys ?? []).find((key) => /\.(mp4|avi|mkv|mov|webm)$/i.test(key));
      if (videoKey) getFileUrl(videoKey, 86400).then((r) => {
        if (!cancelled) { setVideoUrl(r.url); setVideoError(null); }
      }).catch((err) => console.warn('[annotation.video] early video preview failed', err));
      if (taskDataIdRef.current === dataId) return;
      taskDataIdRef.current = dataId;
      createAnnotationTask({ source: 'video', version_id: version.id, name: 'AN-视频' })
        .then((res) => { if (!cancelled) setTaskId(res.job_id); })
        .catch((err) => {
          if (taskDataIdRef.current === dataId) taskDataIdRef.current = null;
          console.warn('[annotation.video] createAnnotationTask failed', err);
        });
    }).catch((err) => console.warn('[annotation.video] listVersions failed', err));
    return () => { cancelled = true; };
  }, [dataId]);

  // 任务成功后：加载视频锚点样本（video_url）+ 已标注帧
  useEffect(() => {
    if (!taskId || jobStatus !== 'succeeded') return;
    let cancelled = false;
    listAnnotationSamples(taskId, 1, 100).then((page) => {
      if (cancelled) return;
      const anchor = page.items.find((s) => s.meta?.mode === 'video');
      if (anchor) {
        const key = anchor.meta?.video_key;
        if (typeof key === 'string' && key) getFileUrl(key).then((r) => { if (!cancelled) { setVideoUrl(r.url); setVideoError(null); } }).catch((err) => console.warn('[annotation.video] getFileUrl failed', err));
      }
      const frames = page.items.filter((s) => s.meta?.mode === 'frame');
      if (frames.length) {
        const done = frames.map((f) => ({
          timestamp: (f.meta?.timestamp as number) ?? 0,
          sample_id: f.id,
          count: (f.annotations ?? []).length,
        }));
        setSavedFrames(done);
        done.forEach((d) => sampleByTime.current.set(d.timestamp, d.sample_id));
      }
    }).catch((err) => console.warn('[annotation.video] listAnnotationSamples failed', err));
    return () => { cancelled = true; };
  }, [taskId, jobStatus]);

  // 捕获当前帧：canvas 按视频自然分辨率取帧 → dataURL 喂标注器
  const handleCapture = () => {
    const video = videoRef.current;
    const canvas = canvasRef.current;
    if (!video || !canvas) return;
    if (video.readyState < 2) { console.warn('[annotation.video] Video is not ready for decoding'); return; }
    const w = video.videoWidth || 1280;
    const h = video.videoHeight || 720;
    canvas.width = w; canvas.height = h;
    canvas.getContext('2d')?.drawImage(video, 0, 0, w, h);
    setFrameW(w); setFrameH(h);
    setCurrentTime(Math.round(video.currentTime * 1000) / 1000);
    setFrameImage(canvas.toDataURL('image/jpeg', 0.9));
    setFrameDraft([]);
    setSaved(false);
    setCaptureKey((k) => k + 1);
  };
  const stepFrame = (delta: number) => {
    const video = videoRef.current;
    if (!video || !video.duration) return;
    video.currentTime = Math.min(video.duration, Math.max(0, video.currentTime + delta));
  };

  // 播放失败兜底：原始视频常为浏览器不支持的编码（如工业相机 MPEG-4 Part 2），
  // 或转码预览版尚未生成（登记后 media_prep 异步处理）。给出明确原因与建议，
  // 不再静默黑屏。MEDIA_ERR_SRC_NOT_SUPPORTED(4) = 编码/容器浏览器解不了。
  const handleVideoError = () => {
    const code = videoRef.current?.error?.code;
    setVideoError(
      code === 4
        ? '该视频编码格式浏览器不支持解码（常见为工业相机的 MPEG-4 Part 2）。系统已在上传后自动转码 H.264 预览版，请稍后重试；若持续失败请将原始视频转码为 H.264 MP4 后重新上传。'
        : '视频加载失败，请检查网络后重试。',
    );
  };

  const handleFrameSave = () => {
    if (!frameDraft.length || !taskId || !frameImage) return;
    const labels: LabelItem[] = frameDraft.filter((item) => item.kind === 'polygon' && item.points.length >= 3).map((item) => ({
      category: item.category || '熔池', kind: 'polygon', points: item.points.map(([x, y]) => [Math.round(x), Math.round(y)]),
    }));
    if (!labels.length) return;
    const existing = sampleByTime.current.get(currentTime);
    const create = existing != null
      ? Promise.resolve(existing)
      : createAnnotationFrame(taskId, currentTime, frameW, frameH).then((r) => { sampleByTime.current.set(currentTime, r.sample_id); return r.sample_id; });
    create
      .then((sid) => saveAnnotation(taskId, String(sid), labels))
      .then(() => {
        setSaved(true);
        const realSid = sampleByTime.current.get(currentTime) ?? 0;
        setSavedFrames((cur) => [...cur.filter((f) => Math.abs(f.timestamp - currentTime) > 0.001), { timestamp: currentTime, sample_id: realSid, count: labels.length }]);
      })
      .catch((err) => console.warn('[annotation.video] saveAnnotation failed', err));
  };

  return (
    <div className="annotation-signal-layout">
      <section className="panel annotation-signal-board">
        <div className="board-toolbar">
          <div><span className="file-badge"><ImageIcon size={15} />视频标注 · {dataId ?? '未选择'}</span><h2>{videoUrl ? '熔池视频 · 播放/定位后捕获帧画多边形' : '加载视频中…'}</h2></div>
          <div className="toolbar-actions"><button className="outline-button" onClick={onBack}><ImageIcon size={14} />图像标注</button><button className="outline-button" onClick={handleFrameSave} disabled={!frameDraft.length}>保存当前帧</button><button className="primary-button" onClick={handleCapture} disabled={!videoUrl}><Play size={14} />捕获当前帧</button></div>
        </div>
        <div className="signal-stage">
          {videoError ? (
            <div className="selection-required"><Play size={23} /><h2>视频无法在浏览器中播放</h2><p>{videoError}</p></div>
          ) : (
            <video ref={videoRef} src={videoUrl ?? undefined} controls className="video-annotate-player" onPause={handleCapture} onError={handleVideoError} />
          )}
          <canvas ref={canvasRef} style={{ display: 'none' }} />
        </div>
        <div className="video-annotate-controls">
          <button className="ghost-button" onClick={() => stepFrame(-1 / 30)}>‹ 上一帧</button>
          <span className="signal-seg-time">{fmt(currentTime)}</span>
          <button className="ghost-button" onClick={() => stepFrame(1 / 30)}>下一帧 ›</button>
        </div>
        {frameImage ? (
          <div className="video-annotate-editor">
            <AnnotoriousImageEditor key={captureKey} src={frameImage} annotations={[]} tool="polygon" defaultLabel="熔池" onChange={setFrameDraft} />
          </div>
        ) : <div className="signal-stage-tip">播放/定位到要标注的时间点，点「捕获当前帧」后画多边形（点若干顶点、双击闭合），再点标注器自带的保存按钮。</div>}
        <div className="signal-stage-tip">{saved ? <><Check size={14} />已保存 </> : null}已标注 {savedFrames.length} 帧 · 当前帧绘制完成后点击“保存当前帧”</div>
      </section>
      <aside className="annotation-signal-side">
        <section className="panel annotation-info">
          <div className="panel-heading"><div><h2>已标注帧</h2><p>{savedFrames.length} 帧 · 熔池区域</p></div></div>
          {savedFrames.length === 0 ? <p className="signal-empty">尚无标注。捕获帧 → 画多边形 → 保存。</p> : savedFrames.map((f) => (
            <div className="signal-seg-row" key={f.timestamp}>
              <span className="signal-seg-cat">熔池</span>
              <span className="signal-seg-time">{fmt(f.timestamp)}</span>
              <span className="signal-seg-count">×{f.count}</span>
            </div>
          ))}
        </section>
      </aside>
    </div>
  );
}
