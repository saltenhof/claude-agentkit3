import type { ExecutionLimits } from '../lib/executionLimits';
import { EXECUTION_LIMIT_DESCRIPTORS } from '../lib/executionLimits';

export function ExecutionLimitsView({
  limits,
  onChange,
}: {
  limits: ExecutionLimits;
  onChange: (next: ExecutionLimits) => void;
}) {
  return (
    <div className="execution-limits-view">
      <header className="execution-limits-view__header">
        <h2>Execution Limits</h2>
        <p>
          Diese Caps bilden die zentrale Kapazitätsschicht: sie schneiden zwischen
          theoretischer Parallelisierbarkeit (Graph-Feasibility) und der maximal
          erlaubten parallelen Ausführung. Wirken zusammen, harte Abhängigkeiten
          stechen jeden Cap.
        </p>
      </header>
      <div className="execution-limits-grid">
        {EXECUTION_LIMIT_DESCRIPTORS.map((descriptor) => (
          <label key={descriptor.key} className="execution-limits-field">
            <div className="execution-limits-field__label">{descriptor.label}</div>
            <div className="execution-limits-field__description">{descriptor.description}</div>
            <input
              type="number"
              min={0}
              step={1}
              value={limits[descriptor.key]}
              onChange={(event) => {
                const parsed = Number(event.target.value);
                onChange({
                  ...limits,
                  [descriptor.key]: Number.isFinite(parsed) && parsed >= 0 ? parsed : 0,
                });
              }}
            />
          </label>
        ))}
      </div>
    </div>
  );
}
