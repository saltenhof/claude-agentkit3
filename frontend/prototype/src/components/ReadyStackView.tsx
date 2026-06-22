/*
 * Execution-Input-View — laufende und effektiv delegierbare Stories.
 *
 * ---------------------------------------------------------------
 * Layout-Invarianten (normatives UI-Verhalten, FK-72 Prototyp):
 * ---------------------------------------------------------------
 *
 * 1. Beide Sektionen ("Aktuell laufend" und "Effektiv delegierbar")
 *    sind IMMER sichtbar — auch wenn die jeweilige Liste leer ist.
 *    Headline und Sektion-Reihenfolge bleiben ortsfest. Damit hat
 *    der User keinen "ist die View kaputt?"-Eindruck bei leerem
 *    Backlog.
 *
 * 2. Ist eine Liste leer, wird genau EINE Platzhalter-Saeule
 *    gerendert: drei Placeholder-Karten (Vorgaenger / "keine
 *    laufende Story" bzw. "keine ausfuehrbare Story" / Nachfolger).
 *    Damit gibt es eine visuelle Andocke, in die spaetere
 *    SSE-Updates Karten einfuegen koennen, ohne dass das Layout
 *    wandert.
 *
 * 3. Bei echten Stories ersetzt eine echte Spalte die Platzhalter-
 *    Saeule; weitere Stories docken nach rechts an. Kein
 *    Layout-Sprung.
 *
 * 4. Logik (Triage gegen Caps, Round-Robin pro Repo, Critical-Path
 *    priorisiert) liegt im Store (`selectExecutionInput`). Diese
 *    View ist reine Praesentation.
 *
 * 5. Copy-Mechanik (Hand-off an Orchestrator):
 *    - Bulk-Copy hinter der Headline "Effektiv delegierbar"
 *      kopiert alle delegierbaren Story-IDs als
 *      "BB2-X, BB2-Y, BB2-Z"-String (Komma plus Leerzeichen
 *      getrennt). Disabled, solange die Sektion leer ist.
 *      Konsument: Operator, der das Set in einem Rutsch an
 *      einen Orchestrator-Skill weiterreichen will.
 *    - Per-Card-Copy oben rechts in jeder delegierbaren Story
 *      kopiert ausschliesslich diese eine Story-ID. Konsument:
 *      Operator, der eine gezielte Einzel-Story delegiert.
 *    Per-Card-Copy ist per showCopyId-Prop nur fuer Variant
 *    'current' aktiv. Vorgaenger, Nachfolger, Running- und
 *    Placeholder-Karten zeigen keinen Copy-Button — sie sind
 *    nicht das delegierbare Set.
 *    Aktive "Aktuell laufend"-Karten haben bewusst keinen
 *    Copy-Button: sie sind bereits delegiert, ein erneutes
 *    Kopieren fuer Hand-off ergibt fachlich keinen Sinn.
 */

import {
  selectExecutionInput,
  type ExecutionLimits,
  type ReadyStack,
  type Story,
} from '../store';
import { CopyButton } from './CopyButton';
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

      <section className="ready-stack-section">
        <header className="ready-stack-section__header">
          <h3 className="ready-stack-section__title">
            Aktuell laufend ({running.length})
          </h3>
        </header>
        <div className="ready-stack-grid">
          {running.length > 0 ? (
            running.map((stack) => (
              <StackColumn
                key={stack.story.id}
                stack={stack}
                variant="running"
                onSelect={onSelect}
              />
            ))
          ) : (
            <PlaceholderColumn centerLabel="Keine laufende Story" />
          )}
        </div>
      </section>

      <section className="ready-stack-section">
        <header className="ready-stack-section__header">
          <h3 className="ready-stack-section__title">
            Effektiv delegierbar ({eligibleReady.length})
          </h3>
          {/* Bulk-Copy — siehe §5 Copy-Mechanik im Header-Kommentar. */}
          <CopyButton
            text={() => eligibleReady.map((s) => s.story.id).join(', ')}
            ariaLabel="Alle delegierbaren Story-IDs kopieren"
            disabled={eligibleReady.length === 0}
          />
        </header>
        <div className="ready-stack-grid">
          {eligibleReady.length > 0 ? (
            eligibleReady.map((stack) => (
              <StackColumn
                key={stack.story.id}
                stack={stack}
                variant="current"
                onSelect={onSelect}
                showCopyId
              />
            ))
          ) : (
            <PlaceholderColumn centerLabel="Keine ausführbare Story" />
          )}
        </div>
      </section>
    </div>
  );
}

function StackColumn({
  stack,
  variant,
  onSelect,
  showCopyId,
}: {
  stack: ReadyStack;
  variant: 'running' | 'current';
  onSelect: (story: Story) => void;
  showCopyId?: boolean;
}) {
  return (
    <div className="ready-stack-column">
      <StoryCard
        story={stack.predecessor}
        variant="completed"
        placeholderLabel="Kein Vorgänger"
      />
      <StoryCard
        story={stack.story}
        variant={variant}
        onSelect={onSelect}
        showCopyId={showCopyId}
      />
      <StoryCard
        story={stack.successor}
        variant="upcoming"
        placeholderLabel="Kein Nachfolger"
      />
    </div>
  );
}

/*
 * PlaceholderColumn — wird gerendert, wenn die Sektion leer ist.
 * Gleiches dreiteiliges Layout wie eine echte Spalte (Vorgaenger /
 * Story / Nachfolger), damit das Layout der View ortsfest bleibt
 * und SSE-Updates ohne Layout-Sprung Karten einsetzen koennen.
 */
function PlaceholderColumn({ centerLabel }: { centerLabel: string }) {
  return (
    <div className="ready-stack-column">
      <StoryCard story={null} variant="placeholder" placeholderLabel="Kein Vorgänger" />
      <StoryCard story={null} variant="placeholder" placeholderLabel={centerLabel} />
      <StoryCard story={null} variant="placeholder" placeholderLabel="Kein Nachfolger" />
    </div>
  );
}
