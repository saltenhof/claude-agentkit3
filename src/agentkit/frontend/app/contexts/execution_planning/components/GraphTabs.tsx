import type { ReactElement } from 'react';

export type GraphTab = 'graph' | 'ready' | 'limits';

const GRAPH_TABS: Array<{ id: GraphTab; label: string }> = [
  { id: 'graph', label: 'Story Dependency Graph' },
  { id: 'ready', label: 'Execution Input' },
  { id: 'limits', label: 'Execution Limits' },
];

interface GraphTabsProps {
  active: GraphTab;
  onChange: (tab: GraphTab) => void;
}

export function GraphTabs({ active, onChange }: Readonly<GraphTabsProps>): ReactElement {
  return (
    <div className="graph-tabs" role="tablist" aria-label="Graph-Sichten">
      {GRAPH_TABS.map((tab) => (
        <button
          aria-selected={active === tab.id}
          className={active === tab.id ? 'active' : ''}
          key={tab.id}
          role="tab"
          type="button"
          onClick={() => onChange(tab.id)}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}
