import type { Story } from '../store';

export type StoryCardVariant = 'completed' | 'current' | 'running' | 'upcoming' | 'placeholder';

export interface StoryCardProps {
  story: Story | null;
  variant: StoryCardVariant;
  placeholderLabel?: string;
  onSelect?: (story: Story) => void;
}

export function StoryCard({ story, variant, placeholderLabel, onSelect }: StoryCardProps) {
  if (variant === 'placeholder' || story === null) {
    return (
      <div className="story-card story-card--placeholder">
        <span className="story-card__placeholder-label">
          {placeholderLabel ?? 'Kein Eintrag'}
        </span>
      </div>
    );
  }

  const className = `story-card story-card--${variant}`;
  const interactive = Boolean(onSelect);
  const handleClick = () => {
    if (onSelect) onSelect(story);
  };

  return (
    <div
      className={className}
      onClick={interactive ? handleClick : undefined}
      role={interactive ? 'button' : undefined}
      tabIndex={interactive ? 0 : undefined}
      onKeyDown={
        interactive
          ? (event) => {
              if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault();
                handleClick();
              }
            }
          : undefined
      }
    >
      <div className="story-card__header">
        <div className="story-card__header-left">
          <span className="story-card__id">{story.id}</span>
          {variant === 'running' && (
            <span className="story-card__status-badge">In Progress</span>
          )}
        </div>
        <span className="story-card__size">{story.size}</span>
      </div>
      <div className="story-card__title">{story.title}</div>
      <div className="story-card__meta">
        <span>{story.module}</span>
        <span aria-hidden="true">·</span>
        <span>{story.epic}</span>
      </div>
    </div>
  );
}
