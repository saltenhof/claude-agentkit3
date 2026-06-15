/**
 * AC10d/10e/10h — REAL Shell-rendered edge-case tests (E5).
 *
 * These render the actual App shell (app_shell/layout/Shell) with a controlled
 * transport and assert USER-VISIBLE behavior after real UI events, NOT a
 * BffClient-only 404 assert or a mini harness that re-implements Shell logic.
 *
 * The Shell constructs `new BffClient('')` at module scope; a partial mock keeps
 * every real export (normalization, BffReadError, listItemToStory) but routes the
 * default-constructed client through a per-test transport we can drive.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent, act, waitFor } from '@testing-library/react';
import { jsonResponse } from './testTransport';
import {
  REAL_SEARCH_RESPONSE,
  REAL_PROJECTS_RESPONSE,
  REAL_COUNTERS_RESPONSE,
  REAL_MODE_LOCK_RESPONSE,
  REAL_LIMITS_RESPONSE,
  REAL_FLOW_RESPONSE,
  REAL_COVERAGE_ACCEPTANCE_RESPONSE,
  REAL_ARE_EVIDENCE_RESPONSE,
} from './realShapes.fixture';

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

vi.mock('../graph', () => ({
  toGraph: () => ({ nodes: [], edges: [] }),
  layoutGraph: () => Promise.resolve({ nodes: [], edges: [] }),
}));

// The transport the Shell's default BffClient routes through. Tests assign it.
type Transport = (url: string, options?: RequestInit) => Promise<Response>;
let activeTransport: Transport;

vi.mock('../foundation/bff/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../foundation/bff/client')>();
  class TestBffClient extends actual.BffClient {
    constructor(baseUrl = '') {
      super(baseUrl, (url: string, options?: RequestInit) => activeTransport(url, options));
    }
  }
  return { ...actual, BffClient: TestBffClient };
});

/** Build a multi-project search response so project-scoping is observable. */
function searchResponseFor(projectKey: string, storyId: string, title: string) {
  return {
    project_key: projectKey,
    stories: [
      {
        ...REAL_SEARCH_RESPONSE.stories[0],
        project_key: projectKey,
        story_id: storyId,
        title,
        status: 'Backlog',
      },
    ],
  };
}

/** Shared read-model routing used by every test (search-backed board/sheet). */
function baseRoute(url: string): Response | null {
  if (url.endsWith('/v1/projects')) return jsonResponse(200, REAL_PROJECTS_RESPONSE);
  if (url.endsWith('/mode-lock')) return jsonResponse(200, REAL_MODE_LOCK_RESPONSE);
  if (url.endsWith('/stories/counters')) return jsonResponse(200, REAL_COUNTERS_RESPONSE);
  if (url.endsWith('/execution-input/limits')) return jsonResponse(200, REAL_LIMITS_RESPONSE);
  if (url.endsWith('/flow')) return jsonResponse(200, REAL_FLOW_RESPONSE);
  if (url.endsWith('/acceptance')) return jsonResponse(200, REAL_COVERAGE_ACCEPTANCE_RESPONSE);
  if (url.endsWith('/are-evidence')) return jsonResponse(200, REAL_ARE_EVIDENCE_RESPONSE);
  return null;
}

beforeEach(() => {
  window.location.hash = '';
  window.localStorage.clear();
});

// ── AC10d: stale-selected-story (404 on detail) -> inspector closes + pill ────

describe('AC10d (real Shell): stale story 404 closes inspector + shows removal pill', () => {
  it('selecting a story whose detail GET 404s closes the inspector and shows the pill', async () => {
    const projectKey = REAL_PROJECTS_RESPONSE.projects[0].project_key;
    activeTransport = vi.fn(async (url: string) => {
      const base = baseRoute(url);
      if (base) return base;
      // Search (board/sheet) returns one selectable story.
      if (url.includes('/stories/search')) {
        return jsonResponse(200, searchResponseFor(projectKey, 'STALE-1', 'Stale Story'));
      }
      // The detail GET for the selected story 404s (story_deleted).
      if (/\/v1\/projects\/[^/]+\/stories\/[^/]+$/.test(url)) {
        return jsonResponse(404, { error_code: 'story_not_found' });
      }
      return jsonResponse(404, { error_code: 'not_found' });
    });

    const { App } = await import('../app_shell/layout/Shell');
    await act(async () => {
      render(<App />);
    });
    // Go to the Kanban view and select the story.
    await act(async () => {
      fireEvent.click(screen.getByTitle('Kanban'));
    });
    const card = await screen.findByText('STALE-1');
    await act(async () => {
      fireEvent.dblClick(card.closest('button') as HTMLButtonElement);
    });

    // Inspector opens, then closes when the detail 404s.
    await waitFor(() => {
      expect(screen.getByText('Story wurde entfernt.')).toBeTruthy();
    });
    await waitFor(() => {
      expect(document.querySelector('[data-story-inspector="true"]')).toBeNull();
    });
  });
});

// ── AC10e: last-request-wins in the REAL Shell inspector ──────────────────────

describe('AC10e (real Shell): late stale detail does not overwrite the latest selection', () => {
  it('fast switch with out-of-order detail responses shows the latest story', async () => {
    const projectKey = REAL_PROJECTS_RESPONSE.projects[0].project_key;
    let resolveFirst: (() => void) | null = null;

    const detailFor = (id: string) => ({
      project_key: projectKey, story_id: id, title: `Detail ${id}`,
      story_type: 'implementation', story_size: 'M', lifecycle_status: 'defined',
      participating_repos: [], recent_events: [], spec: null, evidence: null,
    });

    activeTransport = vi.fn((url: string) => {
      const base = baseRoute(url);
      if (base) return Promise.resolve(base);
      if (url.includes('/stories/search')) {
        // Two selectable stories for the fast switch.
        return Promise.resolve(jsonResponse(200, {
          project_key: projectKey,
          stories: [
            { ...REAL_SEARCH_RESPONSE.stories[0], project_key: projectKey, story_id: 'LRW-001', title: 'First', status: 'Backlog' },
            { ...REAL_SEARCH_RESPONSE.stories[0], project_key: projectKey, story_id: 'LRW-002', title: 'Second', status: 'Backlog' },
          ],
        }));
      }
      const m = url.match(/\/stories\/([^/]+)$/);
      if (m) {
        const id = m[1];
        if (id === 'LRW-001') {
          // Delay the FIRST story's detail until we resolve it manually.
          return new Promise<Response>((resolve) => {
            resolveFirst = () => resolve(jsonResponse(200, detailFor('LRW-001')));
          });
        }
        return Promise.resolve(jsonResponse(200, detailFor(id)));
      }
      return Promise.resolve(jsonResponse(404, { error_code: 'not_found' }));
    });

    const { App } = await import('../app_shell/layout/Shell');
    await act(async () => {
      render(<App />);
    });
    await act(async () => {
      fireEvent.click(screen.getByTitle('Kanban'));
    });
    const firstCard = await screen.findByText('LRW-001');
    const secondCard = await screen.findByText('LRW-002');

    // Select story 1 (detail pending), then story 2 (resolves immediately).
    await act(async () => {
      fireEvent.dblClick(firstCard.closest('button') as HTMLButtonElement);
    });
    await act(async () => {
      fireEvent.dblClick(secondCard.closest('button') as HTMLButtonElement);
    });
    // Story 2's detail resolved -> spec tab shows the SECOND story's title.
    const inspector = document.querySelector('[data-story-inspector="true"]') as HTMLElement;
    await waitFor(() => {
      expect(inspector.querySelector('h2')?.textContent).toContain('LRW-002');
    });

    // Now resolve the STALE first request — it must NOT overwrite the selection.
    await act(async () => {
      resolveFirst?.();
    });
    await waitFor(() => {
      expect(inspector.querySelector('h2')?.textContent).toContain('LRW-002');
    });
    expect(inspector.querySelector('h2')?.textContent).not.toContain('LRW-001');
  });
});

// ── AC10h: project switch (warning + inspector close + view preserved) ────────

describe('AC10h (real Shell): project switch warns on drafts, closes inspector, keeps view', () => {
  it('switches project: draft-loss warning, inspector closes, view selection preserved', async () => {
    activeTransport = vi.fn(async (url: string) => {
      const base = baseRoute(url);
      if (base) return base;
      if (url.includes('/stories/search')) {
        const key = url.match(/\/v1\/projects\/([^/]+)\//)?.[1] ?? 'alpha';
        return jsonResponse(200, searchResponseFor(key, `${key.toUpperCase()}-1`, `${key} Story`));
      }
      if (/\/v1\/projects\/[^/]+\/stories\/[^/]+$/.test(url)) {
        return jsonResponse(200, {
          summary: { story_id: 'X', title: 'X' }, spec: null, evidence: null,
          telemetry: null, gates: [], phases: [], events: [],
        });
      }
      return jsonResponse(404, { error_code: 'not_found' });
    });

    const { App } = await import('../app_shell/layout/Shell');
    await act(async () => {
      render(<App />);
    });

    // Move to the Sheet view (view-selection that must survive the switch).
    await act(async () => {
      fireEvent.click(screen.getByTitle('Story Sheet'));
    });
    expect(window.location.hash).toBe('#sheet');

    // Create an unsaved sheet draft by inline-editing a title cell.
    const titleCell = await waitFor(() => {
      const cell = Array.from(document.querySelectorAll('td.cell-title')).find((td) =>
        td.textContent?.includes('Story'),
      );
      expect(cell).toBeTruthy();
      return cell as HTMLElement;
    });
    fireEvent.doubleClick(titleCell);
    const input = document.querySelector('td.is-editing input, td.is-editing textarea') as HTMLInputElement;
    await act(async () => {
      fireEvent.change(input, { target: { value: 'Renamed Draft' } });
    });

    // Open the project menu and switch to the archived project.
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /Alpha Project/ }));
    });
    const switchTarget = await screen.findByText('Archived One');
    await act(async () => {
      fireEvent.click(switchTarget.closest('button') as HTMLButtonElement);
    });

    // Draft-loss warning shown, inspector closed, and the Sheet view preserved.
    await waitFor(() => {
      expect(screen.getByText(/Sheet-Entwürfe gehen durch den Projektwechsel verloren/)).toBeTruthy();
    });
    expect(document.querySelector('[data-story-inspector="true"]')).toBeNull();
    expect(window.location.hash).toBe('#sheet');
  });
});
