import type { KpiTileData } from '../lib/storyKpis';

export function KpiTile({ label, value, suffix, tone = 'default' }: KpiTileData) {
  const className = tone === 'warning' ? 'kpi-tile kpi-tile--warning' : 'kpi-tile';
  return (
    <div className={className}>
      <div className="kpi-tile__label">{label}</div>
      <div className="kpi-tile__value">
        <span className="kpi-tile__number">{value}</span>
        {suffix !== undefined ? <span className="kpi-tile__suffix">{suffix}</span> : null}
      </div>
    </div>
  );
}

export function KpiBar({ tiles }: { tiles: KpiTileData[] }) {
  return (
    <div className="kpi-bar" role="group" aria-label="Story KPIs">
      {tiles.map((tile) => (
        <KpiTile key={tile.label} {...tile} />
      ))}
    </div>
  );
}
