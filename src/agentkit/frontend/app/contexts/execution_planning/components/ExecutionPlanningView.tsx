import { useState } from 'react';
import type { ReactElement } from 'react';

import type { StorySummary } from '../../story_context_manager/types';
import type { DependencyEdge, ExecutionInputSnapshot, ExecutionLimits } from '../types';
import { DependencyGraph } from './DependencyGraph';
import { ExecutionLimitsView } from './ExecutionLimitsView';
import { GraphTabs, type GraphTab } from './GraphTabs';
import { ReadyStackView } from './ReadyStackView';

interface ExecutionPlanningViewProps {
  dependencies: readonly DependencyEdge[];
  executionInput: ExecutionInputSnapshot | null;
  executionLimits: ExecutionLimits | null;
  stories: readonly StorySummary[];
  onSelectStory: (storyId: string) => void;
}

export function ExecutionPlanningView({
  dependencies,
  executionInput,
  executionLimits,
  stories,
  onSelectStory,
}: Readonly<ExecutionPlanningViewProps>): ReactElement {
  const [activeTab, setActiveTab] = useState<GraphTab>('graph');

  return (
    <div className="graph-main">
      <GraphTabs active={activeTab} onChange={setActiveTab} />
      {activeTab === 'graph' && (
        <DependencyGraph dependencies={dependencies} stories={stories} onSelectStory={onSelectStory} />
      )}
      {activeTab === 'ready' && <ReadyStackView input={executionInput} onSelectStory={onSelectStory} />}
      {activeTab === 'limits' && <ExecutionLimitsView limits={executionLimits} />}
    </div>
  );
}
