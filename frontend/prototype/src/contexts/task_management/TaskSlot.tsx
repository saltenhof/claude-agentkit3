/**
 * TaskSlot — task-management BC view slice (AG3-105 / FK-77).
 *
 * Renders the task list for a project. Supports the full FK-77 surface:
 *   - List tasks (BFF GET /v1/projects/{key}/tasks)
 *   - Create a task (POST /v1/.../tasks) — new task appears FROM SERVER RESPONSE, no local shadow
 *   - Resolve as done (POST /v1/.../resolve) — strictly separate from dismiss
 *   - Dismiss (POST /v1/.../dismiss) — strictly separate from resolve
 *   - Link a task to a story or another task (POST /v1/.../links)
 *     target_kind ∈ {task, story} ONLY — artifacts are never valid targets (FK-77 §77.3)
 *   - Unlink (POST /v1/.../links/delete)
 *   - Link badges per task (links attached to a task)
 *   - Optimistic updates with revert on failure (AC9)
 *   - Error pills include error_code (AC9)
 *   - Empty state with create CTA (AC9)
 *   - Injectable client prop for testing; defaults to new BffClient(baseUrl)
 *
 * ARCH-55: all identifiers, wire keys, comments English. German only for rendered UI labels.
 * No pipeline mechanics (no phases, gates, worktrees, flow-tab, mode-indicator).
 * Links target only task|story — no artifacts.
 * No new :root CSS tokens — uses existing --ak-status-progress / --ak-status-done /
 * --ak-status-cancelled from design-system.css.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { ReactElement } from 'react';
import {
  BffClient,
  BffReadError,
  type WireTask,
  type WireTaskLink,
  type CreateTaskPayload,
} from '../../foundation/bff/client';

// ── Status color helpers — only existing design-system tokens (FK-64) ────────

/** Map task status to an existing CSS token var (no new :root tokens). */
function statusColor(status: WireTask['status']): string {
  switch (status) {
    case 'open':
      return 'var(--ak-status-progress)';
    case 'done':
      return 'var(--ak-status-done)';
    case 'dismissed':
      return 'var(--ak-status-cancelled)';
    default:
      return 'var(--ak-text-muted)';
  }
}

/** Map task priority to a display label. */
function priorityLabel(priority: WireTask['priority']): string {
  switch (priority) {
    case 'high':
      return 'Hoch';
    case 'normal':
      return 'Normal';
    case 'low':
      return 'Niedrig';
    default:
      return priority;
  }
}

/** Map task kind to a display label. */
function kindLabel(kind: WireTask['kind']): string {
  switch (kind) {
    case 'actionable':
      return 'Handlungsauftrag';
    case 'reminder':
      return 'Erinnerung';
    default:
      return kind;
  }
}

/** Map task status to a display label. */
function statusLabel(status: WireTask['status']): string {
  switch (status) {
    case 'open':
      return 'Offen';
    case 'done':
      return 'Erledigt';
    case 'dismissed':
      return 'Verworfen';
    default:
      return status;
  }
}

/** Map relation kind to a display label. */
function relationLabel(kind: WireTaskLink['kind']): string {
  switch (kind) {
    case 'relates_to':
      return 'Verwandt';
    case 'spawned_story':
      return 'Story';
    case 'duplicate_of':
      return 'Duplikat';
    default:
      return kind;
  }
}

/** Extract the error_code from a BffReadError or fall back to a generic string. */
function errorCodeOf(err: unknown): string {
  if (err instanceof BffReadError) return err.errorCode;
  return 'error';
}

// ── Link badge sub-component ──────────────────────────────────────────────────

interface LinkBadgesProps {
  links: WireTaskLink[];
  taskId: string;
  onUnlink: (targetKind: 'task' | 'story', targetId: string, kind: WireTaskLink['kind']) => void;
  /** Cross-slice navigation: focus a linked story in the story view (AC4). */
  onFocusStory?: (storyId: string) => void;
  mutating: boolean;
  /** When false, the per-badge unlink control is hidden (terminal tasks, AC5). */
  canMutate: boolean;
}

function LinkBadges({ links, taskId, onUnlink, onFocusStory, mutating, canMutate }: LinkBadgesProps): ReactElement {
  if (links.length === 0) {
    return <span className="task-row__no-links" data-testid={`task-no-links-${taskId}`}>Keine Links</span>;
  }
  return (
    <div className="task-row__links" data-testid={`task-links-${taskId}`}>
      {links.map((link) => {
        // AC4: a story link is clickable and focuses the story in the story view
        // via the shell. Task links are not navigable inside the task slice.
        const isStory = link.target_kind === 'story';
        const navigable = isStory && onFocusStory != null;
        return (
          <span
            key={`${link.target_kind}:${link.target_id}:${link.kind}`}
            className="task-row__link-badge"
            data-testid={`task-link-badge-${taskId}-${link.target_kind}-${link.target_id}`}
          >
            <span className="task-row__link-kind">{isStory ? '📖' : '🔗'}</span>
            {navigable ? (
              <button
                type="button"
                className="task-row__link-target task-row__link-target--nav"
                data-testid={`task-link-focus-${taskId}-${link.target_id}`}
                title="Story in der Story-Sicht öffnen"
                onClick={() => onFocusStory(link.target_id)}
              >
                {link.target_id}
              </button>
            ) : (
              <span className="task-row__link-target">{link.target_id}</span>
            )}
            <span className="task-row__link-relation">({relationLabel(link.kind)})</span>
            {canMutate && (
              <button
                type="button"
                className="task-row__link-remove"
                disabled={mutating}
                data-testid={`task-unlink-${taskId}-${link.target_kind}-${link.target_id}`}
                title="Link entfernen"
                onClick={() => onUnlink(link.target_kind, link.target_id, link.kind)}
              >
                ×
              </button>
            )}
          </span>
        );
      })}
    </div>
  );
}

// ── Reverse-link (incoming) sub-component (AC4 bidirectional) ─────────────────

interface ReverseLinksProps {
  /** ids of the tasks that LINK TO this task (incoming direction). */
  linkerIds: string[];
  taskId: string;
  /** Optional: focus/scroll to a linking task row when its id is clicked. */
  onFocusTask?: (taskId: string) => void;
}

/**
 * AC4 reverse view (task side): a compact, read-only "Verlinkende Aufgaben"
 * section listing the tasks that link TO this task. The ids come from
 * list_tasks_for_target('task', task_id) — backend truth, no session shadow.
 */
function ReverseLinks({ linkerIds, taskId, onFocusTask }: ReverseLinksProps): ReactElement | null {
  if (linkerIds.length === 0) return null;
  return (
    <div className="task-row__reverse-links" data-testid={`task-reverse-links-${taskId}`}>
      <span className="task-row__reverse-label">Verlinkende Aufgaben:</span>
      {linkerIds.map((linkerId) => (
        <button
          key={linkerId}
          type="button"
          className="task-row__reverse-link"
          data-testid={`task-reverse-link-${taskId}-${linkerId}`}
          title="Zur verlinkenden Aufgabe springen"
          onClick={() => onFocusTask?.(linkerId)}
        >
          {linkerId}
        </button>
      ))}
    </div>
  );
}

// ── Add-link form sub-component ───────────────────────────────────────────────

interface AddLinkFormProps {
  taskId: string;
  onLink: (targetKind: 'task' | 'story', targetId: string, kind: WireTaskLink['kind']) => void;
  onCancel: () => void;
  mutating: boolean;
}

function AddLinkForm({ taskId, onLink, onCancel, mutating }: AddLinkFormProps): ReactElement {
  const [targetKind, setTargetKind] = useState<'task' | 'story'>('story');
  const [targetId, setTargetId] = useState('');
  const [kind, setKind] = useState<WireTaskLink['kind']>('relates_to');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!targetId.trim()) return;
    onLink(targetKind, targetId.trim(), kind);
  };

  return (
    <form
      className="task-row__link-form"
      data-testid={`task-link-form-${taskId}`}
      onSubmit={handleSubmit}
    >
      <select
        value={targetKind}
        data-testid={`task-link-target-kind-${taskId}`}
        onChange={(e) => setTargetKind(e.target.value as 'task' | 'story')}
        disabled={mutating}
      >
        <option value="story">Story</option>
        <option value="task">Aufgabe</option>
        {/* No artifact option — FK-77 §77.3: only task|story are valid targets */}
      </select>
      <input
        type="text"
        value={targetId}
        data-testid={`task-link-target-id-${taskId}`}
        onChange={(e) => setTargetId(e.target.value)}
        placeholder={targetKind === 'story' ? 'Story-ID (z.B. AG3-042)' : 'Aufgaben-ID (z.B. TM-2026-0001)'}
        disabled={mutating}
      />
      <select
        value={kind}
        data-testid={`task-link-kind-${taskId}`}
        onChange={(e) => setKind(e.target.value as WireTaskLink['kind'])}
        disabled={mutating}
      >
        <option value="relates_to">Verwandt</option>
        <option value="spawned_story">Story</option>
        <option value="duplicate_of">Duplikat</option>
      </select>
      <button type="submit" className="ak-button ak-button--primary" disabled={mutating || !targetId.trim()}>
        Verlinken
      </button>
      <button type="button" className="ak-button" onClick={onCancel} disabled={mutating}>
        Abbrechen
      </button>
    </form>
  );
}

// ── Task row sub-component ────────────────────────────────────────────────────

interface TaskRowProps {
  task: WireTask;
  links: WireTaskLink[];
  /** AC4 reverse view: ids of tasks that link TO this task (incoming). */
  reverseLinkerIds: string[];
  onResolve: (taskId: string) => void;
  onDismiss: (taskId: string) => void;
  onLink: (taskId: string, targetKind: 'task' | 'story', targetId: string, kind: WireTaskLink['kind']) => void;
  onUnlink: (taskId: string, targetKind: 'task' | 'story', targetId: string, kind: WireTaskLink['kind']) => void;
  /** Cross-slice navigation: focus a linked story in the story view (AC4). */
  onFocusStory?: (storyId: string) => void;
  /** AC4 reverse view: focus/scroll to a linking task row within the slice. */
  onFocusTask?: (taskId: string) => void;
  mutating: boolean;
}

function TaskRow({
  task,
  links,
  reverseLinkerIds,
  onResolve,
  onDismiss,
  onLink,
  onUnlink,
  onFocusStory,
  onFocusTask,
  mutating,
}: TaskRowProps): ReactElement {
  const [showLinkForm, setShowLinkForm] = useState(false);
  const color = statusColor(task.status);
  const isOpen = task.status === 'open';

  const handleLink = (targetKind: 'task' | 'story', targetId: string, kind: WireTaskLink['kind']) => {
    setShowLinkForm(false);
    onLink(task.task_id, targetKind, targetId, kind);
  };

  return (
    <li className="task-row ak-panel" data-testid={`task-row-${task.task_id}`}>
      <div className="task-row__header">
        <span
          className="task-row__status-dot"
          style={{ background: color }}
          aria-hidden="true"
        />
        <span
          className="task-row__title"
          data-testid={`task-title-${task.task_id}`}
        >
          {task.title}
        </span>
        <span
          className="task-row__priority"
          data-testid={`task-priority-${task.task_id}`}
        >
          {priorityLabel(task.priority)}
        </span>
        <span
          className="task-row__kind"
          data-testid={`task-kind-${task.task_id}`}
        >
          {kindLabel(task.kind)}
        </span>
        <span
          className="task-row__status"
          style={{ color }}
          data-testid={`task-status-${task.task_id}`}
        >
          {statusLabel(task.status)}
        </span>
      </div>

      {/* body field — NOT description (wire key is `body`) */}
      {task.body && (
        <p
          className="task-row__body"
          data-testid={`task-body-${task.task_id}`}
        >
          {task.body}
        </p>
      )}

      {/* source_story_id field — NOT story_id */}
      {task.source_story_id && (
        <p
          className="task-row__story-ref"
          data-testid={`task-story-ref-${task.task_id}`}
        >
          Story: <code>{task.source_story_id}</code>
        </p>
      )}

      {/* Link badges (AC2 / AC4). Badges stay VISIBLE (read-only) for terminal
          tasks; only the mutating controls (+ Link, AddLinkForm, unlink ×) are
          hidden when the task is no longer open (AC5: terminal tasks offer no
          further actions). */}
      <div className="task-row__link-section">
        <LinkBadges
          links={links}
          taskId={task.task_id}
          onUnlink={(targetKind, targetId, kind) => onUnlink(task.task_id, targetKind, targetId, kind)}
          onFocusStory={onFocusStory}
          mutating={mutating}
          canMutate={isOpen}
        />
        {isOpen && !showLinkForm && (
          <button
            type="button"
            className="ak-button task-row__add-link"
            disabled={mutating}
            data-testid={`task-add-link-${task.task_id}`}
            onClick={() => setShowLinkForm(true)}
          >
            + Link
          </button>
        )}
        {isOpen && showLinkForm && (
          <AddLinkForm
            taskId={task.task_id}
            onLink={handleLink}
            onCancel={() => setShowLinkForm(false)}
            mutating={mutating}
          />
        )}
        {/* AC4 reverse view (task side): tasks that link TO this task. Read-only,
            backend-hydrated; stays visible regardless of task status. */}
        <ReverseLinks
          linkerIds={reverseLinkerIds}
          taskId={task.task_id}
          onFocusTask={onFocusTask}
        />
      </div>

      {/* Actions: only available from open state — terminal tasks have no actions (AC5) */}
      {isOpen && (
        <div className="task-row__actions">
          <button
            className="ak-button ak-button--primary"
            type="button"
            disabled={mutating}
            data-testid={`task-resolve-${task.task_id}`}
            onClick={() => onResolve(task.task_id)}
          >
            Erledigen
          </button>
          <button
            className="ak-button"
            type="button"
            disabled={mutating}
            data-testid={`task-dismiss-${task.task_id}`}
            onClick={() => onDismiss(task.task_id)}
          >
            Verwerfen
          </button>
        </div>
      )}
    </li>
  );
}

// ── Create task form sub-component ────────────────────────────────────────────

interface CreateTaskFormProps {
  onSubmit: (payload: CreateTaskPayload) => void;
  onCancel: () => void;
  mutating: boolean;
}

function CreateTaskForm({ onSubmit, onCancel, mutating }: CreateTaskFormProps): ReactElement {
  const [title, setTitle] = useState('');
  const [body, setBody] = useState('');
  const [kind, setKind] = useState<WireTask['kind']>('actionable');
  const [type, setType] = useState('general');
  const [priority, setPriority] = useState<WireTask['priority']>('normal');
  const [origin, setOrigin] = useState<WireTask['origin']>('human');
  const [sourceStoryId, setSourceStoryId] = useState('');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!title.trim() || !body.trim()) return;
    const payload: CreateTaskPayload = {
      kind,
      type: type.trim() || 'general',
      title: title.trim(),
      body: body.trim(),
      priority,
      origin,
      source_story_id: sourceStoryId.trim() || null,
    };
    onSubmit(payload);
  };

  return (
    <form className="task-create-form ak-panel" data-testid="task-create-form" onSubmit={handleSubmit}>
      <h3>Neue Aufgabe erstellen</h3>
      <div className="task-create-form__field">
        <label htmlFor="task-create-title">Titel *</label>
        <input
          id="task-create-title"
          type="text"
          value={title}
          data-testid="task-create-title"
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Aufgabentitel"
          disabled={mutating}
          required
        />
      </div>
      <div className="task-create-form__field">
        <label htmlFor="task-create-body">Beschreibung *</label>
        <textarea
          id="task-create-body"
          value={body}
          data-testid="task-create-body"
          onChange={(e) => setBody(e.target.value)}
          placeholder="Aufgabenbeschreibung"
          disabled={mutating}
          required
        />
      </div>
      <div className="task-create-form__row">
        <div className="task-create-form__field">
          <label htmlFor="task-create-kind">Art</label>
          <select
            id="task-create-kind"
            value={kind}
            data-testid="task-create-kind"
            onChange={(e) => setKind(e.target.value as WireTask['kind'])}
            disabled={mutating}
          >
            <option value="actionable">Handlungsauftrag</option>
            <option value="reminder">Erinnerung</option>
          </select>
        </div>
        <div className="task-create-form__field">
          <label htmlFor="task-create-type">Typ</label>
          <input
            id="task-create-type"
            type="text"
            value={type}
            data-testid="task-create-type"
            onChange={(e) => setType(e.target.value)}
            placeholder="general"
            disabled={mutating}
          />
        </div>
        <div className="task-create-form__field">
          <label htmlFor="task-create-priority">Priorität</label>
          <select
            id="task-create-priority"
            value={priority}
            data-testid="task-create-priority"
            onChange={(e) => setPriority(e.target.value as WireTask['priority'])}
            disabled={mutating}
          >
            <option value="high">Hoch</option>
            <option value="normal">Normal</option>
            <option value="low">Niedrig</option>
          </select>
        </div>
        <div className="task-create-form__field">
          <label htmlFor="task-create-origin">Ursprung</label>
          <select
            id="task-create-origin"
            value={origin}
            data-testid="task-create-origin"
            onChange={(e) => setOrigin(e.target.value as WireTask['origin'])}
            disabled={mutating}
          >
            <option value="human">Manuell</option>
            <option value="governance">Governance</option>
            <option value="verify">Verify</option>
            <option value="closure">Closure</option>
          </select>
        </div>
      </div>
      <div className="task-create-form__field">
        <label htmlFor="task-create-source-story">Story-Referenz (optional)</label>
        <input
          id="task-create-source-story"
          type="text"
          value={sourceStoryId}
          data-testid="task-create-source-story-id"
          onChange={(e) => setSourceStoryId(e.target.value)}
          placeholder="z.B. AG3-042"
          disabled={mutating}
        />
      </div>
      <div className="task-create-form__actions">
        <button
          type="submit"
          className="ak-button ak-button--primary"
          disabled={mutating || !title.trim() || !body.trim()}
          data-testid="task-create-submit"
        >
          Erstellen
        </button>
        <button type="button" className="ak-button" onClick={onCancel} disabled={mutating}>
          Abbrechen
        </button>
      </div>
    </form>
  );
}

// ── Props + slot component ─────────────────────────────────────────────────────

export interface TaskSlotProps {
  projectKey: string;
  baseUrl?: string;
  /** Injectable BFF client for testing; defaults to new BffClient(baseUrl). */
  client?: BffClient;
  /**
   * Cross-slice navigation callback (AC4): focus a linked story in the story
   * view. The shell switches the active view away from 'tasks' and opens the
   * story in the inspector. Optional so the slice renders standalone in tests.
   */
  onFocusStory?: (storyId: string) => void;
}

export function TaskSlot({ projectKey, baseUrl = '', client, onFocusStory }: TaskSlotProps): ReactElement {
  // Respect injectable client first; otherwise create one from baseUrl.
  // useMemo ensures a stable BffClient reference (avoids infinite re-render from new object every render).
  const bff = useMemo(
    () => client ?? new BffClient(baseUrl),
    [client, baseUrl],
  );

  const [tasks, setTasks] = useState<WireTask[]>([]);
  // Map from task_id -> links for that task
  const [taskLinks, setTaskLinks] = useState<Record<string, WireTaskLink[]>>({});
  // AC4 reverse view (task side): map from task_id -> ids of the tasks that
  // LINK TO this task (incoming direction). Hydrated from the backend via
  // list_tasks_for_target('task', task_id) — NOT derived from session state.
  const [reverseLinks, setReverseLinks] = useState<Record<string, string[]>>({});
  const [isLoading, setIsLoading] = useState(false);
  const [loadError, setLoadError] = useState<{ message: string; code: string } | null>(null);
  const [mutating, setMutating] = useState(false);
  const [mutateError, setMutateError] = useState<{ message: string; code: string } | null>(null);
  const [showCreateForm, setShowCreateForm] = useState(false);

  // Stale-request guard (AC6 cross-tenant race): a monotonically increasing
  // request id. Every load run captures the id it was started with; results
  // are only applied to state when their id is still the latest one. On a fast
  // projectKey change, an in-flight fetch for the OLD project would otherwise
  // resolve AFTER the new project's fetch and overwrite state with the wrong
  // tenant's data. The per-effect cleanup bumps the id so the superseded run's
  // setTasks/setTaskLinks become no-ops.
  const requestIdRef = useRef(0);

  // AC4 reverse view (task side): for each task, fetch the tasks that LINK TO
  // it (incoming) via list_tasks_for_target('task', task_id). Reads from the
  // backend, keyed off projectKey/task_id — guarded by the SAME requestId so a
  // superseded projectKey switch never applies these. Runs as a non-blocking
  // follow-up so the primary list is already rendered. A failure here is
  // auxiliary: it must not blank the primary task list.
  const hydrateReverseLinks = useCallback(
    async (loadedTasks: WireTask[], isCurrent: () => boolean) => {
      try {
        const reverseEntries = await Promise.all(
          loadedTasks.map(async (t) => {
            const resp = await bff.listTasksForTarget(projectKey, 'task', t.task_id);
            // Exclude self: a task is never its own linker.
            const linkerIds = resp.tasks
              .map((linker) => linker.task_id)
              .filter((id) => id !== t.task_id);
            return [t.task_id, linkerIds] as const;
          }),
        );
        if (!isCurrent()) return;
        const reverseByTask: Record<string, string[]> = {};
        for (const [taskId, linkerIds] of reverseEntries) {
          reverseByTask[taskId] = linkerIds;
        }
        setReverseLinks(reverseByTask);
      } catch {
        if (isCurrent()) setReverseLinks({});
      }
    },
    [bff, projectKey],
  );

  const fetchTasks = useCallback(
    async (requestId: number) => {
      const isCurrent = () => requestId === requestIdRef.current;
      setIsLoading(true);
      setLoadError(null);
      setReverseLinks({});
      try {
        // SSOT (finding 1): both the tasks AND their links come from the backend.
        // taskLinks is hydrated from GET /task-links — NOT from session-local
        // mutation state — so badges reflect backend truth on every (re)load.
        const [tasksResp, linksResp] = await Promise.all([
          bff.listTasks(projectKey),
          bff.listTaskLinks(projectKey),
        ]);
        // Drop superseded results: a newer projectKey fetch has started.
        if (!isCurrent()) return;
        setTasks(tasksResp.tasks);
        // Bucket links by task_id so each task renders its own outgoing links.
        const byTask: Record<string, WireTaskLink[]> = {};
        for (const link of linksResp.links) {
          (byTask[link.task_id] ??= []).push(link);
        }
        setTaskLinks(byTask);
        // Release the loading state as soon as the primary list is applied —
        // the reverse-view hydration must NOT delay the list render.
        setIsLoading(false);
        await hydrateReverseLinks(tasksResp.tasks, isCurrent);
      } catch (err) {
        if (!isCurrent()) return;
        const code = errorCodeOf(err);
        const msg = err instanceof Error ? err.message : String(err);
        setLoadError({ message: `Aufgaben konnten nicht geladen werden: ${msg}`, code });
        setIsLoading(false);
      }
    },
    [bff, projectKey, hydrateReverseLinks],
  );

  useEffect(() => {
    const requestId = requestIdRef.current + 1;
    requestIdRef.current = requestId;
    void fetchTasks(requestId);
    return () => {
      // Supersede this run: any pending result for it must not touch state.
      requestIdRef.current += 1;
    };
  }, [fetchTasks]);

  // ── Resolve (optimistic update + revert on failure) ────────────────────────

  const handleResolve = useCallback(
    async (taskId: string) => {
      // Optimistic: mark task as done immediately
      const previousTasks = tasks;
      setTasks((prev) =>
        prev.map((t) => (t.task_id === taskId ? { ...t, status: 'done' as const } : t)),
      );
      setMutating(true);
      setMutateError(null);
      try {
        const updatedTask = await bff.resolveTask(projectKey, taskId);
        // Replace with server truth
        setTasks((prev) => prev.map((t) => (t.task_id === taskId ? updatedTask : t)));
      } catch (err) {
        // Revert on failure (AC9)
        setTasks(previousTasks);
        const code = errorCodeOf(err);
        const msg = err instanceof Error ? err.message : String(err);
        setMutateError({ message: `Aufgabe konnte nicht erledigt werden (${code}): ${msg}`, code });
      } finally {
        setMutating(false);
      }
    },
    [bff, projectKey, tasks],
  );

  // ── Dismiss (optimistic update + revert on failure) ────────────────────────

  const handleDismiss = useCallback(
    async (taskId: string) => {
      // Optimistic: mark task as dismissed immediately
      const previousTasks = tasks;
      setTasks((prev) =>
        prev.map((t) => (t.task_id === taskId ? { ...t, status: 'dismissed' as const } : t)),
      );
      setMutating(true);
      setMutateError(null);
      try {
        const updatedTask = await bff.dismissTask(projectKey, taskId);
        // Replace with server truth
        setTasks((prev) => prev.map((t) => (t.task_id === taskId ? updatedTask : t)));
      } catch (err) {
        // Revert on failure (AC9)
        setTasks(previousTasks);
        const code = errorCodeOf(err);
        const msg = err instanceof Error ? err.message : String(err);
        setMutateError({ message: `Aufgabe konnte nicht verworfen werden (${code}): ${msg}`, code });
      } finally {
        setMutating(false);
      }
    },
    [bff, projectKey, tasks],
  );

  // ── Create (AC3: new task appears FROM server response, no local shadow) ──

  const handleCreate = useCallback(
    async (payload: CreateTaskPayload) => {
      setMutating(true);
      setMutateError(null);
      try {
        const resp = await bff.createTask(projectKey, payload);
        // Prepend the server-returned task — no local ID fabrication (AC3)
        setTasks((prev) => [resp.task, ...prev]);
        setShowCreateForm(false);
      } catch (err) {
        const code = errorCodeOf(err);
        const msg = err instanceof Error ? err.message : String(err);
        setMutateError({ message: `Aufgabe konnte nicht erstellt werden (${code}): ${msg}`, code });
      } finally {
        setMutating(false);
      }
    },
    [bff, projectKey],
  );

  // ── Link (AC4: target_kind ∈ {task, story} only) ──────────────────────────

  const handleLink = useCallback(
    async (
      taskId: string,
      targetKind: 'task' | 'story',
      targetId: string,
      kind: WireTaskLink['kind'],
    ) => {
      setMutating(true);
      setMutateError(null);
      try {
        const resp = await bff.linkTask(projectKey, taskId, targetKind, targetId, kind);
        setTaskLinks((prev) => ({
          ...prev,
          [taskId]: [...(prev[taskId] ?? []), resp.link],
        }));
      } catch (err) {
        const code = errorCodeOf(err);
        const msg = err instanceof Error ? err.message : String(err);
        setMutateError({ message: `Link konnte nicht erstellt werden (${code}): ${msg}`, code });
      } finally {
        setMutating(false);
      }
    },
    [bff, projectKey],
  );

  // ── Unlink (optimistic update + revert on failure) ─────────────────────────

  const handleUnlink = useCallback(
    async (
      taskId: string,
      targetKind: 'task' | 'story',
      targetId: string,
      kind: WireTaskLink['kind'],
    ) => {
      const previousLinks = taskLinks;
      // Optimistic removal
      setTaskLinks((prev) => ({
        ...prev,
        [taskId]: (prev[taskId] ?? []).filter(
          (l) => !(l.target_kind === targetKind && l.target_id === targetId && l.kind === kind),
        ),
      }));
      setMutating(true);
      setMutateError(null);
      try {
        await bff.unlinkTask(projectKey, taskId, targetKind, targetId, kind);
      } catch (err) {
        // Revert on failure
        setTaskLinks(previousLinks);
        const code = errorCodeOf(err);
        const msg = err instanceof Error ? err.message : String(err);
        setMutateError({ message: `Link konnte nicht entfernt werden (${code}): ${msg}`, code });
      } finally {
        setMutating(false);
      }
    },
    [bff, projectKey, taskLinks],
  );

  // AC4 reverse view: scroll/focus the row of a linking task within the slice.
  const handleFocusTask = useCallback((taskId: string) => {
    const row = document.querySelector(`[data-testid="task-row-${taskId}"]`);
    if (row instanceof HTMLElement) {
      row.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
  }, []);

  const openTasks = tasks.filter((t) => t.status === 'open');
  const closedTasks = tasks.filter((t) => t.status !== 'open');

  return (
    <div className="task-slot" data-testid="task-slot">
      {/* Error pills include error_code (AC9) */}
      {loadError && (
        <div
          className="error-pill"
          role="alert"
          data-testid="task-load-error"
          data-error-code={loadError.code}
        >
          {loadError.message}
          {loadError.code !== 'error' && (
            <code className="error-pill__code" data-testid="task-load-error-code">
              {' '}[{loadError.code}]
            </code>
          )}
        </div>
      )}
      {mutateError && (
        <div
          className="error-pill"
          role="alert"
          data-testid="task-mutate-error"
          data-error-code={mutateError.code}
        >
          {mutateError.message}
          {mutateError.code !== 'error' && (
            <code className="error-pill__code" data-testid="task-mutate-error-code">
              {' '}[{mutateError.code}]
            </code>
          )}
        </div>
      )}

      <header className="task-slot__head">
        <div>
          <p className="eyebrow">Aufgabenverwaltung</p>
          <h1>Aufgaben</h1>
        </div>
        <div className="task-slot__head-actions">
          <span className="task-slot__count" data-testid="task-open-count">
            {openTasks.length} offen
          </span>
          <button
            type="button"
            className="ak-button ak-button--primary"
            data-testid="task-create-open"
            disabled={mutating}
            onClick={() => setShowCreateForm((prev) => !prev)}
          >
            {showCreateForm ? 'Abbrechen' : '+ Aufgabe'}
          </button>
        </div>
      </header>

      {/* Create form (AC1/AC3) */}
      {showCreateForm && (
        <CreateTaskForm
          onSubmit={(payload) => { void handleCreate(payload); }}
          onCancel={() => setShowCreateForm(false)}
          mutating={mutating}
        />
      )}

      {isLoading ? (
        <p className="task-slot__loading" data-testid="task-loading">
          Aufgaben werden geladen…
        </p>
      ) : tasks.length === 0 ? (
        // Empty state with create CTA (AC9)
        <div className="task-slot__empty" data-testid="task-empty">
          <p>Keine Aufgaben vorhanden.</p>
          {!showCreateForm && (
            <button
              type="button"
              className="ak-button ak-button--primary"
              data-testid="task-empty-create-cta"
              onClick={() => setShowCreateForm(true)}
            >
              Erste Aufgabe erstellen
            </button>
          )}
        </div>
      ) : (
        <>
          {openTasks.length > 0 && (
            <section aria-label="Offene Aufgaben">
              <ul className="task-list" data-testid="task-list-open">
                {openTasks.map((task) => (
                  <TaskRow
                    key={task.task_id}
                    task={task}
                    links={taskLinks[task.task_id] ?? []}
                    reverseLinkerIds={reverseLinks[task.task_id] ?? []}
                    onResolve={(id) => { void handleResolve(id); }}
                    onDismiss={(id) => { void handleDismiss(id); }}
                    onLink={(id, tk, ti, k) => { void handleLink(id, tk, ti, k); }}
                    onUnlink={(id, tk, ti, k) => { void handleUnlink(id, tk, ti, k); }}
                    onFocusStory={onFocusStory}
                    onFocusTask={handleFocusTask}
                    mutating={mutating}
                  />
                ))}
              </ul>
            </section>
          )}

          {closedTasks.length > 0 && (
            <section aria-label="Erledigte / Verworfene Aufgaben">
              <h2 className="task-slot__section-title">Abgeschlossen</h2>
              <ul className="task-list task-list--closed" data-testid="task-list-closed">
                {closedTasks.map((task) => (
                  <TaskRow
                    key={task.task_id}
                    task={task}
                    links={taskLinks[task.task_id] ?? []}
                    reverseLinkerIds={reverseLinks[task.task_id] ?? []}
                    onResolve={(id) => { void handleResolve(id); }}
                    onDismiss={(id) => { void handleDismiss(id); }}
                    onLink={(id, tk, ti, k) => { void handleLink(id, tk, ti, k); }}
                    onUnlink={(id, tk, ti, k) => { void handleUnlink(id, tk, ti, k); }}
                    onFocusStory={onFocusStory}
                    onFocusTask={handleFocusTask}
                    mutating={mutating}
                  />
                ))}
              </ul>
            </section>
          )}
        </>
      )}
    </div>
  );
}
