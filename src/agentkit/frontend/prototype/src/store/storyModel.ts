/*
 * Story-Datenmodell — die *eine* Quelle der Typen fuer alle Views.
 *
 * Single source of truth: jede UI-Sicht (Graph, Sheet, Kanban,
 * Inspector, KpiBar, ReadyStack, ExecutionLimits) konsumiert diese
 * Typen und arbeitet auf demselben Story-Bestand aus
 * `storyFixtures.ts`. Sichten sind reine Selectors auf diesem Modell.
 */

export type StoryStatus = 'Backlog' | 'Approved' | 'In Progress' | 'Done' | 'Cancelled';
export type StoryType = 'implementation' | 'bugfix' | 'concept' | 'research';
export type StorySize = 'XS' | 'S' | 'M' | 'L' | 'XL' | 'XXL';
export type PhaseStatus = 'done' | 'active' | 'blocked' | 'idle' | 'skipped';
export type ChangeImpact = 'Local' | 'Component' | 'Cross-Component' | 'Architecture Impact';
export type ConceptQuality = 'High' | 'Medium' | 'Low';

/* Story-Mode (FK-24): execution / exploration / fast */
export type Mode = 'standard' | 'fast';

/* 4-Phasen-Pipeline (FK-20) */
export type Phase = 'setup' | 'exploration' | 'implementation' | 'closure';

/* Substep-Sequenzen pro Phase, abgeleitet aus FK-22/23/26/27/29.
 * Im Prototyp als String typisiert; Backend kanonisiert das spaeter
 * als Phase-spezifische StrEnum (AG3-019). */
export type Substep = string;

export interface RuntimeState {
  phase: Phase;
  substep: Substep;
  /* Aktuelle Iteration einer Loop-Gruppe innerhalb der Phase
   * (z. B. Remediation-Loop in Implementation: Worker -> QA -> Worker
   * -> QA ...). 1 = erste Runde, 2 = erste Wiederholung, usw.
   * Default 1. */
  iteration?: number;
}

/* Substep-Metadaten fuer Visualisierung im Story-Inspector "Ablauf"-Tab.
 *
 * - `optional = true`: Substep ist im Standard-Mode konzeptionell
 *   vorgesehen, wird aber nur dann ausgefuehrt, wenn eine Vorbedingung
 *   eintritt (Beispiel: `feindesign` nur fuer Stories mit erforderlicher
 *   Feindesign-Pflicht; `finding_resolution` nur, wenn QA-Findings
 *   vorliegen).
 * - `loopGroup`: zusammenhaengende Substep-Sequenz, die mehrfach
 *   durchlaufen werden kann (z. B. `remediation` in der Implementation,
 *   `design_iteration` in der Exploration). Substeps mit gleichem Wert
 *   bilden eine Loop-Region; das Phase-UI zeigt einen
 *   Iterations-Counter und eine Return-Markierung. */
export interface SubstepMeta {
  optional?: boolean;
  loopGroup?: string;
}

export interface Story {
  id: string;
  title: string;
  type: StoryType;
  status: StoryStatus;
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
  /* Story-Mode (optional, Default = 'standard'). */
  mode?: Mode;
  /* Aktueller Laufzeit-State; nur belegt fuer 'In Progress'-Stories. */
  runtime?: RuntimeState;
}

/* Execution-Limits (FK-70 §70.6.2): die fuenf Caps zwischen
 * Feasibility und max_allowed_batch. */
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
