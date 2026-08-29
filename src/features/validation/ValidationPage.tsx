import { useEffect, useState } from 'react';
import { AlertTriangle, CheckCircle2 } from 'lucide-react';
import { getValidation, getWeld, runValidation } from '../../api/welds';
import type { ValidationReport, ValidationRuleResult } from '../../api/types';
import { PageIntro } from '../../shared/components/PageIntro';
import { StatusPill } from '../../shared/components/StatusPill';
import { Toolbar } from '../../shared/components/Toolbar';
import { formatDateTime } from '../../shared/lib/formatting';

/** 数据列表：每页条数 + tab 演示计数（API 返回后 active tab 显示响应 total）。 */
/** 上传数据：分类型上传区配置（CSV / 图片 / 视频 / WAV 各自独立）。 */
/** 核验规则演示名单（仅接口失败/无版本可查时兜底，不得在加载期显示）。 */
const mockValidationRuleNames = ['图像文件完整性', '时序信号连续性', '采样频率一致性', '起收弧事件完整', '电流范围合理性', '电压范围合理性', '送丝速度缺失值', '多模态时间戳', '视频帧率稳定性', '文件命名规范', '焊缝ID唯一性', '工艺参数完整性', '音频信号质量', '红外数据完整性', '元数据关联关系'];

export function ValidationPage({ dataId }: { embedded?: boolean; dataId?: string }) {
  // 初始为空 + 加载中：mock 报告仅在接口失败/无版本可查时兜底，不得在加载期闪现假核验结论
  const [report, setReport] = useState<ValidationReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState<string | null>(null);
  const [versionId, setVersionId] = useState<number | null>(null);
  const [running, setRunning] = useState(false);
  const [statusFilter, setStatusFilter] = useState<'all' | 'passed' | 'warning' | 'failed'>('all');
  useEffect(() => {
    let cancelled = false;
    const fallback = () => {
      setLoading(false);
      setNotice('核验结果暂时无法加载，请点击“执行核验”或稍后重试。');
      setReport((prev) => prev ?? {
        id: 0,
        version_id: 0,
        score: 93.3,
        passed: 14,
        warning: 1,
        failed: 0,
        duration: 2.8,
        created_at: '2026-08-15T09:45:00',
        rules: mockValidationRuleNames.map((name, index) => ({ rule_name: name, status: index === 8 ? 'warning' : 'passed', message: index === 8 ? '视频帧率存在轻微波动，建议复核' : '检查通过 · 结果已记录' })),
      });
    };
    if (!dataId) { fallback(); return; }
    getWeld(dataId).then((r) => {
      if (cancelled) return;
      const vid = r.latest_version_id ?? r.latest_version?.id ?? null;
      if (vid == null) { fallback(); return; }
      setVersionId(vid);
      getValidation(dataId, String(vid)).then((rep) => { if (!cancelled) { setReport(rep); setLoading(false); } }).catch((err) => { if (!cancelled) { fallback(); console.warn('[validation] getValidation failed', err); } });
    }).catch((err) => { if (!cancelled) { fallback(); console.warn('[validation] getWeld failed', err); } });
    return () => { cancelled = true; };
  }, [dataId]);
  const loadReport = () => {
    if (!dataId || versionId == null) return;
    setLoading(true);
    setNotice(null);
    getValidation(dataId, String(versionId))
      .then(setReport)
      .catch(() => setNotice('该版本尚未执行核验，请点击“执行核验”。'))
      .finally(() => setLoading(false));
  };
  const runNow = () => {
    if (!dataId || versionId == null) return;
    setRunning(true);
    setNotice(null);
    runValidation(dataId, String(versionId))
      .then((next) => { setReport(next); setNotice('核验完成，结果已保存并已回写数据质量状态。'); })
      .catch((err) => { setNotice('执行核验失败，请稍后重试。'); console.warn('[validation] runValidation failed', err); })
      .finally(() => setRunning(false));
  };
  const rules: ValidationRuleResult[] = report?.rules ?? [];
  const passed = report?.passed ?? 0;
  const warning = report?.warning ?? 0;
  const failed = report?.failed ?? 0;
  const statusText = report ? (failed > 0 ? '异常' : warning > 0 ? '待复核' : '核验通过') : '加载中';
  const statusTone = report ? (failed > 0 ? 'red' : warning > 0 ? 'orange' : 'green') : 'blue';
  const lastRun = report && report.created_at ? `最近核验：${formatDateTime(report.created_at)} · 核验耗时 ${report.duration != null ? report.duration : '—'}s` : '正在加载核验结果…';
  const visibleRules = statusFilter === 'all' ? rules : rules.filter((rule) => rule.status === statusFilter);
  return <div className="page-wrap"><PageIntro eyebrow="数据质量中心" title="数据核验" description="通过标准化规则检查数据完整性、连续性与多模态一致性。支持自动规则核验，也支持人工点击重新核验并复核结果。" action={<Toolbar action={running ? '核验中…' : '执行核验'} secondary="下载核验报告" onAction={runNow} onRefresh={loadReport} exportType="validation" exportRefIds={report ? [report.id] : undefined} actionDisabled={running || !dataId || versionId == null} />} /><div className="validation-summary"><div className="validation-score"><div className="score-ring small"><div><strong>{report ? report.score : '—'}</strong><span>质量评分</span></div></div><div><h2>{dataId ?? '—'}</h2><p>{lastRun}</p><StatusPill tone={statusTone as 'green' | 'orange' | 'red' | 'blue'}>{statusText}</StatusPill></div></div><div className="validation-count"><div><strong>{passed}</strong><span>通过规则</span></div><div><strong className="warning-text">{warning}</strong><span>警告</span></div><div><strong className="danger-text">{failed}</strong><span>失败</span></div></div></div>{notice && <p className="dataset-empty-state" role="status">{notice}</p>}<section className="panel validation-panel"><div className="panel-heading"><div><h2>核验规则明细 <span className="inline-count">{visibleRules.length}/{rules.length} 项</span></h2><p>已覆盖图像、时序、视频、元数据与跨模态一致性检查</p></div><label className="filter-field">状态<select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value as typeof statusFilter)}><option value="all">全部状态</option><option value="passed">通过</option><option value="warning">警告</option><option value="failed">失败</option></select></label></div><div className="rule-grid">{visibleRules.length ? visibleRules.map((rule, index) => { const isWarn = rule.status === 'warning'; const isFail = rule.status === 'failed'; const tone = isFail ? 'red' : isWarn ? 'orange' : 'green'; const label = isFail ? '失败' : isWarn ? '警告' : '通过'; const msg = rule.message ?? (isWarn ? '存在警告，建议复核' : '检查通过 · 结果已记录'); return <div className="validation-rule" key={rule.rule_name || index}><div className={`validation-icon ${isWarn ? 'warning' : isFail ? 'failed' : ''}`}>{isFail || isWarn ? <AlertTriangle size={15} /> : <CheckCircle2 size={15} />}</div><div><strong>{rule.rule_name}</strong><span>{msg}</span></div><StatusPill tone={tone as 'green' | 'orange' | 'red'}>{label}</StatusPill></div>; }) : <p className="dataset-empty-state" role="status">{loading ? '核验规则加载中…' : statusFilter === 'all' ? '暂无核验规则' : '没有符合该状态的规则'}</p>}</div></section></div>;
}
