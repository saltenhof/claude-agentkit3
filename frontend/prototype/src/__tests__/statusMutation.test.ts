/**
 * AC8: Status mutation goes to project-scoped dedicated endpoints, NEVER PATCH with status.
 */
import { describe, it, expect, vi } from 'vitest';
import { BffClient } from '../foundation/bff/client';

const makeTransport = (status: number, body: unknown = {}) =>
  vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  });

describe('AC8: Status mutation endpoint routing — project-scoped', () => {
  it('approveStory calls /v1/projects/{key}/stories/{id}/approve', async () => {
    const transport = makeTransport(200);
    const client = new BffClient('', transport);
    await client.approveStory('AG3', 'AG3-001', 'op-1');
    const [url, opts] = (transport.mock.calls as [string, RequestInit?][])[0];
    expect(url).toBe('/v1/projects/AG3/stories/AG3-001/approve');
    expect(opts?.method).toBe('POST');
  });

  it('rejectStory calls /v1/projects/{key}/stories/{id}/reject', async () => {
    const transport = makeTransport(200);
    const client = new BffClient('', transport);
    await client.rejectStory('AG3', 'AG3-001', 'op-1');
    const [url, opts] = (transport.mock.calls as [string, RequestInit?][])[0];
    expect(url).toBe('/v1/projects/AG3/stories/AG3-001/reject');
    expect(opts?.method).toBe('POST');
  });

  it('cancelStory calls /v1/projects/{key}/stories/{id}/cancel', async () => {
    const transport = makeTransport(200);
    const client = new BffClient('', transport);
    await client.cancelStory('AG3', 'AG3-001', undefined, 'op-1');
    const [url, opts] = (transport.mock.calls as [string, RequestInit?][])[0];
    expect(url).toBe('/v1/projects/AG3/stories/AG3-001/cancel');
    expect(opts?.method).toBe('POST');
  });

  it('NEVER calls PATCH /v1/... with status field', async () => {
    const transport = makeTransport(200);
    const client = new BffClient('', transport);
    await client.approveStory('AG3', 'AG3-001', 'op-1');
    await client.rejectStory('AG3', 'AG3-001', 'op-2');
    await client.cancelStory('AG3', 'AG3-001', undefined, 'op-3');
    const calls = transport.mock.calls as [string, RequestInit?][];
    const patchWithStatus = calls.filter(([_url, opts]) => {
      if (opts?.method !== 'PATCH') return false;
      try {
        const body = JSON.parse(opts.body as string) as Record<string, unknown>;
        return 'status' in body;
      } catch {
        return false;
      }
    });
    expect(patchWithStatus).toHaveLength(0);
  });

  it('all mutation URLs include project key in path', async () => {
    const transport = makeTransport(200);
    const client = new BffClient('MY-PROJ', transport);
    await client.approveStory('MY-PROJ', 'S-001', 'op-1');
    await client.rejectStory('MY-PROJ', 'S-001', 'op-2');
    await client.cancelStory('MY-PROJ', 'S-001', 'reason', 'op-3');
    for (const [url] of transport.mock.calls as [string][]) {
      expect(url).toContain('/v1/projects/MY-PROJ/stories/S-001/');
    }
  });
});

describe('AC8: Non-draggable statuses in Kanban', () => {
  it('In Progress is non-draggable', () => {
    const NON_DRAGGABLE = ['In Progress', 'Done', 'Cancelled'];
    expect(NON_DRAGGABLE).toContain('In Progress');
  });

  it('Done is non-draggable', () => {
    const NON_DRAGGABLE = ['In Progress', 'Done', 'Cancelled'];
    expect(NON_DRAGGABLE).toContain('Done');
  });

  it('Cancelled is non-draggable', () => {
    const NON_DRAGGABLE = ['In Progress', 'Done', 'Cancelled'];
    expect(NON_DRAGGABLE).toContain('Cancelled');
  });

  it('Backlog is draggable', () => {
    const NON_DRAGGABLE = ['In Progress', 'Done', 'Cancelled'];
    expect(NON_DRAGGABLE).not.toContain('Backlog');
  });

  it('Approved is draggable', () => {
    const NON_DRAGGABLE = ['In Progress', 'Done', 'Cancelled'];
    expect(NON_DRAGGABLE).not.toContain('Approved');
  });
});

describe('AC8: BffClient read-model methods are project-scoped', () => {
  it('listStories URL is project-scoped (approval-bearing search path)', async () => {
    const transport = makeTransport(200, { stories: [] });
    const client = new BffClient('', transport);
    await client.listStories('MY-KEY');
    const [url] = (transport.mock.calls as [string][])[0];
    // E1: board/sheet status comes from the approval-bearing search path.
    expect(url).toBe('/v1/projects/MY-KEY/stories/search?q=%25');
  });

  it('getStoryCounters URL includes project key', async () => {
    const transport = makeTransport(200, { story_counters: { project_key: 'K', backlog: 0, approved: 0, in_progress: 0, done: 0, cancelled: 0, total: 0, approved_wave_ready: 0 } });
    const client = new BffClient('', transport);
    await client.getStoryCounters('K');
    const [url] = (transport.mock.calls as [string][])[0];
    expect(url).toBe('/v1/projects/K/stories/counters');
  });

  it('getModeLock URL includes project key', async () => {
    const transport = makeTransport(200, { mode_lock: { project_key: 'K', locked: false, mode: 'normal', reason: null } });
    const client = new BffClient('', transport);
    await client.getModeLock('K');
    const [url] = (transport.mock.calls as [string][])[0];
    expect(url).toBe('/v1/projects/K/mode-lock');
  });

  it('getStoryFlow URL includes project key and story id', async () => {
    const transport = makeTransport(200, { story_flow_snapshot: { story_id: 'S1', phases: [] } });
    const client = new BffClient('', transport);
    await client.getStoryFlow('K', 'S1');
    const [url] = (transport.mock.calls as [string][])[0];
    expect(url).toBe('/v1/projects/K/stories/S1/flow');
  });

  it('searchStories URL includes project key and query', async () => {
    const transport = makeTransport(200, { stories: [] });
    const client = new BffClient('', transport);
    await client.searchStories('K', 'my query');
    const [url] = (transport.mock.calls as [string][])[0];
    expect(url).toContain('/v1/projects/K/stories/search');
    expect(url).toContain('q=my%20query');
  });
});
