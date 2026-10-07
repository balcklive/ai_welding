/**
 * 切片级特征提取工作台（2026-10，取代版本级的 `FeatureExtractionPage`）。
 *
 * **单位是「分段任务 + 一个切片」**，不是「焊缝的一个版本」——所以 props 没有
 * `selectedVersionId`。一个 v3 `Sample`（一个时间窗）= 一份 **36 维**向量：
 * 时序 28（cur 8 / vol 8 / gas 6 / wir 6）+ 视觉 8（几何 4 / 纹理 4），**无声音组**
 * （切片 manifest 自己写着 `audio.available = False`，音频上传也已收口拒收）。
 *
 * 两段式（同 `SampleAnnotationWorkspace` 的范式）：
 *   ① 该焊缝可提取的分段任务列表（最新一张卡 + 折叠的历史）；
 *   ② 进任务后：切片条 + 选中切片的向量细节 + 归一化（**只影响导出**）+ 执行提取。
 *
 * **没有 mock 初始态**：初始一律空 + loading，失败走 `ErrorState`——本页此前是全局
 * mock 禁令的唯一例外，这一版起退休（见 `src/CLAUDE.md`）。
 *
 * 归一化只影响**导出文件**：后端落库的权威向量恒为原始值（逐切片 Z-Score 会把每片各自
 * 减均值、抹掉区分切片的那批量），跨切片标准化属于训练侧、按 train 划分拟合。
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { AlertTriangle, Check, Download, Eye, Play, RefreshCw, Trash2 } from 'lucide-react';
import {
  createSampleFeatureExtraction,
  exportSampleFeatures,
  getSampleFeature,
  listSampleFeatures,
  listSampleFeatureTasks,
} from '../../api/sampleFeatures';
import { deleteSplitTask } from '../../api/analysis';
import { getFileUrl } from '../../api/files';
import type { SampleFeatureDetail, SampleFeatureProgress, SampleFeatureRow, SampleFeatureTask } from '../../api/types';
import { useJob } from '../../hooks/useJob';
import { ErrorState } from '../../shared/components/ErrorState';
import { PageIntro } from '../../shared/components/PageIntro';
import { ConfirmDialog } from '../../shared/components/ConfirmDialog';
import { fmt } from '../analysis/signals/chartData';
import { mapTsRows, mapUnifiedGroups, mapVisionRows } from './featureRows';

/** 切片条按批渲染：全量的是索引，不是媒体——一次几百个按钮没有意义。 */
const BATCH_SIZE = 40;

/** 归一化候选：**只作用于导出文件**（落库恒为原始值）。 */
const NORMALIZATIONS = ['无', 'Z-Score', 'Min-Max', 'L2'] as const;

const MODALITY_LABELS: Record<string, string> = { timeseries: '时序', vision: '视觉' };
const STATUS_LABELS: Record<string, string> = { real: '真实', heuristic: '启发式', missing: '缺失', generated: '模拟' };

function modalitySummary(status: Record<string, string> | null | undefined): string {
  if (!status) return '—';
  return Object.entries(status)
    .map(([key, value]) => `${MODALITY_LABELS[key] ?? key}·${STATUS_LABELS[value] ?? value}`)
    .join(' / ');
}

function windowLabel(row: SampleFeatureRow): string {
  if (row.start_time == null || row.end_time == null) return `切片 #${row.index ?? '—'}`;
  return `${fmt(row.start_time)} – ${fmt(row.end_time)}`;
}

// `embedded` 与其它懒加载页一样由 `WorkspaceFrame` 统一传入，本页用不到（页头由外层渲染），
// 故只声明在类型里、不解构——与 `AlignmentWorkspace` / `AdvancedWeldAnalysis` 同一写法。
export function SampleFeatureWorkspace({ dataId }: { embedded?: boolean; dataId?: string }) {
  const [tasks, setTasks] = useState<SampleFeatureTask[]>([]);
  const [tasksLoading, setTasksLoading] = useState(true);
  const [tasksError, setTasksError] = useState<unknown>(null);
  const [taskId, setTaskId] = useState<string | null>(null);
  const [showHistory, setShowHistory] = useState(false);
  const [askDelete, setAskDelete] = useState<SampleFeatureTask | null>(null);

  const loadTasks = useCallback(() => {
    if (!dataId) {
      setTasks([]);
      setTasksLoading(false);
      return;
    }
    setTasksLoading(true);
    setTasksError(null);
    listSampleFeatureTasks(dataId)
      .then((items) => setTasks(items))
      .catch((err) => {
        // 只清空 + 报错，**不回落演示数据**（全局 mock 禁令）
        setTasks([]);
        setTasksError(err);
      })
      .finally(() => setTasksLoading(false));
  }, [dataId]);

  useEffect(() => { loadTasks(); }, [loadTasks]);

  const openTask = tasks.find((task) => task.task_id === taskId) ?? null;

  return (
    <div className="page-wrap">
      <PageIntro
        eyebrow="多模态数据生产线"
        title="特征提取"
        description="按分段任务逐切片计算 36 维特征向量（时序 28 + 视觉 8），训练读的就是这一份。"
        action={taskId ? (
          <button className="full-button studio-reset" type="button" onClick={() => setTaskId(null)}>
            换个分段任务
          </button>
        ) : undefined}
      />
      {!dataId && <div className="dataset-empty-state">请先在顶部选择一条焊缝。</div>}
      {dataId && tasksError != null && (
        <ErrorState scene="加载分段任务" error={tasksError} onRetry={loadTasks} />
      )}
      {dataId && !tasksError && tasksLoading && (
        <div className="dataset-empty-state" role="status">分段任务加载中…</div>
      )}
      {dataId && !tasksError && !tasksLoading && !taskId && (
        <FeatureTaskList
          tasks={tasks}
          showHistory={showHistory}
          onToggleHistory={() => setShowHistory((value) => !value)}
          onOpen={(task) => setTaskId(task.task_id)}
          onDelete={setAskDelete}
        />
      )}
      {dataId && taskId && openTask && (
        <FeatureSliceView
          taskId={taskId}
          task={openTask}
          onReload={loadTasks}
        />
      )}
      {askDelete && (
        <ConfirmDialog
          tone="danger"
          title="删除该分段任务？"
          description={`将删除它的 ${askDelete.sample_count ?? 0} 个切片、切片特征与对象存储产物，无法恢复。`}
          confirmLabel="删除"
          onCancel={() => setAskDelete(null)}
          onConfirm={() => {
            const target = askDelete;
            setAskDelete(null);
            deleteSplitTask(target.task_id).then(() => loadTasks()).catch((err) => setTasksError(err));
          }}
        />
      )}
    </div>
  );
}

/** 阶段 ①：可提取的分段任务列表（最新一张卡 + 折叠历史）。 */
function FeatureTaskList({
  tasks, showHistory, onToggleHistory, onOpen, onDelete,
}: {
  tasks: SampleFeatureTask[];
  showHistory: boolean;
  onToggleHistory: () => void;
  onOpen: (task: SampleFeatureTask) => void;
  onDelete: (task: SampleFeatureTask) => void;
}) {
  if (!tasks.length) {
    return (
      <div className="panel">
        <div className="dataset-empty-state">
          这条焊缝还没有「已完成的多模态分段任务」。请先到「样本分段」切分，再回来提特征。
        </div>
      </div>
    );
  }
  const latest = tasks[0];
  const history = tasks.slice(1);
  return (
    <div className="panel">
      <div className="panel-heading">
        <div>
          <span className="file-badge">分段任务</span>
          <h2>最近一次成功任务</h2>
        </div>
        {history.length > 0 && (
          <button className="ghost-button segment-history-toggle" type="button" onClick={onToggleHistory}>
            历史任务（{history.length}）
          </button>
        )}
      </div>
      <FeatureTaskCard task={latest} onOpen={onOpen} onDelete={onDelete} />
      {showHistory && history.map((task) => (
        <FeatureTaskCard key={task.task_id} task={task} onOpen={onOpen} onDelete={onDelete} />
      ))}
      <p className="lane-note">
        只有**已完成且 v3**（时间统一的多模态样本）的分段任务可以提特征——历史口径的切片没有统一时间窗，
        逐切片特征对它不成立。
      </p>
    </div>
  );
}

function FeatureTaskCard({
  task, onOpen, onDelete,
}: {
  task: SampleFeatureTask;
  onOpen: (task: SampleFeatureTask) => void;
  onDelete: (task: SampleFeatureTask) => void;
}) {
  const progress = task.progress;
  return (
    <div className="segment-task-card">
      <button className="outline-button" type="button" onClick={() => onOpen(task)}>
        v{task.version_no} · {progress.total} 片 · 已提取 {progress.extracted}/{progress.total}（{progress.progress}%）
        {task.finished_at ? ` · ${task.finished_at.slice(0, 19).replace('T', ' ')}` : ''}
      </button>
      <button className="ghost-button segment-task-delete" type="button" onClick={() => onDelete(task)} aria-label="删除该分段任务">
        <Trash2 size={15} />
      </button>
    </div>
  );
}

/** 阶段 ②：某分段任务的逐切片向量。 */
function FeatureSliceView({
  taskId, task, onReload,
}: {
  taskId: string;
  task: SampleFeatureTask;
  onReload: () => void;
}) {
  const [rows, setRows] = useState<SampleFeatureRow[]>([]);
  const [progress, setProgress] = useState<SampleFeatureProgress>(task.progress);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [filter, setFilter] = useState<'all' | 'unextracted'>('all');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [detail, setDetail] = useState<SampleFeatureDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<unknown>(null);
  const [frameUrl, setFrameUrl] = useState<string | null>(null);
  const [normalization, setNormalization] = useState<string>('无');
  const [actionError, setActionError] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const job = useJob<Record<string, unknown>>(jobId);

  const loadPage = useCallback((nextPage: number, replace: boolean) => {
    setLoading(true);
    listSampleFeatures(taskId, { page: nextPage, page_size: BATCH_SIZE, filter })
      .then((data) => {
        setRows((previous) => (replace ? data.items : [...previous, ...data.items]));
        setProgress(data.progress);
        setTotal(data.total);
        setPage(nextPage);
        setError(null);
      })
      .catch((err) => { setError(err); if (replace) setRows([]); })
      .finally(() => setLoading(false));
  }, [taskId, filter]);

  // 换任务/换筛选都从第一页重来；**依赖里只有这两个**（翻页由按钮驱动，不进依赖）
  useEffect(() => { loadPage(1, true); setSelected(null); }, [taskId, filter, loadPage]);

  // 提取完成后：重拉列表（进度 + 各行状态），并把当前选中片的详情刷新
  const reloadAll = useCallback(() => {
    loadPage(1, true);
    onReload();
    if (selected != null) {
      getSampleFeature(taskId, selected).then((data) => setDetail(data.feature)).catch(() => setDetail(null));
    }
  }, [loadPage, onReload, selected, taskId]);

  useEffect(() => {
    if (job.status !== 'succeeded') return;
    setJobId(null);
    reloadAll();
    // 只在"这次刚成功"时重拉一次：jobId 已置空，不会重复触发
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job.status]);

  useEffect(() => {
    if (job.status === 'failed') {
      setActionError('特征提取任务失败，请检查该版本的信号导入状态后重试。');
      setJobId(null);
    }
  }, [job.status]);

  // 选中切片详情：只给**这一片**换预签名 URL（几百片各签一次没有意义）
  useEffect(() => {
    if (selected == null) { setDetail(null); setFrameUrl(null); return; }
    let cancelled = false;
    setDetailLoading(true);
    setDetailError(null);
    getSampleFeature(taskId, selected)
      .then((data) => { if (!cancelled) setDetail(data.feature); })
      .catch((err) => { if (!cancelled) { setDetail(null); setDetailError(err); } })
      .finally(() => { if (!cancelled) setDetailLoading(false); });
    const row = rows.find((item) => item.sample_id === selected);
    if (row?.frame_key) {
      getFileUrl(row.frame_key, 3600)
        .then((res) => { if (!cancelled) setFrameUrl(res.url); })
        .catch(() => { if (!cancelled) setFrameUrl(null); });
    } else {
      setFrameUrl(null);
    }
    return () => { cancelled = true; };
  }, [taskId, selected, rows]);

  const handleExtract = () => {
    setActionError(null);
    createSampleFeatureExtraction(taskId, { normalization })
      .then((res) => setJobId(res.job_id))
      .catch((err) => {
        setActionError(err instanceof Error ? err.message : '特征提取任务创建失败，请稍后重试。');
      });
  };

  const handleExport = (format: 'JSON' | 'CSV') => {
    setActionError(null);
    exportSampleFeatures(taskId, format)
      .then((res) => window.open(res.url, '_blank', 'noopener,noreferrer'))
      .catch((err) => {
        setActionError(err instanceof Error ? err.message : '导出失败：请先执行一次特征提取。');
      });
  };

  const extracting = job.status === 'pending' || job.status === 'running';
  const unifiedRows = useMemo(() => mapUnifiedGroups(detail?.unified_vector), [detail]);

  return (
    <div className="panel">
      <div className="panel-heading">
        <div>
          <span className="file-badge">切片特征</span>
          <h2>v{task.version_no} · {progress.total} 片</h2>
          <p className="lane-note">
            已提取 {progress.extracted}/{progress.total}（{progress.progress}%）· 窗口 {task.window_seconds ?? '—'}s /
            步长 {task.stride_seconds ?? '—'}s
          </p>
        </div>
        <div className="annot-batch-actions">
          <button className="full-button" type="button" onClick={handleExtract} disabled={extracting}>
            {extracting ? <><RefreshCw size={15} />提取中 {job.progress}%</> : <><Play size={15} />{progress.extracted ? '重新提取' : '执行提取'}</>}
          </button>
        </div>
      </div>

      <div className="preprocess-field">
        <label>归一化（**只影响导出文件**，落库恒为原始值）</label>
        <div className="pp-chips">
          {NORMALIZATIONS.map((item) => (
            <button key={item} className={normalization === item ? 'on' : ''} type="button" onClick={() => setNormalization(item)}>
              {item}
            </button>
          ))}
        </div>
      </div>
      <div className="annot-batch-actions">
        <button className="outline-button" type="button" onClick={() => handleExport('JSON')}>
          <Download size={14} />导出 JSON
        </button>
        <button className="outline-button" type="button" onClick={() => handleExport('CSV')}>
          <Download size={14} />导出 CSV
        </button>
      </div>

      {actionError && <div className="alignment-banner bad" role="alert"><AlertTriangle size={15} />{actionError}</div>}

      <div className="pp-chips">
        <button className={filter === 'all' ? 'on' : ''} type="button" onClick={() => setFilter('all')}>全部切片</button>
        <button className={filter === 'unextracted' ? 'on' : ''} type="button" onClick={() => setFilter('unextracted')}>只看未提取</button>
      </div>

      {error != null && <ErrorState scene="加载切片特征" error={error} onRetry={() => loadPage(1, true)} />}
      {error == null && loading && rows.length === 0 && (
        <div className="dataset-empty-state" role="status">切片加载中…</div>
      )}
      {error == null && !loading && rows.length === 0 && (
        <div className="dataset-empty-state">
          {filter === 'unextracted' ? '所有切片都已提取。' : '这个分段任务没有切片。'}
        </div>
      )}

      {rows.length > 0 && (
        <div className="channel-toggles">
          {rows.map((row) => (
            <button
              key={row.sample_id}
              className={`channel-toggle ${selected === row.sample_id ? 'on' : ''}`}
              type="button"
              onClick={() => setSelected(row.sample_id)}
              title={row.extracted ? `已提取 · ${modalitySummary(row.modality_status)}` : '未提取'}
            >
              #{row.index ?? '—'}<small>{windowLabel(row)}</small>
              <span className="toggle-check">{row.extracted ? <Check size={12} /> : null}</span>
            </button>
          ))}
        </div>
      )}
      {rows.length < total && (
        <div className="annot-batch-actions">
          <button className="outline-button" type="button" onClick={() => loadPage(page + 1, false)} disabled={loading}>
            加载更多（{rows.length}/{total}）
          </button>
        </div>
      )}

      {selected != null && (
        <section className="panel split-preview-panel">
          <div className="panel-heading">
            <div>
              <span className="file-badge"><Eye size={14} />切片 #{detail?.index ?? '—'}</span>
              <h2>{detail ? windowLabel({ ...(rows.find((r) => r.sample_id === selected) ?? ({} as SampleFeatureRow)) }) : '读取中…'}</h2>
            </div>
          </div>
          {detailLoading && <div className="dataset-empty-state" role="status">特征读取中…</div>}
          {detailError != null && <ErrorState scene="加载该切片的特征" error={detailError} />}
          {!detailLoading && detailError == null && detail == null && (
            <div className="dataset-empty-state">
              这一片还没提取特征。点上面的「执行提取」生成这一批。
            </div>
          )}
          {detail && (
            <>
              <p className="lane-note">模态：{modalitySummary(detail.modality_status)} · 口径 {detail.pipeline_version}</p>
              {detail.warnings.length > 0 && (
                <div className="alignment-banner warn" role="status">
                  <div>{detail.warnings.map((warning) => <div key={warning}>{warning}</div>)}</div>
                </div>
              )}
              {frameUrl
                ? <img className="sample-thumb" src={frameUrl} alt="该切片的视频代表帧" style={{ maxWidth: '100%' }} />
                : <div className="sample-thumb sample-thumb-empty">该切片没有可用的视频代表帧</div>}

              <div className="split-estimate studio-estimate">
                <strong>{detail.unified_vector.total_dims}</strong>
                <span>维统一向量</span>
                <small>{detail.unified_vector.normalization === '无' ? '原始值（训练侧再做标准化）' : `归一化 ${detail.unified_vector.normalization}`}</small>
              </div>
              <div className="unified-vector-bar">
                {unifiedRows.map((row) => (
                  <span key={row.group} style={{ background: row.tone, flex: row.dims }} title={`${row.group} ${row.range} · ${row.dims} 维`}>
                    {row.group}<small>{row.dims}</small>
                  </span>
                ))}
              </div>

              <table className="feature-table">
                <thead><tr><th>时序特征</th><th>电流</th><th>电压</th><th>气体</th><th>送丝</th></tr></thead>
                <tbody>
                  {mapTsRows(detail).map((row) => (
                    <tr key={row.name}><td>{row.name}</td><td>{row.cur}</td><td>{row.vol}</td><td>{row.gas}</td><td>{row.wir}</td></tr>
                  ))}
                </tbody>
              </table>

              <table className="feature-table">
                <thead><tr><th>视觉特征</th><th>值</th><th>说明</th></tr></thead>
                <tbody>
                  {mapVisionRows(detail).map((row) => (
                    <tr key={row.name}><td>{row.name}</td><td>{row.value}</td><td>{row.desc}</td></tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </section>
      )}
    </div>
  );
}
