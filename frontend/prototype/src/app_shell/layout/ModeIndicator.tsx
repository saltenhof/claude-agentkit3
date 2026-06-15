import type { ProjectModeLock } from '../../store';

export function ModeIndicator({ mode }: { mode: ProjectModeLock }) {
  const tone = mode ?? 'idle';
  const label = mode === 'fast' ? 'Fast' : mode === 'standard' ? 'Standard' : 'Idle';
  const title =
    mode === null
      ? 'Kein Modus aktiv — keine Story in Bearbeitung.'
      : mode === 'fast'
        ? 'Fast-Modus aktiv: Exploration ausgelassen, Standard-Stories blockiert (FK-24 §24.3.3).'
        : 'Standard-Modus aktiv: Fast-Stories blockiert (FK-24 §24.3.3).';
  return (
    <span
      className={`mode-indicator mode-indicator--${tone}`}
      role="status"
      title={title}
      aria-label={`Projekt-Mode: ${label}`}
    >
      <span className="mode-indicator__dot" aria-hidden="true" />
      <span className="mode-indicator__label">Mode</span>
      <span className="mode-indicator__value">{label}</span>
    </span>
  );
}
