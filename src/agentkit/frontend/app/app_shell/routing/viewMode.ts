export type ViewMode = 'graph' | 'kanban' | 'sheet' | 'analytics' | 'hub' | 'concepts';

const VALID_VIEW_MODES = new Set<ViewMode>([
  'graph',
  'kanban',
  'sheet',
  'analytics',
  'hub',
  'concepts',
]);

export function viewModeFromHash(hash: string): ViewMode {
  const value = hash.replace(/^#\/?/, '');
  return VALID_VIEW_MODES.has(value as ViewMode) ? (value as ViewMode) : 'graph';
}

export function setViewModeHash(mode: ViewMode): void {
  globalThis.location.hash = mode;
}
