import { ChevronDown, ChevronRight, Copy, Filter, Group, Table2 } from 'lucide-react';
import { useMemo, useState } from 'react';
import type { ReactElement } from 'react';

import type { StoryStatus, StorySummary } from '../types';
import { STORY_STATUS_COLUMNS, type StoryStatusFilter } from './storyFilters';

interface StorySheetProps {
  stories: readonly StorySummary[];
  selectedStoryId: string | null;
  statusFilter: StoryStatusFilter;
  onSelectStory: (storyId: string) => void;
  onStatusFilterChange: (value: StoryStatusFilter) => void;
}

type SheetGroup = 'identity' | 'classification' | 'planning' | 'metrics';
type SheetField =
  | 'story_id'
  | 'title'
  | 'epic'
  | 'module'
  | 'status'
  | 'type'
  | 'repos'
  | 'size'
  | 'wave'
  | 'risk'
  | 'owner'
  | 'qa_rounds'
  | 'change_impact';

interface SheetColumn {
  id: SheetField;
  label: string;
  group: SheetGroup;
  frozen?: boolean;
  width: string;
}

const SHEET_COLUMNS: readonly SheetColumn[] = [
  { id: 'story_id', label: 'Story ID', group: 'identity', frozen: true, width: '112px' },
  { id: 'title', label: 'Title', group: 'identity', frozen: true, width: '310px' },
  { id: 'epic', label: 'Epic', group: 'planning', width: '190px' },
  { id: 'module', label: 'Module', group: 'planning', width: '170px' },
  { id: 'status', label: 'Status', group: 'classification', width: '132px' },
  { id: 'type', label: 'Story Type', group: 'classification', width: '136px' },
  { id: 'repos', label: 'Repos', group: 'planning', width: '220px' },
  { id: 'size', label: 'Size', group: 'classification', width: '78px' },
  { id: 'wave', label: 'Wave', group: 'planning', width: '82px' },
  { id: 'risk', label: 'Risk', group: 'classification', width: '94px' },
  { id: 'owner', label: 'Owner', group: 'planning', width: '140px' },
  { id: 'qa_rounds', label: 'QA Rounds', group: 'metrics', width: '120px' },
  { id: 'change_impact', label: 'Change Impact', group: 'metrics', width: '170px' },
];

const GROUP_LABELS: Record<SheetGroup, string> = {
  identity: 'Identity',
  classification: 'Classification',
  planning: 'Planning',
  metrics: 'Metrics',
};

export function StorySheet({
  stories,
  selectedStoryId,
  statusFilter,
  onSelectStory,
  onStatusFilterChange,
}: Readonly<StorySheetProps>): ReactElement {
  const [visibleGroups, setVisibleGroups] = useState<ReadonlySet<SheetGroup>>(
    () => new Set(['identity', 'classification', 'planning', 'metrics']),
  );
  const [groupByEpic, setGroupByEpic] = useState(true);
  const [sortField, setSortField] = useState<SheetField>('epic');
  const [sortAsc, setSortAsc] = useState(true);
  const [copiedEpic, setCopiedEpic] = useState<string | null>(null);

  const visibleColumns = SHEET_COLUMNS.filter((column) => visibleGroups.has(column.group));
  const filteredStories = useMemo(
    () => stories.filter((story) => statusFilter === 'all' || story.status === statusFilter),
    [statusFilter, stories],
  );
  const sortedStories = useMemo(
    () =>
      [...filteredStories].sort((left, right) => {
        const result = String(getCellValue(left, sortField)).localeCompare(String(getCellValue(right, sortField)), 'de', {
          numeric: true,
          sensitivity: 'base',
        });
        return sortAsc ? result : -result;
      }),
    [filteredStories, sortAsc, sortField],
  );
  const groupedStories = useMemo(() => {
    if (!groupByEpic) {
      return [['Alle Stories', sortedStories] as const];
    }
    const groups = new Map<string, StorySummary[]>();
    for (const story of sortedStories) {
      const epic = story.epic || 'Ohne Epic';
      groups.set(epic, [...(groups.get(epic) ?? []), story]);
    }
    return Array.from(groups.entries());
  }, [groupByEpic, sortedStories]);

  const toggleGroup = (group: SheetGroup): void => {
    setVisibleGroups((current) => {
      const next = new Set(current);
      if (next.has(group) && next.size > 1) {
        next.delete(group);
      } else {
        next.add(group);
      }
      return next;
    });
  };

  const setSort = (field: SheetField): void => {
    if (sortField === field) {
      setSortAsc((value) => !value);
      return;
    }
    setSortField(field);
    setSortAsc(true);
  };

  const copyEpic = (epic: string, rows: readonly StorySummary[]): void => {
    globalThis.navigator.clipboard?.writeText(rows.map((story) => story.story_id).join('\n')).catch(() => undefined);
    setCopiedEpic(epic);
    globalThis.setTimeout(() => setCopiedEpic(null), 1200);
  };

  return (
    <div className="sheet-wrap">
      <div className="sheet-toolbar">
        <div className="sheet-toolbar__row">
          <div className="sheet-title">
            <Table2 size={17} aria-hidden="true" />
            <strong>Story Spreadsheet</strong>
            <span>{filteredStories.length} rows</span>
          </div>
          <div className="sheet-actions">
            <button className="sheet-action" type="button" onClick={() => setGroupByEpic((value) => !value)}>
              <Group size={15} aria-hidden="true" />
              {groupByEpic ? 'Epic Groups' : 'Flat'}
            </button>
          </div>
        </div>
        <div className="sheet-toolbar__row sheet-toolbar__row--wrap">
          {(Object.entries(GROUP_LABELS) as Array<[SheetGroup, string]>).map(([group, label]) => (
            <button
              className="column-chip"
              data-active={visibleGroups.has(group)}
              key={group}
              type="button"
              onClick={() => toggleGroup(group)}
            >
              {visibleGroups.has(group) ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
              {label}
              <span>{SHEET_COLUMNS.filter((column) => column.group === group).length}</span>
            </button>
          ))}
          <label className="sheet-status-filter">
            <Filter size={13} aria-hidden="true" />
            <select value={statusFilter} onChange={(event) => onStatusFilterChange(event.target.value as StoryStatusFilter)}>
              <option value="all">Alle Status</option>
              {STORY_STATUS_COLUMNS.map((status: StoryStatus) => (
                <option key={status} value={status}>
                  {status}
                </option>
              ))}
            </select>
          </label>
        </div>
      </div>

      <div className="sheet-grid-shell">
        <table className="story-sheet">
          <thead>
            <tr className="sheet-group-head">
              {visibleColumns.map((column) => (
                <th className={column.frozen ? 'is-frozen' : ''} key={column.id} style={{ width: column.width }}>
                  {GROUP_LABELS[column.group]}
                </th>
              ))}
            </tr>
            <tr>
              {visibleColumns.map((column) => (
                <th className={column.frozen ? 'is-frozen' : ''} key={column.id} style={{ width: column.width }}>
                  <button className="sheet-sort" type="button" onClick={() => setSort(column.id)}>
                    {column.label}
                    {sortField === column.id && <span>{sortAsc ? 'asc' : 'desc'}</span>}
                  </button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {groupedStories.map(([epic, rows]) => (
              <FragmentGroup
                key={epic}
                copied={copiedEpic === epic}
                epic={epic}
                groupByEpic={groupByEpic}
                rows={rows}
                selectedStoryId={selectedStoryId}
                visibleColumns={visibleColumns}
                onCopyEpic={copyEpic}
                onSelectStory={onSelectStory}
              />
            ))}
          </tbody>
        </table>
      </div>

      <div className="sheet-statusbar">
        <span>{sortedStories.length} visible rows</span>
        <span>{visibleColumns.length} columns</span>
        <span>{groupByEpic ? `${groupedStories.length} groups` : 'flat list'}</span>
      </div>
    </div>
  );
}

function FragmentGroup({
  copied,
  epic,
  groupByEpic,
  rows,
  selectedStoryId,
  visibleColumns,
  onCopyEpic,
  onSelectStory,
}: Readonly<{
  copied: boolean;
  epic: string;
  groupByEpic: boolean;
  rows: readonly StorySummary[];
  selectedStoryId: string | null;
  visibleColumns: readonly SheetColumn[];
  onCopyEpic: (epic: string, rows: readonly StorySummary[]) => void;
  onSelectStory: (storyId: string) => void;
}>): ReactElement {
  return (
    <>
      {groupByEpic && (
        <tr className="epic-row">
          <td colSpan={visibleColumns.length}>
            <div className="sheet-group-title">
              <ChevronDown size={14} aria-hidden="true" />
              <strong>{epic}</strong>
              <span>{rows.length}</span>
              <button className="sheet-group-copy" type="button" onClick={() => onCopyEpic(epic, rows)}>
                <Copy size={13} aria-hidden="true" />
                {copied ? 'Copied' : 'Copy IDs'}
              </button>
            </div>
          </td>
        </tr>
      )}
      {rows.map((story) => (
        <tr
          className={selectedStoryId === story.story_id ? 'selected' : ''}
          key={story.story_id}
          onDoubleClick={() => onSelectStory(story.story_id)}
        >
          {visibleColumns.map((column) => (
            <td className={column.frozen ? 'is-frozen' : ''} key={column.id} style={{ width: column.width }}>
              <SheetCell column={column} story={story} value={getCellValue(story, column.id)} onSelectStory={onSelectStory} />
            </td>
          ))}
        </tr>
      ))}
    </>
  );
}

function SheetCell({
  column,
  story,
  value,
  onSelectStory,
}: Readonly<{
  column: SheetColumn;
  story: StorySummary;
  value: string | number;
  onSelectStory: (storyId: string) => void;
}>): ReactElement {
  if (column.id === 'story_id') {
    return (
      <button className="table-story-button" type="button" onClick={() => onSelectStory(story.story_id)}>
        {story.story_id}
      </button>
    );
  }
  if (column.id === 'status' || column.id === 'type' || column.id === 'risk' || column.id === 'size') {
    return <span className="sheet-pill" data-kind={column.id}>{value}</span>;
  }
  if (column.id === 'title') {
    return <span className="sheet-title-cell">{value}</span>;
  }
  return <span>{value || '-'}</span>;
}

function getCellValue(story: StorySummary, field: SheetField): string | number {
  if (field === 'repos') {
    return story.repos.join(', ');
  }
  return story[field] ?? '';
}
