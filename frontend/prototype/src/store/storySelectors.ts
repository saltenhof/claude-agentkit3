/*
 * Story-Selectors — Pure Functions zur Sichtbildung auf dem Story-Modell.
 *
 * Jede UI-Sicht (KpiBar, ReadyStackView, ExecutionLimitsView, kuenftig
 * Phase-Stepper / Substep-Liste / etc.) ist ein duenner Wrapper um
 * eine dieser Selector-Funktionen — Komponenten enthalten keine
 * Filter-/Aggregations-Logik mehr.
 */

import type {
  ExecutionLimitDescriptor,
  ExecutionLimits,
  Story,
} from './storyModel';

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

/* ---- Execution-Input-Selector ----
 *
 * Liefert genau die Stories, die operativ relevant sind:
 *   - laufende (In-Progress) Stories
 *   - Ready-Stories nach Triage gegen die Execution-Limits, also nicht
 *     "alle theoretisch ready" sondern "diese duerfen jetzt starten".
 *
 * Triage:
 *   1. globalCap = min(mergeRiskCap, apiRateLimitCap, llmPoolCap,
 *      ciCapacityCap). Davon wird die Anzahl bereits laufender
 *      Stories abgezogen -> globalSlotsLeft.
 *   2. pro Repo: repoParallelCap - bereits laufend in diesem Repo.
 *   3. Bucketing nach Repo, intern sortiert nach criticalPath DESC,
 *      dann Story-Nummer ASC.
 *   4. Round-Robin ueber Repos: jeder Repo darf abwechselnd seine
 *      naechste Karte bringen, bis globalSlotsLeft erschoepft ist
 *      oder kein Repo mehr Slots/Karten hat.
 *
 * Determinismus: gleiche Eingabe -> gleiche Ausgabe (sortierte
 * Repo-Iteration und Story-IDs).
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

  /* In-Progress (= bereits delegiert): Slots bereits belegt. */
  const runningStories = stories.filter((s) => s.status === 'In Progress');
  const running: ReadyStack[] = runningStories.map((story) =>
    buildStackFor(story, stories, successors),
  );

  /* Pro Repo: aktuell belegte Slots. */
  const runningPerRepo = new Map<string, number>();
  for (const story of runningStories) {
    const repo = getRepoKey(story);
    runningPerRepo.set(repo, (runningPerRepo.get(repo) ?? 0) + 1);
  }

  /* Globaler Slot-Cap aus den Caps, abzueglich Laufender. */
  const globalCap = Math.min(
    limits.mergeRiskCap,
    limits.maxParallelAgentCap,
    limits.llmPoolCap,
    limits.ciCapacityCap,
  );
  const globalSlotsLeft = Math.max(0, globalCap - runningStories.length);

  /* Alle technisch ready Stories. */
  const allReady = selectReadyStacks(stories);

  /* Triage: Bucket nach Repo, sortieren, Round-Robin picken. */
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
    description: 'Max. gleichzeitig laufende Stories pro Repo (gegen Merge-Konflikte).',
  },
  {
    key: 'mergeRiskCap',
    label: 'Merge Risk Cap',
    description: 'Aggregiertes Merge-Risiko-Budget über alle aktiven Stories.',
  },
  {
    key: 'maxParallelAgentCap',
    label: 'Max Parallel Agent Cap',
    description: 'Max. parallel laufende Worker-Agent-Sessions ueber alle Stories hinweg.',
  },
  {
    key: 'llmPoolCap',
    label: 'LLM Pool Cap',
    description: 'Summe der parallel belegbaren LLM-Pool-Slots (alle Backends).',
  },
  {
    key: 'ciCapacityCap',
    label: 'CI Capacity Cap',
    description: 'Max. parallele CI- und Build-Slots.',
  },
];
