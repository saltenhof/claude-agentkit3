import type { Story } from '../data';

export interface ReadyStack {
  story: Story;
  predecessor: Story | null;
  successor: Story | null;
}

export function buildReadyStacks(stories: Story[]): ReadyStack[] {
  const doneIds = new Set(
    stories.filter((s) => s.status === 'Done').map((s) => s.id),
  );
  const hasOpenDependency = (story: Story): boolean =>
    story.dependencies.some((dep) => !doneIds.has(dep));
  const isReady = (story: Story): boolean =>
    story.status === 'Approved' && !story.blocker && !hasOpenDependency(story);

  const successorsByStoryId = new Map<string, Story[]>();
  for (const candidate of stories) {
    for (const depId of candidate.dependencies) {
      const list = successorsByStoryId.get(depId) ?? [];
      list.push(candidate);
      successorsByStoryId.set(depId, list);
    }
  }

  const findById = (id: string): Story | null =>
    stories.find((s) => s.id === id) ?? null;

  return stories.filter(isReady).map((story) => ({
    story,
    predecessor:
      story.dependencies.length > 0 ? findById(story.dependencies[0]) : null,
    successor: successorsByStoryId.get(story.id)?.[0] ?? null,
  }));
}
