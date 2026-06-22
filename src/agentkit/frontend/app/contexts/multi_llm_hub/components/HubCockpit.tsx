import { AlertTriangle, Activity, MessagesSquare } from 'lucide-react';
import { useMemo, useState } from 'react';
import type { ReactElement } from 'react';

import type { HubBackendMetric, HubSession, HubSessionStatus, HubStatusSnapshot } from '../types';

interface HubCockpitProps {
  status: HubStatusSnapshot | null;
  sessions: readonly HubSession[];
  error: string | null;
}

export function HubCockpit({ status, sessions, error }: Readonly<HubCockpitProps>): ReactElement {
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(sessions[0]?.session_id ?? null);
  const selectedSession = sessions.find((session) => session.session_id === selectedSessionId) ?? sessions[0] ?? null;
  const activeSessions = sessions.filter((session) => session.status === 'active');
  const totals = useMemo(() => buildBackendTotals(status?.backends ?? []), [status]);

  return (
    <div className="hub-cockpit">
      <header className="context-head">
        <div>
          <p className="eyebrow">Multi-LLM Hub</p>
          <h2>Hub Cockpit</h2>
        </div>
        <div className="context-health" data-health={status?.health.status ?? 'down'}>
          <Activity size={16} />
          <span>{status?.health.status ?? 'unavailable'}</span>
        </div>
      </header>

      {error !== null && (
        <div className="context-warning">
          <AlertTriangle size={17} />
          <span>{error}</span>
        </div>
      )}

      <section className="hub-summary-grid">
        <HubStat label="Active Sessions" value={String(activeSessions.length)} />
        <HubStat label="Slot Usage" value={`${totals.used}/${totals.total}`} />
        <HubStat label="Free Slots" value={String(Math.max(totals.total - totals.used, 0))} />
        <HubStat label="Responses" value={String(totals.responses)} />
      </section>

      <section className="hub-backend-grid">
        {(status?.backends ?? []).map((backend) => <BackendCard backend={backend} key={backend.name} />)}
        {status?.backends.length === 0 && <EmptyPanel text="Der Hub liefert aktuell keine Backend-Metriken." />}
      </section>

      <section className="hub-workbench-grid">
        <aside className="hub-session-panel">
          <header>
            <div>
              <h3>Sessions</h3>
              <span>{sessions.length} geladene Sessions</span>
            </div>
            <MessagesSquare size={18} />
          </header>
          <div className="hub-session-list">
            {sessions.map((session) => (
              <button
                className={session.session_id === selectedSession?.session_id ? 'active' : ''}
                key={session.session_id}
                type="button"
                onClick={() => setSelectedSessionId(session.session_id)}
              >
                <span>
                  <strong>{session.owner}</strong>
                  <small>{session.description}</small>
                </span>
                <span className="hub-session-meta">
                  <StatusBadge status={session.status} />
                  <small>{session.llms.join(' · ')}</small>
                </span>
              </button>
            ))}
            {sessions.length === 0 && <EmptyPanel text="Keine Hub-Sessions vorhanden." />}
          </div>
        </aside>

        <section className="hub-session-detail">
          {selectedSession === null ? (
            <EmptyPanel text="Keine Session ausgewählt." />
          ) : (
            <>
              <header>
                <div>
                  <h3>{selectedSession.description}</h3>
                  <span>{selectedSession.session_id}</span>
                </div>
                <StatusBadge status={selectedSession.status} />
              </header>
              <dl className="detail-list">
                <div><dt>Owner</dt><dd>{selectedSession.owner}</dd></div>
                <div><dt>LLMs</dt><dd>{selectedSession.llms.join(', ')}</dd></div>
                <div><dt>Created</dt><dd>{formatDate(selectedSession.created_at)}</dd></div>
                <div><dt>Last Activity</dt><dd>{formatDate(selectedSession.last_activity)}</dd></div>
                <div><dt>Resumable</dt><dd>{selectedSession.resumable ? 'yes' : 'no'}</dd></div>
              </dl>
            </>
          )}
        </section>
      </section>
    </div>
  );
}

function BackendCard({ backend }: Readonly<{ backend: HubBackendMetric }>): ReactElement {
  const slotPercent = backend.slots_total === 0 ? 0 : Math.round((backend.slots_in_use / backend.slots_total) * 100);
  return (
    <article className="hub-backend-card">
      <header>
        <div>
          <strong>{backend.label}</strong>
          <span>{backend.name}</span>
        </div>
        <StatusBadge status={backend.status} />
      </header>
      <div className="hub-slotbar" aria-label={`${backend.label} slot usage`}>
        <span style={{ width: `${slotPercent}%` }} />
      </div>
      <dl>
        <div><dt>Slots</dt><dd>{backend.slots_in_use}/{backend.slots_total}</dd></div>
        <div><dt>Sends</dt><dd>{backend.sends}</dd></div>
        <div><dt>Responses</dt><dd>{backend.responses}</dd></div>
        <div><dt>Avg</dt><dd>{formatDuration(backend.avg_response_ms)}</dd></div>
      </dl>
      <div className="hub-holder-list">
        {backend.holders.length === 0 ? <span>no holder</span> : backend.holders.map((holder) => (
          <span key={`${backend.name}-${holder.session_id}`}>{holder.owner}</span>
        ))}
      </div>
    </article>
  );
}

function HubStat({ label, value }: Readonly<{ label: string; value: string }>): ReactElement {
  return (
    <article className="context-stat">
      <span>{label}</span>
      <strong>{value}</strong>
    </article>
  );
}

function StatusBadge({ status }: Readonly<{ status: HubBackendMetric['status'] | HubSessionStatus }>): ReactElement {
  return <span className="status-badge" data-status={status}>{status}</span>;
}

function EmptyPanel({ text }: Readonly<{ text: string }>): ReactElement {
  return <div className="context-empty">{text}</div>;
}

function buildBackendTotals(backends: readonly HubBackendMetric[]): { total: number; used: number; responses: number } {
  return backends.reduce(
    (totals, backend) => ({
      total: totals.total + backend.slots_total,
      used: totals.used + backend.slots_in_use,
      responses: totals.responses + backend.responses,
    }),
    { total: 0, used: 0, responses: 0 },
  );
}

function formatDuration(ms: number | null): string {
  if (ms === null) {
    return 'n/a';
  }
  return ms < 1000 ? `${ms} ms` : `${Math.round(ms / 1000)} s`;
}

function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString('de-DE', { dateStyle: 'short', timeStyle: 'short' });
}
