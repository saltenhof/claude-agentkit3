import { Filter, ListFilter } from 'lucide-react';
import type { ReactElement } from 'react';

import type { StoryStatus } from '../types';
import {
  KANBAN_SORT_LABELS,
  STORY_STATUS_COLUMNS,
  type KanbanSortMode,
  type StoryStatusFilter,
} from './storyFilters';

interface KanbanToolbarProps {
  storyIdFilter: string;
  statusFilter: StoryStatusFilter;
  sortMode: KanbanSortMode;
  visibleCount: number;
  totalCount: number;
  onStoryIdFilterChange: (value: string) => void;
  onStatusFilterChange: (value: StoryStatusFilter) => void;
  onSortModeChange: (value: KanbanSortMode) => void;
}

export function KanbanToolbar({
  storyIdFilter,
  statusFilter,
  sortMode,
  visibleCount,
  totalCount,
  onStoryIdFilterChange,
  onStatusFilterChange,
  onSortModeChange,
}: Readonly<KanbanToolbarProps>): ReactElement {
  return (
    <div className="kanban-toolbar">
      <div className="kanban-result-count" aria-live="polite">
        <strong>{visibleCount}</strong>
        <span>/ {totalCount}</span>
      </div>
      <label className="kanban-filter">
        <Filter size={16} aria-hidden="true" />
        <span>Story ID</span>
        <input
          value={storyIdFilter}
          onChange={(event) => onStoryIdFilterChange(event.target.value)}
          placeholder="z. B. BB2-247"
        />
      </label>
      <label className="kanban-filter">
        <span>Status</span>
        <select
          value={statusFilter}
          onChange={(event) => onStatusFilterChange(event.target.value as StoryStatusFilter)}
        >
          <option value="all">Alle</option>
          {STORY_STATUS_COLUMNS.map((status: StoryStatus) => (
            <option key={status} value={status}>
              {status}
            </option>
          ))}
        </select>
      </label>
      <label className="kanban-sort">
        <ListFilter size={16} aria-hidden="true" />
        <span>Sort</span>
        <select value={sortMode} onChange={(event) => onSortModeChange(event.target.value as KanbanSortMode)}>
          {Object.entries(KANBAN_SORT_LABELS).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}
