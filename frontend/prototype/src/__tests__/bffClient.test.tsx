/**
 * AC9: BffClient — project-scoped URL tests for all read-model methods.
 */
import { describe, it, expect, vi } from 'vitest';
import { BffClient, BffReadError, listItemToStory } from '../foundation/bff/client';
import {
  REAL_SEARCH_RESPONSE,
  REAL_PUBLIC_LIST_RESPONSE,
  REAL_PUBLIC_DETAIL_RESPONSE,
  REAL_PROJECTS_RESPONSE,
} from './realShapes.fixture';

const makeTransport = (status: number, body: unknown = {}) =>
  vi.fn().mockImplementation(() => {
    const resp = {
      ok: status >= 200 && status < 300,
      status,
      json: () => Promise.resolve(body),
      text: () => Promise.resolve(JSON.stringify(body)),
      clone: () => resp,
    };
    return Promise.resolve(resp);
  });

const okTransport = (body: unknown) => makeTransport(200, body);

describe('BffClient: project-scoped read-model URLs', () => {
  it('listStories -> approval-bearing search path (match-all q=%)', async () => {
    // E1: board/sheet status comes from the APPROVAL-bearing search path, not
    // the runtime list endpoint. listStories issues a match-all search (q=%).
    const transport = okTransport({ stories: [] });
    const client = new BffClient('', transport);
    await client.listStories('P1');
    const url = (transport.mock.calls as [string][])[0][0] as string;
    expect(url).toBe('/v1/projects/P1/stories/search?q=%25');
  });

  it('listStoriesRuntime -> /v1/projects/{key}/stories (runtime lifecycle path)', async () => {
    const transport = okTransport({ stories: [] });
    const client = new BffClient('', transport);
    await client.listStoriesRuntime('P1');
    expect((transport.mock.calls as [string][])[0][0]).toBe('/v1/projects/P1/stories');
  });

  it('getStoryDetail -> /v1/projects/{key}/stories/{id}', async () => {
    const transport = okTransport({ summary: {}, spec: null, evidence: null, telemetry: null, gates: [], phases: [], events: [] });
    const client = new BffClient('', transport);
    await client.getStoryDetail('P1', 'S1');
    expect((transport.mock.calls as [string][])[0][0]).toBe('/v1/projects/P1/stories/S1');
  });

  it('searchStories -> /v1/projects/{key}/stories/search?q=', async () => {
    const transport = okTransport({ stories: [] });
    const client = new BffClient('', transport);
    await client.searchStories('P1', 'hello world');
    const url = (transport.mock.calls as [string][])[0][0] as string;
    expect(url).toContain('/v1/projects/P1/stories/search');
    expect(url).toContain('q=hello%20world');
  });

  it('getStoryCounters -> /v1/projects/{key}/stories/counters', async () => {
    const transport = okTransport({ story_counters: { project_key: 'P1', backlog: 0, approved: 0, in_progress: 0, done: 0, cancelled: 0, total: 0, approved_wave_ready: 0 } });
    const client = new BffClient('', transport);
    await client.getStoryCounters('P1');
    expect((transport.mock.calls as [string][])[0][0]).toBe('/v1/projects/P1/stories/counters');
  });

  it('getModeLock -> /v1/projects/{key}/mode-lock', async () => {
    const transport = okTransport({ mode_lock: { project_key: 'P1', locked: false, mode: 'normal', reason: null } });
    const client = new BffClient('', transport);
    await client.getModeLock('P1');
    expect((transport.mock.calls as [string][])[0][0]).toBe('/v1/projects/P1/mode-lock');
  });

  it('getStoryFlow -> /v1/projects/{key}/stories/{id}/flow', async () => {
    const transport = okTransport({ story_flow_snapshot: { story_id: 'S1', phases: [] } });
    const client = new BffClient('', transport);
    await client.getStoryFlow('P1', 'S1');
    expect((transport.mock.calls as [string][])[0][0]).toBe('/v1/projects/P1/stories/S1/flow');
  });

  it('getCoverageAcceptance -> /v1/projects/{key}/coverage/stories/{id}/acceptance', async () => {
    const transport = okTransport({ story_coverage_acceptance: {} });
    const client = new BffClient('', transport);
    await client.getCoverageAcceptance('P1', 'S1');
    expect((transport.mock.calls as [string][])[0][0]).toBe('/v1/projects/P1/coverage/stories/S1/acceptance');
  });

  it('getCoverageAreEvidence -> /v1/projects/{key}/coverage/stories/{id}/are-evidence', async () => {
    const transport = okTransport({ story_are_evidence: {} });
    const client = new BffClient('', transport);
    await client.getCoverageAreEvidence('P1', 'S1');
    expect((transport.mock.calls as [string][])[0][0]).toBe('/v1/projects/P1/coverage/stories/S1/are-evidence');
  });

  it('getExecutionLimits -> /v1/projects/{key}/execution-input/limits', async () => {
    const transport = okTransport({ execution_limits: { project_key: 'P1', max_parallel_stories: 3, max_parallel_phases: 2 } });
    const client = new BffClient('', transport);
    await client.getExecutionLimits('P1');
    expect((transport.mock.calls as [string][])[0][0]).toBe('/v1/projects/P1/execution-input/limits');
  });

  it('listProjects -> /v1/projects', async () => {
    const transport = okTransport({ projects: [] });
    const client = new BffClient('', transport);
    await client.listProjects();
    expect((transport.mock.calls as [string][])[0][0]).toBe('/v1/projects');
  });

  it('approveStory -> /v1/projects/{key}/stories/{id}/approve POST', async () => {
    const transport = okTransport({});
    const client = new BffClient('', transport);
    await client.approveStory('P1', 'S1', 'op-1');
    const [url, opts] = (transport.mock.calls as [string, RequestInit?][])[0];
    expect(url).toBe('/v1/projects/P1/stories/S1/approve');
    expect(opts?.method).toBe('POST');
    const body = JSON.parse(opts?.body as string) as Record<string, unknown>;
    expect(body['op_id']).toBe('op-1');
  });

  it('rejectStory -> /v1/projects/{key}/stories/{id}/reject POST', async () => {
    const transport = okTransport({});
    const client = new BffClient('', transport);
    await client.rejectStory('P1', 'S1', 'op-2');
    const [url, opts] = (transport.mock.calls as [string, RequestInit?][])[0];
    expect(url).toBe('/v1/projects/P1/stories/S1/reject');
    expect(opts?.method).toBe('POST');
  });

  it('cancelStory -> /v1/projects/{key}/stories/{id}/cancel POST', async () => {
    const transport = okTransport({});
    const client = new BffClient('', transport);
    await client.cancelStory('P1', 'S1', 'test reason', 'op-3');
    const [url, opts] = (transport.mock.calls as [string, RequestInit?][])[0];
    expect(url).toBe('/v1/projects/P1/stories/S1/cancel');
    expect(opts?.method).toBe('POST');
    const body = JSON.parse(opts?.body as string) as Record<string, unknown>;
    expect(body['reason']).toBe('test reason');
  });

  it('throws on non-OK response with status code in message', async () => {
    const transport = makeTransport(404, {});
    const client = new BffClient('', transport);
    await expect(client.getStoryDetail('P1', 'missing')).rejects.toThrow('404');
  });
});

describe('BffClient: injectable transport for test isolation', () => {
  it('uses provided transport instead of global fetch', async () => {
    const customTransport = makeTransport(200, REAL_SEARCH_RESPONSE);
    const client = new BffClient('http://custom-base', customTransport);
    const result = await client.listStories('K1');
    expect(result.stories[0].id).toBe('E2ETEST-001');
    expect(customTransport).toHaveBeenCalledOnce();
    expect((customTransport.mock.calls as [string][])[0][0]).toContain('http://custom-base');
  });
});

// E1: normalization is tested against REAL backend-shaped payloads (captured
// from the live ControlPlaneApplication), NOT hand-invented shapes.
describe('BffClient: response-shape normalization (E1, real wire payloads)', () => {
  it('search response: maps story_to_wire_summary (story_id/type/status/size/repos) to StoryListItem', async () => {
    const transport = makeTransport(200, REAL_SEARCH_RESPONSE);
    const client = new BffClient('', transport);
    const { stories } = await client.searchStories('e2etest', 'E2E');
    const item = stories[0];
    expect(item.id).toBe('E2ETEST-001'); // from story_id (NOT id)
    expect(item.status).toBe('Approved'); // from status (live approval status)
    expect(item.type).toBe('implementation'); // from type
    expect(item.size).toBe('M'); // from size
    expect(item.repo).toBe('https://github.com/e2e/test-repo'); // from repos[0]
    expect(item.changeImpact).toBe('Local'); // from change_impact
    expect(item.conceptQuality).toBe('Medium'); // from concept_quality
    expect(item.epic).toBe('E2E Epic');
    expect(item.module).toBe('test-module');
  });

  it('runtime list response: maps lifecycle_status to executionLifecycle, NOT status (E1 type-lie fix)', async () => {
    const transport = makeTransport(200, REAL_PUBLIC_LIST_RESPONSE);
    const client = new BffClient('', transport);
    const { stories } = await client.listStoriesRuntime('ctxtest');
    const item = stories[0];
    expect(item.id).toBe('CTX-001'); // from story_id
    expect(item.type).toBe('implementation'); // from story_type (NOT type)
    expect(item.size).toBe('M'); // from story_size (NOT size)
    // The runtime lifecycle is carried in executionLifecycle and NEVER cast into
    // the approval `status` union (two-StoryService split).
    expect(item.executionLifecycle).toBe('defined');
    expect(item.status).toBeUndefined();
  });

  it('search summary: approval status only, no runtime lifecycle (E1)', async () => {
    const transport = makeTransport(200, REAL_SEARCH_RESPONSE);
    const client = new BffClient('', transport);
    const { stories } = await client.searchStories('e2etest', 'E2E');
    const item = stories[0];
    expect(item.status).toBe('Approved'); // typed approval status
    expect(item.executionLifecycle).toBeUndefined();
  });

  it('public detail (flat StoryDetail): normalizes story_id/story_type/lifecycle_status', async () => {
    const transport = makeTransport(200, REAL_PUBLIC_DETAIL_RESPONSE);
    const client = new BffClient('', transport);
    const detail = await client.getStoryDetail('ctxtest', 'CTX-001');
    expect(detail.summary.id).toBe('CTX-001');
    expect(detail.summary.type).toBe('implementation');
    expect(detail.summary.status).toBe('defined');
    expect(detail.summary.repo).toBe('https://github.com/e2e/r'); // participating_repos[0]
  });

  it('projects: maps project_summary (project_key/display_name/status) to ProjectItem with status', async () => {
    const transport = makeTransport(200, REAL_PROJECTS_RESPONSE);
    const client = new BffClient('', transport);
    const { projects } = await client.listProjects();
    expect(projects[0]).toEqual({ key: 'alpha', name: 'Alpha Project', status: 'active' });
    expect(projects[1]).toEqual({ key: 'archived-one', name: 'Archived One', status: 'archived' });
  });

  it('listItemToStory carries the normalized fields into the local Story model', async () => {
    const transport = makeTransport(200, REAL_SEARCH_RESPONSE);
    const client = new BffClient('', transport);
    const { stories } = await client.searchStories('e2etest', 'E2E');
    const story = listItemToStory(stories[0]);
    expect(story.id).toBe('E2ETEST-001');
    expect(story.status).toBe('Approved');
    expect(story.changeImpact).toBe('Local');
  });

  it('failed read throws a typed BffReadError carrying the backend error_code', async () => {
    const transport = makeTransport(404, { error_code: 'story_not_found', error: 'Story not found' });
    const client = new BffClient('', transport);
    await expect(client.getStoryDetail('P1', 'missing')).rejects.toBeInstanceOf(BffReadError);
    try {
      await client.getStoryDetail('P1', 'missing');
    } catch (err) {
      expect(err).toBeInstanceOf(BffReadError);
      expect((err as BffReadError).errorCode).toBe('story_not_found');
      expect((err as BffReadError).status).toBe(404);
    }
  });
});
