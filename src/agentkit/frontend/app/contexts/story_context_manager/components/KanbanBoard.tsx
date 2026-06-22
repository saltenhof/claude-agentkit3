import type { ReactElement } from 'react';

import type { StorySummary } from '../types';
import { StoryCard } from './StoryCard';
import { STORY_STATUS_COLUMNS } from './storyFilters';

interface KanbanBoardProps {
  stories: readonly StorySummary[];
  selectedStoryId: string | null;
  onSelectStory: (storyId: string) => void;
}

export function KanbanBoard({
  stories,
  selectedStoryId,
  onSelectStory,
}: Readonly<KanbanBoardProps>): ReactElement {
  return (
    <div className="kanban-board">
      {STORY_STATUS_COLUMNS.map((status) => {
        const columnStories = stories.filter((story) => story.status === status);
        return (
          <section className="kanban-column" key={status}>
            <header>
              <h2>{status}</h2>
              <span>{columnStories.length}</span>
            </header>
            <div className="kanban-list">
              {columnStories.map((story) => (
                <StoryCard
                  key={story.story_id}
                  story={story}
                  selected={selectedStoryId === story.story_id}
                  onSelect={onSelectStory}
                />
              ))}
            </div>
          </section>
        );
      })}
    </div>
  );
}
