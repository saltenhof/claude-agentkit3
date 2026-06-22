import { Copy } from 'lucide-react';
import type { ReactElement } from 'react';

import type { StorySummary } from '../../story_context_manager/types';
import type { ExecutionInputSnapshot, ExecutionInputStack } from '../types';

interface ReadyStackViewProps {
  input: ExecutionInputSnapshot | null;
  onSelectStory: (storyId: string) => void;
}

export function ReadyStackView({ input, onSelectStory }: Readonly<ReadyStackViewProps>): ReactElement {
  const running = input?.running ?? [];
  const eligibleReady = input?.eligible_ready ?? [];
  const totalReady = input?.total_ready ?? 0;
  const globalSlotsLeft = input?.global_slots_left ?? 0;

  return (
    <div className="ready-stack-view">
      <header className="ready-stack-view__header">
        <h2>Execution Input</h2>
        <p>
          {running.length} laufend · {eligibleReady.length} delegierbar von {totalReady} ready.
          Globale Slots frei: {globalSlotsLeft}.
        </p>
      </header>

      <ReadyStackSection
        title={`Aktuell laufend (${running.length})`}
        emptyLabel="Keine laufende Story"
        stacks={running}
        onSelectStory={onSelectStory}
      />
      <ReadyStackSection
        title={`Effektiv delegierbar (${eligibleReady.length})`}
        emptyLabel="Keine ausfuehrbare Story"
        stacks={eligibleReady}
        copyable
        onSelectStory={onSelectStory}
      />
    </div>
  );
}

function ReadyStackSection({
  title,
  emptyLabel,
  stacks,
  copyable = false,
  onSelectStory,
}: Readonly<{
  title: string;
  emptyLabel: string;
  stacks: readonly ExecutionInputStack[];
  copyable?: boolean;
  onSelectStory: (storyId: string) => void;
}>): ReactElement {
  return (
    <section className="ready-stack-section">
      <header className="ready-stack-section__header">
        <h3>{title}</h3>
        {copyable && (
          <button
            className="copy-ids-button"
            disabled={stacks.length === 0}
            title="Story-IDs kopieren"
            type="button"
            onClick={() =>
              globalThis.navigator.clipboard
                ?.writeText(stacks.map((stack) => stack.story.story_id).join(', '))
                .catch(() => undefined)
            }
          >
            <Copy size={14} />
          </button>
        )}
      </header>
      <div className="ready-stack-grid">
        {stacks.length > 0 ? (
          stacks.map((stack) => (
            <StackColumn key={stack.story.story_id} stack={stack} onSelectStory={onSelectStory} />
          ))
        ) : (
          <PlaceholderColumn centerLabel={emptyLabel} />
        )}
      </div>
    </section>
  );
}

function StackColumn({
  stack,
  onSelectStory,
}: Readonly<{ stack: ExecutionInputStack; onSelectStory: (storyId: string) => void }>): ReactElement {
  return (
    <div className="ready-stack-column">
      <StackCard story={stack.predecessor ?? null} variant="completed" placeholderLabel="Kein Vorgaenger" />
      <StackCard story={stack.story} variant="current" onSelectStory={onSelectStory} />
      <StackCard story={stack.successor ?? null} variant="upcoming" placeholderLabel="Kein Nachfolger" />
    </div>
  );
}

function PlaceholderColumn({ centerLabel }: Readonly<{ centerLabel: string }>): ReactElement {
  return (
    <div className="ready-stack-column">
      <StackCard story={null} variant="placeholder" placeholderLabel="Kein Vorgaenger" />
      <StackCard story={null} variant="placeholder" placeholderLabel={centerLabel} />
      <StackCard story={null} variant="placeholder" placeholderLabel="Kein Nachfolger" />
    </div>
  );
}

function StackCard({
  story,
  variant,
  placeholderLabel,
  onSelectStory,
}: Readonly<{
  story: StorySummary | null;
  variant: 'completed' | 'current' | 'upcoming' | 'placeholder';
  placeholderLabel?: string;
  onSelectStory?: (storyId: string) => void;
}>): ReactElement {
  if (story === null) {
    return <div className="ready-stack-card is-placeholder">{placeholderLabel}</div>;
  }
  return (
    <button
      className="ready-stack-card"
      data-variant={variant}
      type="button"
      onClick={() => onSelectStory?.(story.story_id)}
    >
      <strong>{story.story_id}</strong>
      <span>{story.title}</span>
      <small>{story.module || story.epic || story.status}</small>
    </button>
  );
}
