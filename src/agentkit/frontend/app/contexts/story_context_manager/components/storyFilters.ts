import type { StoryStatus, StorySummary } from '../types';

export type StoryStatusFilter = 'all' | StoryStatus;
export type KanbanSortMode = 'id' | 'title' | 'epic' | 'module' | 'size';

export const STORY_STATUS_COLUMNS: readonly StoryStatus[] = [
  'Backlog',
  'Approved',
  'In Progress',
  'Done',
  'Cancelled',
];

export const KANBAN_SORT_LABELS: Record<KanbanSortMode, string> = {
  id: 'Story ID',
  title: 'Title',
  epic: 'Epic',
  module: 'Module',
  size: 'Size',
};

const STORY_SIZE_RANK: Record<StorySummary['size'], number> = {
  XS: 0,
  S: 1,
  M: 2,
  L: 3,
  XL: 4,
  XXL: 5,
};

export function filterStories(
  stories: readonly StorySummary[],
  query: string,
  statusFilter: StoryStatusFilter = 'all',
  storyIdFilter = '',
): StorySummary[] {
  const normalized = query.trim().toLowerCase();
  const normalizedStoryId = storyIdFilter.trim().toLowerCase();
  return stories.filter((story) =>
    (statusFilter === 'all' || story.status === statusFilter) &&
    (!normalizedStoryId || story.story_id.toLowerCase().includes(normalizedStoryId)) &&
    (!normalized ||
      [story.story_id, story.title, story.module, story.epic, story.owner, ...story.repos]
        .join(' ')
        .toLowerCase()
        .includes(normalized)),
  );
}

export function sortStories(stories: readonly StorySummary[], sortMode: KanbanSortMode): StorySummary[] {
  return [...stories].sort((left, right) => compareStories(left, right, sortMode));
}

export function countStatus(stories: readonly StorySummary[], status: StoryStatus): number {
  return stories.filter((story) => story.status === status).length;
}

function compareStories(left: StorySummary, right: StorySummary, sortMode: KanbanSortMode): number {
  if (sortMode === 'size') {
    return STORY_SIZE_RANK[left.size] - STORY_SIZE_RANK[right.size] || compareStoryId(left.story_id, right.story_id);
  }

  const leftValue = getSortValue(left, sortMode);
  const rightValue = getSortValue(right, sortMode);
  return leftValue.localeCompare(rightValue, 'en', { numeric: true, sensitivity: 'base' });
}

function getSortValue(story: StorySummary, sortMode: Exclude<KanbanSortMode, 'size'>): string {
  if (sortMode === 'id') {
    return story.story_id;
  }
  return story[sortMode] || '';
}

function compareStoryId(left: string, right: string): number {
  return left.localeCompare(right, 'en', { numeric: true, sensitivity: 'base' });
}
