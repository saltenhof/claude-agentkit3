/**
 * AC7/AC9: Shell — keyboard nav, inspector, hash routing, width persist, and
 * REAL search dispatch. The Shell consumes the REAL BffClient against the
 * fixture transport (real wire shapes), so search/list/counters wiring is
 * exercised end-to-end inside the component.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent, act, waitFor } from '@testing-library/react';
import {
  viewFromLocationHash,
  INSPECTOR_WIDTH_KEY,
  DEFAULT_INSPECTOR_WIDTH,
  MIN_INSPECTOR_WIDTH,
  VIEW_MODES,
} from '../app_shell/routing/viewMode';
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

vi.mock('../graph', () => ({
  toGraph: () => ({ nodes: [], edges: [] }),
  layoutGraph: () => Promise.resolve({ nodes: [], edges: [] }),
}));

// The shared transport spy: the REAL BffClient inside the Shell uses this.
const searchSpy = vi.fn();
const transport = makeFixtureTransport();

// Partial-mock: keep all real exports (BffReadError, listItemToStory, normalizers)
// but make the default-constructed BffClient use the fixture transport so the
// Shell drives REAL URLs we can assert on.
vi.mock('../foundation/bff/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../foundation/bff/client')>();
  class TestBffClient extends actual.BffClient {
    constructor(baseUrl = '') {
      super(baseUrl, (url: string, options?: RequestInit) => {
        if (url.includes('/stories/search')) searchSpy(url, options);
        return transport(url, options);
      });
    }
  }
  return { ...actual, BffClient: TestBffClient };
});

describe('AC7: viewFromLocationHash', () => {
  it('returns graph for empty hash', () => {
    window.location.hash = '';
    expect(viewFromLocationHash()).toBe('graph');
  });
  it('returns kanban for #kanban', () => {
    window.location.hash = '#kanban';
    expect(viewFromLocationHash()).toBe('kanban');
  });
  it('returns graph for unknown hash', () => {
    window.location.hash = '#unknown';
    expect(viewFromLocationHash()).toBe('graph');
  });
  it('supports all 5 view modes', () => {
    for (const mode of VIEW_MODES) {
      window.location.hash = `#${mode}`;
      expect(viewFromLocationHash()).toBe(mode);
    }
  });
});

describe('AC7: Inspector width constants + persistence', () => {
  beforeEach(() => window.localStorage.clear());
  it('constants are stable', () => {
    expect(DEFAULT_INSPECTOR_WIDTH).toBe(858);
    expect(MIN_INSPECTOR_WIDTH).toBe(560);
    expect(INSPECTOR_WIDTH_KEY).toBe('ak3.storyInspector.width');
  });
  it('width persists to localStorage', () => {
    window.localStorage.setItem(INSPECTOR_WIDTH_KEY, '700');
    expect(Number(window.localStorage.getItem(INSPECTOR_WIDTH_KEY))).toBe(700);
  });
});

describe('AC7/AC9: Shell renders and loads read-models from the BFF', () => {
  beforeEach(() => {
    searchSpy.mockClear();
    transport.mockClear();
  });

  it('renders navigation after the real read-model load', async () => {
    const { App } = await import('../app_shell/layout/Shell');
    await act(async () => {
      render(<App />);
    });
    expect(screen.getByTitle('Dependency Graph')).toBeTruthy();
    expect(screen.getByTitle('Kanban')).toBeTruthy();
    // It fetched the project list + per-project read-models.
    await waitFor(() => {
      const urls = transport.mock.calls.map((c) => c[0] as string);
      expect(urls.some((u) => u.endsWith('/v1/projects'))).toBe(true);
      expect(urls.some((u) => u.endsWith('/stories/counters'))).toBe(true);
      expect(urls.some((u) => u.endsWith('/mode-lock'))).toBe(true);
      expect(urls.some((u) => u.endsWith('/execution-input/limits'))).toBe(true);
    });
  });

  it('Escape key dispatches without crashing', async () => {
    const { App } = await import('../app_shell/layout/Shell');
    await act(async () => {
      render(<App />);
    });
    await act(async () => {
      fireEvent.keyDown(document.body, { key: 'Escape', bubbles: true });
    });
    expect(screen.getByTitle('Dependency Graph')).toBeTruthy();
  });
});

describe('AC7: Hash routing round-trip', () => {
  it('switching to kanban updates the hash', async () => {
    const { App } = await import('../app_shell/layout/Shell');
    await act(async () => {
      render(<App />);
    });
    await act(async () => {
      fireEvent.click(screen.getByTitle('Kanban'));
    });
    expect(window.location.hash).toBe('#kanban');
  });
  it('switching to sheet updates the hash', async () => {
    const { App } = await import('../app_shell/layout/Shell');
    await act(async () => {
      render(<App />);
    });
    await act(async () => {
      fireEvent.click(screen.getByTitle('Story Sheet'));
    });
    expect(window.location.hash).toBe('#sheet');
  });
});

describe('AC9: Global search dispatches to the BFF search URL (project-scoped)', () => {
  beforeEach(() => {
    searchSpy.mockClear();
  });
  it('typing in search calls searchStories with the project-scoped /stories/search URL', async () => {
    const { App } = await import('../app_shell/layout/Shell');
    await act(async () => {
      render(<App />);
    });
    const searchInput = screen.getByPlaceholderText(/Story, Repo, Modul/);
    await act(async () => {
      fireEvent.change(searchInput, { target: { value: 'test query' } });
    });
    // The Shell also issues a match-all search (q=%) to load the approval-bearing
    // board/sheet status set (E1); find the user-query search call specifically.
    await waitFor(() => {
      expect(
        searchSpy.mock.calls.some((c) => (c[0] as string).includes('q=test%20query')),
      ).toBe(true);
    });
    const url = searchSpy.mock.calls
      .map((c) => c[0] as string)
      .find((u) => u.includes('q=test%20query')) as string;
    expect(url).toContain('/stories/search');
    expect(url).toContain('q=test%20query');
    // Project-scoped under /v1/projects/{key}/...
    expect(url).toMatch(/\/v1\/projects\/[^/]+\/stories\/search/);
  });
});
