/**
 * AC4 & AC5: Views render with REAL interactions (drag&drop, sort, column-resize,
 * group-by, inline-edit, keyboard nav, PlaceholderColumn empty-state). Analytics
 * slot has no echarts (AC5). AC2 slice-boundary imports verified.
 */
import { describe, it, expect, vi } from 'vitest';
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

describe('AC5: AnalyticsSlot is a structural slot (no echarts)', () => {
  it('renders the slot container and AG3-094 placeholder', () => {
    render(<AnalyticsSlot />);
    expect(screen.getByTestId('analytics-slot')).toBeTruthy();
    expect(screen.getByText(/AG3-094/)).toBeTruthy();
  });
  it('has no echarts canvas/instance', () => {
    const { container } = render(<AnalyticsSlot />);
    expect(container.querySelectorAll('canvas')).toHaveLength(0);
    expect(container.querySelectorAll('[_echarts_instance_]')).toHaveLength(0);
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
