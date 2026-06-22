import type { ReactElement } from 'react';

import type { ExecutionInputSnapshot } from '../../execution_planning/types';
import type { StorySummary } from '../../story_context_manager/types';
import { countStatus } from '../../story_context_manager/components/storyFilters';
import type { StoryCounters } from '../types';

interface KpiStripProps {
  counters: StoryCounters | null;
  executionInput: ExecutionInputSnapshot | null;
  stories: readonly StorySummary[];
}

export function KpiStrip({ counters, executionInput, stories }: Readonly<KpiStripProps>): ReactElement {
  const values = [
    ['Stories', counters?.total ?? stories.length],
    ['Done', counters?.finished ?? countStatus(stories, 'Done')],
    ['Ready', counters?.ready ?? countStatus(stories, 'Approved')],
    ['In Progress', counters?.running ?? countStatus(stories, 'In Progress')],
    ['Slots', executionInput?.global_slots_left ?? 0],
  ] as const;
  return (
    <div className="kpi-strip">
      {values.map(([label, value]) => (
        <div className="kpi-item" key={label}>
          <span>{label}</span>
          <strong>{value}</strong>
        </div>
      ))}
    </div>
  );
}
