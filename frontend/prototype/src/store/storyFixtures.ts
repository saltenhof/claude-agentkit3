/*
 * Story-Fixtures — die *eine* Story-Liste, von der alle Views leben.
 *
 * Diese Datei ersetzt die fruehere doppelte Quelle in `data.ts`
 * (`stories: Story[]` plus `rulebookStressStories`). Die Liste hier
 * ist der konsistente Mock-Datensatz; Mode und Runtime-State sind als
 * optionale Felder gepflegt, damit auch zukuenftige Sub-Step- und
 * Mode-Sichten sinnvolle Beispiele haben.
 */

import type { Mode, Phase, RuntimeState, Story, StoryStatus, Substep, SubstepMeta } from './storyModel';

type RulebookRow = [
  id: string,
  dependencies: string[],
  cluster: string,
  repo: string,
  notes?: string,
];

const rulebookRows: RulebookRow[] = [
  ['190', [], 'UC2A_STATE', 'pipeline'],
  ['191', ['BB2-190'], 'UC2A_STATE', 'pipeline'],
  ['192', ['BB2-190', 'BB2-191'], 'UC2A_GRAPH', 'pipeline'],
  ['193', ['BB2-192'], 'UC2A_CONTRACT', 'pipeline+agentframework'],
  ['194', ['BB2-192', 'BB2-193'], 'UC2A_EXTRACT', 'pipeline'],
  ['195', ['BB2-194'], 'UC2A_EXTRACT', 'pipeline'],
  ['187', ['BB2-195'], 'UC2A_EXTRACT', 'pipeline'],
  ['188', ['BB2-187'], 'UC2A_GATES', 'pipeline'],
  ['189', ['BB2-187'], 'UC2A_GATES', 'pipeline'],
  ['196', ['BB2-188', 'BB2-191'], 'UC2A_PERSIST', 'pipeline'],
  ['202', ['BB2-196'], 'UC2A_CLASSIFY', 'pipeline'],
  ['203', ['BB2-202'], 'UC2A_FORMUL', 'pipeline'],
  ['197', ['BB2-203'], 'UC2A_QS', 'pipeline'],
  ['198', ['BB2-197', 'BB2-200'], 'UC2A_REPORT', 'pipeline'],
  ['199', ['BB2-190'], 'UC2A_TEST_INFRA', 'pipeline', 'seed merges once; full bookend on BB2-198 closure'],
  ['200', [], 'SHARED_TYPST', 'pipeline'],
  ['201', ['BB2-198', 'BB2-199'], 'UC2A_GATES_E2E', 'pipeline'],
  ['204', [], 'UC2B_STATE', 'pipeline'],
  ['205', ['BB2-204'], 'UC2B_GRAPH', 'pipeline'],
  ['206', ['BB2-205'], 'UC2B_CONTRACT', 'pipeline'],
  ['207', ['BB2-205', 'BB2-206'], 'UC2B_RUNTIME', 'pipeline+agentframework'],
  ['208', ['BB2-206', 'BB2-196'], 'UC2B_EXTRACT', 'pipeline'],
  ['209', ['BB2-208'], 'UC2B_EXTRACT', 'pipeline'],
  ['210', ['BB2-209'], 'UC2B_EXTRACT', 'pipeline'],
  ['211', ['BB2-210', 'BB2-196'], 'UC2B_MATCH', 'pipeline'],
  ['212', ['BB2-211', 'BB2-202'], 'UC2B_DISPATCH', 'pipeline'],
  ['213', ['BB2-212'], 'UC2B_CHECK', 'pipeline'],
  ['214', ['BB2-212'], 'UC2B_CHECK', 'pipeline'],
  ['215', ['BB2-212', 'BB2-210'], 'UC2B_CHECK', 'pipeline'],
  ['216', ['BB2-213', 'BB2-214', 'BB2-215'], 'UC2B_AGGR', 'pipeline'],
  ['217', ['BB2-216'], 'UC2B_AGGR', 'pipeline'],
  ['218', ['BB2-216', 'BB2-217'], 'UC2B_REPORT', 'pipeline'],
  ['219', ['BB2-218'], 'UC2B_REPORT', 'pipeline'],
  ['220', ['BB2-219', 'BB2-200'], 'UC2B_REPORT', 'pipeline'],
  ['221', ['BB2-218', 'BB2-219', 'BB2-220'], 'UC2B_POST', 'pipeline'],
  ['222', ['BB2-221'], 'UC2B_TEST_INFRA', 'pipeline', 'seed-mergeable with only BB2-204; full closure requires BB2-221'],
  ['229', [], 'BE_MODELS', 'backend'],
  ['230', ['BB2-229'], 'BE_MODELS', 'backend'],
  ['231', ['BB2-229'], 'BE_PREFLIGHT', 'backend'],
  ['232', ['BB2-229', 'BB2-233'], 'BE_PREFLIGHT', 'backend'],
  ['233', ['BB2-200'], 'BE_PREFLIGHT', 'backend'],
  ['234', [], 'BE_RUNTIME', 'backend'],
  ['245', [], 'BE_EVENT', 'backend'],
  ['246', [], 'BE_TOPOLOGY', 'backend'],
  ['247', ['BB2-230'], 'BE_RULE_API', 'backend'],
  ['248', ['BB2-229'], 'BE_RULE_API', 'backend'],
  ['249', ['BB2-230'], 'BE_RULE_API', 'backend'],
  ['250', ['BB2-234', 'BB2-196', 'BB2-198'], 'BE_ARTEFACT', 'backend'],
  ['251', ['BB2-234', 'BB2-218', 'BB2-219'], 'BE_ARTEFACT', 'backend'],
  ['252', ['BB2-245', 'BB2-213'], 'BE_REALTIME', 'backend'],
  ['253', ['BB2-230'], 'BE_FILTER', 'backend'],
  ['254', ['BB2-247'], 'BE_AUDIT', 'backend'],
  ['255', ['BB2-245'], 'BE_E2E', 'backend'],
  ['256', ['BB2-250', 'BB2-251', 'BB2-252', 'BB2-254', 'BB2-255', 'BB2-222'], 'BE_E2E', 'backend'],
  ['223', [], 'FE_FOUNDATION', 'frontend'],
  ['224', [], 'FE_FOUNDATION', 'frontend'],
  ['225', [], 'FE_FOUNDATION', 'frontend'],
  ['226', ['BB2-223'], 'FE_CATALOG', 'frontend', 'DOMINANT - merges alone'],
  ['227', ['BB2-223', 'BB2-226'], 'FE_CATALOG', 'frontend'],
  ['228', ['BB2-223', 'BB2-226'], 'FE_CATALOG', 'frontend'],
  ['235', ['BB2-223', 'BB2-226'], 'FE_CATALOG', 'frontend'],
  ['236', ['BB2-223', 'BB2-226'], 'FE_CATALOG', 'frontend'],
  ['237', ['BB2-223', 'BB2-226'], 'FE_CATALOG', 'frontend'],
  ['238', ['BB2-223', 'BB2-225', 'BB2-234', 'BB2-196', 'BB2-198'], 'FE_RESULT_UC2A', 'frontend', 'BLOCKED_EXTERNAL until CC-04 section 12.2 vs PL-239 resolved'],
  ['239', ['BB2-233'], 'FE_DIALOG', 'frontend'],
  ['240', ['BB2-223', 'BB2-224', 'BB2-225', 'BB2-213'], 'FE_RESULT_UC2B', 'frontend'],
  ['241', ['BB2-223', 'BB2-225', 'BB2-218'], 'FE_RESULT_UC2B', 'frontend'],
  ['242', ['BB2-224', 'BB2-188', 'BB2-189'], 'FE_PIPE_VIEW', 'frontend'],
  ['243', ['BB2-224', 'BB2-212', 'BB2-207'], 'FE_PIPE_VIEW', 'frontend'],
  ['244', ['BB2-226', 'BB2-227', 'BB2-228', 'BB2-235', 'BB2-236', 'BB2-237', 'BB2-238', 'BB2-239', 'BB2-240', 'BB2-241', 'BB2-242', 'BB2-243'], 'FE_E2E', 'frontend'],
  ['260', ['BB2-200'], 'BE_DEMO', 'backend'],
  ['261', [], 'BE_DEMO', 'backend'],
];

const repoLabels: Record<string, string> = {
  pipeline: 'extraction-pipeline',
  agentframework: 'agent-framework',
  'pipeline+agentframework': 'extraction-pipeline + agent-framework',
  backend: 'core-api',
  frontend: 'control-tower-ui',
};

const completedCutoff = 36;
/* Hinweis: streng nach FK-24 §24.3.3 (Mode-Lock) duerften Fast und
 * Standard nicht zeitgleich In Progress sein. Im Fixture lockern wir
 * das fuer Demo-Zwecke, damit der Story-Inspector beide Mode-Profile
 * mit aktivem Substep zeigen kann. */
const inFlightStoryIds = new Set(['BB2-229', 'BB2-230', 'BB2-231', 'BB2-223', 'BB2-224']);
const approvedOverrideStoryIds = new Set(['BB2-247', 'BB2-249', 'BB2-254']);
const cancelledStoryIds = new Set(['BB2-246']);
const externallyBlockedStoryIds = new Set(['BB2-238']);

/* Mode-Verteilung: ein paar Stories laufen im Fast-Modus (FK-24).
 * Bewusst gemischt, damit die geplante Mode-Label-Anzeige Variation hat. */
const fastModeStoryIds = new Set(['BB2-224', 'BB2-247', 'BB2-260']);

/* Runtime-State pro In-Progress-Story: aktuelle Phase + Substep.
 * Verteilt ueber alle vier Phasen und unterschiedliche QA-Schichten,
 * damit die Story-Inspector- und Phase-Stepper-Sicht (AG3-019) den
 * Pipeline-Fortschritt visualisieren kann. */
const runtimeStateByStoryId: Record<string, RuntimeState> = {
  /* BB2-229: zweite Remediation-Runde, gerade in QA Layer 2. */
  'BB2-229': { phase: 'implementation', substep: 'qa_layer2_llm', iteration: 2 },
  'BB2-230': { phase: 'implementation', substep: 'incremental', iteration: 1 },
  'BB2-231': { phase: 'closure', substep: 'integrity_gate', iteration: 1 },
  /* BB2-223: dritte Design-Iteration in Exploration. */
  'BB2-223': { phase: 'exploration', substep: 'design_review', iteration: 3 },
  /* BB2-224: Fast-Mode-Story in der einzigen QA-Schicht des
   * Fast-Profils (Schicht 1, MOD = Tests-gruen-Floor). Schichten 2-4
   * existieren in Fast nicht. */
  'BB2-224': { phase: 'implementation', substep: 'qa_layer1_structural', iteration: 1 },
};

function toStoryStatus(id: string, index: number, dependencies: string[]): StoryStatus {
  if (cancelledStoryIds.has(id)) return 'Cancelled';
  if (index < completedCutoff) return 'Done';
  if (inFlightStoryIds.has(id)) return 'In Progress';
  if (approvedOverrideStoryIds.has(id)) return 'Approved';
  const completedIds = new Set(rulebookRows.slice(0, completedCutoff).map(([rowId]) => `BB2-${rowId}`));
  const depsDone = dependencies.every((dependency) => completedIds.has(dependency));
  return depsDone ? 'Approved' : 'Backlog';
}

function buildStoryFromRow(row: RulebookRow, index: number): Story {
  const [shortId, dependencies, cluster, repo, notes] = row;
  const id = `BB2-${shortId}`;
  const status = toStoryStatus(id, index, dependencies);
  const externalBlocker = externallyBlockedStoryIds.has(id);
  const participatingRepos = repo.split('+').map((item) => repoLabels[item] ?? item);
  const repoLabel = repoLabels[repo] ?? participatingRepos.join(', ');
  const wave = repo.startsWith('frontend') || repo.startsWith('backend') ? 4 : cluster.startsWith('UC2B') ? 3 : 2;
  const primaryModule = cluster.toLowerCase().replaceAll('_', '-');
  const mode: Mode = fastModeStoryIds.has(id) ? 'fast' : 'standard';
  const runtime = runtimeStateByStoryId[id];

  return {
    id,
    title: `${cluster.replaceAll('_', ' ')} execution story`,
    type: id === 'BB2-246' ? 'research' : 'implementation',
    status,
    size: index % 7 === 0 ? 'L' : index % 5 === 0 ? 'M' : 'S',
    owner: status === 'In Progress' ? `worker-${(index % 4) + 1}` : 'unassigned',
    repo: repoLabel,
    primaryRepo: participatingRepos[0],
    participatingRepos,
    module: primaryModule,
    epic: cluster.startsWith('UC2A') ? 'UC2a Pipeline' : cluster.startsWith('UC2B') ? 'UC2b Pipeline' : repo === 'backend' ? 'Backend Wave 4' : 'Frontend Wave 4',
    changeImpact: repo.includes('+') || dependencies.length > 3 ? 'Cross-Component' : dependencies.length > 1 ? 'Component' : 'Local',
    conceptQuality: index % 9 === 0 ? 'Medium' : 'High',
    wave,
    risk: externalBlocker || dependencies.length > 4 ? 'high' : dependencies.length > 1 ? 'medium' : 'low',
    blocker: externalBlocker
      ? 'BLOCKED_EXTERNAL: CC-04 section 12.2 vs PL-239 muss fachlich geklaert werden.'
      : undefined,
    criticalPath: dependencies.length > 2 || ['BB2-198', 'BB2-218', 'BB2-244', 'BB2-256'].includes(id),
    qaRounds: status === 'Done' ? 2 + (index % 2) : status === 'In Progress' ? 1 : 0,
    qaRoundsExploration: status === 'Done' && index % 4 === 0 ? 1 : 0,
    qaRoundsImplementation: status === 'Done' ? 2 + (index % 2) : status === 'In Progress' ? 1 : 0,
    processingTime: status === 'Done' ? `${70 + index * 3} min` : status === 'In Progress' ? `${35 + index} min` : '-',
    createdAt: `2026-04-${String(10 + (index % 18)).padStart(2, '0')}`,
    completedAt: status === 'Done' ? '2026-04-30' : undefined,
    labels: [cluster.toLowerCase(), repo.replace('+', '-'), `wave-${wave}`],
    need: `Belastungsprobe aus orchestrator-rulebook.dsl: ${id} gehoert zu ${cluster} im Repo-Scope ${repo}.`,
    solution: notes ?? `Story wird gemaess Dependency-Graph nach ${dependencies.length || 'keinen'} Vorgaengern eingeplant.`,
    conceptRefs: ['orchestrator-rulebook.dsl', 'FK-70 Execution Planning', 'FK-64 Control-Plane Design System'],
    guardrailRefs: ['DependencyGraphPort', 'SchedulingPolicyPort', 'atomic merge unit'],
    acceptance: [
      'Dependency-Kanten sind im Graph sichtbar',
      'Status wird aus simulierter Rulebook-Halbdurchfuehrung abgeleitet',
      'Blocker sind als operative Ableitung sichtbar',
    ],
    definitionOfDone: ['Vorgaenger erledigt', 'Merge-Window konfliktfrei', 'Story-Evidenz vorhanden'],
    gates: [
      { label: 'Dependency Graph', state: dependencies.length > 0 || externalBlocker ? 'WARNING' : 'PASS' },
      { label: 'Merge Window', state: externalBlocker ? 'ERROR' : 'PASS' },
      { label: 'Rulebook Policy', state: status === 'Cancelled' ? 'WARNING' : 'PASS' },
    ],
    phases: [
      { label: 'Setup', state: status === 'Backlog' ? 'idle' : 'done', detail: status === 'Backlog' ? 'Wartet auf Vorgaenger' : 'Rulebook-Kontext geladen' },
      { label: 'Exploration', state: 'skipped', detail: 'Stress-Datensatz aus realem Rulebook' },
      { label: 'Implementation', state: status === 'Done' ? 'done' : status === 'In Progress' ? 'active' : externalBlocker ? 'blocked' : 'idle', detail: status },
      { label: 'Verify', state: status === 'Done' ? 'done' : 'idle', detail: status === 'Done' ? 'Simuliert abgeschlossen' : 'Nicht gestartet' },
      { label: 'Closure', state: status === 'Done' ? 'done' : 'idle', detail: status === 'Done' ? 'Merged' : 'Wartend' },
    ],
    events: [
      { time: status === 'Done' ? 'Wave done' : status === 'In Progress' ? 'Now' : 'Planned', type: 'rulebook_projection', detail: `${id} aus realem UC2 Rulebook projiziert`, severity: externalBlocker ? 'warning' : 'info' },
    ],
    dependencies,
    mode,
    runtime,
  };
}

export const STORY_FIXTURES: Story[] = rulebookRows.map(buildStoryFromRow);

export interface ProjectFixture {
  key: string;
  name: string;
}

export const PROJECT_FIXTURES: ProjectFixture[] = [
  { key: 'claude-agentkit3', name: 'AgentKit 3 Core' },
  { key: 'brainbox-2', name: 'R+V Brainbox 2.0' },
  { key: 'control-tower', name: 'Control Tower' },
];

export const ACTIVE_PROJECT: ProjectFixture = PROJECT_FIXTURES[0];

export const CONCEPT_ANCHORS: string[] = [
  'FK-63: Dashboard liest analytics + runtime; Story-Cockpit vereint Status, Protokolle, Telemetrie, QA-Artefakte und Closure-Metriken.',
  'FK-70: Pflichtsicht ist der Dependency-Graph; blockierte Umsetzung wird aus Status, Abhaengigkeiten und Blocker-Kontext abgeleitet.',
  'FK-91: Offizielle API-Grenze liefert /v1/stories, /v1/planning/graph und /v1/dashboard/board.',
];

/* Phasen-/Substep-Defaults pro Phase (Sequenz aus den Phasen-FKs).
 * Wird vom Phase-Stepper / Sub-Stepper / Story-Inspector "Ablauf"-Tab
 * genutzt. */
export const PHASE_SUBSTEP_SEQUENCE: Record<Phase, Substep[]> = {
  setup: ['preflight', 'story_context', 'are_bundle', 'type_switch', 'worktree', 'guard_activation', 'mode_resolution'],
  exploration: ['worker_spawn', 'draft', 'structural_validation', 'doc_fidelity_l2', 'design_review', 'aggregation', 'feindesign', 'freeze'],
  implementation: ['worker_start', 'incremental', 'inline_reviews', 'final_build', 'handover', 'qa_layer1_structural', 'qa_layer2_llm', 'qa_layer3_adversarial', 'qa_layer4_policy', 'qa_feedback'],
  closure: ['finding_resolution', 'integrity_gate', 'branch_push', 'merge', 'main_push', 'teardown', 'story_close', 'metrics', 'doc_fidelity_l4', 'postflight', 'vectordb_sync', 'guards_off'],
};

/* Fast-Mode (FK-24 §24.3.3, AG3-018 §"Mode-Profil"):
 * Die kanonische Tabelle aus `stories/AG3-018-fast-modus/story.md`
 * markiert pro Substep IN (unveraendert), MOD (anders parametrisiert,
 * laeuft aber) oder OUT (entfaellt). Hier listen wir ausschliesslich
 * die Substeps, die im Fast-Mode tatsaechlich laufen (IN + MOD).
 * OUT-Substeps tauchen gar nicht erst auf, damit der User nicht erst
 * im Nachhinein merkt, dass etwas uebersprungen wurde.
 *
 * Quellen-Anker: AG3-018-Tabelle ab Zeile 66; siehe auch FK-24 §24.3.3,
 * FK-27 §27.4–27.7 (QA-Schichten 2–4 entfallen) und FK-29 (Closure-OUTs). */
export const PHASE_SUBSTEP_SEQUENCE_FAST: Record<Phase, Substep[]> = {
  /* OUT: are_bundle, guard_activation, mode_resolution */
  setup: ['preflight', 'story_context', 'type_switch', 'worktree'],
  /* gesamte Phase OUT */
  exploration: [],
  /* OUT: inline_reviews, qa_layer2_llm, qa_layer3_adversarial,
   *      qa_layer4_policy, qa_feedback. QA-Schicht 1 bleibt MOD
   *      (degeneriert auf Tests-gruen-Floor). */
  implementation: ['worker_start', 'incremental', 'final_build', 'handover', 'qa_layer1_structural'],
  /* OUT: finding_resolution, doc_fidelity_l4. Rest ist MOD oder IN. */
  closure: [
    'integrity_gate',
    'branch_push',
    'merge',
    'main_push',
    'teardown',
    'story_close',
    'metrics',
    'postflight',
    'vectordb_sync',
    'guards_off',
  ],
};

/* Phasen-Reihenfolge im UI-Flowchart. Fast laesst Exploration als
 * "skipped"-Phase weiterhin sichtbar (greyed), damit der Mode-Effekt
 * im Vergleich zum Standard nachvollziehbar ist. */
export const PHASE_ORDER: Phase[] = ['setup', 'exploration', 'implementation', 'closure'];

export const PHASE_LABELS: Record<Phase, string> = {
  setup: 'Setup',
  exploration: 'Exploration',
  implementation: 'Implementation',
  closure: 'Closure',
};

/* Fachliche Substep-Bezeichner fuer die UI.
 *
 * Die Keys (technische IDs aus PHASE_SUBSTEP_SEQUENCE) bleiben stabil
 * gegenueber Backend / Telemetrie; die Werte sind sprechende
 * Kurz-Bezeichner (max. 4 Worte) fuer das Story-Inspector-Flowchart. */
export const SUBSTEP_LABELS: Record<Substep, string> = {
  /* Setup */
  preflight: 'Preflight-Check',
  story_context: 'Story-Kontext laden',
  are_bundle: 'ARE-Bundle erstellen',
  type_switch: 'Story-Typ-Routing',
  worktree: 'Worktree anlegen',
  guard_activation: 'Schutz-Guards aktivieren',
  mode_resolution: 'Mode-Lock setzen',

  /* Exploration */
  worker_spawn: 'Explorations-Worker starten',
  draft: 'Entwurf erstellen',
  structural_validation: 'Strukturprüfung',
  doc_fidelity_l2: 'Konzepttreue prüfen',
  design_review: 'Design-Review',
  aggregation: 'Ergebnisse aggregieren',
  feindesign: 'Feindesign verfassen',
  freeze: 'Entwurf einfrieren',

  /* Implementation */
  worker_start: 'Worker starten',
  incremental: 'Inkrementelle Umsetzung',
  inline_reviews: 'Inline-Reviews',
  final_build: 'Final-Build',
  handover: 'Handover-Paket',
  qa_layer1_structural: 'QA Strukturprüfung',
  qa_layer2_llm: 'QA LLM-Bewertung',
  qa_layer3_adversarial: 'QA Adversarial-Tests',
  qa_layer4_policy: 'QA Policy-Aggregation',
  qa_feedback: 'QA-Feedback einarbeiten',

  /* Closure */
  finding_resolution: 'Findings auflösen',
  integrity_gate: 'Integrity-Gate',
  branch_push: 'Branch-Push',
  merge: 'Merge in Main',
  main_push: 'Main-Push',
  teardown: 'Worktree abreißen',
  story_close: 'Story schließen',
  metrics: 'Metriken erfassen',
  doc_fidelity_l4: 'Konzepttreue Final-Check',
  postflight: 'Postflight-Check',
  vectordb_sync: 'VectorDB-Sync',
  guards_off: 'Guards deaktivieren',
};

export function substepLabel(substep: Substep): string {
  return SUBSTEP_LABELS[substep] ?? substep;
}

/* Substep-Metadaten:
 * - Optionalitaet: nur dann aktiv, wenn Vorbedingung erfuellt ist
 * - Loop-Gruppen: Substeps, die mehrfach durchlaufen werden koennen
 *
 * Loop-Gruppen-IDs sind UI-stabile Tokens; das Backend wird sie spaeter
 * aus den Phase-FKs ableiten. */
export const SUBSTEP_META: Record<Substep, SubstepMeta> = {
  /* Setup -- alle Pflicht, kein Loop. `guard_activation` ist nur im
   * Fast-Mode ausgelassen, was ueber PHASE_SUBSTEP_SEQUENCE_FAST
   * abgedeckt ist. */
  preflight: {},
  story_context: {},
  are_bundle: {},
  type_switch: {},
  worktree: {},
  guard_activation: {},
  mode_resolution: {},

  /* Exploration -- Design-Iteration ist die natuerliche Loop-Gruppe
   * (Draft -> Strukturpruefung -> Konzepttreue -> Design-Review ->
   * ggfs. zurueck zum Draft). Feindesign ist optional (FK-26): nur
   * Stories mit Feindesign-Pflicht durchlaufen es. */
  worker_spawn: {},
  draft: { loopGroup: 'design_iteration' },
  structural_validation: { loopGroup: 'design_iteration' },
  doc_fidelity_l2: { loopGroup: 'design_iteration' },
  design_review: { loopGroup: 'design_iteration' },
  aggregation: {},
  feindesign: { optional: true },
  freeze: {},

  /* Implementation -- Remediation-Loop (FK-27): nach QA-Feedback geht
   * der Worker ggfs. zurueck in `incremental` und faehrt die QA-Kette
   * erneut. `inline_reviews` und `qa_feedback` sind optional (nicht
   * jede Story nutzt Inline-Reviews; QA-Feedback nur wenn Findings). */
  worker_start: {},
  incremental: { loopGroup: 'remediation' },
  inline_reviews: { optional: true, loopGroup: 'remediation' },
  final_build: { loopGroup: 'remediation' },
  handover: { loopGroup: 'remediation' },
  qa_layer1_structural: { loopGroup: 'remediation' },
  qa_layer2_llm: { loopGroup: 'remediation' },
  qa_layer3_adversarial: { loopGroup: 'remediation' },
  qa_layer4_policy: { loopGroup: 'remediation' },
  qa_feedback: { optional: true, loopGroup: 'remediation' },

  /* Closure -- `finding_resolution` nur wenn Findings vorliegen;
   * `vectordb_sync` nur, wenn die VectorDB im Projekt eingebunden ist. */
  finding_resolution: { optional: true },
  integrity_gate: {},
  branch_push: {},
  merge: {},
  main_push: {},
  teardown: {},
  story_close: {},
  metrics: {},
  doc_fidelity_l4: {},
  postflight: {},
  vectordb_sync: { optional: true },
  guards_off: {},
};

/* Lesbare Bezeichner fuer Loop-Gruppen, die im UI sichtbar werden. */
export const LOOP_GROUP_LABELS: Record<string, string> = {
  design_iteration: 'Design-Iteration',
  remediation: 'Remediation-Loop',
};

/* Konfigurierter Hard-Cap fuer Iterationen pro Loop-Gruppe. Der
 * Story-Inspector zeigt das als "max N" neben der aktuellen Runde,
 * damit klar ist, ab wann der Loop fail-closed greift. Werte sind
 * Prototyp-Defaults; das Backend wird sie spaeter aus den Phase-FKs
 * bzw. aus Project-Settings ableiten. */
export const LOOP_GROUP_MAX_ITERATIONS: Record<string, number> = {
  design_iteration: 3,
  remediation: 5,
};
