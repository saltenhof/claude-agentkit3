import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  BarChart3,
  Bot,
  GitBranch,
  KanbanSquare,
  Plus,
  Search,
  ShieldCheck,
  Table2,
  ChevronDown,
  WifiOff,
} from 'lucide-react';
import type { Edge, Node } from '@xyflow/react';
import { useEdgesState, useNodesState } from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import {
  DEFAULT_EXECUTION_LIMITS,
  type ExecutionLimits,
  type Story,
  type StoryCounters,
  type ProjectModeLock,
} from '../../store';
import { layoutGraph, toGraph } from '../../graph';
import { GraphTabs, type GraphTab } from '../../components/GraphTabs';
import { ReadyStackView } from '../../contexts/execution_planning/ReadyStackView';
import { ExecutionLimitsView } from '../../contexts/execution_planning/ExecutionLimitsView';
import { AnalyticsSlot } from '../../contexts/kpi_analytics/AnalyticsSlot';
import { useProjectSse, KANBAN_TOPICS, GRAPH_TOPICS } from '../../foundation/sse/useProjectSse';
import { ModeIndicator } from './ModeIndicator';
import { DetailInspector } from '../inspector/DetailInspector';
import { Kanban } from '../board/Kanban';
import { StorySheet } from '../sheet/StorySheet';
import { GraphView } from '../../contexts/execution_planning/GraphView';
import { LlmHubView } from '../../foundation/multi_llm_hub/LlmHubView';
import {
  BffClient,
  BffReadError,
  listItemToStory,
  type ProjectItem,
  type StoryDetailResponse,
  type StoryFlowResponse,
  type CoverageAcceptanceResponse,
  type AreEvidenceResponse,
} from '../../foundation/bff/client';
import {
  viewFromLocationHash,
  INSPECTOR_WIDTH_KEY,
  DEFAULT_INSPECTOR_WIDTH,
  MIN_INSPECTOR_WIDTH,
  type ViewMode,
} from '../routing/viewMode';

const bffClient = new BffClient('');

/** Map the wire mode-lock mode into the local ProjectModeLock used by ModeIndicator. */
function toProjectMode(mode: string): ProjectModeLock {
  if (mode === 'fast') return 'fast';
  if (mode === 'standard') return 'standard';
  return null; // 'idle'
}

function errorCodeOf(err: unknown): string {
  if (err instanceof BffReadError) return err.errorCode;
  return 'error';
}

function IconNav({
  active,
  title,
  onClick,
  children,
}: {
  active: boolean;
  title: string;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button className={active ? 'active' : ''} type="button" title={title} onClick={onClick}>
      {children}
    </button>
  );
}

export function App() {
  const [storyState, setStoryState] = useState<Story[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [searchResults, setSearchResults] = useState<Story[] | null>(null);
  const [activeProjectKey, setActiveProjectKey] = useState('AG3');
  const [projects, setProjects] = useState<ProjectItem[]>([]);
  const [projectMenuOpen, setProjectMenuOpen] = useState(false);
  const [statusFilter, setStatusFilter] = useState<'all' | Story['status']>('all');
  const [kanbanStoryIdFilter, setKanbanStoryIdFilter] = useState('');
  const [view, setView] = useState<ViewMode>(viewFromLocationHash);
  const [graphTab, setGraphTab] = useState<GraphTab>('graph');
  const [executionLimits, setExecutionLimits] = useState<ExecutionLimits>(DEFAULT_EXECUTION_LIMITS);
  // Read-model-sourced counters and mode-lock (E2/AC9): NOT local selectors.
  const [counters, setCounters] = useState<StoryCounters>({
    total: 0, finished: 0, running: 0, ready: 0, queue: 0, blocked: 0,
  });
  const [activeMode, setActiveMode] = useState<ProjectModeLock>(null);
  const [selectedStory, setSelectedStory] = useState<Story | null>(null);
  const [storyDetail, setStoryDetail] = useState<StoryDetailResponse | null>(null);
  const [flowSnapshot, setFlowSnapshot] = useState<StoryFlowResponse['story_flow_snapshot'] | null>(null);
  // Coverage read-models (E2/AC9): acceptance + ARE-evidence feed the Evidence tab.
  const [coverageAcceptance, setCoverageAcceptance] =
    useState<CoverageAcceptanceResponse['story_coverage_acceptance'] | null>(null);
  const [coverageAreEvidence, setCoverageAreEvidence] =
    useState<AreEvidenceResponse['story_are_evidence'] | null>(null);
  // Distinguishes "flow not yet loaded" from "flow read failed" (E3/FAIL-CLOSED).
  const [flowError, setFlowError] = useState<string | null>(null);
  // Sheet drafts are owned by the Shell so a project switch can warn before dropping them (E5/AC10h).
  const [hasSheetDrafts, setHasSheetDrafts] = useState(false);
  const [detailOpen, setDetailOpen] = useState(false);
  const [inspectorWidth, setInspectorWidth] = useState(() => {
    const stored = Number(window.localStorage.getItem(INSPECTOR_WIDTH_KEY));
    return Number.isFinite(stored) && stored > 0 ? stored : DEFAULT_INSPECTOR_WIDTH;
  });
  const [resizingInspector, setResizingInspector] = useState(false);
  const [errorPill, setErrorPill] = useState<string | null>(null);
  const [inspectorRequestId, setInspectorRequestId] = useState(0);
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  // Offline state (FK-72 §72.14.6 / AC6): true when SSE cannot connect.
  const [isOffline, setIsOffline] = useState(false);
  // SSE-triggered re-fetch counters: incrementing signals a live-update to the view.
  // Used by the SSE hooks to trigger loadProjectData and re-render dependent sub-views.
  const [_kanbanSseRevision, setKanbanSseRevision] = useState(0);
  const [_graphSseRevision, setGraphSseRevision] = useState(0);

  const inspectorRequestIdRef = useRef(0);

  const showErrorPill = useCallback((msg: string) => {
    setErrorPill(msg);
    window.setTimeout(() => setErrorPill(null), 4000);
  }, []);

  const activeProject = useMemo(
    () => projects.find((p) => p.key === activeProjectKey) ?? null,
    [projects, activeProjectKey],
  );
  const projectArchived = activeProject?.status === 'archived';

  // ── Load all view read-models for a project (E2/AC9) ──────────────────────
  // Every REQUIRED read surfaces a visible error pill on failure (E4/FAIL-CLOSED).
  // No silent default fallback, no swallowed catch.

  const loadProjectData = useCallback(
    async (projectKey: string): Promise<void> => {
      const [storiesRes, countersRes, modeLockRes, limitsRes] = await Promise.allSettled([
        bffClient.listStories(projectKey),
        bffClient.getStoryCounters(projectKey),
        bffClient.getModeLock(projectKey),
        bffClient.getExecutionLimits(projectKey),
      ]);

      const failures: string[] = [];

      if (storiesRes.status === 'fulfilled') {
        setStoryState(storiesRes.value.stories.map(listItemToStory));
      } else {
        failures.push(`Stories (${errorCodeOf(storiesRes.reason)})`);
      }

      if (countersRes.status === 'fulfilled') {
        setCounters(countersRes.value.story_counters);
      } else {
        failures.push(`Counters (${errorCodeOf(countersRes.reason)})`);
      }

      if (modeLockRes.status === 'fulfilled') {
        setActiveMode(toProjectMode(modeLockRes.value.mode_lock.mode));
      } else {
        failures.push(`Mode-Lock (${errorCodeOf(modeLockRes.reason)})`);
      }

      if (limitsRes.status === 'fulfilled') {
        const lim = limitsRes.value.execution_limits;
        setExecutionLimits({
          repoParallelCap: lim.repo_parallel_cap,
          mergeRiskCap: lim.merge_risk_cap,
          maxParallelAgentCap: lim.max_parallel_agent_cap,
          llmPoolCap: lim.llm_pool_cap,
          ciCapacityCap: lim.ci_capacity_cap,
        });
      } else {
        failures.push(`Limits (${errorCodeOf(limitsRes.reason)})`);
      }

      if (failures.length > 0) {
        setLoadError(`Fehler beim Laden: ${failures.join(', ')}`);
      } else {
        setLoadError(null);
      }
    },
    [],
  );

  // ── Initial data load ─────────────────────────────────────────────────────

  useEffect(() => {
    let cancelled = false;

    async function bootstrap(): Promise<void> {
      let firstKey = activeProjectKey;
      try {
        const resp = await bffClient.listProjects();
        if (cancelled) return;
        setProjects(resp.projects);
        if (resp.projects.length > 0 && resp.projects[0]) {
          firstKey = resp.projects[0].key;
          setActiveProjectKey(firstKey);
        }
      } catch (err: unknown) {
        if (cancelled) return;
        // E4/FAIL-CLOSED: project list is required — surface the error, do NOT
        // silently fall back to a default project that hides backend unavailability.
        setLoadError(`Projekte konnten nicht geladen werden (${errorCodeOf(err)}).`);
        return;
      }
      if (!cancelled) await loadProjectData(firstKey);
    }

    void bootstrap();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── Search via BFF (E4: surface failures, no silent clear) ─────────────────

  useEffect(() => {
    const needle = query.trim();
    if (!needle) {
      setSearchResults(null);
      return;
    }
    let cancelled = false;
    bffClient
      .searchStories(activeProjectKey, needle)
      .then((resp) => {
        if (cancelled) return;
        setSearchResults(resp.stories.map(listItemToStory));
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        // FAIL-CLOSED: a failed search surfaces an error pill instead of silently
        // clearing the result set (which would masquerade as "no matches").
        setSearchResults([]);
        showErrorPill(`Suche fehlgeschlagen (${errorCodeOf(err)}).`);
      });
    return () => {
      cancelled = true;
    };
  }, [query, activeProjectKey, showErrorPill]);

  const visibleStories = useMemo(() => {
    const base = searchResults ?? storyState;
    if (searchResults !== null) {
      // Search results already filtered by the backend; only apply the status facet.
      return base.filter((story) => statusFilter === 'all' || story.status === statusFilter);
    }
    return base.filter((story) => statusFilter === 'all' || story.status === statusFilter);
  }, [statusFilter, storyState, searchResults]);

  useEffect(() => {
    let stale = false;
    const highlightId = detailOpen && selectedStory ? selectedStory.id : null;
    const graph = toGraph(visibleStories, highlightId);
    layoutGraph(graph.nodes, graph.edges).then((layouted) => {
      if (!stale) {
        setNodes(layouted.nodes);
        setEdges(layouted.edges);
      }
    });
    return () => {
      stale = true;
    };
  }, [detailOpen, selectedStory, visibleStories, setEdges, setNodes]);

  const resetInspectorReads = useCallback(() => {
    setStoryDetail(null);
    setFlowSnapshot(null);
    setFlowError(null);
    setCoverageAcceptance(null);
    setCoverageAreEvidence(null);
  }, []);

  const selectStory = useCallback((story: Story) => {
    setSelectedStory(story);
    setDetailOpen(true);
    resetInspectorReads();
    setInspectorRequestId((id) => id + 1);
  }, [resetInspectorReads]);

  const focusStory = useCallback((story: Story) => {
    setSelectedStory(story);
  }, []);

  // Fetch story detail + flow when inspector opens — REAL BFF calls (AC9).
  // last-request-wins guards both against out-of-order responses (AC10e).
  useEffect(() => {
    if (!detailOpen || !selectedStory) return;
    const myRequestId = inspectorRequestId;
    inspectorRequestIdRef.current = myRequestId;
    const storyId = selectedStory.id;
    const projectKey = activeProjectKey;

    bffClient
      .getStoryDetail(projectKey, storyId)
      .then((detail) => {
        if (inspectorRequestIdRef.current !== myRequestId) return;
        setStoryDetail(detail);
      })
      .catch((err: unknown) => {
        if (inspectorRequestIdRef.current !== myRequestId) return;
        if (err instanceof BffReadError && err.status === 404) {
          // AC10d: story deleted -> close inspector + notice pill.
          setDetailOpen(false);
          setStoryDetail(null);
          showErrorPill('Story wurde entfernt.');
        } else {
          showErrorPill(`Fehler beim Laden der Story-Details (${errorCodeOf(err)}).`);
        }
      });

    // Flow tab read-model (E3/AC9/AC10f): pipeline_engine flow snapshot from
    // AG3-091. This is a REQUIRED inspector read — there is no local heuristic
    // fallback. A failure surfaces a visible error so the tab fails closed.
    bffClient
      .getStoryFlow(projectKey, storyId)
      .then((flow) => {
        if (inspectorRequestIdRef.current !== myRequestId) return;
        setFlowSnapshot(flow.story_flow_snapshot);
        setFlowError(null);
      })
      .catch((err: unknown) => {
        if (inspectorRequestIdRef.current !== myRequestId) return;
        setFlowSnapshot(null);
        setFlowError(errorCodeOf(err));
        showErrorPill(`Flow konnte nicht geladen werden (${errorCodeOf(err)}).`);
      });

    // Evidence-tab coverage read-models (E2/AC9): acceptance + ARE-evidence.
    bffClient
      .getCoverageAcceptance(projectKey, storyId)
      .then((cov) => {
        if (inspectorRequestIdRef.current !== myRequestId) return;
        setCoverageAcceptance(cov.story_coverage_acceptance);
      })
      .catch((err: unknown) => {
        if (inspectorRequestIdRef.current !== myRequestId) return;
        setCoverageAcceptance(null);
        showErrorPill(`Coverage konnte nicht geladen werden (${errorCodeOf(err)}).`);
      });

    bffClient
      .getCoverageAreEvidence(projectKey, storyId)
      .then((are) => {
        if (inspectorRequestIdRef.current !== myRequestId) return;
        setCoverageAreEvidence(are.story_are_evidence);
      })
      .catch((err: unknown) => {
        if (inspectorRequestIdRef.current !== myRequestId) return;
        setCoverageAreEvidence(null);
        showErrorPill(`ARE-Evidenz konnte nicht geladen werden (${errorCodeOf(err)}).`);
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [detailOpen, inspectorRequestId, activeProjectKey]);

  const changeStoryStatus = useCallback((storyId: string, status: Story['status']) => {
    setStoryState((currentStories) =>
      currentStories.map((story) => (story.id === storyId ? { ...story, status } : story)),
    );
    setSelectedStory((prev) => (prev && prev.id === storyId ? { ...prev, status } : prev));
  }, []);

  const onNodeClick = useCallback((_event: React.MouseEvent, node: Node) => {
    const story = node.data as unknown as Story;
    setSelectedStory(story);
    setDetailOpen(true);
    resetInspectorReads();
    setInspectorRequestId((id) => id + 1);
  }, [resetInspectorReads]);

  // Hash sync
  useEffect(() => {
    const nextHash = `#${view}`;
    if (window.location.hash !== nextHash) {
      window.history.replaceState(null, '', nextHash);
    }
  }, [view]);

  useEffect(() => {
    const onHashChange = () => setView(viewFromLocationHash());
    window.addEventListener('hashchange', onHashChange);
    return () => window.removeEventListener('hashchange', onHashChange);
  }, []);

  // Keyboard navigation
  useEffect(() => {
    const moveSelection = (direction: 1 | -1) => {
      const openAndSelect = (next: Story | undefined) => {
        if (!next) return;
        setSelectedStory(next);
        setDetailOpen(true);
        resetInspectorReads();
        setInspectorRequestId((id) => id + 1);
      };
      if (!selectedStory) {
        openAndSelect(visibleStories[direction === 1 ? 0 : visibleStories.length - 1]);
        return;
      }
      const index = visibleStories.findIndex((story) => story.id === selectedStory.id);
      const fallbackIndex = index < 0 ? 0 : index;
      openAndSelect(
        visibleStories[Math.min(Math.max(fallbackIndex + direction, 0), visibleStories.length - 1)],
      );
    };

    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target && typeof target.matches === 'function' && target.matches('input, textarea, select')) return;
      if (view === 'kanban' && ['ArrowDown', 'ArrowUp', 'ArrowRight', 'ArrowLeft'].includes(event.key)) return;
      if (event.key === 'ArrowDown') {
        event.preventDefault();
        moveSelection(1);
      }
      if (event.key === 'ArrowUp') {
        event.preventDefault();
        moveSelection(-1);
      }
      if (event.key === 'Escape') {
        setDetailOpen(false);
      }
    };

    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [selectedStory, view, visibleStories, resetInspectorReads]);

  // Inspector close on outside click
  useEffect(() => {
    if (!detailOpen) return;
    const onPointerDown = (event: PointerEvent) => {
      const target = event.target as HTMLElement | null;
      if (!target) return;
      if (target.closest('[data-story-inspector="true"]')) return;
      if (target.closest('[data-story-interactive="true"]')) return;
      setDetailOpen(false);
    };
    document.addEventListener('pointerdown', onPointerDown);
    return () => document.removeEventListener('pointerdown', onPointerDown);
  }, [detailOpen]);

  // Inspector resize drag
  useEffect(() => {
    if (!resizingInspector) return;
    const onMouseMove = (event: MouseEvent) => {
      const maxWidth = Math.max(MIN_INSPECTOR_WIDTH, window.innerWidth - 96);
      const nextWidth = Math.min(
        Math.max(window.innerWidth - event.clientX - 14, MIN_INSPECTOR_WIDTH),
        maxWidth,
      );
      setInspectorWidth(nextWidth);
    };
    const onMouseUp = () => setResizingInspector(false);
    document.body.classList.add('is-resizing-inspector');
    window.addEventListener('mousemove', onMouseMove);
    window.addEventListener('mouseup', onMouseUp);
    return () => {
      document.body.classList.remove('is-resizing-inspector');
      window.removeEventListener('mousemove', onMouseMove);
      window.removeEventListener('mouseup', onMouseUp);
    };
  }, [resizingInspector]);

  // Persist inspector width
  useEffect(() => {
    window.localStorage.setItem(INSPECTOR_WIDTH_KEY, String(Math.round(inspectorWidth)));
  }, [inspectorWidth]);

  // Project menu close on outside click
  useEffect(() => {
    if (!projectMenuOpen) return;
    const onPointerDown = (event: PointerEvent) => {
      const target = event.target as HTMLElement | null;
      if (target?.closest('[data-project-menu="true"]')) return;
      setProjectMenuOpen(false);
    };
    document.addEventListener('pointerdown', onPointerDown);
    return () => document.removeEventListener('pointerdown', onPointerDown);
  }, [projectMenuOpen]);

  // AC10h: Project switch — close inspector, warn before dropping sheet drafts,
  // keep the view selection.
  const handleProjectSwitch = useCallback(
    (key: string) => {
      if (key === activeProjectKey) {
        setProjectMenuOpen(false);
        return;
      }
      if (hasSheetDrafts) {
        // Drafts are lost on switch — warn the user (AC10h).
        showErrorPill('Nicht gespeicherte Sheet-Entwürfe gehen durch den Projektwechsel verloren.');
      }
      setActiveProjectKey(key);
      setProjectMenuOpen(false);
      setDetailOpen(false);
      resetInspectorReads();
      setSelectedStory(null);
      setHasSheetDrafts(false);
      setQuery('');
      setSearchResults(null);
      void loadProjectData(key);
    },
    [activeProjectKey, hasSheetDrafts, loadProjectData, resetInspectorReads, showErrorPill],
  );

  const activeProjectName = activeProject?.name ?? activeProjectKey;
  // E3 / AC6: mutating UI is disabled when archived OR when SSE is offline.
  // Total-offline must disable ALL mutating controls, not just archived (FAIL-CLOSED).
  const mutateLocked = projectArchived || isOffline;

  // ── Mode-lock refresh callback (E2 / AC5) ────────────────────────────────────
  // Called by AnalyticsSlot on a telemetry SSE event so mode-lock stays current.
  const refreshModeLock = useCallback(async () => {
    try {
      const modeLockRes = await bffClient.getModeLock(activeProjectKey);
      setActiveMode(toProjectMode(modeLockRes.mode_lock.mode));
    } catch {
      // Non-blocking: mode-lock refresh failure is surfaced via the existing error pill
      // if the next full loadProjectData fails; a silent single-call failure is tolerated.
    }
  }, [activeProjectKey]);

  // ── SSE: Kanban/Board — topics: stories, phases (FK-72 §72.5 / FK-91 §91.8.3) ──
  // Re-sync: reload stories + counters on reconnect or relevant event.
  useProjectSse({
    baseUrl: '',
    projectKey: activeProjectKey,
    topics: KANBAN_TOPICS,
    onReconnect: () => {
      // Lossy re-sync: fresh initial-GET (FK-72 §72.12.4 Z.306).
      void loadProjectData(activeProjectKey);
    },
    onEvent: (event) => {
      // stories/phases events: re-fetch or increment revision for patch.
      if (event.topic === 'stories' || event.topic === 'phases') {
        setKanbanSseRevision((r) => r + 1);
        void loadProjectData(activeProjectKey);
      }
    },
    onOffline: () => setIsOffline(true),
    onOnline: () => setIsOffline(false),
    enabled: view === 'kanban' || view === 'sheet',
  });

  // ── SSE: Graph (incl. sub-tabs graph/ready/limits) — topic: planning ──────
  // planning topic owns dependency_graph_changed / execution_input_changed / limits_changed.
  useProjectSse({
    baseUrl: '',
    projectKey: activeProjectKey,
    topics: GRAPH_TOPICS,
    onReconnect: () => {
      void loadProjectData(activeProjectKey);
    },
    onEvent: (event) => {
      if (event.topic === 'planning') {
        setGraphSseRevision((r) => r + 1);
        void loadProjectData(activeProjectKey);
      }
    },
    onOffline: () => setIsOffline(true),
    onOnline: () => setIsOffline(false),
    enabled: view === 'graph',
  });

  return (
    <main className="shell">
      {errorPill && (
        <div className="error-pill error-pill--global" role="alert">
          {errorPill}
        </div>
      )}
      {loadError && (
        <div className="error-pill error-pill--global" role="alert">
          {loadError}
        </div>
      )}
      <aside className="sidebar">
        <div className="brand">
          <ShieldCheck size={22} />
          <div>
            <strong>AgentKit 3</strong>
            <span>{activeProjectKey}</span>
          </div>
        </div>
        <nav className="nav">
          <IconNav active={view === 'graph'} title="Dependency Graph" onClick={() => setView('graph')}>
            <GitBranch size={18} />
          </IconNav>
          <IconNav active={view === 'kanban'} title="Kanban" onClick={() => setView('kanban')}>
            <KanbanSquare size={18} />
          </IconNav>
          <IconNav active={view === 'sheet'} title="Story Sheet" onClick={() => setView('sheet')}>
            <Table2 size={18} />
          </IconNav>
          <IconNav active={view === 'analytics'} title="Analytics" onClick={() => setView('analytics')}>
            <BarChart3 size={18} />
          </IconNav>
          <IconNav active={view === 'hub'} title="LLM Hub" onClick={() => setView('hub')}>
            <Bot size={18} />
          </IconNav>
        </nav>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div className="topbar-title">
            <h1>Story Cockpit</h1>
            <span className="title-separator" aria-hidden="true">
              |
            </span>
            <div className="project-heading" data-project-menu="true">
              <button
                className="project-heading__button"
                type="button"
                aria-expanded={projectMenuOpen}
                onClick={() => setProjectMenuOpen((open) => !open)}
              >
                <span>{activeProjectName}</span>
                {projectArchived && <span className="project-archived-pill">archiviert</span>}
                <ChevronDown size={18} />
              </button>
              {projectMenuOpen && (
                <div className="project-menu">
                  {projects.map((candidate) => (
                    <button
                      className={candidate.key === activeProjectKey ? 'active' : ''}
                      key={candidate.key}
                      type="button"
                      onClick={() => handleProjectSwitch(candidate.key)}
                    >
                      <span>
                        {candidate.name}
                        {candidate.status === 'archived' && (
                          <span className="project-archived-pill">archiviert</span>
                        )}
                      </span>
                      <small>{candidate.key}</small>
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>
          <div className="top-actions">
            {isOffline && (
              <span className="offline-indicator" role="status" data-testid="offline-indicator">
                <WifiOff size={14} />
                Verbindung verloren
              </span>
            )}
            <ModeIndicator mode={activeMode} />
            <div className="ak-input search">
              <Search size={17} />
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Story, Repo, Modul oder Epic"
              />
            </div>
            <button
              className="ak-button ak-button--primary"
              type="button"
              disabled={mutateLocked}
              title={
                projectArchived
                  ? 'Archiviertes Projekt — keine Mutationen möglich.'
                  : isOffline
                    ? 'Verbindung verloren — keine Mutationen möglich.'
                    : undefined
              }
            >
              <Plus size={16} />
              Story
            </button>
          </div>
        </header>

        <section className="content">
          <div className="left-panel">
            {view === 'kanban' && (
              <Kanban
                projectKey={activeProjectKey}
                stories={visibleStories}
                selectedStory={selectedStory}
                onSelect={selectStory}
                onFocusStory={focusStory}
                onStoryStatusChange={changeStoryStatus}
                storyIdFilter={kanbanStoryIdFilter}
                onStoryIdFilterChange={setKanbanStoryIdFilter}
                kpis={counters}
                readOnly={mutateLocked}
              />
            )}
            {view === 'sheet' && (
              <StorySheet
                projectKey={activeProjectKey}
                stories={visibleStories}
                selectedStory={selectedStory}
                statusFilter={statusFilter}
                onSelect={selectStory}
                onStatusFilterChange={setStatusFilter}
                kpis={counters}
                readOnly={mutateLocked}
                onDraftsChange={setHasSheetDrafts}
              />
            )}
            {view === 'analytics' && (
              <AnalyticsSlot
                projectKey={activeProjectKey}
                baseUrl=""
                isOffline={isOffline}
                onTelemetryEvent={() => { void refreshModeLock(); }}
                onOfflineChange={setIsOffline}
              />
            )}
            {view === 'hub' && <LlmHubView />}
            {view === 'graph' && (
              <div className="graph-main">
                <GraphTabs active={graphTab} onChange={setGraphTab} />
                {graphTab === 'graph' && (
                  <GraphView
                    nodes={nodes}
                    edges={edges}
                    onNodeClick={onNodeClick}
                    onNodesChange={onNodesChange}
                    onEdgesChange={onEdgesChange}
                  />
                )}
                {graphTab === 'ready' && (
                  <ReadyStackView stories={storyState} limits={executionLimits} onSelect={selectStory} />
                )}
                {graphTab === 'limits' && (
                  <ExecutionLimitsView limits={executionLimits} onChange={setExecutionLimits} disabled={mutateLocked} />
                )}
              </div>
            )}
          </div>
        </section>
      </section>

      {detailOpen && selectedStory && (
        <DetailInspector
          story={selectedStory}
          storyDetail={storyDetail}
          flowSnapshot={flowSnapshot}
          flowError={flowError}
          coverageAcceptance={coverageAcceptance}
          coverageAreEvidence={coverageAreEvidence}
          width={inspectorWidth}
          onClose={() => setDetailOpen(false)}
          onResizeStart={() => setResizingInspector(true)}
        />
      )}
    </main>
  );
}
