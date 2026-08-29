import type { ReactNode } from 'react';

export type StatusTone = 'green' | 'orange' | 'red' | 'blue' | 'muted';

export function StatusPill({ children, tone = 'green' }: { children: ReactNode; tone?: StatusTone }) {
  return <span className={`status ${tone}`}>{children}</span>;
}
