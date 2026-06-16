/**
 * AC10: Real E2E — KPI endpoint round-trip + SSE event delivery
 * against the REAL Python backend (no stubs, real SQLite).
 *
 * Tests:
 *   KPI dimension correctness:
 *   1. GET /kpi/stories with valid mandatory period → 200 EMPTY (fresh project)
 *   2. GET /kpi/stories without period → 400 invalid_kpi_filter (fail-closed)
 *   3. GET /kpi/stories with naive datetime → 400 (fail-closed, timezone required)
 *   4. GET /kpi/stories with unknown param → 400 (fail-closed)
 *   5a-d. All five KPI dimensions respond (EMPTY on fresh project)
 *   6a. guard filter on /kpi/guards → 200 (AC7 server-side filter round-trip)
 *   6b. story_type + story_size on /kpi/stories → 200
 *   6c. guard+pool together → 400 (mutually exclusive, fail-closed)
 *   7. compare_from/compare_to → 200 with comparison_period in body
 *   8. design-tokens → chart.series.series_0..11 (AC8 SSOT)
 *
 *   REAL round-trip with persisted KPI facts (AC10 core):
 *   9. Seed real FactStory row via /_test/seed-kpi-facts
 *   10. GET /kpi/stories → 200 with NON-EMPTY rows (non-zero qa_rounds)
 *   11. Real SSE event: POST /_test/emit-sse-event (kpi topic)
 *       then observe the event delivered over the real SSE stream
 *       within a timeout window (proves the stream is live and event routing works).
 *
 *   SSE topic correctness:
 *   12-14. All three view topic sets open without error (Analytics/Kanban/Graph).
 *
 * Requires real Python + agentkit on PYTHONPATH. Fails loudly on startup.
 */
/// <reference types="node" />
import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import { spawn, type ChildProcess } from 'node:child_process';
import * as path from 'node:path';
import * as http from 'node:http';

const REPO_ROOT = path.join(__dirname, '..', '..', '..', '..', '..');
const PYTHON =
  process.platform === 'win32'
    ? path.join(REPO_ROOT, '.venv', 'Scripts', 'python.exe')
    : path.join(REPO_ROOT, '.venv', 'bin', 'python3');
const HARNESS_PATH = path.join(__dirname, '..', '..', '..', 'tests', 'python_harness.py');
const TIMEOUT = 30_000;
const PROJECT_KEY = 'kpie2etest';

let serverProcess: ChildProcess | null = null;
let baseUrl = '';

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

/** ISO-8601 UTC timestamp N days ago. */
function isoDaysAgo(days: number): string {
  const d = new Date(Date.now() - days * 86400000);
  return d.toISOString().split('.')[0] + 'Z';
}

function isoNow(): string {
  return new Date().toISOString().split('.')[0] + 'Z';
}

/** Build a valid KPI URL with mandatory from/to and optional extra params. */
function kpiUrl(
  dimension: string,
  extra: Record<string, string> = {},
): string {
  const params = new URLSearchParams({
    from: isoDaysAgo(30),
    to: isoNow(),
    ...extra,
  });
  return `${baseUrl}/v1/projects/${PROJECT_KEY}/kpi/${dimension}?${params}`;
}

/**
 * Open an SSE URL and collect the response headers within a 3-second window.
 * Uses Node.js http.get to avoid AbortSignal cross-realm issues in jsdom.
 */
async function probeSseHeaders(url: string): Promise<{ status: number; contentType: string }> {
  return new Promise((resolve, reject) => {
    const req = http.request(url, (res) => {
      const status = res.statusCode ?? 0;
      const contentType = res.headers['content-type'] ?? '';
      res.destroy();
      resolve({ status, contentType });
    });
    req.on('error', reject);
    req.setTimeout(3000, () => {
      req.destroy();
      reject(new Error(`SSE probe timed out for ${url}`));
    });
    req.end();
  });
}

/**
 * Open an SSE stream and collect events until we see an event matching
 * the predicate, or until the timeout fires.
 *
 * Returns the first matching raw event line data (JSON string) or null on timeout.
 */
async function collectSseEvent(
  url: string,
  predicate: (eventType: string, data: string) => boolean,
  timeoutMs: number,
): Promise<{ eventType: string; data: string } | null> {
  return new Promise((resolve) => {
    const req = http.request(url, (res) => {
      let buf = '';
      let currentEventType = 'message';

      const timer = setTimeout(() => {
        req.destroy();
        resolve(null);
      }, timeoutMs);

      res.on('data', (chunk: Buffer) => {
        buf += chunk.toString();
        const lines = buf.split('\n');
        buf = lines.pop() ?? '';

        for (const line of lines) {
          if (line.startsWith('event:')) {
            currentEventType = line.slice('event:'.length).trim();
          } else if (line.startsWith('data:')) {
            const dataStr = line.slice('data:'.length).trim();
            if (predicate(currentEventType, dataStr)) {
              clearTimeout(timer);
              req.destroy();
              resolve({ eventType: currentEventType, data: dataStr });
              return;
            }
            // Reset event type after data line.
            currentEventType = 'message';
          }
        }
      });

      res.on('error', () => {
        clearTimeout(timer);
        resolve(null);
      });
    });

    req.on('error', () => resolve(null));
    req.end();
  });
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

  // Create a project to scope KPI reads.
  const createResp = await fetch(`${baseUrl}/v1/projects`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      key: PROJECT_KEY,
      name: 'KPI E2E Test Project',
      story_id_prefix: 'KPIE2E',
      configuration: {
        repo_url: 'https://github.com/e2e/kpi-test-repo',
        default_branch: 'main',
        default_worker_count: 1,
        repositories: ['https://github.com/e2e/kpi-test-repo'],
      },
    }),
  });
  if (!createResp.ok && createResp.status !== 409) {
    throw new Error(`Project creation failed: ${createResp.status} ${await createResp.text()}`);
  }
}, TIMEOUT);

afterAll(() => {
  serverProcess?.kill();
});

// ── KPI endpoint correctness (fail-closed + shape) ─────────────────────────────

describe('AC10: KPI endpoint real E2E round-trips (no stubs)', () => {
  it('AC10-KPI-1: GET /kpi/stories with valid period → 200 + EMPTY rows (fresh project)', async () => {
    const resp = await fetch(kpiUrl('stories'));
    expect(resp.status).toBe(200);
    const body = await resp.json() as Record<string, unknown>;
    expect(body['project_key']).toBe(PROJECT_KEY);
    expect(body['dimension']).toBe('stories');
    expect(body['status']).toBe('EMPTY');
    expect(Array.isArray(body['rows'])).toBe(true);
  });

  it('AC10-KPI-2: GET /kpi/stories without period → 400 invalid_kpi_filter (fail-closed)', async () => {
    const resp = await fetch(`${baseUrl}/v1/projects/${PROJECT_KEY}/kpi/stories`);
    expect(resp.status).toBe(400);
    const body = await resp.json() as Record<string, unknown>;
    expect(body['error_code']).toBe('invalid_kpi_filter');
  });

  it('AC10-KPI-3: GET /kpi/stories with naive datetime → 400 invalid_kpi_filter', async () => {
    const params = new URLSearchParams({
      from: '2026-01-01T00:00:00',  // naive — no timezone
      to: '2026-01-31T23:59:59',    // naive — no timezone
    });
    const resp = await fetch(`${baseUrl}/v1/projects/${PROJECT_KEY}/kpi/stories?${params}`);
    expect(resp.status).toBe(400);
    const body = await resp.json() as Record<string, unknown>;
    expect(body['error_code']).toBe('invalid_kpi_filter');
  });

  it('AC10-KPI-4: GET /kpi/stories with unknown param → 400 invalid_kpi_filter', async () => {
    const params = new URLSearchParams({
      from: isoDaysAgo(30),
      to: isoNow(),
      not_a_real_param: 'value',
    });
    const resp = await fetch(`${baseUrl}/v1/projects/${PROJECT_KEY}/kpi/stories?${params}`);
    expect(resp.status).toBe(400);
    const body = await resp.json() as Record<string, unknown>;
    expect(body['error_code']).toBe('invalid_kpi_filter');
  });

  it('AC10-KPI-5a: GET /kpi/guards → 200 EMPTY', async () => {
    const resp = await fetch(kpiUrl('guards'));
    expect(resp.status).toBe(200);
    const body = await resp.json() as Record<string, unknown>;
    expect(body['dimension']).toBe('guards');
    expect(body['status']).toBe('EMPTY');
  });

  it('AC10-KPI-5b: GET /kpi/pools → 200 EMPTY', async () => {
    const resp = await fetch(kpiUrl('pools'));
    expect(resp.status).toBe(200);
    const body = await resp.json() as Record<string, unknown>;
    expect(body['dimension']).toBe('pools');
    expect(body['status']).toBe('EMPTY');
  });

  it('AC10-KPI-5c: GET /kpi/pipeline → 200 EMPTY', async () => {
    const resp = await fetch(kpiUrl('pipeline'));
    expect(resp.status).toBe(200);
    const body = await resp.json() as Record<string, unknown>;
    expect(body['dimension']).toBe('pipeline');
    expect(body['status']).toBe('EMPTY');
  });

  it('AC10-KPI-5d: GET /kpi/corpus → 200 EMPTY', async () => {
    const resp = await fetch(kpiUrl('corpus'));
    expect(resp.status).toBe(200);
    const body = await resp.json() as Record<string, unknown>;
    expect(body['dimension']).toBe('corpus');
    expect(body['status']).toBe('EMPTY');
  });

  it('AC10-KPI-6a: AC7 guard filter on /kpi/guards dimension → 200', async () => {
    // guard entity filter is accepted server-side on the guards dimension (AC7).
    const resp = await fetch(kpiUrl('guards', { guard: 'test-guard-id' }));
    expect(resp.status).toBe(200);
    const body = await resp.json() as Record<string, unknown>;
    expect(body['dimension']).toBe('guards');
    expect(body['status']).toBe('EMPTY');
  });

  it('AC10-KPI-6b: AC7 story_type + story_size filters on /kpi/stories → 200', async () => {
    const resp = await fetch(kpiUrl('stories', {
      story_type: 'implementation',
      story_size: 'M',
    }));
    expect(resp.status).toBe(200);
    const body = await resp.json() as Record<string, unknown>;
    expect(body['status']).toBe('EMPTY');
  });

  it('AC10-KPI-6c: AC7 guard+pool together → 400 (mutually exclusive, fail-closed)', async () => {
    // Proves fail-closed: backend rejects guard+pool in the same request.
    const resp = await fetch(kpiUrl('guards', { guard: 'g1', pool: 'p1' }));
    expect(resp.status).toBe(400);
    const body = await resp.json() as Record<string, unknown>;
    expect(body['error_code']).toBe('invalid_kpi_filter');
  });

  it('AC10-KPI-7: compare_from/compare_to accepted → 200 with comparison_period in body', async () => {
    const resp = await fetch(kpiUrl('stories', {
      compare_from: isoDaysAgo(60),
      compare_to: isoDaysAgo(31),
    }));
    expect(resp.status).toBe(200);
    const body = await resp.json() as Record<string, unknown>;
    expect(body['comparison_period']).toBeDefined();
  });

  it('AC10-KPI-8: design-tokens → 200 with chart.series.series_0..11 (AC8 SSOT)', async () => {
    const resp = await fetch(`${baseUrl}/v1/projects/${PROJECT_KEY}/kpi/design-tokens`);
    expect(resp.status).toBe(200);
    const body = await resp.json() as Record<string, unknown>;
    const chart = body['chart'] as Record<string, unknown> | undefined;
    expect(chart).toBeDefined();
    const series = chart?.['series'] as Record<string, string> | undefined;
    expect(series).toBeDefined();
    for (let i = 0; i <= 11; i++) {
      expect(series?.[`series_${i}`]).toMatch(/^#[0-9a-fA-F]{6}$/);
    }
  });
});

// ── REAL round-trip: seed facts → non-empty endpoint → observe SSE event ───────

describe('AC10: Real KPI facts persistence + SSE event delivery (core AC10)', () => {
  // Use timestamps strictly inside the [from, to) window — the isoNow() upper
  // bound is exclusive, and sub-second precision could otherwise push a row past it.
  const fiveMinAgo = new Date(Date.now() - 5 * 60_000).toISOString().split('.')[0] + 'Z';
  const periodStart = isoDaysAgo(7);
  const periodEnd = isoDaysAgo(1);

  it('AC10-SEED-1: seed real facts for EVERY consumed dimension via /_test/seed-kpi-facts', async () => {
    // E7: the Analytics view consumes stories/guards/pools/pipeline/corpus —
    // seed REAL rows for ALL of them so every /kpi/* read is non-empty.
    const seedResp = await fetch(`${baseUrl}/_test/seed-kpi-facts`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        project_key: PROJECT_KEY,
        facts: [
          {
            story_id: 'KPIE2E-001', story_type: 'implementation', story_size: 'M',
            story_mode: 'standard', started_at: fiveMinAgo, completed_at: fiveMinAgo,
            qa_rounds: 5, compaction_count: 1, llm_call_count: 42, adversarial_findings: 2,
            adversarial_tests_created: 3, files_changed: 7, feedback_converged: true,
            phase_setup_ms: 1200, phase_implementation_ms: 45000, phase_closure_ms: 3000,
            are_gate_status: 'PASS',
          },
        ],
        guards: [
          {
            guard_id: 'no_competing_mode', period_start: periodStart, period_end: periodEnd,
            invocation_count: 12, violation_count: 3,
          },
        ],
        pools: [
          {
            llm_role: 'worker', period_start: periodStart, period_end: periodEnd,
            call_count: 99, token_input_total: 1000, token_output_total: 500, avg_latency_ms: 1200,
          },
        ],
        pipeline: [
          {
            period_start: periodStart, period_end: periodEnd,
            stories_completed: 7, stories_escalated: 1, avg_qa_rounds: 2.5,
            avg_phase_implementation_ms: 40000,
          },
        ],
        corpus: [
          {
            period_start: periodStart, period_end: periodEnd,
            incidents_recorded: 8, patterns_promoted: 3, checks_approved: 2,
          },
        ],
      }),
    });
    expect(seedResp.status).toBe(200);
    const seedBody = await seedResp.json() as Record<string, unknown>;
    // 1 story + 1 guard + 1 pool + 1 pipeline + 1 corpus = 5 rows persisted.
    expect(seedBody['seeded']).toBe(5);
  });

  it('AC10-SEED-2: ALL consumed /kpi/* dimensions read NON-EMPTY after seeding', async () => {
    // stories
    const storiesBody = await (await fetch(kpiUrl('stories'))).json() as Record<string, unknown>;
    expect(storiesBody['status']).toBe('OK');
    const storyRows = storiesBody['rows'] as Array<Record<string, unknown>>;
    expect(storyRows.find((r) => r['story_id'] === 'KPIE2E-001')?.['qa_rounds']).toBe(5);

    // guards
    const guardsBody = await (await fetch(kpiUrl('guards'))).json() as Record<string, unknown>;
    expect(guardsBody['status']).toBe('OK');
    expect((guardsBody['rows'] as unknown[]).length).toBeGreaterThan(0);

    // pools
    const poolsBody = await (await fetch(kpiUrl('pools'))).json() as Record<string, unknown>;
    expect(poolsBody['status']).toBe('OK');
    expect((poolsBody['rows'] as unknown[]).length).toBeGreaterThan(0);

    // pipeline
    const pipelineBody = await (await fetch(kpiUrl('pipeline'))).json() as Record<string, unknown>;
    expect(pipelineBody['status']).toBe('OK');
    expect((pipelineBody['rows'] as unknown[]).length).toBeGreaterThan(0);

    // corpus
    const corpusBody = await (await fetch(kpiUrl('corpus'))).json() as Record<string, unknown>;
    expect(corpusBody['status']).toBe('OK');
    expect((corpusBody['rows'] as unknown[]).length).toBeGreaterThan(0);
  });

  it('AC10-SSE-RESYNC: kpi event observed on stream AND the subsequent KPI read reflects new data', async () => {
    // 1) Baseline read of the stories dimension.
    const beforeBody = await (await fetch(kpiUrl('stories'))).json() as Record<string, unknown>;
    const beforeRows = beforeBody['rows'] as Array<Record<string, unknown>>;
    const beforeCount = beforeRows.length;

    // 2) Persist NEW backend data (a second story) — this is the state change the
    //    event tells the frontend to re-sync to.
    const seedResp = await fetch(`${baseUrl}/_test/seed-kpi-facts`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        project_key: PROJECT_KEY,
        facts: [
          {
            story_id: 'KPIE2E-002', story_type: 'implementation', story_size: 'L',
            story_mode: 'standard', started_at: fiveMinAgo, completed_at: fiveMinAgo,
            qa_rounds: 9, compaction_count: 0, llm_call_count: 70, adversarial_findings: 1,
            adversarial_tests_created: 4, files_changed: 12, feedback_converged: true,
            phase_setup_ms: 1500, phase_implementation_ms: 60000, phase_closure_ms: 3500,
            are_gate_status: 'PASS',
          },
        ],
      }),
    });
    expect(seedResp.status).toBe(200);

    // 3) Emit a real kpi SSE event (payload.topic="kpi" routes to the kpi topic).
    const emitResp = await fetch(`${baseUrl}/_test/emit-sse-event`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        project_key: PROJECT_KEY,
        event_type: 'kpi_refresh',
        payload: { topic: 'kpi', reason: 'e2e-resync' },
      }),
    });
    expect(emitResp.status).toBe(200);

    // 4) Observe the event over the REAL SSE stream (max 5s; stream polls ~1s).
    const sseUrl = `${baseUrl}/v1/projects/${PROJECT_KEY}/events?topics=kpi%2Ctelemetry%2Cfailure_corpus`;
    const received = await collectSseEvent(sseUrl, (eventType) => eventType === 'kpi', 5000);
    expect(received).not.toBeNull();
    expect(received?.eventType).toBe('kpi');
    if (received) {
      const data = JSON.parse(received.data) as Record<string, unknown>;
      expect(data['project_key']).toBe(PROJECT_KEY);
    }

    // 5) The re-sync (fresh initial-GET the event triggers) now returns CHANGED
    //    data — the new KPIE2E-002 story is present and the row count grew.
    const afterBody = await (await fetch(kpiUrl('stories'))).json() as Record<string, unknown>;
    const afterRows = afterBody['rows'] as Array<Record<string, unknown>>;
    expect(afterRows.length).toBe(beforeCount + 1);
    const newRow = afterRows.find((r) => r['story_id'] === 'KPIE2E-002');
    expect(newRow).toBeDefined();
    expect(newRow?.['qa_rounds']).toBe(9);
  }, 15_000);
});

// ── SSE stream topic correctness ───────────────────────────────────────────────

describe('AC10: SSE stream real E2E (no stubs, AC3/AC4/AC5)', () => {
  it('AC10-SSE-1: GET /events?topics=kpi,telemetry,failure_corpus → 200 text/event-stream', async () => {
    const { status, contentType } = await probeSseHeaders(
      `${baseUrl}/v1/projects/${PROJECT_KEY}/events?topics=kpi%2Ctelemetry%2Cfailure_corpus`,
    );
    expect(status).toBe(200);
    expect(contentType).toContain('text/event-stream');
  });

  it('AC10-SSE-2: GET /events?topics=stories,phases → 200 text/event-stream (Kanban topics)', async () => {
    const { status, contentType } = await probeSseHeaders(
      `${baseUrl}/v1/projects/${PROJECT_KEY}/events?topics=stories%2Cphases`,
    );
    expect(status).toBe(200);
    expect(contentType).toContain('text/event-stream');
  });

  it('AC10-SSE-3: GET /events?topics=planning → 200 text/event-stream (Graph topics)', async () => {
    const { status, contentType } = await probeSseHeaders(
      `${baseUrl}/v1/projects/${PROJECT_KEY}/events?topics=planning`,
    );
    expect(status).toBe(200);
    expect(contentType).toContain('text/event-stream');
  });
});
