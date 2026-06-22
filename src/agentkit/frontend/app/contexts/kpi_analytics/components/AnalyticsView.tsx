import { useMemo, useState } from 'react';
import type { ReactElement } from 'react';

import type { ExecutionLimits } from '../../execution_planning/types';
import type { StorySummary } from '../../story_context_manager/types';
import { countStatus, STORY_STATUS_COLUMNS } from '../../story_context_manager/components/storyFilters';

interface AnalyticsViewProps {
  executionLimits: ExecutionLimits | null;
  stories: readonly StorySummary[];
}

type AnalyticsTab = 'overview' | 'waves';
type MetricStat = {
  key: string;
  label: string;
  unit?: string;
  min: number;
  max: number;
  avg: number;
  p90: number;
};

export function AnalyticsView({ executionLimits, stories }: Readonly<AnalyticsViewProps>): ReactElement {
  const [activeTab, setActiveTab] = useState<AnalyticsTab>('overview');
  const stats = useMemo(() => buildMetricStats(stories), [stories]);
  const byStatus = STORY_STATUS_COLUMNS.map((status) => ({ status, count: countStatus(stories, status) }));
  const byType = countBy(stories, (story) => story.type);
  const byRisk = countBy(stories, (story) => story.risk);
  const waveSeries = useMemo(() => buildWaveSeries(stories), [stories]);

  return (
    <div className="analytics-view">
      <header className="analytics-view__head">
        <div>
          <p className="eyebrow">Project Analytics</p>
          <h2>KPI-Cockpit</h2>
        </div>
        <div className="analytics-tabs" role="tablist" aria-label="Analytics-Sichten">
          <button
            className={activeTab === 'overview' ? 'active' : ''}
            role="tab"
            type="button"
            aria-selected={activeTab === 'overview'}
            onClick={() => setActiveTab('overview')}
          >
            Uebersicht
          </button>
          <button
            className={activeTab === 'waves' ? 'active' : ''}
            role="tab"
            type="button"
            aria-selected={activeTab === 'waves'}
            onClick={() => setActiveTab('waves')}
          >
            Wave-Verlauf
          </button>
        </div>
      </header>

      {activeTab === 'overview' && (
        <AnalyticsOverview
          byRisk={byRisk}
          byStatus={byStatus}
          byType={byType}
          executionLimits={executionLimits}
          stats={stats}
          storyCount={stories.length}
        />
      )}
      {activeTab === 'waves' && <WaveAnalytics series={waveSeries} />}
    </div>
  );
}

function AnalyticsOverview({
  byRisk,
  byStatus,
  byType,
  executionLimits,
  stats,
  storyCount,
}: Readonly<{
  byRisk: Array<{ label: string; count: number }>;
  byStatus: Array<{ status: string; count: number }>;
  byType: Array<{ label: string; count: number }>;
  executionLimits: ExecutionLimits | null;
  stats: readonly MetricStat[];
  storyCount: number;
}>): ReactElement {
  return (
    <section className="analytics-overview">
      <p className="analytics-overview__lead">
        Aggregiert ueber {storyCount} Stories aus dem Backend. Jede Zahl stammt aus Story-Feldern,
        Execution Limits oder deterministischer Aggregation dieser Werte.
      </p>
      <div className="analytics-stat-grid">
        {stats.map((stat) => <KpiStatCard key={stat.key} stat={stat} />)}
      </div>
      <div className="analytics-breakdown-grid">
        <BreakdownCard title="Statusverteilung" rows={byStatus.map(({ status, count }) => ({ label: status, count }))} />
        <BreakdownCard title="Story Types" rows={byType} />
        <BreakdownCard title="Risiko" rows={byRisk} />
        <ExecutionLimitCard executionLimits={executionLimits} />
      </div>
    </section>
  );
}

function KpiStatCard({ stat }: Readonly<{ stat: MetricStat }>): ReactElement {
  return (
    <article className="kpi-stat-card">
      <header>
        <h3>{stat.label}</h3>
      </header>
      <div className="kpi-stat-card__primary">
        <span>Mittelwert</span>
        <strong>{formatNumber(stat.avg)}{stat.unit ?? ''}</strong>
      </div>
      <dl>
        <div><dt>Min</dt><dd>{formatNumber(stat.min)}{stat.unit ?? ''}</dd></div>
        <div><dt>P90</dt><dd>{formatNumber(stat.p90)}{stat.unit ?? ''}</dd></div>
        <div><dt>Max</dt><dd>{formatNumber(stat.max)}{stat.unit ?? ''}</dd></div>
      </dl>
    </article>
  );
}

function BreakdownCard({
  title,
  rows,
}: Readonly<{ title: string; rows: Array<{ label: string; count: number }> }>): ReactElement {
  const max = Math.max(1, ...rows.map((row) => row.count));
  return (
    <section className="analytics-card">
      <h3>{title}</h3>
      {rows.length === 0 ? (
        <p>Keine Daten.</p>
      ) : (
        rows.map((row) => (
          <div className="bar-row" key={row.label}>
            <span>{row.label}</span>
            <div><i style={{ width: `${(row.count / max) * 100}%` }} /></div>
            <strong>{row.count}</strong>
          </div>
        ))
      )}
    </section>
  );
}

function ExecutionLimitCard({ executionLimits }: Readonly<{ executionLimits: ExecutionLimits | null }>): ReactElement {
  return (
    <section className="analytics-card">
      <h3>Execution Limits</h3>
      {executionLimits === null ? (
        <p>Keine Limits geladen.</p>
      ) : (
        <dl className="limit-grid">
          {Object.entries(executionLimits)
            .filter(([key]) => key !== 'project_key')
            .map(([key, value]) => (
              <div key={key}>
                <dt>{key}</dt>
                <dd>{value}</dd>
              </div>
            ))}
        </dl>
      )}
    </section>
  );
}

function WaveAnalytics({ series }: Readonly<{ series: Array<{ wave: number; total: number; done: number; ready: number }> }>): ReactElement {
  const max = Math.max(1, ...series.map((point) => point.total));
  const points = series.map((point, index) => {
    const x = series.length === 1 ? 50 : 12 + (index / (series.length - 1)) * 76;
    const y = 86 - (point.total / max) * 66;
    return `${x},${y}`;
  });

  return (
    <section className="analytics-timeseries">
      <div className="analytics-timeseries__controls">
        <div>
          <span className="eyebrow">Planungsdimension</span>
          <strong>Wave-Verlauf</strong>
        </div>
        <p>
          StorySummary liefert aktuell keine autoritativen Tageswerte. Diese Sicht aggregiert daher
          deterministisch nach Wave.
        </p>
      </div>
      <div className="analytics-chart">
        {series.length === 0 ? (
          <div className="empty-panel">Keine Wave-Daten geladen.</div>
        ) : (
          <svg viewBox="0 0 100 100" role="img" aria-label="Stories pro Wave">
            <polyline className="analytics-line" points={points.join(' ')} />
            {series.map((point, index) => {
              const [x, y] = points[index].split(',').map(Number);
              return (
                <g key={point.wave}>
                  <circle cx={x} cy={y} r="2.6" />
                  <text x={x} y="96">W{point.wave}</text>
                </g>
              );
            })}
          </svg>
        )}
      </div>
      <div className="analytics-wave-grid">
        {series.map((point) => (
          <article className="analytics-wave-card" key={point.wave}>
            <span>Wave {point.wave}</span>
            <strong>{point.total}</strong>
            <small>{point.ready} ready · {point.done} done</small>
          </article>
        ))}
      </div>
    </section>
  );
}

function buildMetricStats(stories: readonly StorySummary[]): MetricStat[] {
  return [
    toMetricStat('wave', 'Wave', stories.map((story) => story.wave)),
    toMetricStat('qa_rounds', 'QA Rounds', stories.map((story) => story.qa_rounds)),
    toMetricStat('repos', 'Repos je Story', stories.map((story) => story.repos.length)),
    toMetricStat('risk', 'Risk Score', stories.map((story) => riskScore(story.risk))),
  ];
}

function toMetricStat(key: string, label: string, values: readonly number[]): MetricStat {
  const sorted = [...values].sort((left, right) => left - right);
  const sum = sorted.reduce((total, value) => total + value, 0);
  return {
    key,
    label,
    min: sorted[0] ?? 0,
    max: sorted[sorted.length - 1] ?? 0,
    avg: sorted.length === 0 ? 0 : sum / sorted.length,
    p90: sorted[Math.max(0, Math.ceil(sorted.length * 0.9) - 1)] ?? 0,
  };
}

function countBy(stories: readonly StorySummary[], select: (story: StorySummary) => string): Array<{ label: string; count: number }> {
  const counts = new Map<string, number>();
  for (const story of stories) {
    const label = select(story) || 'unknown';
    counts.set(label, (counts.get(label) ?? 0) + 1);
  }
  return Array.from(counts.entries())
    .map(([label, count]) => ({ label, count }))
    .sort((left, right) => right.count - left.count || left.label.localeCompare(right.label));
}

function buildWaveSeries(stories: readonly StorySummary[]): Array<{ wave: number; total: number; done: number; ready: number }> {
  const groups = new Map<number, StorySummary[]>();
  for (const story of stories) {
    groups.set(story.wave, [...(groups.get(story.wave) ?? []), story]);
  }
  return Array.from(groups.entries())
    .map(([wave, rows]) => ({
      wave,
      total: rows.length,
      done: rows.filter((story) => story.status === 'Done').length,
      ready: rows.filter((story) => story.status === 'Approved').length,
    }))
    .sort((left, right) => left.wave - right.wave);
}

function riskScore(risk: StorySummary['risk']): number {
  return { low: 1, medium: 2, high: 3 }[risk];
}

function formatNumber(value: number): string {
  if (Number.isInteger(value)) {
    return String(value);
  }
  return value.toLocaleString('de-DE', { maximumFractionDigits: 1 });
}
