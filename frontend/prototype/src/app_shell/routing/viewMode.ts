export type ViewMode = 'graph' | 'kanban' | 'sheet' | 'analytics' | 'hub';

export const VIEW_MODES: ViewMode[] = ['graph', 'kanban', 'sheet', 'analytics', 'hub'];

export const INSPECTOR_WIDTH_KEY = 'ak3.storyInspector.width';
export const DEFAULT_INSPECTOR_WIDTH = 858;
export const MIN_INSPECTOR_WIDTH = 560;

export function viewFromLocationHash(): ViewMode {
  const hashView = window.location.hash.replace(/^#\/?/, '');
  return VIEW_MODES.includes(hashView as ViewMode) ? (hashView as ViewMode) : 'graph';
}
