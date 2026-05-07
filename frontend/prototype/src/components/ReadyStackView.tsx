/*
 * Execution Input — laufende und effektiv delegierbare Stories.
 *
 * Sicht zeigt zwei Sektionen:
 *   - "Aktuell laufend" (status = In Progress): bereits delegierte
 *     Stories. Sie belegen Slots und werden hier sichtbar als
 *     Running-Karten dargestellt.
 *   - "Effektiv delegierbar": Ready-Stories nach Triage gegen die
 *     Execution Limits (FK-70 §70.6.2). Mehr als globalSlotsLeft
 *     wird nicht angezeigt.
 *
 * Die Triage-Logik liegt im Store (`selectExecutionInput`). Diese
 * Komponente ist reine Praesentation.
 */

import {
  selectExecutionInput,
  type ExecutionLimits,
  type ReadyStack,
  type Story,
} from '../store';
import { StoryCard } from './StoryCard';

export function ReadyStackView({
  stories,
  limits,
  onSelect,
}: {
  stories: Story[];
  limits: ExecutionLimits;
  onSelect: (story: Story) => void;
}) {
  const { running, eligibleReady, totalReady, globalSlotsLeft } =
    selectExecutionInput(stories, limits);

  if (running.length === 0 && eligibleReady.length === 0) {
    return (
      <div className="ready-stack-empty">
        <strong>Keine Story aktuell delegierbar oder laufend.</strong>
        <p>
          {totalReady > 0
            ? `Theoretisch ready: ${totalReady}. Aktuell schöpfen die Execution-Caps die freien Slots auf 0 — pruefe die Limits-View.`
            : 'Alle freigegebenen Stories haben offene Abhängigkeiten oder sind bereits abgeschlossen.'}
        </p>
      </div>
    );
  }

  return (
    <div className="ready-stack-view">
      <header className="ready-stack-view__header">
        <h2>Execution Input</h2>
        <p>
          {running.length} laufend · {eligibleReady.length} delegierbar (von{' '}
          {totalReady} ready). Globale Slots frei: {globalSlotsLeft}. Triage:
          Round-Robin pro Repo, Critical-Path priorisiert, dann Story-Nummer.
        </p>
      </header>

      {running.length > 0 && (
        <section className="ready-stack-section">
          <h3 className="ready-stack-section__title">
            Aktuell laufend ({running.length})
          </h3>
          <div className="ready-stack-grid">
            {running.map((stack) => (
              <StackColumn
                key={stack.story.id}
                stack={stack}
                variant="running"
                onSelect={onSelect}
              />
            ))}
          </div>
        </section>
      )}

      {eligibleReady.length > 0 && (
        <section className="ready-stack-section">
          <h3 className="ready-stack-section__title">
            Effektiv delegierbar ({eligibleReady.length})
          </h3>
          <div className="ready-stack-grid">
            {eligibleReady.map((stack) => (
              <StackColumn
                key={stack.story.id}
                stack={stack}
                variant="current"
                onSelect={onSelect}
              />
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

function StackColumn({
  stack,
  variant,
  onSelect,
}: {
  stack: ReadyStack;
  variant: 'running' | 'current';
  onSelect: (story: Story) => void;
}) {
  return (
    <div className="ready-stack-column">
      <StoryCard
        story={stack.predecessor}
        variant="completed"
        placeholderLabel="Kein Vorgänger"
      />
      <StoryCard story={stack.story} variant={variant} onSelect={onSelect} />
      <StoryCard
        story={stack.successor}
        variant="upcoming"
        placeholderLabel="Kein Nachfolger"
      />
    </div>
  );
}
