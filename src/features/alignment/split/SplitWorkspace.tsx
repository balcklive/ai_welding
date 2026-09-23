/**
 * 数据切分 · 样本生产流水线（v3，设计 §4.3/§4.5/§7.2）。
 *
 * 状态约束（§7.2）：
 * - `draftRules` 是用户正在编辑的值；`appliedPreview` 是最后一次**服务端成功**预览。
 * - 屏幕上的窗口、边界、数量一律取 `appliedPreview`——**不在前端算正式窗口数**。
 * - `stale = draftKey(draft) !== appliedPreview.key`，为真时禁止创建任务。
 * - 本页**不持有可编辑的标定**：offset/ROI 只能在对齐页改（§4.3）。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AlertTriangle } from 'lucide-react';
import { createSplitTask, getCalibration, previewSplitTask } from '../../../api/analysis';
import { getFileUrl } from '../../../api/files';
import { getWeld, listVersions } from '../../../api/welds';
import type { DataRecord, SplitPreview, SplitResult } from '../../../api/types';
import { useJob } from '../../../hooks/useJob';
import { PageIntro } from '../../../shared/components/PageIntro';
import { StatusPill } from '../../../shared/components/StatusPill';
import { MultimodalTimeline } from './MultimodalTimeline';
import { SliceDetailPanel } from './SliceDetailPanel';
import { SplitRulesPanel } from './SplitRulesPanel';
import { defaultDraft, draftKey, draftToRules } from './splitTypes';
import type { RulesDraft } from './splitTypes';

const VIDEO_EXTS = ['.mp4', '.avi', '.mkv', '.mov', '.webm'];
/** §4.5：输入合法且停顿 300ms 后才请求预览，避免每敲一个字符打一次服务端。 */
const DEBOUNCE_MS = 300;

export function SplitWorkspace({ dataId }: { dataId?: string }) {
  const [record, setRecord] = useState<DataRecord | null>(null);
  const [versionId, setVersionId] = useState<number | null>(null);
  const [inputError, setInputError] = useState<string | null>(null);
  const [draft, setDraft] = useState<RulesDraft>(defaultDraft);
  /** 最后一次**成功**的预览 + 它的规则指纹（用于判定 stale）。 */
  const [applied, setApplied] = useState<{ preview: SplitPreview; key: string } | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [createError, setCreateError] = useState<string | null>(null);
  const [playhead, setPlayhead] = useState(0);
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const [seamImageUrl, setSeamImageUrl] = useState<string | null>(null);
  /** 视频零点（`t_video = t_signal - offset`）：来自该焊缝 v1.0 的标定。 */
  const [videoOffset, setVideoOffset] = useState(0);
  const fetchTokenRef = useRef(0);

  const { status: jobStatus, progress, result: splitResult, error: jobError } = useJob<SplitResult>(jobId);
  const rules = useMemo(() => draftToRules(draft), [draft]);
  const currentKey = useMemo(() => draftKey(rules), [rules]);

  // ── 输入：焊缝 / 版本 / 媒体 URL / 标定 ────────────────────────────
  useEffect(() => {
    if (!dataId) return;
    let cancelled = false;
    setInputError(null);
    getWeld(dataId)
      .then((r) => { if (!cancelled) setRecord(r); })
      .catch((err) => { if (!cancelled) setInputError(err instanceof Error ? err.message : '焊缝信息读取失败'); });
    listVersions(dataId)
      .then((versions) => {
        if (cancelled || !versions.length) return;
        const source = versions.find((v) => v.id === (record?.latest_version_id ?? null)) ?? versions[versions.length - 1];
        setVersionId(source.id);
        const keys = versions.flatMap((v) => v.object_keys ?? []);
        const videoKey = keys.find((k) => VIDEO_EXTS.some((e) => k.toLowerCase().endsWith(e)));
        if (videoKey) {
          getFileUrl(videoKey).then((r) => { if (!cancelled) setVideoUrl(r.url); })
            .catch(() => { if (!cancelled) setVideoUrl(null); });
        }
        // 焊缝照片的键**不在这条启发式里挑**：ROI 是照着对齐页那张图量的，分段页必须显示
        // **同一张**，否则框选的位置对不上。权威来源是服务端预览的 `seam_image_projection.object_key`
        // （见下方 effect）——扩展名启发式可能先撞上对齐产物的关键帧 jpg。
        // 标定只读：拿 offset 供播放器 seek 换算（标定的编辑在对齐页）
        getCalibration(dataId, String(source.id))
          .then((c) => { if (!cancelled) setVideoOffset(c.video.calibrated ? c.video.offset_seconds : 0); })
          .catch(() => { if (!cancelled) setVideoOffset(0); });
      })
      .catch((err) => { if (!cancelled) setInputError(err instanceof Error ? err.message : '数据版本读取失败'); });
    return () => { cancelled = true; };
    // record 只用于挑默认版本；把它放进依赖会让本效果在 record 到达后重跑一遍，反而发两次请求
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dataId]);

  // ── 预览：300ms 防抖 + 取消在途请求（§4.5） ────────────────────────
  useEffect(() => {
    if (!dataId || versionId == null) return;
    if (draft.windowSeconds <= 0 || draft.strideSeconds <= 0) {
      // §4.6：时长/步长 ≤ 0 是字段错误，**不发预览请求**
      setPreviewError(null);
      return;
    }
    if (applied?.key === currentKey) return;
    const token = ++fetchTokenRef.current;
    setPreviewing(true);
    const timer = setTimeout(() => {
      previewSplitTask(dataId, String(versionId), rules)
        .then((preview) => {
          if (token !== fetchTokenRef.current) return; // 已有更新的请求在途，丢弃这份
          setApplied({ preview, key: currentKey });
          setPreviewError(null);
          setSelectedIndex((prev) => (prev && preview.windows.some((w) => w.index === prev) ? prev : preview.windows[0]?.index ?? null));
        })
        .catch((err) => {
          // §4.6：失败时**保留上一份成功预览**，只提示当前编辑未应用
          if (token === fetchTokenRef.current) {
            setPreviewError(err instanceof Error ? `预览失败（当前编辑未应用）：${err.message}` : '预览失败');
          }
        })
        .finally(() => { if (token === fetchTokenRef.current) setPreviewing(false); });
    }, DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [dataId, versionId, currentKey, rules, applied?.key, draft.windowSeconds, draft.strideSeconds]);

  // 焊缝照片地址取服务端预览认定的那个键（与对齐页框 ROI 时看的必须是同一张）
  const seamImageKey = applied?.preview?.timeline.seam_image_projection.object_key ?? null;
  useEffect(() => {
    if (!seamImageKey) return;
    let cancelled = false;
    getFileUrl(seamImageKey)
      .then((r) => { if (!cancelled) setSeamImageUrl(r.url); })
      .catch(() => { if (!cancelled) setSeamImageUrl(null); });
    return () => { cancelled = true; };
  }, [seamImageKey]);

  const preview = applied?.preview ?? null;
  const stale = Boolean(preview) && applied?.key !== currentKey;
  const fieldError = draft.windowSeconds <= 0 || draft.strideSeconds <= 0 ? '切片时长与步长必须大于 0' : null;

  // 视频轴 → 信号轴的换回（`+ offset`）由详情面板的播放器驱动游标；反向 seek 也在那边
  const onTimeUpdate = useCallback((signalTime: number) => setPlayhead(signalTime), []);

  const handleCreate = () => {
    if (!dataId || versionId == null || !preview) return;
    setCreateError(null);
    createSplitTask(dataId, String(versionId), preview.preview_token)
      .then((res) => setJobId(res.job_id))
      .catch((err) => setCreateError(err instanceof Error ? err.message : '任务创建失败'));
  };

  const goToAlignment = () => { window.location.hash = '#/analysis/alignment'; };
  // 分段成功后进入**段级标注**工作台：那边按同一个分段任务列样本、逐段给结论。
  const goToAnnotation = () => { window.location.hash = '#/analysis/sample-annotation'; };
  const done = jobStatus === 'succeeded';
  const tone = inputError || createError || previewError || jobStatus === 'failed'
    ? 'red' : jobStatus === 'running' || jobStatus === 'pending' ? 'orange' : done ? 'green' : 'muted';
  const statusText = inputError ?? createError ?? (jobStatus === 'failed' ? '生成失败'
    : jobStatus === 'running' ? `生成中 ${progress}%` : jobStatus === 'pending' ? '排队中'
    : done ? '生成完成' : previewing ? '预览中…' : '待生成');

  const selectedWindow = preview?.windows.find((w) => w.index === selectedIndex) ?? null;
  const generatedSamples = done ? splitResult?.samples ?? [] : [];
  const generatedCropKey = selectedWindow
    ? generatedSamples.find((s) => s.frame_no === selectedWindow.index)?.object_keys.find((k) => k.endsWith('.jpg')) ?? null
    : null;

  return (
    <>
      <PageIntro
        eyebrow="多模态数据生产线"
        title="样本分段"
        description="以秒为唯一切分单位，按固定时间窗生成多模态样本；边界与数量全部来自服务端预览。"
      />
      <div className="split-steps">
        <span className="active">1 数据检查</span><i>→</i>
        <span className={preview ? 'active' : ''}>2 规则与预览</span><i>→</i>
        <span className={done ? 'active' : ''}>3 确认生成</span>
      </div>

      {inputError && (
        <div className="alignment-banner bad" role="alert"><AlertTriangle size={15} />{inputError}</div>
      )}
      {jobStatus === 'failed' && (
        <div className="alignment-banner bad" role="alert">
          <AlertTriangle size={15} />
          生成失败：{jobError instanceof Error ? jobError.message : String(splitResult ?? '请查看任务日志')}
        </div>
      )}

      <div className="alignment-layout">
        {preview ? (
          <MultimodalTimeline
            preview={preview}
            seamImageUrl={seamImageUrl}
            selectedIndex={selectedIndex}
            playhead={playhead}
            onSelect={setSelectedIndex}
          />
        ) : (
          <section className="panel alignment-board">
            <div className="board-toolbar">
              <div>
                <span className="file-badge">切分输入{record ? ` · ${record.weld_id}` : ''}</span>
                <h2>等待服务端预览</h2>
              </div>
              <StatusPill tone={tone as 'green' | 'orange' | 'red'}>{statusText}</StatusPill>
            </div>
            <p className="preview-summary">
              规则改动后自动预览；预览失败时会保留上一份可用结果，并标明当前编辑未应用。
            </p>
          </section>
        )}
        <SplitRulesPanel
          draft={draft}
          fieldError={fieldError}
          preview={preview}
          previewError={previewError}
          previewing={previewing}
          stale={stale}
          creating={jobStatus === 'pending' || jobStatus === 'running'}
          onDraft={(patch) => setDraft((prev) => ({ ...prev, ...patch }))}
          onCreate={handleCreate}
          onGoToAlignment={goToAlignment}
          onGoToAnnotation={done ? goToAnnotation : undefined}
        />
      </div>

      {preview && (
        <SliceDetailPanel
          window={selectedWindow}
          preview={preview}
          cropKey={generatedCropKey}
          cropUrl={null}
          videoUrl={videoUrl}
          offsetSeconds={videoOffset}
          onTimeUpdate={onTimeUpdate}
          onOpenKey={(key) => {
            getFileUrl(key).then((r) => window.open(r.url, '_blank', 'noopener,noreferrer')).catch(() => undefined);
          }}
        />
      )}
    </>
  );
}
