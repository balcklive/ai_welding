import { useEffect, useState } from 'react';
import { getLabelStudioTask } from '../api/analysis';
import type { LabelStudioTask } from '../api/types';

/**
 * 轮询标注任务的 LS 同步状态（一期·轨道 A 前端切片）。
 *
 * `ls_status` 语义：pending_ls / annotating → 嵌入 LS 工作台；synced → 全部回写（切只读）；
 * legacy → 未走 LS（off/回退）。pending_ls/annotating 期间每 3s 轮询；synced 停止；
 * legacy 且标注 job 未终态（`jobDone=false`，此时 executor 可能即将把任务置 pending_ls）继续轮询，
 * 直到 job 终态（off 路径 `simulate_annotation` 会 succeeded）才停——否则会在 handler 运行前的
 * 短暂 `legacy` 窗口停止轮询而错过 LS 态。
 */
export function useLabelStudioTask(taskId: string | null, jobDone: boolean) {
  const [lsTask, setLsTask] = useState<LabelStudioTask | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    if (!taskId) {
      setLsTask(null);
      setFailed(false);
      return;
    }
    let cancelled = false;
    let timer: number | undefined;
    const poll = () => {
      getLabelStudioTask(taskId)
        .then((t) => {
          if (cancelled) return;
          setLsTask(t);
          setFailed(false);
          if (t.ls_status === 'synced') return; // 回写完成，停止
          if (t.ls_status === 'legacy' && jobDone) return; // 确证 off 路径（simulate 已终态），停止
          timer = window.setTimeout(poll, 3000);
        })
        .catch((err) => {
          if (cancelled) return;
          setFailed(true);
          console.warn('[labelstudio] getLabelStudioTask failed', err);
          timer = window.setTimeout(poll, 5000);
        });
    };
    poll();
    return () => {
      cancelled = true;
      if (timer) window.clearTimeout(timer);
    };
  }, [taskId, jobDone]);
  return { lsTask, failed };
}
