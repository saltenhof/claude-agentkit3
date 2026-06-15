/**
 * Shared test transport: a real FetchTransport that serves the captured real
 * backend wire shapes by URL pattern. Components under test consume the REAL
 * BffClient (with its real normalization) against this transport — no hollow
 * client-only assertions.
 */
import { vi } from 'vitest';
import {
  REAL_SEARCH_RESPONSE,
  REAL_PUBLIC_LIST_RESPONSE,
  REAL_PUBLIC_DETAIL_RESPONSE,
  REAL_PROJECTS_RESPONSE,
  REAL_COUNTERS_RESPONSE,
  REAL_MODE_LOCK_RESPONSE,
  REAL_LIMITS_RESPONSE,
  REAL_FLOW_RESPONSE,
  REAL_COVERAGE_ACCEPTANCE_RESPONSE,
  REAL_ARE_EVIDENCE_RESPONSE,
} from './realShapes.fixture';

function jsonResponse(status: number, body: unknown): Response {
  const resp = {
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
    clone: () => resp,
  };
  return resp as unknown as Response;
}

export interface FixtureTransportOptions {
  /** Force a status/body for matching URLs (e.g. inject a backend rejection). */
  override?: (url: string, options?: RequestInit) => { status: number; body: unknown } | null;
}

/**
 * Build a transport that resolves the real read-model fixtures by URL.
 * Mutation endpoints (approve/reject/cancel) resolve 200 by default; pass an
 * `override` to inject a rejection (e.g. invalid_transition) for those URLs.
 */
export function makeFixtureTransport(opts: FixtureTransportOptions = {}): ReturnType<typeof vi.fn> {
  return vi.fn().mockImplementation((url: string, options?: RequestInit) => {
    const forced = opts.override?.(url, options);
    if (forced) return Promise.resolve(jsonResponse(forced.status, forced.body));

    if (url.includes('/stories/search')) return Promise.resolve(jsonResponse(200, REAL_SEARCH_RESPONSE));
    if (url.endsWith('/mode-lock')) return Promise.resolve(jsonResponse(200, REAL_MODE_LOCK_RESPONSE));
    if (url.endsWith('/stories/counters')) return Promise.resolve(jsonResponse(200, REAL_COUNTERS_RESPONSE));
    if (url.endsWith('/execution-input/limits')) return Promise.resolve(jsonResponse(200, REAL_LIMITS_RESPONSE));
    if (url.endsWith('/flow')) return Promise.resolve(jsonResponse(200, REAL_FLOW_RESPONSE));
    if (url.endsWith('/acceptance')) return Promise.resolve(jsonResponse(200, REAL_COVERAGE_ACCEPTANCE_RESPONSE));
    if (url.endsWith('/are-evidence')) return Promise.resolve(jsonResponse(200, REAL_ARE_EVIDENCE_RESPONSE));
    if (url.endsWith('/v1/projects')) return Promise.resolve(jsonResponse(200, REAL_PROJECTS_RESPONSE));
    // story detail: /v1/projects/{key}/stories/{id} (no further suffix)
    if (/\/v1\/projects\/[^/]+\/stories\/[^/]+$/.test(url) && (options?.method ?? 'GET') === 'GET') {
      return Promise.resolve(jsonResponse(200, REAL_PUBLIC_DETAIL_RESPONSE));
    }
    if (url.endsWith('/stories')) return Promise.resolve(jsonResponse(200, REAL_PUBLIC_LIST_RESPONSE));
    // mutation endpoints
    if (/\/(approve|reject|cancel)$/.test(url)) return Promise.resolve(jsonResponse(200, {}));
    return Promise.resolve(jsonResponse(404, { error_code: 'not_found' }));
  });
}

export { jsonResponse };
