import { useState } from 'react';
import { X } from 'lucide-react';
import type { Story } from '../../store';
import type {
  StoryDetailResponse,
  StoryFlowResponse,
  CoverageAcceptanceResponse,
  AreEvidenceResponse,
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
    </aside>
  );
}
