/*
 * Execution-Input-View — running and effectively delegatable stories.
 *
 * ---------------------------------------------------------------
 * Layout invariants (normative UI behaviour, FK-72 prototype):
 * ---------------------------------------------------------------
 *
 * 1. Both sections ("Currently running" and "Effectively delegatable")
 *    are ALWAYS visible — even when their respective list is empty.
 *    Headline and section order remain fixed. This prevents the user
 *    getting a "is the view broken?" impression with an empty backlog.
 *
 * 2. When a list is empty, exactly ONE placeholder column is rendered:
 *    three placeholder cards (predecessor / "no running story" or
 *    "no executable story" / successor). This provides a visual anchor
 *    into which later SSE updates can insert cards without the layout
 *    shifting.
 *
 * 3. With real stories a real column replaces the placeholder column;
 *    further stories dock to the right. No layout jump.
 *
 * 4. Logic (triage against caps, round-robin per repo, critical-path
 *    prioritized) lives in the store (`selectExecutionInput`). This
 *    view is pure presentation.
 *
 * 5. Copy mechanics (hand-off to orchestrator):
 *    - Bulk-copy behind the "Effectively delegatable" headline
 *      copies all delegatable story IDs as a
 *      "BB2-X, BB2-Y, BB2-Z" string (comma + space separated).
 *      Disabled while the section is empty.
 *      Consumer: operator passing the set in one shot to an
 *      orchestrator skill.
 *    - Per-card copy in the top-right of each delegatable story
 *      copies exclusively that one story ID.
 *      Consumer: operator delegating a specific single story.
 *    Per-card copy is active only for variant 'current' via the
 *    showCopyId prop. Predecessor, successor, running and placeholder
 *    cards show no copy button — they are not the delegatable set.
 *    Active "Currently running" cards intentionally have no copy
 *    button: they are already delegated, copying them again for
 *    hand-off makes no domain sense.
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
          {/* Bulk copy — see §5 copy mechanics in the header comment. */}
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
 * PlaceholderColumn — rendered when the section is empty.
 * Same three-part layout as a real column (predecessor / story /
 * successor) so the view layout stays fixed and SSE updates can
 * insert cards without a layout jump.
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
