export type ProjectStatus = 'active' | 'archived';

export interface ProjectSummary {
  project_key: string;
  display_name: string;
  status: ProjectStatus;
}

export interface ProjectModeLock {
  project_key: string;
  mode: 'standard' | 'fast' | 'idle';
}

export interface StoryCounters {
  project_key: string;
  total: number;
  finished: number;
  running: number;
  ready: number;
  queue: number;
  blocked: number;
}
