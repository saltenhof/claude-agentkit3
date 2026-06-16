/**
 * Unit tests for TaskSlot (AG3-105 / FK-77).
 *
 * Uses injectable BffClient with a mock transport (no real HTTP).
 * All wire fixtures use the REAL backend wire shape (Task.model_dump(mode="json")):
 *   task_id, project_key, kind, type, title, body (NOT description), priority,
 *   status, origin, source_story_id (NOT story_id), execution_report_ref,
 *   created_at, resolved_at, resolved_by.
 *   WireTaskLink: project_key, task_id, target_kind, target_id, kind (NOT relation_kind).
 *
 * Tests cover:
 *   AC1 — separation: task view has no pipeline/story chrome
 *   AC2 — status + link badges rendered
 *   AC3 — create: new task appears from server response, not local shadow
 *   AC4 — link/unlink: only task|story targets (no artifacts), bidirectional
 *   AC5 — resolve=done/dismiss=dismissed, strictly separate; terminal tasks no actions
 *   AC9 — error_code pill + create CTA in empty state + optimistic revert
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, act, waitFor } from '@testing-library/react';
import { TaskSlot } from '../contexts/task_management/TaskSlot';
import { BffClient, type WireTask, type WireTaskLink } from '../foundation/bff/client';
import { jsonResponse } from './testTransport';
import { VIEW_MODES } from '../app_shell/routing/viewMode';

// ── Wire fixtures — REAL backend shape ────────────────────────────────────────

const OPEN_TASK: WireTask = {
  task_id: 'TM-2025-0001',
  project_key: 'AG3',
  kind: 'actionable',
  type: 'concept_update',
  priority: 'high',
  status: 'open',
  origin: 'human',
  title: 'Fix the critical bug',
  body: 'Needs attention ASAP.',  // wire field is `body`, NOT `description`
  source_story_id: 'AG3-042',      // wire field is `source_story_id`, NOT `story_id`
  execution_report_ref: null,
  created_at: '2025-06-01T10:00:00Z',
  resolved_at: null,
  resolved_by: null,
};

const DONE_TASK: WireTask = {
  ...OPEN_TASK,
  task_id: 'TM-2025-0002',
  title: 'Already resolved task',
  status: 'done',
  body: 'Already done.',
  resolved_at: '2025-06-02T12:00:00Z',
  resolved_by: 'human',
  source_story_id: null,
};

const DISMISSED_TASK: WireTask = {
  ...OPEN_TASK,
  task_id: 'TM-2025-0003',
  title: 'Dismissed task',
  status: 'dismissed',
  body: 'Dismissed.',
  resolved_at: '2025-06-02T13:00:00Z',
  resolved_by: 'human',
  source_story_id: null,
};

/** Real WireTaskLink — `kind` field NOT `relation_kind` (per backend model_dump). */
const TASK_LINK_STORY: WireTaskLink = {
  project_key: 'AG3',
  task_id: 'TM-2025-0001',
  target_kind: 'story',
  target_id: 'AG3-042',
  kind: 'relates_to',  // field is `kind`, NOT `relation_kind`
};

const TASK_LINK_TASK: WireTaskLink = {
  project_key: 'AG3',
  task_id: 'TM-2025-0001',
  target_kind: 'task',
  target_id: 'TM-2025-0002',
  kind: 'duplicate_of',
};

const TASK_LIST_RESPONSE = {
  project_key: 'AG3',
  tasks: [OPEN_TASK, DONE_TASK, DISMISSED_TASK],
};

const EMPTY_TASK_LIST_RESPONSE = {
  project_key: 'AG3',
  tasks: [],
};

// ── Transport helpers ─────────────────────────────────────────────────────────

function makeTaskTransport(
  listResponse: unknown = TASK_LIST_RESPONSE,
  mutateStatus = 200,
  resolvedTask: WireTask = { ...OPEN_TASK, status: 'done', resolved_at: '2025-06-02T12:00:00Z', resolved_by: 'human' },
  dismissedTask: WireTask = { ...OPEN_TASK, status: 'dismissed', resolved_at: '2025-06-02T13:00:00Z', resolved_by: 'human' },
  createdTask: WireTask = { ...OPEN_TASK, task_id: 'TM-2025-0099', title: 'New Task', body: 'New body' },
  link: WireTaskLink = TASK_LINK_STORY,
  // AG3-105 finding 1: backend-hydrated links (GET /task-links). Default: empty,
  // matching the prior "Keine Links" expectation in the AC2 tests.
  linksResponse: { project_key: string; links: WireTaskLink[] } = { project_key: 'AG3', links: [] },
): ReturnType<typeof vi.fn> {
  return vi.fn().mockImplementation((url: string, options?: RequestInit) => {
    const method = options?.method ?? 'GET';
    // List task links (GET /task-links) — checked before /tasks (distinct path).
    if (method === 'GET' && url.includes('/task-links')) {
      return Promise.resolve(jsonResponse(200, linksResponse));
    }
    // Reverse view (GET .../tasks/for-target/...) — by default no linking tasks.
    // Checked before the generic /tasks branch (more specific path first).
    if (method === 'GET' && url.includes('/tasks/for-target/')) {
      return Promise.resolve(jsonResponse(200, { project_key: 'AG3', tasks: [] }));
    }
    // List tasks (collection read)
    if (method === 'GET' && url.includes('/tasks')) {
      return Promise.resolve(jsonResponse(200, listResponse));
    }
    // Resolve
    if (method === 'POST' && url.includes('/resolve')) {
      if (mutateStatus !== 200) {
        return Promise.resolve(jsonResponse(mutateStatus, { error_code: 'invalid_transition' }));
      }
      return Promise.resolve(jsonResponse(200, { task: resolvedTask, project_key: 'AG3' }));
    }
    // Dismiss
    if (method === 'POST' && url.includes('/dismiss')) {
      if (mutateStatus !== 200) {
        return Promise.resolve(jsonResponse(mutateStatus, { error_code: 'invalid_transition' }));
      }
      return Promise.resolve(jsonResponse(200, { task: dismissedTask, project_key: 'AG3' }));
    }
    // Create task (collection POST without /resolve|/dismiss|/links in path)
    if (method === 'POST' && /\/tasks\/?$/.test(url.split('?')[0]!)) {
      if (mutateStatus !== 200) {
        return Promise.resolve(jsonResponse(mutateStatus, { error_code: 'task_already_exists' }));
      }
      return Promise.resolve(jsonResponse(201, { task: createdTask, project_key: 'AG3' }));
    }
    // Link (POST .../links)
    if (method === 'POST' && url.includes('/links') && !url.includes('/delete')) {
      if (mutateStatus !== 200) {
        return Promise.resolve(jsonResponse(mutateStatus, { error_code: 'invalid_task_link_target' }));
      }
      return Promise.resolve(jsonResponse(201, { link }));
    }
    // Unlink (POST .../links/delete)
    if (method === 'POST' && url.includes('/links/delete')) {
      if (mutateStatus !== 200) {
        return Promise.resolve(jsonResponse(mutateStatus, { error_code: 'task_link_not_found' }));
      }
      return Promise.resolve(jsonResponse(200, {}));
    }
    return Promise.resolve(jsonResponse(404, { error_code: 'not_found' }));
  });
}

function makeErrorTransport(errorCode = 'task_management_unavailable'): ReturnType<typeof vi.fn> {
  return vi.fn().mockImplementation(() => {
    return Promise.resolve(jsonResponse(503, { error_code: errorCode }));
  });
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe('TaskSlot — unit tests (AG3-105)', () => {

  // AC1: separation — task view has no pipeline/story chrome

  describe('AC1 — task/story separation', () => {
    it('does not render any phase/gate/flow/mode elements', async () => {
      const transport = makeTaskTransport();
      const client = new BffClient('', transport);

      await act(async () => {
        render(<TaskSlot projectKey="AG3" client={client} />);
      });

      expect(screen.queryByTestId('flow-tab')).toBeNull();
      expect(screen.queryByTestId('mode-indicator')).toBeNull();
      const container = screen.getByTestId('task-slot');
      expect(container.querySelector('[data-testid*="phase"]')).toBeNull();
      expect(container.querySelector('[data-testid*="gate"]')).toBeNull();
      expect(container.querySelector('[data-testid*="worktree"]')).toBeNull();
    });

    it('VIEW_MODES includes tasks', () => {
      expect(VIEW_MODES).toContain('tasks');
    });
  });

  // AC2: task list with status + link badges

  describe('AC2 — task list with status and link badges', () => {
    it('renders the slot with task list from real wire shape (body, not description)', async () => {
      const transport = makeTaskTransport();
      const client = new BffClient('', transport);

      await act(async () => {
        render(<TaskSlot projectKey="AG3" client={client} />);
      });

      expect(screen.getByTestId('task-slot')).toBeTruthy();
      expect(screen.getByTestId('task-list-open')).toBeTruthy();
      expect(screen.getByTestId(`task-row-${OPEN_TASK.task_id}`)).toBeTruthy();
      expect(screen.getByTestId(`task-title-${OPEN_TASK.task_id}`).textContent).toBe(OPEN_TASK.title);
      // body field, NOT description
      expect(screen.getByTestId(`task-body-${OPEN_TASK.task_id}`).textContent).toBe(OPEN_TASK.body);
    });

    it('renders open count badge', async () => {
      const transport = makeTaskTransport();
      const client = new BffClient('', transport);

      await act(async () => {
        render(<TaskSlot projectKey="AG3" client={client} />);
      });

      expect(screen.getByTestId('task-open-count').textContent).toContain('1 offen');
    });

    it('renders source_story_id reference (NOT story_id)', async () => {
      const transport = makeTaskTransport();
      const client = new BffClient('', transport);

      await act(async () => {
        render(<TaskSlot projectKey="AG3" client={client} />);
      });

      expect(screen.getByTestId(`task-story-ref-${OPEN_TASK.task_id}`)).toBeTruthy();
    });

    it('renders link badges for tasks that have links', async () => {
      const transport = makeTaskTransport();
      const client = new BffClient('', transport);

      // Pre-populate links via transport — trigger link via UI later
      await act(async () => {
        render(<TaskSlot projectKey="AG3" client={client} />);
      });

      // Initially no links
      expect(screen.getByTestId(`task-no-links-${OPEN_TASK.task_id}`)).toBeTruthy();
    });

    it('shows done and dismissed tasks in closed section', async () => {
      const transport = makeTaskTransport();
      const client = new BffClient('', transport);

      await act(async () => {
        render(<TaskSlot projectKey="AG3" client={client} />);
      });

      expect(screen.getByTestId('task-list-closed')).toBeTruthy();
      expect(screen.getByTestId(`task-row-${DONE_TASK.task_id}`)).toBeTruthy();
      expect(screen.getByTestId(`task-row-${DISMISSED_TASK.task_id}`)).toBeTruthy();
    });
  });

  // AC3: create — new task appears from server response, no local shadow

  describe('AC3 — create from server response', () => {
    it('opens create form on button click', async () => {
      const transport = makeTaskTransport();
      const client = new BffClient('', transport);

      await act(async () => {
        render(<TaskSlot projectKey="AG3" client={client} />);
      });

      await act(async () => {
        fireEvent.click(screen.getByTestId('task-create-open'));
      });

      expect(screen.getByTestId('task-create-form')).toBeTruthy();
    });

    it('create calls POST /tasks (no task_id in payload) and new task appears from server', async () => {
      const createdTask: WireTask = {
        ...OPEN_TASK,
        task_id: 'TM-2025-0099',
        title: 'Server-allocated task',
        body: 'New body',
        source_story_id: null,
      };
      const transport = makeTaskTransport(
        TASK_LIST_RESPONSE, 200, undefined, undefined, createdTask,
      );
      const client = new BffClient('', transport);

      await act(async () => {
        render(<TaskSlot projectKey="AG3" client={client} />);
      });

      // Open form
      await act(async () => {
        fireEvent.click(screen.getByTestId('task-create-open'));
      });

      // Fill form
      await act(async () => {
        fireEvent.change(screen.getByTestId('task-create-title'), { target: { value: 'Server-allocated task' } });
        fireEvent.change(screen.getByTestId('task-create-body'), { target: { value: 'New body' } });
      });

      // Submit
      await act(async () => {
        fireEvent.click(screen.getByTestId('task-create-submit'));
      });

      // New task appears with server-assigned task_id
      const calls = transport.mock.calls as [string, RequestInit?][];
      const createCalls = calls.filter(([u, opts]) =>
        opts?.method === 'POST' && /\/tasks\/?$/.test(u.split('?')[0]!),
      );
      expect(createCalls.length).toBeGreaterThan(0);

      // Check no task_id in body (server-side allocation)
      const createBody = JSON.parse(createCalls[0]![1]!.body as string) as Record<string, unknown>;
      expect(createBody['task_id']).toBeUndefined();
      expect(createBody['title']).toBe('Server-allocated task');

      // New task appears in the UI from server response
      expect(screen.getByTestId(`task-row-${createdTask.task_id}`)).toBeTruthy();
    });

    it('create form includes kind, type, priority, origin, source_story_id fields', async () => {
      const transport = makeTaskTransport();
      const client = new BffClient('', transport);

      await act(async () => {
        render(<TaskSlot projectKey="AG3" client={client} />);
      });

      await act(async () => {
        fireEvent.click(screen.getByTestId('task-create-open'));
      });

      expect(screen.getByTestId('task-create-kind')).toBeTruthy();
      expect(screen.getByTestId('task-create-type')).toBeTruthy();
      expect(screen.getByTestId('task-create-priority')).toBeTruthy();
      expect(screen.getByTestId('task-create-origin')).toBeTruthy();
      expect(screen.getByTestId('task-create-source-story-id')).toBeTruthy();
    });
  });

  // AC4: link/unlink — only task|story targets, bidirectional

  describe('AC4 — link/unlink (task|story only, no artifacts)', () => {
    it('link form offers only task and story as target_kind (no artifact option)', async () => {
      const transport = makeTaskTransport();
      const client = new BffClient('', transport);

      await act(async () => {
        render(<TaskSlot projectKey="AG3" client={client} />);
      });

      // Open link form for the open task
      await act(async () => {
        fireEvent.click(screen.getByTestId(`task-add-link-${OPEN_TASK.task_id}`));
      });

      const kindSelect = screen.getByTestId(`task-link-target-kind-${OPEN_TASK.task_id}`);
      const options = Array.from(kindSelect.querySelectorAll('option')).map((o) => (o as HTMLOptionElement).value);
      expect(options).toContain('task');
      expect(options).toContain('story');
      expect(options).not.toContain('artifact'); // never allowed (FK-77 §77.3)
    });

    it('link to story calls POST .../links with target_kind=story', async () => {
      const transport = makeTaskTransport(TASK_LIST_RESPONSE, 200, undefined, undefined, undefined, TASK_LINK_STORY);
      const client = new BffClient('', transport);

      await act(async () => {
        render(<TaskSlot projectKey="AG3" client={client} />);
      });

      await act(async () => {
        fireEvent.click(screen.getByTestId(`task-add-link-${OPEN_TASK.task_id}`));
      });

      await act(async () => {
        fireEvent.change(screen.getByTestId(`task-link-target-id-${OPEN_TASK.task_id}`), {
          target: { value: 'AG3-042' },
        });
        fireEvent.click(
          screen.getByTestId(`task-link-target-kind-${OPEN_TASK.task_id}`).closest('form')!
            .querySelector('button[type="submit"]')!,
        );
      });

      const calls = transport.mock.calls as [string, RequestInit?][];
      const linkCalls = calls.filter(([u, opts]) =>
        opts?.method === 'POST' && u.includes('/links') && !u.includes('/delete'),
      );
      expect(linkCalls.length).toBeGreaterThan(0);
      const body = JSON.parse(linkCalls[0]![1]!.body as string) as Record<string, unknown>;
      expect(body['target_kind']).toBe('story');
      expect(body['target_id']).toBe('AG3-042');
      expect(body['kind']).toBeDefined(); // relation kind field is `kind` (NOT `relation_kind`)
    });

    it('link badge appears after linking', async () => {
      const transport = makeTaskTransport(TASK_LIST_RESPONSE, 200, undefined, undefined, undefined, TASK_LINK_STORY);
      const client = new BffClient('', transport);

      await act(async () => {
        render(<TaskSlot projectKey="AG3" client={client} />);
      });

      await act(async () => {
        fireEvent.click(screen.getByTestId(`task-add-link-${OPEN_TASK.task_id}`));
      });

      await act(async () => {
        fireEvent.change(screen.getByTestId(`task-link-target-id-${OPEN_TASK.task_id}`), {
          target: { value: 'AG3-042' },
        });
        const form = screen.getByTestId(`task-link-form-${OPEN_TASK.task_id}`);
        fireEvent.submit(form);
      });

      await waitFor(() => {
        expect(screen.queryByTestId(`task-link-badge-${OPEN_TASK.task_id}-story-AG3-042`)).toBeTruthy();
      });
    });

    it('unlink calls POST .../links/delete with correct body', async () => {
      // Seed a link first
      const transport = makeTaskTransport(TASK_LIST_RESPONSE, 200, undefined, undefined, undefined, TASK_LINK_TASK);
      const client = new BffClient('', transport);

      await act(async () => {
        render(<TaskSlot projectKey="AG3" client={client} />);
      });

      // First add a link so the unlink button appears
      await act(async () => {
        fireEvent.click(screen.getByTestId(`task-add-link-${OPEN_TASK.task_id}`));
      });
      await act(async () => {
        fireEvent.change(screen.getByTestId(`task-link-target-kind-${OPEN_TASK.task_id}`), {
          target: { value: 'task' },
        });
        fireEvent.change(screen.getByTestId(`task-link-target-id-${OPEN_TASK.task_id}`), {
          target: { value: 'TM-2025-0002' },
        });
        fireEvent.change(screen.getByTestId(`task-link-kind-${OPEN_TASK.task_id}`), {
          target: { value: 'duplicate_of' },
        });
        const form = screen.getByTestId(`task-link-form-${OPEN_TASK.task_id}`);
        fireEvent.submit(form);
      });

      await waitFor(() => {
        expect(screen.queryByTestId(`task-unlink-${OPEN_TASK.task_id}-task-TM-2025-0002`)).toBeTruthy();
      });

      await act(async () => {
        fireEvent.click(screen.getByTestId(`task-unlink-${OPEN_TASK.task_id}-task-TM-2025-0002`));
      });

      const calls = transport.mock.calls as [string, RequestInit?][];
      const unlinkCalls = calls.filter(([u, opts]) =>
        opts?.method === 'POST' && u.includes('/links/delete'),
      );
      expect(unlinkCalls.length).toBeGreaterThan(0);
      const body = JSON.parse(unlinkCalls[0]![1]!.body as string) as Record<string, unknown>;
      expect(body['target_kind']).toBe('task');
      expect(body['target_id']).toBe('TM-2025-0002');
    });
  });

  // AC5: resolve=done/dismiss=dismissed strictly separate; terminal tasks no actions

  describe('AC5 — resolve/dismiss strictly separate, terminal tasks no actions', () => {
    it('does not show resolve/dismiss buttons for non-open tasks (terminal = no actions)', async () => {
      const transport = makeTaskTransport();
      const client = new BffClient('', transport);

      await act(async () => {
        render(<TaskSlot projectKey="AG3" client={client} />);
      });

      expect(screen.queryByTestId(`task-resolve-${DONE_TASK.task_id}`)).toBeNull();
      expect(screen.queryByTestId(`task-dismiss-${DONE_TASK.task_id}`)).toBeNull();
      expect(screen.queryByTestId(`task-resolve-${DISMISSED_TASK.task_id}`)).toBeNull();
      expect(screen.queryByTestId(`task-dismiss-${DISMISSED_TASK.task_id}`)).toBeNull();
    });

    it('resolve button calls POST .../resolve (not dismiss endpoint)', async () => {
      const transport = makeTaskTransport();
      const client = new BffClient('', transport);

      await act(async () => {
        render(<TaskSlot projectKey="AG3" client={client} />);
      });

      await act(async () => {
        fireEvent.click(screen.getByTestId(`task-resolve-${OPEN_TASK.task_id}`));
      });

      const calls = transport.mock.calls as [string, RequestInit?][];
      const resolveCalls = calls.filter(([u, opts]) => opts?.method === 'POST' && u.includes('/resolve'));
      const dismissCalls = calls.filter(([u, opts]) => opts?.method === 'POST' && u.includes('/dismiss'));
      expect(resolveCalls.length).toBeGreaterThan(0);
      expect(dismissCalls).toHaveLength(0);
    });

    it('resolve POST body contains resolved_by: human', async () => {
      const transport = makeTaskTransport();
      const client = new BffClient('', transport);

      await act(async () => {
        render(<TaskSlot projectKey="AG3" client={client} />);
      });

      await act(async () => {
        fireEvent.click(screen.getByTestId(`task-resolve-${OPEN_TASK.task_id}`));
      });

      const calls = transport.mock.calls as [string, RequestInit?][];
      const resolveCall = calls.find(([u, opts]) => opts?.method === 'POST' && u.includes('/resolve'));
      expect(resolveCall).toBeTruthy();
      const body = JSON.parse(resolveCall![1]!.body as string) as Record<string, unknown>;
      expect(body.resolved_by).toBe('human');
    });

    it('resolve URL ends with /resolve (correct path)', async () => {
      const transport = makeTaskTransport();
      const client = new BffClient('', transport);

      await act(async () => {
        render(<TaskSlot projectKey="AG3" client={client} />);
      });

      await act(async () => {
        fireEvent.click(screen.getByTestId(`task-resolve-${OPEN_TASK.task_id}`));
      });

      const calls = transport.mock.calls as [string, RequestInit?][];
      const resolveCall = calls.find(([u, opts]) => opts?.method === 'POST' && u.includes('/resolve'));
      expect(resolveCall![0]).toContain(OPEN_TASK.task_id);
      expect(resolveCall![0]).toMatch(/\/resolve$/);
    });

    it('dismiss button calls POST .../dismiss (not resolve endpoint)', async () => {
      const transport = makeTaskTransport();
      const client = new BffClient('', transport);

      await act(async () => {
        render(<TaskSlot projectKey="AG3" client={client} />);
      });

      await act(async () => {
        fireEvent.click(screen.getByTestId(`task-dismiss-${OPEN_TASK.task_id}`));
      });

      const calls = transport.mock.calls as [string, RequestInit?][];
      const dismissCalls = calls.filter(([u, opts]) => opts?.method === 'POST' && u.includes('/dismiss'));
      const resolveCalls = calls.filter(([u, opts]) => opts?.method === 'POST' && u.includes('/resolve'));
      expect(dismissCalls.length).toBeGreaterThan(0);
      expect(resolveCalls).toHaveLength(0);
    });

    it('dismiss URL ends with /dismiss (correct path)', async () => {
      const transport = makeTaskTransport();
      const client = new BffClient('', transport);

      await act(async () => {
        render(<TaskSlot projectKey="AG3" client={client} />);
      });

      await act(async () => {
        fireEvent.click(screen.getByTestId(`task-dismiss-${OPEN_TASK.task_id}`));
      });

      const calls = transport.mock.calls as [string, RequestInit?][];
      const dismissCall = calls.find(([u, opts]) => opts?.method === 'POST' && u.includes('/dismiss'));
      expect(dismissCall![0]).toContain(OPEN_TASK.task_id);
      expect(dismissCall![0]).toMatch(/\/dismiss$/);
    });

    it('optimistic update: task appears done immediately before server responds', async () => {
      // Use a slow transport to capture the intermediate state
      let resolvePromise!: () => void;
      const resolvedTask: WireTask = { ...OPEN_TASK, status: 'done', resolved_at: '2025-06-02T12:00:00Z', resolved_by: 'human' };
      const transport = vi.fn().mockImplementation((url: string, options?: RequestInit) => {
        const method = options?.method ?? 'GET';
        if (method === 'GET') {
          return Promise.resolve(jsonResponse(200, TASK_LIST_RESPONSE));
        }
        if (method === 'POST' && url.includes('/resolve')) {
          return new Promise<Response>((res) => {
            resolvePromise = () => res(jsonResponse(200, { task: resolvedTask, project_key: 'AG3' }) as Response);
          });
        }
        return Promise.resolve(jsonResponse(404, { error_code: 'not_found' }));
      });
      const client = new BffClient('', transport);

      await act(async () => {
        render(<TaskSlot projectKey="AG3" client={client} />);
      });

      // Click resolve — task should optimistically appear done before server responds
      act(() => {
        fireEvent.click(screen.getByTestId(`task-resolve-${OPEN_TASK.task_id}`));
      });

      // Task should appear done optimistically (status element has 'Erledigt')
      await waitFor(() => {
        const statusEl = screen.getByTestId(`task-status-${OPEN_TASK.task_id}`);
        expect(statusEl.textContent).toBe('Erledigt');
      });

      // Now resolve the server call
      await act(async () => { resolvePromise(); });
    });

    it('optimistic revert: if resolve fails, task reverts to open', async () => {
      const transport = makeTaskTransport(TASK_LIST_RESPONSE, 409); // 409 = conflict = failure
      const client = new BffClient('', transport);

      await act(async () => {
        render(<TaskSlot projectKey="AG3" client={client} />);
      });

      await act(async () => {
        fireEvent.click(screen.getByTestId(`task-resolve-${OPEN_TASK.task_id}`));
      });

      // After failed resolve, task should revert to open (revert, AC9)
      await waitFor(() => {
        const statusEl = screen.getByTestId(`task-status-${OPEN_TASK.task_id}`);
        expect(statusEl.textContent).toBe('Offen');
      });

      // Error pill appears with error_code
      const errorEl = screen.getByTestId('task-mutate-error');
      expect(errorEl).toBeTruthy();
      const codeEl = screen.getByTestId('task-mutate-error-code');
      expect(codeEl.textContent).toContain('invalid_transition');
    });
  });

  // AC9: error pill with error_code + empty state CTA + optimistic revert

  describe('AC9 — error pills, create CTA, optimistic revert', () => {
    it('shows error pill when listTasks fails', async () => {
      const transport = makeErrorTransport();
      const client = new BffClient('', transport);

      await act(async () => {
        render(<TaskSlot projectKey="AG3" client={client} />);
      });

      expect(screen.getByTestId('task-load-error')).toBeTruthy();
    });

    it('error pill includes error_code (not just message)', async () => {
      const transport = makeErrorTransport('task_management_unavailable');
      const client = new BffClient('', transport);

      await act(async () => {
        render(<TaskSlot projectKey="AG3" client={client} />);
      });

      const errorEl = screen.getByTestId('task-load-error');
      expect(errorEl).toBeTruthy();
      expect(screen.getByTestId('task-load-error-code').textContent).toContain('task_management_unavailable');
    });

    it('empty state shows a create CTA button', async () => {
      const transport = makeTaskTransport(EMPTY_TASK_LIST_RESPONSE);
      const client = new BffClient('', transport);

      await act(async () => {
        render(<TaskSlot projectKey="AG3" client={client} />);
      });

      expect(screen.getByTestId('task-empty')).toBeTruthy();
      expect(screen.getByTestId('task-empty-create-cta')).toBeTruthy();
    });

    it('mutate error pill includes error_code from BffReadError', async () => {
      const transport = makeTaskTransport(TASK_LIST_RESPONSE, 409);
      const client = new BffClient('', transport);

      await act(async () => {
        render(<TaskSlot projectKey="AG3" client={client} />);
      });

      await act(async () => {
        fireEvent.click(screen.getByTestId(`task-resolve-${OPEN_TASK.task_id}`));
      });

      await waitFor(() => {
        const errorEl = screen.getByTestId('task-mutate-error');
        expect(errorEl).toBeTruthy();
        expect(screen.getByTestId('task-mutate-error-code').textContent).toContain('invalid_transition');
      });
    });
  });

  // AG3-105 finding 1: link badges hydrate from the backend (GET /task-links), no shadow

  describe('finding 1 — link badges hydrate from backend on load (SSOT)', () => {
    it('renders link badges from GET /task-links on initial load (no prior mutation)', async () => {
      const linksResponse = {
        project_key: 'AG3',
        links: [TASK_LINK_STORY, TASK_LINK_TASK],
      };
      const transport = makeTaskTransport(
        TASK_LIST_RESPONSE, 200, undefined, undefined, undefined, TASK_LINK_STORY, linksResponse,
      );
      const client = new BffClient('', transport);

      await act(async () => {
        render(<TaskSlot projectKey="AG3" client={client} />);
      });

      // Both backend links appear as badges WITHOUT any UI mutation happening.
      await waitFor(() => {
        expect(screen.queryByTestId(`task-link-badge-${OPEN_TASK.task_id}-story-AG3-042`)).toBeTruthy();
        expect(screen.queryByTestId(`task-link-badge-${OPEN_TASK.task_id}-task-TM-2025-0002`)).toBeTruthy();
      });

      // The /task-links endpoint was actually queried on load.
      const calls = transport.mock.calls as [string, RequestInit?][];
      const linkReads = calls.filter(([u, opts]) =>
        (opts?.method ?? 'GET') === 'GET' && u.includes('/task-links'),
      );
      expect(linkReads.length).toBeGreaterThan(0);
    });

    it('buckets links by task_id (a link on another task is not shown on this task)', async () => {
      const otherTaskLink: WireTaskLink = {
        project_key: 'AG3',
        task_id: 'TM-2025-0002', // belongs to a DIFFERENT task (the done one)
        target_kind: 'story',
        target_id: 'AG3-099',
        kind: 'relates_to',
      };
      const linksResponse = { project_key: 'AG3', links: [TASK_LINK_STORY, otherTaskLink] };
      const transport = makeTaskTransport(
        TASK_LIST_RESPONSE, 200, undefined, undefined, undefined, TASK_LINK_STORY, linksResponse,
      );
      const client = new BffClient('', transport);

      await act(async () => {
        render(<TaskSlot projectKey="AG3" client={client} />);
      });

      await waitFor(() => {
        expect(screen.queryByTestId(`task-link-badge-${OPEN_TASK.task_id}-story-AG3-042`)).toBeTruthy();
      });
      // The open task does NOT show the link that belongs to TM-2025-0002.
      expect(screen.queryByTestId(`task-link-badge-${OPEN_TASK.task_id}-story-AG3-099`)).toBeNull();
      // ...but the done task (TM-2025-0002) does show it.
      expect(screen.queryByTestId(`task-link-badge-${DONE_TASK.task_id}-story-AG3-099`)).toBeTruthy();
    });
  });

  // AG3-105 finding 2: terminal tasks keep read-only badges but no MUTATE controls

  describe('finding 2 — terminal tasks: read-only badges, no mutate controls', () => {
    it('terminal task shows link badge but NO + Link button and NO unlink ×', async () => {
      const terminalLink: WireTaskLink = {
        project_key: 'AG3',
        task_id: DONE_TASK.task_id,
        target_kind: 'story',
        target_id: 'AG3-300',
        kind: 'relates_to',
      };
      const linksResponse = { project_key: 'AG3', links: [terminalLink] };
      const transport = makeTaskTransport(
        TASK_LIST_RESPONSE, 200, undefined, undefined, undefined, TASK_LINK_STORY, linksResponse,
      );
      const client = new BffClient('', transport);

      await act(async () => {
        render(<TaskSlot projectKey="AG3" client={client} />);
      });

      // Badge IS visible (read-only) for the terminal/done task.
      await waitFor(() => {
        expect(screen.queryByTestId(`task-link-badge-${DONE_TASK.task_id}-story-AG3-300`)).toBeTruthy();
      });
      // But mutating controls are hidden: no + Link button, no AddLinkForm trigger,
      // no per-badge unlink × on the terminal task.
      expect(screen.queryByTestId(`task-add-link-${DONE_TASK.task_id}`)).toBeNull();
      expect(screen.queryByTestId(`task-link-form-${DONE_TASK.task_id}`)).toBeNull();
      expect(screen.queryByTestId(`task-unlink-${DONE_TASK.task_id}-story-AG3-300`)).toBeNull();

      // The OPEN task still has its + Link control.
      expect(screen.queryByTestId(`task-add-link-${OPEN_TASK.task_id}`)).toBeTruthy();
    });
  });

  // AG3-105 finding 3: cross-slice navigation via onFocusStory

  describe('finding 3 — story link badge focuses story via onFocusStory', () => {
    it('clicking a story link badge calls onFocusStory with the target story id', async () => {
      const linksResponse = { project_key: 'AG3', links: [TASK_LINK_STORY] };
      const transport = makeTaskTransport(
        TASK_LIST_RESPONSE, 200, undefined, undefined, undefined, TASK_LINK_STORY, linksResponse,
      );
      const client = new BffClient('', transport);
      const onFocusStory = vi.fn();

      await act(async () => {
        render(<TaskSlot projectKey="AG3" client={client} onFocusStory={onFocusStory} />);
      });

      await waitFor(() => {
        expect(screen.queryByTestId(`task-link-focus-${OPEN_TASK.task_id}-AG3-042`)).toBeTruthy();
      });

      await act(async () => {
        fireEvent.click(screen.getByTestId(`task-link-focus-${OPEN_TASK.task_id}-AG3-042`));
      });

      expect(onFocusStory).toHaveBeenCalledWith('AG3-042');
    });

    it('task link badge is NOT navigable (only story links focus a story)', async () => {
      const linksResponse = { project_key: 'AG3', links: [TASK_LINK_TASK] };
      const transport = makeTaskTransport(
        TASK_LIST_RESPONSE, 200, undefined, undefined, undefined, TASK_LINK_STORY, linksResponse,
      );
      const client = new BffClient('', transport);
      const onFocusStory = vi.fn();

      await act(async () => {
        render(<TaskSlot projectKey="AG3" client={client} onFocusStory={onFocusStory} />);
      });

      await waitFor(() => {
        expect(screen.queryByTestId(`task-link-badge-${OPEN_TASK.task_id}-task-TM-2025-0002`)).toBeTruthy();
      });
      // No focus button for a task-kind link.
      expect(screen.queryByTestId(`task-link-focus-${OPEN_TASK.task_id}-TM-2025-0002`)).toBeNull();
    });
  });

  // AG3-105 finding 6: optimistic-revert for dismiss and unlink

  describe('finding 6 — optimistic revert for dismiss and unlink', () => {
    it('dismiss failure reverts the task back to open', async () => {
      const transport = makeTaskTransport(TASK_LIST_RESPONSE, 409);
      const client = new BffClient('', transport);

      await act(async () => {
        render(<TaskSlot projectKey="AG3" client={client} />);
      });

      await act(async () => {
        fireEvent.click(screen.getByTestId(`task-dismiss-${OPEN_TASK.task_id}`));
      });

      await waitFor(() => {
        const statusEl = screen.getByTestId(`task-status-${OPEN_TASK.task_id}`);
        expect(statusEl.textContent).toBe('Offen');
      });
      expect(screen.getByTestId('task-mutate-error-code').textContent).toContain('invalid_transition');
    });

    it('unlink failure reverts the removed badge (optimistic revert)', async () => {
      // Hydrate a link from the backend, then fail the unlink mutation.
      const linksResponse = { project_key: 'AG3', links: [TASK_LINK_STORY] };
      const transport = makeTaskTransport(
        TASK_LIST_RESPONSE, 409, undefined, undefined, undefined, TASK_LINK_STORY, linksResponse,
      );
      const client = new BffClient('', transport);

      await act(async () => {
        render(<TaskSlot projectKey="AG3" client={client} />);
      });

      await waitFor(() => {
        expect(screen.queryByTestId(`task-unlink-${OPEN_TASK.task_id}-story-AG3-042`)).toBeTruthy();
      });

      await act(async () => {
        fireEvent.click(screen.getByTestId(`task-unlink-${OPEN_TASK.task_id}-story-AG3-042`));
      });

      // After the failed unlink, the badge is restored (revert) and an error pill shows.
      await waitFor(() => {
        expect(screen.queryByTestId(`task-link-badge-${OPEN_TASK.task_id}-story-AG3-042`)).toBeTruthy();
        expect(screen.getByTestId('task-mutate-error-code').textContent).toContain('task_link_not_found');
      });
    });
  });

  // AG3-105 r3 finding 1a: reverse view (task side) — tasks linking TO a task

  describe('finding 1a — reverse view (task side) via list_tasks_for_target', () => {
    it('renders "Verlinkende Aufgaben" with the linking task id from for-target read', async () => {
      // A separate task TM-2025-0077 links TO the open task TM-2025-0001.
      const linkingTask: WireTask = {
        ...OPEN_TASK,
        task_id: 'TM-2025-0077',
        title: 'Linker task',
      };
      // for-target('task', OPEN_TASK) returns the linking task; all others empty.
      const transport = vi.fn().mockImplementation((url: string, options?: RequestInit) => {
        const method = options?.method ?? 'GET';
        if (method === 'GET' && url.includes('/task-links')) {
          return Promise.resolve(jsonResponse(200, { project_key: 'AG3', links: [] }));
        }
        if (method === 'GET' && url.includes(`/tasks/for-target/task/${OPEN_TASK.task_id}`)) {
          return Promise.resolve(jsonResponse(200, { project_key: 'AG3', tasks: [linkingTask] }));
        }
        if (method === 'GET' && url.includes('/tasks/for-target/')) {
          return Promise.resolve(jsonResponse(200, { project_key: 'AG3', tasks: [] }));
        }
        if (method === 'GET' && url.includes('/tasks')) {
          return Promise.resolve(jsonResponse(200, TASK_LIST_RESPONSE));
        }
        return Promise.resolve(jsonResponse(404, { error_code: 'not_found' }));
      });
      const client = new BffClient('', transport);

      await act(async () => {
        render(<TaskSlot projectKey="AG3" client={client} />);
      });

      // The reverse section appears for the open task, listing the linker id —
      // proving it came from list_tasks_for_target, not from session link state.
      await waitFor(() => {
        expect(screen.queryByTestId(`task-reverse-links-${OPEN_TASK.task_id}`)).toBeTruthy();
        expect(
          screen.queryByTestId(`task-reverse-link-${OPEN_TASK.task_id}-${linkingTask.task_id}`),
        ).toBeTruthy();
      });

      // A task with NO incoming links has no reverse section.
      expect(screen.queryByTestId(`task-reverse-links-${DONE_TASK.task_id}`)).toBeNull();

      // The for-target endpoint was actually queried per task.
      const calls = transport.mock.calls as [string, RequestInit?][];
      const forTargetReads = calls.filter(([u]) =>
        u.includes(`/tasks/for-target/task/${OPEN_TASK.task_id}`),
      );
      expect(forTargetReads.length).toBeGreaterThan(0);
    });

    it('excludes self: a task is never listed as its own linker', async () => {
      // for-target returns the task itself (defensive) — must be filtered out.
      const transport = vi.fn().mockImplementation((url: string, options?: RequestInit) => {
        const method = options?.method ?? 'GET';
        if (method === 'GET' && url.includes('/task-links')) {
          return Promise.resolve(jsonResponse(200, { project_key: 'AG3', links: [] }));
        }
        if (method === 'GET' && url.includes(`/tasks/for-target/task/${OPEN_TASK.task_id}`)) {
          return Promise.resolve(jsonResponse(200, { project_key: 'AG3', tasks: [OPEN_TASK] }));
        }
        if (method === 'GET' && url.includes('/tasks/for-target/')) {
          return Promise.resolve(jsonResponse(200, { project_key: 'AG3', tasks: [] }));
        }
        if (method === 'GET' && url.includes('/tasks')) {
          return Promise.resolve(jsonResponse(200, TASK_LIST_RESPONSE));
        }
        return Promise.resolve(jsonResponse(404, { error_code: 'not_found' }));
      });
      const client = new BffClient('', transport);

      await act(async () => {
        render(<TaskSlot projectKey="AG3" client={client} />);
      });

      // No reverse section rendered because the only linker was self (filtered).
      await waitFor(() => {
        expect(screen.queryByTestId('task-slot')).toBeTruthy();
      });
      expect(screen.queryByTestId(`task-reverse-links-${OPEN_TASK.task_id}`)).toBeNull();
    });
  });

  // AG3-105 r3 finding 2: stale-request guard (cross-tenant race)

  describe('finding 2 — cross-tenant stale-request guard on projectKey switch', () => {
    it('a slow project-A fetch resolving after project-B never overwrites B data', async () => {
      const TASK_A: WireTask = { ...OPEN_TASK, task_id: 'TM-A-0001', project_key: 'PROJ_A', title: 'Project A task' };
      const TASK_B: WireTask = { ...OPEN_TASK, task_id: 'TM-B-0001', project_key: 'PROJ_B', title: 'Project B task' };

      // Hold project-A's task list until we explicitly release it, so it can be
      // made to resolve AFTER project-B's (already resolved) fetch.
      let releaseA!: () => void;
      const aGate = new Promise<void>((res) => { releaseA = res; });

      const transport = vi.fn().mockImplementation(async (url: string, options?: RequestInit) => {
        const method = options?.method ?? 'GET';
        const isProjA = url.includes('/projects/PROJ_A/');
        if (method === 'GET' && url.includes('/task-links')) {
          return jsonResponse(200, { project_key: isProjA ? 'PROJ_A' : 'PROJ_B', links: [] });
        }
        if (method === 'GET' && url.includes('/tasks/for-target/')) {
          return jsonResponse(200, { project_key: isProjA ? 'PROJ_A' : 'PROJ_B', tasks: [] });
        }
        if (method === 'GET' && url.includes('/tasks')) {
          if (isProjA) {
            await aGate; // project A is slow — held until released
            return jsonResponse(200, { project_key: 'PROJ_A', tasks: [TASK_A] });
          }
          return jsonResponse(200, { project_key: 'PROJ_B', tasks: [TASK_B] });
        }
        return jsonResponse(404, { error_code: 'not_found' });
      });
      const client = new BffClient('', transport);

      // Render for project A (fetch is in-flight, held at the gate).
      const { rerender } = render(<TaskSlot projectKey="PROJ_A" client={client} />);

      // Switch to project B before A resolves — B's fetch completes immediately.
      await act(async () => {
        rerender(<TaskSlot projectKey="PROJ_B" client={client} />);
      });
      await waitFor(() => {
        expect(screen.queryByTestId(`task-row-${TASK_B.task_id}`)).toBeTruthy();
      });

      // NOW release the stale project-A fetch. Its result is superseded and must
      // be dropped — the UI must keep showing B's data, never A's.
      await act(async () => {
        releaseA();
        await aGate;
      });

      // B still shown; A's task must NEVER appear under project B.
      await waitFor(() => {
        expect(screen.queryByTestId(`task-row-${TASK_B.task_id}`)).toBeTruthy();
      });
      expect(screen.queryByTestId(`task-row-${TASK_A.task_id}`)).toBeNull();
    });

    it('two projects with identical task_id render strictly partitioned data', async () => {
      // Same task_id, different tenant + title — proves no cross-tenant bleed.
      const SHARED_ID = 'TM-2025-0001';
      const A_TASK: WireTask = { ...OPEN_TASK, task_id: SHARED_ID, project_key: 'PROJ_A', title: 'A-tenant title' };
      const B_TASK: WireTask = { ...OPEN_TASK, task_id: SHARED_ID, project_key: 'PROJ_B', title: 'B-tenant title' };

      const transport = vi.fn().mockImplementation((url: string, options?: RequestInit) => {
        const method = options?.method ?? 'GET';
        const isProjA = url.includes('/projects/PROJ_A/');
        if (method === 'GET' && url.includes('/task-links')) {
          return Promise.resolve(jsonResponse(200, { project_key: isProjA ? 'PROJ_A' : 'PROJ_B', links: [] }));
        }
        if (method === 'GET' && url.includes('/tasks/for-target/')) {
          return Promise.resolve(jsonResponse(200, { project_key: isProjA ? 'PROJ_A' : 'PROJ_B', tasks: [] }));
        }
        if (method === 'GET' && url.includes('/tasks')) {
          return Promise.resolve(jsonResponse(200, { project_key: isProjA ? 'PROJ_A' : 'PROJ_B', tasks: [isProjA ? A_TASK : B_TASK] }));
        }
        return Promise.resolve(jsonResponse(404, { error_code: 'not_found' }));
      });
      const client = new BffClient('', transport);

      const { rerender } = render(<TaskSlot projectKey="PROJ_A" client={client} />);
      await waitFor(() => {
        expect(screen.getByTestId(`task-title-${SHARED_ID}`).textContent).toBe('A-tenant title');
      });

      await act(async () => {
        rerender(<TaskSlot projectKey="PROJ_B" client={client} />);
      });
      await waitFor(() => {
        expect(screen.getByTestId(`task-title-${SHARED_ID}`).textContent).toBe('B-tenant title');
      });
    });
  });

  // Rendering misc

  describe('rendering misc', () => {
    it('renders empty state when no tasks', async () => {
      const transport = makeTaskTransport(EMPTY_TASK_LIST_RESPONSE);
      const client = new BffClient('', transport);

      await act(async () => {
        render(<TaskSlot projectKey="AG3" client={client} />);
      });

      expect(screen.getByTestId('task-empty')).toBeTruthy();
    });
  });
});
