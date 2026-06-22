export type HubBackendName = 'chatgpt' | 'gemini' | 'grok' | 'qwen' | 'kimi';
export type HubSessionStatus = 'active' | 'released' | 'expired';
export type HubBackendStatus = 'healthy' | 'degraded' | 'unavailable';
export type HubHealthStatus = 'ok' | 'degraded' | 'down';
export type HubBackendHealth = 'ok' | 'error' | 'login_required';

export interface HubHolder {
  session_id: string;
  owner: string;
  description: string;
}

export interface HubSession {
  session_id: string;
  owner: string;
  description: string;
  llms: HubBackendName[];
  status: HubSessionStatus;
  created_at: string;
  last_activity: string;
  resumable: boolean;
}

export interface HubBackendMetric {
  name: HubBackendName;
  label: string;
  status: HubBackendStatus;
  slots_total: number;
  slots_in_use: number;
  sends: number;
  responses: number;
  errors: number;
  avg_response_ms: number | null;
  holders: HubHolder[];
}

export interface HubHealth {
  status: HubHealthStatus;
  version: string | null;
  backends: Partial<Record<HubBackendName, HubBackendHealth>>;
  persistence: 'ok' | 'error';
  uptime_ms: number;
}

export interface HubStatusSnapshot {
  health: HubHealth;
  backends: HubBackendMetric[];
}
