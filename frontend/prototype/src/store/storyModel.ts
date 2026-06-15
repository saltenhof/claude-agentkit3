/*
 * Story data model — the *single* source of types for all views.
 *
 * Single source of truth: every UI view (Graph, Sheet, Kanban,
 * Inspector, KpiBar, ReadyStack, ExecutionLimits) consumes these
 * types and operates on the same story dataset from
 * `storyFixtures.ts`. Views are pure selectors over this model.
 */

export type StoryStatus = 'Backlog' | 'Approved' | 'In Progress' | 'Done' | 'Cancelled';
/*
 * Runtime execution lifecycle (agentkit.story.models.StorySummary.lifecycle_status),
 * exposed by the PUBLIC list/detail path (agentkit.story.service). This is the
 * runtime projection ('defined', 'in_setup', ...) — NOT the approval status.
 * It is modelled as its OWN field on Story and MUST NEVER be cast into the
 * approval `status` union (two-StoryService split, Codex R3 adjudication).
 */
export type ExecutionLifecycle = string;
export type StoryType = 'implementation' | 'bugfix' | 'concept' | 'research';
export type StorySize = 'XS' | 'S' | 'M' | 'L' | 'XL' | 'XXL';
export type PhaseStatus = 'done' | 'active' | 'blocked' | 'idle' | 'skipped';
export type ChangeImpact = 'Local' | 'Component' | 'Cross-Component' | 'Architecture Impact';
export type ConceptQuality = 'High' | 'Medium' | 'Low';

/* Story mode (FK-24): execution / exploration / fast */
export type Mode = 'standard' | 'fast';

/* 4-phase pipeline (FK-20) */
export type Phase = 'setup' | 'exploration' | 'implementation' | 'closure';

/* Substep sequences per phase, derived from FK-22/23/26/27/29.
 * Typed as string in the prototype; the backend will canonicalize
 * this as a phase-specific StrEnum later (AG3-019). */
export type Substep = string;

export interface RuntimeState {
  phase: Phase;
  substep: Substep;
  /* Current iteration of a loop group within the phase
   * (e.g. remediation loop in Implementation: Worker -> QA -> Worker
   * -> QA ...). 1 = first round, 2 = first retry, etc.
   * Default 1. */
  iteration?: number;
}

/* Substep metadata for visualization in the Story Inspector "Ablauf" tab.
 *
 * - `optional = true`: the substep is conceptually part of standard mode
 *   but only executed when a precondition is met (example: `feindesign`
 *   only for stories that require detailed design; `finding_resolution`
 *   only when QA findings exist).
 * - `loopGroup`: a contiguous substep sequence that may be traversed
 *   multiple times (e.g. `remediation` in Implementation,
 *   `design_iteration` in Exploration). Substeps with the same value
 *   form a loop region; the phase UI shows an iteration counter and a
 *   return marker. */
export interface SubstepMeta {
  optional?: boolean;
  loopGroup?: string;
}

export interface Story {
  id: string;
  title: string;
  type: StoryType;
  status: StoryStatus;
  /* Runtime execution lifecycle from the PUBLIC list/detail path
   * (agentkit.story.service lifecycle_status). Separate from approval `status`;
   * only set when sourced from the runtime list/detail path. Display-only. */
  executionLifecycle?: ExecutionLifecycle;
  size: StorySize;
  owner: string;
  repo: string;
  primaryRepo?: string;
  participatingRepos?: string[];
  module: string;
  epic: string;
  changeImpact: ChangeImpact;
  conceptQuality: ConceptQuality;
  wave: number;
  risk: 'low' | 'medium' | 'high';
  blocker?: string;
  criticalPath: boolean;
  qaRounds: number;
  qaRoundsExploration?: number;
  qaRoundsImplementation?: number;
  processingTime: string;
  createdAt?: string;
  completedAt?: string;
  labels: string[];
  acceptance: string[];
  need?: string;
  solution?: string;
  conceptRefs?: string[];
  guardrailRefs?: string[];
  externalSources?: string[];
  definitionOfDone?: string[];
  evidence?: {
    qaCycleId: string;
    qaCycleRound: number;
    evidenceEpoch: string;
    evidenceFingerprint: string;
    manifestHash: string;
    bundleEntries: Array<{
      authority: 'STORY_SPEC' | 'CONCEPT' | 'GUARDRAIL' | 'DIFF' | 'HANDOVER' | 'SECONDARY_CONTEXT';
      path: string;
      status: 'INCLUDED' | 'REQUESTED' | 'UNRESOLVED';
    }>;
  };
  telemetry?: {
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
    pools: Array<{
      pool: 'chatgpt' | 'gemini' | 'grok' | 'qwen' | 'kimi';
      role: string;
      calls: number;
      status: 'PASS' | 'WARNING' | 'FAIL';
    }>;
  };
  gates: Array<{ label: string; state: 'PASS' | 'WARNING' | 'ERROR' }>;
  phases: Array<{ label: string; state: PhaseStatus; detail: string }>;
  events: Array<{ time: string; type: string; detail: string; severity: 'info' | 'warning' | 'error' }>;
  dependencies: string[];
  /* Story mode (optional, default = 'standard'). */
  mode?: Mode;
  /* Current runtime state; only set for 'In Progress' stories. */
  runtime?: RuntimeState;
}

/* Execution limits (FK-70 §70.6.2): the five caps between
 * feasibility and max_allowed_batch. */
export interface ExecutionLimits {
  repoParallelCap: number;
  mergeRiskCap: number;
  maxParallelAgentCap: number;
  llmPoolCap: number;
  ciCapacityCap: number;
}

export interface ExecutionLimitDescriptor {
  key: keyof ExecutionLimits;
  label: string;
  description: string;
}
