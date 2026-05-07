export interface ExecutionLimits {
  repoParallelCap: number;
  mergeRiskCap: number;
  apiRateLimitCap: number;
  llmPoolCap: number;
  ciCapacityCap: number;
}

export const DEFAULT_EXECUTION_LIMITS: ExecutionLimits = {
  repoParallelCap: 3,
  mergeRiskCap: 5,
  apiRateLimitCap: 30,
  llmPoolCap: 10,
  ciCapacityCap: 4,
};

export interface ExecutionLimitDescriptor {
  key: keyof ExecutionLimits;
  label: string;
  description: string;
}

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
