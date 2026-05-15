/*
 * PhaseStepper — horizontaler Phasen-Fortschrittsanzeiger im
 * Story-Inspector-Header.
 *
 * Zeigt alle vier Phasen der AK3-Pipeline (Setup, Exploration,
 * Implementation, Closure) als Stepper-Kette. Abgeschlossene Phasen
 * sind gruen markiert, die aktive Phase ist hervorgehoben, ausstehende
 * Phasen erscheinen gedimmt.
 *
 * Im Fast-Mode (FK-24 §24.3.3) ist die Exploration-Phase immer
 * "skipped" — sie wird als durchgestrichen/ausgegraut dargestellt
 * mit dem Tooltip-Hinweis, dass sie im Fast-Profil entfaellt.
 *
 * Basiert auf `selectStoryFlow` aus dem Store — die FlowPhase-
 * Daten kommen von dort, damit PhaseStepper und FlowTab-Ablaufansicht
 * auf derselben Logik laufen.
 */

import { Check } from 'lucide-react';
import { PHASE_LABELS, PHASE_ORDER, selectStoryFlow } from '../store';
import type { FlowState, Story } from '../store';

interface PhaseStepperProps {
  story: Story;
}

const STATE_ARIA: Record<FlowState, string> = {
  done: 'abgeschlossen',
  active: 'aktiv',
  pending: 'ausstehend',
  skipped: 'im Fast-Mode ausgelassen',
  'optional-pending': 'ausstehend',
  'optional-skipped': 'uebersprungen',
};

export function PhaseStepper({ story }: PhaseStepperProps) {
  const flow = selectStoryFlow(story);

  return (
    <nav className="phase-stepper" aria-label="Phasen-Fortschritt">
      <ol className="phase-stepper__list">
        {PHASE_ORDER.map((phase, index) => {
          const flowPhase = flow.find((fp) => fp.phase === phase);
          const state: FlowState = flowPhase?.state ?? 'pending';
          const isLast = index === PHASE_ORDER.length - 1;
          const label = PHASE_LABELS[phase];
          const ariaLabel = `Phase ${index + 1} von ${PHASE_ORDER.length}: ${label}, ${STATE_ARIA[state]}`;

          return (
            <li key={phase} className={`phase-stepper__step phase-stepper__step--${state}`}>
              <span
                className={`phase-stepper__bullet phase-stepper__bullet--${state}`}
                aria-hidden="true"
              >
                {state === 'done' && <Check size={10} strokeWidth={3} />}
              </span>
              <span
                className="phase-stepper__label"
                aria-label={ariaLabel}
                title={
                  state === 'skipped'
                    ? `${label}: im Fast-Mode ausgelassen (FK-24 §24.3.3)`
                    : `${label}: ${STATE_ARIA[state]}`
                }
              >
                {label}
              </span>
              {!isLast && (
                <span
                  className={`phase-stepper__connector phase-stepper__connector--${state}`}
                  aria-hidden="true"
                />
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
