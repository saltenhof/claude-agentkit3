import { EXECUTION_LIMIT_DESCRIPTORS, type ExecutionLimits } from '../store';
import { NumberStepper } from './NumberStepper';

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
          Diese Caps bilden die zentrale Kapazitätsschicht (FK-70 §70.6.2): sie
          schneiden zwischen theoretischer Parallelisierbarkeit (Graph-Feasibility)
          und der maximal erlaubten parallelen Ausführung. Harte Abhängigkeiten
          stechen jeden Cap.
        </p>
        <p className="execution-limits-view__hint">
          Aenderungen werden <strong>sofort uebernommen</strong> (Echtzeit-Modus
          fuer den Prototyp; reales Backend wuerde Optimistic-Update +
          debounced Sync nutzen). Effekt ist direkt in der Execution-Input-View
          sichtbar.
        </p>
      </header>
      <div className="execution-limits-grid">
        {EXECUTION_LIMIT_DESCRIPTORS.map((descriptor) => (
          <div key={descriptor.key} className="execution-limits-field">
            <div className="execution-limits-field__label">{descriptor.label}</div>
            <div className="execution-limits-field__description">{descriptor.description}</div>
            <div className="execution-limits-field__control">
              <NumberStepper
                value={limits[descriptor.key]}
                min={0}
                step={1}
                ariaLabel={descriptor.label}
                onChange={(next) =>
                  onChange({
                    ...limits,
                    [descriptor.key]: next,
                  })
                }
              />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
