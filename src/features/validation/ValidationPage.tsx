import { useEffect, useState } from 'react';
import { AlertTriangle, CheckCircle2 } from 'lucide-react';
import { getValidation, getWeld, runValidation } from '../../api/welds';
import type { ValidationReport, ValidationRuleResult } from '../../api/types';
import { ErrorState } from '../../shared/components/ErrorState';
import { PageIntro } from '../../shared/components/PageIntro';
import { StatusPill } from '../../shared/components/StatusPill';
import { Toolbar } from '../../shared/components/Toolbar';
import { formatDateTime } from '../../shared/lib/formatting';
import { toUserMessage } from '../../shared/lib/errors';

/** 404 = 该版本尚未核验，属**空态**（给引导），不是错误态（给原因）。 */
const isNotFound = (err: unknown) => typeof err === 'object' && err !== null && (err as { status?: number }).status === 404;

export function ValidationPage({ dataId }: { embedded?: boolean; dataId?: string }) {
  // T3.2：演示报告已删除。三种情况分开处理——无版本/未核验走空态引导，接口失败走错误态。
  const [report, setReport] = useState<ValidationReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [versionId, setVersionId] = useState<number | null>(null);
  const [running, setRunning] = useState(false);
  const [statusFilter, setStatusFilter] = useState<'all' | 'passed' | 'warning' | 'failed'>('all');
  const [reloadKey, setReloadKey] = useState(0);
  useEffect(() => {
    if (!dataId) {
      setLoading(false);
      setNotice('请先在上方选择一条样本。');
      return;
    }
    let cancelled = false;
    setLoading(true);
    setNotice(null);
    setError(null);
    getWeld(dataId).then((r) => {
      if (cancelled) return;
      const vid = r.latest_version_id ?? r.latest_version?.id ?? null;
      if (vid == null) {
        setVersionId(null);
        setReport(null);
        setLoading(false);
        setNotice('该样本还没有数据版本，请先在数据登记中挂载文件。');
        return;
      }
      setVersionId(vid);
      getValidation(dataId, String(vid))
        .then((rep) => { if (!cancelled) { setReport(rep); setLoading(false); } })
        .catch((err) => {
          if (cancelled) return;
          setLoading(false);
          setReport(null);
          if (isNotFound(err)) setNotice('该版本尚未执行核验，请点击“执行核验”。');
          else { setError(err); console.warn('[validation] getValidation failed', err); }
        });
    }).catch((err) => {
      if (cancelled) return;
      setLoading(false);
      setError(err);
      console.warn('[validation] getWeld failed', err);
    });
    return () => { cancelled = true; };
  }, [dataId, reloadKey]);
  const loadReport = () => {
    if (!dataId || versionId == null) { setReloadKey((n) => n + 1); return; }
    setLoading(true);
    setNotice(null);
    setError(null);
    // 失败时保留上一次的报告，避免一次抖动把已有结果清空。
    getValidation(dataId, String(versionId))
      .then(setReport)
      .catch((err) => {
        if (isNotFound(err)) setNotice('该版本尚未执行核验，请点击“执行核验”。');
        else { setError(err); console.warn('[validation] getValidation failed', err); }
      })
      .finally(() => setLoading(false));
  };
  const runNow = () => {
    if (!dataId || versionId == null) return;
    setRunning(true);
    setNotice(null);
    setError(null);
    runValidation(dataId, String(versionId))
      .then((next) => { setReport(next); setNotice('核验完成，结果已保存并已回写核验状态。'); })
      .catch((err) => { setNotice(toUserMessage(err, '执行核验').message); console.warn('[validation] runValidation failed', err); })
      .finally(() => setRunning(false));
  };
  const rules: ValidationRuleResult[] = report?.rules ?? [];
  const passed = report?.passed ?? 0;
  const warning = report?.warning ?? 0;
  const failed = report?.failed ?? 0;
  const statusText = report ? (failed > 0 ? '异常' : warning > 0 ? '待复核' : '核验通过') : error ? '不可用' : '加载中';
  const statusTone = report ? (failed > 0 ? 'red' : warning > 0 ? 'orange' : 'green') : 'blue';
  const lastRun = report && report.created_at ? `最近核验：${formatDateTime(report.created_at)} · 核验耗时 ${report.duration != null ? report.duration : '—'}s` : error ? '核验结果不可用' : '正在加载核验结果…';
  const visibleRules = statusFilter === 'all' ? rules : rules.filter((rule) => rule.status === statusFilter);
  return <div className="page-wrap"><PageIntro eyebrow="数据核验中心" title="数据核验" description="通过标准化规则检查数据完整性、连续性与多模态一致性。支持自动规则核验，也支持人工点击重新核验并复核结果。" action={<Toolbar action={running ? '核验中…' : '执行核验'} secondary="下载核验报告" onAction={runNow} onRefresh={loadReport} exportType="validation" exportRefIds={report ? [report.id] : undefined} actionDisabled={running || !dataId || versionId == null} exportDisabled={!report} />} /><div className="validation-summary"><div className="validation-score"><div className="score-ring small"><div><strong>{report ? report.score : '—'}</strong><span>核验评分</span></div></div><div><h2>{dataId ?? '—'}</h2><p>{lastRun}</p><StatusPill tone={statusTone as 'green' | 'orange' | 'red' | 'blue'}>{statusText}</StatusPill></div></div><div className="validation-count"><div><strong>{passed}</strong><span>通过规则</span></div><div><strong className="warning-text">{warning}</strong><span>警告</span></div><div><strong className="danger-text">{failed}</strong><span>失败</span></div></div></div>{error ? <ErrorState scene="加载核验结果" error={error} onRetry={() => setReloadKey((n) => n + 1)} /> : notice ? <p className="dataset-empty-state" role="status">{notice}</p> : null}<section className="panel validation-panel"><div className="panel-heading"><div><h2>核验规则明细 <span className="inline-count">{visibleRules.length}/{rules.length} 项</span></h2><p>已覆盖图像、时序、视频、元数据与跨模态一致性检查</p></div><label className="filter-field">状态<select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value as typeof statusFilter)}><option value="all">全部状态</option><option value="passed">通过</option><option value="warning">警告</option><option value="failed">失败</option></select></label></div><div className="rule-grid">{visibleRules.length ? visibleRules.map((rule, index) => { const isWarn = rule.status === 'warning'; const isFail = rule.status === 'failed'; const tone = isFail ? 'red' : isWarn ? 'orange' : 'green'; const label = isFail ? '失败' : isWarn ? '警告' : '通过'; const msg = rule.message ?? (isWarn ? '存在警告，建议复核' : '检查通过 · 结果已记录'); return <div className="validation-rule" key={rule.rule_name || index}><div className={`validation-icon ${isWarn ? 'warning' : isFail ? 'failed' : ''}`}>{isFail || isWarn ? <AlertTriangle size={15} /> : <CheckCircle2 size={15} />}</div><div><strong>{rule.rule_name}</strong><span>{msg}</span></div><StatusPill tone={tone as 'green' | 'orange' | 'red'}>{label}</StatusPill></div>; }) : <p className="dataset-empty-state" role="status">{loading ? '核验规则加载中…' : statusFilter === 'all' ? '暂无核验规则' : '没有符合该状态的规则'}</p>}</div></section></div>;
}
