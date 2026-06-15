export type HubBackendStatus = 'healthy' | 'degraded' | 'unavailable';
export type HubSessionStatus = 'active' | 'released' | 'expired';
export type HubSendMode = 'broadcast' | 'group' | 'single';
export type HubBackendName = 'chatgpt' | 'gemini' | 'grok' | 'qwen' | 'kimi';

export interface HubSession {
  session_id: string;
  owner: string;
  status: HubSessionStatus;
  description: string;
  llms: HubBackendName[];
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
  max_response_ms: number | null;
  holders: Array<{ session_id: string; owner: string; description: string }>;
}

export interface HubMessage {
  id: string;
  session_id: string;
  backend?: HubBackendName;
  role: 'user' | 'assistant';
  text: string;
  at: string;
  status?: 'ok' | 'pending' | 'error';
}

export const hubSessions: HubSession[] = [
  {
    session_id: 's-1777776058738-59e0b427',
    owner: 'main-knobel-test',
    status: 'active',
    description: 'Complex combinatorial game theory problem for ChatGPT and Qwen',
    llms: ['chatgpt', 'qwen'],
    created_at: '2026-05-03T02:40:59.164Z',
    last_activity: '2026-05-03T02:41:13.504Z',
    resumable: false,
  },
  {
    session_id: 's-1777700294588-90868825',
    owner: 'uc2a-test-pyramid-discussion',
    status: 'released',
    description: 'UC2A Test-Pyramide Architektur-Diskussion (Round 1: Positionen)',
    llms: ['chatgpt', 'qwen', 'grok'],
    created_at: '2026-05-02T05:38:14.916Z',
    last_activity: '2026-05-02T08:30:18.766Z',
    resumable: true,
  },
  {
    session_id: 's-live-ak3-ui-001',
    owner: 'main-agent-ui-prototype',
    status: 'active',
    description: 'AgentKit UI Prototype Hub Cockpit',
    llms: ['chatgpt', 'gemini', 'qwen'],
    created_at: '2026-05-03T08:16:22.000Z',
    last_activity: '2026-05-03T09:04:18.000Z',
    resumable: false,
  },
  {
    session_id: 's-live-uc2a-guard-002',
    owner: 'evil-kneivel',
    status: 'active',
    description: 'UC2A contract drift detector implementation',
    llms: ['grok', 'qwen'],
    created_at: '2026-05-03T07:42:11.000Z',
    last_activity: '2026-05-03T08:57:02.000Z',
    resumable: false,
  },
  {
    session_id: 's-1777668697411-082cc5e2',
    owner: 'codex-main-uc2a-b90-review',
    status: 'released',
    description: 'Review b90c21d unknown target handling',
    llms: ['chatgpt', 'gemini'],
    created_at: '2026-05-01T20:51:38.009Z',
    last_activity: '2026-05-01T20:52:41.718Z',
    resumable: true,
  },
  {
    session_id: 's-1777582385389-81681a5b',
    owner: 'llm-discussion-uc2a-restructure',
    status: 'released',
    description: 'Multi-LLM debate UC2A rule extraction approach restructuring',
    llms: ['chatgpt', 'gemini', 'grok', 'qwen', 'kimi'],
    created_at: '2026-04-30T20:53:05.790Z',
    last_activity: '2026-04-30T22:14:12.801Z',
    resumable: true,
  },
];

export const hubBackends: HubBackendMetric[] = [
  {
    name: 'chatgpt',
    label: 'ChatGPT',
    status: 'healthy',
    slots_total: 3,
    slots_in_use: 1,
    sends: 16,
    responses: 16,
    errors: 0,
    avg_response_ms: 64985,
    max_response_ms: 125598,
    holders: [{ session_id: 's-1777776058738-59e0b427', owner: 'main-knobel-test', description: 'Complex combinatorial game theory problem for ChatGPT and Qwen' }],
  },
  {
    name: 'gemini',
    label: 'Gemini',
    status: 'healthy',
    slots_total: 3,
    slots_in_use: 0,
    sends: 4,
    responses: 3,
    errors: 1,
    avg_response_ms: 88420,
    max_response_ms: 141200,
    holders: [{ session_id: 's-live-ak3-ui-001', owner: 'main-agent-ui-prototype', description: 'AgentKit UI Prototype Hub Cockpit' }],
  },
  {
    name: 'grok',
    label: 'Grok',
    status: 'healthy',
    slots_total: 3,
    slots_in_use: 1,
    sends: 3,
    responses: 3,
    errors: 0,
    avg_response_ms: 59477,
    max_response_ms: 95073,
    holders: [{ session_id: 's-live-uc2a-guard-002', owner: 'evil-kneivel', description: 'UC2A contract drift detector implementation' }],
  },
  {
    name: 'qwen',
    label: 'Qwen',
    status: 'degraded',
    slots_total: 3,
    slots_in_use: 3,
    sends: 3,
    responses: 3,
    errors: 0,
    avg_response_ms: 134689,
    max_response_ms: 165868,
    holders: [
      { session_id: 's-1777776058738-59e0b427', owner: 'main-knobel-test', description: 'Complex combinatorial game theory problem for ChatGPT and Qwen' },
      { session_id: 's-live-ak3-ui-001', owner: 'main-agent-ui-prototype', description: 'AgentKit UI Prototype Hub Cockpit' },
      { session_id: 's-live-uc2a-guard-002', owner: 'evil-kneivel', description: 'UC2A contract drift detector implementation' },
    ],
  },
  {
    name: 'kimi',
    label: 'Kimi',
    status: 'healthy',
    slots_total: 2,
    slots_in_use: 0,
    sends: 0,
    responses: 0,
    errors: 1,
    avg_response_ms: null,
    max_response_ms: null,
    holders: [],
  },
];

export const initialHubMessages: HubMessage[] = [
  {
    id: 'hub-msg-1',
    session_id: 's-live-ak3-ui-001',
    role: 'user',
    text: 'Bewertet bitte den geplanten Hub-Cockpit-Flow: Metriken, Sessions und Multi-Target-Chat in einer Arbeitsansicht.',
    at: '09:02',
  },
  {
    id: 'hub-msg-2',
    session_id: 's-live-ak3-ui-001',
    backend: 'chatgpt',
    role: 'assistant',
    text: 'Die Trennung in Session-Liste, Backend-Metriken und Antwortspalten ist tragfaehig. Wichtig ist ein klarer Send-Modus, damit Broadcast nicht mit Single-Target vermischt wird.',
    at: '09:03',
    status: 'ok',
  },
  {
    id: 'hub-msg-3',
    session_id: 's-live-ak3-ui-001',
    backend: 'gemini',
    role: 'assistant',
    text: 'Fuer lange Reviews sollte jede Backend-Antwort eine eigene Spalte behalten. Eine gemischte Chat-Timeline waere nur als Audit-Log sinnvoll.',
    at: '09:03',
    status: 'ok',
  },
  {
    id: 'hub-msg-4',
    session_id: 's-live-ak3-ui-001',
    backend: 'qwen',
    role: 'assistant',
    text: 'Targets sollten explizit als Backend-Set sichtbar sein. Dadurch wird der REST-Body fuer broadcast, target und targets auch im UI nachvollziehbar.',
    at: '09:04',
    status: 'ok',
  },
];
