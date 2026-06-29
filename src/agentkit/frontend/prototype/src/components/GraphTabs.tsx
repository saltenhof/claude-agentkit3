export type GraphTab = 'graph' | 'ready' | 'limits';

const TABS: Array<{ id: GraphTab; label: string }> = [
  { id: 'graph', label: 'Story Dependency Graph' },
  { id: 'ready', label: 'Execution Input' },
  { id: 'limits', label: 'Execution Limits' },
];

export function GraphTabs({
  active,
  onChange,
}: {
  active: GraphTab;
  onChange: (tab: GraphTab) => void;
}) {
  return (
    <div className="file-tabs file-tabs--graph" role="tablist" aria-label="Graph-Sichten">
      {TABS.map((tab) => (
        <button
          key={tab.id}
          type="button"
          role="tab"
          aria-selected={active === tab.id}
          className={active === tab.id ? 'active' : ''}
          onClick={() => onChange(tab.id)}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}
