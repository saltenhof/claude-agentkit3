import type { ReactElement } from 'react';

import type { ExecutionLimits } from '../../execution_planning/types';
import type { StorySummary } from '../../story_context_manager/types';
import { countStatus, STORY_STATUS_COLUMNS } from '../../story_context_manager/components/storyFilters';

interface AnalyticsViewProps {
  executionLimits: ExecutionLimits | null;
  stories: readonly StorySummary[];
}

export function AnalyticsView({ executionLimits, stories }: Readonly<AnalyticsViewProps>): ReactElement {
  const byStatus = STORY_STATUS_COLUMNS.map((status) => ({ status, count: countStatus(stories, status) }));
  const max = Math.max(1, ...byStatus.map((entry) => entry.count));
  return (
    <div className="analytics-view">
      <section>
        <h2>Statusverteilung</h2>
        {byStatus.map((entry) => (
          <div className="bar-row" key={entry.status}>
            <span>{entry.status}</span>
            <div><i style={{ width: `${(entry.count / max) * 100}%` }} /></div>
            <strong>{entry.count}</strong>
          </div>
        ))}
      </section>
      <section>
        <h2>Execution Limits</h2>
        {executionLimits === null ? (
          <p>Keine Limits geladen.</p>
        ) : (
          <dl className="limit-grid">
            {Object.entries(executionLimits)
              .filter(([key]) => key !== 'project_key')
              .map(([key, value]) => (
                <div key={key}>
                  <dt>{key}</dt>
                  <dd>{value}</dd>
                </div>
              ))}
          </dl>
        )}
      </section>
    </div>
  );
}
