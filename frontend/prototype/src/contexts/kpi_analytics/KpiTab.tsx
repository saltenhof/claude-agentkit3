import type { StoryDetailResponse } from '../../foundation/bff/client';
import { Info } from '../../design_system/Info';
import { Badge } from '../../design_system/Badge';

export function KpiTab({ storyDetail }: { storyDetail: StoryDetailResponse | null }) {
  const telemetry = storyDetail?.telemetry ?? null;

  if (!telemetry) {
    return (
      <>
        <h2>KPI und Telemetrie</h2>
        <p className="empty">Noch keine KPI-Telemetrie verfügbar.</p>
      </>
    );
  }

  const fmt = (value: number) => value.toLocaleString('de-DE');

  return (
    <>
      <h2>KPI und Telemetrie</h2>
      <div className="kpi-grid">
        <Info label="Run ID" value={telemetry.runId} />
        <Info label="Agent Starts" value={String(telemetry.agentStarts)} />
        <Info label="Increment Commits" value={String(telemetry.incrementCommits)} />
        <Info label="LLM Calls" value={String(telemetry.llmCalls)} />

        <Info label="Token In" value={fmt(telemetry.tokensIn)} />
        <Info label="Token Out" value={fmt(telemetry.tokensOut)} />
        <Info label="Token Total" value={fmt(telemetry.tokensIn + telemetry.tokensOut)} />

        <Info label="Review Requests" value={String(telemetry.reviewRequests)} />
        <Info label="Review Responses" value={String(telemetry.reviewResponses)} />
        <Info label="Review Compliant" value={String(telemetry.reviewCompliant)} />

        <Info label="Adversarial Tests" value={String(telemetry.adversarialTests)} />
        <Info label="Web Calls" value={String(telemetry.webCalls)} />
      </div>

      <section className="detail-section">
        <h3>LLM-/Pool-Aufrufe</h3>
        <div className="pool-list">
          {telemetry.pools.map((pool) => (
            <div className="pool-row" key={`${pool.pool}-${pool.role}`}>
              <span>{pool.pool}</span>
              <small>{pool.role}</small>
              <strong>{pool.calls} calls</strong>
              <Badge
                tone={
                  pool.status === 'FAIL' ? 'danger' : pool.status === 'WARNING' ? 'warning' : 'success'
                }
              >
                {pool.status}
              </Badge>
            </div>
          ))}
        </div>
      </section>

      <section className="detail-section">
        <h3>Telemetry Stream</h3>
        <div className="event-list">
          {(storyDetail?.events ?? []).length > 0 ? (
            (storyDetail?.events ?? []).map((event) => (
              <div className={`event ${event.severity}`} key={`${event.time}-${event.type}`}>
                <span>{event.time}</span>
                <strong>{event.type}</strong>
                <p>{event.detail}</p>
              </div>
            ))
          ) : (
            <p className="empty">Noch keine Runtime-Telemetrie.</p>
          )}
        </div>
      </section>
    </>
  );
}
