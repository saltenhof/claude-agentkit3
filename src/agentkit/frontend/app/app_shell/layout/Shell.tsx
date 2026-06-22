import {
  BarChart3,
  Bot,
  ChevronDown,
  Columns3,
  GitBranch,
  Grid3X3,
  Library,
  LogOut,
  Plus,
  RefreshCw,
  Search,
  ShieldCheck,
} from 'lucide-react';
import { useState } from 'react';
import type { ReactElement, ReactNode } from 'react';

import type { AppActions, AppData } from '../../App';
import { DependencyGraph } from '../../contexts/execution_planning/components/DependencyGraph';
import { AnalyticsView } from '../../contexts/kpi_analytics/components/AnalyticsView';
import { KpiStrip } from '../../contexts/project_management/components/KpiStrip';
import { KanbanBoard } from '../../contexts/story_context_manager/components/KanbanBoard';
import { StorySheet } from '../../contexts/story_context_manager/components/StorySheet';
import { filterStories } from '../../contexts/story_context_manager/components/storyFilters';
import { DetailInspector } from '../inspector/DetailInspector';
import { setViewModeHash, type ViewMode } from '../routing/viewMode';

interface ShellProps {
  authenticated: boolean;
  data: AppData;
  actions: AppActions;
}

export function Shell({ authenticated, data, actions }: Readonly<ShellProps>): ReactElement {
  const [query, setQuery] = useState('');

  if (!authenticated) {
    return <LoginScreen login={actions.login} error={data.error} loading={data.loading} />;
  }

  const filteredStories = filterStories(data.stories, query);

  return (
    <main className="shell" data-inspector-open={data.selectedStoryId !== null}>
      <aside className="sidebar" aria-label="Hauptnavigation">
        <div className="brand-mark" title="AgentKit 3">
          <ShieldCheck size={24} />
        </div>
        <nav className="nav-stack">
          <NavButton icon={<GitBranch size={21} />} label="Graph" mode="graph" active={data.viewMode === 'graph'} />
          <NavButton icon={<Columns3 size={21} />} label="Kanban" mode="kanban" active={data.viewMode === 'kanban'} />
          <NavButton icon={<Grid3X3 size={21} />} label="Sheet" mode="sheet" active={data.viewMode === 'sheet'} />
          <NavButton icon={<BarChart3 size={21} />} label="Analytics" mode="analytics" active={data.viewMode === 'analytics'} />
          <NavButton icon={<Bot size={21} />} label="Hub" mode="hub" active={data.viewMode === 'hub'} />
          <NavButton icon={<Library size={21} />} label="Concepts" mode="concepts" active={data.viewMode === 'concepts'} />
        </nav>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div className="topbar-title">
            <h1>Story Cockpit</h1>
            <span className="title-separator">|</span>
            <label className="project-heading">
              <span className="sr-only">Projekt</span>
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
              <ChevronDown size={18} aria-hidden="true" />
            </label>
          </div>

          <div className="top-actions">
            <div className="mode-pill" data-mode={data.modeLock?.mode ?? 'idle'}>
              <span>Mode</span>
              <strong>{data.modeLock?.mode ?? 'idle'}</strong>
            </div>
            <label className="search-box">
              <Search size={17} />
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Story, Repo, Modul oder Epic"
              />
            </label>
            <button className="primary-action" type="button" disabled title="Story anlegen">
              <Plus size={18} />
              <span>Story</span>
            </button>
            <IconButton
              icon={<RefreshCw size={18} />}
              label="Neu laden"
              onClick={() => {
                actions.reload().catch(() => undefined);
              }}
            />
            <IconButton
              icon={<LogOut size={18} />}
              label="Abmelden"
              onClick={() => {
                actions.logout().catch(() => undefined);
              }}
            />
          </div>
        </header>

        {data.error !== null && <div className="error-banner">{data.error}</div>}
        {data.offline && <div className="offline-banner">Verbindung verloren</div>}

        <Dashboard data={data} stories={filteredStories} actions={actions} />
      </section>

      {data.selectedStoryId !== null && (
        <DetailInspector
          actions={actions}
          detail={data.selectedStory}
          loading={data.selectedStory === null}
          onClose={() => actions.selectStory(null)}
        />
      )}
    </main>
  );
}

function Dashboard({
  data,
  stories,
  actions,
}: Readonly<{ data: AppData; stories: ReturnType<typeof filterStories>; actions: AppActions }>): ReactElement {
  if (data.selectedProject === null) {
    return <EmptyState title="Keine Projekte" detail="Backend liefert aktuell keine Projektliste." />;
  }
  if (data.loading && data.stories.length === 0) {
    return <div className="loading-state">Lade Daten...</div>;
  }

  return (
    <div className="dashboard">
      <KpiStrip counters={data.counters} executionInput={data.executionInput} stories={data.stories} />
      {data.viewMode === 'graph' && (
        <DependencyGraph dependencies={data.dependencies} stories={stories} onSelectStory={actions.selectStory} />
      )}
      {data.viewMode === 'kanban' && (
        <KanbanBoard stories={stories} selectedStoryId={data.selectedStoryId} onSelectStory={actions.selectStory} />
      )}
      {data.viewMode === 'sheet' && <StorySheet stories={stories} onSelectStory={actions.selectStory} />}
      {data.viewMode === 'analytics' && (
        <AnalyticsView executionLimits={data.executionLimits} stories={stories} />
      )}
      {data.viewMode === 'hub' && (
        <FoundationView
          title="Hub"
          lines={[
            'Multi-LLM-Hub ist projektneutral.',
            'Die produktive Sicht wird an den Hub-Bounded-Context angeschlossen.',
          ]}
        />
      )}
      {data.viewMode === 'concepts' && (
        <FoundationView
          title="Concepts"
          lines={[
            'Concept-Browser ist projektneutral.',
            'Die produktive App ist fuer /v1/concepts vorbereitet.',
          ]}
        />
      )}
    </div>
  );
}

function LoginScreen({
  login,
  error,
  loading,
}: Readonly<{
  login: (username: string, password: string) => Promise<void>;
  error: string | null;
  loading: boolean;
}>): ReactElement {
  const [username, setUsername] = useState('admin');
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
          <span>Nutzer</span>
          <input value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="username" />
        </label>
        <label>
          <span>Passwort</span>
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
}: Readonly<{
  icon: ReactNode;
  label: string;
  mode: ViewMode;
  active: boolean;
}>): ReactElement {
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

function IconButton({
  icon,
  label,
  onClick,
}: Readonly<{ icon: ReactNode; label: string; onClick: () => void }>): ReactElement {
  return (
    <button className="icon-button" type="button" onClick={onClick} title={label}>
      {icon}
    </button>
  );
}

function FoundationView({ title, lines }: Readonly<{ title: string; lines: readonly string[] }>): ReactElement {
  return (
    <div className="foundation-view">
      <h2>{title}</h2>
      {lines.map((line) => <p key={line}>{line}</p>)}
    </div>
  );
}

function EmptyState({ title, detail }: Readonly<{ title: string; detail: string }>): ReactElement {
  return (
    <div className="empty-state">
      <h2>{title}</h2>
      <p>{detail}</p>
    </div>
  );
}
