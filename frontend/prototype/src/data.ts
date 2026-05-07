export type StoryStatus = 'Backlog' | 'Approved' | 'In Progress' | 'Done' | 'Cancelled';
export type StoryType = 'implementation' | 'bugfix' | 'concept' | 'research';
export type PhaseStatus = 'done' | 'active' | 'blocked' | 'idle' | 'skipped';
export type ChangeImpact = 'Local' | 'Component' | 'Cross-Component' | 'Architecture Impact';
export type ConceptQuality = 'High' | 'Medium' | 'Low';

export interface Story {
  id: string;
  title: string;
  type: StoryType;
  status: StoryStatus;
  size: 'XS' | 'S' | 'M' | 'L' | 'XL' | 'XXL';
  owner: string;
  repo: string;
  primaryRepo?: string;
  participatingRepos?: string[];
  module: string;
  epic: string;
  changeImpact: ChangeImpact;
  conceptQuality: ConceptQuality;
  wave: number;
  risk: 'low' | 'medium' | 'high';
  blocker?: string;
  criticalPath: boolean;
  qaRounds: number;
  qaRoundsExploration?: number;
  qaRoundsImplementation?: number;
  processingTime: string;
  createdAt?: string;
  completedAt?: string;
  labels: string[];
  acceptance: string[];
  need?: string;
  solution?: string;
  conceptRefs?: string[];
  guardrailRefs?: string[];
  externalSources?: string[];
  definitionOfDone?: string[];
  evidence?: {
    qaCycleId: string;
    qaCycleRound: number;
    evidenceEpoch: string;
    evidenceFingerprint: string;
    manifestHash: string;
    bundleEntries: Array<{ authority: 'STORY_SPEC' | 'CONCEPT' | 'GUARDRAIL' | 'DIFF' | 'HANDOVER' | 'SECONDARY_CONTEXT'; path: string; status: 'INCLUDED' | 'REQUESTED' | 'UNRESOLVED' }>;
  };
  telemetry?: {
    runId: string;
    agentStarts: number;
    incrementCommits: number;
    reviewRequests: number;
    reviewResponses: number;
    reviewCompliant: number;
    llmCalls: number;
    adversarialTests: number;
    webCalls: number;
    tokensIn: number;
    tokensOut: number;
    pools: Array<{ pool: 'chatgpt' | 'gemini' | 'grok' | 'qwen'; role: string; calls: number; status: 'PASS' | 'WARNING' | 'FAIL' }>;
  };
  gates: Array<{ label: string; state: 'PASS' | 'WARNING' | 'ERROR' }>;
  phases: Array<{ label: string; state: PhaseStatus; detail: string }>;
  events: Array<{ time: string; type: string; detail: string; severity: 'info' | 'warning' | 'error' }>;
  dependencies: string[];
}

export const project = {
  key: 'claude-agentkit3',
  name: 'AgentKit 3 Core',
};

export const projects = [
  project,
  { key: 'brainbox-2', name: 'R+V Brainbox 2.0' },
  { key: 'control-tower', name: 'Control Tower' },
];

export const stories: Story[] = [
  {
    id: 'AK3-118',
    title: 'Control-Plane Story API stabilisieren',
    type: 'implementation',
    status: 'In Progress',
    size: 'L',
    owner: 'worker-2',
    repo: 'core-api',
    module: 'control-plane',
    epic: 'Central Control Plane',
    changeImpact: 'Architecture Impact',
    conceptQuality: 'High',
    wave: 1,
    risk: 'high',
    criticalPath: true,
    qaRounds: 2,
    processingTime: '142 min',
    labels: ['api', 'story-lifecycle', 'runtime'],
    need: 'Die zentrale Control-Plane braucht eine kanonische Story-API, damit Web-UI, CLI und Project Edge Client keine zweite Story-Wahrheit erzeugen.',
    solution: 'REST-Endpunkte fuer Story-Liste, Story-Detail und Status-Transitions werden als tenant-scoped API-Vertrag stabilisiert und mit op_id/correlation_id abgesichert.',
    conceptRefs: ['FK-91 API- und Event-Katalog', 'FK-63 Story Cockpit', 'FK-56 Operating Modes'],
    guardrailRefs: ['ARCH-API-BOUNDARY', 'P-INTEGRITY-V1', 'ZERO-DEBT'],
    externalSources: ['GitHub Project V2 Adaptervertrag'],
    acceptance: [
      'Mutierende Story-Endpunkte liefern correlation_id und op_id',
      'Story-Detail ist projektgebunden lesbar',
      'Fehlerantworten folgen stabilem Fehlervertrag',
    ],
    definitionOfDone: ['Build kompiliert', 'API-Contract-Tests gruen', 'Keine Secrets im Diff', 'Akzeptanzkriterien nachweislich erfuellt'],
    evidence: {
      qaCycleId: '9f3a2c71d0b4',
      qaCycleRound: 2,
      evidenceEpoch: '2026-05-01T10:21:34+02:00',
      evidenceFingerprint: 'sha256:8a7c2b...d91f',
      manifestHash: 'mfst:3b51a9',
      bundleEntries: [
        { authority: 'STORY_SPEC', path: 'stories/AK3-118/story.md', status: 'INCLUDED' },
        { authority: 'CONCEPT', path: 'concept/technical-design/91_api_event_katalog.md', status: 'INCLUDED' },
        { authority: 'DIFF', path: 'src/agentkit/control_plane/http.py', status: 'INCLUDED' },
        { authority: 'SECONDARY_CONTEXT', path: 'src/agentkit/story_context_manager/', status: 'REQUESTED' },
      ],
    },
    telemetry: {
      runId: 'run-8f41e2d4',
      agentStarts: 1,
      incrementCommits: 4,
      reviewRequests: 6,
      reviewResponses: 5,
      reviewCompliant: 6,
      llmCalls: 7,
      adversarialTests: 3,
      webCalls: 0,
      tokensIn: 183200,
      tokensOut: 24600,
      pools: [
        { pool: 'chatgpt', role: 'qa_review', calls: 2, status: 'PASS' },
        { pool: 'gemini', role: 'semantic_review', calls: 2, status: 'WARNING' },
        { pool: 'qwen', role: 'doc_fidelity', calls: 2, status: 'PASS' },
        { pool: 'grok', role: 'adversarial_sparring', calls: 1, status: 'PASS' },
      ],
    },
    gates: [
      { label: 'Integrity Gate', state: 'PASS' },
      { label: 'Policy Engine', state: 'WARNING' },
      { label: 'Sonar', state: 'PASS' },
    ],
    phases: [
      { label: 'Setup', state: 'done', detail: 'StoryContext und Edge-Bundle erzeugt' },
      { label: 'Exploration', state: 'skipped', detail: 'Implementation-Story mit stabilem Scope' },
      { label: 'Implementation', state: 'done', detail: '4 Inkremente, Handover vorhanden' },
      { label: 'Verify', state: 'active', detail: 'Layer 2 LLM-Evaluations laufen' },
      { label: 'Closure', state: 'idle', detail: 'Wartet auf Verify PASS' },
    ],
    events: [
      { time: '09:04', type: 'agent_start', detail: 'worker-2 gestartet', severity: 'info' },
      { time: '09:48', type: 'increment_commit', detail: 'API contract tests ergaenzt', severity: 'info' },
      { time: '10:21', type: 'llm_call', detail: 'semantic_review: WARNING', severity: 'warning' },
    ],
    dependencies: ['AK3-101', 'AK3-111'],
  },
  {
    id: 'AK3-121',
    title: 'Story-Cockpit Read Model fuer Board',
    type: 'implementation',
    status: 'Approved',
    size: 'M',
    owner: 'unassigned',
    repo: 'dashboard',
    module: 'kpi_analytics_engine',
    epic: 'AK3 Story Cockpit',
    changeImpact: 'Component',
    conceptQuality: 'Medium',
    wave: 1,
    risk: 'medium',
    criticalPath: true,
    qaRounds: 0,
    processingTime: '-',
    labels: ['dashboard', 'read-model', 'board'],
    need: 'Das Story Cockpit braucht ein Read Model, das Board, Sheet, Detail und Planning-Sichten konsistent aus Runtime- und Analytics-Daten speist.',
    solution: 'Ein dashboard/board Read Model stellt Status, Custom Fields, Metriken und Planungsattribute projektgebunden bereit.',
    conceptRefs: ['FK-63 Dashboard', 'FK-70 Execution Planning', 'FK-69 story_metrics'],
    guardrailRefs: ['tenant-scoped queries', 'valid runs only'],
    acceptance: [
      'Board-Read-Model liefert Status, Owner, Type, Size und Metriken',
      'Story-Karten verlinken auf Detailansicht',
    ],
    definitionOfDone: ['Story-Liste filterbar', 'Board und Sheet nutzen dieselbe Projektion', 'Reset-Runs bleiben unsichtbar'],
    gates: [
      { label: 'Story Contract', state: 'PASS' },
      { label: 'Dependency Graph', state: 'PASS' },
      { label: 'Scope Coverage', state: 'PASS' },
    ],
    phases: [
      { label: 'Setup', state: 'idle', detail: 'Noch nicht gestartet' },
      { label: 'Exploration', state: 'idle', detail: 'Optional bei Scope-Drift' },
      { label: 'Implementation', state: 'idle', detail: 'Bereit fuer Wave 1' },
      { label: 'Verify', state: 'idle', detail: 'Wartend' },
      { label: 'Closure', state: 'idle', detail: 'Wartend' },
    ],
    events: [
      { time: '08:31', type: 'planning_recompute', detail: 'READY nach FK-70 Graph-Pruefung', severity: 'info' },
    ],
    dependencies: [],
  },
  {
    id: 'AK3-122',
    title: 'Story Sheet Gruppierung und Inline-Editing',
    type: 'implementation',
    status: 'Approved',
    size: 'M',
    owner: 'worker-4',
    repo: 'dashboard',
    module: 'story_sheet',
    epic: 'AK3 Story Cockpit',
    changeImpact: 'Component',
    conceptQuality: 'High',
    wave: 1,
    risk: 'medium',
    criticalPath: false,
    qaRounds: 0,
    processingTime: '-',
    labels: ['dashboard', 'sheet', 'inline-editing'],
    need: 'Die Sheet-Ansicht muss Stories nach Epic gruppieren und Massenpflege ohne Wechsel in Detailseiten erlauben.',
    solution: 'Gruppenheader, Add-Item-Zeilen, sortierbare Spalten und Inline-Editoren werden auf dasselbe Story-Read-Model gelegt.',
    conceptRefs: ['FK-64 Control-Plane Design System', 'FK-63 Dashboard', 'FK-70 Execution Planning'],
    guardrailRefs: ['tenant-scoped queries', 'FK-64 Sheet-Konformitaet'],
    acceptance: [
      'Epic-Gruppen zeigen mehrere Stories als zusammenhaengenden Block',
      'Editierbare Zellen lassen sich inline bearbeiten',
      'Story-ID und Titel verwenden dieselbe Identity-Typografie',
    ],
    definitionOfDone: ['Sheet-Gruppierung sichtbar', 'Inline-Editing bleibt bedienbar', 'FK-64 Typografie eingehalten'],
    gates: [
      { label: 'Design System', state: 'PASS' },
      { label: 'Read Model', state: 'PASS' },
      { label: 'UX Review', state: 'WARNING' },
    ],
    phases: [
      { label: 'Setup', state: 'idle', detail: 'StoryContext bereit' },
      { label: 'Exploration', state: 'skipped', detail: 'UI-Verhalten fachlich festgelegt' },
      { label: 'Implementation', state: 'idle', detail: 'Bereit fuer Umsetzung' },
      { label: 'Verify', state: 'idle', detail: 'Wartend' },
      { label: 'Closure', state: 'idle', detail: 'Wartend' },
    ],
    events: [
      { time: '10:42', type: 'planning_recompute', detail: 'Epic-Gruppe AK3 Story Cockpit erweitert', severity: 'info' },
    ],
    dependencies: ['AK3-101'],
  },
  {
    id: 'AK3-123',
    title: 'Story Inspector Tabs fuer Spezifikation, Ergebnis und KPIs',
    type: 'implementation',
    status: 'In Progress',
    size: 'S',
    owner: 'worker-2',
    repo: 'dashboard',
    module: 'story_inspector',
    epic: 'AK3 Story Cockpit',
    changeImpact: 'Local',
    conceptQuality: 'High',
    wave: 1,
    risk: 'low',
    criticalPath: false,
    qaRounds: 1,
    processingTime: '48 min',
    labels: ['dashboard', 'inspector', 'tabs'],
    need: 'Story-Details muessen normatives Story-Material, Review-Evidenz und Telemetrie getrennt aber in einem Arbeitskontext zeigen.',
    solution: 'Der Inspector nutzt drei abgeschraegte Tabs und aktualisiert sich beim Durchklicken der Story-Auswahl ohne modalen Blur.',
    conceptRefs: ['FK-64 Story Inspector', 'FK-27 Verify Pipeline', 'FK-68 Telemetrie'],
    guardrailRefs: ['non-modal inspector', 'keyboard navigation'],
    acceptance: [
      'Spezifikation, Ergebnis und KPIs sind getrennte Tabs',
      'Arrow Up/Down aktualisiert die aktive Story',
      'Der Inspector schliesst nur bei Klick ausserhalb von Story oder Panel',
    ],
    definitionOfDone: ['Tabs nach FK-64 umgesetzt', 'Nicht-modales Durchklicken funktioniert', 'Detaildaten bleiben konsistent'],
    gates: [
      { label: 'UX Review', state: 'PASS' },
      { label: 'Accessibility', state: 'WARNING' },
      { label: 'Telemetry Mapping', state: 'PASS' },
    ],
    phases: [
      { label: 'Setup', state: 'done', detail: 'StoryContext geladen' },
      { label: 'Exploration', state: 'skipped', detail: 'UI-Konzept aus FK-64' },
      { label: 'Implementation', state: 'done', detail: 'Tabs und Resize-Verhalten umgesetzt' },
      { label: 'Verify', state: 'active', detail: 'Review laeuft' },
      { label: 'Closure', state: 'idle', detail: 'Wartet auf Review' },
    ],
    events: [
      { time: '11:06', type: 'review_request', detail: 'Inspector-Tab-Verhalten zur UX-Pruefung gegeben', severity: 'info' },
      { time: '11:18', type: 'review_response', detail: 'Accessibility-Hinweis offen', severity: 'warning' },
    ],
    dependencies: ['AK3-121', 'AK3-122'],
  },
  {
    id: 'AK3-124',
    title: 'Dependency-Graph Story-Auswahl mit Sheet-Synchronisierung',
    type: 'implementation',
    status: 'Backlog',
    size: 'L',
    owner: 'unassigned',
    repo: 'dashboard',
    module: 'dependency_graph',
    epic: 'AK3 Story Cockpit',
    changeImpact: 'Cross-Component',
    conceptQuality: 'Medium',
    wave: 2,
    risk: 'medium',
    criticalPath: false,
    qaRounds: 0,
    processingTime: '-',
    labels: ['dashboard', 'xyflow', 'planning'],
    need: 'Graph, Sheet und Detailpanel sollen dieselbe Story-Auswahl verwenden, damit Planungs- und Tabellenarbeit nicht auseinanderlaufen.',
    solution: 'XYFlow-Node-Auswahl, Sheet-Zeilenauswahl und Inspector-Zustand werden ueber denselben Story-State synchronisiert.',
    conceptRefs: ['FK-64 Dependency-Graph', 'FK-70 Execution Planning', 'FK-63 Story Cockpit'],
    guardrailRefs: ['single selection state', 'planning view consistency'],
    acceptance: [
      'Klick auf Graph-Node selektiert dieselbe Story wie im Sheet',
      'Sheet-Klick aktualisiert Inspector und Graph-Auswahl',
      'Dependency-Edges bleiben trotz Filterung lesbar',
    ],
    definitionOfDone: ['Auswahlzustand vereinheitlicht', 'Graph bleibt interaktiv', 'Sheet und Inspector bleiben synchron'],
    gates: [
      { label: 'Dependency Graph', state: 'WARNING' },
      { label: 'Design System', state: 'PASS' },
      { label: 'Selection Sync', state: 'WARNING' },
    ],
    phases: [
      { label: 'Setup', state: 'idle', detail: 'Noch nicht gestartet' },
      { label: 'Exploration', state: 'idle', detail: 'Synchronisationskonzept offen' },
      { label: 'Implementation', state: 'idle', detail: 'Backlog' },
      { label: 'Verify', state: 'idle', detail: 'Wartend' },
      { label: 'Closure', state: 'idle', detail: 'Wartend' },
    ],
    events: [
      { time: '11:31', type: 'backlog_refinement', detail: 'Graph-Sheet-Synchronisierung als Wave-2 Kandidat markiert', severity: 'info' },
    ],
    dependencies: ['AK3-101'],
  },
  {
    id: 'AK3-109',
    title: 'Failure-Corpus Pattern Promotion',
    type: 'bugfix',
    status: 'Approved',
    size: 'M',
    owner: 'worker-1',
    repo: 'failure-corpus',
    module: 'failure_corpus',
    epic: 'Pattern Learning',
    changeImpact: 'Cross-Component',
    conceptQuality: 'Medium',
    wave: 2,
    risk: 'high',
    blocker: 'Blockiert durch WARNING aus Policy Engine: unklare Pattern-Deduplizierung',
    criticalPath: true,
    qaRounds: 1,
    processingTime: '67 min',
    labels: ['failure-corpus', 'policy', 'blocked'],
    need: 'Pattern-Promotion darf keine fremde BC-Ownership verletzen und muss Deduplizierung deterministisch nachvollziehbar machen.',
    solution: 'Promotion wird vor Policy-Entscheidung gegen Stage Registry und Owner-Boundaries validiert.',
    conceptRefs: ['FK-41 Failure Corpus', 'FK-33 Stage Registry', 'FK-35 Integrity Gate'],
    guardrailRefs: ['BC owner boundary', 'ZERO-DEBT'],
    acceptance: [
      'Pattern-Promotion respektiert Owner-Grenzen',
      'Deduplizierung ist deterministic nachvollziehbar',
      'Blocker wird typisiert an Planung zurueckgemeldet',
    ],
    gates: [
      { label: 'Dependency Blocker', state: 'WARNING' },
      { label: 'Stage Registry', state: 'PASS' },
      { label: 'Owner Boundary', state: 'ERROR' },
    ],
    phases: [
      { label: 'Setup', state: 'done', detail: 'Preflight mit WARNING' },
      { label: 'Exploration', state: 'done', detail: 'Scope-Konflikt erkannt' },
      { label: 'Implementation', state: 'blocked', detail: 'Wartet auf fachliche Entscheidung' },
      { label: 'Verify', state: 'idle', detail: 'Nicht gestartet' },
      { label: 'Closure', state: 'idle', detail: 'Nicht gestartet' },
    ],
    events: [
      { time: '07:58', type: 'integrity_violation', detail: 'Cross-BC Owner Boundary verletzt', severity: 'error' },
      { time: '08:02', type: 'planning_blocked', detail: 'typisierter Blocker gesetzt', severity: 'warning' },
    ],
    dependencies: ['AK3-121'],
  },
  {
    id: 'AK3-101',
    title: 'Telemetry Event Projection finalisieren',
    type: 'implementation',
    status: 'Done',
    size: 'L',
    owner: 'worker-3',
    repo: 'telemetry',
    module: 'telemetry_service',
    epic: 'Runtime Evidence',
    changeImpact: 'Component',
    conceptQuality: 'High',
    wave: 0,
    risk: 'low',
    criticalPath: false,
    qaRounds: 3,
    processingTime: '188 min',
    completedAt: '2026-04-30',
    labels: ['telemetry', 'events', 'projection'],
    need: 'Telemetry muss gueltige Story-Runs nachvollziehbar und pruefbar machen, ohne JSONL als Runtime-Wahrheit zu verwenden.',
    solution: 'execution_events werden in PostgreSQL project_key-gefiltert persistiert und in story_metrics / Audit-Bundles projiziert.',
    conceptRefs: ['FK-68 Telemetrie', 'FK-69 Read Models', 'FK-18 Relational Mapping'],
    guardrailRefs: ['State backend canonical', 'No JSON truth'],
    acceptance: [
      'execution_events sind project_key-gefiltert',
      'Reset entfernte korrupt verworfene Runs aus Read Models',
      'Closure schreibt story_metrics',
    ],
    gates: [
      { label: 'Integrity Gate', state: 'PASS' },
      { label: 'LLM Evaluations', state: 'PASS' },
      { label: 'Closure Postflight', state: 'PASS' },
    ],
    phases: [
      { label: 'Setup', state: 'done', detail: 'OK' },
      { label: 'Exploration', state: 'skipped', detail: 'Nicht erforderlich' },
      { label: 'Implementation', state: 'done', detail: '7 Inkremente' },
      { label: 'Verify', state: 'done', detail: '4 Layer PASS' },
      { label: 'Closure', state: 'done', detail: 'Merged und Metriken geschrieben' },
    ],
    events: [
      { time: 'Gestern', type: 'closure_complete', detail: 'story_metrics geschrieben', severity: 'info' },
    ],
    dependencies: [],
  },
  {
    id: 'AK3-111',
    title: 'Planning Proposal Validation',
    type: 'concept',
    status: 'In Progress',
    size: 'S',
    owner: 'domain-owner',
    repo: 'concept',
    module: 'execution-planning',
    epic: 'Planning Domain',
    changeImpact: 'Architecture Impact',
    conceptQuality: 'High',
    wave: 0,
    risk: 'medium',
    criticalPath: false,
    qaRounds: 0,
    processingTime: '42 min',
    labels: ['concept', 'planning', 'api-catalog'],
    need: 'Planning-Proposals brauchen einen validierbaren API- und Statusvertrag, damit Agenten Abhaengigkeiten und Wellen nicht frei improvisieren.',
    solution: 'Proposal-Status, Validierung und Anwendung werden im API-Katalog explizit sichtbar gemacht.',
    conceptRefs: ['FK-70 Execution Planning', 'FK-91 API-Katalog'],
    guardrailRefs: ['Concept lint L15', 'Formal compile'],
    acceptance: [
      'Planning-Proposal-Status ist im API-Katalog reflektiert',
      'Formale Referenzen kompilieren',
      'Offene API-Schuld ist explizit markiert',
    ],
    gates: [
      { label: 'Concept Frontmatter', state: 'PASS' },
      { label: 'Formal Compile', state: 'WARNING' },
      { label: 'BC Boundary', state: 'PASS' },
    ],
    phases: [
      { label: 'Setup', state: 'done', detail: 'Concept-Route ohne Worktree-Merge' },
      { label: 'Exploration', state: 'done', detail: 'Proposal formuliert' },
      { label: 'Implementation', state: 'skipped', detail: 'Concept-Story' },
      { label: 'Verify', state: 'skipped', detail: 'Keine 4-Layer-QA' },
      { label: 'Closure', state: 'active', detail: 'Review offen' },
    ],
    events: [
      { time: '09:15', type: 'formal_compile', detail: '1 WARNING zur API-Katalog-Schuld', severity: 'warning' },
    ],
    dependencies: [],
  },
  {
    id: 'AK3-125',
    title: 'LLM-Pool Divergenztrend im Dashboard',
    type: 'research',
    status: 'Cancelled',
    size: 'S',
    owner: 'unassigned',
    repo: 'analytics',
    module: 'kpi_analytics_engine',
    epic: 'LLM Pool Analytics',
    changeImpact: 'Local',
    conceptQuality: 'Low',
    wave: 3,
    risk: 'low',
    criticalPath: false,
    qaRounds: 0,
    processingTime: '-',
    labels: ['analytics', 'llm-pools', 'research'],
    need: 'LLM-Pool-Divergenz sollte als steuerbare Metrik sichtbar werden, ohne anbieterspezifische Events einzufuehren.',
    solution: 'Die Story wurde fachlich verworfen, weil der Nutzen fuer die operative Story-Steuerung nicht tragfaehig genug war und die Kennzahl ohne weitere Kontextdaten zu Fehlinterpretationen fuehren wuerde.',
    conceptRefs: ['FK-68 review_divergence', 'FK-60 KPI-Katalog', 'FK-63 LLM Performance Tab'],
    guardrailRefs: ['producer-neutral event catalog', 'research web-call budget'],
    acceptance: [
      'Divergenztrend ist als KPI definierbar',
      'Pool-Vergleich ist zeitraumbezogen filterbar',
      'Verwerfung ist als terminaler Status sichtbar',
    ],
    gates: [
      { label: 'Story Contract', state: 'PASS' },
      { label: 'KPI Definition', state: 'WARNING' },
      { label: 'API Coverage', state: 'PASS' },
    ],
    phases: [
      { label: 'Setup', state: 'done', detail: 'Story angelegt' },
      { label: 'Exploration', state: 'done', detail: 'Research-Route bewertet' },
      { label: 'Implementation', state: 'skipped', detail: 'Research-Story' },
      { label: 'Verify', state: 'skipped', detail: 'Nicht codeproduzierend' },
      { label: 'Closure', state: 'done', detail: 'Terminal verworfen' },
    ],
    events: [
      { time: '11:47', type: 'story_cancelled', detail: 'Research-KPI nicht weiter verfolgt; Status auf Cancelled gesetzt', severity: 'warning' },
    ],
    dependencies: ['AK3-101'],
  },
];

type RulebookRow = [id: string, dependencies: string[], cluster: string, repo: string, notes?: string];

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
  ['233', [], 'BE_PREFLIGHT', 'backend'],
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
];

const repoLabels: Record<string, string> = {
  pipeline: 'uc2-pipeline',
  backend: 'ruv-brainbox2-backend',
  frontend: 'ruv-brainbox2-frontend',
  'pipeline+agentframework': 'pipeline + agentframework',
};

const completedCutoff = 36;
const inFlightStoryIds = new Set(['BB2-229', 'BB2-230', 'BB2-231', 'BB2-223']);
const approvedOverrideStoryIds = new Set(['BB2-247', 'BB2-249', 'BB2-254']);
const cancelledStoryIds = new Set(['BB2-246']);
const externallyBlockedStoryIds = new Set(['BB2-238']);

function toStoryStatus(id: string, index: number, dependencies: string[]): StoryStatus {
  if (cancelledStoryIds.has(id)) return 'Cancelled';
  if (index < completedCutoff) return 'Done';
  if (inFlightStoryIds.has(id)) return 'In Progress';
  if (approvedOverrideStoryIds.has(id)) return 'Approved';
  const completedIds = new Set(rulebookRows.slice(0, completedCutoff).map(([rowId]) => `BB2-${rowId}`));
  const depsDone = dependencies.every((dependency) => completedIds.has(dependency));
  return depsDone ? 'Approved' : 'Backlog';
}

function buildRulebookStressStories(): Story[] {
  return rulebookRows.map(([shortId, dependencies, cluster, repo, notes], index): Story => {
    const id = `BB2-${shortId}`;
    const status = toStoryStatus(id, index, dependencies);
    const externalBlocker = externallyBlockedStoryIds.has(id);
    const participatingRepos = repo.split('+').map((item) => repoLabels[item] ?? item);
    const repoLabel = repoLabels[repo] ?? participatingRepos.join(', ');
    const wave = repo.startsWith('frontend') || repo.startsWith('backend') ? 4 : cluster.startsWith('UC2B') ? 3 : 2;
    const primaryModule = cluster.toLowerCase().replaceAll('_', '-');

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
    };
  });
}

export const rulebookStressStories = buildRulebookStressStories();

export const conceptAnchors = [
  'FK-63: Dashboard liest analytics + runtime; Story-Cockpit vereint Status, Protokolle, Telemetrie, QA-Artefakte und Closure-Metriken.',
  'FK-70: Pflichtsicht ist der Dependency-Graph; blockierte Umsetzung wird aus Status, Abhaengigkeiten und Blocker-Kontext abgeleitet.',
  'FK-91: Offizielle API-Grenze liefert /v1/stories, /v1/planning/graph und /v1/dashboard/board.',
];
