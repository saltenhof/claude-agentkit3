// Shared status-transition matrix for Kanban drag&drop AND Sheet inline-edit.
//
// Status mutations are contract-compliant (FK-72 §72.14.4): only the dedicated
// approve/reject/cancel endpoints are dispatched — never a PATCH with `status`.
// Kanban allows only Backlog<->Approved and Backlog/Approved->Cancelled; terminal
// and running stories are not draggable.
//
// Both views MUST validate a transition through this matrix BEFORE writing any
// optimistic/local draft, so an unsupported transition never produces a
// local-only invalid state (E6/AC8/AC10b/AC10c).

import type { Story } from '../../store';

/** Statuses that are terminal/running and cannot be transitioned by the UI. */
export const NON_DRAGGABLE_STATUSES: Story['status'][] = ['In Progress', 'Done', 'Cancelled'];

/** Allowed transition matrix. Key = from, value = set of allowed `to`. */
export const ALLOWED_TRANSITIONS: Partial<Record<Story['status'], Set<Story['status']>>> = {
  Backlog: new Set<Story['status']>(['Approved', 'Cancelled']),
  Approved: new Set<Story['status']>(['Backlog', 'Cancelled']),
};

/** The dedicated endpoint a (from -> to) transition dispatches to. */
export type TransitionEndpoint = 'approve' | 'reject' | 'cancel';

export function isAllowedTransition(from: Story['status'], to: Story['status']): boolean {
  if (from === to) return false;
  return ALLOWED_TRANSITIONS[from]?.has(to) ?? false;
}

/**
 * Resolve the dedicated endpoint for an allowed transition, or `null` when the
 * transition is not allowed. Callers MUST treat `null` as a hard rejection
 * (no draft, snap-back, error pill) — never as a silent no-op.
 */
export function resolveTransitionEndpoint(
  from: Story['status'],
  to: Story['status'],
): TransitionEndpoint | null {
  if (!isAllowedTransition(from, to)) return null;
  if (to === 'Approved' && from === 'Backlog') return 'approve';
  if (to === 'Cancelled') return 'cancel';
  if (to === 'Backlog' && from === 'Approved') return 'reject';
  return null;
}
