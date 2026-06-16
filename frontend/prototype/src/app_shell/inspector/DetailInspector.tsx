import { useEffect, useState } from 'react';
import { X } from 'lucide-react';
import type { Story } from '../../store';
import {
  BffClient,
  BffReadError,
  type StoryDetailResponse,
  type StoryFlowResponse,
  type CoverageAcceptanceResponse,
  type AreEvidenceResponse,
  type WireTask,
} from '../../foundation/bff/client';
import { FastBadge } from '../../components/FastBadge';
import { Badge } from '../../design_system/Badge';
import { FlowTab } from '../../contexts/pipeline_engine/FlowTab';
import { SpecificationTab } from '../../contexts/story_context_manager/SpecificationTab';
import { EvidenceTab } from '../../contexts/artifacts/EvidenceTab';
import { KpiTab } from '../../contexts/kpi_analytics/KpiTab';

const statusClass: Record<Story['status'], string> = {
  Backlog: 'status-backlog',
  Approved: 'status-approved',
  'In Progress': 'status-progress',
  Done: 'success',
  Cancelled: 'cancelled',
};

/** Wire flow hold-states that warrant a global inspector-header pill (AC10f). */
const HOLD_STATE_LABEL: Record<string, string> = {
  paused: 'pausiert',
  escalated: 'eskaliert',
  failed: 'fehlgeschlagen',
};

type FlowSnapshot = StoryFlowResponse['story_flow_snapshot'];
type CoverageAcceptance = CoverageAcceptanceResponse['story_coverage_acceptance'];
type AreEvidence = AreEvidenceResponse['story_are_evidence'];

/** Derive the dominant hold-state label from the fetched flow snapshot. */
function holdStateOf(snapshot: FlowSnapshot | null): string | null {
  if (!snapshot) return null;
  for (const phase of snapshot.phases) {
    const label = HOLD_STATE_LABEL[phase.state];
    if (label) return label;
  }
  return null;
}

type InspectorTab = 'spec' | 'evidence' | 'kpi' | 'flow';

/**
 * AC4 reverse view (story side): the tasks that LINK TO this story.
 *
 * Realises "Story-Detail -> verlinkende Tasks" by calling
 * list_tasks_for_target(project_key, 'story', story_id) — backend truth, no
 * session shadow. Read-only. Fail-closed: a read failure surfaces an error pill
 * with its error_code; an empty result shows a quiet hint.
 */
function LinkedTasksSection({
  client,
  projectKey,
  storyId,
}: {
  client: BffClient;
  projectKey: string;
  storyId: string;
}) {
  const [tasks, setTasks] = useState<WireTask[] | null>(null);
  const [error, setError] = useState<{ message: string; code: string } | null>(null);

  useEffect(() => {
    let cancelled = false;
    setTasks(null);
    setError(null);
    void (async () => {
      try {
        const resp = await client.listTasksForTarget(projectKey, 'story', storyId);
        if (!cancelled) setTasks(resp.tasks);
      } catch (err) {
        if (cancelled) return;
        const code = err instanceof BffReadError ? err.errorCode : 'error';
        const msg = err instanceof Error ? err.message : String(err);
        setError({ message: msg, code });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [client, projectKey, storyId]);

  return (
    <section className="inspector-linked-tasks" data-testid="inspector-linked-tasks">
      <h3 className="inspector-linked-tasks__title">Verlinkte Aufgaben</h3>
      {error ? (
        <div
          className="error-pill"
          role="alert"
          data-testid="inspector-linked-tasks-error"
          data-error-code={error.code}
        >
          Verlinkte Aufgaben konnten nicht geladen werden: {error.message}
          <code className="error-pill__code" data-testid="inspector-linked-tasks-error-code">
            {' '}[{error.code}]
          </code>
        </div>
      ) : tasks == null ? (
        <p className="inspector-linked-tasks__loading" data-testid="inspector-linked-tasks-loading">
          Verlinkte Aufgaben werden geladen…
        </p>
      ) : tasks.length === 0 ? (
        <p className="inspector-linked-tasks__empty" data-testid="inspector-linked-tasks-empty">
          Keine verlinkten Aufgaben
        </p>
      ) : (
        <ul className="inspector-linked-tasks__list" data-testid="inspector-linked-tasks-list">
          {tasks.map((task) => (
            <li
              key={task.task_id}
              className="inspector-linked-tasks__item"
              data-testid={`inspector-linked-task-${task.task_id}`}
            >
              <code>{task.task_id}</code> {task.title}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function Detail({
  story,
  storyDetail,
  flowSnapshot,
  flowError,
  coverageAcceptance,
  coverageAreEvidence,
  activeTab,
}: {
  story: Story;
  storyDetail: StoryDetailResponse | null;
  flowSnapshot: FlowSnapshot | null;
  flowError: string | null;
  coverageAcceptance: CoverageAcceptance | null;
  coverageAreEvidence: AreEvidence | null;
  activeTab: InspectorTab;
}) {
  return (
    <aside className="detail">
      {activeTab === 'spec' && <SpecificationTab story={story} spec={storyDetail?.spec ?? null} />}
      {activeTab === 'evidence' && (
        <EvidenceTab
          evidence={storyDetail?.evidence ?? null}
          coverageAcceptance={coverageAcceptance}
          coverageAreEvidence={coverageAreEvidence}
        />
      )}
      {activeTab === 'kpi' && <KpiTab storyDetail={storyDetail} />}
      {activeTab === 'flow' && <FlowTab flowSnapshot={flowSnapshot} flowError={flowError} />}
    </aside>
  );
}

export function DetailInspector({
  story,
  storyDetail = null,
  flowSnapshot = null,
  flowError = null,
  coverageAcceptance = null,
  coverageAreEvidence = null,
  client,
  projectKey,
  width,
  onClose,
  onResizeStart,
}: {
  story: Story;
  storyDetail?: StoryDetailResponse | null;
  flowSnapshot?: FlowSnapshot | null;
  flowError?: string | null;
  coverageAcceptance?: CoverageAcceptance | null;
  coverageAreEvidence?: AreEvidence | null;
  /**
   * AC4 reverse view (story side): BFF client + project key used to list the
   * tasks that link to this story. Optional so the inspector renders standalone
   * in tests that do not exercise the reverse view.
   */
  client?: BffClient;
  projectKey?: string;
  width: number;
  onClose: () => void;
  onResizeStart: () => void;
}) {
  const [activeTab, setActiveTab] = useState<InspectorTab>('spec');
  const holdState = holdStateOf(flowSnapshot);

  return (
    <aside className="detail-inspector ak-panel" data-story-inspector="true" style={{ width }}>
      <div
        aria-label="Inspector-Breite anpassen"
        className="inspector-resize-handle"
        role="separator"
        onMouseDown={(event) => {
          event.preventDefault();
          onResizeStart();
        }}
      />
      <header className="inspector-head">
        <div>
          <p className="eyebrow">Story Inspector</p>
          <h2>
            {story.id}
            <FastBadge mode={story.mode} size={22} />
            <Badge tone={statusClass[story.status]}>{story.status}</Badge>
            {holdState && <Badge tone="warning">{holdState}</Badge>}
          </h2>
        </div>
        <button className="ak-button" type="button" onClick={onClose}>
          <X size={16} />
          Close
        </button>
      </header>
      <div className="file-tabs" role="tablist">
        <button
          className={activeTab === 'spec' ? 'active' : ''}
          type="button"
          onClick={() => setActiveTab('spec')}
        >
          Spezifikation
        </button>
        <button
          className={activeTab === 'evidence' ? 'active' : ''}
          type="button"
          onClick={() => setActiveTab('evidence')}
        >
          Ergebnis
        </button>
        <button
          className={activeTab === 'kpi' ? 'active' : ''}
          type="button"
          onClick={() => setActiveTab('kpi')}
        >
          KPIs
        </button>
        <button
          className={activeTab === 'flow' ? 'active' : ''}
          type="button"
          onClick={() => setActiveTab('flow')}
        >
          Ablauf
        </button>
      </div>
      <Detail
        story={story}
        storyDetail={storyDetail}
        flowSnapshot={flowSnapshot}
        flowError={flowError}
        coverageAcceptance={coverageAcceptance}
        coverageAreEvidence={coverageAreEvidence}
        activeTab={activeTab}
      />
      {/* AC4 reverse view (story side): tasks linking to this story. Shown in the
          Spezifikation tab; needs a client + projectKey from the shell. */}
      {activeTab === 'spec' && client != null && projectKey != null && (
        <LinkedTasksSection client={client} projectKey={projectKey} storyId={story.id} />
      )}
    </aside>
  );
}
