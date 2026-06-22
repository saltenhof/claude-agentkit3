import type { ReactElement } from 'react';

import type { StorySummary } from '../types';
import { KanbanToolbar } from './KanbanToolbar';
import { StoryCard } from './StoryCard';
import { sortStories, STORY_STATUS_COLUMNS, type KanbanSortMode, type StoryStatusFilter } from './storyFilters';

interface KanbanBoardProps {
  stories: readonly StorySummary[];
  totalStoryCount: number;
  selectedStoryId: string | null;
  storyIdFilter: string;
  statusFilter: StoryStatusFilter;
  sortMode: KanbanSortMode;
  onSelectStory: (storyId: string) => void;
  onStoryIdFilterChange: (value: string) => void;
  onStatusFilterChange: (value: StoryStatusFilter) => void;
  onSortModeChange: (value: KanbanSortMode) => void;
}

export function KanbanBoard({
  stories,
  totalStoryCount,
  selectedStoryId,
  storyIdFilter,
  statusFilter,
  sortMode,
  onSelectStory,
  onStoryIdFilterChange,
  onStatusFilterChange,
  onSortModeChange,
}: Readonly<KanbanBoardProps>): ReactElement {
  const sortedStories = sortStories(stories, sortMode);

  return (
    <div className="kanban-view">
      <KanbanToolbar
        storyIdFilter={storyIdFilter}
        statusFilter={statusFilter}
        sortMode={sortMode}
        visibleCount={stories.length}
        totalCount={totalStoryCount}
        onStoryIdFilterChange={onStoryIdFilterChange}
        onStatusFilterChange={onStatusFilterChange}
        onSortModeChange={onSortModeChange}
      />
      <div className="kanban-board">
        {STORY_STATUS_COLUMNS.map((status) => {
          const columnStories = sortedStories.filter((story) => story.status === status);
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
    </div>
  );
}
