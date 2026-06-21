import {
  BarChart3,
  Columns3,
  GitBranch,
  Grid3X3,
  Library,
  LogOut,
  Network,
  RefreshCw,
  Search,
  ShieldCheck,
} from 'lucide-react';
import { useMemo, useState } from 'react';
import type { ReactElement, ReactNode } from 'react';

import type { AppActions, AppData } from '../../App';
import { setViewModeHash, type ViewMode } from '../routing/viewMode';
import { DetailInspector } from '../inspector/DetailInspector';
import type { StoryStatus, StorySummary } from '../../contexts/story_context_manager/types';

interface ShellProps {
  authenticated: boolean;
  data: AppData;
  actions: AppActions;
}

const STATUS_COLUMNS: readonly StoryStatus[] = ['Backlog', 'Approved', 'In Progress', 'Done', 'Cancelled'];

export function Shell({ authenticated, data, actions }: ShellProps): ReactElement {
  const [query, setQuery] = useState('');

  if (!authenticated) {
    return <LoginScreen login={actions.login} error={data.error} loading={data.loading} />;
  }

  const filteredStories = filterStories(data.stories, query);

  return (
    <main className="shell">
      <aside className="sidebar" aria-label="Hauptnavigation">
        <div className="brand-mark" title="AgentKit 3">
          <ShieldCheck size={24} />
        </div>
        <NavButton icon={<GitBranch size={21} />} label="Graph" mode="graph" active={data.viewMode === 'graph'} />
        <NavButton icon={<Columns3 size={21} />} label="Kanban" mode="kanban" active={data.viewMode === 'kanban'} />
        <NavButton icon={<Grid3X3 size={21} />} label="Sheet" mode="sheet" active={data.viewMode === 'sheet'} />
        <NavButton icon={<BarChart3 size={21} />} label="Analytics" mode="analytics" active={data.viewMode === 'analytics'} />
        <NavButton icon={<Network size={21} />} label="Hub" mode="hub" active={data.viewMode === 'hub'} />
        <NavButton icon={<Library size={21} />} label="Concepts" mode="concepts" active={data.viewMode === 'concepts'} />
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div className="project-select">
            <label htmlFor="project-key">Projekt</label>
            <select
              id="project-key"
              value={data.selectedProject?.project_key ?? ''}
              onChange={(event) => actions.selectProject(event.target.value)}
            >
              {data.projects.map((project) => (
                <option key={project.project_key} value={project.project_key}>
                  {project.display_name}
                </option>
              ))}
            </select>
          </div>
          <div className="mode-pill" data-mode={data.modeLock?.mode ?? 'idle'}>
            {data.modeLock?.mode ?? 'idle'}
          </div>
          <label className="search-box">
            <Search size={17} />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Suchen"
            />
          </label>
          <button className="icon-button" type="button" onClick={() => void actions.reload()} title="Neu laden">
            <RefreshCw size={18} />
          </button>
          <button className="icon-button" type="button" onClick={() => void actions.logout()} title="Abmelden">
            <LogOut size={18} />
          </button>
        </header>

        {data.error !== null && <div className="error-banner">{data.error}</div>}
        {data.offline && <div className="offline-banner">Verbindung verloren</div>}

        <Dashboard data={data} stories={filteredStories} actions={actions} />
      </section>

      <DetailInspector
        actions={actions}
        detail={data.selectedStory}
        loading={data.selectedStoryId !== null && data.selectedStory === null}
        onClose={() => actions.selectStory(null)}
      />
    </main>
  );
}

function LoginScreen({
  login,
  error,
  loading,
}: {
  login: (username: string, password: string) => Promise<void>;
  error: string | null;
  loading: boolean;
}): ReactElement {
  const [username, setUsername] = useState('strategist');
  const [password, setPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);

  return (
    <main className="login-page">
      <form
        className="login-panel"
        onSubmit={(event) => {
          event.preventDefault();
          setSubmitting(true);
          login(username, password).finally(() => setSubmitting(false));
        }}
      >
        <div className="login-mark">
          <ShieldCheck size={28} />
          <span>AgentKit 3</span>
        </div>
        <label>
          Nutzer
          <input value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="username" />
        </label>
        <label>
          Passwort
          <input
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            type="password"
            autoComplete="current-password"
          />
        </label>
        {error !== null && <div className="login-error">{error}</div>}
        <button className="primary-button" type="submit" disabled={loading || submitting || password.length === 0}>
          Anmelden
        </button>
      </form>
    </main>
  );
}

function NavButton({
  icon,
  label,
  mode,
  active,
}: {
  icon: ReactNode;
  label: string;
  mode: ViewMode;
  active: boolean;
}): ReactElement {
  return (
    <button
      className="nav-button"
      data-active={active}
      type="button"
      title={label}
      onClick={() => setViewModeHash(mode)}
    >
      {icon}
    </button>
  );
}

function Dashboard({ data, stories, actions }: { data: AppData; stories: StorySummary[]; actions: AppActions }): ReactElement {
  if (data.selectedProject === null) {
    return <EmptyState title="Keine Projekte" detail="Backend liefert aktuell keine Projektliste." />;
  }
  if (data.loading && data.stories.length === 0) {
    return <div className="loading-state">Lade Daten...</div>;
  }

  return (
    <div className="dashboard">
      <KpiStrip data={data} />
      {data.viewMode === 'graph' && <GraphView data={data} stories={stories} actions={actions} />}
      {data.viewMode === 'kanban' && <KanbanView stories={stories} actions={actions} selectedStoryId={data.selectedStoryId} />}
      {data.viewMode === 'sheet' && <SheetView stories={stories} actions={actions} />}
      {data.viewMode === 'analytics' && <AnalyticsView data={data} stories={stories} />}
      {data.viewMode === 'hub' && <FoundationView title="Hub" lines={['Multi-LLM-Hub ist projektneutral.', 'Backend-Status wird nachgeliefert, sobald /v1/hub eine produktive Sicht liefert.']} />}
      {data.viewMode === 'concepts' && <FoundationView title="Concepts" lines={['Concept-Browser ist projektneutral.', 'Die produktive App ist fuer /v1/concepts vorbereitet.']} />}
    </div>
  );
}

function KpiStrip({ data }: { data: AppData }): ReactElement {
  const counters = data.counters;
  const values = [
    ['Stories', counters?.total ?? data.stories.length],
    ['Ready', counters?.ready ?? countStatus(data.stories, 'Approved')],
    ['Running', counters?.running ?? countStatus(data.stories, 'In Progress')],
    ['Done', counters?.finished ?? countStatus(data.stories, 'Done')],
    ['Slots', data.executionInput?.global_slots_left ?? 0],
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

function GraphView({ data, stories, actions }: { data: AppData; stories: StorySummary[]; actions: AppActions }): ReactElement {
  const edges = data.dependencies;
  const positioned = useMemo(() => stories.map((story, index) => ({ story, x: 80 + (index % 4) * 260, y: 70 + Math.floor(index / 4) * 150 })), [stories]);
  const byId = new Map(positioned.map((entry) => [entry.story.story_id, entry]));

  if (stories.length === 0) {
    return <EmptyState title="Keine Stories" detail="+Story zum Anlegen." />;
  }

  return (
    <div className="graph-view">
      <svg viewBox="0 0 1120 680" role="img" aria-label="Dependency Graph">
        {edges.map((edge) => {
          const fromId = edge.from_story_id ?? edge.depends_on_story_id;
          const toId = edge.to_story_id ?? edge.story_id;
          const from = fromId !== undefined ? byId.get(fromId) : undefined;
          const to = toId !== undefined ? byId.get(toId) : undefined;
          if (from === undefined || to === undefined) {
            return null;
          }
          return (
            <line
              className="graph-edge"
              key={`${from.story.story_id}-${to.story.story_id}-${edge.kind}`}
              x1={from.x + 170}
              y1={from.y + 45}
              x2={to.x}
              y2={to.y + 45}
            />
          );
        })}
        {positioned.map(({ story, x, y }) => (
          <g
            className="graph-node"
            key={story.story_id}
            onClick={() => actions.selectStory(story.story_id)}
            tabIndex={0}
          >
            <rect x={x} y={y} width="205" height="92" rx="8" />
            <text x={x + 14} y={y + 27}>{story.story_id}</text>
            <text x={x + 14} y={y + 52}>{truncate(story.title, 28)}</text>
            <text x={x + 14} y={y + 76}>{story.status}</text>
          </g>
        ))}
      </svg>
    </div>
  );
}

function KanbanView({
  stories,
  actions,
  selectedStoryId,
}: {
  stories: StorySummary[];
  actions: AppActions;
  selectedStoryId: string | null;
}): ReactElement {
  return (
    <div className="kanban-board">
      {STATUS_COLUMNS.map((status) => (
        <section className="kanban-column" key={status}>
          <h2>{status}</h2>
          <div className="kanban-list">
            {stories.filter((story) => story.status === status).map((story) => (
              <StoryCard key={story.story_id} story={story} actions={actions} selected={selectedStoryId === story.story_id} />
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}

function StoryCard({ story, actions, selected }: { story: StorySummary; actions: AppActions; selected: boolean }): ReactElement {
  return (
    <article className="story-card" data-selected={selected} onClick={() => actions.selectStory(story.story_id)}>
      <div className="story-card-head">
        <strong>{story.story_id}</strong>
        <span data-risk={story.risk}>{story.risk}</span>
      </div>
      <h3>{story.title}</h3>
      <p>{story.module || story.epic || 'ohne Modul'}</p>
      <div className="story-meta">
        <span>{story.size}</span>
        <span>{story.mode ?? 'standard'}</span>
        <span>{story.repos[0] ?? 'repo?'}</span>
      </div>
    </article>
  );
}

function SheetView({ stories, actions }: { stories: StorySummary[]; actions: AppActions }): ReactElement {
  return (
    <div className="sheet-view">
      <table>
        <thead>
          <tr>
            <th>Story</th>
            <th>Titel</th>
            <th>Status</th>
            <th>Modul</th>
            <th>Repo</th>
            <th>QA</th>
          </tr>
        </thead>
        <tbody>
          {stories.map((story) => (
            <tr key={story.story_id} onClick={() => actions.selectStory(story.story_id)}>
              <td>{story.story_id}</td>
              <td>{story.title}</td>
              <td>{story.status}</td>
              <td>{story.module}</td>
              <td>{story.repos.join(', ')}</td>
              <td>{story.qa_rounds}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function AnalyticsView({ data, stories }: { data: AppData; stories: StorySummary[] }): ReactElement {
  const byStatus = STATUS_COLUMNS.map((status) => ({ status, count: countStatus(stories, status) }));
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
        {data.executionLimits === null ? (
          <p>Keine Limits geladen.</p>
        ) : (
          <dl className="limit-grid">
            {Object.entries(data.executionLimits)
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

function FoundationView({ title, lines }: { title: string; lines: string[] }): ReactElement {
  return (
    <div className="foundation-view">
      <h2>{title}</h2>
      {lines.map((line) => <p key={line}>{line}</p>)}
    </div>
  );
}

function EmptyState({ title, detail }: { title: string; detail: string }): ReactElement {
  return (
    <div className="empty-state">
      <h2>{title}</h2>
      <p>{detail}</p>
    </div>
  );
}

function filterStories(stories: StorySummary[], query: string): StorySummary[] {
  const normalized = query.trim().toLowerCase();
  if (!normalized) {
    return stories;
  }
  return stories.filter((story) =>
    [story.story_id, story.title, story.module, story.epic, story.owner, ...story.repos]
      .join(' ')
      .toLowerCase()
      .includes(normalized),
  );
}

function countStatus(stories: StorySummary[], status: StoryStatus): number {
  return stories.filter((story) => story.status === status).length;
}

function truncate(value: string, limit: number): string {
  return value.length <= limit ? value : `${value.slice(0, limit - 1)}…`;
}
