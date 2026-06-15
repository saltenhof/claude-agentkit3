import { Fragment, useCallback, useEffect, useMemo, useState } from 'react';
import type { CSSProperties } from 'react';
import {
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  ChevronDown,
  ChevronRight,
  Copy,
  Download,
  Filter,
  Group,
  MoreHorizontal,
  Plus,
  Table2,
} from 'lucide-react';
import { buildStoryKpiTiles } from '../../store';
import type { Story, StoryCounters } from '../../store';
import { KpiBar } from '../../components/KpiBar';
import { SheetCell } from './SheetCell';
import { BffClient } from '../../foundation/bff/client';
import { resolveTransitionEndpoint } from '../board/statusTransitions';

const SHEET_COLUMN_WIDTHS_KEY = 'ak3.storySheet.columnWidths';

type SheetField = keyof Pick<
  Story,
  | 'id'
  | 'title'
  | 'epic'
  | 'module'
  | 'status'
  | 'labels'
  | 'type'
  | 'primaryRepo'
  | 'participatingRepos'
  | 'size'
  | 'createdAt'
  | 'completedAt'
  | 'processingTime'
  | 'qaRoundsExploration'
  | 'qaRoundsImplementation'
  | 'changeImpact'
>;

type Column = {
  id: SheetField;
  label: string;
  group: 'identity' | 'classification' | 'planning' | 'metrics';
  frozen?: boolean;
  editable?: boolean;
  width?: string;
};

const columns: Column[] = [
  { id: 'id', label: 'Story ID', group: 'identity', frozen: true, width: '6.5625rem' },
  { id: 'title', label: 'Title', group: 'identity', frozen: true, editable: true, width: '20.625rem' },
  { id: 'epic', label: 'Epic', group: 'planning', editable: true, width: '13.125rem' },
  { id: 'module', label: 'Module', group: 'planning', editable: true, width: '11.25rem' },
  { id: 'status', label: 'Status', group: 'classification', editable: true, width: '8.125rem' },
  { id: 'labels', label: 'Labels', group: 'classification', width: '16rem' },
  { id: 'type', label: 'Story Type', group: 'classification', editable: true, width: '8.75rem' },
  { id: 'primaryRepo', label: 'Primary Repo', group: 'planning', editable: true, width: '12rem' },
  { id: 'participatingRepos', label: 'Participating Repos', group: 'planning', width: '16rem' },
  { id: 'size', label: 'Size', group: 'classification', editable: true, width: '4.5rem' },
  { id: 'createdAt', label: 'Created At', group: 'metrics', editable: true, width: '7.5rem' },
  { id: 'completedAt', label: 'Completed At', group: 'metrics', editable: true, width: '8rem' },
  { id: 'processingTime', label: 'Processing Time', group: 'metrics', width: '9rem' },
  { id: 'qaRoundsExploration', label: 'QA Rounds Exploration', group: 'metrics', width: '10.5rem' },
  { id: 'qaRoundsImplementation', label: 'QA Rounds Implementation', group: 'metrics', width: '11.5rem' },
  { id: 'changeImpact', label: 'Change Impact', group: 'classification', editable: true, width: '10.625rem' },
];

const groupLabels: Record<Column['group'], string> = {
  identity: 'Identity',
  classification: 'Classification',
  planning: 'Planning',
  metrics: 'Metrics',
};

const defaultBffClient = new BffClient('');

export function StorySheet({
  projectKey,
  stories: sheetStories,
  selectedStory,
  statusFilter,
  onSelect,
  onStatusFilterChange,
  kpis,
  client = defaultBffClient,
  readOnly = false,
  onDraftsChange,
}: {
  projectKey: string;
  stories: Story[];
  selectedStory: Story | null;
  statusFilter: 'all' | Story['status'];
  onSelect: (story: Story) => void;
  onStatusFilterChange: (status: 'all' | Story['status']) => void;
  kpis: StoryCounters;
  /** Injectable BFF client so the inline-edit dispatch flow is testable (E7). */
  client?: BffClient;
  /** When true (archived project), inline status mutation is disabled (E5/AC10h). */
  readOnly?: boolean;
  /** Reports whether unsaved local drafts exist, so the Shell can warn on project switch (E5/AC10h). */
  onDraftsChange?: (hasDrafts: boolean) => void;
}) {
  const [visibleGroups, setVisibleGroups] = useState<Set<Column['group']>>(
    () => new Set(['identity', 'classification', 'planning', 'metrics']),
  );
  const [groupByEpic, setGroupByEpic] = useState(true);
  const [sortField, setSortField] = useState<SheetField>('epic');
  const [sortAsc, setSortAsc] = useState(true);
  const [editingCell, setEditingCell] = useState<{ storyId: string; field: SheetField } | null>(null);
  const [drafts, setDrafts] = useState<Record<string, Partial<Record<SheetField, string | number>>>>({});
  const [validationErrors, setValidationErrors] = useState<Record<string, SheetField[]>>({});
  const [copiedEpic, setCopiedEpic] = useState<string | null>(null);
  const [errorPill, setErrorPill] = useState<string | null>(null);
  const [columnWidths, setColumnWidths] = useState<Record<string, string>>(() => {
    const defaults = Object.fromEntries(columns.map((column) => [column.id, column.width ?? '8rem']));
    try {
      const stored = JSON.parse(
        window.localStorage.getItem(SHEET_COLUMN_WIDTHS_KEY) ?? '{}',
      ) as Record<string, string>;
      return { ...defaults, ...stored };
    } catch {
      return defaults;
    }
  });

  useEffect(() => {
    window.localStorage.setItem(SHEET_COLUMN_WIDTHS_KEY, JSON.stringify(columnWidths));
  }, [columnWidths]);

  // Report draft presence to the Shell (E5/AC10h: project-switch draft-loss warning).
  useEffect(() => {
    onDraftsChange?.(Object.keys(drafts).length > 0);
  }, [drafts, onDraftsChange]);

  const visibleColumns = columns
    .map((column) => ({ ...column, width: columnWidths[column.id] ?? column.width }))
    .filter((column) => visibleGroups.has(column.group));
  const frozenColumns = visibleColumns.filter((column) => column.frozen);
  const scrollColumns = visibleColumns.filter((column) => !column.frozen);
  const idColumnWidth = columnWidths.id ?? columns.find((column) => column.id === 'id')?.width ?? '6.5625rem';

  const getColumnStyle = (column: Column): CSSProperties => {
    const style: CSSProperties = {
      minWidth: column.width,
      width: column.width,
    };
    if (column.frozen) {
      style.left = column.id === 'title' ? idColumnWidth : '0';
    }
    return style;
  };

  const startColumnResize = (event: React.PointerEvent, column: Column) => {
    event.preventDefault();
    event.stopPropagation();
    const rootFontSize = Number.parseFloat(getComputedStyle(document.documentElement).fontSize) || 16;
    const startX = event.clientX;
    const initialRem = Number.parseFloat(column.width ?? columnWidths[column.id] ?? '8');
    const minRem = column.id === 'title' ? 12 : 4;

    const onPointerMove = (moveEvent: PointerEvent) => {
      const next = Math.max(minRem, initialRem + (moveEvent.clientX - startX) / rootFontSize);
      setColumnWidths((current) => ({
        ...current,
        [column.id]: `${next.toFixed(3)}rem`,
      }));
    };

    const onPointerUp = () => {
      window.removeEventListener('pointermove', onPointerMove);
      window.removeEventListener('pointerup', onPointerUp);
    };

    window.addEventListener('pointermove', onPointerMove);
    window.addEventListener('pointerup', onPointerUp);
  };

  const getCellValue = useCallback(
    (story: Story, field: SheetField): string | number | string[] => {
      const draft = drafts[story.id]?.[field];
      if (draft !== undefined) return draft;
      const value = story[field];
      return value === undefined ? '' : value;
    },
    [drafts],
  );

  const sortedStories = useMemo(() => {
    return [...sheetStories].sort((a, b) => {
      const av = getCellValue(a, sortField);
      const bv = getCellValue(b, sortField);
      const result = String(av).localeCompare(String(bv), 'de', { numeric: true });
      return sortAsc ? result : -result;
    });
  }, [getCellValue, sheetStories, sortAsc, sortField]);

  const groupedStories = useMemo(() => {
    if (!groupByEpic) return [['Alle Stories', sortedStories] as const];
    const map = new Map<string, Story[]>();
    for (const story of sortedStories) {
      const epic = String(getCellValue(story, 'epic') || 'Ohne Epic');
      map.set(epic, [...(map.get(epic) ?? []), story]);
    }
    return Array.from(map.entries());
  }, [getCellValue, groupByEpic, sortedStories]);

  const setSort = (field: SheetField) => {
    if (sortField === field) {
      setSortAsc((current) => !current);
      return;
    }
    setSortField(field);
    setSortAsc(true);
  };

  const toggleGroup = (group: Column['group']) => {
    setVisibleGroups((current) => {
      const next = new Set(current);
      if (next.has(group) && next.size > 1) next.delete(group);
      else next.add(group);
      return next;
    });
  };

  const showSheetError = (msg: string) => {
    setErrorPill(msg);
    window.setTimeout(() => setErrorPill(null), 4000);
  };

  const markFieldInvalid = (storyId: string, field: SheetField) => {
    setValidationErrors((current) => ({
      ...current,
      [storyId]: [...(current[storyId] ?? []), field],
    }));
  };

  const dropDraftField = (storyId: string, field: SheetField) => {
    setDrafts((current) => {
      const next = { ...current };
      if (next[storyId]) {
        const storyDraft = { ...next[storyId] };
        delete storyDraft[field];
        if (Object.keys(storyDraft).length === 0) delete next[storyId];
        else next[storyId] = storyDraft;
      }
      return next;
    });
  };

  const writeDraft = (storyId: string, field: SheetField, value: string | number) => {
    setDrafts((current) => ({
      ...current,
      [storyId]: { ...current[storyId], [field]: value },
    }));
  };

  const updateDraft = (storyId: string, field: SheetField, value: string) => {
    // E6/AC8: the status field is special — VALIDATE the transition against the
    // SHARED matrix BEFORE writing any local draft. An unsupported transition is a
    // hard rejection (failure pill, no draft), never a local-only invalid state.
    if (field === 'status') {
      if (readOnly) {
        showSheetError('Archiviertes Projekt — Statusänderungen sind deaktiviert.');
        return;
      }
      const story = sheetStories.find((s) => s.id === storyId);
      if (!story) return;
      const newStatus = value as Story['status'];
      const transition = resolveTransitionEndpoint(story.status, newStatus);
      if (transition === null) {
        showSheetError(`Übergang ${story.status} → ${newStatus} nicht erlaubt.`);
        return;
      }
      // Allowed: write the draft, then dispatch to the dedicated endpoint.
      writeDraft(storyId, field, value);
      const opId = `sheet-${Date.now()}`;
      const endpoint =
        transition === 'approve'
          ? client.approveStory(projectKey, storyId, opId)
          : transition === 'cancel'
            ? client.cancelStory(projectKey, storyId, undefined, opId)
            : client.rejectStory(projectKey, storyId, opId);
      endpoint.catch((err: unknown) => {
        const message = err instanceof Error ? err.message : String(err);
        if (message.includes('validation_failed')) {
          // AC10c: keep draft + mark field red until corrected/discarded.
          markFieldInvalid(storyId, field);
        } else {
          // AC10a: revert draft + show error pill with the error code.
          dropDraftField(storyId, field);
          showSheetError(`Fehler: ${message}`);
        }
      });
      return;
    }

    // Non-status fields: plain local draft (no backend mutation in this story).
    const normalized =
      field === 'qaRoundsExploration' || field === 'qaRoundsImplementation' ? Number(value) : value;
    writeDraft(storyId, field, normalized);
  };

  const copyEpic = (epic: string, rows: Story[]) => {
    const text = rows.map((story) => story.id).join(', ');
    void navigator.clipboard?.writeText(text);
    setCopiedEpic(epic);
    window.setTimeout(() => setCopiedEpic(null), 1800);
  };

  return (
    <div className="sheet-wrap">
      {errorPill && (
        <div className="error-pill" role="alert">
          {errorPill}
        </div>
      )}
      <KpiBar tiles={buildStoryKpiTiles(kpis)} />
      <div className="sheet-toolbar ak-panel">
        <div className="sheet-toolbar__row">
          <div className="sheet-title">
            <Table2 size={17} />
            <strong>Story Spreadsheet</strong>
            <span>{sheetStories.length} rows</span>
          </div>
          <div className="sheet-actions">
            <button
              className="ak-button ak-button--compact"
              type="button"
              onClick={() => setGroupByEpic((value) => !value)}
            >
              <Group size={15} />
              {groupByEpic ? 'Epic Groups' : 'Flat'}
            </button>
            <button className="ak-button ak-button--compact" type="button">
              <Filter size={15} />
              Filter
            </button>
            <button className="ak-button ak-button--compact" type="button">
              <Download size={15} />
              Export
            </button>
          </div>
        </div>
        <div className="sheet-toolbar__row sheet-toolbar__row--wrap">
          {Object.entries(groupLabels).map(([group, label]) => (
            <button
              className={`column-chip ${visibleGroups.has(group as Column['group']) ? 'active' : ''}`}
              key={group}
              type="button"
              onClick={() => toggleGroup(group as Column['group'])}
            >
              {visibleGroups.has(group as Column['group']) ? (
                <ChevronDown size={13} />
              ) : (
                <ChevronRight size={13} />
              )}
              {label}
              <span>{columns.filter((column) => column.group === group).length}</span>
            </button>
          ))}
          <label className="sheet-status-filter">
            <Filter size={13} />
            <select
              value={statusFilter}
              onChange={(event) =>
                onStatusFilterChange(event.target.value as 'all' | Story['status'])
              }
            >
              <option value="all">Alle Status</option>
              <option value="Backlog">Backlog</option>
              <option value="Approved">Approved</option>
              <option value="In Progress">In Progress</option>
              <option value="Done">Done</option>
              <option value="Cancelled">Cancelled</option>
            </select>
          </label>
        </div>
      </div>

      <div className="sheet-grid-shell">
        <table className="story-sheet">
          <thead>
            <tr className="sheet-group-head">
              {visibleColumns.map((column) => (
                <th className={column.frozen ? 'is-frozen' : ''} key={column.id} style={getColumnStyle(column)}>
                  {groupLabels[column.group]}
                </th>
              ))}
            </tr>
            <tr>
              {visibleColumns.map((column) => (
                <th
                  className={column.frozen ? 'is-frozen is-resizable' : 'is-resizable'}
                  key={column.id}
                  style={getColumnStyle(column)}
                >
                  <button className="sort-header" type="button" onClick={() => setSort(column.id)}>
                    {column.label}
                    {sortField === column.id ? (
                      sortAsc ? (
                        <ArrowUp size={13} />
                      ) : (
                        <ArrowDown size={13} />
                      )
                    ) : (
                      <ArrowUpDown size={13} />
                    )}
                  </button>
                  <span
                    aria-label={`${column.label} Spaltenbreite anpassen`}
                    className="sheet-column-resize"
                    role="separator"
                    onPointerDown={(event) => startColumnResize(event, column)}
                  />
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {groupedStories.map(([epic, rows]) => (
              <Fragment key={epic}>
                {groupByEpic && (
                  <tr className="epic-row">
                    <td colSpan={visibleColumns.length}>
                      <div className="sheet-group-title">
                        <ChevronDown size={14} />
                        <strong>{epic}</strong>
                        <span>{rows.length}</span>
                        <button
                          aria-label={`${epic} menu`}
                          className="sheet-group-menu"
                          type="button"
                        >
                          <MoreHorizontal size={15} />
                        </button>
                        <button
                          className="sheet-group-copy"
                          type="button"
                          onClick={() => copyEpic(epic, rows)}
                        >
                          <Copy size={13} />
                          {copiedEpic === epic ? 'Copied' : 'Copy IDs'}
                        </button>
                      </div>
                    </td>
                  </tr>
                )}
                {rows.map((story) => (
                  <tr
                    className={[
                      selectedStory?.id === story.id ? 'selected' : '',
                      drafts[story.id] ? 'is-dirty' : '',
                    ]
                      .filter(Boolean)
                      .join(' ')}
                    key={story.id}
                    data-story-interactive="true"
                    onClick={() => onSelect(story)}
                  >
                    {[...frozenColumns, ...scrollColumns].map((column) => (
                      <td
                        className={[
                          column.id === 'id' ? 'cell-id' : '',
                          column.id === 'title' ? 'cell-title' : '',
                          column.frozen ? 'is-frozen' : '',
                          editingCell?.storyId === story.id && editingCell.field === column.id
                            ? 'is-editing'
                            : '',
                          validationErrors[story.id]?.includes(column.id)
                            ? 'has-validation-error'
                            : '',
                        ]
                          .filter(Boolean)
                          .join(' ')}
                        data-validation-error={
                          validationErrors[story.id]?.includes(column.id) ? 'true' : undefined
                        }
                        key={column.id}
                        style={getColumnStyle(column)}
                        onDoubleClick={(event) => {
                          event.stopPropagation();
                          if (column.editable) setEditingCell({ storyId: story.id, field: column.id });
                        }}
                      >
                        <SheetCell
                          column={column}
                          editing={editingCell?.storyId === story.id && editingCell.field === column.id}
                          story={story}
                          value={getCellValue(story, column.id)}
                          onChange={(value) => updateDraft(story.id, column.id, value)}
                          onDone={() => setEditingCell(null)}
                          validationError={validationErrors[story.id]?.includes(column.id)}
                        />
                      </td>
                    ))}
                  </tr>
                ))}
                {groupByEpic && (
                  <tr className="sheet-add-row">
                    <td colSpan={visibleColumns.length}>
                      <button type="button">
                        <Plus size={14} />
                        Add item
                      </button>
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>

      <div className="sheet-statusbar">
        <span>{sortedStories.length} visible rows</span>
        <span>{visibleColumns.length} columns</span>
        <span>{Object.keys(drafts).length} edited rows</span>
      </div>
    </div>
  );
}
