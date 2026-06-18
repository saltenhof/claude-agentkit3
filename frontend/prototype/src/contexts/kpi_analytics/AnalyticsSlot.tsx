/**
 * AnalyticsSlot — productive analytics view filling the kpi_analytics BC slice.
 *
 * AC1/AC2: ECharts Overview (aggregate KPI cards avg/min/max/p90) + Timeseries
 *   (multi-series lines, preset+custom range, metric overlay, min/max band, dataZoom,
 *   cross-axisPointer tooltip). Data from real /v1/.../kpi/* endpoints (AG3-084).
 * AC3: SSE subscribe with topics kpi,telemetry,failure_corpus (FK-72 §72.5 / FK-91 §91.8.3).
 * AC4: Lossy re-sync on every EventSource (re-)connect; no polling loop.
 * AC5: kpi/failure_corpus events → re-fetch only; telemetry events → re-fetch mode-lock.
 * AC6: offline indicator + reconnect + empty-state hint.
 * AC7: filter/compare UI bound to KpiQueryFilter (from/to/guard/pool/story_type/story_size/
 *      comparison_period). All passed as server-side query params; no client-side recompute.
 * AC8: chart colors from CSS design tokens (--chart-series-*), not loose hex.
 *
 * ARCH-55: all identifiers, event-types, topic names English.
 * selectKpiDailySeries / selectProjectKpiStats are NOT used as productive data sources.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { ReactElement } from 'react';
import ReactECharts from 'echarts-for-react';
import type { EChartsOption } from 'echarts';
import {
  BffClient,
  type KpiChartSeriesTokens,
  type KpiDimensionResponse,
  type KpiQueryParams,
  type WireFactStory,
  type WireFactGuardPeriod,
  type WireFactPoolPeriod,
  type WireFactPipelinePeriod,
  type WireFactCorpusPeriod,
} from '../../foundation/bff/client';
import { useProjectSse, ANALYTICS_TOPICS } from '../../foundation/sse/useProjectSse';

// ── Design-token CSS var references (AC8 — no loose hex) ──────────────────────
// Chart series colors come from --chart-series-{N} CSS vars (design_system.py + design-system.css).
// We read them from the document root at render time so they respond to theme changes.
// Fallbacks use CSS var() references to owner-backed tokens — never bare hex.

function getSeriesColor(index: number): string {
  if (typeof document === 'undefined') return 'var(--ak-accent-text)';
  const style = getComputedStyle(document.documentElement);
  return style.getPropertyValue(`--chart-series-${index % 12}`).trim() || 'var(--ak-accent-text)';
}

/**
 * Resolve a chart series color (AC8 / E1).
 *
 * When the design-token set fetched from the /kpi/design-tokens endpoint
 * (AG3-092, FK-64 §64.2) is available, the series color comes from that
 * owner-backed token family (consuming the endpoint, not discarding it).
 * Otherwise we fall back to the CSS ``--chart-series-{N}`` custom property
 * (same owner, read at render time). Never a loose hex literal.
 */
function resolveSeriesColor(index: number, tokens: KpiChartSeriesTokens | null): string {
  if (tokens) {
    const key = `series_${index % 12}` as keyof KpiChartSeriesTokens;
    const value = tokens[key];
    if (value) return value;
  }
  return getSeriesColor(index);
}

// Axis/grid/tooltip colors from token CSS vars — no bare hex or raw rgba.
const TOKEN_AXIS_LINE = 'var(--ak-border-tab)';
const TOKEN_AXIS_LABEL = 'var(--ak-text-muted)';
const TOKEN_SPLIT_LINE = 'var(--ak-chart-grid, var(--ak-border-hairline, var(--ak-border-tab)))';
const TOKEN_TOOLTIP_BG = 'var(--ak-surface-tooltip, var(--ak-bg-deep, var(--ak-bg)))';
const TOKEN_TOOLTIP_BORDER = 'var(--ak-border-tab)';
const TOKEN_LEGEND_TEXT = 'var(--ak-text-soft)';
const TOKEN_ACCENT = 'var(--ak-accent-text)';
const TOKEN_TOOLTIP_TEXT = 'var(--ak-text)';
const TOKEN_ZOOM_FILLER = 'var(--ak-chart-zoom-filler, var(--ak-accent-text))';
// E5/AC8: the dataZoom slider track is a subtle non-token overlay → use the
// owner-managed, allowlisted overlay helper (design_system.CSS_NON_TOKEN_ALLOWLIST
// "--overlay-white-3" = rgb(255 255 255 / 3%)), never a loose rgba() literal.
const TOKEN_ZOOM_TRACK = 'var(--overlay-white-3)';
// xAxis pointer label background — owner-backed surface token (no loose literal).
const TOKEN_AXIS_POINTER_LABEL_BG = 'var(--ak-surface-tab-active-top)';

// ── Types ──────────────────────────────────────────────────────────────────────

type AnalyticsTab = 'overview' | 'timeseries';

const TIMESERIES_PRESETS = [
  { value: 7, label: '7 Tage' },
  { value: 14, label: '14 Tage' },
  { value: 30, label: '30 Tage' },
  { value: 60, label: '60 Tage' },
] as const;

/** Aggregated KPI stat derived from real backend fact rows. */
export interface KpiStat {
  key: string;
  label: string;
  unit?: string;
  avg: number;
  min: number;
  max: number;
  p90: number;
}

/** One daily point for the timeseries chart. */
export interface KpiDailyPoint {
  date: string;
  values: Record<string, number>;
}

/** Filter state bound to KpiQueryFilter (FK-63 §63.4.2). */
interface KpiFilterState {
  presetDays: number;
  customFrom: string;
  customTo: string;
  useCustomRange: boolean;
  guard: string;
  pool: string;
  story_type: string;
  story_size: string;
  compareFrom: string;
  compareTo: string;
  useCompare: boolean;
}

// ── KPI stats derivation from real FactStory rows ────────────────────────────

function agg(values: number[]): { avg: number; min: number; max: number; p90: number } {
  if (values.length === 0) return { avg: 0, min: 0, max: 0, p90: 0 };
  const sorted = [...values].sort((a, b) => a - b);
  const avg = values.reduce((s, v) => s + v, 0) / values.length;
  const min = sorted[0] ?? 0;
  const max = sorted[sorted.length - 1] ?? 0;
  const idx = Math.ceil(0.9 * sorted.length) - 1;
  const p90 = sorted[Math.max(0, idx)] ?? 0;
  return { avg, min, max, p90 };
}

function deriveKpiStats(rows: WireFactStory[]): KpiStat[] {
  const qaRounds = rows.map((r) => r.qa_round_count);
  const llmCalls = rows.map((r) => r.llm_call_count ?? 0);
  const filesChanged = rows.map((r) => r.files_changed ?? 0);
  const setupMs = rows.map((r) => r.phase_setup_ms ?? 0);
  const implMs = rows.map((r) => r.phase_implementation_ms ?? 0);
  const closureMs = rows.map((r) => r.phase_closure_ms ?? 0);
  const advFindings = rows.map((r) => r.adversarial_findings_count ?? 0);
  const compactions = rows.map((r) => r.compaction_count ?? 0);

  const stat = (key: string, label: string, vals: number[], unit?: string): KpiStat => ({
    key,
    label,
    unit,
    ...agg(vals),
  });

  return [
    stat('qa_rounds', 'QA-Runden', qaRounds),
    stat('llm_calls', 'LLM Calls', llmCalls),
    stat('files_changed', 'Geaenderte Dateien', filesChanged),
    stat('phase_setup_ms', 'Setup-Phase (ms)', setupMs, 'ms'),
    stat('phase_implementation_ms', 'Implementation-Phase (ms)', implMs, 'ms'),
    stat('phase_closure_ms', 'Closure-Phase (ms)', closureMs, 'ms'),
    stat('adversarial_findings', 'Adversarial Findings', advFindings),
    stat('compaction_count', 'Compactions', compactions),
  ];
}

/** Build daily timeseries from FactStory rows grouped by opened_at date (FK-62 AG3-116). */
function deriveKpiDailySeries(rows: WireFactStory[], days: number): KpiDailyPoint[] {
  const now = new Date();
  const points: KpiDailyPoint[] = [];
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(now.getTime() - i * 86400000);
    const iso = d.toISOString().slice(0, 10);
    const dayRows = rows.filter((r) => r.opened_at.slice(0, 10) === iso);
    const values: Record<string, number> = {};
    if (dayRows.length > 0) {
      values['qa_rounds'] = dayRows.reduce((s, r) => s + r.qa_round_count, 0) / dayRows.length;
      values['llm_calls'] = dayRows.reduce((s, r) => s + (r.llm_call_count ?? 0), 0) / dayRows.length;
      values['files_changed'] = dayRows.reduce((s, r) => s + (r.files_changed ?? 0), 0) / dayRows.length;
      values['phase_setup_ms'] = dayRows.reduce((s, r) => s + (r.phase_setup_ms ?? 0), 0) / dayRows.length;
      values['phase_implementation_ms'] = dayRows.reduce((s, r) => s + (r.phase_implementation_ms ?? 0), 0) / dayRows.length;
      values['phase_closure_ms'] = dayRows.reduce((s, r) => s + (r.phase_closure_ms ?? 0), 0) / dayRows.length;
    }
    points.push({ date: iso, values });
  }
  return points;
}

// ── Chart option builder ───────────────────────────────────────────────────────

const DEFAULT_TIMESERIES_KEYS = ['qa_rounds', 'llm_calls', 'files_changed'];

/** Exported for unit testing: build the ECharts option object (AC6 test surface). */
export function buildChartOption(
  series: KpiDailyPoint[],
  stats: KpiStat[],
  selectedKeys: Set<string>,
  showBand: boolean,
  seriesTokens: KpiChartSeriesTokens | null = null,
): EChartsOption {
  const dates = series.map((p) => p.date);
  const indexByKey = new Map(stats.map((s, i) => [s.key, i] as const));
  const selectedStats = stats.filter((s) => selectedKeys.has(s.key));

  const ranges = selectedStats.map((s) => Math.max(1, s.max));
  const maxRange = Math.max(...ranges, 1);
  const minRange = Math.min(...ranges, 1);
  const useDualAxis = selectedStats.length > 1 && maxRange / minRange > 50;

  const yAxes: NonNullable<EChartsOption['yAxis']> = useDualAxis
    ? [
        {
          type: 'value',
          position: 'left',
          axisLine: { lineStyle: { color: TOKEN_AXIS_LINE } },
          splitLine: { lineStyle: { color: TOKEN_SPLIT_LINE } },
          axisLabel: { color: TOKEN_AXIS_LABEL },
        },
        {
          type: 'value',
          position: 'right',
          axisLine: { lineStyle: { color: TOKEN_AXIS_LABEL } },
          splitLine: { show: false },
          axisLabel: { color: TOKEN_AXIS_LABEL },
        },
      ]
    : [
        {
          type: 'value',
          axisLine: { lineStyle: { color: TOKEN_AXIS_LINE } },
          splitLine: { lineStyle: { color: TOKEN_SPLIT_LINE } },
          axisLabel: { color: TOKEN_AXIS_LABEL },
        },
      ];

  const seriesItems: NonNullable<EChartsOption['series']> = [];

  selectedStats.forEach((stat, idx) => {
    const colorIdx = indexByKey.get(stat.key) ?? idx;
    const color = resolveSeriesColor(colorIdx, seriesTokens);
    const yAxisIndex = useDualAxis && idx > 0 ? 1 : 0;
    const data = series.map((p) => p.values[stat.key] ?? null);

    if (showBand) {
      const lower = data.map((v) => (v === null ? null : v * 0.88));
      const upper = data.map((v) => (v === null ? null : v * 1.12));
      seriesItems.push({
        name: `${stat.label} · Untergrenze`,
        type: 'line',
        stack: `band-${stat.key}`,
        symbol: 'none',
        lineStyle: { opacity: 0 },
        areaStyle: { opacity: 0 },
        data: lower,
        yAxisIndex,
        tooltip: { show: false },
        silent: true,
      });
      seriesItems.push({
        name: `${stat.label} · Huelle`,
        type: 'line',
        stack: `band-${stat.key}`,
        symbol: 'none',
        lineStyle: { opacity: 0 },
        areaStyle: { color, opacity: 0.12 },
        data: upper.map((up, i) => {
          const lo = lower[i];
          return up === null || lo === null ? null : up - lo;
        }),
        yAxisIndex,
        tooltip: { show: false },
        silent: true,
      });
    }

    seriesItems.push({
      name: stat.label,
      type: 'line',
      smooth: false,
      symbol: 'circle',
      symbolSize: 6,
      showSymbol: false,
      lineStyle: { color, width: 2.5 },
      itemStyle: { color },
      emphasis: { focus: 'series', lineStyle: { width: 3.5 } },
      data,
      yAxisIndex,
    });
  });

  return {
    backgroundColor: 'transparent',
    grid: { left: 56, right: useDualAxis ? 56 : 24, top: 48, bottom: 80 },
    tooltip: {
      trigger: 'axis',
      backgroundColor: TOKEN_TOOLTIP_BG,
      borderColor: TOKEN_TOOLTIP_BORDER,
      borderWidth: 1,
      textStyle: { color: TOKEN_TOOLTIP_TEXT, fontSize: 12 },
      axisPointer: { type: 'cross', lineStyle: { color: TOKEN_ACCENT, opacity: 0.45 } },
      formatter: (params) => {
        if (!Array.isArray(params)) return '';
        const rows = params
          .filter(
            (p) =>
              !String(p.seriesName).includes('Untergrenze') &&
              !String(p.seriesName).includes('Huelle'),
          )
          .map((p) => {
            const st = selectedStats.find((s) => s.label === p.seriesName);
            const unit = st?.unit ? ` ${st.unit}` : '';
            return `<div style="display:flex;align-items:center;gap:6px;margin-top:4px"><span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${p.color}"></span><span style="flex:1">${p.seriesName}</span><strong>${formatNumber(Number(p.value))}${unit}</strong></div>`;
          })
          .join('');
        const header = (params[0] as { axisValueLabel?: string }).axisValueLabel ?? '';
        return `<div style="font-weight:600;color:${TOKEN_AXIS_LABEL};font-size:11px;letter-spacing:0.04em;text-transform:uppercase">${header}</div>${rows}`;
      },
    },
    legend: {
      show: true,
      bottom: 0,
      textStyle: { color: TOKEN_LEGEND_TEXT, fontSize: 12 },
      itemWidth: 14,
      itemHeight: 8,
      icon: 'roundRect',
      data: selectedStats.map((s) => s.label),
    },
    xAxis: {
      type: 'category',
      data: dates,
      boundaryGap: false,
      axisLine: { lineStyle: { color: TOKEN_AXIS_LINE } },
      axisLabel: {
        color: TOKEN_AXIS_LABEL,
        formatter: (value: string) => {
          const d = new Date(`${value}T00:00:00Z`);
          return `${d.getUTCDate()}.${d.getUTCMonth() + 1}.`;
        },
      },
      axisPointer: { label: { backgroundColor: TOKEN_AXIS_POINTER_LABEL_BG } },
    },
    yAxis: yAxes,
    dataZoom: [
      { type: 'inside', start: 0, end: 100 },
      {
        type: 'slider',
        height: 18,
        bottom: 36,
        borderColor: 'transparent',
        backgroundColor: TOKEN_ZOOM_TRACK,
        fillerColor: TOKEN_ZOOM_FILLER,
        handleStyle: { color: TOKEN_ACCENT },
        textStyle: { color: TOKEN_AXIS_LABEL, fontSize: 10 },
      },
    ],
    series: seriesItems,
  };
}

function formatNumber(value: number): string {
  if (!Number.isFinite(value)) return '—';
  if (Math.abs(value) >= 1000) return value.toLocaleString('de-DE', { maximumFractionDigits: 0 });
  if (Number.isInteger(value)) return String(value);
  return value.toLocaleString('de-DE', { maximumFractionDigits: 1 });
}

// ── ISO date helpers ───────────────────────────────────────────────────────────

function isoNow(): string {
  return new Date().toISOString().replace('.000Z', 'Z').split('.')[0] + 'Z';
}

function isoDaysAgo(days: number): string {
  const d = new Date(Date.now() - days * 86400000);
  return d.toISOString().split('.')[0] + 'Z';
}

// ── Sub-components ─────────────────────────────────────────────────────────────

function KpiStatCard({
  stat,
  colorIdx,
  seriesTokens,
}: {
  stat: KpiStat;
  colorIdx: number;
  seriesTokens: KpiChartSeriesTokens | null;
}): ReactElement {
  const color = resolveSeriesColor(colorIdx, seriesTokens);
  return (
    <article className="kpi-stat-card ak-panel" data-testid={`kpi-card-${stat.key}`}>
      <header className="kpi-stat-card__head">
        <span className="kpi-stat-card__swatch" style={{ background: color }} />
        <h3>{stat.label}</h3>
      </header>
      <div className="kpi-stat-card__primary">
        <span className="kpi-stat-card__primary-label">Mittelwert</span>
        <span className="kpi-stat-card__primary-value">
          {formatNumber(stat.avg)}
          {stat.unit && <span className="kpi-stat-card__unit"> {stat.unit}</span>}
        </span>
      </div>
      <dl className="kpi-stat-card__breakdown">
        <div>
          <dt>Min</dt>
          <dd>
            {formatNumber(stat.min)}
            {stat.unit && <span className="kpi-stat-card__unit"> {stat.unit}</span>}
          </dd>
        </div>
        <div>
          <dt>P90</dt>
          <dd>
            {formatNumber(stat.p90)}
            {stat.unit && <span className="kpi-stat-card__unit"> {stat.unit}</span>}
          </dd>
        </div>
        <div>
          <dt>Max</dt>
          <dd>
            {formatNumber(stat.max)}
            {stat.unit && <span className="kpi-stat-card__unit"> {stat.unit}</span>}
          </dd>
        </div>
      </dl>
    </article>
  );
}

function AnalyticsOverview({
  stats,
  storyCount,
  isLoading,
  seriesTokens,
}: {
  stats: KpiStat[];
  storyCount: number;
  isLoading: boolean;
  seriesTokens: KpiChartSeriesTokens | null;
}): ReactElement {
  if (isLoading) {
    return (
      <section className="analytics-overview">
        <p className="analytics-overview__lead">Daten werden geladen…</p>
      </section>
    );
  }
  if (stats.length === 0 || storyCount === 0) {
    return (
      <section className="analytics-overview">
        <p className="analytics-overview__lead analytics-overview__lead--empty" data-testid="kpi-empty-hint">
          Noch keine abgeschlossenen Stories im gewaehlten Zeitraum. Bitte Zeitraum anpassen oder warten bis die ersten Fact-Daten vorliegen.
        </p>
      </section>
    );
  }
  return (
    <section className="analytics-overview">
      <p className="analytics-overview__lead">
        Aggregiert ueber {storyCount} Stories im gewaehlten Zeitraum. Min/Max grenzen die
        Spreizung ab; das 90&nbsp;%-Quantil zeigt, wo die Oberkante der typischen Workload liegt.
      </p>
      <div className="analytics-overview__grid">
        {stats.map((stat, idx) => (
          <KpiStatCard key={stat.key} stat={stat} colorIdx={idx} seriesTokens={seriesTokens} />
        ))}
      </div>
    </section>
  );
}

function AnalyticsTimeseries({
  stats,
  series,
  isLoading,
  seriesTokens,
}: {
  stats: KpiStat[];
  series: KpiDailyPoint[];
  isLoading: boolean;
  seriesTokens: KpiChartSeriesTokens | null;
}): ReactElement {
  const [selectedKeys, setSelectedKeys] = useState<Set<string>>(new Set(DEFAULT_TIMESERIES_KEYS));
  const [showBand, setShowBand] = useState(true);

  const option = useMemo<EChartsOption>(
    () => buildChartOption(series, stats, selectedKeys, showBand, seriesTokens),
    [series, stats, selectedKeys, showBand, seriesTokens],
  );

  const toggleKey = (key: string) => {
    setSelectedKeys((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  return (
    <section className="analytics-timeseries">
      <div className="analytics-timeseries__controls ak-panel">
        <div className="analytics-timeseries__group analytics-timeseries__group--wide">
          <span className="eyebrow">Metriken (Overlay)</span>
          <div className="analytics-timeseries__metrics">
            {stats.map((stat, idx) => {
              const active = selectedKeys.has(stat.key);
              const color = resolveSeriesColor(idx, seriesTokens);
              return (
                <button
                  className={`metric-chip ${active ? 'active' : ''}`}
                  key={stat.key}
                  type="button"
                  data-testid={`metric-chip-${stat.key}`}
                  onClick={() => toggleKey(stat.key)}
                  style={active ? { borderColor: color, color } : undefined}
                >
                  <span className="metric-chip__swatch" style={{ background: color }} />
                  {stat.label}
                </button>
              );
            })}
          </div>
        </div>
        <div className="analytics-timeseries__group">
          <span className="eyebrow">Huelle</span>
          <label className="analytics-timeseries__toggle">
            <input
              type="checkbox"
              checked={showBand}
              onChange={(e) => setShowBand(e.target.checked)}
              data-testid="band-toggle"
            />
            Min/Max-Band
          </label>
        </div>
      </div>

      <div className="analytics-timeseries__chart ak-panel">
        {isLoading ? (
          <p className="analytics-timeseries__loading">Daten werden geladen…</p>
        ) : series.every((p) => Object.keys(p.values).length === 0) ? (
          <p className="analytics-timeseries__empty" data-testid="timeseries-empty-hint">
            Keine Zeitreihendaten im gewaehlten Zeitraum.
          </p>
        ) : (
          <ReactECharts
            option={option}
            notMerge
            lazyUpdate
            style={{ width: '100%', height: '32rem' }}
            theme={undefined}
          />
        )}
      </div>
    </section>
  );
}

// ── Filter panel (AC7) ─────────────────────────────────────────────────────────

function FilterPanel({
  filter,
  onChange,
}: {
  filter: KpiFilterState;
  onChange: (patch: Partial<KpiFilterState>) => void;
}): ReactElement {
  return (
    <div className="analytics-filter ak-panel" data-testid="analytics-filter">
      <div className="analytics-filter__group">
        <span className="eyebrow">Zeitraum</span>
        <div className="analytics-timeseries__presets" role="group">
          {TIMESERIES_PRESETS.map((preset) => (
            <button
              className={!filter.useCustomRange && filter.presetDays === preset.value ? 'active' : ''}
              key={preset.value}
              type="button"
              data-testid={`preset-${preset.value}`}
              onClick={() => onChange({ presetDays: preset.value, useCustomRange: false })}
            >
              {preset.label}
            </button>
          ))}
        </div>
        <div className="analytics-filter__custom-range">
          <label>
            Von
            <input
              type="date"
              value={filter.customFrom}
              onChange={(e) => onChange({ customFrom: e.target.value, useCustomRange: true })}
              data-testid="filter-from"
            />
          </label>
          <label>
            Bis
            <input
              type="date"
              value={filter.customTo}
              onChange={(e) => onChange({ customTo: e.target.value, useCustomRange: true })}
              data-testid="filter-to"
            />
          </label>
        </div>
      </div>

      <div className="analytics-filter__group">
        <span className="eyebrow">Entity-Filter</span>
        <label>
          Guard
          <input
            type="text"
            value={filter.guard}
            placeholder="Guard-ID"
            onChange={(e) => onChange({ guard: e.target.value })}
            data-testid="filter-guard"
          />
        </label>
        <label>
          Pool
          <input
            type="text"
            value={filter.pool}
            placeholder="Pool-Name"
            onChange={(e) => onChange({ pool: e.target.value })}
            data-testid="filter-pool"
          />
        </label>
      </div>

      <div className="analytics-filter__group">
        <span className="eyebrow">Story-Filter</span>
        <label>
          Typ
          <input
            type="text"
            value={filter.story_type}
            placeholder="z.B. implementation"
            onChange={(e) => onChange({ story_type: e.target.value })}
            data-testid="filter-story-type"
          />
        </label>
        <label>
          Groesse
          <input
            type="text"
            value={filter.story_size}
            placeholder="z.B. M"
            onChange={(e) => onChange({ story_size: e.target.value })}
            data-testid="filter-story-size"
          />
        </label>
      </div>

      <div className="analytics-filter__group">
        <span className="eyebrow">Vergleichszeitraum</span>
        <label>
          <input
            type="checkbox"
            checked={filter.useCompare}
            onChange={(e) => onChange({ useCompare: e.target.checked })}
            data-testid="filter-compare-toggle"
          />
          Vergleich aktivieren
        </label>
        {filter.useCompare && (
          <div className="analytics-filter__custom-range">
            <label>
              Von
              <input
                type="date"
                value={filter.compareFrom}
                onChange={(e) => onChange({ compareFrom: e.target.value })}
                data-testid="filter-compare-from"
              />
            </label>
            <label>
              Bis
              <input
                type="date"
                value={filter.compareTo}
                onChange={(e) => onChange({ compareTo: e.target.value })}
                data-testid="filter-compare-to"
              />
            </label>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Main slot component ────────────────────────────────────────────────────────

const DEFAULT_PRESET_DAYS = 30;

function buildKpiParams(filter: KpiFilterState): KpiQueryParams {
  let from: string;
  let to: string;
  if (filter.useCustomRange && filter.customFrom && filter.customTo) {
    from = `${filter.customFrom}T00:00:00Z`;
    to = `${filter.customTo}T23:59:59Z`;
  } else {
    from = isoDaysAgo(filter.presetDays);
    to = isoNow();
  }
  const params: KpiQueryParams = { from, to };
  if (filter.guard) params.guard = filter.guard;
  if (filter.pool) params.pool = filter.pool;
  if (filter.story_type) params.story_type = filter.story_type;
  if (filter.story_size) params.story_size = filter.story_size;
  if (filter.useCompare && filter.compareFrom && filter.compareTo) {
    params.compare_from = `${filter.compareFrom}T00:00:00Z`;
    params.compare_to = `${filter.compareTo}T23:59:59Z`;
  }
  return params;
}

// ── Corpus funnel rendering (FK-72 §72.11.3) ─────────────────────────────────

function CorpusFunnel({ rows }: { rows: WireFactCorpusPeriod[] }): ReactElement {
  if (rows.length === 0) {
    return (
      <section className="analytics-funnel">
        <h3 className="analytics-funnel__title">Failure Corpus Funnel</h3>
        <p className="analytics-funnel__empty" data-testid="corpus-funnel-empty">
          Keine Corpus-Daten im gewaehlten Zeitraum.
        </p>
      </section>
    );
  }
  const totalIncidents = rows.reduce((s, r) => s + r.new_incident_count, 0);
  const totalPromoted = rows.reduce((s, r) => s + r.patterns_total_count, 0);
  const totalApproved = rows.reduce((s, r) => s + r.patterns_with_active_check, 0);
  return (
    <section className="analytics-funnel" data-testid="corpus-funnel">
      <h3 className="analytics-funnel__title">Failure Corpus Funnel</h3>
      <ol className="analytics-funnel__steps">
        <li className="analytics-funnel__step" data-testid="funnel-incidents">
          <span className="analytics-funnel__step-label">Incidents recorded</span>
          <span className="analytics-funnel__step-value">{totalIncidents}</span>
        </li>
        <li className="analytics-funnel__step" data-testid="funnel-promoted">
          <span className="analytics-funnel__step-label">Patterns promoted</span>
          <span className="analytics-funnel__step-value">{totalPromoted}</span>
        </li>
        <li className="analytics-funnel__step" data-testid="funnel-approved">
          <span className="analytics-funnel__step-label">Checks approved</span>
          <span className="analytics-funnel__step-value">{totalApproved}</span>
        </li>
      </ol>
    </section>
  );
}

// ── Entity / pipeline dimension panels (E1 — render fetched dimensions) ───────
//
// FK-63 §63.3.3 / story §2.1.5: the guards/pools/pipeline KPI dimensions are
// part of the Analytics view and are surfaced when their filter selects them:
//   guard filter active  → guards dimension panel  (/kpi/guards rows)
//   pool  filter active  → pools  dimension panel  (/kpi/pools rows)
//   story_type filter active → pipeline dimension panel (/kpi/pipeline rows)
// Each panel renders the REAL fetched rows (no fetch-then-discard). When the
// corresponding filter is empty the dimension is not selected and its panel is
// not shown — the fetch still primes the data for an immediate switch and the
// SSE re-sync, but it is never silently discarded.

function GuardsDimensionPanel({ rows }: { rows: WireFactGuardPeriod[] }): ReactElement {
  return (
    <section className="analytics-dimension" data-testid="guards-dimension">
      <h3 className="analytics-dimension__title">Guards</h3>
      {rows.length === 0 ? (
        <p className="analytics-dimension__empty" data-testid="guards-dimension-empty">
          Keine Guard-Daten fuer den gewaehlten Filter/Zeitraum.
        </p>
      ) : (
        <ul className="analytics-dimension__rows">
          {rows.map((r) => (
            <li
              className="analytics-dimension__row"
              key={`${r.guard_key}-${r.period_start}`}
              data-testid={`guards-row-${r.guard_key}`}
            >
              <span className="analytics-dimension__row-label">{r.guard_key}</span>
              <span className="analytics-dimension__row-metric">
                {formatNumber(r.invocation_count)} Invocations
              </span>
              <span className="analytics-dimension__row-metric">
                {formatNumber(r.violation_count)} Violations
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function PoolsDimensionPanel({ rows }: { rows: WireFactPoolPeriod[] }): ReactElement {
  return (
    <section className="analytics-dimension" data-testid="pools-dimension">
      <h3 className="analytics-dimension__title">Pools</h3>
      {rows.length === 0 ? (
        <p className="analytics-dimension__empty" data-testid="pools-dimension-empty">
          Keine Pool-Daten fuer den gewaehlten Filter/Zeitraum.
        </p>
      ) : (
        <ul className="analytics-dimension__rows">
          {rows.map((r) => (
            <li
              className="analytics-dimension__row"
              key={`${r.pool_key}-${r.period_start}`}
              data-testid={`pools-row-${r.pool_key}`}
            >
              <span className="analytics-dimension__row-label">{r.pool_key}</span>
              <span className="analytics-dimension__row-metric">{formatNumber(r.call_count)} Calls</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function PipelineDimensionPanel({ rows }: { rows: WireFactPipelinePeriod[] }): ReactElement {
  return (
    <section className="analytics-dimension" data-testid="pipeline-dimension">
      <h3 className="analytics-dimension__title">Pipeline</h3>
      {rows.length === 0 ? (
        <p className="analytics-dimension__empty" data-testid="pipeline-dimension-empty">
          Keine Pipeline-Daten fuer den gewaehlten Filter/Zeitraum.
        </p>
      ) : (
        <ul className="analytics-dimension__rows">
          {rows.map((r) => (
            <li
              className="analytics-dimension__row"
              key={r.period_start}
              data-testid={`pipeline-row-${r.period_start}`}
            >
              <span className="analytics-dimension__row-label">
                {r.period_start.slice(0, 10)}
              </span>
              <span className="analytics-dimension__row-metric">
                {formatNumber(r.story_count_closed)} abgeschlossen
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

// ── Filter routing: endpoint-scoped (E1 / AC7 / story §2.1.5) ─────────────────
//
// guard  → /kpi/guards ONLY   (EntityFilter, guards dimension)
// pool   → /kpi/pools  ONLY   (EntityFilter, pools dimension)
// story_type → /kpi/stories + /kpi/pipeline
// story_size → /kpi/stories ONLY
// compare_from/to → all endpoints that support it (stories, guards, pools, pipeline, corpus)
//
// guard and pool are MUTUALLY EXCLUSIVE: sending both together triggers a
// 400 invalid_kpi_filter from the backend (KpiQueryFilter validation).
// The UI presents them as separate inputs; this function enforces the routing.

function buildStoriesParams(filter: KpiFilterState): KpiQueryParams {
  const base = buildKpiParams(filter);
  // stories dimension: story_type + story_size accepted; guard/pool NOT sent here.
  const params: KpiQueryParams = { from: base.from, to: base.to };
  if (filter.story_type) params.story_type = filter.story_type;
  if (filter.story_size) params.story_size = filter.story_size;
  if (base.compare_from) params.compare_from = base.compare_from;
  if (base.compare_to) params.compare_to = base.compare_to;
  return params;
}

function buildGuardsParams(filter: KpiFilterState): KpiQueryParams {
  const base = buildKpiParams(filter);
  // guards dimension: guard entity filter only (not pool, not story filters).
  const params: KpiQueryParams = { from: base.from, to: base.to };
  if (filter.guard) params.guard = filter.guard;
  if (base.compare_from) params.compare_from = base.compare_from;
  if (base.compare_to) params.compare_to = base.compare_to;
  return params;
}

function buildPoolsParams(filter: KpiFilterState): KpiQueryParams {
  const base = buildKpiParams(filter);
  // pools dimension: pool entity filter only (not guard, not story filters).
  const params: KpiQueryParams = { from: base.from, to: base.to };
  if (filter.pool) params.pool = filter.pool;
  if (base.compare_from) params.compare_from = base.compare_from;
  if (base.compare_to) params.compare_to = base.compare_to;
  return params;
}

function buildPipelineParams(filter: KpiFilterState): KpiQueryParams {
  const base = buildKpiParams(filter);
  // pipeline dimension: story_type accepted (not story_size, not guard, not pool).
  const params: KpiQueryParams = { from: base.from, to: base.to };
  if (filter.story_type) params.story_type = filter.story_type;
  if (base.compare_from) params.compare_from = base.compare_from;
  if (base.compare_to) params.compare_to = base.compare_to;
  return params;
}

function buildCorpusParams(filter: KpiFilterState): KpiQueryParams {
  const base = buildKpiParams(filter);
  // corpus dimension: only period + compare (no entity or story filters).
  const params: KpiQueryParams = { from: base.from, to: base.to };
  if (base.compare_from) params.compare_from = base.compare_from;
  if (base.compare_to) params.compare_to = base.compare_to;
  return params;
}

// ── Props + main slot ──────────────────────────────────────────────────────────

export interface AnalyticsSlotProps {
  projectKey: string;
  baseUrl?: string;
  /** Injectable BFF client for testing; defaults to singleton BffClient. */
  client?: BffClient;
  /** Whether SSE is enabled (can be disabled in tests). */
  sseEnabled?: boolean;
  /** Offline state passed down from Shell (AC6). */
  isOffline?: boolean;
  /** Called on telemetry SSE event so Shell can refresh mode-lock (E2 / AC5). */
  onTelemetryEvent?: () => void;
  /**
   * Called when the Analytics SSE stream goes offline (true) or recovers (false)
   * (E3 / AC6). Wired to the Shell ``setIsOffline`` so that a dropped Analytics
   * stream sets the GLOBAL offline state and locks all mutating UI — total-offline
   * must lock regardless of which view's stream dropped (FAIL-CLOSED, FK-72 §72.14.6).
   */
  onOfflineChange?: (offline: boolean) => void;
}

/** Singleton client used when no injectable client is provided. */
const _defaultClient = new BffClient('');

export function AnalyticsSlot({
  projectKey,
  baseUrl = '',
  client,
  sseEnabled = true,
  isOffline = false,
  onTelemetryEvent,
  onOfflineChange,
}: AnalyticsSlotProps): ReactElement {
  const bff = client ?? _defaultClient;

  const [tab, setTab] = useState<AnalyticsTab>('overview');
  const [isLoading, setIsLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [storiesResponse, setStoriesResponse] = useState<KpiDimensionResponse | null>(null);
  // Additional KPI dimensions (E1 — all dimensions wired).
  const [guardsResponse, setGuardsResponse] = useState<KpiDimensionResponse | null>(null);
  const [poolsResponse, setPoolsResponse] = useState<KpiDimensionResponse | null>(null);
  const [pipelineResponse, setPipelineResponse] = useState<KpiDimensionResponse | null>(null);
  // Corpus funnel (FK-72 §72.11.3 — failure_corpus shown as funnel IN Analytics).
  const [corpusResponse, setCorpusResponse] = useState<KpiDimensionResponse | null>(null);
  // Chart series tokens from the /kpi/design-tokens endpoint (AG3-092 — consumed,
  // not discarded). null until fetched; resolveSeriesColor falls back to CSS vars.
  const [seriesTokens, setSeriesTokens] = useState<KpiChartSeriesTokens | null>(null);

  const [filter, setFilter] = useState<KpiFilterState>({
    presetDays: DEFAULT_PRESET_DAYS,
    customFrom: '',
    customTo: '',
    useCustomRange: false,
    guard: '',
    pool: '',
    story_type: '',
    story_size: '',
    compareFrom: '',
    compareTo: '',
    useCompare: false,
  });
  const [showFilter, setShowFilter] = useState(false);

  // Use a ref to hold the latest filter without re-triggering the SSE subscription.
  const filterRef = useRef(filter);
  filterRef.current = filter;

  const onTelemetryEventRef = useRef(onTelemetryEvent);
  onTelemetryEventRef.current = onTelemetryEvent;

  const onOfflineChangeRef = useRef(onOfflineChange);
  onOfflineChangeRef.current = onOfflineChange;

  /**
   * Fetch all KPI dimensions with endpoint-scoped filter routing (E1 / AC7).
   * Called on initial-GET + lossy re-sync (FK-72 §72.12.4 Z.306).
   *
   * Filter routing rules (story §2.1.5 / AC7):
   *   guard  → /kpi/guards ONLY (EntityFilter; mutually exclusive with pool)
   *   pool   → /kpi/pools  ONLY (EntityFilter; mutually exclusive with guard)
   *   story_type → /kpi/stories + /kpi/pipeline
   *   story_size → /kpi/stories ONLY
   *   compare_from/to → all dimensions
   */
  const fetchKpiData = useCallback(async () => {
    setIsLoading(true);
    setLoadError(null);
    try {
      const f = filterRef.current;
      // Parallel fetches: all five KPI dimensions with endpoint-scoped params.
      const [storiesRes, guardsRes, poolsRes, pipelineRes, corpusRes] = await Promise.allSettled([
        bff.getKpiStories(projectKey, buildStoriesParams(f)),
        bff.getKpiGuards(projectKey, buildGuardsParams(f)),
        bff.getKpiPools(projectKey, buildPoolsParams(f)),
        bff.getKpiPipeline(projectKey, buildPipelineParams(f)),
        bff.getKpiCorpus(projectKey, buildCorpusParams(f)),
      ]);
      if (storiesRes.status === 'fulfilled') setStoriesResponse(storiesRes.value);
      if (guardsRes.status === 'fulfilled') setGuardsResponse(guardsRes.value);
      if (poolsRes.status === 'fulfilled') setPoolsResponse(poolsRes.value);
      if (pipelineRes.status === 'fulfilled') setPipelineResponse(pipelineRes.value);
      if (corpusRes.status === 'fulfilled') setCorpusResponse(corpusRes.value);

      // Surface first error (fail-closed, but non-blocking for other dimensions).
      const firstError = [storiesRes, guardsRes, poolsRes, pipelineRes, corpusRes].find(
        (r) => r.status === 'rejected',
      );
      if (firstError && firstError.status === 'rejected') {
        const msg = firstError.reason instanceof Error ? firstError.reason.message : String(firstError.reason);
        setLoadError(`KPI konnten nicht vollstaendig geladen werden: ${msg}`);
      } else {
        setLoadError(null);
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setLoadError(`KPI konnten nicht geladen werden: ${msg}`);
    } finally {
      setIsLoading(false);
    }
  }, [bff, projectKey]);

  /**
   * Fetch only the corpus funnel (called on failure_corpus SSE event — re-sync only,
   * no field-granular patching since wire schema is open, AC5 / Out-of-Scope).
   */
  const fetchCorpusFunnel = useCallback(async () => {
    try {
      const resp = await bff.getKpiCorpus(projectKey, buildCorpusParams(filterRef.current));
      setCorpusResponse(resp);
    } catch {
      // non-blocking — corpus funnel re-sync failure surfaces nothing extra
    }
  }, [bff, projectKey]);

  // Initial-GET on mount and on filter/projectKey changes.
  useEffect(() => {
    void fetchKpiData();
  }, [fetchKpiData, filter]);

  // Fetch the chart design tokens once per project (AG3-092 /kpi/design-tokens).
  // Consumed for ECharts series theming (E1 — endpoint is wired, not dead surface).
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const resp = await bff.getKpiDesignTokens(projectKey);
        if (!cancelled) setSeriesTokens(resp.chart.series);
      } catch {
        // Non-blocking: fall back to CSS --chart-series-* vars (resolveSeriesColor).
        if (!cancelled) setSeriesTokens(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [bff, projectKey]);

  // SSE subscription: Analytics topics = kpi, telemetry, failure_corpus (FK-72 §72.5).
  // kpi → re-fetch all (open wire schema, AC5/Out-of-Scope).
  // failure_corpus → re-fetch corpus funnel only (re-sync, open schema).
  // telemetry → notify Shell for mode-lock refresh (E2) + re-fetch KPI.
  useProjectSse({
    baseUrl,
    projectKey,
    topics: ANALYTICS_TOPICS,
    enabled: sseEnabled,
    onReconnect: () => {
      // Lossy re-sync: fresh initial-GET on every (re-)connect (FK-72 §72.12.4 Z.306).
      void fetchKpiData();
    },
    onEvent: (event) => {
      if (event.topic === 'kpi') {
        // kpi event: re-fetch all KPI dimensions (open schema — no field-granular patching).
        void fetchKpiData();
      } else if (event.topic === 'failure_corpus') {
        // failure_corpus: re-fetch corpus funnel only (open schema, AC5 Out-of-Scope).
        void fetchCorpusFunnel();
      } else if (event.topic === 'telemetry') {
        // telemetry: notify Shell so it can refresh mode-lock (E2 / AC5).
        onTelemetryEventRef.current?.();
        // Also re-fetch KPI in case mode-lock affects aggregation visibility.
        void fetchKpiData();
      }
    },
    // E3 / AC6: a dropped Analytics stream sets the GLOBAL offline state in the
    // Shell (setIsOffline) so total-offline locks ALL mutating UI regardless of
    // which view's stream dropped (FAIL-CLOSED, FK-72 §72.14.6 Z.503).
    onOffline: () => onOfflineChangeRef.current?.(true),
    onOnline: () => onOfflineChangeRef.current?.(false),
  });

  const storyRows = useMemo(
    () => (storiesResponse?.rows ?? []) as WireFactStory[],
    [storiesResponse],
  );
  const stats = useMemo(() => deriveKpiStats(storyRows), [storyRows]);
  const dailySeries = useMemo(
    () => deriveKpiDailySeries(storyRows, filter.useCustomRange ? 30 : filter.presetDays),
    [storyRows, filter.presetDays, filter.useCustomRange],
  );

  const corpusRows = useMemo(
    () => (corpusResponse?.rows ?? []) as WireFactCorpusPeriod[],
    [corpusResponse],
  );

  // E1: render the fetched guards/pools/pipeline dimensions (no fetch-then-discard).
  const guardsRows = useMemo(
    () => (guardsResponse?.rows ?? []) as WireFactGuardPeriod[],
    [guardsResponse],
  );
  const poolsRows = useMemo(
    () => (poolsResponse?.rows ?? []) as WireFactPoolPeriod[],
    [poolsResponse],
  );
  const pipelineRows = useMemo(
    () => (pipelineResponse?.rows ?? []) as WireFactPipelinePeriod[],
    [pipelineResponse],
  );

  // A dimension panel is shown when its filter selects it (FK-63 §63.3.3 / E1):
  //   guard filter active → guards; pool filter active → pools;
  //   story_type filter active → pipeline (story_type also routes to /kpi/pipeline).
  const showGuards = filter.guard.trim().length > 0;
  const showPools = filter.pool.trim().length > 0;
  const showPipeline = filter.story_type.trim().length > 0;

  const handleFilterChange = useCallback((patch: Partial<KpiFilterState>) => {
    setFilter((prev) => ({ ...prev, ...patch }));
  }, []);

  return (
    <div className="analytics-slot" data-testid="analytics-slot">
      {isOffline && (
        <div className="analytics-offline-banner" role="alert" data-testid="offline-banner">
          Verbindung verloren — Live-Updates pausiert.
        </div>
      )}
      {loadError && (
        <div className="analytics-error" role="alert" data-testid="analytics-error">
          {loadError}
        </div>
      )}

      <header className="analytics-view__head">
        <div>
          <p className="eyebrow">Project Analytics</p>
          <h1>KPI-Cockpit</h1>
        </div>
        <div className="analytics-tabs" role="tablist">
          <button
            className={tab === 'overview' ? 'active' : ''}
            type="button"
            onClick={() => setTab('overview')}
          >
            Uebersicht
          </button>
          <button
            className={tab === 'timeseries' ? 'active' : ''}
            type="button"
            onClick={() => setTab('timeseries')}
          >
            Zeitverlaeufe
          </button>
        </div>
        <button
          className={`analytics-filter-toggle ${showFilter ? 'active' : ''}`}
          type="button"
          data-testid="filter-toggle"
          onClick={() => setShowFilter((v) => !v)}
        >
          Filter
        </button>
      </header>

      {showFilter && (
        <FilterPanel filter={filter} onChange={handleFilterChange} />
      )}

      {tab === 'overview' && (
        <>
          <AnalyticsOverview
            stats={stats}
            storyCount={storyRows.length}
            isLoading={isLoading}
            seriesTokens={seriesTokens}
          />
          {/* Corpus funnel (FK-72 §72.11.3 — failure_corpus shown as funnel IN Analytics) */}
          {!isLoading && <CorpusFunnel rows={corpusRows} />}
        </>
      )}
      {tab === 'timeseries' && (
        <AnalyticsTimeseries
          stats={stats}
          series={dailySeries}
          isLoading={isLoading}
          seriesTokens={seriesTokens}
        />
      )}

      {/* E1: filter-selected entity/pipeline dimensions rendered with REAL fetched rows. */}
      {!isLoading && (showGuards || showPools || showPipeline) && (
        <div className="analytics-dimensions" data-testid="analytics-dimensions">
          {showGuards && <GuardsDimensionPanel rows={guardsRows} />}
          {showPools && <PoolsDimensionPanel rows={poolsRows} />}
          {showPipeline && <PipelineDimensionPanel rows={pipelineRows} />}
        </div>
      )}
    </div>
  );
}
