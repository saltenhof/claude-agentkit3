import type { ReactElement } from 'react';

import type { ExecutionLimits } from '../types';

const LIMIT_LABELS: Record<Exclude<keyof ExecutionLimits, 'project_key'>, { label: string; description: string }> = {
  repo_parallel_cap: {
    label: 'Repo Parallel Cap',
    description: 'Maximale parallele Arbeit pro Repository.',
  },
  merge_risk_cap: {
    label: 'Merge Risk Cap',
    description: 'Begrenzt gleichzeitige Änderungen mit Merge-Risiko.',
  },
  max_parallel_agent_cap: {
    label: 'Max Parallel Agent Cap',
    description: 'Globale Obergrenze paralleler Agentenarbeit.',
  },
  llm_pool_cap: {
    label: 'LLM Pool Cap',
    description: 'Kapazitätsgrenze für LLM-gestützte Ausführung.',
  },
  ci_capacity_cap: {
    label: 'CI Capacity Cap',
    description: 'Parallelität, die CI noch stabil verarbeiten kann.',
  },
};

interface ExecutionLimitsViewProps {
  limits: ExecutionLimits | null;
}

export function ExecutionLimitsView({ limits }: Readonly<ExecutionLimitsViewProps>): ReactElement {
  return (
    <div className="execution-limits-view">
      <header className="execution-limits-view__header">
        <h2>Execution Limits</h2>
        <p>
          Diese Caps schneiden zwischen theoretischer Parallelisierbarkeit und maximal erlaubter
          paralleler Ausführung. Harte Abhängigkeiten bleiben führend.
        </p>
      </header>
      {limits === null ? (
        <div className="empty-panel">Keine Limits vom Backend geladen.</div>
      ) : (
        <div className="execution-limits-grid">
          {(Object.entries(LIMIT_LABELS) as Array<[keyof typeof LIMIT_LABELS, { label: string; description: string }]>)
            .map(([key, descriptor]) => (
              <section className="execution-limits-field" key={key}>
                <span>{descriptor.label}</span>
                <strong>{limits[key]}</strong>
                <p>{descriptor.description}</p>
              </section>
            ))}
        </div>
      )}
    </div>
  );
}
