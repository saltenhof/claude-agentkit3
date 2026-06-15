import { Edit3 } from 'lucide-react';
import type { Story } from '../../store';
import { Badge } from '../../design_system/Badge';
import { FastBadge } from '../../components/FastBadge';

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

const statusClass: Record<Story['status'], string> = {
  Backlog: 'status-backlog',
  Approved: 'status-approved',
  'In Progress': 'status-progress',
  Done: 'success',
  Cancelled: 'cancelled',
};

export function SheetCell({
  column,
  editing,
  story,
  value,
  onChange,
  onDone,
  validationError,
}: {
  column: { id: SheetField; editable?: boolean };
  editing: boolean;
  story: Story;
  value: string | number | string[];
  onChange: (value: string) => void;
  onDone: () => void;
  validationError?: boolean;
}) {
  const options: Partial<Record<SheetField, string[]>> = {
    status: ['Backlog', 'Approved', 'In Progress', 'Done', 'Cancelled'],
    type: ['implementation', 'bugfix', 'concept', 'research'],
    size: ['XS', 'S', 'M', 'L', 'XL', 'XXL'],
    changeImpact: ['Local', 'Component', 'Cross-Component', 'Architecture Impact'],
  };

  if (editing && column.editable) {
    if (options[column.id]) {
      return (
        <select
          autoFocus
          className={`sheet-editor${validationError ? ' is-validation-error' : ''}`}
          value={String(value)}
          onBlur={onDone}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' || event.key === 'Escape') onDone();
          }}
        >
          {options[column.id]?.map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </select>
      );
    }

    return (
      <input
        autoFocus
        className={`sheet-editor${validationError ? ' is-validation-error' : ''}`}
        type={
          column.id === 'qaRoundsExploration' || column.id === 'qaRoundsImplementation'
            ? 'number'
            : column.id === 'createdAt' || column.id === 'completedAt'
              ? 'date'
              : 'text'
        }
        value={Array.isArray(value) ? value.join(', ') : String(value)}
        onBlur={onDone}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === 'Enter' || event.key === 'Escape') onDone();
        }}
      />
    );
  }

  if (column.id === 'status')
    return <Badge tone={statusClass[String(value) as Story['status']]}>{String(value)}</Badge>;
  if (column.id === 'labels')
    return <span>{Array.isArray(value) ? value.join(', ') : String(value || '-')}</span>;
  if (column.id === 'participatingRepos')
    return <span>{Array.isArray(value) ? value.join(', ') : String(value || '-')}</span>;
  if (column.id === 'title') {
    return (
      <div className="sheet-title-cell">
        <span>{String(value)}</span>
        <Edit3 size={12} />
      </div>
    );
  }
  if (column.id === 'epic') {
    return <span className="epic-label">{String(value)}</span>;
  }
  if (column.id === 'id') {
    return (
      <span className="cell-id">
        {story.id}
        <FastBadge mode={story.mode} size={12} />
      </span>
    );
  }
  return <span>{value || '-'}</span>;
}
