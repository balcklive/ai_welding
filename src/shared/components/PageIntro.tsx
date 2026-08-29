import type { ReactNode } from 'react';

interface PageIntroProps {
  eyebrow: string;
  title: string;
  description: string;
  action?: ReactNode;
}

export function PageIntro({ eyebrow, title, description, action }: PageIntroProps) {
  return (
    <div className="page-intro">
      <div>
        <div className="eyebrow"><span />{eyebrow}</div>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {action}
    </div>
  );
}
