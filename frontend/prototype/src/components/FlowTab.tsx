/*
 * FlowTab — Story Inspector "Ablauf" view.
 *
 * Renders the 4-phase pipeline (FK-20) as a vertical phase sequence
 * with substeps. The view is built from the story mode
 * (FK-24 §24.3.3): in Fast mode Exploration is dropped entirely —
 * the phase remains visible but marked as "skipped".
 *
 * Two effects are modelled explicitly in the flowchart:
 *
 * 1. Optional substeps (e.g. `feindesign`, `finding_resolution`,
 *    `vectordb_sync`, `inline_reviews`, `qa_feedback`): rendered with
 *    a dashed marker, italic label and an "optional" pill. After the
 *    phase has passed they may appear as `optional-skipped` (not
 *    executed) rather than simply `done`.
 *
 * 2. Loop groups (Exploration: `design_iteration`; Implementation:
 *    `remediation`): contiguous substep sequences are rendered as a
 *    loop region with an accent bar on the left and a return arrow
 *    at the loop end. On the active phase a "Round N" badge appears
 *    once iteration > 1 has run.
 */

import { Fragment } from 'react';
import { RotateCcw } from 'lucide-react';
import {
  LOOP_GROUP_LABELS,
  LOOP_GROUP_MAX_ITERATIONS,
  PHASE_LABELS,
  substepLabel,
  type FlowPhase,
  type FlowState,
  type FlowSubstep,
  type Phase,
} from '../store';
import type { StoryFlowResponse } from '../foundation/bff/client';

const KNOWN_FLOW_STATES: FlowState[] = [
  'done',
  'active',
  'pending',
  'skipped',
  'optional-pending',
  'optional-skipped',
  'paused',
  'escalated',
  'failed',
];

/** Map a wire flow state into a UI FlowState. Hold-states (paused/escalated/
 *  failed) are PRESERVED with their own marker class (AC10f), never collapsed to
 *  'active'. An unknown wire value fails closed to 'pending'. */
function toFlowState(raw: string): FlowState {
  return (KNOWN_FLOW_STATES as string[]).includes(raw) ? (raw as FlowState) : 'pending';
}

/**
 * Adapt the fetched story_flow_snapshot (AG3-091 read-model) into the FlowPhase[]
 * the renderer consumes. This is the ONLY flow source: there is no local Story
 * heuristic fallback (E3). `state_reason` is carried through verbatim (AC10f).
 */
export function flowSnapshotToPhases(
  snapshot: StoryFlowResponse['story_flow_snapshot'],
): FlowPhase[] {
  return snapshot.phases.map((phase) => ({
    phase: phase.phase as Phase,
    state: toFlowState(phase.state),
    stateReason: phase.state_reason ?? undefined,
    iteration: phase.iteration ?? undefined,
    iterationLoopGroup: phase.iteration_loop_group ?? undefined,
    substeps: phase.substeps.map(
      (substep): FlowSubstep => ({
        substep: substep.substep,
        state: toFlowState(substep.state),
        optional: substep.optional,
        loopGroup: substep.loop_group ?? undefined,
        loopPosition: substep.loop_position ?? undefined,
        loopSize: substep.loop_size ?? undefined,
      }),
    ),
  }));
}

const STATE_LABEL: Record<FlowState, string> = {
  done: 'erledigt',
  active: 'läuft',
  pending: 'ausstehend',
  skipped: 'übersprungen',
  /* The pill to the right of the label already says "optional" —
   * the state field therefore only shows progress. */
  'optional-pending': 'ausstehend',
  'optional-skipped': 'nicht nötig',
  paused: 'pausiert',
  escalated: 'eskaliert',
  failed: 'fehlgeschlagen',
};

const PHASE_STATE_LABEL: Record<FlowState, string> = {
  done: 'Phase abgeschlossen',
  active: 'Phase läuft',
  pending: 'Phase ausstehend',
  skipped: 'im Fast-Mode ausgelassen',
  'optional-pending': 'optional',
  'optional-skipped': 'optional übersprungen',
  paused: 'Phase pausiert',
  escalated: 'Phase eskaliert',
  failed: 'Phase fehlgeschlagen',
};

export function FlowTab({
  flowSnapshot = null,
  flowError = null,
}: {
  /** Server-derived flow snapshot (AG3-091). The ONLY flow source — no local
   *  heuristic fallback (E3/AC9). */
  flowSnapshot?: StoryFlowResponse['story_flow_snapshot'] | null;
  /** Error code of a failed required flow read; renders a fail-closed pill. */
  flowError?: string | null;
}) {
  // FAIL-CLOSED: a failed required flow read shows a visible error, never a
  // silently substituted heuristic (E3).
  if (flowError) {
    return (
      <section className="flow-chart" aria-label="Phasen- und Substep-Ablauf">
        <header className="flow-chart__head">
          <div>
            <p className="eyebrow">Pipeline-Ablauf</p>
            <h3>Ablauf nicht verfügbar</h3>
          </div>
        </header>
        <div className="error-pill" role="alert">
          Flow konnte nicht geladen werden ({flowError}).
        </div>
      </section>
    );
  }

  if (!flowSnapshot) {
    return (
      <section className="flow-chart" aria-label="Phasen- und Substep-Ablauf">
        <header className="flow-chart__head">
          <div>
            <p className="eyebrow">Pipeline-Ablauf</p>
            <h3>Ablauf wird geladen…</h3>
          </div>
        </header>
        <p className="empty">Noch kein Flow-Snapshot verfügbar.</p>
      </section>
    );
  }

  const mode = flowSnapshot.mode;
  const flow = flowSnapshotToPhases(flowSnapshot);

  return (
    <section className="flow-chart" aria-label="Phasen- und Substep-Ablauf">
      <header className="flow-chart__head">
        <div>
          <p className="eyebrow">Pipeline-Ablauf</p>
          <h3>{mode === 'fast' ? 'Fast-Mode' : 'Standard-Mode'}</h3>
        </div>
        <p className="flow-chart__hint">
          {mode === 'fast'
            ? 'Exploration ist projektweit ausgelassen; QA-Schichten laufen inline in Implementation.'
            : 'Vollständige 4-Phasen-Pipeline mit Exploration als eigenständigem Vorlauf.'}
        </p>
      </header>

      <ol className="flow-chart__phases">
        {flow.map((phase, index) => (
          <FlowPhaseCard key={phase.phase} phase={phase} isLast={index === flow.length - 1} />
        ))}
      </ol>

      <footer className="flow-chart__legend" aria-label="Legende">
        <span className="flow-chart__legend-item">
          <span className="flow-substep__marker flow-substep__marker--active" aria-hidden="true" />
          aktiv
        </span>
        <span className="flow-chart__legend-item">
          <span className="flow-substep__marker flow-substep__marker--done" aria-hidden="true" />
          erledigt
        </span>
        <span className="flow-chart__legend-item flow-chart__legend-item--optional">
          <span className="flow-substep__marker flow-substep__marker--optional-pending" aria-hidden="true" />
          optional
        </span>
        <span className="flow-chart__legend-item flow-chart__legend-item--loop">
          <RotateCcw size={12} aria-hidden="true" />
          Loop-Region
        </span>
      </footer>
    </section>
  );
}

function FlowPhaseCard({ phase, isLast }: { phase: FlowPhase; isLast: boolean }) {
  const showIteration = phase.state === 'active' && phase.iteration && phase.iteration > 1;
  return (
    <li className={`flow-phase flow-phase--${phase.state}`}>
      <div className="flow-phase__rail">
        <span className={`flow-phase__bullet flow-phase__bullet--${phase.state}`} aria-hidden="true" />
        {!isLast && <span className="flow-phase__connector" aria-hidden="true" />}
      </div>
      <div className="flow-phase__body">
        <header className="flow-phase__head">
          <div className="flow-phase__head-titles">
            <h4>{PHASE_LABELS[phase.phase]}</h4>
            {showIteration && phase.iterationLoopGroup && (
              <span
                className="flow-phase__iteration"
                title={`Aktuelle Iteration der ${LOOP_GROUP_LABELS[phase.iterationLoopGroup] ?? phase.iterationLoopGroup}-Gruppe.`}
              >
                <RotateCcw size={11} aria-hidden="true" />
                Runde {phase.iteration}
              </span>
            )}
          </div>
          <span className={`flow-phase__state-pill flow-phase__state-pill--${phase.state}`}>
            {PHASE_STATE_LABEL[phase.state]}
          </span>
        </header>
        {phase.stateReason && (
          <p className={`flow-phase__state-reason flow-phase__state-reason--${phase.state}`}>
            {phase.stateReason}
          </p>
        )}
        {phase.substeps.length === 0 ? (
          <p className="flow-phase__empty">Keine Substeps in diesem Modus.</p>
        ) : (
          <ul className="flow-substeps">
            {phase.substeps.map((substep, index) => {
              const prev = phase.substeps[index - 1];
              const next = phase.substeps[index + 1];
              return (
                <Fragment key={substep.substep}>
                  {isLoopStart(prev, substep) && (
                    <LoopHeaderRow
                      loopGroup={substep.loopGroup ?? 'loop'}
                      iteration={iterationForGroup(phase, substep.loopGroup)}
                    />
                  )}
                  <FlowSubstepRow substep={substep} />
                  {isLoopEnd(substep, next) && (
                    <LoopFooterRow loopGroup={substep.loopGroup ?? 'loop'} />
                  )}
                </Fragment>
              );
            })}
          </ul>
        )}
      </div>
    </li>
  );
}

function FlowSubstepRow({ substep }: { substep: FlowSubstep }) {
  const isLoopMember = Boolean(substep.loopGroup);
  const classes = [
    'flow-substep',
    `flow-substep--${substep.state}`,
    isLoopMember ? 'flow-substep--in-loop' : '',
    substep.optional ? 'flow-substep--optional' : '',
  ]
    .filter(Boolean)
    .join(' ');

  return (
    <li className={classes}>
      <span
        className={`flow-substep__marker flow-substep__marker--${substep.state}`}
        aria-hidden="true"
      />
      <span className="flow-substep__label" title={substep.substep}>
        {substepLabel(substep.substep)}
      </span>
      <span className="flow-substep__trailing">
        {substep.optional && (
          <span className="flow-substep__optional-pill" title="Wird nur bei erfüllter Vorbedingung ausgeführt.">
            optional
          </span>
        )}
        <span className={`flow-substep__state flow-substep__state--${substep.state}`}>
          {STATE_LABEL[substep.state]}
        </span>
      </span>
    </li>
  );
}

/* Loop boundary detection. */
function isLoopStart(prev: FlowSubstep | undefined, current: FlowSubstep): boolean {
  if (!current.loopGroup) return false;
  return !prev || prev.loopGroup !== current.loopGroup;
}

function isLoopEnd(current: FlowSubstep, next: FlowSubstep | undefined): boolean {
  if (!current.loopGroup) return false;
  return !next || next.loopGroup !== current.loopGroup;
}

/* Current iteration of the loop group in this phase. Only the group
 * containing the runtime substep is active; all others default to 1
 * (first pass or standard value before start). */
function iterationForGroup(phase: FlowPhase, loopGroup: string | undefined): number {
  if (!loopGroup) return 1;
  if (phase.state === 'active' && phase.iterationLoopGroup === loopGroup) {
    return phase.iteration ?? 1;
  }
  return 1;
}

function LoopHeaderRow({ loopGroup, iteration }: { loopGroup: string; iteration: number }) {
  const label = LOOP_GROUP_LABELS[loopGroup] ?? 'Loop';
  const max = LOOP_GROUP_MAX_ITERATIONS[loopGroup];
  return (
    <li className="flow-loop-marker flow-loop-marker--start" role="presentation">
      <span className="flow-loop-marker__icon" aria-hidden="true">
        <RotateCcw size={13} />
      </span>
      <span className="flow-loop-marker__label">{label}</span>
      <span className="flow-loop-marker__detail">
        Runde {iteration}
        {max !== undefined && <span className="flow-loop-marker__max"> (max {max})</span>}
      </span>
    </li>
  );
}

function LoopFooterRow({ loopGroup }: { loopGroup: string }) {
  const label = LOOP_GROUP_LABELS[loopGroup] ?? 'Loop';
  return (
    <li className="flow-loop-marker flow-loop-marker--end" role="presentation">
      <span className="flow-loop-marker__label">{label}</span>
      <span className="flow-loop-marker__detail">Ende</span>
    </li>
  );
}
