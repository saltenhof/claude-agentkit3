/*
 * FlowTab — Story-Inspector "Ablauf"-Sicht.
 *
 * Rendert die 4-Phasen-Pipeline (FK-20) als vertikale Phasen-Sequenz
 * mit Substeps. Der Sichtbau leitet sich aus dem Story-Mode ab
 * (FK-24 §24.3.3): im Fast-Mode entfaellt die Exploration komplett —
 * die Phase bleibt sichtbar, aber als "skipped" markiert.
 *
 * Zwei Effekte modelliert das Flowchart explizit:
 *
 * 1. Optionale Substeps (z. B. `feindesign`, `finding_resolution`,
 *    `vectordb_sync`, `inline_reviews`, `qa_feedback`): werden mit
 *    gestricheltem Marker, kursivem Label und einer "optional"-Pille
 *    gekennzeichnet. Nach Phase-Vorbeilauf koennen sie als
 *    `optional-skipped` (nicht ausgefuehrt) erscheinen, statt einfach
 *    `done`.
 *
 * 2. Loop-Gruppen (Exploration: `design_iteration`; Implementation:
 *    `remediation`): zusammenhaengende Substep-Sequenzen werden als
 *    Loop-Region mit Akzent-Bar links und Return-Pfeil am Loop-Ende
 *    dargestellt. Auf der aktiven Phase erscheint zusaetzlich ein
 *    "Runde N"-Badge, sobald Iteration > 1 gelaufen ist.
 */

import { Fragment } from 'react';
import { RotateCcw } from 'lucide-react';
import {
  LOOP_GROUP_LABELS,
  LOOP_GROUP_MAX_ITERATIONS,
  PHASE_LABELS,
  selectStoryFlow,
  substepLabel,
  type FlowPhase,
  type FlowState,
  type FlowSubstep,
  type Story,
} from '../store';

const STATE_LABEL: Record<FlowState, string> = {
  done: 'erledigt',
  active: 'läuft',
  pending: 'ausstehend',
  skipped: 'übersprungen',
  /* Pill rechts neben dem Label sagt bereits "optional" — das
   * State-Feld zeigt deshalb nur noch den Fortschritt. */
  'optional-pending': 'ausstehend',
  'optional-skipped': 'nicht nötig',
};

const PHASE_STATE_LABEL: Record<FlowState, string> = {
  done: 'Phase abgeschlossen',
  active: 'Phase läuft',
  pending: 'Phase ausstehend',
  skipped: 'im Fast-Mode ausgelassen',
  'optional-pending': 'optional',
  'optional-skipped': 'optional übersprungen',
};

export function FlowTab({ story }: { story: Story }) {
  const mode = story.mode ?? 'standard';
  const flow = selectStoryFlow(story);

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

/* Loop-Boundary-Detektion. */
function isLoopStart(prev: FlowSubstep | undefined, current: FlowSubstep): boolean {
  if (!current.loopGroup) return false;
  return !prev || prev.loopGroup !== current.loopGroup;
}

function isLoopEnd(current: FlowSubstep, next: FlowSubstep | undefined): boolean {
  if (!current.loopGroup) return false;
  return !next || next.loopGroup !== current.loopGroup;
}

/* Aktuelle Iteration der Loop-Gruppe in dieser Phase. Aktiv ist nur
 * die Gruppe, in der der Runtime-Substep liegt; alle anderen
 * defaulten auf 1 (Erstdurchlauf bzw. Standardwert vor Start). */
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
