/*
 * SubStepper — kompakter Substep-Fortschrittsanzeiger fuer die
 * aktive Phase im Story-Inspector-Header.
 *
 * Zeigt die Substeps der **aktiven** Phase als horizontale Chip-Reihe.
 * Die Reihenfolge entspricht `PHASE_SUBSTEP_SEQUENCE` / `_FAST`.
 *
 * Fast-Profil-Hinweise (FK-24 §24.3.3, AG3-018 §Mode-Profil):
 * - OUT-Substeps: werden ausgegraut, mit gestricheltem Rand und
 *   Tooltip "entfaellt im Fast-Modus".
 * - MOD-Substeps: erscheinen normal, tragen aber ein (mod)-Suffix
 *   und einen Tooltip "abgespeckt im Fast-Modus".
 * - IN-Substeps: unveraendert.
 *
 * Wenn keine Phase aktiv ist (Story nicht In Progress), zeigt
 * der SubStepper einen leeren / Placeholder-Zustand.
 */

import {
  PHASE_LABELS,
  PHASE_ORDER,
  PHASE_SUBSTEP_SEQUENCE,
  PHASE_SUBSTEP_SEQUENCE_FAST,
  selectStoryFlow,
  substepLabel,
} from '../store';
import type { FlowState, Mode, Phase, Story, Substep } from '../store';

/* Fast-Profil-Klassifizierung pro Substep (AG3-018 §Mode-Profil).
 * OUT = Substep entfaellt im Fast-Mode.
 * MOD = Substep laeuft abgespeckt (Delta in den Tooltips).
 * IN = unveraendert.
 *
 * Quelle: Tabelle in stories/AG3-018-fast-modus/story.md */
type FastBehavior = 'IN' | 'OUT' | 'MOD';

/* Canonical map: substep -> Fast-Verhalten.
 * Alle Substeps, die in PHASE_SUBSTEP_SEQUENCE_FAST als IN enthalten
 * sind und NICHT in PHASE_SUBSTEP_SEQUENCE_FAST fehlen, sind IN oder MOD.
 * OUT-Substeps sind genau jene, die in PHASE_SUBSTEP_SEQUENCE (Standard)
 * vorkommen, aber nicht in PHASE_SUBSTEP_SEQUENCE_FAST. */
const FAST_BEHAVIOR: Record<Substep, FastBehavior> = (() => {
  /* Setup */
  const map: Record<Substep, FastBehavior> = {
    /* Setup */
    preflight: 'MOD',            /* 4 Mindest-Checks statt 10 */
    story_context: 'IN',
    are_bundle: 'OUT',
    type_switch: 'MOD',          /* nur impl/bugfix erlaubt */
    worktree: 'IN',
    guard_activation: 'OUT',
    mode_resolution: 'OUT',
    /* Exploration — komplette Phase OUT */
    worker_spawn: 'OUT',
    draft: 'OUT',
    structural_validation: 'OUT',
    doc_fidelity_l2: 'OUT',
    design_review: 'OUT',
    aggregation: 'OUT',
    feindesign: 'OUT',
    freeze: 'OUT',
    /* Implementation */
    worker_start: 'MOD',         /* Light-Prompt */
    incremental: 'MOD',          /* kein Inkrement-Tracking */
    inline_reviews: 'OUT',
    final_build: 'MOD',          /* Tests gruen — harter Pflicht-Floor */
    handover: 'MOD',             /* nur Worker-Manifest */
    qa_layer1_structural: 'MOD', /* degeneriert auf Tests-gruen-Floor */
    qa_layer2_llm: 'OUT',
    qa_layer3_adversarial: 'OUT',
    qa_layer4_policy: 'OUT',
    qa_feedback: 'OUT',
    /* Closure */
    finding_resolution: 'OUT',
    integrity_gate: 'MOD',       /* Sanity-Gate statt vollem Integrity-Gate */
    branch_push: 'IN',
    merge: 'MOD',                /* Pre-Merge-Rebase statt Lock */
    main_push: 'IN',
    teardown: 'IN',
    story_close: 'IN',
    metrics: 'MOD',              /* mode=fast getaggt */
    doc_fidelity_l4: 'OUT',
    postflight: 'MOD',           /* nur Hard-Failures */
    vectordb_sync: 'IN',
    guards_off: 'MOD',           /* no-op, keine Locks aktiv */
  };
  return map;
})();

const MOD_DETAIL: Record<Substep, string> = {
  preflight: '4 Mindest-Checks statt 10 (story_exists, kein aktiver Run, kein staler Worktree, Mode-Konflikt)',
  type_switch: 'Nur impl/bugfix erlaubt; concept/research -> Fail-Closed',
  worker_start: 'Light-Prompt: keine Inkrement-/Review-Pflicht',
  incremental: 'Worker-frei, kein Inkrement-Tracking',
  final_build: 'Tests gruen — harter Pflicht-Floor, nicht abschaltbar',
  handover: 'Nur Worker-Manifest; keine QA-Artefakte',
  qa_layer1_structural: 'Degeneriert auf Tests-gruen-Floor',
  integrity_gate: 'Sanity-Gate: Tests gruen, Worktree clean, Pre-Merge-Rebase OK',
  merge: 'Pre-Merge-Rebase auf main statt Lock; bei Konflikt Eskalation an User',
  metrics: 'Records mit mode=fast getaggt; KPI separat aggregierbar',
  postflight: 'Nur Hard-Failures (Branch-Reste, offene Worktrees)',
  guards_off: 'no-op: keine Story-scoped Locks aktiv',
  /* Alle anderen MOD-Substeps bekommen einen generischen Hinweis
   * (Fallback im Code unten). Restliche sind IN oder OUT. */
  story_context: '',
  worktree: '',
  worker_spawn: '',
  draft: '',
  structural_validation: '',
  doc_fidelity_l2: '',
  design_review: '',
  aggregation: '',
  feindesign: '',
  freeze: '',
  are_bundle: '',
  guard_activation: '',
  mode_resolution: '',
  inline_reviews: '',
  qa_layer2_llm: '',
  qa_layer3_adversarial: '',
  qa_layer4_policy: '',
  qa_feedback: '',
  finding_resolution: '',
  branch_push: '',
  main_push: '',
  teardown: '',
  story_close: '',
  doc_fidelity_l4: '',
  vectordb_sync: '',
};

interface SubStepperProps {
  story: Story;
}

export function SubStepper({ story }: SubStepperProps) {
  const mode: Mode = story.mode ?? 'standard';
  const flow = selectStoryFlow(story);

  /* Aktive Phase bestimmen */
  const activeFlowPhase = flow.find((fp) => fp.state === 'active');
  const activePhase: Phase | null = activeFlowPhase?.phase ?? null;

  if (!activePhase) {
    /* Story ist nicht aktiv (Backlog/Approved/Done/Cancelled) */
    const noActiveLabel =
      story.status === 'Done'
        ? 'Alle Phasen abgeschlossen'
        : story.status === 'Cancelled'
          ? 'Story abgebrochen'
          : 'Story noch nicht gestartet';
    return (
      <div className="sub-stepper sub-stepper--inactive" aria-label="Substep-Fortschritt">
        <span className="sub-stepper__empty">{noActiveLabel}</span>
      </div>
    );
  }

  /* Substep-Sequenz fuer aktive Phase und Mode */
  const stdSequence = PHASE_SUBSTEP_SEQUENCE[activePhase];
  const fastSequence = PHASE_SUBSTEP_SEQUENCE_FAST[activePhase];

  /* Im Standard-Mode: die normalen Substeps. Im Fast-Mode: alle
   * Substeps der Standard-Sequenz zeigen (auch OUTs, aber ausgegraut),
   * damit der User sieht, was im Fast-Profil entfaellt. */
  const displaySequence = stdSequence;

  /* Aktiven Substep aus Flow ermitteln */
  const activeSubstep = activeFlowPhase?.substeps.find((s) => s.state === 'active')?.substep ?? null;

  return (
    <div className="sub-stepper" aria-label={`Substep-Fortschritt: ${PHASE_LABELS[activePhase]}`}>
      <span className="sub-stepper__phase-label">{PHASE_LABELS[activePhase]}</span>
      <ol className="sub-stepper__list">
        {displaySequence.map((substep) => {
          /* State aus FlowTab-Logik lesen */
          const flowSubstep = activeFlowPhase?.substeps.find((s) => s.substep === substep);
          const state: FlowState = flowSubstep?.state ?? 'pending';

          /* Fast-Profil-Klassifizierung */
          const fastBehavior: FastBehavior = mode === 'fast'
            ? (FAST_BEHAVIOR[substep] ?? 'IN')
            : 'IN';
          const isOutInFast = fastBehavior === 'OUT';
          const isModInFast = fastBehavior === 'MOD';

          /* Im Fast-Mode: OUTs sind nie aktiv — sie sind immer "skipped"
           * im Flow. Falls sie dennoch in der Standardsequenz stehen,
           * zeigen wir sie als ausgegraut. */
          const inFastSequence = mode !== 'fast' || fastSequence.includes(substep);

          const tooltip = buildTooltip(substep, fastBehavior, mode);
          const label = substepLabel(substep);
          const isActive = state === 'active';
          const isDone = state === 'done';

          const classes = [
            'sub-stepper__step',
            `sub-stepper__step--${state}`,
            isOutInFast && !inFastSequence ? 'sub-stepper__step--fast-out' : '',
            isModInFast ? 'sub-stepper__step--fast-mod' : '',
            isActive ? 'sub-stepper__step--current' : '',
          ]
            .filter(Boolean)
            .join(' ');

          return (
            <li
              key={substep}
              className={classes}
              title={tooltip}
              aria-label={`${label}: ${state}${isOutInFast && !inFastSequence ? ' (entfaellt im Fast-Modus)' : ''}${isModInFast ? ' (abgespeckt im Fast-Modus)' : ''}`}
            >
              <span
                className={`sub-stepper__dot sub-stepper__dot--${isDone ? 'done' : isActive ? 'active' : isOutInFast && !inFastSequence ? 'out' : 'pending'}`}
                aria-hidden="true"
              />
              <span className="sub-stepper__chip-label">
                {label}
                {isModInFast && (
                  <span className="sub-stepper__mod-pill" aria-hidden="true">
                    mod
                  </span>
                )}
              </span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

function buildTooltip(substep: Substep, behavior: FastBehavior, mode: Mode): string {
  const label = substepLabel(substep);
  if (mode !== 'fast') return label;
  if (behavior === 'OUT') return `${label}: entfaellt im Fast-Modus (FK-24 §24.3.3)`;
  if (behavior === 'MOD') {
    const detail = MOD_DETAIL[substep];
    return detail
      ? `${label}: abgespeckt im Fast-Modus — ${detail}`
      : `${label}: abgespeckt im Fast-Modus`;
  }
  return label;
}
