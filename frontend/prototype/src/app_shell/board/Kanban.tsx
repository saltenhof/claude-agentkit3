import { useEffect, useMemo, useState } from 'react';
import { buildStoryKpiTiles } from '../../store';
import type { Story, StoryCounters } from '../../store';
import { KpiBar } from '../../components/KpiBar';
import { FastBadge } from '../../components/FastBadge';
import { Badge } from '../../design_system/Badge';
import { BffClient } from '../../foundation/bff/client';
import {
  NON_DRAGGABLE_STATUSES,
  resolveTransitionEndpoint,
} from './statusTransitions';

const STORY_STATUSES: Story['status'][] = ['Backlog', 'Approved', 'In Progress', 'Done', 'Cancelled'];

const statusClass: Record<Story['status'], string> = {
  Backlog: 'status-backlog',
  Approved: 'status-approved',
  'In Progress': 'status-progress',
  Done: 'success',
  Cancelled: 'cancelled',
};

type KanbanSortMode = 'id' | 'title' | 'epic' | 'module' | 'size' | 'createdAt';

const kanbanSortLabels: Record<KanbanSortMode, string> = {
  id: 'Story ID',
  title: 'Title',
  epic: 'Epic',
  module: 'Module',
  size: 'Size',
  createdAt: 'Created At',
};

const sizeRank: Record<Story['size'], number> = {
  XS: 1,
  S: 2,
  M: 3,
  L: 4,
  XL: 5,
  XXL: 6,
};

function compareStoryId(left: string, right: string): number {
  const leftMatch = left.match(/^(.+?)(\d+)$/);
  const rightMatch = right.match(/^(.+?)(\d+)$/);
  if (!leftMatch || !rightMatch) return left.localeCompare(right);
  const prefixCompare = leftMatch[1].localeCompare(rightMatch[1]);
  if (prefixCompare !== 0) return prefixCompare;
  return Number(leftMatch[2]) - Number(rightMatch[2]);
}

function compareKanbanStories(sortMode: KanbanSortMode, left: Story, right: Story): number {
  if (sortMode === 'title') return left.title.localeCompare(right.title) || compareStoryId(left.id, right.id);
  if (sortMode === 'epic') return left.epic.localeCompare(right.epic) || compareStoryId(left.id, right.id);
  if (sortMode === 'module') return left.module.localeCompare(right.module) || compareStoryId(left.id, right.id);
  if (sortMode === 'size')
    return sizeRank[left.size] - sizeRank[right.size] || compareStoryId(left.id, right.id);
  if (sortMode === 'createdAt')
    return (left.createdAt ?? '').localeCompare(right.createdAt ?? '') || compareStoryId(left.id, right.id);
  return compareStoryId(left.id, right.id);
}

const defaultBffClient = new BffClient('');

export function Kanban({
  projectKey,
  stories: boardStories,
  selectedStory,
  onSelect,
  onFocusStory,
  onStoryStatusChange,
  storyIdFilter,
  onStoryIdFilterChange,
  kpis,
  client = defaultBffClient,
  readOnly = false,
}: {
  projectKey: string;
  stories: Story[];
  selectedStory: Story | null;
  onSelect: (story: Story) => void;
  onFocusStory: (story: Story) => void;
  onStoryStatusChange: (storyId: string, status: Story['status']) => void;
  storyIdFilter: string;
  onStoryIdFilterChange: (value: string) => void;
  kpis: StoryCounters;
  /** Injectable BFF client so the drop->reject->revert flow is testable (E7/AC10a). */
  client?: BffClient;
  /** When true (archived project), mutating controls are disabled (E5/AC10h). */
  readOnly?: boolean;
}) {
  const [draggedStoryId, setDraggedStoryId] = useState<string | null>(null);
  const [dropTarget, setDropTarget] = useState<Story['status'] | null>(null);
  const [sortMode, setSortMode] = useState<KanbanSortMode>('id');
  const [errorPill, setErrorPill] = useState<string | null>(null);

  const filteredStories = useMemo(() => {
    const storyIdNeedle = storyIdFilter.trim().toLowerCase();
    if (!storyIdNeedle) return boardStories;
    return boardStories.filter((story) => story.id.toLowerCase().includes(storyIdNeedle));
  }, [boardStories, storyIdFilter]);

  const sortedStories = useMemo(
    () => [...filteredStories].sort((left, right) => compareKanbanStories(sortMode, left, right)),
    [filteredStories, sortMode],
  );

  const storiesByStatus = useMemo(
    () =>
      STORY_STATUSES.reduce<Record<Story['status'], Story[]>>(
        (groups, status) => {
          groups[status] = sortedStories.filter((story) => story.status === status);
          return groups;
        },
        { Backlog: [], Approved: [], 'In Progress': [], Done: [], Cancelled: [] },
      ),
    [sortedStories],
  );

  useEffect(() => {
    if (!selectedStory) return;
    document.querySelector<HTMLElement>(`[data-kanban-story-id="${selectedStory.id}"]`)?.focus();
  }, [selectedStory]);

  const focusKanbanNeighbor = (key: string) => {
    if (!selectedStory) return;
    const currentColumnIndex = STORY_STATUSES.indexOf(selectedStory.status);
    const currentColumn = storiesByStatus[selectedStory.status];
    const currentRowIndex = Math.max(0, currentColumn.findIndex((story) => story.id === selectedStory.id));
    if (key === 'ArrowDown' || key === 'ArrowUp') {
      const offset = key === 'ArrowDown' ? 1 : -1;
      const next = currentColumn[Math.min(Math.max(currentRowIndex + offset, 0), currentColumn.length - 1)];
      if (next) onFocusStory(next);
      return;
    }

    const offset = key === 'ArrowRight' ? 1 : -1;
    const nextStatus =
      STORY_STATUSES[Math.min(Math.max(currentColumnIndex + offset, 0), STORY_STATUSES.length - 1)];
    const nextColumn = storiesByStatus[nextStatus];
    if (!nextColumn) return;
    const next = nextColumn[Math.min(currentRowIndex, nextColumn.length - 1)];
    if (next) onFocusStory(next);
  };

  const onDragStart = (event: React.DragEvent<HTMLButtonElement>, story: Story) => {
    setDraggedStoryId(story.id);
    event.dataTransfer.effectAllowed = 'move';
    event.dataTransfer.setData('text/plain', story.id);
    const dragImage = event.currentTarget.cloneNode(true) as HTMLElement;
    dragImage.classList.add('kanban-drag-preview');
    document.body.appendChild(dragImage);
    event.dataTransfer.setDragImage(dragImage, 24, 24);
    window.setTimeout(() => dragImage.remove(), 0);
  };

  function showError(msg: string) {
    setErrorPill(msg);
    window.setTimeout(() => setErrorPill(null), 4000);
  }

  const onDrop = (event: React.DragEvent<HTMLElement>, targetStatus: Story['status']) => {
    event.preventDefault();
    const storyId = event.dataTransfer.getData('text/plain') || draggedStoryId;
    setDraggedStoryId(null);
    setDropTarget(null);
    if (readOnly) {
      showError('Archiviertes Projekt — Statusänderungen sind deaktiviert.');
      return;
    }
    if (!storyId) return;

    const story = boardStories.find((s) => s.id === storyId);
    if (!story) return;

    const previousStatus = story.status;
    if (previousStatus === targetStatus) return;

    // AC5/AC10b: validate BEFORE optimistic update via the SHARED transition matrix.
    const transition = resolveTransitionEndpoint(previousStatus, targetStatus);
    if (transition === null) {
      // Snap back immediately — no local state change
      showError(`Übergang ${previousStatus} → ${targetStatus} nicht erlaubt.`);
      return;
    }

    // Allowed: optimistic update first
    onStoryStatusChange(storyId, targetStatus);

    // Dispatch to dedicated project-scoped endpoint (AC8) — never PATCH status.
    const opId = `kanban-${Date.now()}`;
    let endpoint: Promise<void>;
    if (transition === 'approve') {
      endpoint = client.approveStory(projectKey, storyId, opId);
    } else if (transition === 'cancel') {
      endpoint = client.cancelStory(projectKey, storyId, undefined, opId);
    } else {
      endpoint = client.rejectStory(projectKey, storyId, opId);
    }

    endpoint.catch((err: unknown) => {
      const message = err instanceof Error ? err.message : String(err);
      // AC10a/10b: Revert optimistic update on backend rejection
      onStoryStatusChange(storyId, previousStatus);
      const errorCode = message.match(/failed: (\d+)/)?.[1] ?? 'error';
      showError(
        message.includes('invalid_transition')
          ? `Ungültige Statusänderung (invalid_transition).`
          : `Fehler: ${errorCode}`,
      );
    });
  };

  return (
    <div className="kanban">
      {errorPill && (
        <div className="error-pill" role="alert">
          {errorPill}
        </div>
      )}
      <KpiBar tiles={buildStoryKpiTiles(kpis)} />
      <div className="kanban-toolbar ak-panel" data-story-interactive="true">
        <label className="kanban-filter">
          <span>Story ID</span>
          <input
            value={storyIdFilter}
            onChange={(event) => onStoryIdFilterChange(event.target.value)}
            placeholder="z. B. BB2-247"
          />
        </label>
        <label className="kanban-sort">
          <span>Sort</span>
          <select
            value={sortMode}
            onChange={(event) => setSortMode(event.target.value as KanbanSortMode)}
          >
            {Object.entries(kanbanSortLabels).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
      </div>
      {STORY_STATUSES.map((column) => {
        const items = storiesByStatus[column];
        return (
          <section
            className={`kanban-column ak-panel ${dropTarget === column ? 'is-drop-target' : ''}`}
            data-story-interactive="true"
            key={column}
            onDragOver={(event) => {
              event.preventDefault();
              event.dataTransfer.dropEffect = 'move';
              setDropTarget(column);
            }}
            onDragLeave={(event) => {
              if (!event.currentTarget.contains(event.relatedTarget as globalThis.Node | null)) {
                setDropTarget(null);
              }
            }}
            onDrop={(event) => onDrop(event, column)}
          >
            <header>
              <h2>{column}</h2>
              <span>{items.length}</span>
            </header>
            {items.length === 0 && (
              <p className="kanban-empty">Keine Stories</p>
            )}
            {items.map((story) => {
              const isDraggable = !readOnly && !NON_DRAGGABLE_STATUSES.includes(story.status);
              return (
                <button
                  className={[
                    'kanban-card',
                    selectedStory?.id === story.id ? 'selected' : '',
                    draggedStoryId === story.id ? 'is-dragging' : '',
                    !isDraggable ? 'is-non-draggable' : '',
                  ]
                    .filter(Boolean)
                    .join(' ')}
                  data-story-interactive="true"
                  data-kanban-story-id={story.id}
                  draggable={isDraggable}
                  key={story.id}
                  type="button"
                  onDragEnd={() => {
                    setDraggedStoryId(null);
                    setDropTarget(null);
                  }}
                  onDragStart={(event) => {
                    if (isDraggable) onDragStart(event, story);
                  }}
                  onClick={() => onFocusStory(story)}
                  onDoubleClick={() => onSelect(story)}
                  onKeyDown={(event) => {
                    if (
                      ['ArrowDown', 'ArrowUp', 'ArrowRight', 'ArrowLeft'].includes(event.key)
                    ) {
                      event.preventDefault();
                      focusKanbanNeighbor(event.key);
                    }
                    if (event.key === 'Enter' || event.key === ' ') {
                      event.preventDefault();
                      onSelect(story);
                    }
                  }}
                >
                  <span className="node-id">
                    {story.id}
                    <FastBadge mode={story.mode} />
                  </span>
                  <strong>{story.title}</strong>
                  <small>
                    {story.module} · Wave {story.wave}
                  </small>
                  <div className="tag-row">
                    <Badge tone={statusClass[story.status]}>{story.type}</Badge>
                    <Badge tone="neutral">{story.size}</Badge>
                  </div>
                </button>
              );
            })}
          </section>
        );
      })}
    </div>
  );
}
