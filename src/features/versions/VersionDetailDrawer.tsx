import { useEffect, useState } from 'react';
import { getDatasetVersion } from '../../api/datasets';
import { getValidation, getVersion } from '../../api/welds';
import type { DatasetVersion, DataVersion, ValidationReport } from '../../api/types';
import { InfoRow } from '../../shared/components/InfoRow';
import { StatusPill } from '../../shared/components/StatusPill';
import { formatDateTime } from '../../shared/lib/formatting';

type VersionDetailDrawerProps =
  | { mode: 'weld'; weldId: string; versionId: string; onClose: () => void }
  | { mode: 'dataset'; datasetId: string; version: DatasetVersion; onClose: () => void };

export function VersionDetailDrawer(props: VersionDetailDrawerProps) {
  const { onClose } = props;
  const ownerId = props.mode === 'weld' ? props.weldId : props.datasetId;
  const versionId = props.mode === 'weld' ? props.versionId : String(props.version.id);
  const [weldVersion, setWeldVersion] = useState<DataVersion | null>(null);
  const [validation, setValidation] = useState<ValidationReport | null>(null);
  const [datasetVersion, setDatasetVersion] = useState<DatasetVersion | null>(props.mode === 'dataset' ? props.version : null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose(); };
    document.addEventListener('keydown', onKeyDown);
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => { document.removeEventListener('keydown', onKeyDown); document.body.style.overflow = previousOverflow; };
  }, [onClose]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    if (props.mode === 'weld') {
      Promise.all([
        getVersion(ownerId, versionId),
        getValidation(ownerId, versionId).catch(() => null),
      ]).then(([version, report]) => {
        if (cancelled) return;
        setWeldVersion(version);
        setValidation(report);
        setLoading(false);
      }).catch((err) => { if (!cancelled) { setError(err instanceof Error ? err.message : '版本详情加载失败'); setLoading(false); } });
    } else {
      getDatasetVersion(ownerId, versionId)
        .then((version) => { if (!cancelled) { setDatasetVersion(version); setLoading(false); } })
        .catch((err) => { if (!cancelled) { setError(err instanceof Error ? err.message : '快照详情加载失败'); setLoading(false); } });
    }
    return () => { cancelled = true; };
  }, [props.mode, ownerId, versionId]);

  const version = props.mode === 'weld' ? weldVersion : datasetVersion;
  const split = version && 'split' in version
    ? `${version.split.train?.toLocaleString() ?? '—'} / ${version.split.val?.toLocaleString() ?? '—'} / ${version.split.test?.toLocaleString() ?? '—'}`
    : null;
  const quality = version && 'quality' in version && version.quality
    ? `${((1 - version.quality.repeat_rate - version.quality.empty_label_rate - version.quality.dimension_missing_rate) * 100).toFixed(1)}%`
    : '—';

  const versionKind = props.mode === 'weld' ? '焊缝版本' : '数据集快照';
  return <div className="version-drawer-backdrop" role="presentation" onClick={onClose}><aside className="version-drawer" role="dialog" aria-modal="true" aria-label={`${versionKind}详情`} onClick={(event) => event.stopPropagation()}><div className="version-drawer-head"><div><span className="eyebrow"><span />{versionKind}详情</span><h2>{version?.version_no ?? '加载中…'}</h2></div><button className="icon-button" onClick={onClose} aria-label={`关闭${versionKind}详情`}>×</button></div>{loading && <div className="version-drawer-state">正在加载{versionKind}详情…</div>}{error && <div className="version-drawer-state error">{error}</div>}{!loading && !error && version && props.mode === 'weld' && <><div className="version-drawer-summary"><StatusPill>{weldVersion?.action}</StatusPill><span>{weldVersion?.operator ?? '—'} · {formatDateTime(weldVersion?.created_at)}</span></div><div className="version-drawer-section"><h3>焊缝版本信息</h3><InfoRow label="处理动作" value={weldVersion?.action ?? '—'} /><InfoRow label="操作人" value={weldVersion?.operator ?? '—'} /><InfoRow label="备注" value={weldVersion?.note ?? '暂无备注'} /><InfoRow label="数据文件" value={weldVersion?.object_keys.length ? `${weldVersion.object_keys.length} 个文件` : '暂无关联文件'} /></div><div className="version-drawer-section"><h3>核验结果</h3>{validation ? <><InfoRow label="质量分数" value={`${validation.score.toFixed(1)} 分`} accent /><InfoRow label="规则统计" value={`通过 ${validation.passed} · 警告 ${validation.warning} · 失败 ${validation.failed}`} /></> : <p className="version-drawer-muted">尚未执行核验</p>}</div></>}{!loading && !error && version && props.mode === 'dataset' && <><div className="version-drawer-summary"><StatusPill>固定快照</StatusPill><span>创建于 {formatDateTime(datasetVersion?.created_at)}</span></div><div className="version-drawer-section"><h3>数据集快照信息</h3><InfoRow label="样本总数" value={`${datasetVersion?.item_count.toLocaleString() ?? '—'} 条`} /><InfoRow label="训练 / 验证 / 测试" value={split ?? '—'} /><InfoRow label="数据质量" value={quality} accent /><InfoRow label="快照 ID" value={datasetVersion?.snapshot_id ?? '尚未生成'} /></div><div className="version-drawer-section"><h3>使用说明</h3><p className="version-drawer-muted">该快照是固定样本清单，不会随单条焊缝后续处理自动变化。</p></div></>}</aside></div>;
}
