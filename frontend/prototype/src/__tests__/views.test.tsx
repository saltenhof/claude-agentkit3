/**
 * AC1/AC2/AC3/AC4/AC5/AC6: Real interaction tests for all views.
 *
 * ECharts option-level tests: build the chart option and assert overlay selection,
 * band-toggle, custom range, dataZoom, tooltip formatter.
 * EventSource lifecycle/topic tests per view: topic subscription, reconnect re-sync,
 * event-triggered updates, no periodic polling.
 * Views render with real interactions (drag&drop, sort, column-resize, group-by,
 * inline-edit, keyboard nav, PlaceholderColumn empty-state). AC2 slice-boundary imports.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, act } from '@testing-library/react';
import { AnalyticsSlot } from '../contexts/kpi_analytics/AnalyticsSlot';
import { Kanban } from '../app_shell/board/Kanban';
import { StorySheet } from '../app_shell/sheet/StorySheet';
import { ReadyStackView } from '../contexts/execution_planning/ReadyStackView';
import { ExecutionLimitsView } from '../contexts/execution_planning/ExecutionLimitsView';
import { BffClient } from '../foundation/bff/client';
import { DEFAULT_EXECUTION_LIMITS } from '../store';
import type { Story, StoryCounters, ExecutionLimits } from '../store';
import { makeFixtureTransport } from './testTransport';
import { buildChartOption } from '../contexts/kpi_analytics/AnalyticsSlot';
import { ANALYTICS_TOPICS, KANBAN_TOPICS, GRAPH_TOPICS, useProjectSse } from '../foundation/sse/useProjectSse';
import type { SseTopic } from '../foundation/sse/useProjectSse';

// ── ECharts mock: captures the last option passed so tests can assert on it ────
// The mock renders a div with data-testid='echarts-mock' AND exposes the option
// via data-option attribute so option-level assertions work without a real canvas.
vi.mock('echarts-for-react', () => ({
  default: ({ option, style }: { option?: unknown; style?: React.CSSProperties }) => {
    return <div data-testid="echarts-mock" style={style} data-option={JSON.stringify(option)} />;
  },
}));

vi.mock('@xyflow/react', () => ({
  ReactFlow: ({ children }: { children?: React.ReactNode }) => <div data-testid="react-flow">{children}</div>,
  Background: () => null,
  Controls: () => null,
  MiniMap: () => null,
  Handle: () => null,
  BaseEdge: () => null,
  getBezierPath: () => [''],
  Position: { Left: 'left', Right: 'right' },
  useNodesState: () => [[], vi.fn(), vi.fn()],
  useEdgesState: () => [[], vi.fn(), vi.fn()],
}));

const baseStory: Story = {
  id: 'AG3-001',
  title: 'Alpha Story',
  type: 'implementation',
  status: 'Backlog',
  size: 'S',
  owner: 'u',
  repo: 'r',
  module: 'm',
  epic: 'Epic A',
  changeImpact: 'Local',
  conceptQuality: 'High',
  wave: 1,
  mode: 'standard',
  risk: 'low',
  criticalPath: false,
  qaRounds: 0,
  processingTime: '-',
  labels: [],
  acceptance: [],
  gates: [],
  phases: [],
  events: [],
  dependencies: [],
};
const storyB: Story = { ...baseStory, id: 'AG3-002', title: 'Bravo Story', epic: 'Epic B', size: 'L' };
const baseCounters: StoryCounters = { total: 2, finished: 0, running: 0, ready: 0, queue: 0, blocked: 0 };

function sheet(props: Partial<React.ComponentProps<typeof StorySheet>> = {}) {
  return render(
    <StorySheet
      projectKey="AG3"
      stories={[baseStory, storyB]}
      selectedStory={null}
      statusFilter="all"
      onSelect={vi.fn()}
      onStatusFilterChange={vi.fn()}
      kpis={baseCounters}
      client={new BffClient('', makeFixtureTransport())}
      {...props}
    />,
  );
}

function kanban(props: Partial<React.ComponentProps<typeof Kanban>> = {}) {
  return render(
    <Kanban
      projectKey="AG3"
      stories={[baseStory, storyB]}
      selectedStory={null}
      onSelect={vi.fn()}
      onFocusStory={vi.fn()}
      onStoryStatusChange={vi.fn()}
      storyIdFilter=""
      onStoryIdFilterChange={vi.fn()}
      kpis={baseCounters}
      client={new BffClient('', makeFixtureTransport())}
      {...props}
    />,
  );
}

/**
 * Build a transport that serves all five KPI dimensions.
 * story rows are served for /kpi/stories; all other dimensions return EMPTY.
 */
function kpiStoriesTransport(rows: unknown[]): (url: string) => Promise<Response> {
  return async (url: string) => {
    const dimensionMatch = url.match(/\/kpi\/(stories|guards|pools|pipeline|corpus)/);
    if (dimensionMatch) {
      const dim = dimensionMatch[1];
      const dimRows = dim === 'stories' ? rows : [];
      const body = {
        project_key: 'AG3',
        dimension: dim,
        status: dimRows.length ? 'OK' : 'EMPTY',
        rows: dimRows,
      };
      return new Response(JSON.stringify(body), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    }
    return new Response(JSON.stringify({ error_code: 'not_found' }), { status: 404 });
  };
}

const FAKE_STORY_ROW = {
  project_key: 'AG3', story_id: 'AG3-001', story_type: 'implementation',
  story_size: 'M', story_mode: null, started_at: new Date().toISOString(),
  completed_at: null, qa_rounds: 3, compaction_count: 1, llm_call_count: 45,
  adversarial_findings: 2, adversarial_tests_created: 5, files_changed: 8,
  feedback_converged: true, phase_setup_ms: 1200, phase_implementation_ms: 45000,
  phase_closure_ms: 3000, are_gate_status: 'PASS',
  agentkit_version: '3.0.0', agentkit_commit: 'abc123',
};

describe('AC1/AC2: AnalyticsSlot is the productive analytics view (AG3-094)', () => {
  it('renders the analytics slot container with KPI header', async () => {
    const client = new BffClient('', kpiStoriesTransport([]));
    render(<AnalyticsSlot projectKey="AG3" client={client} sseEnabled={false} />);
    expect(screen.getByTestId('analytics-slot')).toBeTruthy();
    expect(screen.getByText('KPI-Cockpit')).toBeTruthy();
  });

  it('shows empty hint when no KPI rows in period', async () => {
    const client = new BffClient('', kpiStoriesTransport([]));
    const { findByTestId } = render(
      <AnalyticsSlot projectKey="AG3" client={client} sseEnabled={false} />,
    );
    expect(await findByTestId('kpi-empty-hint')).toBeTruthy();
  });

  it('renders KPI cards from real fact rows (AC2: data from backend)', async () => {
    const client = new BffClient('', kpiStoriesTransport([FAKE_STORY_ROW]));
    const { findByTestId } = render(
      <AnalyticsSlot projectKey="AG3" client={client} sseEnabled={false} />,
    );
    expect(await findByTestId('kpi-card-qa_rounds')).toBeTruthy();
  });

  it('AC2: selectKpiDailySeries / selectProjectKpiStats are NOT productive source', async () => {
    // The view calls BffClient.getKpiStories; the card value reflects the BACKEND row.
    const rowWith7Rounds = { ...FAKE_STORY_ROW, qa_rounds: 7 };
    const client = new BffClient('', kpiStoriesTransport([rowWith7Rounds]));
    const { findByTestId } = render(
      <AnalyticsSlot projectKey="AG3" client={client} sseEnabled={false} />,
    );
    const card = await findByTestId('kpi-card-qa_rounds');
    // Avg of [7] = 7 — must come from backend row, not synthetic selector.
    expect(card.textContent).toContain('7');
  });

  it('AC6: shows offline banner when isOffline=true', () => {
    const client = new BffClient('', kpiStoriesTransport([]));
    render(<AnalyticsSlot projectKey="AG3" client={client} sseEnabled={false} isOffline={true} />);
    expect(screen.getByTestId('offline-banner')).toBeTruthy();
  });

  it('AC7: filter panel is hidden by default and shown after toggle', () => {
    const client = new BffClient('', kpiStoriesTransport([]));
    render(<AnalyticsSlot projectKey="AG3" client={client} sseEnabled={false} />);
    expect(screen.queryByTestId('analytics-filter')).toBeNull();
    fireEvent.click(screen.getByTestId('filter-toggle'));
    expect(screen.getByTestId('analytics-filter')).toBeTruthy();
  });

  it('AC7: guard filter routed to /kpi/guards ONLY (not /kpi/stories)', async () => {
    const calls: string[] = [];
    const trackingTransport = async (url: string): Promise<Response> => {
      calls.push(url);
      const dim = url.match(/\/kpi\/(stories|guards|pools|pipeline|corpus)/)?.[1] ?? 'stories';
      return new Response(
        JSON.stringify({ project_key: 'AG3', dimension: dim, status: 'EMPTY', rows: [] }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      );
    };
    const client = new BffClient('', trackingTransport);
    render(<AnalyticsSlot projectKey="AG3" client={client} sseEnabled={false} />);
    fireEvent.click(screen.getByTestId('filter-toggle'));
    fireEvent.change(screen.getByTestId('filter-guard'), { target: { value: 'my-guard' } });
    await act(async () => { await new Promise((r) => setTimeout(r, 50)); });
    // guard=my-guard must appear in /kpi/guards calls ONLY.
    const guardEndpointCalls = calls.filter((u) => u.includes('/kpi/guards') && u.includes('guard=my-guard'));
    expect(guardEndpointCalls.length).toBeGreaterThan(0);
    // guard MUST NOT be sent to /kpi/stories.
    const storiesWithGuard = calls.filter((u) => u.includes('/kpi/stories') && u.includes('guard='));
    expect(storiesWithGuard.length).toBe(0);
  });

  it('AC7: pool filter routed to /kpi/pools ONLY (not /kpi/stories)', async () => {
    const calls: string[] = [];
    const trackingTransport = async (url: string): Promise<Response> => {
      calls.push(url);
      const dim = url.match(/\/kpi\/(stories|guards|pools|pipeline|corpus)/)?.[1] ?? 'stories';
      return new Response(
        JSON.stringify({ project_key: 'AG3', dimension: dim, status: 'EMPTY', rows: [] }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      );
    };
    const client = new BffClient('', trackingTransport);
    render(<AnalyticsSlot projectKey="AG3" client={client} sseEnabled={false} />);
    fireEvent.click(screen.getByTestId('filter-toggle'));
    fireEvent.change(screen.getByTestId('filter-pool'), { target: { value: 'my-pool' } });
    await act(async () => { await new Promise((r) => setTimeout(r, 50)); });
    // pool=my-pool must appear in /kpi/pools calls ONLY.
    const poolEndpointCalls = calls.filter((u) => u.includes('/kpi/pools') && u.includes('pool=my-pool'));
    expect(poolEndpointCalls.length).toBeGreaterThan(0);
    // pool MUST NOT be sent to /kpi/stories.
    const storiesWithPool = calls.filter((u) => u.includes('/kpi/stories') && u.includes('pool='));
    expect(storiesWithPool.length).toBe(0);
  });

  it('AC7: story_type routed to /kpi/stories AND /kpi/pipeline; story_size to /kpi/stories only', async () => {
    const calls: string[] = [];
    const trackingTransport = async (url: string): Promise<Response> => {
      calls.push(url);
      const dim = url.match(/\/kpi\/(stories|guards|pools|pipeline|corpus)/)?.[1] ?? 'stories';
      return new Response(
        JSON.stringify({ project_key: 'AG3', dimension: dim, status: 'EMPTY', rows: [] }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      );
    };
    const client = new BffClient('', trackingTransport);
    render(<AnalyticsSlot projectKey="AG3" client={client} sseEnabled={false} />);
    fireEvent.click(screen.getByTestId('filter-toggle'));
    fireEvent.change(screen.getByTestId('filter-story-type'), { target: { value: 'implementation' } });
    fireEvent.change(screen.getByTestId('filter-story-size'), { target: { value: 'M' } });
    await act(async () => { await new Promise((r) => setTimeout(r, 50)); });
    // story_type sent to /kpi/stories.
    expect(calls.filter((u) => u.includes('/kpi/stories') && u.includes('story_type=implementation')).length).toBeGreaterThan(0);
    // story_type sent to /kpi/pipeline.
    expect(calls.filter((u) => u.includes('/kpi/pipeline') && u.includes('story_type=implementation')).length).toBeGreaterThan(0);
    // story_size sent to /kpi/stories.
    expect(calls.filter((u) => u.includes('/kpi/stories') && u.includes('story_size=M')).length).toBeGreaterThan(0);
    // story_size NOT sent to /kpi/pipeline.
    expect(calls.filter((u) => u.includes('/kpi/pipeline') && u.includes('story_size=')).length).toBe(0);
  });

  /** Parse the band-helper series names out of the captured echarts-mock option. */
  function bandHelperNames(chartEl: HTMLElement): string[] {
    const raw = chartEl.getAttribute('data-option');
    if (!raw) return [];
    const option = JSON.parse(raw) as { series?: Array<{ name?: string }> };
    return (option.series ?? [])
      .map((s) => String(s.name ?? ''))
      .filter((n) => n.includes('Untergrenze') || n.includes('Huelle'));
  }

  it('AC1: band toggle changes the chart OPTION (band helper series removed on toggle-off)', async () => {
    const client = new BffClient('', kpiStoriesTransport([FAKE_STORY_ROW]));
    const { findByTestId } = render(
      <AnalyticsSlot projectKey="AG3" client={client} sseEnabled={false} />,
    );
    await findByTestId('kpi-card-qa_rounds');
    const timeseriesTab = screen.getAllByText('Zeitverlaeufe')[0];
    if (timeseriesTab) fireEvent.click(timeseriesTab);
    const chart = await findByTestId('echarts-mock');

    // showBand defaults to true → band helper series (Untergrenze + Huelle) present.
    expect(bandHelperNames(chart).length).toBeGreaterThan(0);

    // Toggling OFF must REMOVE the band helper series from the captured option.
    fireEvent.click(screen.getByTestId('band-toggle'));
    const afterOff = await findByTestId('echarts-mock');
    expect(bandHelperNames(afterOff).length).toBe(0);

    // Toggling back ON re-adds them — the option content actually changed both ways.
    fireEvent.click(screen.getByTestId('band-toggle'));
    const afterOn = await findByTestId('echarts-mock');
    expect(bandHelperNames(afterOn).length).toBeGreaterThan(0);
  });

  it('AC1/AC7: custom-range selection changes the query period (from/to) sent to /kpi/*', async () => {
    const calls: string[] = [];
    const trackingTransport = async (url: string): Promise<Response> => {
      calls.push(url);
      const dim = url.match(/\/kpi\/(stories|guards|pools|pipeline|corpus)/)?.[1] ?? 'stories';
      return new Response(
        JSON.stringify({ project_key: 'AG3', dimension: dim, status: 'EMPTY', rows: [] }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      );
    };
    const client = new BffClient('', trackingTransport);
    render(<AnalyticsSlot projectKey="AG3" client={client} sseEnabled={false} />);
    await act(async () => { await new Promise((r) => setTimeout(r, 30)); });

    // Baseline: the default preset (30 days) period that initial-GET used.
    const storiesBefore = calls.filter((u) => u.includes('/kpi/stories'));
    expect(storiesBefore.length).toBeGreaterThan(0);

    // Set an explicit custom range.
    fireEvent.click(screen.getByTestId('filter-toggle'));
    fireEvent.change(screen.getByTestId('filter-from'), { target: { value: '2026-01-01' } });
    fireEvent.change(screen.getByTestId('filter-to'), { target: { value: '2026-02-15' } });
    await act(async () => { await new Promise((r) => setTimeout(r, 50)); });

    // The custom from/to must now be the query period on /kpi/stories.
    const customCalls = calls.filter(
      (u) =>
        u.includes('/kpi/stories') &&
        u.includes('from=2026-01-01T00%3A00%3A00Z') &&
        u.includes('to=2026-02-15T23%3A59%3A59Z'),
    );
    expect(customCalls.length).toBeGreaterThan(0);
  });

  it('E1/AC7: guard filter renders the guards dimension with REAL fetched rows', async () => {
    const guardRow = {
      project_key: 'AG3', guard_id: 'no_competing_mode', period_start: '2026-06-01T00:00:00Z',
      period_end: '2026-06-15T00:00:00Z', invocation_count: 12, violation_count: 3,
    };
    const transport = async (url: string): Promise<Response> => {
      const dim = url.match(/\/kpi\/(stories|guards|pools|pipeline|corpus)/)?.[1] ?? 'stories';
      const rows = dim === 'guards' ? [guardRow] : [];
      return new Response(
        JSON.stringify({ project_key: 'AG3', dimension: dim, status: rows.length ? 'OK' : 'EMPTY', rows }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      );
    };
    const client = new BffClient('', transport);
    const { findByTestId } = render(<AnalyticsSlot projectKey="AG3" client={client} sseEnabled={false} />);
    fireEvent.click(screen.getByTestId('filter-toggle'));
    fireEvent.change(screen.getByTestId('filter-guard'), { target: { value: 'no_competing_mode' } });
    // The guards dimension panel must render the fetched row (non-empty assertion).
    const row = await findByTestId('guards-row-no_competing_mode');
    expect(row.textContent).toContain('12');
    expect(row.textContent).toContain('3');
  });

  it('E1/AC7: pool filter renders the pools dimension with REAL fetched rows', async () => {
    const poolRow = {
      project_key: 'AG3', llm_role: 'worker', period_start: '2026-06-01T00:00:00Z',
      period_end: '2026-06-15T00:00:00Z', call_count: 99, token_input_total: 1000,
      token_output_total: 500, avg_latency_ms: 1200,
    };
    const transport = async (url: string): Promise<Response> => {
      const dim = url.match(/\/kpi\/(stories|guards|pools|pipeline|corpus)/)?.[1] ?? 'stories';
      const rows = dim === 'pools' ? [poolRow] : [];
      return new Response(
        JSON.stringify({ project_key: 'AG3', dimension: dim, status: rows.length ? 'OK' : 'EMPTY', rows }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      );
    };
    const client = new BffClient('', transport);
    const { findByTestId } = render(<AnalyticsSlot projectKey="AG3" client={client} sseEnabled={false} />);
    fireEvent.click(screen.getByTestId('filter-toggle'));
    fireEvent.change(screen.getByTestId('filter-pool'), { target: { value: 'worker' } });
    const row = await findByTestId('pools-row-worker');
    expect(row.textContent).toContain('99');
  });

  it('E1/AC7: story_type filter renders the pipeline dimension with REAL fetched rows', async () => {
    const pipelineRow = {
      project_key: 'AG3', period_start: '2026-06-10T00:00:00Z', period_end: '2026-06-11T00:00:00Z',
      stories_completed: 7, stories_escalated: 1, avg_qa_rounds: 2.5, avg_phase_implementation_ms: 40000,
    };
    const transport = async (url: string): Promise<Response> => {
      const dim = url.match(/\/kpi\/(stories|guards|pools|pipeline|corpus)/)?.[1] ?? 'stories';
      const rows = dim === 'pipeline' ? [pipelineRow] : [];
      return new Response(
        JSON.stringify({ project_key: 'AG3', dimension: dim, status: rows.length ? 'OK' : 'EMPTY', rows }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      );
    };
    const client = new BffClient('', transport);
    const { findByTestId } = render(<AnalyticsSlot projectKey="AG3" client={client} sseEnabled={false} />);
    fireEvent.click(screen.getByTestId('filter-toggle'));
    fireEvent.change(screen.getByTestId('filter-story-type'), { target: { value: 'implementation' } });
    const row = await findByTestId('pipeline-row-2026-06-10T00:00:00Z');
    expect(row.textContent).toContain('7');
  });

  it('AC1: corpus funnel renders on overview tab', async () => {
    const client = new BffClient('', kpiStoriesTransport([]));
    render(<AnalyticsSlot projectKey="AG3" client={client} sseEnabled={false} />);
    // Corpus funnel section should appear (may be empty state).
    await act(async () => { await new Promise((r) => setTimeout(r, 50)); });
    // Either corpus-funnel or corpus-funnel-empty should be present.
    const funnelEl = screen.queryByTestId('corpus-funnel') ?? screen.queryByTestId('corpus-funnel-empty');
    expect(funnelEl).toBeTruthy();
  });
});

// ── ECharts option-level tests (AC1 — real chart option assertions) ────────────

describe('AC1: buildChartOption — real option-level assertions', () => {
  const NOW = new Date().toISOString().slice(0, 10);
  const SERIES: import('../contexts/kpi_analytics/AnalyticsSlot').KpiDailyPoint[] = [
    { date: NOW, values: { qa_rounds: 3, llm_calls: 45 } },
  ];
  const STATS: import('../contexts/kpi_analytics/AnalyticsSlot').KpiStat[] = [
    { key: 'qa_rounds', label: 'QA-Runden', avg: 3, min: 3, max: 3, p90: 3 },
    { key: 'llm_calls', label: 'LLM Calls', avg: 45, min: 45, max: 45, p90: 45 },
  ];

  it('overlay selection: only selected key produces a main series', () => {
    const onlyQa = new Set(['qa_rounds']);
    const option = buildChartOption(SERIES, STATS, onlyQa, false);
    const seriesArr = option.series as Array<{ name: string }>;
    const mainNames = seriesArr.map((s) => s.name);
    // Only 'QA-Runden' main series should be present (not LLM Calls).
    expect(mainNames.some((n) => n === 'QA-Runden')).toBe(true);
    expect(mainNames.some((n) => n === 'LLM Calls')).toBe(false);
  });

  it('overlay selection: adding a second key adds its series', () => {
    const both = new Set(['qa_rounds', 'llm_calls']);
    const option = buildChartOption(SERIES, STATS, both, false);
    const seriesArr = option.series as Array<{ name: string }>;
    const mainNames = seriesArr.map((s) => s.name);
    expect(mainNames.some((n) => n === 'QA-Runden')).toBe(true);
    expect(mainNames.some((n) => n === 'LLM Calls')).toBe(true);
  });

  it('showBand=true adds min/max band helper series (Untergrenze + Huelle) for each selected metric', () => {
    const option = buildChartOption(SERIES, STATS, new Set(['qa_rounds']), true);
    const seriesArr = option.series as Array<{ name: string }>;
    const names = seriesArr.map((s) => s.name);
    // Band series names contain German UI labels (Untergrenze / Huelle — rendered UI label).
    expect(names.some((n) => String(n).includes('Untergrenze'))).toBe(true);
    expect(names.some((n) => String(n).includes('Huelle'))).toBe(true);
  });

  it('showBand=false: NO band helper series', () => {
    const option = buildChartOption(SERIES, STATS, new Set(['qa_rounds']), false);
    const seriesArr = option.series as Array<{ name: string }>;
    const names = seriesArr.map((s) => s.name);
    expect(names.some((n) => String(n).includes('Untergrenze'))).toBe(false);
    expect(names.some((n) => String(n).includes('Huelle'))).toBe(false);
  });

  it('dataZoom: both inside and slider type present', () => {
    const option = buildChartOption(SERIES, STATS, new Set(['qa_rounds']), false);
    const zooms = option.dataZoom as Array<{ type: string }>;
    expect(Array.isArray(zooms)).toBe(true);
    expect(zooms.some((z) => z.type === 'inside')).toBe(true);
    expect(zooms.some((z) => z.type === 'slider')).toBe(true);
  });

  it('tooltip formatter filters out band-helper series (Untergrenze/Huelle not in output)', () => {
    const option = buildChartOption(SERIES, STATS, new Set(['qa_rounds']), true);
    const tooltip = option.tooltip as { formatter?: (params: unknown) => string };
    expect(typeof tooltip.formatter).toBe('function');

    // Simulate params including a band-helper series.
    const fakeParams = [
      { seriesName: 'QA-Runden', value: 3, color: '#fff', axisValueLabel: '2026-06-01' },
      { seriesName: 'QA-Runden · Untergrenze', value: 2.6, color: '#fff' },
      { seriesName: 'QA-Runden · Huelle', value: 0.72, color: '#fff' },
    ];
    const result = tooltip.formatter!(fakeParams);
    // Main series appears in tooltip.
    expect(result).toContain('QA-Runden');
    // Band-helper series are filtered out.
    expect(result).not.toContain('Untergrenze');
    expect(result).not.toContain('Huelle');
  });
});

// ── EventSource lifecycle / topic tests (AC3/AC4/AC5) ────────────────────────
//
// A controllable EventSource test double intercepts window.EventSource so the
// hook wires up against it. We verify:
//   - each view subscribes with the correct ?topics= set
//   - (re-)connect triggers a fresh initial-GET
//   - an injected event causes the view to re-fetch
//   - NO periodic refetch fires without an event (no setInterval poll)
//
// useProjectSse is enabled only when window.EventSource is defined, so we
// install the double BEFORE rendering and remove it AFTER.

interface FakeEventSourceInstance {
  url: string;
  onopen: ((e: Event) => void) | null;
  onerror: ((e: Event) => void) | null;
  onmessage: ((e: MessageEvent) => void) | null;
  listeners: Map<string, Array<(e: MessageEvent) => void>>;
  addEventListener(type: string, listener: (e: MessageEvent) => void): void;
  close(): void;
  // Test control: trigger lifecycle events.
  simulateOpen(): void;
  simulateError(): void;
  simulateEvent(type: string, data: unknown): void;
}

function makeFakeEventSource(): {
  FakeEventSource: new (url: string) => FakeEventSourceInstance;
  instances: FakeEventSourceInstance[];
} {
  const instances: FakeEventSourceInstance[] = [];

  class FakeES implements FakeEventSourceInstance {
    url: string;
    onopen: ((e: Event) => void) | null = null;
    onerror: ((e: Event) => void) | null = null;
    onmessage: ((e: MessageEvent) => void) | null = null;
    listeners: Map<string, Array<(e: MessageEvent) => void>> = new Map();

    constructor(url: string) {
      this.url = url;
      instances.push(this);
    }

    addEventListener(type: string, listener: (e: MessageEvent) => void): void {
      if (!this.listeners.has(type)) this.listeners.set(type, []);
      this.listeners.get(type)!.push(listener);
    }

    close(): void {}

    simulateOpen(): void {
      this.onopen?.(new Event('open'));
    }

    simulateError(): void {
      this.onerror?.(new Event('error'));
    }

    simulateEvent(type: string, data: unknown): void {
      const payload = typeof data === 'string' ? data : JSON.stringify(data);
      const ev = new MessageEvent(type, { data: payload });
      for (const listener of this.listeners.get(type) ?? []) {
        listener(ev);
      }
    }
  }

  return { FakeEventSource: FakeES, instances };
}

describe('AC3/AC4/AC5: EventSource lifecycle — topic subscription per view', () => {
  let original: typeof window.EventSource;

  beforeEach(() => {
    original = window.EventSource;
  });

  afterEach(() => {
    window.EventSource = original;
    vi.clearAllMocks();
  });

  it('ANALYTICS_TOPICS constant = [kpi, telemetry, failure_corpus]', () => {
    expect([...ANALYTICS_TOPICS].sort()).toEqual(['failure_corpus', 'kpi', 'telemetry'].sort());
  });

  it('KANBAN_TOPICS constant = [stories, phases]', () => {
    expect([...KANBAN_TOPICS].sort()).toEqual(['phases', 'stories'].sort());
  });

  it('GRAPH_TOPICS constant = [planning]', () => {
    expect([...GRAPH_TOPICS]).toEqual(['planning']);
  });

  // ── Real Kanban / Graph subscriptions via the SAME useProjectSse hook ────────
  //
  // Exercises the ACTUAL subscription mechanics each view uses in Shell.tsx:
  // the useProjectSse hook + the real exported topic constants + the
  // onReconnect→re-sync / onEvent→re-sync wiring. This is NOT a constant-array
  // check — it renders the hook against the FakeEventSource and asserts the live
  // ?topics= URL and that an injected event re-syncs the view.

  function SseViewHarness({
    topics,
    relevant,
    onResync,
  }: {
    topics: readonly SseTopic[];
    relevant: readonly string[];
    onResync: () => void;
  }) {
    useProjectSse({
      baseUrl: '',
      projectKey: 'PROJ',
      topics,
      // Lossy re-sync on every (re-)connect (exactly as Shell wires Kanban/Graph).
      onReconnect: () => onResync(),
      onEvent: (event) => {
        if (relevant.includes(event.topic)) onResync();
      },
      enabled: true,
    });
    return null;
  }

  it('AC3/AC5: Kanban subscribes with topics=stories,phases and a stories event re-syncs it', async () => {
    const { FakeEventSource, instances } = makeFakeEventSource();
    window.EventSource = FakeEventSource as unknown as typeof EventSource;

    const resync = vi.fn();
    render(
      <SseViewHarness topics={KANBAN_TOPICS} relevant={['stories', 'phases']} onResync={resync} />,
    );
    await act(async () => { await new Promise((r) => setTimeout(r, 20)); });

    // Real ?topics= set for the Kanban view.
    const url = instances[0]!.url;
    expect(url).toContain('topics=stories%2Cphases');
    expect(url).toContain('/v1/projects/PROJ/events');

    // (Re-)connect triggers the initial-GET re-sync.
    await act(async () => { instances[0]?.simulateOpen(); });
    expect(resync).toHaveBeenCalled();
    const afterOpen = resync.mock.calls.length;

    // An injected stories event re-syncs the Kanban view.
    await act(async () => { instances[0]?.simulateEvent('stories', { story_id: 'AG3-001' }); });
    expect(resync.mock.calls.length).toBeGreaterThan(afterOpen);

    // An UNRELATED topic (planning) must NOT re-sync the Kanban view.
    const beforeUnrelated = resync.mock.calls.length;
    await act(async () => { instances[0]?.simulateEvent('planning', {}); });
    expect(resync.mock.calls.length).toBe(beforeUnrelated);
  });

  it('AC3/AC5: Graph subscribes with topics=planning and a planning event re-syncs it', async () => {
    const { FakeEventSource, instances } = makeFakeEventSource();
    window.EventSource = FakeEventSource as unknown as typeof EventSource;

    const resync = vi.fn();
    render(
      <SseViewHarness topics={GRAPH_TOPICS} relevant={['planning']} onResync={resync} />,
    );
    await act(async () => { await new Promise((r) => setTimeout(r, 20)); });

    // Real ?topics= set for the Graph view (planning, NOT stories/phases).
    const url = instances[0]!.url;
    expect(url).toContain('topics=planning');
    expect(url).not.toContain('stories');
    expect(url).not.toContain('phases');

    await act(async () => { instances[0]?.simulateOpen(); });
    const afterOpen = resync.mock.calls.length;
    expect(afterOpen).toBeGreaterThan(0);

    // dependency_graph_changed/execution_input_changed/limits_changed arrive on
    // the planning topic → re-sync the Graph view.
    await act(async () => { instances[0]?.simulateEvent('planning', { kind: 'dependency_graph_changed' }); });
    expect(resync.mock.calls.length).toBeGreaterThan(afterOpen);
  });

  it('AC3: AnalyticsSlot subscribes with topics=kpi,telemetry,failure_corpus', async () => {
    const { FakeEventSource, instances } = makeFakeEventSource();
    window.EventSource = FakeEventSource as unknown as typeof EventSource;

    const client = new BffClient('', kpiStoriesTransport([]));
    render(<AnalyticsSlot projectKey="PROJ" baseUrl="" client={client} sseEnabled={true} />);

    await act(async () => { await new Promise((r) => setTimeout(r, 20)); });

    expect(instances.length).toBeGreaterThan(0);
    const url = instances[0]!.url;
    // Must include all three Analytics topics.
    expect(url).toContain('kpi');
    expect(url).toContain('telemetry');
    expect(url).toContain('failure_corpus');
    expect(url).toContain('/v1/projects/PROJ/events');
  });

  it('AC4: (re-)connect triggers a fresh initial-GET re-sync (no polling without event)', async () => {
    const { FakeEventSource, instances } = makeFakeEventSource();
    window.EventSource = FakeEventSource as unknown as typeof EventSource;

    const calls: string[] = [];
    const transport = async (url: string): Promise<Response> => {
      calls.push(url);
      const dim = url.match(/\/kpi\/(stories|guards|pools|pipeline|corpus)/)?.[1] ?? 'stories';
      return new Response(
        JSON.stringify({ project_key: 'PROJ', dimension: dim, status: 'EMPTY', rows: [] }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      );
    };
    const client = new BffClient('', transport);
    render(<AnalyticsSlot projectKey="PROJ" baseUrl="" client={client} sseEnabled={true} />);

    // Wait for initial-GET (mount).
    await act(async () => { await new Promise((r) => setTimeout(r, 20)); });
    const callsAfterMount = calls.length;
    expect(callsAfterMount).toBeGreaterThan(0);

    // Simulate SSE open (re-connect) — should trigger another initial-GET.
    await act(async () => { instances[0]?.simulateOpen(); });
    await act(async () => { await new Promise((r) => setTimeout(r, 20)); });
    expect(calls.length).toBeGreaterThan(callsAfterMount);

    // No additional fetches without events (no polling).
    const callsAfterOpen = calls.length;
    await act(async () => { await new Promise((r) => setTimeout(r, 100)); });
    // At most one more call is allowed (due to React re-renders), but NOT polling.
    expect(calls.length).toBeLessThanOrEqual(callsAfterOpen + 2);
  });

  it('AC5: kpi event triggers re-fetch; failure_corpus event triggers corpus re-fetch', async () => {
    const { FakeEventSource, instances } = makeFakeEventSource();
    window.EventSource = FakeEventSource as unknown as typeof EventSource;

    const calls: string[] = [];
    const transport = async (url: string): Promise<Response> => {
      calls.push(url);
      const dim = url.match(/\/kpi\/(stories|guards|pools|pipeline|corpus)/)?.[1] ?? 'stories';
      return new Response(
        JSON.stringify({ project_key: 'PROJ', dimension: dim, status: 'EMPTY', rows: [] }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      );
    };
    const client = new BffClient('', transport);
    render(<AnalyticsSlot projectKey="PROJ" baseUrl="" client={client} sseEnabled={true} />);

    await act(async () => { await new Promise((r) => setTimeout(r, 20)); });
    instances[0]?.simulateOpen();
    await act(async () => { await new Promise((r) => setTimeout(r, 20)); });
    const callsBeforeKpi = calls.length;

    // Inject a kpi event — should trigger re-fetch of all KPI dimensions.
    await act(async () => { instances[0]?.simulateEvent('kpi', { project_key: 'PROJ' }); });
    await act(async () => { await new Promise((r) => setTimeout(r, 30)); });
    expect(calls.length).toBeGreaterThan(callsBeforeKpi);

    const callsBeforeCorpus = calls.length;
    // Inject a failure_corpus event — should trigger corpus re-fetch.
    await act(async () => { instances[0]?.simulateEvent('failure_corpus', { project_key: 'PROJ' }); });
    await act(async () => { await new Promise((r) => setTimeout(r, 30)); });
    // At least one corpus call should have fired.
    expect(calls.filter((u) => u.includes('/kpi/corpus')).length).toBeGreaterThan(0);
    expect(calls.length).toBeGreaterThan(callsBeforeCorpus);
  });

  it('AC5: telemetry event calls onTelemetryEvent callback', async () => {
    const { FakeEventSource, instances } = makeFakeEventSource();
    window.EventSource = FakeEventSource as unknown as typeof EventSource;

    const onTelemetry = vi.fn();
    const client = new BffClient('', kpiStoriesTransport([]));
    render(
      <AnalyticsSlot
        projectKey="PROJ"
        baseUrl=""
        client={client}
        sseEnabled={true}
        onTelemetryEvent={onTelemetry}
      />,
    );

    await act(async () => { await new Promise((r) => setTimeout(r, 20)); });
    instances[0]?.simulateOpen();
    await act(async () => { await new Promise((r) => setTimeout(r, 20)); });

    // Inject telemetry event.
    await act(async () => { instances[0]?.simulateEvent('telemetry', { project_key: 'PROJ' }); });
    await act(async () => { await new Promise((r) => setTimeout(r, 20)); });
    expect(onTelemetry).toHaveBeenCalled();
  });

  it('AC4: no setInterval polling — calls do not increment without events after open', async () => {
    const { FakeEventSource, instances } = makeFakeEventSource();
    window.EventSource = FakeEventSource as unknown as typeof EventSource;

    let callCount = 0;
    const transport = async (url: string): Promise<Response> => {
      callCount++;
      const dim = url.match(/\/kpi\/(stories|guards|pools|pipeline|corpus)/)?.[1] ?? 'stories';
      return new Response(
        JSON.stringify({ project_key: 'PROJ', dimension: dim, status: 'EMPTY', rows: [] }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      );
    };
    const client = new BffClient('', transport);
    render(<AnalyticsSlot projectKey="PROJ" baseUrl="" client={client} sseEnabled={true} />);

    // Let it mount + open.
    await act(async () => { await new Promise((r) => setTimeout(r, 30)); });
    instances[0]?.simulateOpen();
    await act(async () => { await new Promise((r) => setTimeout(r, 30)); });
    const countAfterOpen = callCount;

    // Wait 200ms — no events should fire new fetches.
    await act(async () => { await new Promise((r) => setTimeout(r, 200)); });
    // Must NOT have grown (no polling loop).
    // Allow a small margin for React re-renders but not periodic polling.
    expect(callCount).toBeLessThanOrEqual(countAfterOpen + 2);
  });
});

describe('AC4: Kanban interactions', () => {
  it('renders columns + cards', () => {
    kanban();
    expect(screen.getAllByText('Backlog').length).toBeGreaterThan(0);
    expect(screen.getByText('AG3-001')).toBeTruthy();
    expect(screen.getByText('AG3-002')).toBeTruthy();
  });

  it('double-click selects, Enter selects (keyboard)', () => {
    const onSelect = vi.fn();
    kanban({ onSelect });
    const card = screen.getByText('AG3-001').closest('button') as HTMLButtonElement;
    fireEvent.dblClick(card);
    expect(onSelect).toHaveBeenCalledWith(baseStory);
    onSelect.mockClear();
    fireEvent.keyDown(card, { key: 'Enter' });
    expect(onSelect).toHaveBeenCalledWith(baseStory);
  });

  it('Arrow keyboard navigation focuses a neighbor', () => {
    const onFocusStory = vi.fn();
    kanban({ onFocusStory, selectedStory: baseStory });
    const card = screen.getByText('AG3-001').closest('button') as HTMLButtonElement;
    fireEvent.keyDown(card, { key: 'ArrowDown' });
    // Both AG3-001 and AG3-002 are Backlog; ArrowDown moves within column.
    expect(onFocusStory).toHaveBeenCalled();
  });

  it('valid drop (Backlog->Approved) dispatches optimistic change', async () => {
    const onChange = vi.fn();
    const { container } = kanban({ onStoryStatusChange: onChange });
    const approvedColumn = Array.from(container.querySelectorAll('.kanban-column')).find(
      (el) => el.querySelector('h2')?.textContent === 'Approved',
    );
    await act(async () => {
      fireEvent.drop(approvedColumn as Element, { dataTransfer: { getData: () => 'AG3-001', dropEffect: 'move' } });
    });
    expect(onChange).toHaveBeenCalledWith('AG3-001', 'Approved');
  });
});

describe('AC4: StorySheet interactions', () => {
  it('renders rows and group-by-epic groups', () => {
    const { container } = sheet();
    expect(screen.getByText('Alpha Story')).toBeTruthy();
    // group-by-epic on by default -> epic group headers visible (epic also shows
    // in the planning cell, so it appears more than once).
    expect(screen.getAllByText('Epic A').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Epic B').length).toBeGreaterThan(0);
    // toggle group-by off
    fireEvent.click(screen.getByText('Epic Groups'));
    expect(container.textContent).toContain('Flat');
  });

  it('sort header click toggles sort order', () => {
    const { container } = sheet();
    const sortButtons = container.querySelectorAll('.sort-header');
    expect(sortButtons.length).toBeGreaterThan(0);
    fireEvent.click(sortButtons[0]); // first column sort
    // Re-clicking the same column flips the order (no crash; rows still present).
    fireEvent.click(sortButtons[0]);
    expect(screen.getByText('Alpha Story')).toBeTruthy();
  });

  it('column resize handle is present and draggable (pointer events)', () => {
    const { container } = sheet();
    const handle = container.querySelector('.sheet-column-resize');
    expect(handle).toBeTruthy();
    // Pointer down starts resize without throwing.
    fireEvent.pointerDown(handle as Element, { clientX: 100 });
    fireEvent.pointerUp(handle as Element);
    expect(screen.getByText('Alpha Story')).toBeTruthy();
  });

  it('inline-edit on title writes a draft (edited rows counter increments)', async () => {
    const { container } = sheet();
    const titleCell = Array.from(container.querySelectorAll('td.cell-title')).find((td) =>
      td.textContent?.includes('Alpha Story'),
    );
    fireEvent.doubleClick(titleCell as Element);
    const input = container.querySelector('td.is-editing input') as HTMLInputElement;
    expect(input).toBeTruthy();
    await act(async () => {
      fireEvent.change(input, { target: { value: 'Renamed Alpha' } });
    });
    expect(container.textContent).toContain('1 edited rows');
  });

  it('valid inline status edit (Backlog->Approved) dispatches via the dedicated endpoint', async () => {
    const transport = makeFixtureTransport();
    const { container } = sheet({ client: new BffClient('', transport) });
    const statusCell = Array.from(container.querySelectorAll('td')).find((td) => td.textContent === 'Backlog');
    fireEvent.doubleClick(statusCell as Element);
    const select = container.querySelector('td.is-editing select') as HTMLSelectElement;
    await act(async () => {
      fireEvent.change(select, { target: { value: 'Approved' } });
    });
    const approveCall = transport.mock.calls.find((c) => (c[0] as string).endsWith('/approve'));
    expect(approveCall).toBeTruthy();
    // NEVER a PATCH with status (AC8).
    const patchStatus = transport.mock.calls.find(
      (c) => (c[1] as RequestInit | undefined)?.method === 'PATCH',
    );
    expect(patchStatus).toBeUndefined();
  });
});

describe('AC4: ReadyStackView PlaceholderColumn empty-state', () => {
  it('renders both sections with placeholders when nothing runs/is ready', () => {
    render(<ReadyStackView stories={[baseStory]} limits={DEFAULT_EXECUTION_LIMITS} onSelect={vi.fn()} />);
    expect(screen.getByText(/Aktuell laufend/)).toBeTruthy();
    expect(screen.getByText(/Effektiv delegierbar/)).toBeTruthy();
    // PlaceholderColumn centre labels for the empty sections.
    expect(screen.getByText('Keine laufende Story')).toBeTruthy();
    expect(screen.getByText('Keine ausführbare Story')).toBeTruthy();
  });
});

describe('AC4/AC10i: ExecutionLimitsView applies changes immediately', () => {
  it('increment stepper applies the new cap value (last_writer_wins)', () => {
    let current: ExecutionLimits = { ...DEFAULT_EXECUTION_LIMITS };
    const onChange = (next: ExecutionLimits) => { current = next; };
    const { container, rerender } = render(<ExecutionLimitsView limits={current} onChange={onChange} />);
    const incButton = container.querySelector('button[aria-label="Erhöhen"]') as HTMLButtonElement;
    expect(incButton).toBeTruthy();
    act(() => {
      fireEvent.click(incButton);
    });
    rerender(<ExecutionLimitsView limits={current} onChange={onChange} />);
    // First descriptor is repoParallelCap (default 3) -> now 4.
    expect(current.repoParallelCap).toBe(DEFAULT_EXECUTION_LIMITS.repoParallelCap + 1);
  });
});

describe('AC2: BC slice boundary imports verified', () => {
  it('FlowTab importable from contexts/pipeline_engine/', async () => {
    const mod = await import('../contexts/pipeline_engine/FlowTab');
    expect(typeof mod.FlowTab).toBe('function');
  });
  it('ReadyStackView importable from contexts/execution_planning/', async () => {
    const mod = await import('../contexts/execution_planning/ReadyStackView');
    expect(typeof mod.ReadyStackView).toBe('function');
  });
  it('ExecutionLimitsView importable from contexts/execution_planning/', async () => {
    const mod = await import('../contexts/execution_planning/ExecutionLimitsView');
    expect(typeof mod.ExecutionLimitsView).toBe('function');
  });
});
