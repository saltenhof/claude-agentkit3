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

/* ---- Execution-Limits-Defaults ---- */

export const DEFAULT_EXECUTION_LIMITS: ExecutionLimits = {
  repoParallelCap: 3,
  mergeRiskCap: 5,
  apiRateLimitCap: 30,
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
    key: 'apiRateLimitCap',
    label: 'API Rate Limit Cap',
    description: 'Max. parallele API-Aufrufe gegen externe Anbieter (Claude, GitHub).',
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
