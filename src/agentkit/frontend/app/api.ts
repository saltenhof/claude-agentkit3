import type { ExecutionInputSnapshot, ExecutionLimits, DependencyEdge } from './contexts/execution_planning/types';
import type { HubSession, HubStatusSnapshot } from './contexts/multi_llm_hub/types';
import type { ProjectModeLock, ProjectSummary, StoryCounters } from './contexts/project_management/types';
import type { StoryDetail, StorySummary } from './contexts/story_context_manager/types';
import type {
  TakeoverApprovalRequest,
  TakeoverApprovalsResponse,
  TakeoverMutationResult,
  TakeoverRequestContext,
} from './contexts/story_context_manager/takeoverTypes';

export class ApiError extends Error {
  readonly status: number;
  readonly errorCode: string;
  readonly correlationId?: string;

  constructor(message: string, status: number, errorCode: string, correlationId?: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.errorCode = errorCode;
    this.correlationId = correlationId;
  }
}

export interface LoginResult {
  csrf_token: string;
  status: string;
}

interface ApiClientOptions {
  getCsrfToken: () => string | null;
  onUnauthorized: () => void;
}

export class ApiClient {
  private readonly getCsrfToken: () => string | null;
  private readonly onUnauthorized: () => void;

  constructor(options: ApiClientOptions) {
    this.getCsrfToken = options.getCsrfToken;
    this.onUnauthorized = options.onUnauthorized;
  }

  async login(username: string, password: string): Promise<LoginResult> {
    return this.request<LoginResult>('/v1/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
      skipCsrf: true,
    });
  }

  async logout(): Promise<void> {
    await this.request('/v1/auth/logout', {
      method: 'POST',
      body: JSON.stringify({}),
    });
  }

  async projects(): Promise<ProjectSummary[]> {
    const payload = await this.request<{ projects: ProjectSummary[] }>('/v1/projects');
    return payload.projects;
  }

  async stories(projectKey: string): Promise<StorySummary[]> {
    const payload = await this.request<{ stories: StorySummary[] }>(
      `/v1/projects/${encodeURIComponent(projectKey)}/stories`,
    );
    return payload.stories;
  }

  async story(projectKey: string, storyId: string): Promise<StoryDetail> {
    return this.request<StoryDetail>(
      `/v1/projects/${encodeURIComponent(projectKey)}/stories/${encodeURIComponent(storyId)}`,
    );
  }

  async counters(projectKey: string): Promise<StoryCounters> {
    const payload = await this.request<{ story_counters: StoryCounters }>(
      `/v1/projects/${encodeURIComponent(projectKey)}/stories/counters`,
    );
    return payload.story_counters;
  }

  async modeLock(projectKey: string): Promise<ProjectModeLock> {
    const payload = await this.request<{ mode_lock: ProjectModeLock }>(
      `/v1/projects/${encodeURIComponent(projectKey)}/mode-lock`,
    );
    return payload.mode_lock;
  }

  async dependencyGraph(projectKey: string): Promise<DependencyEdge[]> {
    const payload = await this.request<{ dependencies: DependencyEdge[] }>(
      `/v1/projects/${encodeURIComponent(projectKey)}/planning/dependency-graph`,
    );
    return payload.dependencies;
  }

  async executionInput(projectKey: string): Promise<ExecutionInputSnapshot> {
    return this.request<ExecutionInputSnapshot>(
      `/v1/projects/${encodeURIComponent(projectKey)}/execution-input/snapshot`,
    );
  }

  async executionLimits(projectKey: string): Promise<ExecutionLimits> {
    const payload = await this.request<{ execution_limits: ExecutionLimits }>(
      `/v1/projects/${encodeURIComponent(projectKey)}/execution-input/limits`,
    );
    return payload.execution_limits;
  }

  async hubStatus(): Promise<HubStatusSnapshot> {
    return this.request<HubStatusSnapshot>('/v1/hub/status');
  }

  async hubSessions(): Promise<HubSession[]> {
    const payload = await this.request<{ sessions: HubSession[] }>('/v1/hub/sessions');
    return payload.sessions;
  }

  async takeoverApprovals(): Promise<TakeoverApprovalsResponse> {
    return this.request<TakeoverApprovalsResponse>('/v1/governance/takeover-approvals');
  }

  async requestStoryRunTakeover(
    context: TakeoverRequestContext,
    reason: string,
  ): Promise<TakeoverMutationResult> {
    return this.request<TakeoverMutationResult>(
      `/v1/project-edge/story-runs/${encodeURIComponent(context.run_id)}/ownership/takeover-request`,
      {
        method: 'POST',
        headers: { 'X-Project-Key': context.project_key },
        body: JSON.stringify({
          project_key: context.project_key,
          story_id: context.story_id,
          session_id: context.session_id,
          principal_type: 'human_cli',
          worktree_roots: context.worktree_roots,
          reason,
          op_id: makeOpId(),
        }),
      },
    );
  }

  async confirmStoryRunTakeover(approval: TakeoverApprovalRequest): Promise<TakeoverMutationResult> {
    return this.request<TakeoverMutationResult>(
      `/v1/project-edge/story-runs/${encodeURIComponent(approval.run_id)}/ownership/takeover-confirm`,
      {
        method: 'POST',
        headers: { 'X-Project-Key': approval.project_key },
        body: JSON.stringify({
          project_key: approval.project_key,
          story_id: approval.story_id,
          challenge_id: approval.challenge_id,
          reason: approval.reason,
          op_id: makeOpId(),
        }),
      },
    );
  }

  async denyStoryRunTakeover(approval: TakeoverApprovalRequest, reason: string): Promise<TakeoverMutationResult> {
    return this.request<TakeoverMutationResult>(
      `/v1/project-edge/story-runs/${encodeURIComponent(approval.run_id)}/ownership/takeover-deny`,
      {
        method: 'POST',
        headers: { 'X-Project-Key': approval.project_key },
        body: JSON.stringify({
          project_key: approval.project_key,
          story_id: approval.story_id,
          approval_id: approval.approval_id,
          reason,
          op_id: makeOpId(),
        }),
      },
    );
  }

  async approveStory(projectKey: string, storyId: string): Promise<StorySummary> {
    return this.storyCommand(projectKey, storyId, 'approve', {});
  }

  async rejectStory(projectKey: string, storyId: string): Promise<StorySummary> {
    return this.storyCommand(projectKey, storyId, 'reject', {});
  }

  async cancelStory(projectKey: string, storyId: string, reason: string): Promise<StorySummary> {
    return this.storyCommand(projectKey, storyId, 'cancel', { reason });
  }

  async updateStoryFields(projectKey: string, storyId: string, updates: Record<string, unknown>): Promise<StorySummary> {
    return this.request<StorySummary>(
      `/v1/projects/${encodeURIComponent(projectKey)}/stories/${encodeURIComponent(storyId)}`,
      {
        method: 'PATCH',
        body: JSON.stringify({ ...updates, op_id: makeOpId() }),
      },
    );
  }

  private async storyCommand(
    projectKey: string,
    storyId: string,
    command: 'approve' | 'reject' | 'cancel',
    body: Record<string, unknown>,
  ): Promise<StorySummary> {
    return this.request<StorySummary>(
      `/v1/projects/${encodeURIComponent(projectKey)}/stories/${encodeURIComponent(storyId)}/${command}`,
      {
        method: 'POST',
        body: JSON.stringify({ ...body, op_id: makeOpId() }),
      },
    );
  }

  private async request<T = unknown>(
    path: string,
    init: RequestInit & { skipCsrf?: boolean } = {},
  ): Promise<T> {
    const controller = new AbortController();
    const timeout = globalThis.setTimeout(() => controller.abort(), 12000);
    const headers = new Headers(init.headers);
    headers.set('Accept', 'application/json');
    headers.set('X-Correlation-Id', makeCorrelationId());
    if (init.body !== undefined) {
      headers.set('Content-Type', 'application/json');
    }
    const method = (init.method ?? 'GET').toUpperCase();
    const csrfToken = this.getCsrfToken();
    if (!init.skipCsrf && csrfToken !== null && ['POST', 'PUT', 'PATCH', 'DELETE'].includes(method)) {
      headers.set('X-CSRF-Token', csrfToken);
    }

    let response: Response;
    try {
      response = await fetch(path, {
        ...init,
        method,
        headers,
        credentials: 'include',
        signal: controller.signal,
      });
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') {
        throw new ApiError('Backend request timed out', 504, 'request_timeout');
      }
      throw err;
    } finally {
      globalThis.clearTimeout(timeout);
    }

    if (response.status === 204) {
      return undefined as T;
    }

    const raw = await response.text();
    const payload = raw ? parseJson(raw) : {};

    if (!response.ok) {
      const errorPayload = payload as Partial<{ error: string; error_code: string; correlation_id: string }>;
      const error = new ApiError(
        errorPayload.error ?? response.statusText,
        response.status,
        errorPayload.error_code ?? 'http_error',
        errorPayload.correlation_id,
      );
      if (response.status === 401) {
        this.onUnauthorized();
      }
      throw error;
    }

    return payload as T;
  }
}

function parseJson(raw: string): unknown {
  try {
    return JSON.parse(raw) as unknown;
  } catch {
    throw new ApiError('Backend returned invalid JSON', 502, 'invalid_json_from_backend');
  }
}

function makeCorrelationId(): string {
  return `ui-${makeId()}`;
}

function makeOpId(): string {
  return `op-${makeId()}`;
}

function makeId(): string {
  const cryptoApi = globalThis.crypto;
  if (typeof cryptoApi?.randomUUID === 'function') {
    return cryptoApi.randomUUID().replaceAll('-', '');
  }
  if (typeof cryptoApi?.getRandomValues === 'function') {
    const bytes = cryptoApi.getRandomValues(new Uint8Array(16));
    return Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
  }
  return `${Date.now().toString(36)}${makeIdFallbackCounter()}`;
}

let fallbackCounter = 0;

function makeIdFallbackCounter(): string {
  fallbackCounter = (fallbackCounter + 1) % Number.MAX_SAFE_INTEGER;
  return fallbackCounter.toString(36);
}
