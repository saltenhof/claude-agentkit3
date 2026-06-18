/**
 * REAL backend-shaped wire payloads, captured empirically against the live
 * ControlPlaneApplication (in-process, real SQLite store) on 2026-06-15.
 *
 * These are NOT hand-invented shapes — they are verbatim copies of the JSON the
 * real endpoints emit, so the BffClient normalization is tested against the
 * actual field names. If the backend wire contract changes, these fixtures (and
 * the normalization) must change together. See the AG3-093 R3 handover for the
 * capture procedure (build_app + handle_request probes).
 */

/** GET /v1/projects/{key}/stories/search — story_context_manager story_to_wire_summary. */
export const REAL_SEARCH_RESPONSE = {
  project_key: 'e2etest',
  stories: [
    {
      blocker: null,
      change_impact: 'Local',
      completed_at: null,
      concept_quality: 'Medium',
      created_at: '2026-06-15T21:00:21.987952+00:00',
      critical_path: false,
      dependencies: [],
      epic: 'E2E Epic',
      labels: [],
      mode: null,
      module: 'test-module',
      owner: 'e2e-test',
      processing_time: null,
      project_key: 'e2etest',
      qa_rounds: 0,
      qa_rounds_exploration: null,
      qa_rounds_implementation: null,
      repos: ['https://github.com/e2e/test-repo'],
      risk: 'low',
      size: 'M',
      split_from: null,
      split_successors: [],
      status: 'Approved',
      story_id: 'E2ETEST-001',
      title: 'E2E Test Story',
      type: 'implementation',
      vectordb_conflict_resolved: false,
      wave: 0,
    },
  ],
} as const;

/** GET /v1/projects/{key}/stories — agentkit.story.models.StorySummary (public list). */
export const REAL_PUBLIC_LIST_RESPONSE = {
  project_key: 'ctxtest',
  stories: [
    {
      project_key: 'ctxtest',
      story_id: 'CTX-001',
      title: 'Ctx Story',
      story_type: 'implementation',
      execution_route: 'execution',
      implementation_contract: 'standard',
      story_size: 'M',
      issue_nr: null,
      lifecycle_status: 'defined',
      active_phase: null,
      phase_status: null,
      current_run: null,
      latest_metrics: null,
    },
  ],
} as const;

/** GET /v1/projects/{key}/stories/{id} — flat agentkit.story.models.StoryDetail. */
export const REAL_PUBLIC_DETAIL_RESPONSE = {
  project_key: 'ctxtest',
  story_id: 'CTX-001',
  title: 'Ctx Story',
  story_type: 'implementation',
  execution_route: 'execution',
  implementation_contract: 'standard',
  story_size: 'M',
  issue_nr: null,
  lifecycle_status: 'defined',
  active_phase: null,
  phase_status: null,
  current_run: null,
  latest_metrics: null,
  labels: [],
  participating_repos: ['https://github.com/e2e/r'],
  created_at: null,
  recent_events: [],
} as const;

/** GET /v1/projects — project_management ProjectSummary list. */
export const REAL_PROJECTS_RESPONSE = {
  projects: [
    { display_name: 'Alpha Project', project_key: 'alpha', status: 'active' },
    { display_name: 'Archived One', project_key: 'archived-one', status: 'archived' },
  ],
} as const;

/** GET /v1/projects/{key}/stories/counters — frontend-contracts.entity.story_counters. */
export const REAL_COUNTERS_RESPONSE = {
  story_counters: {
    project_key: 'ctxtest',
    blocked: 2,
    finished: 0,
    queue: 0,
    ready: 0,
    running: 0,
    total: 2,
  },
} as const;

/** GET /v1/projects/{key}/mode-lock — frontend-contracts.entity.project_mode_lock. */
export const REAL_MODE_LOCK_RESPONSE = {
  mode_lock: { mode: 'idle', project_key: 'ctxtest' },
} as const;

/** GET /v1/projects/{key}/execution-input/limits — frontend-contracts.entity.execution_limits. */
export const REAL_LIMITS_RESPONSE = {
  execution_limits: {
    project_key: 'ctxtest',
    repo_parallel_cap: 3,
    merge_risk_cap: 5,
    max_parallel_agent_cap: 8,
    llm_pool_cap: 10,
    ci_capacity_cap: 4,
  },
} as const;

/** GET /v1/projects/{key}/stories/{id}/flow — frontend-contracts.entity.story_flow_snapshot. */
export const REAL_FLOW_RESPONSE = {
  story_flow_snapshot: {
    story_id: 'CTX-001',
    mode: 'standard',
    phases: [
      {
        phase: 'setup',
        state: 'pending',
        state_reason: null,
        iteration: null,
        iteration_loop_group: null,
        substeps: [
          {
            substep: 'preflight',
            state: 'pending',
            optional: false,
            loop_group: null,
            loop_position: null,
            loop_size: null,
          },
        ],
      },
      {
        phase: 'exploration',
        state: 'pending',
        state_reason: null,
        iteration: null,
        iteration_loop_group: null,
        substeps: [],
      },
      {
        phase: 'implementation',
        state: 'pending',
        state_reason: null,
        iteration: null,
        iteration_loop_group: null,
        substeps: [],
      },
      {
        phase: 'closure',
        state: 'pending',
        state_reason: null,
        iteration: null,
        iteration_loop_group: null,
        substeps: [],
      },
    ],
  },
} as const;

/** GET /v1/projects/{key}/coverage/stories/{id}/acceptance. */
export const REAL_COVERAGE_ACCEPTANCE_RESPONSE = {
  story_coverage_acceptance: {
    acceptance_criteria: [],
    linked_requirements: [],
    project_key: 'ctxtest',
    story_id: 'CTX-001',
  },
} as const;

/** GET /v1/projects/{key}/coverage/stories/{id}/are-evidence. */
export const REAL_ARE_EVIDENCE_RESPONSE = {
  story_are_evidence: {
    linked_requirements: [],
    project_key: 'ctxtest',
    story_id: 'CTX-001',
  },
} as const;

/**
 * GET /v1/projects/{key}/kpi/stories — KpiAnalytics dimension endpoint (AG3-084 / AG3-116).
 * Wire shape: FK-62 §62.2.1 named projection via WireKpiStoryRow DTO.
 * Rows are empty because the fact tables start empty in a fresh SQLite store.
 * The status field is "EMPTY" when no fact rows exist.
 *
 * Field renames at HTTP edge (AG3-116): story_mode→pipeline_mode,
 * started_at→opened_at, completed_at→closed_at, qa_rounds→qa_round_count,
 * adversarial_findings→adversarial_findings_count, are_gate_status→are_gate_passed.
 * Dropped: agentkit_version, agentkit_commit.
 */
export const REAL_KPI_STORIES_RESPONSE = {
  project_key: 'kpitest',
  dimension: 'stories',
  status: 'EMPTY',
  rows: [] as Array<{
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
  }>,
} as const;

/**
 * GET /v1/projects/{key}/kpi/guards — KpiAnalytics guards dimension (AG3-116).
 * Wire shape: FK-62 §62.2.2 named projection via WireKpiGuardRow DTO.
 * Renamed: guard_id→guard_key. Dropped: period_end.
 */
export const REAL_KPI_GUARDS_RESPONSE = {
  project_key: 'kpitest',
  dimension: 'guards',
  status: 'EMPTY',
  rows: [] as Array<{
    project_key: string;
    guard_key: string;
    period_start: string;
    invocation_count: number;
    violation_count: number;
  }>,
} as const;

/**
 * GET /v1/projects/{key}/kpi/pools — KpiAnalytics pools dimension (AG3-116).
 * Wire shape: FK-62 §62.2.3 named projection via WireKpiPoolRow DTO.
 * Renamed: llm_role→pool_key. Dropped: period_end, token_input_total,
 * token_output_total, avg_latency_ms.
 */
export const REAL_KPI_POOLS_RESPONSE = {
  project_key: 'kpitest',
  dimension: 'pools',
  status: 'EMPTY',
  rows: [] as Array<{
    project_key: string;
    pool_key: string;
    period_start: string;
    call_count: number;
  }>,
} as const;

/**
 * GET /v1/projects/{key}/kpi/pipeline — KpiAnalytics pipeline dimension (AG3-116).
 * Wire shape: FK-62 §62.2.4 named projection via WireKpiPipelineRow DTO.
 * Renamed: stories_completed→story_count_closed, avg_qa_rounds→qa_round_avg.
 * Dropped: period_end, stories_escalated, avg_phase_implementation_ms.
 */
export const REAL_KPI_PIPELINE_RESPONSE = {
  project_key: 'kpitest',
  dimension: 'pipeline',
  status: 'EMPTY',
  rows: [] as Array<{
    project_key: string;
    period_start: string;
    story_count_closed: number;
    qa_round_avg: number | null;
  }>,
} as const;

/**
 * GET /v1/projects/{key}/kpi/corpus — KpiAnalytics corpus dimension (AG3-116).
 * Wire shape: FK-62 §62.2.5 named projection via WireKpiCorpusRow DTO.
 * Renamed: incidents_recorded→new_incident_count,
 * patterns_promoted→patterns_total_count, checks_approved→patterns_with_active_check.
 * Dropped: period_end.
 */
export const REAL_KPI_CORPUS_RESPONSE = {
  project_key: 'kpitest',
  dimension: 'corpus',
  status: 'EMPTY',
  rows: [] as Array<{
    project_key: string;
    period_start: string;
    new_incident_count: number;
    patterns_total_count: number;
    patterns_with_active_check: number;
  }>,
} as const;

/**
 * GET /v1/projects/{key}/kpi/design-tokens — design-token static adapter.
 * Wire shape: { project_key, colors, typography, spacing, control, chart }
 * This is a static serialization of the DesignSystem owner (AG3-092, FK-64).
 * The chart.series sub-object holds the ordered series colors (AG3-094).
 */
export const REAL_KPI_DESIGN_TOKENS_RESPONSE = {
  project_key: 'kpitest',
  colors: {
    neutral: { bg: '#111214' /* ... other fields ... */ },
    accent: { accent_text: '#48e7ff' /* ... */ },
    status: { success: '#74d17f' /* ... */ },
  },
  chart: {
    series: {
      series_0: '#48e7ff',
      series_1: '#ffb32c',
      series_2: '#74d17f',
      series_3: '#b38cff',
      series_4: '#ff5b57',
      series_5: '#7ea7ff',
      series_6: '#ffd35e',
      series_7: '#82c4ff',
      series_8: '#a371f7',
      series_9: '#3fb950',
      series_10: '#d29922',
      series_11: '#9ff5ff',
    },
  },
} as const;
