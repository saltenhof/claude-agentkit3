export type ViewMode = 'graph' | 'kanban' | 'sheet' | 'analytics' | 'hub' | 'concepts';

const VALID_VIEW_MODES: readonly ViewMode[] = [
  'graph',
  'kanban',
  'sheet',
  'analytics',
  'hub',
  'concepts',
];

export function viewModeFromHash(hash: string): ViewMode {
  const value = hash.replace(/^#\/?/, '');
  return VALID_VIEW_MODES.includes(value as ViewMode) ? (value as ViewMode) : 'graph';
}

export function setViewModeHash(mode: ViewMode): void {
  window.location.hash = mode;
}
