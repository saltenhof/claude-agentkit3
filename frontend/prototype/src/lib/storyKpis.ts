export interface StoryCounters {
  total: number;
  finished: number;
  running: number;
  ready: number;
  queue: number;
  blocked: number;
}

export type KpiTone = 'default' | 'warning';

export interface KpiTileData {
  label: string;
  value: number | string;
  suffix?: string;
  tone?: KpiTone;
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
