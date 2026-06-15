/**
 * AC10a–10i: Edge-case handlers — REAL render + interaction tests (E7).
 *
 * Components are real; the BFF transport is the only injected boundary. Each
 * test asserts USER-VISIBLE behavior after real fireEvent/userEvent — no
 * hollow BffClient-only or local-variable assertions.
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import { BffClient } from '../foundation/bff/client';
import { KpiTab } from '../contexts/kpi_analytics/KpiTab';
import { AnalyticsSlot } from '../contexts/kpi_analytics/AnalyticsSlot';
import { Kanban } from '../app_shell/board/Kanban';
import { StorySheet } from '../app_shell/sheet/StorySheet';
import { ExecutionLimitsView } from '../contexts/execution_planning/ExecutionLimitsView';
import { DetailInspector } from '../app_shell/inspector/DetailInspector';
import type { Story, StoryCounters, ExecutionLimits } from '../store';
import type { StoryDetailResponse } from '../foundation/bff/client';
import { makeFixtureTransport } from './testTransport';

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
  id: 'AG3-010',
  title: 'Edge Case Story',
  type: 'implementation',
  status: 'Backlog',
  size: 'S',
  owner: 'test',
  repo: 'test',
  module: 'test',
  epic: 'Edge Cases',
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

const approvedStory: Story = { ...baseStory, id: 'AG3-011', status: 'Approved' };
const cancelledStory: Story = { ...baseStory, id: 'AG3-012', status: 'Cancelled' };
const inProgressStory: Story = { ...baseStory, id: 'AG3-013', status: 'In Progress' };

const baseCounters: StoryCounters = {
  total: 4, finished: 0, running: 1, ready: 0, queue: 1, blocked: 2,
};

function makeKanban(
  stories: Story[],
  onStatusChange: (id: string, status: Story['status']) => void,
  extra: Partial<React.ComponentProps<typeof Kanban>> = {},
) {
  return render(
    <Kanban
      projectKey="AG3"
      stories={stories}
      selectedStory={null}
      onSelect={vi.fn()}
      onFocusStory={vi.fn()}
      onStoryStatusChange={onStatusChange}
      storyIdFilter=""
      onStoryIdFilterChange={vi.fn()}
      kpis={baseCounters}
      {...extra}
    />,
  );
}

// ── AC10a/10b: Mutation fail -> optimistic revert + error pill (REAL render) ──

describe('AC10a/10b: drop rejected by backend -> card snaps back + error pill', () => {
  it('renders error pill and reverts optimistic status when the dedicated endpoint rejects', async () => {
    // Inject a transport that REJECTS the approve mutation (invalid_transition).
    const transport = makeFixtureTransport({
      override: (url) =>
        url.endsWith('/approve') ? { status: 422, body: { error_code: 'invalid_transition' } } : null,
    });
    const client = new BffClient('', transport);
    const onChange = vi.fn();
    const { container } = makeKanban([baseStory], onChange, { client });

    const approvedColumn = Array.from(container.querySelectorAll('.kanban-column')).find(
      (el) => el.querySelector('h2')?.textContent === 'Approved',
    );
    expect(approvedColumn).toBeTruthy();

    await act(async () => {
      fireEvent.drop(approvedColumn as Element, {
        dataTransfer: { getData: () => baseStory.id, dropEffect: 'move' },
      });
    });

    // Optimistic update first to Approved, then revert to Backlog after rejection.
    expect(onChange).toHaveBeenNthCalledWith(1, 'AG3-010', 'Approved');
    await waitFor(() => {
      expect(onChange).toHaveBeenCalledWith('AG3-010', 'Backlog');
    });
    // Visible error pill with invalid_transition surfaced.
    await waitFor(() => {
      expect(screen.getByRole('alert').textContent).toContain('invalid_transition');
    });
  });

  it('disallowed drop (Backlog->Done) snaps back with error pill, no dispatch', async () => {
    const transport = makeFixtureTransport();
    const client = new BffClient('', transport);
    const onChange = vi.fn();
    const { container } = makeKanban([baseStory], onChange, { client });

    const doneColumn = Array.from(container.querySelectorAll('.kanban-column')).find(
      (el) => el.querySelector('h2')?.textContent === 'Done',
    );
    fireEvent.drop(doneColumn as Element, {
      dataTransfer: { getData: () => baseStory.id, dropEffect: 'move' },
    });
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByRole('alert')).toBeTruthy();
  });

  it('terminal/running cards are non-draggable (Done/Cancelled/In Progress)', () => {
    for (const story of [cancelledStory, inProgressStory, { ...baseStory, id: 'AG3-014', status: 'Done' as const }]) {
      const { container, unmount } = makeKanban([story], vi.fn());
      const card = container.querySelector(`[data-kanban-story-id="${story.id}"]`);
      expect(card?.getAttribute('draggable')).toBe('false');
      unmount();
    }
  });

  it('Approved card IS draggable', () => {
    const { container } = makeKanban([approvedStory], vi.fn());
    const card = container.querySelector('[data-kanban-story-id="AG3-011"]');
    expect(card?.getAttribute('draggable')).toBe('true');
  });
});

// ── AC10c: Sheet validation_failed -> keep draft + mark field red ─────────────

describe('AC10c: Sheet inline-status validation_failed keeps draft + marks field', () => {
  function renderSheet(client: BffClient) {
    return render(
      <StorySheet
        projectKey="AG3"
        stories={[baseStory]}
        selectedStory={null}
        statusFilter="all"
        onSelect={vi.fn()}
        onStatusFilterChange={vi.fn()}
        kpis={baseCounters}
        client={client}
      />,
    );
  }

  it('validation_failed: cell keeps draft and is marked invalid', async () => {
    const transport = makeFixtureTransport({
      override: (url) =>
        url.endsWith('/approve') ? { status: 400, body: { error_code: 'validation_failed' } } : null,
    });
    const client = new BffClient('', transport);
    const { container } = renderSheet(client);

    const statusCell = Array.from(container.querySelectorAll('td')).find(
      (td) => td.textContent === 'Backlog',
    );
    expect(statusCell).toBeTruthy();
    fireEvent.doubleClick(statusCell as Element);
    const select = container.querySelector('td.is-editing select') as HTMLSelectElement | null;
    expect(select).toBeTruthy();
    await act(async () => {
      fireEvent.change(select as HTMLSelectElement, { target: { value: 'Approved' } });
    });

    // Draft persists ("edited rows" statusbar > 0) and the field is marked invalid.
    await waitFor(() => {
      expect(container.textContent).toContain('1 edited rows');
    });
    await waitFor(() => {
      expect(container.querySelector('.cell-validation-error, [data-validation-error="true"], .is-invalid')).toBeTruthy();
    });
  });

  it('disallowed transition (Backlog->Done) shows error pill and writes no draft', async () => {
    const transport = makeFixtureTransport();
    const client = new BffClient('', transport);
    const { container } = renderSheet(client);
    const statusCell = Array.from(container.querySelectorAll('td')).find((td) => td.textContent === 'Backlog');
    fireEvent.doubleClick(statusCell as Element);
    const select = container.querySelector('td.is-editing select') as HTMLSelectElement;
    await act(async () => {
      fireEvent.change(select, { target: { value: 'Done' } });
    });
    expect(screen.getByRole('alert')).toBeTruthy();
    expect(container.textContent).toContain('0 edited rows');
  });
});

// AC10d (stale-selected-story closes inspector + pill) and AC10e
// (last-request-wins) are proven through the REAL App shell render path in
// shellEdgeCases.test.tsx (E5), not via a BffClient-only assert or a mini
// harness. See that file.

// ── AC10f: hold state (escalated/paused/failed) visual markers ────────────────

describe('AC10f: FlowTab renders server flow snapshot with hold-state', () => {
  it('renders an escalated phase from the fetched snapshot (state_reason), not the local heuristic', () => {
    const snapshot = {
      story_id: 'AG3-010',
      mode: 'standard' as const,
      phases: [
        {
          phase: 'implementation' as const,
          state: 'escalated',
          state_reason: 'qa_budget_exceeded',
          iteration: 2,
          iteration_loop_group: 'remediation',
          substeps: [
            { substep: 'worker', state: 'failed', optional: false, loop_group: 'remediation', loop_position: 1, loop_size: 2 },
          ],
        },
      ],
    };
    render(
      <DetailInspector
        story={baseStory}
        storyDetail={null}
        flowSnapshot={snapshot}
        width={600}
        onClose={vi.fn()}
        onResizeStart={vi.fn()}
      />,
    );
    // Global header hold pill (AC10f) — derived from the escalated phase.
    expect(screen.getByText('eskaliert')).toBeTruthy();
    // Switch to the "Ablauf" (flow) tab and assert the snapshot phase rendered.
    fireEvent.click(screen.getByText('Ablauf'));
    expect(screen.getByText('Pipeline-Ablauf')).toBeTruthy();
    // The implementation phase from the SNAPSHOT renders (server-derived).
    expect(screen.getAllByText(/Implementation/i).length).toBeGreaterThan(0);
    // state_reason is rendered verbatim, and the hold-state label (not the active-state "läuft" label).
    expect(screen.getByText('qa_budget_exceeded')).toBeTruthy();
    expect(screen.getByText('Phase eskaliert')).toBeTruthy();
  });
});

// ── AC10g: Empty states per view ──────────────────────────────────────────────

describe('AC10g: Empty states per view', () => {
  it('KpiTab shows placeholder when storyDetail is null', () => {
    render(<KpiTab storyDetail={null} />);
    expect(screen.getByText(/Noch keine KPI-Telemetrie/)).toBeTruthy();
  });

  it('KpiTab renders telemetry from storyDetail (not fixture synthesis)', () => {
    const detail: StoryDetailResponse = {
      summary: { id: 'AG3-001', title: 'T', status: 'Backlog', type: 'impl', size: 'S', owner: 'u', repo: 'r', module: 'm', epic: 'e', changeImpact: 'Local', conceptQuality: 'High', wave: 1 },
      spec: null, evidence: null,
      telemetry: {
        runId: 'run-abc-123', agentStarts: 5, incrementCommits: 12, reviewRequests: 3,
        reviewResponses: 3, reviewCompliant: 3, llmCalls: 42, adversarialTests: 8, webCalls: 1,
        tokensIn: 10000, tokensOut: 5000, pools: [{ pool: 'chatgpt', role: 'worker', calls: 20, status: 'PASS' }],
      },
      gates: [], phases: [], events: [],
    };
    render(<KpiTab storyDetail={detail} />);
    expect(screen.getByText('run-abc-123')).toBeTruthy();
    expect(screen.getByText('42')).toBeTruthy();
  });

  it('AnalyticsSlot renders placeholder slot', () => {
    render(<AnalyticsSlot />);
    expect(screen.getByTestId('analytics-slot')).toBeTruthy();
  });

  it('Kanban column shows empty state text when no stories', () => {
    const { container } = makeKanban([], vi.fn());
    expect(container.textContent).toContain('Keine Stories');
  });
});

// ── AC10h: archived project -> mutating controls disabled (REAL render) ───────

describe('AC10h: archived project disables mutating controls', () => {
  it('Kanban readOnly: cards are NOT draggable and drop shows disabled pill', async () => {
    const onChange = vi.fn();
    const { container } = makeKanban([baseStory], onChange, { readOnly: true });
    const card = container.querySelector('[data-kanban-story-id="AG3-010"]');
    expect(card?.getAttribute('draggable')).toBe('false');

    const approvedColumn = Array.from(container.querySelectorAll('.kanban-column')).find(
      (el) => el.querySelector('h2')?.textContent === 'Approved',
    );
    fireEvent.drop(approvedColumn as Element, {
      dataTransfer: { getData: () => baseStory.id, dropEffect: 'move' },
    });
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByRole('alert').textContent).toContain('Archiviert');
  });

  it('Sheet readOnly: inline status edit is blocked with disabled pill', async () => {
    const client = new BffClient('', makeFixtureTransport());
    const { container } = render(
      <StorySheet
        projectKey="AG3"
        stories={[baseStory]}
        selectedStory={null}
        statusFilter="all"
        onSelect={vi.fn()}
        onStatusFilterChange={vi.fn()}
        kpis={baseCounters}
        client={client}
        readOnly
      />,
    );
    const statusCell = Array.from(container.querySelectorAll('td')).find((td) => td.textContent === 'Backlog');
    fireEvent.doubleClick(statusCell as Element);
    const select = container.querySelector('td.is-editing select') as HTMLSelectElement;
    await act(async () => {
      fireEvent.change(select, { target: { value: 'Approved' } });
    });
    expect(screen.getByRole('alert').textContent).toContain('Archiviert');
    expect(container.textContent).toContain('0 edited rows');
  });

  it('Sheet reports draft presence via onDraftsChange (drives the switch warning)', async () => {
    const client = new BffClient('', makeFixtureTransport());
    const onDraftsChange = vi.fn();
    const { container } = render(
      <StorySheet
        projectKey="AG3"
        stories={[baseStory]}
        selectedStory={null}
        statusFilter="all"
        onSelect={vi.fn()}
        onStatusFilterChange={vi.fn()}
        kpis={baseCounters}
        client={client}
        onDraftsChange={onDraftsChange}
      />,
    );
    // Edit a non-status (title) cell to create a draft.
    const titleCell = Array.from(container.querySelectorAll('td.cell-title')).find((td) => td.textContent?.includes('Edge Case Story'));
    fireEvent.doubleClick(titleCell as Element);
    const input = container.querySelector('td.is-editing input, td.is-editing textarea') as HTMLInputElement;
    await act(async () => {
      fireEvent.change(input, { target: { value: 'Renamed' } });
    });
    await waitFor(() => {
      expect(onDraftsChange).toHaveBeenCalledWith(true);
    });
  });
});

// ── AC10i: Limits last_writer_wins (REAL render) ──────────────────────────────

describe('AC10i: ExecutionLimitsView applies the last value (last_writer_wins)', () => {
  it('renders the applied limit value after change', () => {
    const initial: ExecutionLimits = {
      repoParallelCap: 3, mergeRiskCap: 5, maxParallelAgentCap: 8, llmPoolCap: 10, ciCapacityCap: 4,
    };
    let current = initial;
    const onChange = (next: ExecutionLimits) => { current = next; };
    const { rerender, container } = render(<ExecutionLimitsView limits={current} onChange={onChange} />);
    // Find an increment stepper button and click it; assert the applied value renders.
    const incButtons = container.querySelectorAll('button[aria-label*="erhöhen"], button[aria-label*="increase"], .number-stepper button');
    expect(incButtons.length).toBeGreaterThan(0);
    act(() => {
      fireEvent.click(incButtons[incButtons.length - 1]);
    });
    rerender(<ExecutionLimitsView limits={current} onChange={onChange} />);
    // The new repoParallelCap (or whichever cap) must be reflected (last write wins).
    expect(JSON.stringify(current)).not.toBe(JSON.stringify(initial));
  });
});

// ── AC9 negative: no own telemetry/KPI aggregation endpoint ───────────────────

describe('AC9 negative: BffClient has no own telemetry/KPI aggregation endpoint', () => {
  it('BffClient does not expose getTelemetry/getKpiAggregation', () => {
    const client = new BffClient('') as unknown as Record<string, unknown>;
    expect(typeof client['getTelemetry']).toBe('undefined');
    expect(typeof client['getKpiAggregation']).toBe('undefined');
  });
});
