import type { ReactNode } from 'react';

/** 面包屑的一段；带 `onClick` 的渲染成可点（回上一级）。 */
export interface Crumb {
  label: string;
  onClick?: () => void;
}

/**
 * 面包屑（T6.1/T6.2）：全站一套用词，与术语表一致
 * （`docs/数据管理改造技术实施方案.md` §T6.2 的表）。
 */
export function PageBreadcrumb({ crumbs }: { crumbs: Crumb[] }) {
  return (
    <nav className="page-breadcrumb" aria-label="面包屑">
      {crumbs.map((crumb, index) => (
        <span key={`${crumb.label}-${index}`}>
          {index > 0 && <i>/</i>}
          {crumb.onClick ? (
            <button type="button" onClick={crumb.onClick}>{crumb.label}</button>
          ) : (
            <span>{crumb.label}</span>
          )}
        </span>
      ))}
    </nav>
  );
}

/**
 * 页面骨架（T6.1）：**面包屑 → 上下文条（可选）→ 主体**。
 *
 * 工作区头（eyebrow/title/toolbar）在 `App.tsx` 的 `WorkspaceFrame` 里，不属于本组件；
 * 需要全局上下文条的页面（核验/版本等）由框架把面包屑与 `SelectionSwitcher` 渲染在页面之上，
 * 顺序同样是 头 → 面包屑 → 上下文条 → 主体。
 */
export function PageScaffold({ crumbs, context, children }: { crumbs: Crumb[]; context?: ReactNode; children: ReactNode }) {
  return (
    <>
      <PageBreadcrumb crumbs={crumbs} />
      {context}
      {children}
    </>
  );
}
