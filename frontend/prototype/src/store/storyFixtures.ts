/*
 * Story fixtures — the *single* story list all views live off.
 *
 * This file replaces the former duplicate source in `data.ts`
 * (`stories: Story[]` plus `rulebookStressStories`). The list here
 * is the consistent mock dataset; mode and runtime state are maintained
 * as optional fields so that future substep and mode views have
 * meaningful examples.
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
/* Note: strictly per FK-24 §24.3.3 (Mode-Lock), Fast and Standard
 * must not be In Progress simultaneously. In the fixture we relax
 * this for demo purposes so the Story Inspector can show both mode
 * profiles with an active substep. */
const inFlightStoryIds = new Set(['BB2-229', 'BB2-230', 'BB2-231', 'BB2-223', 'BB2-224']);
const approvedOverrideStoryIds = new Set(['BB2-247', 'BB2-249', 'BB2-254']);
const cancelledStoryIds = new Set(['BB2-246']);
const externallyBlockedStoryIds = new Set(['BB2-238']);

/* Mode distribution: a few stories run in Fast mode (FK-24).
 * Intentionally mixed so the planned mode-label display has variation. */
const fastModeStoryIds = new Set(['BB2-224', 'BB2-247', 'BB2-260']);

/* Runtime state per in-progress story: current phase + substep.
 * Spread across all four phases and different QA layers so that
 * the Story Inspector and phase stepper view (AG3-019) can
 * visualize pipeline progress. */
const runtimeStateByStoryId: Record<string, RuntimeState> = {
  /* BB2-229: second remediation round, currently in QA Layer 2. */
  'BB2-229': { phase: 'implementation', substep: 'qa_layer2_llm', iteration: 2 },
  'BB2-230': { phase: 'implementation', substep: 'incremental', iteration: 1 },
  'BB2-231': { phase: 'closure', substep: 'integrity_gate', iteration: 1 },
  /* BB2-223: third design iteration in Exploration. */
  'BB2-223': { phase: 'exploration', substep: 'design_review', iteration: 3 },
  /* BB2-224: Fast-mode story in the only QA layer of the Fast
   * profile (Layer 1, MOD = tests-green floor). Layers 2-4
   * do not exist in Fast mode. */
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
      ? 'BLOCKED_EXTERNAL: CC-04 section 12.2 vs PL-239 must be resolved at domain level.'
      : undefined,
    criticalPath: dependencies.length > 2 || ['BB2-198', 'BB2-218', 'BB2-244', 'BB2-256'].includes(id),
    qaRounds: status === 'Done' ? 2 + (index % 2) : status === 'In Progress' ? 1 : 0,
    qaRoundsExploration: status === 'Done' && index % 4 === 0 ? 1 : 0,
    qaRoundsImplementation: status === 'Done' ? 2 + (index % 2) : status === 'In Progress' ? 1 : 0,
    processingTime: status === 'Done' ? `${70 + index * 3} min` : status === 'In Progress' ? `${35 + index} min` : '-',
    createdAt: `2026-04-${String(10 + (index % 18)).padStart(2, '0')}`,
    completedAt: status === 'Done' ? '2026-04-30' : undefined,
    labels: [cluster.toLowerCase(), repo.replace('+', '-'), `wave-${wave}`],
    need: `Stress test from orchestrator-rulebook.dsl: ${id} belongs to ${cluster} in repo scope ${repo}.`,
    solution: notes ?? `Story scheduled per dependency graph after ${dependencies.length || 'no'} predecessors.`,
    conceptRefs: ['orchestrator-rulebook.dsl', 'FK-70 Execution Planning', 'FK-64 Control-Plane Design System'],
    guardrailRefs: ['DependencyGraphPort', 'SchedulingPolicyPort', 'atomic merge unit'],
    acceptance: [
      'Dependency edges are visible in the graph',
      'Status is derived from a simulated rulebook partial run',
      'Blockers are visible as an operational derivation',
    ],
    definitionOfDone: ['Predecessors done', 'Merge window conflict-free', 'Story evidence present'],
    gates: [
      { label: 'Dependency Graph', state: dependencies.length > 0 || externalBlocker ? 'WARNING' : 'PASS' },
      { label: 'Merge Window', state: externalBlocker ? 'ERROR' : 'PASS' },
      { label: 'Rulebook Policy', state: status === 'Cancelled' ? 'WARNING' : 'PASS' },
    ],
    phases: [
      { label: 'Setup', state: status === 'Backlog' ? 'idle' : 'done', detail: status === 'Backlog' ? 'Waiting for predecessors' : 'Rulebook context loaded' },
      { label: 'Exploration', state: 'skipped', detail: 'Stress dataset from real rulebook' },
      { label: 'Implementation', state: status === 'Done' ? 'done' : status === 'In Progress' ? 'active' : externalBlocker ? 'blocked' : 'idle', detail: status },
      { label: 'Verify', state: status === 'Done' ? 'done' : 'idle', detail: status === 'Done' ? 'Simulated complete' : 'Not started' },
      { label: 'Closure', state: status === 'Done' ? 'done' : 'idle', detail: status === 'Done' ? 'Merged' : 'Waiting' },
    ],
    events: [
      { time: status === 'Done' ? 'Wave done' : status === 'In Progress' ? 'Now' : 'Planned', type: 'rulebook_projection', detail: `${id} projected from real UC2 rulebook`, severity: externalBlocker ? 'warning' : 'info' },
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
  'FK-63: Dashboard reads analytics + runtime; Story Cockpit unifies status, logs, telemetry, QA artifacts and closure metrics.',
  'FK-70: Mandatory view is the dependency graph; blocked execution is derived from status, dependencies and blocker context.',
  'FK-91: Official API boundary exposes /v1/stories, /v1/planning/graph and /v1/dashboard/board.',
];

/* Phase/substep defaults per phase (sequence from the phase FKs).
 * Used by the phase stepper / sub-stepper / Story Inspector "Ablauf" tab. */
export const PHASE_SUBSTEP_SEQUENCE: Record<Phase, Substep[]> = {
  setup: ['preflight', 'story_context', 'are_bundle', 'type_switch', 'worktree', 'guard_activation', 'mode_resolution'],
  exploration: ['worker_spawn', 'draft', 'structural_validation', 'doc_fidelity_l2', 'design_review', 'aggregation', 'feindesign', 'freeze'],
  implementation: ['worker_start', 'incremental', 'inline_reviews', 'final_build', 'handover', 'qa_layer1_structural', 'qa_layer2_llm', 'qa_layer3_adversarial', 'qa_layer4_policy', 'qa_feedback'],
  closure: ['finding_resolution', 'integrity_gate', 'branch_push', 'merge', 'main_push', 'teardown', 'story_close', 'metrics', 'doc_fidelity_l4', 'postflight', 'vectordb_sync', 'guards_off'],
};

/* Fast mode (FK-24 §24.3.3, AG3-018 §"Mode profile"):
 * The canonical table from `stories/AG3-018-fast-modus/story.md`
 * marks each substep as IN (unchanged), MOD (differently parameterized
 * but still runs) or OUT (dropped). Here we list only the substeps
 * that actually run in Fast mode (IN + MOD). OUT substeps are omitted
 * entirely so the user does not discover after the fact that something
 * was skipped.
 *
 * Source anchor: AG3-018 table from line 66; see also FK-24 §24.3.3,
 * FK-27 §27.4–27.7 (QA layers 2–4 dropped) and FK-29 (closure OUTs). */
export const PHASE_SUBSTEP_SEQUENCE_FAST: Record<Phase, Substep[]> = {
  /* OUT: are_bundle, guard_activation, mode_resolution -- dropped in Fast mode */
  setup: ['preflight', 'story_context', 'type_switch', 'worktree'],
  /* entire phase OUT in Fast mode */
  exploration: [],
  /* OUT: inline_reviews, qa_layer2_llm, qa_layer3_adversarial,
   *      qa_layer4_policy, qa_feedback. QA layer 1 remains MOD
   *      (degenerates to tests-green floor). */
  implementation: ['worker_start', 'incremental', 'final_build', 'handover', 'qa_layer1_structural'],
  /* OUT: finding_resolution, doc_fidelity_l4. Remainder is MOD or IN. */
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

/* Phase order in the UI flowchart. Fast mode keeps Exploration visible
 * as a "skipped" phase (greyed) so the mode effect is comparable
 * to standard mode. */
export const PHASE_ORDER: Phase[] = ['setup', 'exploration', 'implementation', 'closure'];

export const PHASE_LABELS: Record<Phase, string> = {
  setup: 'Setup',
  exploration: 'Exploration',
  implementation: 'Implementation',
  closure: 'Closure',
};

/* Domain substep labels for the UI.
 *
 * Keys (technical IDs from PHASE_SUBSTEP_SEQUENCE) remain stable
 * with respect to the backend / telemetry; values are human-readable
 * short labels (max. 4 words) for the Story Inspector flowchart. */
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

/* Substep metadata:
 * - Optionality: only active when a precondition is met
 * - Loop groups: substeps that may be traversed multiple times
 *
 * Loop group IDs are UI-stable tokens; the backend will derive them
 * from the phase FKs later. */
export const SUBSTEP_META: Record<Substep, SubstepMeta> = {
  /* Setup -- all mandatory, no loop. `guard_activation` is only
   * omitted in Fast mode, which is covered via PHASE_SUBSTEP_SEQUENCE_FAST. */
  preflight: {},
  story_context: {},
  are_bundle: {},
  type_switch: {},
  worktree: {},
  guard_activation: {},
  mode_resolution: {},

  /* Exploration -- design iteration is the natural loop group
   * (Draft -> structural validation -> doc fidelity -> design review ->
   * optionally back to draft). Fine design is optional (FK-26): only
   * stories that require detailed design go through it. */
  worker_spawn: {},
  draft: { loopGroup: 'design_iteration' },
  structural_validation: { loopGroup: 'design_iteration' },
  doc_fidelity_l2: { loopGroup: 'design_iteration' },
  design_review: { loopGroup: 'design_iteration' },
  aggregation: {},
  feindesign: { optional: true },
  freeze: {},

  /* Implementation -- remediation loop (FK-27): after QA feedback the
   * worker optionally returns to `incremental` and re-runs the QA chain.
   * `inline_reviews` and `qa_feedback` are optional (not every story
   * uses inline reviews; QA feedback only when findings exist). */
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

  /* Closure -- `finding_resolution` only when findings exist;
   * `vectordb_sync` only when the VectorDB is enabled for the project. */
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

/* Human-readable labels for loop groups shown in the UI. */
export const LOOP_GROUP_LABELS: Record<string, string> = {
  design_iteration: 'Design-Iteration',
  remediation: 'Remediation-Loop',
};

/* Configured hard cap for iterations per loop group. The Story
 * Inspector displays this as "max N" next to the current round so
 * it is clear when the loop fails closed. Values are prototype
 * defaults; the backend will derive them from the phase FKs or
 * project settings later. */
export const LOOP_GROUP_MAX_ITERATIONS: Record<string, number> = {
  design_iteration: 3,
  remediation: 5,
};
