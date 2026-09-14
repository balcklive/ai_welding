import { useState } from 'react';
import { Download, Plus, RefreshCw } from 'lucide-react';
import { exportReport } from '../../api/reports';
import { toUserMessage } from '../lib/errors';

interface ToolbarProps {
  action?: string;
  secondary?: string;
  onAction?: () => void;
  onRefresh?: () => void;
  actionDisabled?: boolean;
  exportType?: string;
  exportRefIds?: unknown[];
  /** 为真时禁用导出按钮（如核验页还没有核验报告可导，S12）。 */
  exportDisabled?: boolean;
}

export function Toolbar({ action, secondary, onAction, onRefresh, actionDisabled = false, exportType, exportRefIds, exportDisabled = false }: ToolbarProps) {
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  const handleExport = () => {
    if (!exportType || exporting || exportDisabled) return;
    setExportError(null);
    const popup = window.open('', '_blank');
    setExporting(true);
    exportReport({ type: exportType, ref_ids: exportRefIds ?? [], format: 'pdf' })
      .then((res) => {
        const url = res.urls?.[0]?.url;
        if (!url) throw new Error('empty export URL');
        if (popup && !popup.closed) popup.location.href = url;
        else window.location.href = url;
      })
      .catch((err) => {
        if (popup && !popup.closed) popup.close();
        setExportError(toUserMessage(err, '导出报告').message);
        console.warn('[export] exportReport failed', err);
      })
      .finally(() => setExporting(false));
  };
  return <div className="page-toolbar"><button className="ghost-button" onClick={onRefresh} disabled={!onRefresh}><RefreshCw size={14} />刷新</button>{secondary && <button className="outline-button" onClick={handleExport} disabled={exporting || exportDisabled}><Download size={14} />{exporting ? '导出中…' : secondary}</button>}{action && <button className="primary-button" onClick={onAction} disabled={actionDisabled || !onAction}><Plus size={15} />{action}</button>}{exportError && <span className="toolbar-error" role="alert">{exportError}</span>}</div>;
}
