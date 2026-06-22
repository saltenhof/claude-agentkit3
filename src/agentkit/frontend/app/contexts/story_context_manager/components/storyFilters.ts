import type { StoryStatus, StorySummary } from '../types';

export const STORY_STATUS_COLUMNS: readonly StoryStatus[] = [
  'Backlog',
  'Approved',
  'In Progress',
  'Done',
  'Cancelled',
];

export function filterStories(stories: readonly StorySummary[], query: string): StorySummary[] {
  const normalized = query.trim().toLowerCase();
  if (!normalized) {
    return [...stories];
  }
  return stories.filter((story) =>
    [story.story_id, story.title, story.module, story.epic, story.owner, ...story.repos]
      .join(' ')
      .toLowerCase()
      .includes(normalized),
  );
}

export function countStatus(stories: readonly StorySummary[], status: StoryStatus): number {
  return stories.filter((story) => story.status === status).length;
}
