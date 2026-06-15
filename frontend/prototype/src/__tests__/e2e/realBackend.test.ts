/**
 * AC14: Real E2E — full create -> mutate -> public read-back round-trip against
 * the REAL Python backend THROUGH THE PUBLIC BFF paths the UI uses (no stubs,
 * real DB).
 *
 * E4 (AG3-093 R4) — PUBLIC CREATE investigation result:
 *   The public create path (POST /v1/projects/{key}/stories ->
 *   BffClient.createStory) is NON-BYPASSABLE: it requires a typed, self-
 *   validating `reconciliation` evidence block (FK-21 §21.4/§21.12,
 *   src/agentkit/story_context_manager/http/routes.py:_enforce_reconciliation).
 *   This is NOT a foreign-owner blocker we must work around: a clean,
 *   no-conflict reconciliation outcome (weaviate_ready=true, zero hits,
 *   verdict=PASS) is a VALID ReconciliationEvidence
 *   (src/agentkit/story_creation/reconciliation_evidence.py). Supplying that
 *   typed evidence is exactly what the gate asks for — proof the reconciliation
 *   ran — so this e2e drives the REAL public create end to end.
 *
 * Two-StoryService split (Codex R3 adjudication, ACCEPTED):
 *   - create + approve/reject/cancel + SEARCH go through
 *     agentkit.story_context_manager (the `stories` table). The live approval
 *     status (Backlog/Approved/Cancelled) lives ONLY here.
 *   - GET /v1/projects/{key}/stories and /stories/{id} go through
 *     agentkit.story.service.StoryService (the `story_contexts` table) and expose
 *     a runtime `lifecycle_status`, NOT the approval status. Exposing approval
 *     status on that path is a foreign-owner backend concern that does NOT block
 *     this story.
 *
 * Therefore the honest PUBLIC read-back of the APPROVAL status is the PUBLIC
 * search endpoint (BffClient.searchStories), whose story_to_wire_summary carries
 * the live `status` from the SAME `stories` store the create/mutation path
 * writes. Every read-back here is via a public BffClient method against the real
 * ControlPlaneApplication.
 *
 * NOT skipped. Requires Python + agentkit on PYTHONPATH. Fails loudly on startup
 * failure.
 */
/// <reference types="node" />
import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import { spawn, type ChildProcess } from 'node:child_process';
import * as path from 'node:path';
import { BffClient } from '../../foundation/bff/client';

const REPO_ROOT = path.join(__dirname, '..', '..', '..', '..', '..');
const PYTHON =
  process.platform === 'win32'
    ? path.join(REPO_ROOT, '.venv', 'Scripts', 'python.exe')
    : path.join(REPO_ROOT, '.venv', 'bin', 'python3');
const HARNESS_PATH = path.join(__dirname, '..', '..', '..', 'tests', 'python_harness.py');
const TIMEOUT = 30_000;

let serverProcess: ChildProcess | null = null;
let baseUrl = '';
let client: BffClient;
let seededStoryId = '';
const PROJECT_KEY = 'e2etest';

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

const REPO = 'https://github.com/e2e/test-repo';

/**
 * A VALID, self-consistent clean reconciliation outcome (no similar stories,
 * Weaviate ran, verdict PASS). This is exactly the typed proof the non-bypassable
 * create gate (FK-21 §21.4/§21.12) requires — not a bypass.
 */
function cleanReconciliation() {
  return {
    weaviate_ready: true,
    total_hits: 0,
    hits_above_threshold: 0,
    candidates_evaluated: 0,
    hits_classified_conflict: 0,
    threshold_value: 0.85,
    verdict: 'PASS',
    story_was_adapted: false,
    participating_repos: [REPO],
  };
}

/** Create a story through the REAL PUBLIC create path (BffClient.createStory). */
async function publicCreate(title: string): Promise<string> {
  const detail = await client.createStory(PROJECT_KEY, {
    op_id: `e2e-create-${title}-${Date.now()}`,
    project_key: PROJECT_KEY,
    title,
    type: 'implementation',
    repos: [REPO],
    module: 'test-module',
    epic: 'E2E Epic',
    owner: 'e2e-test',
    reconciliation: cleanReconciliation(),
  });
  return detail.summary.id;
}

/** PUBLIC read-back of the live approval status via BffClient.searchStories. */
async function publicSearchStatus(storyId: string): Promise<string | undefined> {
  const resp = await client.searchStories(PROJECT_KEY, storyId);
  return resp.stories.find((s) => s.id === storyId)?.status;
}

beforeAll(async () => {
  serverProcess = spawn(PYTHON, [HARNESS_PATH, '0'], {
    stdio: ['ignore', 'pipe', 'pipe'],
    env: { ...process.env },
  });

  let port: string;
  try {
    port = await waitForLine(serverProcess, 15_000);
  } catch (err) {
    serverProcess?.kill();
    throw new Error(`Failed to start Python harness: ${err}`, { cause: err });
  }

  baseUrl = `http://127.0.0.1:${port}`;
  client = new BffClient(baseUrl);

  // Create a real project via the real API (real DB write).
  const createProjectResp = await apiPost(`${baseUrl}/v1/projects`, {
    key: PROJECT_KEY,
    name: 'E2E Test Project',
    story_id_prefix: 'E2ETEST',
    configuration: {
      repo_url: 'https://github.com/e2e/test-repo',
      default_branch: 'main',
      default_worker_count: 1,
      repositories: ['https://github.com/e2e/test-repo'],
    },
  });
  if (!createProjectResp.ok && createProjectResp.status !== 409) {
    throw new Error(`Failed to create project: ${createProjectResp.status} ${await createProjectResp.text()}`);
  }

  // Create the primary story through the REAL PUBLIC create path (no seed,
  // no /_test bypass) — real DB write via POST /v1/projects/{key}/stories.
  seededStoryId = await publicCreate('E2E Test Story');
}, TIMEOUT);

afterAll(() => {
  serverProcess?.kill();
});

describe('AC14: Real E2E round-trip THROUGH THE PUBLIC BFF paths (no stubs, real DB)', () => {
  it('PUBLIC-created story is visible via PUBLIC search and starts as Backlog', async () => {
    const status = await publicSearchStatus(seededStoryId);
    expect(status).toBe('Backlog');
  });

  it('approve via dedicated endpoint -> persisted Approved, read back via PUBLIC search', async () => {
    await client.approveStory(PROJECT_KEY, seededStoryId, `e2e-approve-${Date.now()}`);
    expect(await publicSearchStatus(seededStoryId)).toBe('Approved');
  });

  it('reject (Approved -> Backlog) -> persisted, read back via PUBLIC search', async () => {
    await client.approveStory(PROJECT_KEY, seededStoryId, `e2e-pre-reject-${Date.now()}`).catch(() => undefined);
    await client.rejectStory(PROJECT_KEY, seededStoryId, `e2e-reject-${Date.now()}`);
    expect(await publicSearchStatus(seededStoryId)).toBe('Backlog');
  });

  it('cancel -> persisted Cancelled, read back via PUBLIC search', async () => {
    await client.approveStory(PROJECT_KEY, seededStoryId, `e2e-pre-cancel-${Date.now()}`).catch(() => undefined);
    await client.cancelStory(PROJECT_KEY, seededStoryId, 'E2E cancellation', `e2e-cancel-${Date.now()}`);
    expect(await publicSearchStatus(seededStoryId)).toBe('Cancelled');
  });

  it('full PUBLIC create -> approve -> public read-back cycle on a fresh story', async () => {
    // This proves the ENTIRE cycle through PUBLIC endpoints: create via
    // BffClient.createStory (POST /v1/projects/{key}/stories, real
    // reconciliation gate satisfied with valid evidence), then approve, then
    // read back the persisted approval status via PUBLIC search.
    const freshId = await publicCreate('Fresh Public Story');
    expect(freshId).toBeTruthy();

    expect(await publicSearchStatus(freshId)).toBe('Backlog');
    await client.approveStory(PROJECT_KEY, freshId, `e2e-fresh-approve-${Date.now()}`);
    expect(await publicSearchStatus(freshId)).toBe('Approved');
  });

  it('public-create gate rejects a story WITHOUT reconciliation evidence (fail-closed)', async () => {
    // The non-bypassable gate (FK-21 §21.4/§21.12): create without the typed
    // reconciliation evidence is rejected, proving the path is real, not stubbed.
    const resp = await apiPost(`${baseUrl}/v1/projects/${PROJECT_KEY}/stories`, {
      op_id: `e2e-noevidence-${Date.now()}`,
      project_key: PROJECT_KEY,
      title: 'No Evidence Story',
      type: 'implementation',
      repos: [REPO],
      module: 'm',
      epic: 'E2E',
      owner: 'e2e',
    });
    expect(resp.status).toBe(422);
    const body = (await resp.json()) as { error_code?: string };
    expect(body.error_code).toBe('reconciliation_evidence_missing');
  });

  it('story DATA round-trips through the PUBLIC search read path (real normalization)', async () => {
    // The PUBLIC detail/list endpoints (GET /v1/projects/{key}/stories[/{id}]) read
    // the `story_contexts` runtime projection and expose `lifecycle_status`, NOT the
    // approval status (two-StoryService split, accepted by Codex R3). The honest
    // public DATA + APPROVAL-STATUS round-trip is therefore the PUBLIC search path
    // (BffClient.searchStories), which reads the SAME persisted `stories` store the
    // PUBLIC create + mutation path writes, through the REAL BffClient
    // normalization — a full UI -> public API -> real DB write -> real DB read ->
    // back-into-the-view cycle with no stub at the backend/DB boundary.
    const resp = await client.searchStories(PROJECT_KEY, seededStoryId);
    const story = resp.stories.find((s) => s.id === seededStoryId);
    expect(story).toBeTruthy();
    expect(story?.title).toBe('E2E Test Story');
    expect(story?.type).toBe('implementation');
    expect(story?.module).toBe('test-module');
    expect(story?.epic).toBe('E2E Epic');
    expect(story?.repo).toBe('https://github.com/e2e/test-repo');
    expect(story?.changeImpact).toBeTruthy();
  });

  it('NEVER sends PATCH /v1/.../stories/{id} with a status field', async () => {
    const calls: [string, RequestInit?][] = [];
    const loggingTransport = async (url: string, opts?: RequestInit): Promise<Response> => {
      calls.push([url, opts]);
      return fetch(url, opts);
    };
    const loggingClient = new BffClient(baseUrl, loggingTransport);
    await loggingClient.approveStory(PROJECT_KEY, seededStoryId, `neg-${Date.now()}`).catch(() => undefined);

    const patchWithStatus = calls.filter(([, opts]) => {
      if (opts?.method !== 'PATCH') return false;
      try {
        return 'status' in (JSON.parse(opts.body as string) as Record<string, unknown>);
      } catch {
        return false;
      }
    });
    expect(patchWithStatus).toHaveLength(0);
  });
});
