/**
 * AC3/AC9/AC10f: Inspector has exactly 4 tabs in order ("Spezifikation", "Ergebnis",
 * "KPIs", "Ablauf") AND each tab renders its FETCHED read-model (E2/E3), not local
 * fallback prose.
 */
import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { DetailInspector } from '../app_shell/inspector/DetailInspector';
import type { Story } from '../store';
import type {
  StoryDetailResponse,
  StoryFlowResponse,
  CoverageAcceptanceResponse,
  AreEvidenceResponse,
} from '../foundation/bff/client';

// Minimal story fixture for inspector tests
const minimalStory: Story = {
  id: 'AG3-093',
  title: 'Test Story',
  type: 'implementation',
  status: 'Backlog',
  size: 'M',
  owner: 'test',
  repo: 'test-repo',
  module: 'test-module',
  epic: 'Test Epic',
  changeImpact: 'Local',
  conceptQuality: 'High',
  wave: 1,
  risk: 'low',
  criticalPath: false,
  qaRounds: 0,
  processingTime: '0 min',
  labels: [],
  acceptance: ['AC1', 'AC2'],
  gates: [],
  phases: [],
  events: [],
  dependencies: [],
};

const storyDetail: StoryDetailResponse = {
  summary: {
    id: 'AG3-093', title: 'Test Story', status: 'Backlog', type: 'implementation',
    size: 'M', owner: 'test', repo: 'test-repo', module: 'test-module', epic: 'Test Epic',
    changeImpact: 'Local', conceptQuality: 'High', wave: 1,
  },
  spec: {
    need: 'FETCHED-NEED-TEXT',
    solution: 'FETCHED-SOLUTION-TEXT',
    acceptance: ['FETCHED-AC-1'],
    definition_of_done: ['FETCHED-DOD-1'],
    concept_refs: ['FK-72'],
    guardrail_refs: ['ARCH-55'],
    external_sources: null,
  },
  evidence: {
    qa_cycle_id: 'qa-cycle-xyz',
    qa_cycle_round: 2,
    evidence_epoch: 'epoch-1',
    evidence_fingerprint: 'fp-1',
    manifest_hash: 'hash-1',
    bundle_entries: [{ authority: 'STORY_SPEC', path: 'stories/x/story.md', status: 'INCLUDED' }],
  },
  telemetry: null, gates: [], phases: [], events: [],
};

const flowSnapshot: StoryFlowResponse['story_flow_snapshot'] = {
  story_id: 'AG3-093', mode: 'standard',
  phases: [
    {
      phase: 'implementation', state: 'paused', state_reason: 'awaiting_human_input',
      iteration: null, iteration_loop_group: null,
      substeps: [{ substep: 'worker', state: 'paused', optional: false, loop_group: null, loop_position: null, loop_size: null }],
    },
  ],
};

const coverageAcceptance: CoverageAcceptanceResponse['story_coverage_acceptance'] = {
  story_id: 'AG3-093', project_key: 'AG3',
  acceptance_criteria: ['COVERAGE-AC-1'], linked_requirements: ['REQ-1'],
};

const coverageAreEvidence: AreEvidenceResponse['story_are_evidence'] = {
  story_id: 'AG3-093', project_key: 'AG3',
  linked_requirements: [{ are_item_id: 'ARE-1', kind: 'requirement', coverage_status: 'covered', evidence_paths: ['p'] }],
};

describe('AC3: DetailInspector tabs', () => {
  it('renders exactly 4 tabs in correct order', () => {
    render(
      <DetailInspector
        story={minimalStory}
        width={858}
        onClose={() => undefined}
        onResizeStart={() => undefined}
      />,
    );

    const tablist = screen.getByRole('tablist');
    const tabs = tablist.querySelectorAll('button');

    expect(tabs).toHaveLength(4);
    expect(tabs[0]).toHaveTextContent('Spezifikation');
    expect(tabs[1]).toHaveTextContent('Ergebnis');
    expect(tabs[2]).toHaveTextContent('KPIs');
    expect(tabs[3]).toHaveTextContent('Ablauf');
  });

  it('shows Spezifikation tab content by default', () => {
    render(
      <DetailInspector
        story={minimalStory}
        width={858}
        onClose={() => undefined}
        onResizeStart={() => undefined}
      />,
    );

    // SpecificationTab shows story title
    expect(screen.getByText('Test Story')).toBeTruthy();
  });
});

describe('AC9 E2: tabs render the FETCHED read-models, not local fallback', () => {
  function renderWithReadModels() {
    return render(
      <DetailInspector
        story={minimalStory}
        storyDetail={storyDetail}
        flowSnapshot={flowSnapshot}
        coverageAcceptance={coverageAcceptance}
        coverageAreEvidence={coverageAreEvidence}
        width={858}
        onClose={() => undefined}
        onResizeStart={() => undefined}
      />,
    );
  }

  it('SpecificationTab renders fetched spec.need/solution', () => {
    renderWithReadModels();
    expect(screen.getByText(/FETCHED-NEED-TEXT/)).toBeTruthy();
    expect(screen.getByText(/FETCHED-SOLUTION-TEXT/)).toBeTruthy();
    expect(screen.getByText('FETCHED-AC-1')).toBeTruthy();
  });

  it('EvidenceTab renders fetched evidence + coverage read-models', () => {
    renderWithReadModels();
    fireEvent.click(screen.getByText('Ergebnis'));
    expect(screen.getByText('qa-cycle-xyz')).toBeTruthy();
    expect(screen.getByText('COVERAGE-AC-1')).toBeTruthy();
    expect(screen.getByText('ARE-1')).toBeTruthy();
  });

  it('SpecificationTab fails closed (empty-state) when spec is absent', () => {
    render(
      <DetailInspector
        story={minimalStory}
        storyDetail={{ ...storyDetail, spec: null }}
        width={858}
        onClose={() => undefined}
        onResizeStart={() => undefined}
      />,
    );
    expect(screen.getByText('Keine Spezifikation verfügbar.')).toBeTruthy();
  });
});

describe('AC10f E3: flow hold-state + state_reason from the fetched snapshot', () => {
  it('renders the paused hold-state, state_reason, and a global header pill', () => {
    render(
      <DetailInspector
        story={minimalStory}
        flowSnapshot={flowSnapshot}
        width={858}
        onClose={() => undefined}
        onResizeStart={() => undefined}
      />,
    );
    // Global header hold pill (AC10f).
    expect(screen.getByText('pausiert')).toBeTruthy();
    fireEvent.click(screen.getByText('Ablauf'));
    // state_reason rendered (verbatim from the snapshot).
    expect(screen.getByText('awaiting_human_input')).toBeTruthy();
    // Phase hold-state label, not the active "läuft" label.
    expect(screen.getByText('Phase pausiert')).toBeTruthy();
  });

  it('flow tab fails closed (error pill) when the required flow read failed', () => {
    render(
      <DetailInspector
        story={minimalStory}
        flowSnapshot={null}
        flowError="story_flow_unavailable"
        width={858}
        onClose={() => undefined}
        onResizeStart={() => undefined}
      />,
    );
    fireEvent.click(screen.getByText('Ablauf'));
    expect(screen.getByText(/story_flow_unavailable/)).toBeTruthy();
  });
});
