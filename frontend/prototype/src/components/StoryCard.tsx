import type { Story } from '../store';
import { CopyButton } from './CopyButton';
import { FastBadge } from './FastBadge';

export type StoryCardVariant = 'completed' | 'current' | 'running' | 'upcoming' | 'placeholder';

export interface StoryCardProps {
  story: Story | null;
  variant: StoryCardVariant;
  placeholderLabel?: string;
  onSelect?: (story: Story) => void;
  /* When set, a copy button is shown in the card header to the right
   * of the size badge. Click copies this card's story ID to the
   * clipboard. */
  showCopyId?: boolean;
}

export function StoryCard({ story, variant, placeholderLabel, onSelect, showCopyId }: StoryCardProps) {
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
          <FastBadge mode={story.mode} size={13} />
          {variant === 'running' && (
            <span className="story-card__status-badge">In Progress</span>
          )}
        </div>
        <div className="story-card__header-right">
          <span className="story-card__size">{story.size}</span>
          {showCopyId && (
            <CopyButton
              text={story.id}
              ariaLabel={`Story-ID ${story.id} kopieren`}
              size="sm"
            />
          )}
        </div>
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
