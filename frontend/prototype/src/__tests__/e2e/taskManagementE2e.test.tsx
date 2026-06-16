/**
 * E2E: Task-Management UI round-trip against the REAL Python backend (AG3-105 / FK-77 AC11).
 *
 * REAL backend, REAL SQLite — no mocks at the backend or DB boundary.
 *
 * The test starts the Python harness (ControlPlaneApplication over real SQLite),
 * creates a project, and then:
 *
 * 1. RENDERS the TaskSlot component (real component, real React rendering).
 * 2. Drives create through the RENDERED UI (fill form, submit button click).
 * 3. The create goes UI -> real BffClient -> real HTTP -> real TaskManagement -> real SQLite write.
 * 4. The new task appears in the rendered UI from the SERVER RESPONSE (not local shadow).
 * 5. Drives resolve through the rendered UI — real HTTP -> real SQLite write.
 * 6. Change reappears in the rendered UI (task status = done).
 * 7. Drives dismiss through the rendered UI on a second task — status = dismissed.
 * 8. Drives link through the rendered UI — POST .../links -> link badge appears.
 *
 * AC11 proof: create + resolve + dismiss + link go THROUGH the rendered UI using
 * real fireEvent/userEvent on real buttons/inputs, backed by real backend + real DB.
 *
 * AG3-105 finding 5 (strengthened, NO seed shortcut for the action loops):
 *   - create->resolve->reload : task created via the UI form, resolved via the UI,
 *     then a FRESH TaskSlot re-fetches and the 'done' status comes from a real
 *     backend read (real TaskManagement -> real SQLite write -> real read).
 *   - create->dismiss->reload : same loop, dismissed.
 *   - link->reload-hydrates    : source+target created via the UI, linked via the
 *     UI, then a FRESH TaskSlot re-render shows the badge purely from
 *     GET /task-links (backend truth — proves finding 1: no session shadow).
 *   The `_test/seed-task` helper is intentionally NOT used for these loops; the
 *   first seed-based test (endpoint separation) keeps a seed only where it needs
 *   pre-existing data.
 */
/// <reference types="node" />
import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import { render, screen, fireEvent, act, waitFor, cleanup } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { spawn, type ChildProcess } from 'node:child_process';
import * as path from 'node:path';
import { BffClient } from '../../foundation/bff/client';
import { TaskSlot } from '../../contexts/task_management/TaskSlot';
import { DetailInspector } from '../../app_shell/inspector/DetailInspector';
import type { Story } from '../../store';

const REPO_ROOT = path.join(__dirname, '..', '..', '..', '..', '..');
const PYTHON =
  process.platform === 'win32'
    ? path.join(REPO_ROOT, '.venv', 'Scripts', 'python.exe')
    : path.join(REPO_ROOT, '.venv', 'bin', 'python3');
const HARNESS_PATH = path.join(__dirname, '..', '..', '..', 'tests', 'python_harness.py');
const TIMEOUT = 60_000;

let serverProcess: ChildProcess | null = null;
let baseUrl = '';
// Use timestamp for BOTH project key and prefix to avoid SQLite collisions
// from previous runs on shared Path.cwd() project store.
const _TS = Date.now();
const PROJECT_KEY = `e2eui${_TS}`;
const PROJECT_PREFIX = `UI${String(_TS).slice(-6)}`;

async function waitForLine(proc: ChildProcess, timeoutMs: number): Promise<string> {
  return new Promise((resolve, reject) => {
    let output = '';
    const timer = setTimeout(
      () => reject(new Error(`Timeout waiting for harness output. Got: ${output}`)),
      timeoutMs,
    );
    proc.stdout?.on('data', (chunk: Buffer) => {
      output += chunk.toString();
      const line = output.split('\n')[0]?.trim();
      if (line) {
        clearTimeout(timer);
        resolve(line);
      }
    });
    proc.stderr?.on('data', (chunk: Buffer) => {
      output += chunk.toString();
    });
    proc.on('exit', (code) => {
      clearTimeout(timer);
      reject(new Error(`Harness exited with code ${code}. Output: ${output}`));
    });
  });
}

async function apiPost(url: string, body: object): Promise<Response> {
  return fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

beforeAll(async () => {
  serverProcess = spawn(PYTHON, [HARNESS_PATH, '0'], {
    stdio: ['ignore', 'pipe', 'pipe'],
    env: { ...process.env },
  });

  let port: string;
  try {
    port = await waitForLine(serverProcess, 20_000);
  } catch (err) {
    serverProcess?.kill();
    throw new Error(`Failed to start Python harness: ${err}`, { cause: err });
  }

  baseUrl = `http://127.0.0.1:${port}`;

  // Create project — unique key + prefix to avoid SQLite collision from prior runs.
  const createProjectResp = await apiPost(`${baseUrl}/v1/projects`, {
    key: PROJECT_KEY,
    name: 'E2E UI Task Test',
    story_id_prefix: PROJECT_PREFIX,
    configuration: {
      repo_url: 'https://github.com/e2e/task-ui-test',
      default_branch: 'main',
      default_worker_count: 1,
      repositories: ['https://github.com/e2e/task-ui-test'],
    },
  });
  if (!createProjectResp.ok) {
    throw new Error(
      `Failed to create project: ${createProjectResp.status} ${await createProjectResp.text()}`,
    );
  }
}, TIMEOUT);

afterAll(async () => {
  // Unmount all rendered components before killing the server to prevent
  // "window is not defined" errors from pending async state updates.
  cleanup();
  // Small delay to let pending promises settle before killing the server.
  await new Promise((resolve) => setTimeout(resolve, 100));
  serverProcess?.kill();
});

describe('AG3-105 AC11: Task-Management UI E2E (rendered UI + real backend + real SQLite)', () => {

  it('UI-driven create: renders UI, fills form, submits, task appears from server response', async () => {
    // Render the real TaskSlot component pointed at the real backend
    const client = new BffClient(baseUrl);

    await act(async () => {
      render(<TaskSlot projectKey={PROJECT_KEY} client={client} />);
    });

    // Wait for initial load to complete
    await waitFor(() => {
      expect(screen.getByTestId('task-slot')).toBeTruthy();
    });

    // Open create form by clicking the UI button
    await act(async () => {
      fireEvent.click(screen.getByTestId('task-create-open'));
    });

    expect(screen.getByTestId('task-create-form')).toBeTruthy();

    // Fill in the create form through the UI using userEvent for proper React state updates
    const titleValue = `UI-Created Task ${Date.now()}`;
    const bodyValue = 'Created through the rendered UI in the E2E test';

    const user = userEvent.setup();
    await user.clear(screen.getByTestId('task-create-title'));
    await user.type(screen.getByTestId('task-create-title'), titleValue);
    await user.clear(screen.getByTestId('task-create-body'));
    await user.type(screen.getByTestId('task-create-body'), bodyValue);

    // Submit through the UI — goes UI -> real BffClient -> real HTTP -> real TaskManagement -> real SQLite
    await user.click(screen.getByTestId('task-create-submit'));

    // Wait for server response to propagate back to the UI
    await waitFor(
      () => {
        // Task appears in the rendered UI with its server-allocated task_id
        const openList = screen.queryByTestId('task-list-open');
        expect(openList).toBeTruthy();
        // The new task title is visible in the UI (came from server response, not local shadow)
        expect(openList!.textContent).toContain(titleValue);
      },
      { timeout: 15_000 },
    );
  }, TIMEOUT);

  /**
   * Create a task purely through the rendered UI form (no seed) and return its
   * server-allocated task_id by reading it back from the real backend.
   */
  async function createTaskViaUi(client: BffClient, title: string): Promise<string> {
    const before = await client.listTasks(PROJECT_KEY);
    const beforeIds = new Set(before.tasks.map((t) => t.task_id));

    await act(async () => {
      render(<TaskSlot projectKey={PROJECT_KEY} client={client} />);
    });
    await waitFor(() => {
      expect(screen.getByTestId('task-slot')).toBeTruthy();
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId('task-create-open'));
    });
    const user = userEvent.setup();
    await user.clear(screen.getByTestId('task-create-title'));
    await user.type(screen.getByTestId('task-create-title'), title);
    await user.clear(screen.getByTestId('task-create-body'));
    await user.type(screen.getByTestId('task-create-body'), `${title} body`);
    await user.click(screen.getByTestId('task-create-submit'));

    await waitFor(
      () => {
        const openList = screen.queryByTestId('task-list-open');
        expect(openList?.textContent).toContain(title);
      },
      { timeout: 15_000 },
    );

    // Read the server-allocated id back from the real backend (no shadow).
    const after = await client.listTasks(PROJECT_KEY);
    const created = after.tasks.find((t) => !beforeIds.has(t.task_id) && t.title === title);
    if (!created) throw new Error(`Created task ${title} not found in backend after UI create`);
    return created.task_id;
  }

  it('UI-only create->resolve->reload: full loop through rendered UI, done comes from a real backend read', async () => {
    const client = new BffClient(baseUrl);

    // 1) Create via the UI form (NO seed shortcut).
    const taskId = await createTaskViaUi(client, `UIonly-Resolve ${Date.now()}`);

    // 2) Resolve via the rendered Erledigen button -> real HTTP -> real SQLite write.
    await act(async () => {
      fireEvent.click(screen.getByTestId(`task-resolve-${taskId}`));
    });
    await waitFor(
      () => {
        expect(screen.queryByTestId(`task-status-${taskId}`)?.textContent).toBe('Erledigt');
      },
      { timeout: 10_000 },
    );

    // 3) Re-render a FRESH TaskSlot (reload) and assert 'done' comes from a real
    // backend read, not session state — unmount first so the new mount re-fetches.
    cleanup();
    await act(async () => {
      render(<TaskSlot projectKey={PROJECT_KEY} client={new BffClient(baseUrl)} />);
    });
    await waitFor(
      () => {
        // The task is in the closed section after reload with status 'Erledigt'.
        expect(screen.queryByTestId(`task-status-${taskId}`)?.textContent).toBe('Erledigt');
      },
      { timeout: 10_000 },
    );

    // Hard proof of the DB write via a direct backend read.
    const resp = await client.listTasks(PROJECT_KEY);
    expect(resp.tasks.find((t) => t.task_id === taskId)?.status).toBe('done');
  }, TIMEOUT);

  it('UI-only create->dismiss->reload: dismissed status survives a fresh re-fetch from the backend', async () => {
    const client = new BffClient(baseUrl);

    const taskId = await createTaskViaUi(client, `UIonly-Dismiss ${Date.now()}`);

    await act(async () => {
      fireEvent.click(screen.getByTestId(`task-dismiss-${taskId}`));
    });
    await waitFor(
      () => {
        expect(screen.queryByTestId(`task-status-${taskId}`)?.textContent).toBe('Verworfen');
      },
      { timeout: 10_000 },
    );

    // Reload (fresh mount) — status must hydrate from the backend, not UI state.
    cleanup();
    await act(async () => {
      render(<TaskSlot projectKey={PROJECT_KEY} client={new BffClient(baseUrl)} />);
    });
    await waitFor(
      () => {
        expect(screen.queryByTestId(`task-status-${taskId}`)?.textContent).toBe('Verworfen');
      },
      { timeout: 10_000 },
    );

    const resp = await client.listTasks(PROJECT_KEY);
    expect(resp.tasks.find((t) => t.task_id === taskId)?.status).toBe('dismissed');
  }, TIMEOUT);

  it('UI-driven link->reload: link badge HYDRATES from the backend on a fresh re-fetch (not session state)', async () => {
    const client = new BffClient(baseUrl);

    // Create the source task via the UI, and a target task via the UI too.
    const sourceId = await createTaskViaUi(client, `UIonly-LinkSource ${Date.now()}`);
    cleanup();
    const targetId = await createTaskViaUi(client, `UIonly-LinkTarget ${Date.now()}`);

    // Render fresh on the source task and open its link form.
    cleanup();
    await act(async () => {
      render(<TaskSlot projectKey={PROJECT_KEY} client={new BffClient(baseUrl)} />);
    });
    await waitFor(
      () => expect(screen.queryByTestId(`task-add-link-${sourceId}`)).toBeTruthy(),
      { timeout: 10_000 },
    );
    await act(async () => {
      fireEvent.click(screen.getByTestId(`task-add-link-${sourceId}`));
    });
    await act(async () => {
      fireEvent.change(screen.getByTestId(`task-link-target-kind-${sourceId}`), {
        target: { value: 'task' },
      });
      fireEvent.change(screen.getByTestId(`task-link-target-id-${sourceId}`), {
        target: { value: targetId },
      });
      fireEvent.change(screen.getByTestId(`task-link-kind-${sourceId}`), {
        target: { value: 'relates_to' },
      });
      fireEvent.submit(screen.getByTestId(`task-link-form-${sourceId}`));
    });
    await waitFor(
      () => expect(screen.queryByTestId(`task-link-badge-${sourceId}-task-${targetId}`)).toBeTruthy(),
      { timeout: 10_000 },
    );

    // CRITICAL (finding 1): unmount and re-render a FRESH TaskSlot. The badge must
    // reappear purely from GET /task-links (backend truth), NOT session state.
    cleanup();
    await act(async () => {
      render(<TaskSlot projectKey={PROJECT_KEY} client={new BffClient(baseUrl)} />);
    });
    await waitFor(
      () => {
        expect(screen.queryByTestId(`task-link-badge-${sourceId}-task-${targetId}`)).toBeTruthy();
      },
      { timeout: 10_000 },
    );

    // And confirm the same via a direct backend read.
    const links = await new BffClient(baseUrl).listTaskLinks(PROJECT_KEY);
    expect(
      links.links.some((l) => l.task_id === sourceId && l.target_id === targetId),
    ).toBe(true);
  }, TIMEOUT);

  it('UI-driven link: opens link form, submits, link badge appears in UI', async () => {
    const client = new BffClient(baseUrl);

    const seedResp = await apiPost(`${baseUrl}/_test/seed-task`, {
      project_key: PROJECT_KEY,
      task_id: `TM-2025-${String(Date.now() + 2).slice(-4)}`,
      kind: 'actionable',
      priority: 'normal',
      status: 'open',
      origin: 'human',
      title: 'UI-Link Test Task',
    });
    if (!seedResp.ok) {
      throw new Error(`seed-task failed: ${seedResp.status} ${await seedResp.text()}`);
    }
    const seedData = (await seedResp.json()) as { task_id: string };
    const taskId = seedData.task_id;

    await act(async () => {
      render(<TaskSlot projectKey={PROJECT_KEY} client={client} />);
    });

    await waitFor(
      () => {
        expect(screen.queryByTestId(`task-add-link-${taskId}`)).toBeTruthy();
      },
      { timeout: 10_000 },
    );

    // Open link form via UI button click
    await act(async () => {
      fireEvent.click(screen.getByTestId(`task-add-link-${taskId}`));
    });

    expect(screen.getByTestId(`task-link-form-${taskId}`)).toBeTruthy();

    // Verify only task|story are offered (no artifact) — AC4
    const kindSelect = screen.getByTestId(`task-link-target-kind-${taskId}`);
    const opts = Array.from(kindSelect.querySelectorAll('option')).map((o) => (o as HTMLOptionElement).value);
    expect(opts).toContain('story');
    expect(opts).toContain('task');
    expect(opts).not.toContain('artifact');

    // Fill and submit link form — target_kind=task pointing to another seeded task
    // We'll link to a second seeded task
    const seed2Resp = await apiPost(`${baseUrl}/_test/seed-task`, {
      project_key: PROJECT_KEY,
      task_id: `TM-2025-${String(Date.now() + 3).slice(-4)}`,
      kind: 'actionable',
      priority: 'normal',
      status: 'open',
      origin: 'human',
      title: 'Link Target Task',
    });
    const seed2Data = (await seed2Resp.json()) as { task_id: string };
    const targetTaskId = seed2Data.task_id;

    await act(async () => {
      fireEvent.change(screen.getByTestId(`task-link-target-kind-${taskId}`), {
        target: { value: 'task' },
      });
      fireEvent.change(screen.getByTestId(`task-link-target-id-${taskId}`), {
        target: { value: targetTaskId },
      });
      fireEvent.change(screen.getByTestId(`task-link-kind-${taskId}`), {
        target: { value: 'relates_to' },
      });
      // Submit the form — real HTTP -> real SQLite write
      const form = screen.getByTestId(`task-link-form-${taskId}`);
      fireEvent.submit(form);
    });

    // Link badge appears in the rendered UI (came from server response)
    await waitFor(
      () => {
        const badge = screen.queryByTestId(`task-link-badge-${taskId}-task-${targetTaskId}`);
        expect(badge).toBeTruthy();
      },
      { timeout: 10_000 },
    );
  }, TIMEOUT);

  it('resolve and dismiss use strictly separate endpoints (no mixing)', async () => {
    // Proof: resolve uses /resolve, dismiss uses /dismiss — never swapped
    const calls: [string, RequestInit?][] = [];
    const loggingTransport = async (url: string, opts?: RequestInit): Promise<Response> => {
      calls.push([url, opts]);
      return fetch(url, opts);
    };
    const loggingClient = new BffClient(baseUrl, loggingTransport);

    const seedResp = await apiPost(`${baseUrl}/_test/seed-task`, {
      project_key: PROJECT_KEY,
      task_id: `TM-2025-${String(Date.now() + 10).slice(-4)}`,
      kind: 'actionable',
      priority: 'normal',
      status: 'open',
      origin: 'human',
      title: 'Endpoint Separation Task',
    });
    const seedData = (await seedResp.json()) as { task_id: string };
    const taskId = seedData.task_id;

    await act(async () => {
      render(<TaskSlot projectKey={PROJECT_KEY} client={loggingClient} />);
    });

    await waitFor(
      () => expect(screen.queryByTestId(`task-resolve-${taskId}`)).toBeTruthy(),
      { timeout: 10_000 },
    );

    await act(async () => {
      fireEvent.click(screen.getByTestId(`task-resolve-${taskId}`));
    });

    await waitFor(
      () => {
        const resolveCalls = calls.filter(([u, opts]) => opts?.method === 'POST' && u.includes('/resolve'));
        expect(resolveCalls.length).toBeGreaterThan(0);
      },
    );

    const resolveCalls = calls.filter(([u, opts]) => opts?.method === 'POST' && u.includes('/resolve'));
    const dismissCalls = calls.filter(([u, opts]) => opts?.method === 'POST' && u.includes('/dismiss'));
    expect(resolveCalls.length).toBeGreaterThan(0);
    expect(dismissCalls).toHaveLength(0);
  }, TIMEOUT);

  /**
   * AG3-105 r3 finding 1 (AC4 bidirectional reverse view) — REAL backend.
   *
   * Create task A via the UI, link A -> story S and A -> task B through the
   * rendered UI (real HTTP -> real TaskManagement -> real SQLite). Then, on a
   * FRESH load:
   *   - task side: the reverse view of B ("Verlinkende Aufgaben") shows A,
   *   - story side: the DetailInspector reverse view of S ("Verlinkte Aufgaben")
   *     shows A.
   * Both surfaces read via list_tasks_for_target on the real backend — proving
   * the data comes from the DB, not from session state.
   */
  it('reverse view (story S + task B) shows the linking task A after a fresh load (real backend)', async () => {
    const client = new BffClient(baseUrl);

    // Create source A and target B purely through the rendered UI.
    const taskA = await createTaskViaUi(client, `Reverse-A ${Date.now()}`);
    cleanup();
    const taskB = await createTaskViaUi(client, `Reverse-B ${Date.now()}`);

    // Seed a REAL story row so the story-target link passes backend validation
    // (story_target_exists). Test-only seed of real data — no backend stub.
    const storyS = `${PROJECT_PREFIX}-${String(Date.now()).slice(-4)}`;
    const seedStoryResp = await apiPost(`${baseUrl}/_test/seed-story`, {
      project_key: PROJECT_KEY,
      story_number: Number(String(Date.now()).slice(-6)),
      story_display_id: storyS,
      title: 'Reverse-view target story',
      story_type: 'implementation',
    });
    if (!seedStoryResp.ok) {
      throw new Error(`seed-story failed: ${seedStoryResp.status} ${await seedStoryResp.text()}`);
    }

    // Render fresh on A and open its link form.
    cleanup();
    await act(async () => {
      render(<TaskSlot projectKey={PROJECT_KEY} client={new BffClient(baseUrl)} />);
    });
    await waitFor(
      () => expect(screen.queryByTestId(`task-add-link-${taskA}`)).toBeTruthy(),
      { timeout: 10_000 },
    );

    // Link A -> task B (relates_to) through the UI.
    await act(async () => {
      fireEvent.click(screen.getByTestId(`task-add-link-${taskA}`));
    });
    await act(async () => {
      fireEvent.change(screen.getByTestId(`task-link-target-kind-${taskA}`), { target: { value: 'task' } });
      fireEvent.change(screen.getByTestId(`task-link-target-id-${taskA}`), { target: { value: taskB } });
      fireEvent.change(screen.getByTestId(`task-link-kind-${taskA}`), { target: { value: 'relates_to' } });
      fireEvent.submit(screen.getByTestId(`task-link-form-${taskA}`));
    });
    await waitFor(
      () => expect(screen.queryByTestId(`task-link-badge-${taskA}-task-${taskB}`)).toBeTruthy(),
      { timeout: 10_000 },
    );

    // Link A -> story S (relates_to) through the UI.
    await act(async () => {
      fireEvent.click(screen.getByTestId(`task-add-link-${taskA}`));
    });
    await act(async () => {
      fireEvent.change(screen.getByTestId(`task-link-target-kind-${taskA}`), { target: { value: 'story' } });
      fireEvent.change(screen.getByTestId(`task-link-target-id-${taskA}`), { target: { value: storyS } });
      fireEvent.change(screen.getByTestId(`task-link-kind-${taskA}`), { target: { value: 'relates_to' } });
      fireEvent.submit(screen.getByTestId(`task-link-form-${taskA}`));
    });
    await waitFor(
      () => expect(screen.queryByTestId(`task-link-badge-${taskA}-story-${storyS}`)).toBeTruthy(),
      { timeout: 10_000 },
    );

    // ── TASK SIDE: fresh TaskSlot — B's reverse view must list A (from DB read).
    cleanup();
    await act(async () => {
      render(<TaskSlot projectKey={PROJECT_KEY} client={new BffClient(baseUrl)} />);
    });
    await waitFor(
      () => {
        expect(screen.queryByTestId(`task-reverse-link-${taskB}-${taskA}`)).toBeTruthy();
      },
      { timeout: 10_000 },
    );

    // ── STORY SIDE: DetailInspector for S — reverse view must list A.
    cleanup();
    const story: Story = {
      id: storyS, title: 'Reverse-view story', type: 'implementation', status: 'Backlog',
      size: 'M', owner: 'test', repo: 'r', module: 'm', epic: 'e', changeImpact: 'Local',
      conceptQuality: 'High', wave: 1, risk: 'low', criticalPath: false, qaRounds: 0,
      processingTime: '0 min', labels: [], acceptance: [], gates: [], phases: [],
      events: [], dependencies: [],
    };
    await act(async () => {
      render(
        <DetailInspector
          story={story}
          client={new BffClient(baseUrl)}
          projectKey={PROJECT_KEY}
          width={858}
          onClose={() => undefined}
          onResizeStart={() => undefined}
        />,
      );
    });
    await waitFor(
      () => {
        expect(screen.queryByTestId(`inspector-linked-task-${taskA}`)).toBeTruthy();
      },
      { timeout: 10_000 },
    );

    // Hard proof via direct backend reads (real list_tasks_for_target).
    const fromStory = await client.listTasksForTarget(PROJECT_KEY, 'story', storyS);
    expect(fromStory.tasks.some((t) => t.task_id === taskA)).toBe(true);
    const fromTask = await client.listTasksForTarget(PROJECT_KEY, 'task', taskB);
    expect(fromTask.tasks.some((t) => t.task_id === taskA)).toBe(true);
  }, TIMEOUT);
});
