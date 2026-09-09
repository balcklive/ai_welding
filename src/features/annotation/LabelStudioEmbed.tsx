import { useState } from 'react';
import type { LabelStudioTask } from '../../api/types';

/**
 * Label Studio 嵌入（一期·轨道 A 前端切片）：把 LS 标注工作台以 iframe 嵌进主应用「数据标注」页，
 * 用户在主应用页面内完成标注；LS 回写后由父组件切到只读结果。`ls_status` 语义（决策 1/2/5）：
 *   pending_ls / annotating → 嵌入 LS；synced → 全部回写（父组件走只读）；legacy → 未走 LS（off/回退）。
 *
 * 仅图像（检测）链路当前端到端可走 LS；时序/视频媒体导出未落地（计划 Track A line 68）。
 * 轮询逻辑见 `src/hooks/useLabelStudioTask`。
 */

/** 图像标注页内的 LS 工作台：项目页 iframe + 「在新标签页打开」兜底。 */
export function LabelStudioEmbed({ lsTask }: { lsTask: LabelStudioTask }) {
  const project = lsTask.ls_project_ids?.[0];
  const url = lsTask.ls_public_url;
  const frameSrc = url && project != null && Number.isInteger(project) ? `${url}/projects/${project}/` : null;
  // 内嵌加载态：iframe 首次加载 LS 工作台前显示提示，避免白屏；onLoad 后淡入。
  const [loaded, setLoaded] = useState(false);
  return (
    <section className="panel annotation-board">
      <div className="board-toolbar">
        <div>
          <span className="file-badge">标注工作台</span>
          <h2>图像标注 · 内嵌工作台</h2>
        </div>
      </div>
      <div
        className="ls-embed-stage"
        style={{ position: 'relative', width: '100%', height: '70vh', minHeight: 480, overflow: 'hidden', borderRadius: 8, border: '1px solid #e5e7eb' }}
      >
        {frameSrc ? (
          <>
            {!loaded && (
              <div
                className="selection-required ls-embed-loading"
                style={{ position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, borderRadius: 8, border: 'none', background: 'rgba(255,255,255,0.92)', zIndex: 1 }}
              >
                <span style={{ fontSize: 13, color: '#84999a' }}>正在连接 Label Studio 工作台…</span>
              </div>
            )}
            <iframe
              className="ls-embed-frame"
              src={frameSrc}
              title="Label Studio 标注工作台"
              onLoad={() => setLoaded(true)}
              style={{ width: '100%', height: '100%', border: 'none', opacity: loaded ? 1 : 0, transition: 'opacity 0.25s ease' }}
              allowFullScreen
            />
          </>
        ) : (
          <div className="selection-required">Label Studio 任务初始化中…</div>
        )}
      </div>
      <div className="stage-tip">
        标注可在这块内嵌工作台里直接完成，保存后自动回写，回写完成切到主应用只读结果。
      </div>
    </section>
  );
}
