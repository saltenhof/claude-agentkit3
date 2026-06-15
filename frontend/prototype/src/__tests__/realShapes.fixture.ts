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
