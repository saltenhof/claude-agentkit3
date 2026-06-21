export type StoryStatus = 'Backlog' | 'Approved' | 'In Progress' | 'Done' | 'Cancelled';

export interface StoryRuntimeState {
  story_id: string;
  phase: string;
  substep: string;
  iteration?: number | null;
}

export interface StorySummary {
  story_id: string;
  project_key: string;
  title: string;
  type: 'implementation' | 'bugfix' | 'concept' | 'research';
  status: StoryStatus;
  size: 'XS' | 'S' | 'M' | 'L' | 'XL' | 'XXL';
  mode?: 'standard' | 'fast' | null;
  epic: string;
  module: string;
  repos: string[];
  change_impact: string;
  concept_quality: string;
  owner: string;
  wave: number;
  critical_path: boolean;
  risk: 'low' | 'medium' | 'high';
  blocker?: string | null;
  dependencies: string[];
  labels?: string[];
  qa_rounds: number;
  processing_time?: string | null;
  runtime?: StoryRuntimeState | null;
}

export interface StorySpecification {
  need?: string | null;
  solution?: string | null;
  acceptance: string[];
  definition_of_done?: string[];
  concept_refs?: string[];
  guardrail_refs?: string[];
  external_sources?: string[];
}

export interface StoryDetail {
  summary: StorySummary;
  spec: StorySpecification | null;
  evidence: unknown | null;
  telemetry: unknown | null;
  gates: Array<{ label: string; state: 'PASS' | 'WARNING' | 'ERROR' }>;
  phases: Array<{ label: string; state: string; detail?: string | null }>;
  events: Array<{ time: string; type: string; detail?: string | null; severity: string }>;
}
