import type { ReactNode } from 'react';

export function Badge({ tone = 'neutral', children }: { tone?: string; children: ReactNode }) {
  return <span className={`ak-badge tone-${tone}`}>{children}</span>;
}
