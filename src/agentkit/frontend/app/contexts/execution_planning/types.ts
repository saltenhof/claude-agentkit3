import type { StorySummary } from '../story_context_manager/types';

export interface DependencyEdge {
  from_story_id?: string;
  to_story_id?: string;
  story_id?: string;
  depends_on_story_id?: string;
  kind: 'hard' | 'soft';
}

export interface ExecutionInputStack {
  story: StorySummary;
  predecessor?: StorySummary | null;
  successor?: StorySummary | null;
}

export interface ExecutionInputSnapshot {
  project_key: string;
  running: ExecutionInputStack[];
  eligible_ready: ExecutionInputStack[];
  total_ready: number;
  global_slots_left: number;
}

export interface ExecutionLimits {
  project_key: string;
  repo_parallel_cap: number;
  merge_risk_cap: number;
  max_parallel_agent_cap: number;
  llm_pool_cap: number;
  ci_capacity_cap: number;
}
