import type { ReactNode } from 'react';

/** 上下文条的一项：标签 + 值（+ 可选补充说明）。 */
export interface ContextItem {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
}

/**
 * 页面上下文条（T6.1）：`所属数据集 | 数据 | 数据版本 | 状态  [更换]`。
 *
 * 只在页面绑定到某个对象时出现；无业务逻辑、不碰接口，值由调用方给。
 * 顶部的「当前处理数据」选择器（`SelectionSwitcher`）是它的全局版本，由 App 渲染在
 * 面包屑之后；本组件用于数据集层级里那些需要额外说明"当前在看哪个数据集版本"的页面。
 */
export function ContextBar({ items, action }: { items: ContextItem[]; action?: ReactNode }) {
  return (
    <div className="context-bar">
      {items.map((item) => (
        <div key={item.label}>
          <span>{item.label}</span>
          <strong>{item.value}</strong>
          {item.hint != null && <small>{item.hint}</small>}
        </div>
      ))}
      {action && <div className="context-bar-actions">{action}</div>}
    </div>
  );
}
