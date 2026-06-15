/*
 * Story selectors — pure functions that derive views from the story model.
 *
 * Every UI view (KpiBar, ReadyStackView, ExecutionLimitsView, future
 * phase stepper / substep list / etc.) is a thin wrapper around one
 * of these selector functions — components contain no filter or
 * aggregation logic of their own.
 */

import type {
  ExecutionLimitDescriptor,
  ExecutionLimits,
  Mode,
  Phase,
  Story,
  Substep,
} from './storyModel';
import {
  PHASE_ORDER,
  PHASE_SUBSTEP_SEQUENCE,
  PHASE_SUBSTEP_SEQUENCE_FAST,
  SUBSTEP_META,
} from './storyFixtures';

/* ---- KPI-Selector ---- */

export interface StoryCounters {
  total: number;
  finished: number;
  running: number;
  ready: number;
  queue: number;
  blocked: number;
}

export interface KpiTileData {
  label: string;
  value: number | string;
  suffix?: string;
  tone?: 'default' | 'warning';
}

export function selectStoryCounters(stories: Story[]): StoryCounters {
  const doneIds = new Set(
    stories.filter((s) => s.status === 'Done').map((s) => s.id),
  );
  const hasOpenDependency = (story: Story): boolean =>
    story.dependencies.some((dep) => !doneIds.has(dep));
  const isReady = (story: Story): boolean =>
    story.status === 'Approved' && !story.blocker && !hasOpenDependency(story);
  const isBlocked = (story: Story): boolean =>
    story.status === 'Backlog' ||
    (story.status === 'Approved' && (Boolean(story.blocker) || hasOpenDependency(story)));

  return {
    total: stories.length,
    running: stories.filter((s) => s.status === 'In Progress').length,
    finished: stories.filter((s) => s.status === 'Done').length,
    ready: stories.filter(isReady).length,
    queue: stories.filter((s) => s.status === 'Approved').length,
    blocked: stories.filter(isBlocked).length,
  };
}

export function buildStoryKpiTiles(counters: StoryCounters): KpiTileData[] {
  const donePercent =
    counters.total > 0 ? Math.round((counters.finished / counters.total) * 100) : 0;
  return [
    { label: 'Total Stories', value: counters.total },
    { label: 'Done', value: donePercent, suffix: '%' },
    { label: 'Ready', value: counters.ready },
    { label: 'In Progress', value: counters.running },
    { label: 'Blocked', value: counters.blocked, tone: 'warning' },
  ];
}

/* ---- Ready-Stack-Selector ---- */

export interface ReadyStack {
  story: Story;
  predecessor: Story | null;
  successor: Story | null;
}

export function selectReadyStacks(stories: Story[]): ReadyStack[] {
  const doneIds = new Set(
    stories.filter((s) => s.status === 'Done').map((s) => s.id),
  );
  const hasOpenDependency = (story: Story): boolean =>
    story.dependencies.some((dep) => !doneIds.has(dep));
  const isReady = (story: Story): boolean =>
    story.status === 'Approved' && !story.blocker && !hasOpenDependency(story);

  const successorsByStoryId = new Map<string, Story[]>();
  for (const candidate of stories) {
    for (const depId of candidate.dependencies) {
      const list = successorsByStoryId.get(depId) ?? [];
      list.push(candidate);
      successorsByStoryId.set(depId, list);
    }
  }

  const findById = (id: string): Story | null =>
    stories.find((s) => s.id === id) ?? null;

  return stories.filter(isReady).map((story) => ({
    story,
    predecessor:
      story.dependencies.length > 0 ? findById(story.dependencies[0]) : null,
    successor: successorsByStoryId.get(story.id)?.[0] ?? null,
  }));
}

/* ---- Execution-Input selector ----
 *
 * Concept anchor: FK-70 §70.8a (Execution-Input top surface,
 * dual interface).
 *
 * Returns exactly the stories that are operationally relevant:
 *   - running (In-Progress) stories
 *   - Ready stories after triage against the execution limits, i.e.
 *     not "all theoretically ready" but "these may start now".
 *
 * Triage:
 *   1. globalCap = min(mergeRiskCap, maxParallelAgentCap, llmPoolCap,
 *      ciCapacityCap). Subtract the number of already-running stories
 *      -> globalSlotsLeft.
 *   2. Per repo: repoParallelCap - already running in that repo.
 *   3. Bucket by repo, sorted internally by criticalPath DESC,
 *      then story number ASC.
 *   4. Round-robin across repos: each repo may contribute its next
 *      card in turn until globalSlotsLeft is exhausted or no repo
 *      has remaining slots / cards.
 *
 * Determinism: same input -> same output (sorted repo iteration and
 * story IDs).
 *
 * This function is the single-source triage. In the backend it must
 * feed exactly two adapters (FK-70 §70.8a, FK-91 §91.1a):
 *   - GET /v1/projects/{project_key}/execution-input/snapshot
 *     (frontend, returns the full pick result)
 *   - GET /v1/projects/{project_key}/execution-input/next
 *     (orchestrator skill, returns the first card of the pick result)
 * A duplicate implementation of the triage logic is explicitly
 * prohibited.
 */

export interface ExecutionInputSnapshot {
  running: ReadyStack[];
  eligibleReady: ReadyStack[];
  totalReady: number;
  globalSlotsLeft: number;
}

function getStorySerial(storyId: string): number {
  const match = storyId.match(/(\d+)$/);
  return match ? Number.parseInt(match[1], 10) : 0;
}

function getRepoKey(story: Story): string {
  return story.primaryRepo ?? story.repo;
}

function buildSuccessorIndex(stories: Story[]): Map<string, Story[]> {
  const index = new Map<string, Story[]>();
  for (const candidate of stories) {
    for (const depId of candidate.dependencies) {
      const list = index.get(depId) ?? [];
      list.push(candidate);
      index.set(depId, list);
    }
  }
  return index;
}

function buildStackFor(
  story: Story,
  stories: Story[],
  successors: Map<string, Story[]>,
): ReadyStack {
  const findById = (id: string) => stories.find((s) => s.id === id) ?? null;
  return {
    story,
    predecessor:
      story.dependencies.length > 0 ? findById(story.dependencies[0]) : null,
    successor: successors.get(story.id)?.[0] ?? null,
  };
}

export function selectExecutionInput(
  stories: Story[],
  limits: ExecutionLimits,
): ExecutionInputSnapshot {
  const successors = buildSuccessorIndex(stories);

  /* In-Progress (= already delegated): slots already occupied. */
  const runningStories = stories.filter((s) => s.status === 'In Progress');
  const running: ReadyStack[] = runningStories.map((story) =>
    buildStackFor(story, stories, successors),
  );

  /* Per repo: currently occupied slots. */
  const runningPerRepo = new Map<string, number>();
  for (const story of runningStories) {
    const repo = getRepoKey(story);
    runningPerRepo.set(repo, (runningPerRepo.get(repo) ?? 0) + 1);
  }

  /* Global slot cap derived from the caps, minus running stories. */
  const globalCap = Math.min(
    limits.mergeRiskCap,
    limits.maxParallelAgentCap,
    limits.llmPoolCap,
    limits.ciCapacityCap,
  );
  const globalSlotsLeft = Math.max(0, globalCap - runningStories.length);

  /* All technically ready stories. */
  const allReady = selectReadyStacks(stories);

  /* Triage: bucket by repo, sort, pick round-robin. */
  const buckets = new Map<string, ReadyStack[]>();
  for (const stack of allReady) {
    const repo = getRepoKey(stack.story);
    const list = buckets.get(repo) ?? [];
    list.push(stack);
    buckets.set(repo, list);
  }
  for (const list of buckets.values()) {
    list.sort((a, b) => {
      if (a.story.criticalPath !== b.story.criticalPath) {
        return a.story.criticalPath ? -1 : 1;
      }
      return getStorySerial(a.story.id) - getStorySerial(b.story.id);
    });
  }

  const sortedRepos = Array.from(buckets.keys()).sort();
  const repoUsed = new Map<string, number>();
  const eligibleReady: ReadyStack[] = [];

  let madeProgress = true;
  while (madeProgress && eligibleReady.length < globalSlotsLeft) {
    madeProgress = false;
    for (const repo of sortedRepos) {
      if (eligibleReady.length >= globalSlotsLeft) break;
      const used = repoUsed.get(repo) ?? 0;
      const repoSlotsLeft = Math.max(
        0,
        limits.repoParallelCap - (runningPerRepo.get(repo) ?? 0) - used,
      );
      if (repoSlotsLeft <= 0) continue;
      const bucket = buckets.get(repo) ?? [];
      if (used >= bucket.length) continue;
      eligibleReady.push(bucket[used]);
      repoUsed.set(repo, used + 1);
      madeProgress = true;
    }
  }

  return {
    running,
    eligibleReady,
    totalReady: allReady.length,
    globalSlotsLeft,
  };
}

/* ---- Mode-Lock selector (FK-24 §24.3.3) ----
 *
 * Only one mode may be active at runtime across the whole project.
 * The UI value mirrors the `mode_lock` of the control plane: it is
 * set as soon as at least one In-Progress story is running; the mode
 * of those stories determines the lock. When no story is in progress
 * the lock is `null` -> "Idle".
 */

export type ProjectModeLock = Mode | null;

export function selectActiveProjectMode(stories: Story[]): ProjectModeLock {
  for (const story of stories) {
    if (story.status !== 'In Progress') continue;
    return story.mode ?? 'standard';
  }
  return null;
}

/* ---- Flow selectors for the Story Inspector "Ablauf" tab ---- */

/* Substep states in the flowchart.
 *
 * - `done`     : completed successfully in this or a prior iteration
 * - `active`   : currently being executed (runtime points here)
 * - `pending`  : not yet reached (in this iteration)
 * - `skipped`  : skipped due to mode / phase jump (e.g. Exploration in Fast)
 * - `optional-pending` : optional substep, precondition still open
 * - `optional-skipped` : optional substep, precondition was negative
 *                        (substep was not executed) */
export type FlowState =
  | 'done'
  | 'active'
  | 'pending'
  | 'skipped'
  | 'optional-pending'
  | 'optional-skipped'
  /* Hold-states (FK-72 §72.14.6 / AC10f): the phase is stalled and rendered with
   * a distinct hold color + state_reason, never collapsed to 'active'. */
  | 'paused'
  | 'escalated'
  | 'failed';

export interface FlowSubstep {
  substep: Substep;
  state: FlowState;
  optional: boolean;
  loopGroup?: string;
  /* Position within the loop group (1-based), only set when
   * `loopGroup` is set. Helps the UI identify loop start and end. */
  loopPosition?: number;
  loopSize?: number;
}

export interface FlowPhase {
  phase: Phase;
  state: FlowState;
  /* Human-readable reason for a hold-state (paused/escalated/failed), carried
   * verbatim from the flow read-model's `state_reason` (AC10f). */
  stateReason?: string;
  substeps: FlowSubstep[];
  /* Current iteration of the active loop group in this phase
   * (only set when the phase is active AND the active substep is
   * part of a loop group). 1 = first pass, 2+ shown as "Round N". */
  iteration?: number;
  iterationLoopGroup?: string;
}

export function selectStorySubstepSequence(mode: Mode): Record<Phase, Substep[]> {
  return mode === 'fast' ? PHASE_SUBSTEP_SEQUENCE_FAST : PHASE_SUBSTEP_SEQUENCE;
}

/* Returns the UI metadata for a substep depending on the story mode.
 *
 * In Fast mode all loop groups are dropped: Exploration is OUT and
 * therefore so is `design_iteration`; the `remediation` loop in
 * Implementation does not exist without QA feedback (layers 2-4 +
 * feedback OUT) because without feedback there is nothing to
 * re-iterate. Source: AG3-018 §Mode-profile. */
function metaFor(substep: Substep, mode: Mode): { optional: boolean; loopGroup?: string } {
  const meta = SUBSTEP_META[substep];
  if (mode === 'fast') {
    return { optional: meta?.optional ?? false };
  }
  return {
    optional: meta?.optional ?? false,
    loopGroup: meta?.loopGroup,
  };
}

/* Annotates a list of substep-IDs with loop-position / loop-size, so
 * the UI can render the boundaries of each loop region. */
function annotateLoopPositions(
  substepIds: Substep[],
  mode: Mode,
): Array<{ substep: Substep; loopPosition?: number; loopSize?: number }> {
  /* Loop region = the maximal contiguous range sharing the same
   * `loopGroup` value. Substeps without `loopGroup` close the region. */
  const result: Array<{ substep: Substep; loopPosition?: number; loopSize?: number }> = [];
  let regionStart = -1;
  let regionGroup: string | undefined;
  const flushRegion = (endExclusive: number) => {
    if (regionStart === -1 || regionGroup === undefined) return;
    const size = endExclusive - regionStart;
    for (let i = regionStart; i < endExclusive; i += 1) {
      result[i].loopPosition = i - regionStart + 1;
      result[i].loopSize = size;
    }
    regionStart = -1;
    regionGroup = undefined;
  };
  substepIds.forEach((substep, index) => {
    result.push({ substep });
    const group = metaFor(substep, mode).loopGroup;
    if (group !== regionGroup) {
      flushRegion(index);
      if (group) {
        regionStart = index;
        regionGroup = group;
      }
    }
  });
  flushRegion(substepIds.length);
  return result;
}

function buildSubstep(
  substep: Substep,
  state: FlowState,
  mode: Mode,
  loopPosition?: number,
  loopSize?: number,
): FlowSubstep {
  const { optional, loopGroup } = metaFor(substep, mode);
  /* `pending` on optional substeps is promoted to `optional-pending`
   * so the UI state stays clearly distinct from mandatory pending substeps. */
  const finalState: FlowState =
    optional && state === 'pending' ? 'optional-pending' : state;
  return {
    substep,
    state: finalState,
    optional,
    loopGroup,
    loopPosition,
    loopSize,
  };
}

export function selectStoryFlow(story: Story): FlowPhase[] {
  const mode: Mode = story.mode ?? 'standard';
  const sequence = selectStorySubstepSequence(mode);
  const status = story.status;
  const runtime = story.runtime;

  const allDone = status === 'Done';
  const noProgress = status === 'Backlog' || status === 'Approved' || status === 'Cancelled';

  return PHASE_ORDER.map((phase): FlowPhase => {
    const substepIds = sequence[phase];
    const annotated = annotateLoopPositions(substepIds, mode);
    const isExplorationSkippedByMode = phase === 'exploration' && mode === 'fast';

    if (isExplorationSkippedByMode) {
      /* Fast mode drops Exploration entirely. We show the phase with
       * a "skipped in Fast mode" pill but without the substep list —
       * the user should not see what *theoretically* would run in
       * Exploration when they are not in Exploration at all. */
      return {
        phase,
        state: 'skipped',
        substeps: [],
      };
    }

    if (allDone) {
      return {
        phase,
        state: 'done',
        substeps: annotated.map(({ substep, loopPosition, loopSize }) =>
          buildSubstep(substep, 'done', mode, loopPosition, loopSize),
        ),
      };
    }

    if (noProgress || !runtime) {
      return {
        phase,
        state: 'pending',
        substeps: annotated.map(({ substep, loopPosition, loopSize }) =>
          buildSubstep(substep, 'pending', mode, loopPosition, loopSize),
        ),
      };
    }

    const runtimePhaseIndex = PHASE_ORDER.indexOf(runtime.phase);
    const phaseIndex = PHASE_ORDER.indexOf(phase);

    if (phaseIndex < runtimePhaseIndex) {
      return {
        phase,
        state: 'done',
        substeps: annotated.map(({ substep, loopPosition, loopSize }) =>
          buildSubstep(substep, 'done', mode, loopPosition, loopSize),
        ),
      };
    }

    if (phaseIndex > runtimePhaseIndex) {
      return {
        phase,
        state: 'pending',
        substeps: annotated.map(({ substep, loopPosition, loopSize }) =>
          buildSubstep(substep, 'pending', mode, loopPosition, loopSize),
        ),
      };
    }

    /* Active phase. Substeps before the runtime point are `done` in
     * this iteration. Optional substeps that are not the runtime point
     * and lie before it could have been executed or skipped in a real
     * run. The prototype does not track this — we optimistically assume
     * `done`, except for `feindesign` which we deliberately show as
     * `optional-skipped` for the demo as soon as the runtime point
     * is past the substep. This illustrates the difference between
     * "executed" and "skipped as unnecessary". */
    const activeIndex = substepIds.indexOf(runtime.substep);
    const activeMeta = activeIndex >= 0 ? metaFor(substepIds[activeIndex], mode) : undefined;

    const substeps: FlowSubstep[] = annotated.map(({ substep, loopPosition, loopSize }, index) => {
      if (activeIndex === -1) {
        return buildSubstep(substep, 'pending', mode, loopPosition, loopSize);
      }
      if (index < activeIndex) {
        const { optional } = metaFor(substep, mode);
        if (optional && substep === 'feindesign') {
          return buildSubstep(substep, 'optional-skipped', mode, loopPosition, loopSize);
        }
        return buildSubstep(substep, 'done', mode, loopPosition, loopSize);
      }
      if (index === activeIndex) {
        return buildSubstep(substep, 'active', mode, loopPosition, loopSize);
      }
      return buildSubstep(substep, 'pending', mode, loopPosition, loopSize);
    });

    const iteration = runtime.iteration ?? 1;
    return {
      phase,
      state: activeIndex === -1 ? 'pending' : 'active',
      substeps,
      iteration,
      iterationLoopGroup: activeMeta?.loopGroup,
    };
  });
}

/* ---- Analytics selectors (project-wide aggregation) ----
 *
 * Returns per metric a four-value view: avg / min / max / p90.
 * The KPI page shows this in the overview tab; the time-series tab
 * uses `selectKpiDailySeries` (see below) as its trend source. */

export interface KpiStat {
  key: string;
  label: string;
  unit?: string;
  avg: number;
  min: number;
  max: number;
  p90: number;
}

function parseProcessingMinutes(value: string | undefined): number | null {
  if (!value) return null;
  const match = value.match(/(\d+(?:[.,]\d+)?)/);
  if (!match) return null;
  const num = Number.parseFloat(match[1].replace(',', '.'));
  return Number.isFinite(num) ? num : null;
}

function quantile(values: number[], q: number): number {
  if (values.length === 0) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const pos = (sorted.length - 1) * q;
  const base = Math.floor(pos);
  const rest = pos - base;
  if (sorted[base + 1] !== undefined) {
    return sorted[base] + rest * (sorted[base + 1] - sorted[base]);
  }
  return sorted[base];
}

function stat(key: string, label: string, values: number[], unit?: string): KpiStat {
  if (values.length === 0) {
    return { key, label, unit, avg: 0, min: 0, max: 0, p90: 0 };
  }
  const sum = values.reduce((acc, v) => acc + v, 0);
  return {
    key,
    label,
    unit,
    avg: sum / values.length,
    min: Math.min(...values),
    max: Math.max(...values),
    p90: quantile(values, 0.9),
  };
}

/* Synthetic QA solving rate, consistent with the inspector heuristic.
 * Does not apply any Fast-mode-specific special logic (Fast stories
 * carry neither Exploration QA nor Implementation QA in a form that
 * can be statistically separated here). */
function syntheticSolvingRate(story: Story, phase: 'exploration' | 'implementation'): number | null {
  if (story.mode === 'fast' && phase === 'exploration') return null;
  const rounds = phase === 'exploration' ? story.qaRoundsExploration ?? 0 : story.qaRoundsImplementation ?? story.qaRounds;
  if (rounds === 0) {
    return story.status === 'Done' ? 100 : null;
  }
  const base = phase === 'exploration' ? 70 : 72;
  const step = phase === 'exploration' ? 10 : 8;
  return Math.min(100, base + rounds * step);
}

export function selectProjectKpiStats(stories: Story[]): KpiStat[] {
  /* Aggregate only operationally relevant stories: Done and In Progress
   * (Backlog/Approved yield no meaningful values). */
  const relevant = stories.filter((s) => s.status === 'Done' || s.status === 'In Progress');

  const runtimeTotals = relevant.map((s) => parseProcessingMinutes(s.processingTime)).filter((v): v is number => v !== null);
  const runtimeExpl = runtimeTotals.map((v, i) => (relevant[i].mode === 'fast' ? 0 : v * 0.2));
  const runtimeImpl = runtimeTotals.map((v, i) => (relevant[i].mode === 'fast' ? v * 0.75 : v * 0.6));
  const runtimeClosure = runtimeTotals.map((v, i) => (relevant[i].mode === 'fast' ? v * 0.25 : v * 0.2));

  const qaRoundsExpl = relevant.map((s) => s.qaRoundsExploration ?? 0);
  const qaRoundsImpl = relevant.map((s) => s.qaRoundsImplementation ?? s.qaRounds);

  /* Tokens: synthetic from QA rounds + in-progress penalty,
   * consistent with the inspector logic (see KpiTab). */
  const tokensIn = relevant.map((s) => Math.round(s.qaRounds * 22000 + 8000));
  const tokensOut = relevant.map((s) => Math.round(s.qaRounds * 8000 + 3000));
  const tokensTotal = tokensIn.map((v, i) => v + tokensOut[i]);
  const tokensCached = tokensIn.map((v) => Math.round(v * 0.32));

  const solvingExpl = relevant
    .map((s) => syntheticSolvingRate(s, 'exploration'))
    .filter((v): v is number => v !== null);
  const solvingImpl = relevant
    .map((s) => syntheticSolvingRate(s, 'implementation'))
    .filter((v): v is number => v !== null);

  return [
    stat('runtime_total', 'Laufzeit Total', runtimeTotals, 'min'),
    stat('runtime_exploration', 'Laufzeit Exploration', runtimeExpl, 'min'),
    stat('runtime_implementation', 'Laufzeit Implementation', runtimeImpl, 'min'),
    stat('runtime_closure', 'Laufzeit Closure', runtimeClosure, 'min'),
    stat('tokens_total', 'Token Total', tokensTotal),
    stat('tokens_in', 'Token In', tokensIn),
    stat('tokens_out', 'Token Out', tokensOut),
    stat('tokens_cached', 'Token Cached', tokensCached),
    stat('qa_rounds_exploration', 'QA-Runden Exploration', qaRoundsExpl),
    stat('solving_rate_exploration', 'Solving Rate Exploration', solvingExpl, '%'),
    stat('qa_rounds_implementation', 'QA-Runden Implementation', qaRoundsImpl),
    stat('solving_rate_implementation', 'Solving Rate Implementation', solvingImpl, '%'),
  ];
}

/* ---- Daily-series synthesis ----
 *
 * The backend snapshot will later deliver real per-day aggregations.
 * Until then we synthesize the last N calendar days from the story
 * corpus: per day a deterministic value is computed that approximates
 * the real values and varies by a seed-based noise term. */

export interface KpiDailyPoint {
  date: string; // ISO YYYY-MM-DD
  values: Record<string, number>;
}

function seededNoise(seed: number): number {
  /* Linear congruential pseudo-random; reproducible per day. */
  const x = Math.sin(seed * 9301 + 49297) * 233280;
  return x - Math.floor(x);
}

export function selectKpiDailySeries(stories: Story[], days = 30): KpiDailyPoint[] {
  const base = selectProjectKpiStats(stories);
  const baseByKey = new Map(base.map((s) => [s.key, s] as const));
  const today = new Date('2026-05-11T00:00:00Z');
  const points: KpiDailyPoint[] = [];
  for (let offset = days - 1; offset >= 0; offset -= 1) {
    const day = new Date(today.getTime() - offset * 24 * 60 * 60 * 1000);
    const iso = day.toISOString().slice(0, 10);
    const wave = Math.sin(offset / 4) * 0.15;
    const values: Record<string, number> = {};
    for (const s of base) {
      const noise = seededNoise(offset * 17 + s.key.length);
      const swing = (noise - 0.5) * 0.25 + wave;
      const center = (baseByKey.get(s.key)?.avg ?? 0);
      let value = center * (1 + swing);
      if (s.unit === '%') value = Math.max(0, Math.min(100, value));
      values[s.key] = Math.round(value * 100) / 100;
    }
    points.push({ date: iso, values });
  }
  return points;
}

/* ---- Execution-Limits-Defaults ---- */

export const DEFAULT_EXECUTION_LIMITS: ExecutionLimits = {
  repoParallelCap: 3,
  mergeRiskCap: 5,
  maxParallelAgentCap: 8,
  llmPoolCap: 10,
  ciCapacityCap: 4,
};

export const EXECUTION_LIMIT_DESCRIPTORS: ExecutionLimitDescriptor[] = [
  {
    key: 'repoParallelCap',
    label: 'Repo Parallel Cap',
    description: 'Max. concurrent stories per repo (guards against merge conflicts).',
  },
  {
    key: 'mergeRiskCap',
    label: 'Merge Risk Cap',
    description: 'Aggregate merge-risk budget across all active stories.',
  },
  {
    key: 'maxParallelAgentCap',
    label: 'Max Parallel Agent Cap',
    description: 'Max. parallel worker-agent sessions across all stories.',
  },
  {
    key: 'llmPoolCap',
    label: 'LLM Pool Cap',
    description: 'Total parallel LLM pool slots available (all backends combined).',
  },
  {
    key: 'ciCapacityCap',
    label: 'CI Capacity Cap',
    description: 'Max. parallel CI and build slots.',
  },
];
