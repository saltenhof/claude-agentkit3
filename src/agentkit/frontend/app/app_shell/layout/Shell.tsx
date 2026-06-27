import {
  BarChart3,
  Bot,
  ChevronDown,
  Columns3,
  GitBranch,
  Grid3X3,
  LogOut,
  Plus,
  RefreshCw,
  Search,
  ShieldCheck,
} from 'lucide-react';
import { useState } from 'react';
import type { ReactElement, ReactNode } from 'react';

import type { AppActions, AppData } from '../../App';
import type { ProjectSummary } from '../../contexts/project_management/types';
import { ExecutionPlanningView } from '../../contexts/execution_planning/components/ExecutionPlanningView';
import { AnalyticsView } from '../../contexts/kpi_analytics/components/AnalyticsView';
import { HubCockpit } from '../../contexts/multi_llm_hub/components/HubCockpit';
import { KpiStrip } from '../../contexts/project_management/components/KpiStrip';
import { KanbanBoard } from '../../contexts/story_context_manager/components/KanbanBoard';
import { StorySheet } from '../../contexts/story_context_manager/components/StorySheet';
import {
  filterStories,
  type KanbanSortMode,
  type StoryStatusFilter,
} from '../../contexts/story_context_manager/components/storyFilters';
import { DetailInspector } from '../inspector/DetailInspector';
import { setViewModeHash, type ViewMode } from '../routing/viewMode';

interface ShellProps {
  authenticated: boolean;
  data: AppData;
  actions: AppActions;
}

export function Shell({ authenticated, data, actions }: Readonly<ShellProps>): ReactElement {
  const [query, setQuery] = useState('');
  const [kanbanStoryIdFilter, setKanbanStoryIdFilter] = useState('');
  const [kanbanStatusFilter, setKanbanStatusFilter] = useState<StoryStatusFilter>('all');
  const [kanbanSortMode, setKanbanSortMode] = useState<KanbanSortMode>('id');
  const [sheetStatusFilter, setSheetStatusFilter] = useState<StoryStatusFilter>('all');

  if (!authenticated) {
    return <LoginScreen login={actions.login} error={data.error} loading={data.loading} />;
  }

  const searchedStories = filterStories(data.stories, query);

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
        </nav>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div className="topbar-title">
            <h1>Story Cockpit</h1>
            <span className="title-separator">|</span>
            <ProjectSelector
              projects={data.projects}
              selectedProjectKey={data.selectedProject?.project_key ?? ''}
              onSelect={actions.selectProject}
            />
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

        <Dashboard
          data={data}
          stories={searchedStories}
          kanbanStoryIdFilter={kanbanStoryIdFilter}
          kanbanStatusFilter={kanbanStatusFilter}
          kanbanSortMode={kanbanSortMode}
          sheetStatusFilter={sheetStatusFilter}
          actions={actions}
          onKanbanStoryIdFilterChange={setKanbanStoryIdFilter}
          onKanbanStatusFilterChange={setKanbanStatusFilter}
          onKanbanSortModeChange={setKanbanSortMode}
          onSheetStatusFilterChange={setSheetStatusFilter}
        />
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

function ProjectSelector({
  projects,
  selectedProjectKey,
  onSelect,
}: Readonly<{
  projects: ProjectSummary[];
  selectedProjectKey: string;
  onSelect: (projectKey: string) => void;
}>): ReactElement {
  const [open, setOpen] = useState(false);
  const selectedProject =
    projects.find((project) => project.project_key === selectedProjectKey) ?? null;
  const label = selectedProject?.display_name ?? 'Projekt auswählen';
  const disabled = projects.length === 0;

  return (
    <div
      className="project-picker"
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) {
          setOpen(false);
        }
      }}
      onKeyDown={(event) => {
        if (event.key === 'Escape') {
          setOpen(false);
        }
      }}
    >
      <button
        aria-expanded={open}
        aria-haspopup="menu"
        className="project-combo"
        disabled={disabled}
        title={label}
        type="button"
        onClick={() => setOpen((current) => !current)}
      >
        <span className="project-combo__label">{label}</span>
        <ChevronDown size={18} aria-hidden="true" />
      </button>
      {open && !disabled && (
        <div className="project-menu" aria-label="Projekt">
          {projects.map((project) => {
            const selected = project.project_key === selectedProjectKey;
            return (
              <button
                key={project.project_key}
                aria-current={selected ? 'true' : undefined}
                className="project-menu__item"
                data-selected={selected}
                title={project.display_name}
                type="button"
                onClick={() => {
                  onSelect(project.project_key);
                  setOpen(false);
                }}
              >
                <span>{project.display_name}</span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

function Dashboard({
  data,
  stories,
  kanbanStoryIdFilter,
  kanbanStatusFilter,
  kanbanSortMode,
  sheetStatusFilter,
  actions,
  onKanbanStoryIdFilterChange,
  onKanbanStatusFilterChange,
  onKanbanSortModeChange,
  onSheetStatusFilterChange,
}: Readonly<{
  data: AppData;
  stories: ReturnType<typeof filterStories>;
  kanbanStoryIdFilter: string;
  kanbanStatusFilter: StoryStatusFilter;
  kanbanSortMode: KanbanSortMode;
  sheetStatusFilter: StoryStatusFilter;
  actions: AppActions;
  onKanbanStoryIdFilterChange: (value: string) => void;
  onKanbanStatusFilterChange: (value: StoryStatusFilter) => void;
  onKanbanSortModeChange: (value: KanbanSortMode) => void;
  onSheetStatusFilterChange: (value: StoryStatusFilter) => void;
}>): ReactElement {
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
        <ExecutionPlanningView
          dependencies={data.dependencies}
          executionInput={data.executionInput}
          executionLimits={data.executionLimits}
          stories={stories}
          onSelectStory={actions.selectStory}
        />
      )}
      {data.viewMode === 'kanban' && (
        <KanbanBoard
          stories={filterStories(stories, '', kanbanStatusFilter, kanbanStoryIdFilter)}
          totalStoryCount={data.stories.length}
          selectedStoryId={data.selectedStoryId}
          storyIdFilter={kanbanStoryIdFilter}
          statusFilter={kanbanStatusFilter}
          sortMode={kanbanSortMode}
          onSelectStory={actions.selectStory}
          onStoryIdFilterChange={onKanbanStoryIdFilterChange}
          onStatusFilterChange={onKanbanStatusFilterChange}
          onSortModeChange={onKanbanSortModeChange}
        />
      )}
      {data.viewMode === 'sheet' && (
        <StorySheet
          stories={stories}
          selectedStoryId={data.selectedStoryId}
          statusFilter={sheetStatusFilter}
          onSelectStory={actions.selectStory}
          onStatusFilterChange={onSheetStatusFilterChange}
        />
      )}
      {data.viewMode === 'analytics' && (
        <AnalyticsView executionLimits={data.executionLimits} stories={stories} />
      )}
      {data.viewMode === 'hub' && (
        <HubCockpit error={data.hubError} sessions={data.hubSessions} status={data.hubStatus} />
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

function EmptyState({ title, detail }: Readonly<{ title: string; detail: string }>): ReactElement {
  return (
    <div className="empty-state">
      <h2>{title}</h2>
      <p>{detail}</p>
    </div>
  );
}
