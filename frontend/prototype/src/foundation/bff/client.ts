// BFF client for the AK3 frontend.
//
// Every method takes project_key. No bare /v1/stories/... paths.
// All story access is project-scoped under /v1/projects/{project_key}/...
// Keep injectable FetchTransport for tests. Default transport hits real relative URLs.
//
// RESPONSE-SHAPE ADAPTATION (AC9/AC14):
//   The real backend exposes TWO different list shapes plus a detail shape, all with
//   snake_case wire field names that differ from the UI types. This module owns the
//   typed normalization from the REAL wire shapes to the UI's Story/StoryListItem types:
//
//   - GET /v1/projects/{key}/stories  (agentkit.story.service.StoryService.list_stories)
//       -> StoryListResponse { project_key, stories: WireStorySummary[] }
//       where WireStorySummary = { story_id, title, story_type, story_size,
//         lifecycle_status, execution_route, ... }  (src/agentkit/story/models.py:60-77)
//   - GET /v1/projects/{key}/stories/search  (story_context_manager search)
//       -> { project_key, stories: WireStoryContextSummary[] }
//       where WireStoryContextSummary = { story_id, title, type, status, size, repos,
//         change_impact, concept_quality, mode, epic, module, owner, wave, ... }
//         (src/agentkit/story_context_manager/wire_adapter.py:37 story_to_wire_summary)
//   - GET /v1/projects/{key}/stories/{id}  (public detail; flat StoryDetail)
//       OR the story_context_manager detail envelope { summary, spec, telemetry, ... }
//
//   These wire shapes were captured empirically against the real ControlPlaneApplication
//   (see src/__tests__/realShapes.fixture.ts), not hand-invented.

import type { Story, StoryStatus, StoryType, StorySize, ChangeImpact, ConceptQuality } from '../../store';

export interface PoolStat {
  pool: 'chatgpt' | 'gemini' | 'grok' | 'qwen' | 'kimi';
  role: string;
  calls: number;
  status: 'PASS' | 'WARNING' | 'FAIL';
}

export interface StoryTelemetry {
  runId: string;
  agentStarts: number;
  incrementCommits: number;
  reviewRequests: number;
  reviewResponses: number;
  reviewCompliant: number;
  llmCalls: number;
  adversarialTests: number;
  webCalls: number;
  tokensIn: number;
  tokensOut: number;
  pools: PoolStat[];
}

export interface GateResult {
  label: string;
  state: 'PASS' | 'WARNING' | 'ERROR';
}

export interface PhaseResult {
  label: string;
  state: 'done' | 'active' | 'blocked' | 'idle' | 'skipped';
  detail: string;
}

export interface StoryEvent {
  time: string;
  type: string;
  detail: string;
  severity: 'info' | 'warning' | 'error';
}

/** Story specification read-model (story_context_manager story_specification wire). */
export interface StorySpecResponse {
  need: string | null;
  solution: string | null;
  acceptance: string[];
  definition_of_done: string[] | null;
  concept_refs: string[] | null;
  guardrail_refs: string[] | null;
  external_sources: string[] | null;
}

/** Evidence read-model (artifacts BC). Null until the producer fills it. */
export interface StoryEvidenceResponse {
  qa_cycle_id: string | null;
  qa_cycle_round: number | null;
  evidence_epoch: string | null;
  evidence_fingerprint: string | null;
  manifest_hash: string | null;
  bundle_entries: Array<{
    authority: string;
    path: string;
    status: string;
  }>;
}

export interface StoryDetailResponse {
  summary: {
    id: string;
    title: string;
    status: string;
    type: string;
    size: string;
    owner: string;
    repo: string;
    module: string;
    epic: string;
    changeImpact: string;
    conceptQuality: string;
    wave: number;
  };
  spec: StorySpecResponse | null;
  evidence: StoryEvidenceResponse | null;
  telemetry: StoryTelemetry | null;
  gates: GateResult[];
  phases: PhaseResult[];
  events: StoryEvent[];
}

/** UI-facing list/search item, normalized from the real wire shapes.
 *
 * Two-StoryService split (Codex R3 adjudication): the approval `status`
 * (Backlog/Approved/Cancelled/...) is carried ONLY by the search adapter
 * (story_context_manager.wire_adapter), and the runtime `executionLifecycle`
 * ('defined', ...) ONLY by the public list/detail adapter
 * (agentkit.story.service). They live in SEPARATE fields and are NEVER
 * cross-cast — `status` is undefined for a pure runtime-list item, and
 * `executionLifecycle` is undefined for a search item.
 */
export interface StoryListItem {
  id: string;
  title: string;
  /** Approval status — ONLY set from the search (approval-bearing) path. */
  status?: StoryStatus;
  /** Runtime execution lifecycle — ONLY set from the public list/detail path. */
  executionLifecycle?: string;
  type: string;
  size: string;
  owner: string;
  repo: string;
  module: string;
  epic: string;
  changeImpact: string;
  conceptQuality: string;
  wave: number;
  mode?: string;
  dependencies?: string[];
}

export interface StoryListResponse {
  stories: StoryListItem[];
}

/** Project counters wire model (frontend-contracts.entity.story_counters). */
export interface StoryCountersResponse {
  story_counters: {
    project_key: string;
    total: number;
    finished: number;
    running: number;
    ready: number;
    queue: number;
    blocked: number;
  };
}

/** Mode-lock wire model (frontend-contracts.entity.project_mode_lock). */
export interface ModeLockResponse {
  mode_lock: {
    project_key: string;
    mode: 'standard' | 'fast' | 'idle';
  };
}

/** Flow substep wire model (frontend-contracts.entity.story_flow_substep). */
export interface FlowSubstepWire {
  substep: string;
  state: string;
  optional: boolean;
  loop_group: string | null;
  loop_position: number | null;
  loop_size: number | null;
}

/** Flow phase wire model (frontend-contracts.entity.story_flow_phase). */
export interface FlowPhaseWire {
  phase: 'setup' | 'exploration' | 'implementation' | 'closure';
  state: string;
  state_reason: string | null;
  iteration: number | null;
  iteration_loop_group: string | null;
  substeps: FlowSubstepWire[];
}

/** Flow snapshot wire model (frontend-contracts.entity.story_flow_snapshot). */
export interface StoryFlowResponse {
  story_flow_snapshot: {
    story_id: string;
    mode: 'standard' | 'fast';
    phases: FlowPhaseWire[];
  };
}

/** Coverage acceptance wire model (frontend-contracts.entity.story_coverage_acceptance). */
export interface CoverageAcceptanceResponse {
  story_coverage_acceptance: {
    story_id: string;
    project_key: string;
    acceptance_criteria: string[];
    linked_requirements: string[];
  };
}

/** ARE evidence wire model (frontend-contracts.entity.story_are_evidence). */
export interface AreEvidenceResponse {
  story_are_evidence: {
    story_id: string;
    project_key: string;
    linked_requirements: Array<{
      are_item_id: string;
      kind: string;
      coverage_status: string;
      evidence_paths: string[];
    }>;
  };
}

/** Execution-limits wire model (frontend-contracts.entity.execution_limits). */
export interface ExecutionLimitsResponse {
  execution_limits: {
    project_key: string;
    repo_parallel_cap: number;
    merge_risk_cap: number;
    max_parallel_agent_cap: number;
    llm_pool_cap: number;
    ci_capacity_cap: number;
  };
}

/** UI-facing project item, normalized from the real project_summary wire shape. */
export interface ProjectItem {
  key: string;
  name: string;
  status: 'active' | 'archived';
}

export interface ProjectListResponse {
  projects: ProjectItem[];
}

/** A required read failed: carries the parsed error_code for the FAIL-CLOSED error pill. */
export class BffReadError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly errorCode: string,
  ) {
    super(message);
    this.name = 'BffReadError';
  }
}

// ── Raw wire shapes (snake_case, exactly as the real backend emits) ──────────

interface WireStorySummary {
  // agentkit.story.models.StorySummary (public list/detail)
  story_id?: string;
  title?: string;
  story_type?: string;
  story_size?: string;
  lifecycle_status?: string;
  execution_route?: string;
  participating_repos?: string[];
  // story_context_manager.wire_adapter.story_to_wire_summary (search/fields)
  type?: string;
  status?: string;
  size?: string;
  repos?: string[];
  change_impact?: string;
  concept_quality?: string;
  mode?: string | null;
  epic?: string;
  module?: string;
  owner?: string;
  wave?: number;
  dependencies?: string[];
  // common fallbacks
  id?: string;
}

// ── Normalization helpers ────────────────────────────────────────────────────

function str(value: unknown, fallback = ''): string {
  return typeof value === 'string' ? value : fallback;
}

function num(value: unknown, fallback = 0): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback;
}

function firstRepo(item: WireStorySummary): string {
  const repos = item.repos ?? item.participating_repos;
  return Array.isArray(repos) && repos.length > 0 ? str(repos[0]) : '';
}

const APPROVAL_STATUSES: readonly StoryStatus[] = [
  'Backlog',
  'Approved',
  'In Progress',
  'Done',
  'Cancelled',
];

/** Parse a wire approval-status string into the typed union, or undefined. */
function approvalStatus(raw: unknown): StoryStatus | undefined {
  return typeof raw === 'string' && (APPROVAL_STATUSES as readonly string[]).includes(raw)
    ? (raw as StoryStatus)
    : undefined;
}

/** Fields shared by both list and search wire summaries. */
function commonSummaryFields(item: WireStorySummary): Omit<StoryListItem, 'status' | 'executionLifecycle'> {
  return {
    id: str(item.story_id ?? item.id),
    title: str(item.title),
    type: str(item.type ?? item.story_type),
    size: str(item.size ?? item.story_size),
    owner: str(item.owner),
    repo: firstRepo(item),
    module: str(item.module),
    epic: str(item.epic),
    changeImpact: str(item.change_impact),
    conceptQuality: str(item.concept_quality),
    wave: num(item.wave),
    mode: typeof item.mode === 'string' ? item.mode : undefined,
    dependencies: Array.isArray(item.dependencies) ? item.dependencies.map((d) => str(d)) : [],
  };
}

/**
 * Normalize a SEARCH wire summary (story_context_manager.wire_adapter). This is
 * the approval-bearing public read path: its `status` is the live approval
 * status (Backlog/Approved/Cancelled/...). Runtime lifecycle is NOT present here.
 */
export function normalizeSearchSummary(raw: unknown): StoryListItem {
  const item = (raw ?? {}) as WireStorySummary;
  return { ...commonSummaryFields(item), status: approvalStatus(item.status) };
}

/**
 * Normalize a PUBLIC LIST wire summary (agentkit.story.service). This path
 * carries the runtime `lifecycle_status`, NOT the approval status. The runtime
 * value is mapped into `executionLifecycle` and is NEVER cast into `status`.
 */
export function normalizeListSummary(raw: unknown): StoryListItem {
  const item = (raw ?? {}) as WireStorySummary;
  const lifecycle = typeof item.lifecycle_status === 'string' ? item.lifecycle_status : undefined;
  return { ...commonSummaryFields(item), executionLifecycle: lifecycle };
}

function normalizeSearchList(raw: Record<string, unknown>): StoryListResponse {
  const stories = Array.isArray(raw['stories']) ? raw['stories'] : [];
  return { stories: stories.map(normalizeSearchSummary) };
}

function normalizeStoryList(raw: Record<string, unknown>): StoryListResponse {
  const stories = Array.isArray(raw['stories']) ? raw['stories'] : [];
  return { stories: stories.map(normalizeListSummary) };
}

function normalizeProjectList(raw: Record<string, unknown>): ProjectListResponse {
  const projects = Array.isArray(raw['projects']) ? raw['projects'] : [];
  return {
    projects: projects.map((p) => {
      const obj = (p ?? {}) as Record<string, unknown>;
      const status = str(obj['status'], 'active');
      return {
        key: str(obj['project_key'] ?? obj['key']),
        name: str(obj['display_name'] ?? obj['name']),
        status: status === 'archived' ? 'archived' : 'active',
      };
    }),
  };
}

/**
 * Map a normalized StoryListItem into the local Story model used by the views.
 *
 * The approval `status` MUST come from the approval-bearing search path
 * (E1/AC9): if the item carries no approval `status` it was sourced from the
 * runtime list/detail path, and feeding the runtime lifecycle into the approval
 * union would be a type lie. Such items default fail-closed to 'Backlog' for the
 * approval `status` and carry the runtime value in `executionLifecycle` so the
 * UI never conflates the two. Board/sheet load via {@link BffClient.listStories}
 * (search-backed), so they always have a real approval status.
 */
export function listItemToStory(item: StoryListItem): Story {
  return {
    id: item.id,
    title: item.title,
    status: item.status ?? 'Backlog',
    executionLifecycle: item.executionLifecycle,
    type: item.type as StoryType,
    size: item.size as StorySize,
    owner: item.owner,
    repo: item.repo,
    module: item.module,
    epic: item.epic,
    changeImpact: item.changeImpact as ChangeImpact,
    conceptQuality: item.conceptQuality as ConceptQuality,
    wave: item.wave,
    mode: (item.mode as Story['mode']) ?? 'standard',
    dependencies: item.dependencies ?? [],
    risk: 'medium',
    criticalPath: false,
    qaRounds: 0,
    processingTime: '-',
    labels: [],
    acceptance: [],
    gates: [],
    phases: [],
    events: [],
  };
}

/** Normalize a story-detail response (flat public StoryDetail OR detail envelope). */
function normalizeStoryDetail(raw: Record<string, unknown>): StoryDetailResponse {
  // story_context_manager detail envelope: { summary, spec, telemetry, ... }
  if (raw['summary'] !== undefined && typeof raw['summary'] === 'object') {
    const summary = raw['summary'] as Record<string, unknown>;
    return {
      summary: {
        id: str(summary['story_id'] ?? summary['id']),
        title: str(summary['title']),
        status: str(summary['status'] ?? summary['lifecycle_status']),
        type: str(summary['type'] ?? summary['story_type']),
        size: str(summary['size'] ?? summary['story_size']),
        owner: str(summary['owner']),
        repo: firstRepo(summary as WireStorySummary),
        module: str(summary['module']),
        epic: str(summary['epic']),
        changeImpact: str(summary['change_impact'] ?? summary['changeImpact']),
        conceptQuality: str(summary['concept_quality'] ?? summary['conceptQuality']),
        wave: num(summary['wave']),
      },
      spec: (raw['spec'] ?? null) as StoryDetailResponse['spec'],
      evidence: (raw['evidence'] ?? null) as StoryDetailResponse['evidence'],
      telemetry: (raw['telemetry'] ?? null) as StoryDetailResponse['telemetry'],
      gates: Array.isArray(raw['gates']) ? (raw['gates'] as StoryDetailResponse['gates']) : [],
      phases: Array.isArray(raw['phases']) ? (raw['phases'] as StoryDetailResponse['phases']) : [],
      events: Array.isArray(raw['events']) ? (raw['events'] as StoryDetailResponse['events']) : [],
    };
  }
  // Flat public StoryDetail (agentkit.story.models.StoryDetail).
  const wire = raw as WireStorySummary & Record<string, unknown>;
  return {
    summary: {
      id: str(wire.story_id ?? wire.id),
      title: str(wire.title),
      status: str(wire.lifecycle_status ?? wire.status),
      type: str(wire.story_type ?? wire.type),
      size: str(wire.story_size ?? wire.size),
      owner: str(wire.owner),
      repo: firstRepo(wire),
      module: str(wire.module),
      epic: str(wire.epic),
      changeImpact: str(wire.change_impact),
      conceptQuality: str(wire.concept_quality),
      wave: num(wire.wave),
    },
    spec: (raw['spec'] ?? null) as StoryDetailResponse['spec'],
    evidence: (raw['evidence'] ?? null) as StoryDetailResponse['evidence'],
    telemetry: (raw['telemetry'] ?? null) as StoryDetailResponse['telemetry'],
    gates: Array.isArray(raw['gates']) ? (raw['gates'] as StoryDetailResponse['gates']) : [],
    phases: Array.isArray(raw['phases']) ? (raw['phases'] as StoryDetailResponse['phases']) : [],
    events: Array.isArray(raw['recent_events'])
      ? (raw['recent_events'] as StoryDetailResponse['events'])
      : Array.isArray(raw['events'])
        ? (raw['events'] as StoryDetailResponse['events'])
        : [],
  };
}

/** Injectable transport for testing. */
export type FetchTransport = (url: string, options?: RequestInit) => Promise<Response>;

export const defaultTransport: FetchTransport = (url, options) => fetch(url, options);

export class BffClient {
  constructor(
    private readonly baseUrl: string = '',
    private readonly transport: FetchTransport = defaultTransport,
  ) {}

  private async readJson(url: string): Promise<Record<string, unknown>> {
    let response: Response;
    try {
      response = await this.transport(url);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      throw new BffReadError(`GET ${url} failed: ${message}`, 0, 'network_error');
    }
    if (!response.ok) {
      let errorCode = 'error';
      try {
        const body = (await response.clone().json()) as Record<string, unknown>;
        if (typeof body['error_code'] === 'string') errorCode = body['error_code'];
      } catch {
        errorCode = `http_${response.status}`;
      }
      throw new BffReadError(`GET ${url} failed: ${response.status}`, response.status, errorCode);
    }
    return (await response.json()) as Record<string, unknown>;
  }

  // ── Story collection ─────────────────────────────────────────────────────

  /**
   * Board/sheet initial story set WITH approval status (E1/AC9).
   *
   * Sourced from the APPROVAL-BEARING public read path (the search endpoint of
   * story_context_manager), NOT the runtime list endpoint whose `lifecycle_status`
   * is not an approval value. An all-stories read uses a SQL-LIKE wildcard query
   * (`%`) so the backend's substring match returns the full project story set
   * (story_repository.search wraps the query as `%{q}%`). The route requires a
   * non-empty `q`, so `%` is the canonical match-all token.
   */
  async listStories(projectKey: string): Promise<StoryListResponse> {
    return this.searchStories(projectKey, '%');
  }

  /**
   * Runtime list path (agentkit.story.service): carries `lifecycle_status`, NOT
   * approval status. Kept available for runtime-lifecycle consumers; the board /
   * sheet status views deliberately do NOT use this (see {@link listStories}).
   */
  async listStoriesRuntime(projectKey: string): Promise<StoryListResponse> {
    const url = `${this.baseUrl}/v1/projects/${encodeURIComponent(projectKey)}/stories`;
    return normalizeStoryList(await this.readJson(url));
  }

  async getStoryDetail(projectKey: string, storyId: string): Promise<StoryDetailResponse> {
    const url = `${this.baseUrl}/v1/projects/${encodeURIComponent(projectKey)}/stories/${encodeURIComponent(storyId)}`;
    return normalizeStoryDetail(await this.readJson(url));
  }

  async searchStories(projectKey: string, query: string): Promise<StoryListResponse> {
    const url = `${this.baseUrl}/v1/projects/${encodeURIComponent(projectKey)}/stories/search?q=${encodeURIComponent(query)}`;
    return normalizeSearchList(await this.readJson(url));
  }

  async getStoryCounters(projectKey: string): Promise<StoryCountersResponse> {
    const url = `${this.baseUrl}/v1/projects/${encodeURIComponent(projectKey)}/stories/counters`;
    return (await this.readJson(url)) as unknown as StoryCountersResponse;
  }

  // ── Project-level read-models ─────────────────────────────────────────────

  async getModeLock(projectKey: string): Promise<ModeLockResponse> {
    const url = `${this.baseUrl}/v1/projects/${encodeURIComponent(projectKey)}/mode-lock`;
    return (await this.readJson(url)) as unknown as ModeLockResponse;
  }

  async getStoryFlow(projectKey: string, storyId: string): Promise<StoryFlowResponse> {
    const url = `${this.baseUrl}/v1/projects/${encodeURIComponent(projectKey)}/stories/${encodeURIComponent(storyId)}/flow`;
    return (await this.readJson(url)) as unknown as StoryFlowResponse;
  }

  async getCoverageAcceptance(projectKey: string, storyId: string): Promise<CoverageAcceptanceResponse> {
    const url = `${this.baseUrl}/v1/projects/${encodeURIComponent(projectKey)}/coverage/stories/${encodeURIComponent(storyId)}/acceptance`;
    return (await this.readJson(url)) as unknown as CoverageAcceptanceResponse;
  }

  async getCoverageAreEvidence(projectKey: string, storyId: string): Promise<AreEvidenceResponse> {
    const url = `${this.baseUrl}/v1/projects/${encodeURIComponent(projectKey)}/coverage/stories/${encodeURIComponent(storyId)}/are-evidence`;
    return (await this.readJson(url)) as unknown as AreEvidenceResponse;
  }

  async getExecutionLimits(projectKey: string): Promise<ExecutionLimitsResponse> {
    const url = `${this.baseUrl}/v1/projects/${encodeURIComponent(projectKey)}/execution-input/limits`;
    return (await this.readJson(url)) as unknown as ExecutionLimitsResponse;
  }

  // ── Project list ─────────────────────────────────────────────────────────

  async listProjects(): Promise<ProjectListResponse> {
    const url = `${this.baseUrl}/v1/projects`;
    return normalizeProjectList(await this.readJson(url));
  }

  // ── Story mutations ───────────────────────────────────────────────────────

  private async mutate(url: string, body: Record<string, unknown>): Promise<Response> {
    const response = await this.transport(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!response.ok) {
      let errorCode = 'error';
      try {
        const parsed = (await response.clone().json()) as Record<string, unknown>;
        if (typeof parsed['error_code'] === 'string') errorCode = parsed['error_code'];
      } catch {
        errorCode = `http_${response.status}`;
      }
      throw new BffReadError(`POST ${url} failed: ${response.status} (${errorCode})`, response.status, errorCode);
    }
    return response;
  }

  async createStory(projectKey: string, payload: Record<string, unknown>): Promise<StoryDetailResponse> {
    const url = `${this.baseUrl}/v1/projects/${encodeURIComponent(projectKey)}/stories`;
    const response = await this.mutate(url, payload);
    return normalizeStoryDetail((await response.json()) as Record<string, unknown>);
  }

  async approveStory(projectKey: string, storyId: string, opId: string): Promise<void> {
    const url = `${this.baseUrl}/v1/projects/${encodeURIComponent(projectKey)}/stories/${encodeURIComponent(storyId)}/approve`;
    await this.mutate(url, { op_id: opId });
  }

  async rejectStory(projectKey: string, storyId: string, opId: string): Promise<void> {
    const url = `${this.baseUrl}/v1/projects/${encodeURIComponent(projectKey)}/stories/${encodeURIComponent(storyId)}/reject`;
    await this.mutate(url, { op_id: opId });
  }

  async cancelStory(projectKey: string, storyId: string, reason?: string, opId?: string): Promise<void> {
    const url = `${this.baseUrl}/v1/projects/${encodeURIComponent(projectKey)}/stories/${encodeURIComponent(storyId)}/cancel`;
    await this.mutate(url, { reason, op_id: opId });
  }
}
