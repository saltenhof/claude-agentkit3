import type { ReactElement } from 'react';

import type { StorySummary } from '../types';

interface StoryCardProps {
  story: StorySummary;
  selected: boolean;
  onSelect: (storyId: string) => void;
}

export function StoryCard({ story, selected, onSelect }: Readonly<StoryCardProps>): ReactElement {
  return (
    <button
      className="story-card"
      data-selected={selected}
      type="button"
      onClick={() => onSelect(story.story_id)}
    >
      <div className="story-card-head">
        <strong>{story.story_id}</strong>
        <span data-risk={story.risk}>{story.risk}</span>
      </div>
      <h3>{story.title}</h3>
      <p>{story.module || story.epic || 'ohne Modul'} · Wave {story.wave}</p>
      <div className="story-meta">
        <span data-tone={story.type}>{story.type}</span>
        <span>{story.size}</span>
        {story.critical_path && <span data-tone="critical">critical</span>}
      </div>
    </button>
  );
}
