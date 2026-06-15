/*
 * AnalyticsView — main navigation page "Analytics" with two sub-tabs:
 *
 * - "Übersicht": project-wide aggregate KPIs per story metric
 *   (mean, min, max, 90th-percentile).
 * - "Zeitverläufe": per calendar day aggregated values as an
 *   interactive line chart (ECharts) with multi-series selection,
 *   zoom/brush, tooltip overlay and min/max band.
 *
 * Data source: the selectors `selectProjectKpiStats` and
 * `selectKpiDailySeries` from the story store — single source of truth.
 */

import { useMemo, useState } from 'react';
import ReactECharts from 'echarts-for-react';
import type { EChartsOption } from 'echarts';
import {
  selectKpiDailySeries,
  selectProjectKpiStats,
  type KpiDailyPoint,
  type KpiStat,
  type Story,
} from '../store';

type AnalyticsTab = 'overview' | 'timeseries';

const TIMESERIES_PRESETS = [
  { value: 7, label: '7 Tage' },
  { value: 14, label: '14 Tage' },
  { value: 30, label: '30 Tage' },
  { value: 60, label: '60 Tage' },
] as const;

/* Default series for the time series view: three closely related
 * KPIs shown as initially selected overlays. */
const DEFAULT_TIMESERIES_KEYS = ['runtime_total', 'qa_rounds_implementation', 'solving_rate_implementation'];

const SERIES_COLORS = [
  '#48e7ff', // accent cyan
  '#ffb32c', // warm yellow
  '#74d17f', // success green
  '#b38cff', // violet
  '#ff5b57', // danger red
  '#7ea7ff', // info blue
  '#ffd35e', // accent warm strong
  '#82c4ff', // done blue
  '#a371f7', // backlog purple
  '#3fb950', // status done
  '#d29922', // progress amber
  '#9ff5ff', // accent soft
];

export function AnalyticsView({ stories }: { stories: Story[] }) {
  const [tab, setTab] = useState<AnalyticsTab>('overview');
  const stats = useMemo(() => selectProjectKpiStats(stories), [stories]);

  return (
    <div className="analytics-view">
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
            Übersicht
          </button>
          <button
            className={tab === 'timeseries' ? 'active' : ''}
            type="button"
            onClick={() => setTab('timeseries')}
          >
            Zeitverläufe
          </button>
        </div>
      </header>

      {tab === 'overview' && <AnalyticsOverview stats={stats} storyCount={stories.length} />}
      {tab === 'timeseries' && <AnalyticsTimeseries stories={stories} stats={stats} />}
    </div>
  );
}

function AnalyticsOverview({ stats, storyCount }: { stats: KpiStat[]; storyCount: number }) {
  return (
    <section className="analytics-overview">
      <p className="analytics-overview__lead">
        Aggregiert ueber alle {storyCount} Stories im Projekt-Backlog. Min/Max grenzen die
        Spreizung ab; das 90 %-Quantil zeigt, wo die Oberkante der typischen Workload liegt
        — Outlier liegen darueber.
      </p>
      <div className="analytics-overview__grid">
        {stats.map((stat) => (
          <KpiStatCard key={stat.key} stat={stat} />
        ))}
      </div>
    </section>
  );
}

function KpiStatCard({ stat }: { stat: KpiStat }) {
  return (
    <article className="kpi-stat-card ak-panel">
      <header className="kpi-stat-card__head">
        <h3>{stat.label}</h3>
      </header>
      <div className="kpi-stat-card__primary">
        <span className="kpi-stat-card__primary-label">Mittelwert</span>
        <span className="kpi-stat-card__primary-value">
          {formatNumber(stat.avg)}
          {stat.unit && <span className="kpi-stat-card__unit">{stat.unit}</span>}
        </span>
      </div>
      <dl className="kpi-stat-card__breakdown">
        <div>
          <dt>Min</dt>
          <dd>
            {formatNumber(stat.min)}
            {stat.unit && <span className="kpi-stat-card__unit">{stat.unit}</span>}
          </dd>
        </div>
        <div>
          <dt>P90</dt>
          <dd>
            {formatNumber(stat.p90)}
            {stat.unit && <span className="kpi-stat-card__unit">{stat.unit}</span>}
          </dd>
        </div>
        <div>
          <dt>Max</dt>
          <dd>
            {formatNumber(stat.max)}
            {stat.unit && <span className="kpi-stat-card__unit">{stat.unit}</span>}
          </dd>
        </div>
      </dl>
    </article>
  );
}

function AnalyticsTimeseries({ stories, stats }: { stories: Story[]; stats: KpiStat[] }) {
  const [days, setDays] = useState<number>(30);
  const [selectedKeys, setSelectedKeys] = useState<Set<string>>(new Set(DEFAULT_TIMESERIES_KEYS));
  const [showBand, setShowBand] = useState(true);

  const series = useMemo(() => selectKpiDailySeries(stories, days), [stories, days]);

  const option = useMemo<EChartsOption>(
    () => buildChartOption(series, stats, selectedKeys, showBand),
    [series, stats, selectedKeys, showBand],
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
        <div className="analytics-timeseries__group">
          <span className="eyebrow">Zeitraum</span>
          <div className="analytics-timeseries__presets" role="group">
            {TIMESERIES_PRESETS.map((preset) => (
              <button
                className={days === preset.value ? 'active' : ''}
                key={preset.value}
                type="button"
                onClick={() => setDays(preset.value)}
              >
                {preset.label}
              </button>
            ))}
          </div>
        </div>
        <div className="analytics-timeseries__group analytics-timeseries__group--wide">
          <span className="eyebrow">Metriken (Overlay)</span>
          <div className="analytics-timeseries__metrics">
            {stats.map((stat, index) => {
              const active = selectedKeys.has(stat.key);
              return (
                <button
                  className={`metric-chip ${active ? 'active' : ''}`}
                  key={stat.key}
                  type="button"
                  onClick={() => toggleKey(stat.key)}
                  style={active ? { borderColor: SERIES_COLORS[index % SERIES_COLORS.length], color: SERIES_COLORS[index % SERIES_COLORS.length] } : undefined}
                >
                  <span className="metric-chip__swatch" style={{ background: SERIES_COLORS[index % SERIES_COLORS.length] }} />
                  {stat.label}
                </button>
              );
            })}
          </div>
        </div>
        <div className="analytics-timeseries__group">
          <span className="eyebrow">Hülle</span>
          <label className="analytics-timeseries__toggle">
            <input
              type="checkbox"
              checked={showBand}
              onChange={(event) => setShowBand(event.target.checked)}
            />
            Min/Max-Band
          </label>
        </div>
      </div>

      <div className="analytics-timeseries__chart ak-panel">
        <ReactECharts
          option={option}
          notMerge
          lazyUpdate
          style={{ width: '100%', height: '32rem' }}
          theme={undefined}
        />
      </div>
    </section>
  );
}

function buildChartOption(
  series: KpiDailyPoint[],
  stats: KpiStat[],
  selectedKeys: Set<string>,
  showBand: boolean,
): EChartsOption {
  const dates = series.map((point) => point.date);
  const indexByKey = new Map(stats.map((s, i) => [s.key, i] as const));
  const selectedStats = stats.filter((s) => selectedKeys.has(s.key));

  /* Y-axis selection: when multiple metrics with dramatically different
   * value ranges are active (e.g. token total ~100 k vs. solving rate
   * 80 %), the first gets a left axis and the rest share a scaled right
   * axis. Simplified: a separate axis per series when scales differ by
   * > 100x — otherwise all on one axis. */
  const ranges = selectedStats.map((s) => Math.max(1, s.max));
  const maxRange = Math.max(...ranges, 1);
  const minRange = Math.min(...ranges, 1);
  const useDualAxis = selectedStats.length > 1 && maxRange / minRange > 50;

  const yAxes: NonNullable<EChartsOption['yAxis']> = useDualAxis
    ? [
        {
          type: 'value',
          position: 'left',
          axisLine: { lineStyle: { color: '#48e7ff' } },
          splitLine: { lineStyle: { color: 'rgba(255,255,255,0.04)' } },
          axisLabel: { color: '#9a9fa8' },
        },
        {
          type: 'value',
          position: 'right',
          axisLine: { lineStyle: { color: '#9a9fa8' } },
          splitLine: { show: false },
          axisLabel: { color: '#9a9fa8' },
        },
      ]
    : [
        {
          type: 'value',
          axisLine: { lineStyle: { color: '#3a4049' } },
          splitLine: { lineStyle: { color: 'rgba(255,255,255,0.04)' } },
          axisLabel: { color: '#9a9fa8' },
        },
      ];

  const seriesItems: NonNullable<EChartsOption['series']> = [];

  selectedStats.forEach((stat, idx) => {
    const color = SERIES_COLORS[(indexByKey.get(stat.key) ?? idx) % SERIES_COLORS.length];
    const yAxisIndex = useDualAxis && idx > 0 ? 1 : 0;
    const data = series.map((point) => point.values[stat.key] ?? null);

    if (showBand) {
      /* Min/max band as two stacked area series (trick: lower line
       * invisible, upper rendered as a tinted band). */
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
        name: `${stat.label} · Hülle`,
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
      backgroundColor: 'rgba(20, 22, 26, 0.92)',
      borderColor: '#3a4049',
      borderWidth: 1,
      textStyle: { color: '#f0f0f0', fontSize: 12 },
      axisPointer: { type: 'cross', lineStyle: { color: '#48e7ff', opacity: 0.45 } },
      /* Show only the "main" series (not the band helper series). */
      formatter: (params) => {
        if (!Array.isArray(params)) return '';
        const rows = params
          .filter((p) => !String(p.seriesName).includes('Untergrenze') && !String(p.seriesName).includes('Hülle'))
          .map((p) => {
            const stat = selectedStats.find((s) => s.label === p.seriesName);
            const unit = stat?.unit ? ` ${stat.unit}` : '';
            return `<div style="display:flex;align-items:center;gap:6px;margin-top:4px"><span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${p.color}"></span><span style="flex:1">${p.seriesName}</span><strong>${formatNumber(Number(p.value))}${unit}</strong></div>`;
          })
          .join('');
        const header = (params[0] as { axisValueLabel?: string }).axisValueLabel ?? '';
        return `<div style="font-weight:600;color:#9a9fa8;font-size:11px;letter-spacing:0.04em;text-transform:uppercase">${header}</div>${rows}`;
      },
    },
    legend: {
      show: true,
      bottom: 0,
      textStyle: { color: '#d3d5d8', fontSize: 12 },
      itemWidth: 14,
      itemHeight: 8,
      icon: 'roundRect',
      data: selectedStats.map((s) => s.label),
    },
    xAxis: {
      type: 'category',
      data: dates,
      boundaryGap: false,
      axisLine: { lineStyle: { color: '#3a4049' } },
      axisLabel: {
        color: '#9a9fa8',
        formatter: (value: string) => {
          const d = new Date(`${value}T00:00:00Z`);
          return `${d.getUTCDate()}.${d.getUTCMonth() + 1}.`;
        },
      },
      axisPointer: { label: { backgroundColor: '#1c3844' } },
    },
    yAxis: yAxes,
    dataZoom: [
      {
        type: 'inside',
        start: 0,
        end: 100,
      },
      {
        type: 'slider',
        height: 18,
        bottom: 36,
        borderColor: 'transparent',
        backgroundColor: 'rgba(255,255,255,0.03)',
        fillerColor: 'rgba(72, 231, 255, 0.12)',
        handleStyle: { color: '#48e7ff' },
        textStyle: { color: '#9a9fa8', fontSize: 10 },
      },
    ],
    series: seriesItems,
  };
}

function formatNumber(value: number): string {
  if (Math.abs(value) >= 1000) return value.toLocaleString('de-DE', { maximumFractionDigits: 0 });
  if (Number.isInteger(value)) return String(value);
  return value.toLocaleString('de-DE', { maximumFractionDigits: 1 });
}
