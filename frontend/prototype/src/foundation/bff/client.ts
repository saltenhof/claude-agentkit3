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

// ── KPI wire types (AG3-084 / AG3-094 — real backend shapes) ─────────────────

/**
 * Wire shape for a FactStory row — FK-62 §62.2.1 named projection (AG3-116).
 *
 * Internal record renames applied here: story_mode→pipeline_mode,
 * started_at→opened_at, completed_at→closed_at, qa_rounds→qa_round_count,
 * adversarial_findings→adversarial_findings_count,
 * are_gate_status→are_gate_passed.
 * Dropped (no FK-62 equivalent): agentkit_version, agentkit_commit.
 */
export interface WireFactStory {
  project_key: string;
  story_id: string;
  story_type: string;
  story_size: string;
  pipeline_mode: string | null;
  opened_at: string;
  closed_at: string | null;
  qa_round_count: number;
  compaction_count: number | null;
  llm_call_count: number | null;
  adversarial_findings_count: number | null;
  adversarial_tests_created: number | null;
  files_changed: number | null;
  feedback_converged: boolean | null;
  phase_setup_ms: number | null;
  phase_implementation_ms: number | null;
  phase_closure_ms: number | null;
  are_gate_passed: string | null;
}

/**
 * Wire shape for a FactGuardPeriod row — FK-62 §62.2.2 named projection (AG3-116).
 *
 * Renamed: guard_id→guard_key.  Dropped: period_end.
 */
export interface WireFactGuardPeriod {
  project_key: string;
  guard_key: string;
  period_start: string;
  invocation_count: number;
  violation_count: number;
}

/**
 * Wire shape for a FactPoolPeriod row — FK-62 §62.2.3 named projection (AG3-116).
 *
 * Renamed: llm_role→pool_key.  Dropped: period_end, token_input_total,
 * token_output_total, avg_latency_ms.
 */
export interface WireFactPoolPeriod {
  project_key: string;
  pool_key: string;
  period_start: string;
  call_count: number;
}

/**
 * Wire shape for a FactPipelinePeriod row — FK-62 §62.2.4 named projection (AG3-116).
 *
 * Renamed: stories_completed→story_count_closed, avg_qa_rounds→qa_round_avg.
 * Dropped: period_end, stories_escalated, avg_phase_implementation_ms.
 */
export interface WireFactPipelinePeriod {
  project_key: string;
  period_start: string;
  story_count_closed: number;
  qa_round_avg: number | null;
}

/**
 * Wire shape for a FactCorpusPeriod row — FK-62 §62.2.5 named projection (AG3-116).
 *
 * Renamed: incidents_recorded→new_incident_count,
 * patterns_promoted→patterns_total_count,
 * checks_approved→patterns_with_active_check.
 * Dropped: period_end.
 */
export interface WireFactCorpusPeriod {
  project_key: string;
  period_start: string;
  new_incident_count: number;
  patterns_total_count: number;
  patterns_with_active_check: number;
}

/** Union of all KPI fact row wire shapes. */
export type KpiFactRow =
  | WireFactStory
  | WireFactGuardPeriod
  | WireFactPoolPeriod
  | WireFactPipelinePeriod
  | WireFactCorpusPeriod;

/** KPI dimension endpoint response wire shape (AG3-084). */
export interface KpiDimensionResponse {
  project_key: string;
  dimension: string;
  status: 'OK' | 'EMPTY' | 'UNAVAILABLE';
  rows: KpiFactRow[];
  comparison_period?: { from: string; to: string };
  comparison_rows?: KpiFactRow[];
}

/** Chart series tokens from the /kpi/design-tokens endpoint (AG3-092). */
export interface KpiChartSeriesTokens {
  series_0: string;
  series_1: string;
  series_2: string;
  series_3: string;
  series_4: string;
  series_5: string;
  series_6: string;
  series_7: string;
  series_8: string;
  series_9: string;
  series_10: string;
  series_11: string;
}

/** Design tokens response from /kpi/design-tokens (AG3-092). */
export interface KpiDesignTokensResponse {
  project_key: string;
  chart: { series: KpiChartSeriesTokens };
  colors: Record<string, unknown>;
  typography: Record<string, unknown>;
  spacing: Record<string, unknown>;
  control: Record<string, unknown>;
}

/**
 * Query filter parameters for KPI endpoints (FK-63 §63.4.2 / AG3-084).
 * All dates must be timezone-aware ISO-8601 (Z or +HH:MM).
 */
export interface KpiQueryParams {
  from: string;
  to: string;
  guard?: string;
  pool?: string;
  story_type?: string;
  story_size?: string;
  compare_from?: string;
  compare_to?: string;
}

// ── Task-management wire types (AG3-105 / FK-77) ─────────────────────────────
// Wire shapes match Task.model_dump(mode="json") exactly (src/agentkit/task_management/models.py).
// NO description/story_id/updated_at/due_at — those are wrong field names from the prior worker.

/** Wire shape for a Task row (task_management.models.Task.model_dump(mode="json")). */
export interface WireTask {
  task_id: string;
  project_key: string;
  /** reminder | actionable */
  kind: 'reminder' | 'actionable';
  /** Freeform task category string (e.g. "general", "concept_update"). */
  type: string;
  title: string;
  /** Task body text — NOT "description". */
  body: string;
  priority: 'low' | 'normal' | 'high';
  status: 'open' | 'done' | 'dismissed';
  origin: 'closure' | 'verify' | 'governance' | 'human';
  /** Optional story that spawned this task — NOT "story_id". */
  source_story_id: string | null;
  /** Optional reference to an execution-report artifact. */
  execution_report_ref: string | null;
  created_at: string;
  resolved_at: string | null;
  resolved_by: 'human' | 'agent' | null;
}

/** Wire shape for a TaskLink row (task_management.models.TaskLink.model_dump()).
 * NOTE: the relation-type field is named `kind`, NOT `relation_kind`.
 */
export interface WireTaskLink {
  project_key: string;
  task_id: string;
  target_kind: 'task' | 'story';
  target_id: string;
  /** Relation kind field name is literally `kind` (not `relation_kind`). */
  kind: 'relates_to' | 'spawned_story' | 'duplicate_of';
}

/** Task list response wire shape. */
export interface TaskListResponse {
  project_key: string;
  tasks: WireTask[];
}

/** Task-links list response wire shape (AG3-105/AC4 — GET /task-links). */
export interface TaskLinkListResponse {
  project_key: string;
  links: WireTaskLink[];
}

/** Single task response wire shape. */
export interface TaskResponse {
  project_key: string;
  task: WireTask;
}

/** Task link response (201 on create). */
export interface TaskLinkResponse {
  link: WireTaskLink;
}

/** Payload for createTask (no task_id — allocated server-side). */
export interface CreateTaskPayload {
  kind: WireTask['kind'];
  type: string;
  title: string;
  body: string;
  priority: WireTask['priority'];
  origin: WireTask['origin'];
  source_story_id?: string | null;
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

  // ── KPI analytics (AG3-084 / AG3-094) ────────────────────────────────────

  /**
   * Build the KPI endpoint URL for a given dimension with typed query params.
   * Requires from/to (mandatory — backend rejects requests without a period).
   */
  private kpiUrl(projectKey: string, dimension: string, params: KpiQueryParams): string {
    const base = `${this.baseUrl}/v1/projects/${encodeURIComponent(projectKey)}/kpi/${encodeURIComponent(dimension)}`;
    const q = new URLSearchParams();
    q.set('from', params.from);
    q.set('to', params.to);
    if (params.guard != null) q.set('guard', params.guard);
    if (params.pool != null) q.set('pool', params.pool);
    if (params.story_type != null) q.set('story_type', params.story_type);
    if (params.story_size != null) q.set('story_size', params.story_size);
    if (params.compare_from != null) q.set('compare_from', params.compare_from);
    if (params.compare_to != null) q.set('compare_to', params.compare_to);
    return `${base}?${q.toString()}`;
  }

  /** GET /v1/projects/{key}/kpi/stories — story KPI dimension (fact_story). */
  async getKpiStories(projectKey: string, params: KpiQueryParams): Promise<KpiDimensionResponse> {
    const url = this.kpiUrl(projectKey, 'stories', params);
    return (await this.readJson(url)) as unknown as KpiDimensionResponse;
  }

  /** GET /v1/projects/{key}/kpi/guards — guards KPI dimension (fact_guard_period). */
  async getKpiGuards(projectKey: string, params: KpiQueryParams): Promise<KpiDimensionResponse> {
    const url = this.kpiUrl(projectKey, 'guards', params);
    return (await this.readJson(url)) as unknown as KpiDimensionResponse;
  }

  /** GET /v1/projects/{key}/kpi/pools — pools KPI dimension (fact_pool_period). */
  async getKpiPools(projectKey: string, params: KpiQueryParams): Promise<KpiDimensionResponse> {
    const url = this.kpiUrl(projectKey, 'pools', params);
    return (await this.readJson(url)) as unknown as KpiDimensionResponse;
  }

  /** GET /v1/projects/{key}/kpi/pipeline — pipeline KPI dimension (fact_pipeline_period). */
  async getKpiPipeline(projectKey: string, params: KpiQueryParams): Promise<KpiDimensionResponse> {
    const url = this.kpiUrl(projectKey, 'pipeline', params);
    return (await this.readJson(url)) as unknown as KpiDimensionResponse;
  }

  /** GET /v1/projects/{key}/kpi/corpus — failure-corpus KPI dimension (fact_corpus_period). */
  async getKpiCorpus(projectKey: string, params: KpiQueryParams): Promise<KpiDimensionResponse> {
    const url = this.kpiUrl(projectKey, 'corpus', params);
    return (await this.readJson(url)) as unknown as KpiDimensionResponse;
  }

  /** GET /v1/projects/{key}/kpi/design-tokens — static token family (AG3-092, FK-64). */
  async getKpiDesignTokens(projectKey: string): Promise<KpiDesignTokensResponse> {
    const url = `${this.baseUrl}/v1/projects/${encodeURIComponent(projectKey)}/kpi/design-tokens`;
    return (await this.readJson(url)) as unknown as KpiDesignTokensResponse;
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

  // ── Task-management methods (AG3-105 / FK-77) ────────────────────────────────

  /** GET /v1/projects/{key}/tasks — list tasks for a project (optional filter params). */
  async listTasks(
    projectKey: string,
    params?: { status?: string; type?: string; kind?: string; origin?: string },
  ): Promise<TaskListResponse> {
    let url = `${this.baseUrl}/v1/projects/${encodeURIComponent(projectKey)}/tasks`;
    if (params) {
      const q = new URLSearchParams();
      if (params.status) q.set('status', params.status);
      if (params.type) q.set('type', params.type);
      if (params.kind) q.set('kind', params.kind);
      if (params.origin) q.set('origin', params.origin);
      const qs = q.toString();
      if (qs) url = `${url}?${qs}`;
    }
    return (await this.readJson(url)) as unknown as TaskListResponse;
  }

  /**
   * GET /v1/projects/{key}/task-links — all task links for the project (AG3-105/AC4).
   *
   * The list view calls this once on load and buckets the links by ``task_id`` so
   * each task's own (outgoing) link badges render from BACKEND truth, not from a
   * session-local shadow (SSOT / FIX-THE-MODEL). Lives at a dedicated /task-links
   * path so it is never shadowed by /tasks/{task_id}.
   */
  async listTaskLinks(projectKey: string): Promise<TaskLinkListResponse> {
    const url = `${this.baseUrl}/v1/projects/${encodeURIComponent(projectKey)}/task-links`;
    return (await this.readJson(url)) as unknown as TaskLinkListResponse;
  }

  /** GET /v1/projects/{key}/tasks/for-target/{target_kind}/{target_id} — bidirectional link view. */
  async listTasksForTarget(
    projectKey: string,
    targetKind: 'task' | 'story',
    targetId: string,
  ): Promise<TaskListResponse> {
    const url = `${this.baseUrl}/v1/projects/${encodeURIComponent(projectKey)}/tasks/for-target/${encodeURIComponent(targetKind)}/${encodeURIComponent(targetId)}`;
    return (await this.readJson(url)) as unknown as TaskListResponse;
  }

  /** GET /v1/projects/{key}/tasks/{id} — fetch a single task. */
  async getTask(projectKey: string, taskId: string): Promise<TaskResponse> {
    const url = `${this.baseUrl}/v1/projects/${encodeURIComponent(projectKey)}/tasks/${encodeURIComponent(taskId)}`;
    return (await this.readJson(url)) as unknown as TaskResponse;
  }

  /**
   * POST /v1/projects/{key}/tasks — create a new task.
   * task_id is allocated server-side (TM-YYYY-NNNN); do NOT send task_id.
   * Returns the created task from the server response (AC3: no local shadow fabrication).
   */
  async createTask(projectKey: string, payload: CreateTaskPayload): Promise<TaskResponse> {
    const url = `${this.baseUrl}/v1/projects/${encodeURIComponent(projectKey)}/tasks`;
    const response = await this.mutate(url, payload as unknown as Record<string, unknown>);
    return (await response.json()) as TaskResponse;
  }

  /** POST /v1/projects/{key}/tasks/{id}/resolve — mark a task as done (human). */
  async resolveTask(projectKey: string, taskId: string): Promise<WireTask> {
    const url = `${this.baseUrl}/v1/projects/${encodeURIComponent(projectKey)}/tasks/${encodeURIComponent(taskId)}/resolve`;
    const response = await this.mutate(url, { resolved_by: 'human' });
    const body = (await response.json()) as { task: WireTask };
    return body.task;
  }

  /** POST /v1/projects/{key}/tasks/{id}/dismiss — dismiss a task (human). */
  async dismissTask(projectKey: string, taskId: string): Promise<WireTask> {
    const url = `${this.baseUrl}/v1/projects/${encodeURIComponent(projectKey)}/tasks/${encodeURIComponent(taskId)}/dismiss`;
    const response = await this.mutate(url, { resolved_by: 'human' });
    const body = (await response.json()) as { task: WireTask };
    return body.task;
  }

  /**
   * POST /v1/projects/{key}/tasks/{id}/links — link a task to a story or another task.
   * target_kind ∈ {task, story} only — artifacts are not valid link targets (FK-77 §77.3).
   */
  async linkTask(
    projectKey: string,
    taskId: string,
    targetKind: 'task' | 'story',
    targetId: string,
    kind: WireTaskLink['kind'],
  ): Promise<TaskLinkResponse> {
    const url = `${this.baseUrl}/v1/projects/${encodeURIComponent(projectKey)}/tasks/${encodeURIComponent(taskId)}/links`;
    const response = await this.mutate(url, { target_kind: targetKind, target_id: targetId, kind });
    return (await response.json()) as TaskLinkResponse;
  }

  /**
   * POST /v1/projects/{key}/tasks/{id}/links/delete — remove a task link.
   * Uses POST .../links/delete pattern (not HTTP DELETE) per the backend contract.
   */
  async unlinkTask(
    projectKey: string,
    taskId: string,
    targetKind: 'task' | 'story',
    targetId: string,
    kind: WireTaskLink['kind'],
  ): Promise<void> {
    const url = `${this.baseUrl}/v1/projects/${encodeURIComponent(projectKey)}/tasks/${encodeURIComponent(taskId)}/links/delete`;
    await this.mutate(url, { target_kind: targetKind, target_id: targetId, kind });
  }
}
