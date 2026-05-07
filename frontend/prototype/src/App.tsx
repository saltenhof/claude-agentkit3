import { Fragment, useCallback, useEffect, useMemo, useState } from 'react';
import type { CSSProperties, ReactNode } from 'react';
import {
  Background,
  BaseEdge,
  Controls,
  Handle,
  MiniMap,
  Position,
  ReactFlow,
  getBezierPath,
  type Edge,
  useEdgesState,
  useNodesState,
  type EdgeProps,
  type EdgeTypes,
  type Node,
  type NodeProps,
  type NodeTypes,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import {
  Activity,
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  BarChart3,
  Bot,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  CircleDot,
  Copy,
  Download,
  Edit3,
  Filter,
  GitBranch,
  Group,
  KanbanSquare,
  ListFilter,
  MoreHorizontal,
  PauseCircle,
  Play,
  Plus,
  Search,
  Send,
  ShieldCheck,
  Table2,
  X,
  XCircle,
} from 'lucide-react';
import { conceptAnchors, project, projects, rulebookStressStories as initialStories, type PhaseStatus, type Story } from './data';
import { layoutGraph, toGraph } from './graph';
import { KpiBar } from './components/KpiBar';
import { buildStoryKpiTiles, type StoryCounters } from './lib/storyKpis';

type ViewMode = 'graph' | 'kanban' | 'sheet' | 'analytics' | 'hub';
const INSPECTOR_WIDTH_KEY = 'ak3.storyInspector.width';
const SHEET_COLUMN_WIDTHS_KEY = 'ak3.storySheet.columnWidths';
const DEFAULT_INSPECTOR_WIDTH = 858;
const MIN_INSPECTOR_WIDTH = 560;
const STORY_STATUSES: Story['status'][] = ['Backlog', 'Approved', 'In Progress', 'Done', 'Cancelled'];
const VIEW_MODES: ViewMode[] = ['graph', 'kanban', 'sheet', 'analytics', 'hub'];

function viewFromLocationHash(): ViewMode {
  const hashView = window.location.hash.replace(/^#\/?/, '');
  return VIEW_MODES.includes(hashView as ViewMode) ? (hashView as ViewMode) : 'graph';
}

const statusClass: Record<Story['status'], string> = {
  Backlog: 'status-backlog',
  Approved: 'status-approved',
  'In Progress': 'status-progress',
  Done: 'success',
  Cancelled: 'cancelled',
};

type KanbanSortMode = 'id' | 'title' | 'epic' | 'module' | 'size' | 'createdAt';

const kanbanSortLabels: Record<KanbanSortMode, string> = {
  id: 'Story ID',
  title: 'Title',
  epic: 'Epic',
  module: 'Module',
  size: 'Size',
  createdAt: 'Created At',
};

const sizeRank: Record<Story['size'], number> = {
  XS: 1,
  S: 2,
  M: 3,
  L: 4,
  XL: 5,
  XXL: 6,
};

function compareStoryId(left: string, right: string): number {
  const leftMatch = left.match(/^(.+?)(\d+)$/);
  const rightMatch = right.match(/^(.+?)(\d+)$/);
  if (!leftMatch || !rightMatch) return left.localeCompare(right);
  const prefixCompare = leftMatch[1].localeCompare(rightMatch[1]);
  if (prefixCompare !== 0) return prefixCompare;
  return Number(leftMatch[2]) - Number(rightMatch[2]);
}

function compareKanbanStories(sortMode: KanbanSortMode, left: Story, right: Story): number {
  if (sortMode === 'title') return left.title.localeCompare(right.title) || compareStoryId(left.id, right.id);
  if (sortMode === 'epic') return left.epic.localeCompare(right.epic) || compareStoryId(left.id, right.id);
  if (sortMode === 'module') return left.module.localeCompare(right.module) || compareStoryId(left.id, right.id);
  if (sortMode === 'size') return sizeRank[left.size] - sizeRank[right.size] || compareStoryId(left.id, right.id);
  if (sortMode === 'createdAt') return (left.createdAt ?? '').localeCompare(right.createdAt ?? '') || compareStoryId(left.id, right.id);
  return compareStoryId(left.id, right.id);
}

type HubBackendStatus = 'healthy' | 'degraded' | 'unavailable';
type HubSessionStatus = 'active' | 'released' | 'expired';
type HubSendMode = 'broadcast' | 'group' | 'single';
type HubBackendName = 'chatgpt' | 'gemini' | 'grok' | 'qwen' | 'kimi';

interface HubSession {
  session_id: string;
  owner: string;
  status: HubSessionStatus;
  description: string;
  llms: HubBackendName[];
  created_at: string;
  last_activity: string;
  resumable: boolean;
}

interface HubBackendMetric {
  name: HubBackendName;
  label: string;
  status: HubBackendStatus;
  slots_total: number;
  slots_in_use: number;
  sends: number;
  responses: number;
  errors: number;
  avg_response_ms: number | null;
  max_response_ms: number | null;
  holders: Array<{ session_id: string; owner: string; description: string }>;
}

interface HubMessage {
  id: string;
  session_id: string;
  backend?: HubBackendName;
  role: 'user' | 'assistant';
  text: string;
  at: string;
  status?: 'ok' | 'pending' | 'error';
}

const hubSessions: HubSession[] = [
  {
    session_id: 's-1777776058738-59e0b427',
    owner: 'main-knobel-test',
    status: 'active',
    description: 'Complex combinatorial game theory problem for ChatGPT and Qwen',
    llms: ['chatgpt', 'qwen'],
    created_at: '2026-05-03T02:40:59.164Z',
    last_activity: '2026-05-03T02:41:13.504Z',
    resumable: false,
  },
  {
    session_id: 's-1777700294588-90868825',
    owner: 'uc2a-test-pyramid-discussion',
    status: 'released',
    description: 'UC2A Test-Pyramide Architektur-Diskussion (Round 1: Positionen)',
    llms: ['chatgpt', 'qwen', 'grok'],
    created_at: '2026-05-02T05:38:14.916Z',
    last_activity: '2026-05-02T08:30:18.766Z',
    resumable: true,
  },
  {
    session_id: 's-live-ak3-ui-001',
    owner: 'main-agent-ui-prototype',
    status: 'active',
    description: 'AgentKit UI Prototype Hub Cockpit',
    llms: ['chatgpt', 'gemini', 'qwen'],
    created_at: '2026-05-03T08:16:22.000Z',
    last_activity: '2026-05-03T09:04:18.000Z',
    resumable: false,
  },
  {
    session_id: 's-live-uc2a-guard-002',
    owner: 'evil-kneivel',
    status: 'active',
    description: 'UC2A contract drift detector implementation',
    llms: ['grok', 'qwen'],
    created_at: '2026-05-03T07:42:11.000Z',
    last_activity: '2026-05-03T08:57:02.000Z',
    resumable: false,
  },
  {
    session_id: 's-1777668697411-082cc5e2',
    owner: 'codex-main-uc2a-b90-review',
    status: 'released',
    description: 'Review b90c21d unknown target handling',
    llms: ['chatgpt', 'gemini'],
    created_at: '2026-05-01T20:51:38.009Z',
    last_activity: '2026-05-01T20:52:41.718Z',
    resumable: true,
  },
  {
    session_id: 's-1777582385389-81681a5b',
    owner: 'llm-discussion-uc2a-restructure',
    status: 'released',
    description: 'Multi-LLM debate UC2A rule extraction approach restructuring',
    llms: ['chatgpt', 'gemini', 'grok', 'qwen', 'kimi'],
    created_at: '2026-04-30T20:53:05.790Z',
    last_activity: '2026-04-30T22:14:12.801Z',
    resumable: true,
  },
];

const hubBackends: HubBackendMetric[] = [
  {
    name: 'chatgpt',
    label: 'ChatGPT',
    status: 'healthy',
    slots_total: 3,
    slots_in_use: 1,
    sends: 16,
    responses: 16,
    errors: 0,
    avg_response_ms: 64985,
    max_response_ms: 125598,
    holders: [{ session_id: 's-1777776058738-59e0b427', owner: 'main-knobel-test', description: 'Complex combinatorial game theory problem for ChatGPT and Qwen' }],
  },
  {
    name: 'gemini',
    label: 'Gemini',
    status: 'healthy',
    slots_total: 3,
    slots_in_use: 0,
    sends: 4,
    responses: 3,
    errors: 1,
    avg_response_ms: 88420,
    max_response_ms: 141200,
    holders: [{ session_id: 's-live-ak3-ui-001', owner: 'main-agent-ui-prototype', description: 'AgentKit UI Prototype Hub Cockpit' }],
  },
  {
    name: 'grok',
    label: 'Grok',
    status: 'healthy',
    slots_total: 3,
    slots_in_use: 1,
    sends: 3,
    responses: 3,
    errors: 0,
    avg_response_ms: 59477,
    max_response_ms: 95073,
    holders: [{ session_id: 's-live-uc2a-guard-002', owner: 'evil-kneivel', description: 'UC2A contract drift detector implementation' }],
  },
  {
    name: 'qwen',
    label: 'Qwen',
    status: 'degraded',
    slots_total: 3,
    slots_in_use: 3,
    sends: 3,
    responses: 3,
    errors: 0,
    avg_response_ms: 134689,
    max_response_ms: 165868,
    holders: [
      { session_id: 's-1777776058738-59e0b427', owner: 'main-knobel-test', description: 'Complex combinatorial game theory problem for ChatGPT and Qwen' },
      { session_id: 's-live-ak3-ui-001', owner: 'main-agent-ui-prototype', description: 'AgentKit UI Prototype Hub Cockpit' },
      { session_id: 's-live-uc2a-guard-002', owner: 'evil-kneivel', description: 'UC2A contract drift detector implementation' },
    ],
  },
  {
    name: 'kimi',
    label: 'Kimi',
    status: 'healthy',
    slots_total: 2,
    slots_in_use: 0,
    sends: 0,
    responses: 0,
    errors: 1,
    avg_response_ms: null,
    max_response_ms: null,
    holders: [],
  },
];

const initialHubMessages: HubMessage[] = [
  {
    id: 'hub-msg-1',
    session_id: 's-live-ak3-ui-001',
    role: 'user',
    text: 'Bewertet bitte den geplanten Hub-Cockpit-Flow: Metriken, Sessions und Multi-Target-Chat in einer Arbeitsansicht.',
    at: '09:02',
  },
  {
    id: 'hub-msg-2',
    session_id: 's-live-ak3-ui-001',
    backend: 'chatgpt',
    role: 'assistant',
    text: 'Die Trennung in Session-Liste, Backend-Metriken und Antwortspalten ist tragfaehig. Wichtig ist ein klarer Send-Modus, damit Broadcast nicht mit Single-Target vermischt wird.',
    at: '09:03',
    status: 'ok',
  },
  {
    id: 'hub-msg-3',
    session_id: 's-live-ak3-ui-001',
    backend: 'gemini',
    role: 'assistant',
    text: 'Fuer lange Reviews sollte jede Backend-Antwort eine eigene Spalte behalten. Eine gemischte Chat-Timeline waere nur als Audit-Log sinnvoll.',
    at: '09:03',
    status: 'ok',
  },
  {
    id: 'hub-msg-4',
    session_id: 's-live-ak3-ui-001',
    backend: 'qwen',
    role: 'assistant',
    text: 'Targets sollten explizit als Backend-Set sichtbar sein. Dadurch wird der REST-Body fuer broadcast, target und targets auch im UI nachvollziehbar.',
    at: '09:04',
    status: 'ok',
  },
];

const phaseIcon: Record<PhaseStatus, ReactNode> = {
  done: <CheckCircle2 size={14} />,
  active: <CircleDot size={14} />,
  blocked: <XCircle size={14} />,
  idle: <PauseCircle size={14} />,
  skipped: <Play size={14} />,
};

function StoryNode({ data, selected }: NodeProps) {
  const story = data as unknown as Story & { dependencyHighlight?: boolean; visualState?: string };
  const statusSlug = story.status.toLowerCase().replaceAll(' ', '-');
  return (
    <button
      className={[
        'story-node',
        `status-${statusSlug}`,
        story.visualState ? `visual-${story.visualState}` : '',
        selected ? 'is-selected' : '',
        story.dependencyHighlight ? 'is-highlighted' : '',
      ].filter(Boolean).join(' ')}
      data-story-interactive="true"
      type="button"
    >
      <Handle className="node-handle" type="target" position={Position.Left} />
      <div className="node-topline">
        <span className="node-id">{story.id}</span>
        <Badge tone={statusClass[story.status]}>{story.status}</Badge>
      </div>
      <div className="node-title">{story.title}</div>
      <div className="node-meta">
        <span>{story.type}</span>
        <span>{story.size}</span>
        <span>Wave {story.wave}</span>
      </div>
      {story.blocker && <div className="node-blocker">{story.blocker}</div>}
      <Handle className="node-handle" type="source" position={Position.Right} />
    </button>
  );
}

function DependencyEdge(props: EdgeProps) {
  const [path] = getBezierPath(props);
  const data = props.data as { open?: boolean; blockingHighlight?: boolean } | undefined;
  const className = ['dependency-edge', data?.open ? 'is-open' : '', data?.blockingHighlight ? 'is-blocking-highlight' : '']
    .filter(Boolean)
    .join(' ');
  return <BaseEdge path={path} className={className} />;
}

const nodeTypes: NodeTypes = { story: StoryNode };
const edgeTypes: EdgeTypes = { dependency: DependencyEdge };

function selectInitialStory(): Story {
  return initialStories.find((story) => story.status === 'In Progress') ?? initialStories[0];
}

export function App() {
  const [storyState, setStoryState] = useState<Story[]>(initialStories);
  const [query, setQuery] = useState('');
  const [activeProjectKey, setActiveProjectKey] = useState(project.key);
  const [projectMenuOpen, setProjectMenuOpen] = useState(false);
  const [statusFilter, setStatusFilter] = useState<'all' | Story['status']>('all');
  const [kanbanStoryIdFilter, setKanbanStoryIdFilter] = useState('');
  const [view, setView] = useState<ViewMode>(viewFromLocationHash);
  const [selectedStory, setSelectedStory] = useState<Story>(selectInitialStory);
  const [detailOpen, setDetailOpen] = useState(false);
  const [inspectorWidth, setInspectorWidth] = useState(() => {
    const stored = Number(window.localStorage.getItem(INSPECTOR_WIDTH_KEY));
    return Number.isFinite(stored) && stored > 0 ? stored : DEFAULT_INSPECTOR_WIDTH;
  });
  const [resizingInspector, setResizingInspector] = useState(false);
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);

  const visibleStories = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return storyState.filter((story) => {
      const matchesStatus = statusFilter === 'all' || story.status === statusFilter;
      const matchesQuery =
        !needle ||
        story.id.toLowerCase().includes(needle) ||
        story.title.toLowerCase().includes(needle) ||
        story.repo.toLowerCase().includes(needle) ||
        story.module.toLowerCase().includes(needle) ||
        story.epic.toLowerCase().includes(needle);
      return matchesStatus && matchesQuery;
    });
  }, [query, statusFilter, storyState]);

  useEffect(() => {
    let stale = false;
    const graph = toGraph(visibleStories, detailOpen ? selectedStory.id : null);
    layoutGraph(graph.nodes, graph.edges).then((layouted) => {
      if (!stale) {
        setNodes(layouted.nodes);
        setEdges(layouted.edges);
      }
    });
    return () => {
      stale = true;
    };
  }, [detailOpen, selectedStory.id, visibleStories, setEdges, setNodes]);

  const selectStory = useCallback((story: Story) => {
    setSelectedStory(story);
    setDetailOpen(true);
  }, []);

  const focusStory = useCallback((story: Story) => {
    setSelectedStory(story);
  }, []);

  const changeStoryStatus = useCallback((storyId: string, status: Story['status']) => {
    let updatedStory: Story | null = null;
    setStoryState((currentStories) =>
      currentStories.map((story) => {
        if (story.id !== storyId) return story;
        updatedStory = { ...story, status };
        return updatedStory;
      }),
    );
    if (updatedStory) {
      setSelectedStory(updatedStory);
      setDetailOpen(true);
    }
  }, []);

  const onNodeClick = useCallback((_event: React.MouseEvent, node: Node) => {
    setSelectedStory(node.data as unknown as Story);
    setDetailOpen(true);
  }, []);

  const counters = useMemo(() => {
    const doneStoryIds = new Set(storyState.filter((story) => story.status === 'Done').map((story) => story.id));
    const hasOpenDependency = (story: Story) => story.dependencies.some((dependency) => !doneStoryIds.has(dependency));
    const isReady = (story: Story) => story.status === 'Approved' && !story.blocker && !hasOpenDependency(story);
    const isBlocked = (story: Story) =>
      story.status === 'Backlog' || (story.status === 'Approved' && (Boolean(story.blocker) || hasOpenDependency(story)));
    return {
      total: storyState.length,
      running: storyState.filter((story) => story.status === 'In Progress').length,
      finished: storyState.filter((story) => story.status === 'Done').length,
      ready: storyState.filter(isReady).length,
      queue: storyState.filter((story) => story.status === 'Approved').length,
      blocked: storyState.filter(isBlocked).length,
    };
  }, [storyState]);

  const activeProject = projects.find((candidate) => candidate.key === activeProjectKey) ?? project;

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

  useEffect(() => {
    const moveSelection = (direction: 1 | -1) => {
      const index = visibleStories.findIndex((story) => story.id === selectedStory.id);
      const fallbackIndex = index < 0 ? 0 : index;
      const next = visibleStories[Math.min(Math.max(fallbackIndex + direction, 0), visibleStories.length - 1)];
      if (next) {
        setSelectedStory(next);
        setDetailOpen(true);
      }
    };

    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target?.matches('input, textarea, select')) return;
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
  }, [selectedStory.id, view, visibleStories]);

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

  useEffect(() => {
    if (!resizingInspector) return;

    const onMouseMove = (event: MouseEvent) => {
      const maxWidth = Math.max(MIN_INSPECTOR_WIDTH, window.innerWidth - 96);
      const nextWidth = Math.min(Math.max(window.innerWidth - event.clientX - 14, MIN_INSPECTOR_WIDTH), maxWidth);
      setInspectorWidth(nextWidth);
    };

    const onMouseUp = () => {
      setResizingInspector(false);
    };

    document.body.classList.add('is-resizing-inspector');
    window.addEventListener('mousemove', onMouseMove);
    window.addEventListener('mouseup', onMouseUp);
    return () => {
      document.body.classList.remove('is-resizing-inspector');
      window.removeEventListener('mousemove', onMouseMove);
      window.removeEventListener('mouseup', onMouseUp);
    };
  }, [resizingInspector]);

  useEffect(() => {
    window.localStorage.setItem(INSPECTOR_WIDTH_KEY, String(Math.round(inspectorWidth)));
  }, [inspectorWidth]);

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

  return (
    <main className="shell">
      <aside className="sidebar">
        <div className="brand">
          <ShieldCheck size={22} />
          <div>
            <strong>AgentKit 3</strong>
            <span>{project.key}</span>
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
            <span className="title-separator" aria-hidden="true">|</span>
            <div className="project-heading" data-project-menu="true">
              <button
                className="project-heading__button"
                type="button"
                aria-expanded={projectMenuOpen}
                onClick={() => setProjectMenuOpen((open) => !open)}
              >
                <span>{activeProject.name}</span>
                <ChevronDown size={18} />
              </button>
              {projectMenuOpen && (
                <div className="project-menu">
                  {projects.map((candidate) => (
                    <button
                      className={candidate.key === activeProjectKey ? 'active' : ''}
                      key={candidate.key}
                      type="button"
                      onClick={() => {
                        setActiveProjectKey(candidate.key);
                        setProjectMenuOpen(false);
                      }}
                    >
                      <span>{candidate.name}</span>
                      <small>{candidate.key}</small>
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>
          <div className="top-actions">
            <div className="ak-input search">
              <Search size={17} />
              <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Story, Repo, Modul oder Epic" />
            </div>
            <button className="ak-button ak-button--primary" type="button">
              <Plus size={16} />
              Story
            </button>
          </div>
        </header>

        <section className="content">
          <div className="left-panel">
            <MainView
              view={view}
              nodes={nodes}
              edges={edges}
              stories={visibleStories}
              selectedStory={selectedStory}
              onNodeClick={onNodeClick}
              onNodesChange={onNodesChange}
              onEdgesChange={onEdgesChange}
              onSelect={selectStory}
              onFocusStory={focusStory}
              onStoryStatusChange={changeStoryStatus}
              kanbanStoryIdFilter={kanbanStoryIdFilter}
              onKanbanStoryIdFilterChange={setKanbanStoryIdFilter}
              statusFilter={statusFilter}
              onStatusFilterChange={setStatusFilter}
              kpis={counters}
            />
          </div>
        </section>
      </section>
      {detailOpen && (
        <DetailInspector
          story={selectedStory}
          width={inspectorWidth}
          onClose={() => setDetailOpen(false)}
          onResizeStart={() => setResizingInspector(true)}
        />
      )}
    </main>
  );
}

function MainView({
  view,
  nodes,
  edges,
  stories: visibleStories,
  selectedStory,
  onNodeClick,
  onNodesChange,
  onEdgesChange,
  onSelect,
  onFocusStory,
  onStoryStatusChange,
  kanbanStoryIdFilter,
  onKanbanStoryIdFilterChange,
  statusFilter,
  onStatusFilterChange,
  kpis,
}: {
  view: ViewMode;
  nodes: Node[];
  edges: Edge[];
  stories: Story[];
  selectedStory: Story;
  onNodeClick: (event: React.MouseEvent, node: Node) => void;
  onNodesChange: ReturnType<typeof useNodesState<Node>>[2];
  onEdgesChange: ReturnType<typeof useEdgesState<Edge>>[2];
  onSelect: (story: Story) => void;
  onFocusStory: (story: Story) => void;
  onStoryStatusChange: (storyId: string, status: Story['status']) => void;
  kanbanStoryIdFilter: string;
  onKanbanStoryIdFilterChange: (value: string) => void;
  statusFilter: 'all' | Story['status'];
  onStatusFilterChange: (status: 'all' | Story['status']) => void;
  kpis: StoryCounters;
}) {
  if (view === 'kanban') {
    return (
      <Kanban
        stories={visibleStories}
        selectedStory={selectedStory}
        onSelect={onSelect}
        onFocusStory={onFocusStory}
        onStoryStatusChange={onStoryStatusChange}
        storyIdFilter={kanbanStoryIdFilter}
        onStoryIdFilterChange={onKanbanStoryIdFilterChange}
        kpis={kpis}
      />
    );
  }

  if (view === 'sheet') {
    return (
      <StorySheet
        stories={visibleStories}
        selectedStory={selectedStory}
        statusFilter={statusFilter}
        onSelect={onSelect}
        onStatusFilterChange={onStatusFilterChange}
        kpis={kpis}
      />
    );
  }

  if (view === 'analytics') {
    return <AnalyticsView />;
  }

  if (view === 'hub') {
    return <LlmHubView />;
  }

  return (
    <div className="graph-shell">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={onNodeClick}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        fitView
        fitViewOptions={{ padding: 0.18 }}
        minZoom={0.35}
        maxZoom={1.8}
        nodesConnectable={false}
        proOptions={{ hideAttribution: true }}
      >
        <Background gap={28} size={1} />
        <Controls />
        <MiniMap pannable zoomable nodeStrokeWidth={3} />
      </ReactFlow>
    </div>
  );
}

function IconNav({ active, title, onClick, children }: { active: boolean; title: string; onClick: () => void; children: ReactNode }) {
  return (
    <button className={active ? 'active' : ''} type="button" title={title} onClick={onClick}>
      {children}
    </button>
  );
}

function Metric({ icon, label, value, tone = 'normal' }: { icon: ReactNode; label: string; value: number | string; tone?: 'normal' | 'warning' | 'danger' }) {
  return (
    <article className={`metric ak-panel tone-${tone}`}>
      {icon}
      <div>
        <strong>{value}</strong>
        <span>{label}</span>
      </div>
    </article>
  );
}

function Kanban({
  stories: boardStories,
  selectedStory,
  onSelect,
  onFocusStory,
  onStoryStatusChange,
  storyIdFilter,
  onStoryIdFilterChange,
  kpis,
}: {
  stories: Story[];
  selectedStory: Story;
  onSelect: (story: Story) => void;
  onFocusStory: (story: Story) => void;
  onStoryStatusChange: (storyId: string, status: Story['status']) => void;
  storyIdFilter: string;
  onStoryIdFilterChange: (value: string) => void;
  kpis: StoryCounters;
}) {
  const [draggedStoryId, setDraggedStoryId] = useState<string | null>(null);
  const [dropTarget, setDropTarget] = useState<Story['status'] | null>(null);
  const [sortMode, setSortMode] = useState<KanbanSortMode>('id');
  const filteredStories = useMemo(() => {
    const storyIdNeedle = storyIdFilter.trim().toLowerCase();
    if (!storyIdNeedle) return boardStories;
    return boardStories.filter((story) => story.id.toLowerCase().includes(storyIdNeedle));
  }, [boardStories, storyIdFilter]);
  const sortedStories = useMemo(
    () => [...filteredStories].sort((left, right) => compareKanbanStories(sortMode, left, right)),
    [filteredStories, sortMode],
  );
  const storiesByStatus = useMemo(
    () =>
      STORY_STATUSES.reduce<Record<Story['status'], Story[]>>(
        (groups, status) => {
          groups[status] = sortedStories.filter((story) => story.status === status);
          return groups;
        },
        { Backlog: [], Approved: [], 'In Progress': [], Done: [], Cancelled: [] },
      ),
    [sortedStories],
  );

  useEffect(() => {
    document.querySelector<HTMLElement>(`[data-kanban-story-id="${selectedStory.id}"]`)?.focus();
  }, [selectedStory.id]);

  const focusKanbanNeighbor = (key: string) => {
    const currentColumnIndex = STORY_STATUSES.indexOf(selectedStory.status);
    const currentColumn = storiesByStatus[selectedStory.status];
    const currentRowIndex = Math.max(0, currentColumn.findIndex((story) => story.id === selectedStory.id));
    if (key === 'ArrowDown' || key === 'ArrowUp') {
      const offset = key === 'ArrowDown' ? 1 : -1;
      const next = currentColumn[Math.min(Math.max(currentRowIndex + offset, 0), currentColumn.length - 1)];
      if (next) onFocusStory(next);
      return;
    }

    const offset = key === 'ArrowRight' ? 1 : -1;
    const nextStatus = STORY_STATUSES[Math.min(Math.max(currentColumnIndex + offset, 0), STORY_STATUSES.length - 1)];
    const nextColumn = storiesByStatus[nextStatus];
    const next = nextColumn[Math.min(currentRowIndex, nextColumn.length - 1)];
    if (next) onFocusStory(next);
  };

  const onDragStart = (event: React.DragEvent<HTMLButtonElement>, story: Story) => {
    setDraggedStoryId(story.id);
    event.dataTransfer.effectAllowed = 'move';
    event.dataTransfer.setData('text/plain', story.id);
    const dragImage = event.currentTarget.cloneNode(true) as HTMLElement;
    dragImage.classList.add('kanban-drag-preview');
    document.body.appendChild(dragImage);
    event.dataTransfer.setDragImage(dragImage, 24, 24);
    window.setTimeout(() => dragImage.remove(), 0);
  };

  const onDrop = (event: React.DragEvent<HTMLElement>, status: Story['status']) => {
    event.preventDefault();
    const storyId = event.dataTransfer.getData('text/plain') || draggedStoryId;
    setDraggedStoryId(null);
    setDropTarget(null);
    if (storyId) {
      onStoryStatusChange(storyId, status);
    }
  };

  return (
    <div className="kanban">
      <KpiBar tiles={buildStoryKpiTiles(kpis)} />
      <div className="kanban-toolbar ak-panel" data-story-interactive="true">
        <label className="kanban-filter">
          <span>Story ID</span>
          <input
            value={storyIdFilter}
            onChange={(event) => onStoryIdFilterChange(event.target.value)}
            placeholder="z. B. BB2-247"
          />
        </label>
        <label className="kanban-sort">
          <span>Sort</span>
          <select value={sortMode} onChange={(event) => setSortMode(event.target.value as KanbanSortMode)}>
            {Object.entries(kanbanSortLabels).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
      </div>
      {STORY_STATUSES.map((column) => {
        const items = storiesByStatus[column];
        return (
          <section
            className={`kanban-column ak-panel ${dropTarget === column ? 'is-drop-target' : ''}`}
            data-story-interactive="true"
            key={column}
            onDragOver={(event) => {
              event.preventDefault();
              event.dataTransfer.dropEffect = 'move';
              setDropTarget(column);
            }}
            onDragLeave={(event) => {
              if (!event.currentTarget.contains(event.relatedTarget as globalThis.Node | null)) {
                setDropTarget(null);
              }
            }}
            onDrop={(event) => onDrop(event, column)}
          >
            <header>
              <h2>{column}</h2>
              <span>{items.length}</span>
            </header>
            {items.map((story) => (
              <button
                className={[
                  'kanban-card',
                  selectedStory.id === story.id ? 'selected' : '',
                  draggedStoryId === story.id ? 'is-dragging' : '',
                ].filter(Boolean).join(' ')}
                data-story-interactive="true"
                data-kanban-story-id={story.id}
                draggable
                key={story.id}
                type="button"
                onDragEnd={() => {
                  setDraggedStoryId(null);
                  setDropTarget(null);
                }}
                onDragStart={(event) => onDragStart(event, story)}
                onClick={() => onFocusStory(story)}
                onDoubleClick={() => onSelect(story)}
                onKeyDown={(event) => {
                  if (['ArrowDown', 'ArrowUp', 'ArrowRight', 'ArrowLeft'].includes(event.key)) {
                    event.preventDefault();
                    focusKanbanNeighbor(event.key);
                  }
                  if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault();
                    onSelect(story);
                  }
                }}
              >
                <span className="node-id">{story.id}</span>
                <strong>{story.title}</strong>
                <small>{story.module} · Wave {story.wave}</small>
                <div className="tag-row">
                  <Badge tone={statusClass[story.status]}>{story.type}</Badge>
                  <Badge tone="neutral">{story.size}</Badge>
                </div>
              </button>
            ))}
          </section>
        );
      })}
    </div>
  );
}

function StorySheet({
  stories: sheetStories,
  selectedStory,
  statusFilter,
  onSelect,
  onStatusFilterChange,
  kpis,
}: {
  stories: Story[];
  selectedStory: Story;
  statusFilter: 'all' | Story['status'];
  onSelect: (story: Story) => void;
  onStatusFilterChange: (status: 'all' | Story['status']) => void;
  kpis: StoryCounters;
}) {
  type SheetField = keyof Pick<Story, 'id' | 'title' | 'epic' | 'module' | 'status' | 'labels' | 'type' | 'primaryRepo' | 'participatingRepos' | 'size' | 'createdAt' | 'completedAt' | 'processingTime' | 'qaRoundsExploration' | 'qaRoundsImplementation' | 'changeImpact'>;
  type Column = {
    id: SheetField;
    label: string;
    group: 'identity' | 'classification' | 'planning' | 'metrics';
    frozen?: boolean;
    editable?: boolean;
    width?: string;
  };

  const columns: Column[] = [
    { id: 'id', label: 'Story ID', group: 'identity', frozen: true, width: '6.5625rem' },
    { id: 'title', label: 'Title', group: 'identity', frozen: true, editable: true, width: '20.625rem' },
    { id: 'epic', label: 'Epic', group: 'planning', editable: true, width: '13.125rem' },
    { id: 'module', label: 'Module', group: 'planning', editable: true, width: '11.25rem' },
    { id: 'status', label: 'Status', group: 'classification', editable: true, width: '8.125rem' },
    { id: 'labels', label: 'Labels', group: 'classification', width: '16rem' },
    { id: 'type', label: 'Story Type', group: 'classification', editable: true, width: '8.75rem' },
    { id: 'primaryRepo', label: 'Primary Repo', group: 'planning', editable: true, width: '12rem' },
    { id: 'participatingRepos', label: 'Participating Repos', group: 'planning', width: '16rem' },
    { id: 'size', label: 'Size', group: 'classification', editable: true, width: '4.5rem' },
    { id: 'createdAt', label: 'Created At', group: 'metrics', editable: true, width: '7.5rem' },
    { id: 'completedAt', label: 'Completed At', group: 'metrics', editable: true, width: '8rem' },
    { id: 'processingTime', label: 'Processing Time', group: 'metrics', width: '9rem' },
    { id: 'qaRoundsExploration', label: 'QA Rounds Exploration', group: 'metrics', width: '10.5rem' },
    { id: 'qaRoundsImplementation', label: 'QA Rounds Implementation', group: 'metrics', width: '11.5rem' },
    { id: 'changeImpact', label: 'Change Impact', group: 'classification', editable: true, width: '10.625rem' },
  ];

  const groupLabels: Record<Column['group'], string> = {
    identity: 'Identity',
    classification: 'Classification',
    planning: 'Planning',
    metrics: 'Metrics',
  };

  const [visibleGroups, setVisibleGroups] = useState<Set<Column['group']>>(
    () => new Set(['identity', 'classification', 'planning', 'metrics']),
  );
  const [groupByEpic, setGroupByEpic] = useState(true);
  const [sortField, setSortField] = useState<SheetField>('epic');
  const [sortAsc, setSortAsc] = useState(true);
  const [editingCell, setEditingCell] = useState<{ storyId: string; field: SheetField } | null>(null);
  const [drafts, setDrafts] = useState<Record<string, Partial<Record<SheetField, string | number>>>>({});
  const [copiedEpic, setCopiedEpic] = useState<string | null>(null);
  const [columnWidths, setColumnWidths] = useState<Record<string, string>>(() => {
    const defaults = Object.fromEntries(columns.map((column) => [column.id, column.width ?? '8rem']));
    try {
      const stored = JSON.parse(window.localStorage.getItem(SHEET_COLUMN_WIDTHS_KEY) ?? '{}') as Record<string, string>;
      return { ...defaults, ...stored };
    } catch {
      return defaults;
    }
  });

  useEffect(() => {
    window.localStorage.setItem(SHEET_COLUMN_WIDTHS_KEY, JSON.stringify(columnWidths));
  }, [columnWidths]);

  const visibleColumns = columns.map((column) => ({ ...column, width: columnWidths[column.id] ?? column.width })).filter((column) => visibleGroups.has(column.group));
  const frozenColumns = visibleColumns.filter((column) => column.frozen);
  const scrollColumns = visibleColumns.filter((column) => !column.frozen);
  const idColumnWidth = columnWidths.id ?? columns.find((column) => column.id === 'id')?.width ?? '6.5625rem';

  const getColumnStyle = (column: Column): CSSProperties => {
    const style: CSSProperties = {
      minWidth: column.width,
      width: column.width,
    };
    if (column.frozen) {
      style.left = column.id === 'title' ? idColumnWidth : '0';
    }
    return style;
  };

  const startColumnResize = (event: React.PointerEvent, column: Column) => {
    event.preventDefault();
    event.stopPropagation();
    const rootFontSize = Number.parseFloat(getComputedStyle(document.documentElement).fontSize) || 16;
    const startX = event.clientX;
    const initialRem = Number.parseFloat(column.width ?? columnWidths[column.id] ?? '8');
    const minRem = column.id === 'title' ? 12 : 4;

    const onPointerMove = (moveEvent: PointerEvent) => {
      const next = Math.max(minRem, initialRem + (moveEvent.clientX - startX) / rootFontSize);
      setColumnWidths((current) => ({
        ...current,
        [column.id]: `${next.toFixed(3)}rem`,
      }));
    };

    const onPointerUp = () => {
      window.removeEventListener('pointermove', onPointerMove);
      window.removeEventListener('pointerup', onPointerUp);
    };

    window.addEventListener('pointermove', onPointerMove);
    window.addEventListener('pointerup', onPointerUp);
  };

  const getCellValue = useCallback(
    (story: Story, field: SheetField): string | number | string[] => {
      const draft = drafts[story.id]?.[field];
      if (draft !== undefined) return draft;
      const value = story[field];
      return value === undefined ? '' : value;
    },
    [drafts],
  );

  const sortedStories = useMemo(() => {
    return [...sheetStories].sort((a, b) => {
      const av = getCellValue(a, sortField);
      const bv = getCellValue(b, sortField);
      const result = String(av).localeCompare(String(bv), 'de', { numeric: true });
      return sortAsc ? result : -result;
    });
  }, [getCellValue, sheetStories, sortAsc, sortField]);

  const groupedStories = useMemo(() => {
    if (!groupByEpic) return [['Alle Stories', sortedStories] as const];
    const map = new Map<string, Story[]>();
    for (const story of sortedStories) {
      const epic = String(getCellValue(story, 'epic') || 'Ohne Epic');
      map.set(epic, [...(map.get(epic) ?? []), story]);
    }
    return Array.from(map.entries());
  }, [getCellValue, groupByEpic, sortedStories]);

  const setSort = (field: SheetField) => {
    if (sortField === field) {
      setSortAsc((current) => !current);
      return;
    }
    setSortField(field);
    setSortAsc(true);
  };

  const toggleGroup = (group: Column['group']) => {
    setVisibleGroups((current) => {
      const next = new Set(current);
      if (next.has(group) && next.size > 1) next.delete(group);
      else next.add(group);
      return next;
    });
  };

  const updateDraft = (storyId: string, field: SheetField, value: string) => {
    const normalized = field === 'qaRoundsExploration' || field === 'qaRoundsImplementation' ? Number(value) : value;
    setDrafts((current) => ({
      ...current,
      [storyId]: {
        ...current[storyId],
        [field]: normalized,
      },
    }));
  };

  const copyEpic = (epic: string, rows: Story[]) => {
    const text = rows.map((story) => story.id).join(', ');
    void navigator.clipboard?.writeText(text);
    setCopiedEpic(epic);
    window.setTimeout(() => setCopiedEpic(null), 1800);
  };

  return (
    <div className="sheet-wrap">
      <KpiBar tiles={buildStoryKpiTiles(kpis)} />
      <div className="sheet-toolbar ak-panel">
        <div className="sheet-toolbar__row">
          <div className="sheet-title">
            <Table2 size={17} />
            <strong>Story Spreadsheet</strong>
            <span>{sheetStories.length} rows</span>
          </div>
          <div className="sheet-actions">
            <button className="ak-button ak-button--compact" type="button" onClick={() => setGroupByEpic((value) => !value)}>
              <Group size={15} />
              {groupByEpic ? 'Epic Groups' : 'Flat'}
            </button>
            <button className="ak-button ak-button--compact" type="button">
              <Filter size={15} />
              Filter
            </button>
            <button className="ak-button ak-button--compact" type="button">
              <Download size={15} />
              Export
            </button>
          </div>
        </div>
        <div className="sheet-toolbar__row sheet-toolbar__row--wrap">
          {Object.entries(groupLabels).map(([group, label]) => (
            <button
              className={`column-chip ${visibleGroups.has(group as Column['group']) ? 'active' : ''}`}
              key={group}
              type="button"
              onClick={() => toggleGroup(group as Column['group'])}
            >
              {visibleGroups.has(group as Column['group']) ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
              {label}
              <span>{columns.filter((column) => column.group === group).length}</span>
            </button>
          ))}
          <label className="sheet-status-filter">
            <Filter size={13} />
            <select value={statusFilter} onChange={(event) => onStatusFilterChange(event.target.value as 'all' | Story['status'])}>
              <option value="all">Alle Status</option>
              <option value="Backlog">Backlog</option>
              <option value="Approved">Approved</option>
              <option value="In Progress">In Progress</option>
              <option value="Done">Done</option>
              <option value="Cancelled">Cancelled</option>
            </select>
          </label>
        </div>
      </div>

      <div className="sheet-grid-shell">
        <table className="story-sheet">
          <thead>
            <tr className="sheet-group-head">
              {visibleColumns.map((column) => (
                <th className={column.frozen ? 'is-frozen' : ''} key={column.id} style={getColumnStyle(column)}>
                  {groupLabels[column.group]}
                </th>
              ))}
            </tr>
            <tr>
              {visibleColumns.map((column) => (
                <th className={column.frozen ? 'is-frozen is-resizable' : 'is-resizable'} key={column.id} style={getColumnStyle(column)}>
                  <button className="sort-header" type="button" onClick={() => setSort(column.id)}>
                    {column.label}
                    {sortField === column.id ? (sortAsc ? <ArrowUp size={13} /> : <ArrowDown size={13} />) : <ArrowUpDown size={13} />}
                  </button>
                  <span
                    aria-label={`${column.label} Spaltenbreite anpassen`}
                    className="sheet-column-resize"
                    role="separator"
                    onPointerDown={(event) => startColumnResize(event, column)}
                  />
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {groupedStories.map(([epic, rows]) => (
              <Fragment key={epic}>
                {groupByEpic && (
                  <tr className="epic-row">
                    <td colSpan={visibleColumns.length}>
                      <div className="sheet-group-title">
                        <ChevronDown size={14} />
                        <strong>{epic}</strong>
                        <span>{rows.length}</span>
                        <button aria-label={`${epic} menu`} className="sheet-group-menu" type="button">
                          <MoreHorizontal size={15} />
                        </button>
                        <button className="sheet-group-copy" type="button" onClick={() => copyEpic(epic, rows)}>
                          <Copy size={13} />
                          {copiedEpic === epic ? 'Copied' : 'Copy IDs'}
                        </button>
                      </div>
                    </td>
                  </tr>
                )}
                {rows.map((story) => (
                  <tr
                    className={[
                      selectedStory.id === story.id ? 'selected' : '',
                      drafts[story.id] ? 'is-dirty' : '',
                    ].filter(Boolean).join(' ')}
                    key={story.id}
                    data-story-interactive="true"
                    onClick={() => onSelect(story)}
                  >
                    {[...frozenColumns, ...scrollColumns].map((column) => (
                      <td
                        className={[
                          column.id === 'id' ? 'cell-id' : '',
                          column.id === 'title' ? 'cell-title' : '',
                          column.frozen ? 'is-frozen' : '',
                          editingCell?.storyId === story.id && editingCell.field === column.id ? 'is-editing' : '',
                        ].filter(Boolean).join(' ')}
                        key={column.id}
                        style={getColumnStyle(column)}
                        onDoubleClick={(event) => {
                          event.stopPropagation();
                          if (column.editable) setEditingCell({ storyId: story.id, field: column.id });
                        }}
                      >
                        <SheetCell
                          column={column}
                          editing={editingCell?.storyId === story.id && editingCell.field === column.id}
                          story={story}
                          value={getCellValue(story, column.id)}
                          onChange={(value) => updateDraft(story.id, column.id, value)}
                          onDone={() => setEditingCell(null)}
                        />
                      </td>
                    ))}
                  </tr>
                ))}
                {groupByEpic && (
                  <tr className="sheet-add-row">
                    <td colSpan={visibleColumns.length}>
                      <button type="button">
                        <Plus size={14} />
                        Add item
                      </button>
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>

      <div className="sheet-statusbar">
        <span>{sortedStories.length} visible rows</span>
        <span>{visibleColumns.length} columns</span>
        <span>{Object.keys(drafts).length} edited rows</span>
      </div>
    </div>
  );
}

function SheetCell({
  column,
  editing,
  story,
  value,
  onChange,
  onDone,
}: {
  column: {
    id: keyof Pick<Story, 'id' | 'title' | 'epic' | 'module' | 'status' | 'labels' | 'type' | 'primaryRepo' | 'participatingRepos' | 'size' | 'createdAt' | 'completedAt' | 'processingTime' | 'qaRoundsExploration' | 'qaRoundsImplementation' | 'changeImpact'>;
    editable?: boolean;
  };
  editing: boolean;
  story: Story;
  value: string | number | string[];
  onChange: (value: string) => void;
  onDone: () => void;
}) {
  const options: Partial<Record<typeof column.id, string[]>> = {
    status: ['Backlog', 'Approved', 'In Progress', 'Done', 'Cancelled'],
    type: ['implementation', 'bugfix', 'concept', 'research'],
    size: ['XS', 'S', 'M', 'L', 'XL', 'XXL'],
    changeImpact: ['Local', 'Component', 'Cross-Component', 'Architecture Impact'],
  };

  if (editing && column.editable) {
    if (options[column.id]) {
      return (
        <select
          autoFocus
          className="sheet-editor"
          value={String(value)}
          onBlur={onDone}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' || event.key === 'Escape') onDone();
          }}
        >
          {options[column.id]?.map((option) => (
            <option key={option} value={option}>{option}</option>
          ))}
        </select>
      );
    }

    return (
      <input
        autoFocus
        className="sheet-editor"
        type={column.id === 'qaRoundsExploration' || column.id === 'qaRoundsImplementation' ? 'number' : column.id === 'createdAt' || column.id === 'completedAt' ? 'date' : 'text'}
        value={Array.isArray(value) ? value.join(', ') : String(value)}
        onBlur={onDone}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === 'Enter' || event.key === 'Escape') onDone();
        }}
      />
    );
  }

  if (column.id === 'status') return <Badge tone={statusClass[String(value) as Story['status']]}>{String(value)}</Badge>;
  if (column.id === 'labels') return <span>{Array.isArray(value) ? value.join(', ') : String(value || '-')}</span>;
  if (column.id === 'participatingRepos') return <span>{Array.isArray(value) ? value.join(', ') : String(value || '-')}</span>;
  if (column.id === 'title') {
    return (
      <div className="sheet-title-cell">
        <span>{String(value)}</span>
        <Edit3 size={12} />
      </div>
    );
  }
  if (column.id === 'epic') {
    return <span className="epic-label">{String(value)}</span>;
  }
  if (column.id === 'id') return <span className="cell-id">{story.id}</span>;
  return <span>{value || '-'}</span>;
}

function AnalyticsView() {
  const pipelineSeries = [78, 64, 71, 86, 82, 91];
  const qaSeries = [3, 2, 4, 1, 2, 3];
  const poolRows = [
    ['chatgpt', '1.9s', '5.8s', '84%'],
    ['gemini', '2.4s', '7.1s', '79%'],
    ['grok', '2.8s', '8.6s', '73%'],
    ['qwen', '2.1s', '6.3s', '76%'],
  ];

  return (
    <div className="analytics-grid">
      <section className="analytics-card ak-panel accent-teal">
        <h2>Story KPI</h2>
        <div className="big-number">82%</div>
        <p>First-Pass-Rate, gueltige nicht zurueckgesetzte Runs.</p>
        <Sparkline values={pipelineSeries} />
      </section>
      <section className="analytics-card ak-panel accent-amber">
        <h2>Pipeline Trends</h2>
        <div className="bar-stack">
          {qaSeries.map((value, index) => (
            <div className="bar" key={index}>
              <span style={{ height: `${value * 20}%` }} />
            </div>
          ))}
        </div>
        <p>QA-Runden-Trend und Processing-Time bleiben zusammen zu lesen.</p>
      </section>
      <section className="analytics-card ak-panel accent-violet">
        <h2>LLM Performance</h2>
        <table className="mini-table">
          <tbody>
            {poolRows.map(([pool, p50, p95, adoption]) => (
              <tr key={pool}>
                <td>{pool}</td>
                <td>{p50}</td>
                <td>{p95}</td>
                <td>{adoption}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      <section className="analytics-card ak-panel accent-danger">
        <h2>Failure Corpus</h2>
        <div className="funnel">
          <span style={{ width: '92%' }}>Incidents 24</span>
          <span style={{ width: '62%' }}>Patterns 11</span>
          <span style={{ width: '38%' }}>Checks 4</span>
        </div>
      </section>
    </div>
  );
}

function formatDuration(ms: number | null): string {
  if (ms === null) return 'n/a';
  return ms < 1000 ? `${ms} ms` : `${Math.round(ms / 1000)} s`;
}

function statusTone(status: HubBackendStatus | HubSessionStatus): string {
  if (status === 'healthy' || status === 'active') return 'success';
  if (status === 'degraded' || status === 'released') return 'warning';
  return 'cancelled';
}

function LlmHubView() {
  const [selectedSessionId, setSelectedSessionId] = useState('s-1777776058738-59e0b427');
  const [sendMode, setSendMode] = useState<HubSendMode>('broadcast');
  const [selectedBackends, setSelectedBackends] = useState<Set<HubBackendName>>(new Set(['chatgpt', 'gemini', 'qwen']));
  const [activeResponseBackend, setActiveResponseBackend] = useState<HubBackendName>('chatgpt');
  const [draft, setDraft] = useState('');
  const [messages, setMessages] = useState<HubMessage[]>(initialHubMessages);
  const selectedSession = hubSessions.find((session) => session.session_id === selectedSessionId) ?? hubSessions[0];
  const activeSessions = hubSessions.filter((session) => session.status === 'active');
  const totalSlots = hubBackends.reduce((sum, backend) => sum + backend.slots_total, 0);
  const usedSlots = hubBackends.reduce((sum, backend) => sum + backend.slots_in_use, 0);
  const availableTargets = selectedSession.llms;
  const effectiveTargets =
    sendMode === 'broadcast'
      ? availableTargets
      : sendMode === 'single'
        ? [activeResponseBackend].filter((backend) => availableTargets.includes(backend))
        : availableTargets.filter((backend) => selectedBackends.has(backend));
  const sessionMessages = messages.filter((message) => message.session_id === selectedSession.session_id);

  useEffect(() => {
    if (!selectedSession.llms.includes(activeResponseBackend)) {
      setActiveResponseBackend(selectedSession.llms[0]);
    }
    setSelectedBackends(new Set(selectedSession.llms));
  }, [activeResponseBackend, selectedSession.llms]);

  const toggleBackend = (backend: HubBackendName) => {
    setSelectedBackends((current) => {
      const next = new Set(current);
      if (next.has(backend)) next.delete(backend);
      else next.add(backend);
      return next;
    });
  };

  const sendMessage = () => {
    const text = draft.trim();
    if (!text || effectiveTargets.length === 0) return;
    const now = new Date();
    const time = now.toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' });
    const baseId = `${selectedSession.session_id}-${now.getTime()}`;
    setMessages((current) => [
      ...current,
      { id: `${baseId}-user`, session_id: selectedSession.session_id, role: 'user', text, at: time },
      ...effectiveTargets.map((backend) => ({
        id: `${baseId}-${backend}`,
        session_id: selectedSession.session_id,
        backend,
        role: 'assistant' as const,
        text: `Mock response from ${backend}: request accepted via ${sendMode === 'broadcast' ? 'broadcast message' : sendMode === 'single' ? 'single target' : 'targets map'}.`,
        at: time,
        status: 'ok' as const,
      })),
    ]);
    setDraft('');
  };

  return (
    <div className="hub-page">
      <section className="hub-summary">
        <article className="hub-active-sessions ak-panel">
          <header>
            <span>Active Sessions</span>
            <strong>{activeSessions.length}</strong>
          </header>
          <div>
            {activeSessions.map((session) => (
              <button
                className={session.session_id === selectedSession.session_id ? 'active' : ''}
                key={session.session_id}
                type="button"
                onClick={() => setSelectedSessionId(session.session_id)}
              >
                <strong>{session.owner}</strong>
                <span>{session.llms.join(' · ')}</span>
              </button>
            ))}
          </div>
        </article>
        <Info label="Slot Usage" value={`${usedSlots}/${totalSlots}`} />
        <Info label="Free Slots" value={String(totalSlots - usedSlots)} />
      </section>

      <section className="hub-backends">
        {hubBackends.map((backend) => (
          <article className="hub-backend-card ak-panel" key={backend.name}>
            <header>
              <div>
                <strong>{backend.label}</strong>
                <span>{backend.name}</span>
              </div>
              <Badge tone={statusTone(backend.status)}>{backend.status}</Badge>
            </header>
            <div className="hub-slotbar">
              <span style={{ width: `${(backend.slots_in_use / backend.slots_total) * 100}%` }} />
            </div>
            <dl>
              <div><dt>Slots</dt><dd>{backend.slots_in_use}/{backend.slots_total}</dd></div>
              <div><dt>Sends</dt><dd>{backend.sends}</dd></div>
              <div><dt>Responses</dt><dd>{backend.responses}</dd></div>
              <div><dt>Avg</dt><dd>{formatDuration(backend.avg_response_ms)}</dd></div>
            </dl>
            <div className="hub-holders">
              {backend.holders.length > 0 ? backend.holders.map((holder) => (
                <span key={`${backend.name}-${holder.session_id}`}>{holder.owner}</span>
              )) : <span>no holder</span>}
            </div>
          </article>
        ))}
      </section>

      <section className="hub-workbench">
        <aside className="hub-sessions ak-panel">
          <header>
            <div>
              <h2>Conversations</h2>
              <span>{hubSessions.length} sessions</span>
            </div>
            <Badge tone="info">/api/sessions</Badge>
          </header>
          <div className="hub-session-list">
            {hubSessions.map((session) => (
              <button
                className={session.session_id === selectedSession.session_id ? 'active' : ''}
                key={session.session_id}
                type="button"
                onClick={() => setSelectedSessionId(session.session_id)}
              >
                <span>
                  <strong>{session.owner}</strong>
                  <small>{session.description}</small>
                </span>
                <span className="hub-session-meta">
                  <Badge tone={statusTone(session.status)}>{session.status}</Badge>
                  <small>{session.llms.join(' · ')}</small>
                </span>
              </button>
            ))}
          </div>
        </aside>

        <section className="hub-chat ak-panel">
          <header className="hub-chat-head">
            <div>
              <h2>{selectedSession.description}</h2>
              <span>{selectedSession.owner} · {selectedSession.session_id}</span>
            </div>
            <div className="hub-chat-head__badges">
              <Badge tone={selectedSession.resumable ? 'accent' : 'neutral'}>{selectedSession.resumable ? 'resumable' : 'leased'}</Badge>
              <Badge tone={statusTone(selectedSession.status)}>{selectedSession.status}</Badge>
            </div>
          </header>

          <div className="hub-target-bar">
            <div className="hub-segmented">
              {(['broadcast', 'group', 'single'] as HubSendMode[]).map((mode) => (
                <button className={sendMode === mode ? 'active' : ''} key={mode} type="button" onClick={() => setSendMode(mode)}>
                  {mode === 'broadcast' ? 'All' : mode === 'group' ? 'Subgroup' : 'Single'}
                </button>
              ))}
            </div>
            <div className="hub-targets">
              {availableTargets.map((backend) => (
                <button
                  className={[effectiveTargets.includes(backend) ? 'active' : '', sendMode === 'broadcast' ? 'locked' : ''].filter(Boolean).join(' ')}
                  disabled={sendMode === 'broadcast'}
                  key={backend}
                  type="button"
                  onClick={() => {
                    if (sendMode === 'single') setActiveResponseBackend(backend);
                    if (sendMode === 'group') toggleBackend(backend);
                  }}
                >
                  {backend}
                </button>
              ))}
            </div>
          </div>

          <div className="hub-response-tabs">
            {availableTargets.map((backend) => (
              <button className={activeResponseBackend === backend ? 'active' : ''} key={backend} type="button" onClick={() => setActiveResponseBackend(backend)}>
                {backend}
              </button>
            ))}
          </div>

          <div className="hub-response-grid">
            {availableTargets.map((backend) => (
              <section className={activeResponseBackend === backend ? 'active' : ''} key={backend}>
                <header>
                  <strong>{backend}</strong>
                  <Badge tone={effectiveTargets.includes(backend) ? 'accent' : 'neutral'}>{effectiveTargets.includes(backend) ? 'targeted' : 'idle'}</Badge>
                </header>
                <div className="hub-message-list">
                  {sessionMessages.filter((message) => message.role === 'user' || message.backend === backend).map((message) => (
                    <article className={`hub-message role-${message.role}`} key={`${backend}-${message.id}`}>
                      <span>{message.role === 'user' ? 'you' : backend} · {message.at}</span>
                      <p>{message.text}</p>
                    </article>
                  ))}
                </div>
              </section>
            ))}
          </div>

          <footer className="hub-composer">
            <textarea value={draft} onChange={(event) => setDraft(event.target.value)} placeholder="Message to selected Hub session" rows={3} />
            <button className="ak-button ak-button--primary" type="button" onClick={sendMessage}>
              <Send size={16} />
              Send
            </button>
          </footer>
        </section>
      </section>
    </div>
  );
}

function DetailInspector({
  story,
  width,
  onClose,
  onResizeStart,
}: {
  story: Story;
  width: number;
  onClose: () => void;
  onResizeStart: () => void;
}) {
  const [activeTab, setActiveTab] = useState<'spec' | 'evidence' | 'kpi'>('spec');
  return (
    <aside className="detail-inspector ak-panel" data-story-inspector="true" style={{ width }}>
      <div
        aria-label="Inspector-Breite anpassen"
        className="inspector-resize-handle"
        role="separator"
        onMouseDown={(event) => {
          event.preventDefault();
          onResizeStart();
        }}
      />
      <header className="inspector-head">
        <div>
          <p className="eyebrow">Story Inspector</p>
          <h2>{story.id}</h2>
        </div>
        <button className="ak-button" type="button" onClick={onClose}>
          <X size={16} />
          Close
        </button>
      </header>
      <div className="file-tabs" role="tablist">
        <button className={activeTab === 'spec' ? 'active' : ''} type="button" onClick={() => setActiveTab('spec')}>
          Spezifikation
        </button>
        <button className={activeTab === 'evidence' ? 'active' : ''} type="button" onClick={() => setActiveTab('evidence')}>
          Ergebnis
        </button>
        <button className={activeTab === 'kpi' ? 'active' : ''} type="button" onClick={() => setActiveTab('kpi')}>
          KPIs
        </button>
      </div>
      <Detail story={story} activeTab={activeTab} />
    </aside>
  );
}

function Detail({ story, activeTab }: { story: Story; activeTab: 'spec' | 'evidence' | 'kpi' }) {
  return (
    <aside className="detail">
      <div className="detail-head">
        <span className="node-id">{story.id}</span>
        <Badge tone={statusClass[story.status]}>{story.status}</Badge>
      </div>
      {activeTab === 'spec' && <SpecificationTab story={story} />}
      {activeTab === 'evidence' && <EvidenceTab story={story} />}
      {activeTab === 'kpi' && <KpiTab story={story} />}
    </aside>
  );
}

function SpecificationTab({ story }: { story: Story }) {
  const conceptRefs = story.conceptRefs ?? ['FK-21 Story-Creation', 'FK-24 Story Types'];
  const guardrailRefs = story.guardrailRefs ?? ['Definition of Done', 'ZERO-DEBT'];
  const definitionOfDone = story.definitionOfDone ?? ['Build kompiliert erfolgreich', 'Alle Tests gruen', 'Keine Secrets im Diff', 'Code-Review durch mindestens ein weiteres LLM', 'Akzeptanzkriterien nachweislich erfuellt'];
  return (
    <>
      <h2>{story.title}</h2>
      <div className="detail-grid">
        <Info label="Typ" value={story.type} />
        <Info label="Status" value={story.status} />
        <Info label="Repo" value={story.repo} />
        <Info label="Module" value={story.module} />
        <Info label="Epic" value={story.epic} />
        <Info label="Impact" value={story.changeImpact} />
        <Info label="Concept Quality" value={story.conceptQuality} />
        <Info label="Owner" value={story.owner} />
      </div>

      {story.blocker && <div className="blocker-box">{story.blocker}</div>}

      <section className="detail-section">
        <h3>Bedarf und Loesungsansatz</h3>
        <p className="story-body">
          <strong>Bedarf:</strong> {story.need ?? `${story.title} wird aus einem fachlichen Bedarf in eine strukturierte Story ueberfuehrt.`}
        </p>
        <p className="story-body">
          <strong>Loesung:</strong> {story.solution ?? 'Der create-userstory-Prozess strukturiert Problem, Loesungsansatz, Felder, Referenzen und Akzeptanzkriterien.'}
        </p>
      </section>

      <section className="detail-section">
        <h3>Akzeptanzkriterien</h3>
        <ul className="acceptance-list">
          {story.acceptance.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      </section>

      <section className="detail-section">
        <h3>Abhaengigkeiten</h3>
        <div className="dependency-list">
          {story.dependencies.length ? (
            story.dependencies.map((dependency) => <Badge tone="accent" key={dependency}>{dependency}</Badge>)
          ) : (
            <p className="empty">Keine vorgelagerten Story-Abhaengigkeiten.</p>
          )}
        </div>
      </section>

      <section className="detail-section">
        <h3>Referenzen und Guardrails</h3>
        <div className="reference-grid">
          <div className="reference-box ak-panel">
            <strong>Konzeptquellen</strong>
            {conceptRefs.map((ref) => <span key={ref}>{ref}</span>)}
          </div>
          <div className="reference-box ak-panel">
            <strong>Guardrails</strong>
            {guardrailRefs.map((ref) => <span key={ref}>{ref}</span>)}
          </div>
          <div className="reference-box ak-panel">
            <strong>Definition of Done</strong>
            {definitionOfDone.map((item) => <span key={item}>{item}</span>)}
          </div>
        </div>
      </section>

      <section className="detail-section concept">
        <h3>Konzeptanker</h3>
        {conceptAnchors.map((anchor) => (
          <p key={anchor}>{anchor}</p>
        ))}
      </section>
    </>
  );
}

function EvidenceTab({ story }: { story: Story }) {
  const evidence = story.evidence ?? {
    qaCycleId: 'not-started',
    qaCycleRound: story.qaRounds,
    evidenceEpoch: '-',
    evidenceFingerprint: '-',
    manifestHash: '-',
    bundleEntries: [
      { authority: 'STORY_SPEC' as const, path: `stories/${story.id}/story.md`, status: 'INCLUDED' as const },
      { authority: 'CONCEPT' as const, path: story.conceptRefs?.[0] ?? 'FK-21 Story-Creation', status: 'INCLUDED' as const },
    ],
  };
  return (
    <>
      <h2>Ergebnis und Evidenz</h2>
      <section className="detail-section">
        <h3>QA-Zyklus und Evidence Bundle</h3>
        <div className="evidence-summary">
          <Info label="QA Cycle" value={evidence.qaCycleId} />
          <Info label="Round" value={String(evidence.qaCycleRound)} />
          <Info label="Evidence Epoch" value={evidence.evidenceEpoch} />
          <Info label="Fingerprint" value={evidence.evidenceFingerprint} />
          <Info label="Manifest" value={evidence.manifestHash} />
        </div>
        <div className="bundle-list">
          {evidence.bundleEntries.map((entry) => (
            <div className="bundle-entry" key={`${entry.authority}-${entry.path}`}>
              <Badge tone={entry.status === 'UNRESOLVED' ? 'danger' : entry.status === 'REQUESTED' ? 'warning' : 'accent'}>{entry.authority}</Badge>
              <span>{entry.path}</span>
              <Badge tone={entry.status === 'UNRESOLVED' ? 'danger' : entry.status === 'REQUESTED' ? 'warning' : 'success'}>{entry.status}</Badge>
            </div>
          ))}
        </div>
      </section>

      <section className="detail-section">
        <h3>Phasenstatus</h3>
        <div className="phase-list">
          {story.phases.map((phase) => (
            <div className={`phase ${phase.state}`} key={phase.label}>
              {phaseIcon[phase.state]}
              <div>
                <strong>{phase.label}</strong>
                <span>{phase.detail}</span>
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className="detail-section">
        <h3>Review-Runden</h3>
        <div className="review-rounds">
          {Array.from({ length: Math.max(story.qaRounds, story.status === 'Done' ? 1 : 0) }).map((_, index) => (
            <article className="review-round ak-panel" key={index}>
              <div>
                <strong>Review Runde {index + 1}</strong>
                <span>{index + 1 === story.qaRounds && story.status !== 'Done' ? 'Aktuelle Runde' : 'Abgeschlossen'}</span>
              </div>
              <Badge tone={story.gates.some((gate) => gate.state === 'ERROR') ? 'danger' : story.gates.some((gate) => gate.state === 'WARNING') ? 'warning' : 'success'}>
                {story.gates.some((gate) => gate.state === 'ERROR') ? 'FAIL' : story.gates.some((gate) => gate.state === 'WARNING') ? 'WARNING' : 'PASS'}
              </Badge>
            </article>
          ))}
          {story.qaRounds === 0 && <p className="empty">Noch keine Review-Runde abgeschlossen.</p>}
        </div>
      </section>

      <section className="detail-section">
        <h3>Gates und Artefakt-Evidenz</h3>
        <div className="gate-list">
          {story.gates.map((gate) => (
            <Badge tone={gate.state === 'PASS' ? 'success' : gate.state === 'WARNING' ? 'warning' : 'danger'} key={gate.label}>
              {gate.label}: {gate.state}
            </Badge>
          ))}
        </div>
      </section>

      <section className="detail-section">
        <h3>Evidenzlog</h3>
        <div className="event-list">
          {story.events.length ? (
            story.events.map((event) => (
              <div className={`event ${event.severity}`} key={`${event.time}-${event.type}`}>
                <span>{event.time}</span>
                <strong>{event.type}</strong>
                <p>{event.detail}</p>
              </div>
            ))
          ) : (
            <p className="empty">Noch keine Evidenz-Events.</p>
          )}
        </div>
      </section>
    </>
  );
}

function KpiTab({ story }: { story: Story }) {
  const telemetry = story.telemetry;
  const observedLlmCalls = story.events.filter((event) => event.type === 'llm_call').length || (story.qaRounds > 0 ? story.qaRounds * 3 : 0);
  const llmCalls = telemetry?.llmCalls ?? observedLlmCalls;
  const tokenEstimate = (telemetry?.tokensIn ?? 0) + (telemetry?.tokensOut ?? 0) || story.qaRounds * 42000 + (story.status === 'In Progress' ? 28000 : 12000);

  return (
    <>
      <h2>KPI und Telemetrie</h2>
      <div className="kpi-grid">
        <Info label="Laufzeit" value={story.processingTime} />
        <Info label="QA-Runden" value={String(story.qaRounds)} />
        <Info label="LLM Calls" value={String(llmCalls)} />
        <Info label="Tokens Total" value={tokenEstimate.toLocaleString('de-DE')} />
        <Info label="Review Events" value={`${telemetry?.reviewResponses ?? story.events.filter((event) => event.type === 'review_response').length}/${telemetry?.reviewRequests ?? story.events.filter((event) => event.type === 'review_request').length}`} />
        <Info label="Increments" value={String(telemetry?.incrementCommits ?? story.events.filter((event) => event.type === 'increment_commit').length)} />
        <Info label="Completed At" value={story.completedAt ?? '-'} />
      </div>

      <section className="detail-section">
        <h3>Telemetry Stream</h3>
        <div className="event-list">
          {story.events.length ? (
            story.events.map((event) => (
              <div className={`event ${event.severity}`} key={`${event.time}-${event.type}`}>
                <span>{event.time}</span>
                <strong>{event.type}</strong>
                <p>{event.detail}</p>
              </div>
            ))
          ) : (
            <p className="empty">Noch keine Runtime-Telemetrie.</p>
          )}
        </div>
      </section>

      <section className="detail-section">
        <h3>LLM-/Pool-Aufrufe</h3>
        <div className="pool-list">
          {(telemetry?.pools ?? [
            { pool: 'chatgpt' as const, role: 'qa_review', calls: Math.max(story.qaRounds, 0), status: 'PASS' as const },
            { pool: 'gemini' as const, role: 'semantic_review', calls: Math.max(story.qaRounds - 1, 0), status: 'PASS' as const },
            { pool: 'qwen' as const, role: 'doc_fidelity', calls: Math.max(story.qaRounds - 1, 0), status: 'PASS' as const },
          ]).map((pool) => (
            <div className="pool-row" key={`${pool.pool}-${pool.role}`}>
              <span>{pool.pool}</span>
              <small>{pool.role}</small>
              <strong>{pool.calls} calls</strong>
              <Badge tone={pool.status === 'FAIL' ? 'danger' : pool.status === 'WARNING' ? 'warning' : 'success'}>{pool.status}</Badge>
            </div>
          ))}
        </div>
      </section>
    </>
  );
}

function Badge({ tone = 'neutral', children }: { tone?: string; children: ReactNode }) {
  return <span className={`ak-badge tone-${tone}`}>{children}</span>;
}

function Sparkline({ values }: { values: number[] }) {
  return (
    <div className="sparkline">
      {values.map((value, index) => (
        <span key={index} style={{ height: `${value}%` }} />
      ))}
    </div>
  );
}

function Info({ label, value }: { label: string; value: string }) {
  return (
    <div className="info ak-panel">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}
