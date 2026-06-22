import { useMemo } from 'react';
import type { ReactElement } from 'react';

import type { StorySummary } from '../../story_context_manager/types';
import type { DependencyEdge } from '../types';

interface DependencyGraphProps {
  dependencies: readonly DependencyEdge[];
  stories: readonly StorySummary[];
  onSelectStory: (storyId: string) => void;
}

export function DependencyGraph({
  dependencies,
  stories,
  onSelectStory,
}: Readonly<DependencyGraphProps>): ReactElement {
  const positioned = useMemo(
    () => stories.map((story, index) => ({
      story,
      x: 80 + (index % 4) * 260,
      y: 70 + Math.floor(index / 4) * 150,
    })),
    [stories],
  );
  const byId = new Map(positioned.map((entry) => [entry.story.story_id, entry]));

  if (stories.length === 0) {
    return <EmptyGraph />;
  }

  return (
    <div className="graph-view">
      <svg viewBox="0 0 1120 680" aria-label="Dependency Graph">
        {dependencies.map((edge) => {
          const fromId = edge.from_story_id ?? edge.depends_on_story_id;
          const toId = edge.to_story_id ?? edge.story_id;
          const from = fromId === undefined ? undefined : byId.get(fromId);
          const to = toId === undefined ? undefined : byId.get(toId);
          if (from === undefined || to === undefined) {
            return null;
          }
          return (
            <line
              className="graph-edge"
              key={`${from.story.story_id}-${to.story.story_id}-${edge.kind}`}
              x1={from.x + 170}
              y1={from.y + 45}
              x2={to.x}
              y2={to.y + 45}
            />
          );
        })}
        {positioned.map(({ story, x, y }) => (
          <a
            className="graph-node"
            href={`#story-${encodeURIComponent(story.story_id)}`}
            key={story.story_id}
            onClick={(event) => {
              event.preventDefault();
              onSelectStory(story.story_id);
            }}
          >
            <rect x={x} y={y} width="205" height="92" rx="8" />
            <text x={x + 14} y={y + 27}>{story.story_id}</text>
            <text x={x + 14} y={y + 52}>{truncate(story.title, 28)}</text>
            <text x={x + 14} y={y + 76}>{story.status}</text>
          </a>
        ))}
      </svg>
    </div>
  );
}

function EmptyGraph(): ReactElement {
  return (
    <div className="empty-state">
      <h2>Keine Stories</h2>
      <p>Der Dependency Graph wartet auf Story-Daten aus dem Backend.</p>
    </div>
  );
}

function truncate(value: string, limit: number): string {
  return value.length <= limit ? value : `${value.slice(0, limit - 1)}...`;
}
