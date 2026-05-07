import { selectReadyStacks, type Story } from '../store';
import { StoryCard } from './StoryCard';

export function ReadyStackView({
  stories,
  onSelect,
}: {
  stories: Story[];
  onSelect: (story: Story) => void;
}) {
  const stacks = selectReadyStacks(stories);

  if (stacks.length === 0) {
    return (
      <div className="ready-stack-empty">
        <strong>Keine Story aktuell delegierbar.</strong>
        <p>
          Alle freigegebenen Stories haben offene Abhängigkeiten oder sind bereits in
          Bearbeitung.
        </p>
      </div>
    );
  }

  return (
    <div className="ready-stack-view">
      <header className="ready-stack-view__header">
        <h2>{stacks.length === 1 ? '1 Story delegierbar' : `${stacks.length} Stories delegierbar`}</h2>
        <p>
          Kontextkachel oben (Vorgänger), aktuelle Story mittig, Nachfolger ausgegraut.
        </p>
      </header>
      <div className="ready-stack-grid">
        {stacks.map(({ story, predecessor, successor }) => (
          <div key={story.id} className="ready-stack-column">
            <StoryCard
              story={predecessor}
              variant="completed"
              placeholderLabel="Kein Vorgänger"
            />
            <StoryCard story={story} variant="current" onSelect={onSelect} />
            <StoryCard
              story={successor}
              variant="upcoming"
              placeholderLabel="Kein Nachfolger"
            />
          </div>
        ))}
      </div>
    </div>
  );
}
