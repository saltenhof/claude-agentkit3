/*
 * Story-Selectors — Pure Functions zur Sichtbildung auf dem Story-Modell.
 *
 * Jede UI-Sicht (KpiBar, ReadyStackView, ExecutionLimitsView, kuenftig
 * Phase-Stepper / Substep-Liste / etc.) ist ein duenner Wrapper um
 * eine dieser Selector-Funktionen — Komponenten enthalten keine
 * Filter-/Aggregations-Logik mehr.
 */

import type {
  ExecutionLimitDescriptor,
  ExecutionLimits,
  Mode,
  Phase,
  Story,
  Substep,
} from './storyModel';
import {
  PHASE_ORDER,
  PHASE_SUBSTEP_SEQUENCE,
  PHASE_SUBSTEP_SEQUENCE_FAST,
  SUBSTEP_META,
} from './storyFixtures';

/* ---- KPI-Selector ---- */

export interface StoryCounters {
  total: number;
  finished: number;
  running: number;
  ready: number;
  queue: number;
  blocked: number;
}

export interface KpiTileData {
  label: string;
  value: number | string;
  suffix?: string;
  tone?: 'default' | 'warning';
}

export function selectStoryCounters(stories: Story[]): StoryCounters {
  const doneIds = new Set(
    stories.filter((s) => s.status === 'Done').map((s) => s.id),
  );
  const hasOpenDependency = (story: Story): boolean =>
    story.dependencies.some((dep) => !doneIds.has(dep));
  const isReady = (story: Story): boolean =>
    story.status === 'Approved' && !story.blocker && !hasOpenDependency(story);
  const isBlocked = (story: Story): boolean =>
    story.status === 'Backlog' ||
    (story.status === 'Approved' && (Boolean(story.blocker) || hasOpenDependency(story)));

  return {
    total: stories.length,
    running: stories.filter((s) => s.status === 'In Progress').length,
    finished: stories.filter((s) => s.status === 'Done').length,
    ready: stories.filter(isReady).length,
    queue: stories.filter((s) => s.status === 'Approved').length,
    blocked: stories.filter(isBlocked).length,
  };
}

export function buildStoryKpiTiles(counters: StoryCounters): KpiTileData[] {
  const donePercent =
    counters.total > 0 ? Math.round((counters.finished / counters.total) * 100) : 0;
  return [
    { label: 'Total Stories', value: counters.total },
    { label: 'Done', value: donePercent, suffix: '%' },
    { label: 'Ready', value: counters.ready },
    { label: 'In Progress', value: counters.running },
    { label: 'Blocked', value: counters.blocked, tone: 'warning' },
  ];
}

/* ---- Ready-Stack-Selector ---- */

export interface ReadyStack {
  story: Story;
  predecessor: Story | null;
  successor: Story | null;
}

export function selectReadyStacks(stories: Story[]): ReadyStack[] {
  const doneIds = new Set(
    stories.filter((s) => s.status === 'Done').map((s) => s.id),
  );
  const hasOpenDependency = (story: Story): boolean =>
    story.dependencies.some((dep) => !doneIds.has(dep));
  const isReady = (story: Story): boolean =>
    story.status === 'Approved' && !story.blocker && !hasOpenDependency(story);

  const successorsByStoryId = new Map<string, Story[]>();
  for (const candidate of stories) {
    for (const depId of candidate.dependencies) {
      const list = successorsByStoryId.get(depId) ?? [];
      list.push(candidate);
      successorsByStoryId.set(depId, list);
    }
  }

  const findById = (id: string): Story | null =>
    stories.find((s) => s.id === id) ?? null;

  return stories.filter(isReady).map((story) => ({
    story,
    predecessor:
      story.dependencies.length > 0 ? findById(story.dependencies[0]) : null,
    successor: successorsByStoryId.get(story.id)?.[0] ?? null,
  }));
}

/* ---- Execution-Input-Selector ----
 *
 * Konzept-Anker: FK-70 §70.8a (Execution-Input-Top-Surface,
 * Doppel-Schnittstelle).
 *
 * Liefert genau die Stories, die operativ relevant sind:
 *   - laufende (In-Progress) Stories
 *   - Ready-Stories nach Triage gegen die Execution-Limits, also nicht
 *     "alle theoretisch ready" sondern "diese duerfen jetzt starten".
 *
 * Triage:
 *   1. globalCap = min(mergeRiskCap, maxParallelAgentCap, llmPoolCap,
 *      ciCapacityCap). Davon wird die Anzahl bereits laufender
 *      Stories abgezogen -> globalSlotsLeft.
 *   2. pro Repo: repoParallelCap - bereits laufend in diesem Repo.
 *   3. Bucketing nach Repo, intern sortiert nach criticalPath DESC,
 *      dann Story-Nummer ASC.
 *   4. Round-Robin ueber Repos: jeder Repo darf abwechselnd seine
 *      naechste Karte bringen, bis globalSlotsLeft erschoepft ist
 *      oder kein Repo mehr Slots/Karten hat.
 *
 * Determinismus: gleiche Eingabe -> gleiche Ausgabe (sortierte
 * Repo-Iteration und Story-IDs).
 *
 * Diese Funktion ist die Single-Source-Triage. Im Backend muss sie
 * exakt zwei Adapter speisen (FK-70 §70.8a, FK-91 §91.1a):
 *   - GET /v1/projects/{project_key}/execution-input/snapshot
 *     (Frontend, gibt das gesamte Pick-Ergebnis)
 *   - GET /v1/projects/{project_key}/execution-input/next
 *     (Orchestrator-Skill, gibt die erste Karte des Pick-Ergebnisses)
 * Eine Doppel-Implementierung der Triage-Logik ist explizit
 * unzulaessig.
 */

export interface ExecutionInputSnapshot {
  running: ReadyStack[];
  eligibleReady: ReadyStack[];
  totalReady: number;
  globalSlotsLeft: number;
}

function getStorySerial(storyId: string): number {
  const match = storyId.match(/(\d+)$/);
  return match ? Number.parseInt(match[1], 10) : 0;
}

function getRepoKey(story: Story): string {
  return story.primaryRepo ?? story.repo;
}

function buildSuccessorIndex(stories: Story[]): Map<string, Story[]> {
  const index = new Map<string, Story[]>();
  for (const candidate of stories) {
    for (const depId of candidate.dependencies) {
      const list = index.get(depId) ?? [];
      list.push(candidate);
      index.set(depId, list);
    }
  }
  return index;
}

function buildStackFor(
  story: Story,
  stories: Story[],
  successors: Map<string, Story[]>,
): ReadyStack {
  const findById = (id: string) => stories.find((s) => s.id === id) ?? null;
  return {
    story,
    predecessor:
      story.dependencies.length > 0 ? findById(story.dependencies[0]) : null,
    successor: successors.get(story.id)?.[0] ?? null,
  };
}

export function selectExecutionInput(
  stories: Story[],
  limits: ExecutionLimits,
): ExecutionInputSnapshot {
  const successors = buildSuccessorIndex(stories);

  /* In-Progress (= bereits delegiert): Slots bereits belegt. */
  const runningStories = stories.filter((s) => s.status === 'In Progress');
  const running: ReadyStack[] = runningStories.map((story) =>
    buildStackFor(story, stories, successors),
  );

  /* Pro Repo: aktuell belegte Slots. */
  const runningPerRepo = new Map<string, number>();
  for (const story of runningStories) {
    const repo = getRepoKey(story);
    runningPerRepo.set(repo, (runningPerRepo.get(repo) ?? 0) + 1);
  }

  /* Globaler Slot-Cap aus den Caps, abzueglich Laufender. */
  const globalCap = Math.min(
    limits.mergeRiskCap,
    limits.maxParallelAgentCap,
    limits.llmPoolCap,
    limits.ciCapacityCap,
  );
  const globalSlotsLeft = Math.max(0, globalCap - runningStories.length);

  /* Alle technisch ready Stories. */
  const allReady = selectReadyStacks(stories);

  /* Triage: Bucket nach Repo, sortieren, Round-Robin picken. */
  const buckets = new Map<string, ReadyStack[]>();
  for (const stack of allReady) {
    const repo = getRepoKey(stack.story);
    const list = buckets.get(repo) ?? [];
    list.push(stack);
    buckets.set(repo, list);
  }
  for (const list of buckets.values()) {
    list.sort((a, b) => {
      if (a.story.criticalPath !== b.story.criticalPath) {
        return a.story.criticalPath ? -1 : 1;
      }
      return getStorySerial(a.story.id) - getStorySerial(b.story.id);
    });
  }

  const sortedRepos = Array.from(buckets.keys()).sort();
  const repoUsed = new Map<string, number>();
  const eligibleReady: ReadyStack[] = [];

  let madeProgress = true;
  while (madeProgress && eligibleReady.length < globalSlotsLeft) {
    madeProgress = false;
    for (const repo of sortedRepos) {
      if (eligibleReady.length >= globalSlotsLeft) break;
      const used = repoUsed.get(repo) ?? 0;
      const repoSlotsLeft = Math.max(
        0,
        limits.repoParallelCap - (runningPerRepo.get(repo) ?? 0) - used,
      );
      if (repoSlotsLeft <= 0) continue;
      const bucket = buckets.get(repo) ?? [];
      if (used >= bucket.length) continue;
      eligibleReady.push(bucket[used]);
      repoUsed.set(repo, used + 1);
      madeProgress = true;
    }
  }

  return {
    running,
    eligibleReady,
    totalReady: allReady.length,
    globalSlotsLeft,
  };
}

/* ---- Mode-Lock-Selector (FK-24 §24.3.3) ----
 *
 * Projektweit kann zur Laufzeit nur ein Mode aktiv sein. Der UI-Wert
 * spiegelt den `mode_lock` der Control Plane: belegt ist er, sobald
 * mindestens eine In-Progress-Story laeuft; der Mode dieser Stories
 * bestimmt den Lock. Sind keine Stories in Bearbeitung, ist der Lock
 * `null` -> "Idle".
 */

export type ProjectModeLock = Mode | null;

export function selectActiveProjectMode(stories: Story[]): ProjectModeLock {
  for (const story of stories) {
    if (story.status !== 'In Progress') continue;
    return story.mode ?? 'standard';
  }
  return null;
}

/* ---- Flow-Selectors fuer den Story-Inspector "Ablauf"-Tab ---- */

/* Substep-States im Flowchart.
 *
 * - `done`     : in dieser oder einer frueheren Iteration erfolgreich abgeschlossen
 * - `active`   : aktuell in Bearbeitung (Runtime zeigt darauf)
 * - `pending`  : noch nicht erreicht (in dieser Iteration)
 * - `skipped`  : durch Mode/Phase-Sprung uebersprungen (z. B. Exploration im Fast)
 * - `optional-pending` : optionaler Substep, Vorbedingung noch offen
 * - `optional-skipped` : optionaler Substep, Vorbedingung war negativ
 *                        (Substep wurde nicht ausgefuehrt) */
export type FlowState =
  | 'done'
  | 'active'
  | 'pending'
  | 'skipped'
  | 'optional-pending'
  | 'optional-skipped';

export interface FlowSubstep {
  substep: Substep;
  state: FlowState;
  optional: boolean;
  loopGroup?: string;
  /* Position innerhalb der Loop-Gruppe (1-basiert), nur gesetzt wenn
   * `loopGroup` gesetzt ist. Hilft dem UI, Loop-Anfang und -Ende zu
   * erkennen. */
  loopPosition?: number;
  loopSize?: number;
}

export interface FlowPhase {
  phase: Phase;
  state: FlowState;
  substeps: FlowSubstep[];
  /* Aktuelle Iteration der aktiven Loop-Gruppe in dieser Phase
   * (nur gesetzt, wenn die Phase aktiv ist UND der aktive Substep
   * Teil einer Loop-Gruppe ist). 1 = Erstdurchlauf, ab 2 sichtbar
   * als "Runde N". */
  iteration?: number;
  iterationLoopGroup?: string;
}

export function selectStorySubstepSequence(mode: Mode): Record<Phase, Substep[]> {
  return mode === 'fast' ? PHASE_SUBSTEP_SEQUENCE_FAST : PHASE_SUBSTEP_SEQUENCE;
}

/* Liefert die UI-Metadaten eines Substeps abhaengig vom Story-Mode.
 *
 * Im Fast-Mode entfallen alle Loop-Gruppen: die Exploration ist OUT
 * und damit auch `design_iteration`; der `remediation`-Loop in
 * Implementation existiert ohne QA-Feedback (Schichten 2-4 + Feedback
 * OUT) nicht, weil ohne Feedback nichts mehr re-iteriert werden kann.
 * Quelle: AG3-018 §Mode-Profil. */
function metaFor(substep: Substep, mode: Mode): { optional: boolean; loopGroup?: string } {
  const meta = SUBSTEP_META[substep];
  if (mode === 'fast') {
    return { optional: meta?.optional ?? false };
  }
  return {
    optional: meta?.optional ?? false,
    loopGroup: meta?.loopGroup,
  };
}

/* Annotates a list of substep-IDs with loop-position / loop-size, so
 * the UI can render the boundaries of each loop region. */
function annotateLoopPositions(
  substepIds: Substep[],
  mode: Mode,
): Array<{ substep: Substep; loopPosition?: number; loopSize?: number }> {
  /* Loop-Region = maximaler zusammenhaengender Bereich gleicher
   * `loopGroup`-Markierung. Substeps ohne `loopGroup` schliessen die
   * Region. */
  const result: Array<{ substep: Substep; loopPosition?: number; loopSize?: number }> = [];
  let regionStart = -1;
  let regionGroup: string | undefined;
  const flushRegion = (endExclusive: number) => {
    if (regionStart === -1 || regionGroup === undefined) return;
    const size = endExclusive - regionStart;
    for (let i = regionStart; i < endExclusive; i += 1) {
      result[i].loopPosition = i - regionStart + 1;
      result[i].loopSize = size;
    }
    regionStart = -1;
    regionGroup = undefined;
  };
  substepIds.forEach((substep, index) => {
    result.push({ substep });
    const group = metaFor(substep, mode).loopGroup;
    if (group !== regionGroup) {
      flushRegion(index);
      if (group) {
        regionStart = index;
        regionGroup = group;
      }
    }
  });
  flushRegion(substepIds.length);
  return result;
}

function buildSubstep(
  substep: Substep,
  state: FlowState,
  mode: Mode,
  loopPosition?: number,
  loopSize?: number,
): FlowSubstep {
  const { optional, loopGroup } = metaFor(substep, mode);
  /* `pending` auf optionalen Substeps wird zu `optional-pending`
   * gehoben — der UI-State bleibt damit klar von zwingenden
   * Pending-Substeps unterschieden. */
  const finalState: FlowState =
    optional && state === 'pending' ? 'optional-pending' : state;
  return {
    substep,
    state: finalState,
    optional,
    loopGroup,
    loopPosition,
    loopSize,
  };
}

export function selectStoryFlow(story: Story): FlowPhase[] {
  const mode: Mode = story.mode ?? 'standard';
  const sequence = selectStorySubstepSequence(mode);
  const status = story.status;
  const runtime = story.runtime;

  const allDone = status === 'Done';
  const noProgress = status === 'Backlog' || status === 'Approved' || status === 'Cancelled';

  return PHASE_ORDER.map((phase): FlowPhase => {
    const substepIds = sequence[phase];
    const annotated = annotateLoopPositions(substepIds, mode);
    const isExplorationSkippedByMode = phase === 'exploration' && mode === 'fast';

    if (isExplorationSkippedByMode) {
      /* Fast-Mode laesst Exploration komplett aus. Wir zeigen die
       * Phase mit "im Fast-Mode ausgelassen"-Pille, aber ohne
       * Substep-Liste -- der Benutzer soll nicht sehen, was *theoretisch*
       * in Exploration laufen wuerde, wenn er gerade gar nicht in
       * Exploration ist. */
      return {
        phase,
        state: 'skipped',
        substeps: [],
      };
    }

    if (allDone) {
      return {
        phase,
        state: 'done',
        substeps: annotated.map(({ substep, loopPosition, loopSize }) =>
          buildSubstep(substep, 'done', mode, loopPosition, loopSize),
        ),
      };
    }

    if (noProgress || !runtime) {
      return {
        phase,
        state: 'pending',
        substeps: annotated.map(({ substep, loopPosition, loopSize }) =>
          buildSubstep(substep, 'pending', mode, loopPosition, loopSize),
        ),
      };
    }

    const runtimePhaseIndex = PHASE_ORDER.indexOf(runtime.phase);
    const phaseIndex = PHASE_ORDER.indexOf(phase);

    if (phaseIndex < runtimePhaseIndex) {
      return {
        phase,
        state: 'done',
        substeps: annotated.map(({ substep, loopPosition, loopSize }) =>
          buildSubstep(substep, 'done', mode, loopPosition, loopSize),
        ),
      };
    }

    if (phaseIndex > runtimePhaseIndex) {
      return {
        phase,
        state: 'pending',
        substeps: annotated.map(({ substep, loopPosition, loopSize }) =>
          buildSubstep(substep, 'pending', mode, loopPosition, loopSize),
        ),
      };
    }

    /* Aktive Phase. Substeps vor dem Runtime-Punkt sind in dieser
     * Iteration `done`. Optionale Substeps, die nicht der Runtime-Punkt
     * sind und vor ihm liegen, koennen im realen Lauf entweder
     * ausgefuehrt oder uebersprungen worden sein. Der Prototyp kennt
     * das nicht — wir nehmen optimistisch `done` an, mit Ausnahme von
     * `feindesign`, das wir fuer die Demo bewusst als
     * `optional-skipped` zeigen, sobald der Runtime-Punkt nach dem
     * Substep liegt. Das verdeutlicht den Unterschied zwischen
     * "ausgefuehrt" und "weil unnoetig uebersprungen". */
    const activeIndex = substepIds.indexOf(runtime.substep);
    const activeMeta = activeIndex >= 0 ? metaFor(substepIds[activeIndex], mode) : undefined;

    const substeps: FlowSubstep[] = annotated.map(({ substep, loopPosition, loopSize }, index) => {
      if (activeIndex === -1) {
        return buildSubstep(substep, 'pending', mode, loopPosition, loopSize);
      }
      if (index < activeIndex) {
        const { optional } = metaFor(substep, mode);
        if (optional && substep === 'feindesign') {
          return buildSubstep(substep, 'optional-skipped', mode, loopPosition, loopSize);
        }
        return buildSubstep(substep, 'done', mode, loopPosition, loopSize);
      }
      if (index === activeIndex) {
        return buildSubstep(substep, 'active', mode, loopPosition, loopSize);
      }
      return buildSubstep(substep, 'pending', mode, loopPosition, loopSize);
    });

    const iteration = runtime.iteration ?? 1;
    return {
      phase,
      state: activeIndex === -1 ? 'pending' : 'active',
      substeps,
      iteration,
      iterationLoopGroup: activeMeta?.loopGroup,
    };
  });
}

/* ---- Analytics-Selectors (Project-weite Aggregation) ----
 *
 * Liefert pro Metrik die Vier-Werte-Sicht avg / min / max / p90.
 * Die KPI-Seite zeigt das im Übersichts-Tab; der Zeitreihen-Tab nutzt
 * `selectKpiDailySeries` (siehe unten) als Verlaufs-Quelle. */

export interface KpiStat {
  key: string;
  label: string;
  unit?: string;
  avg: number;
  min: number;
  max: number;
  p90: number;
}

function parseProcessingMinutes(value: string | undefined): number | null {
  if (!value) return null;
  const match = value.match(/(\d+(?:[\.,]\d+)?)/);
  if (!match) return null;
  const num = Number.parseFloat(match[1].replace(',', '.'));
  return Number.isFinite(num) ? num : null;
}

function quantile(values: number[], q: number): number {
  if (values.length === 0) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const pos = (sorted.length - 1) * q;
  const base = Math.floor(pos);
  const rest = pos - base;
  if (sorted[base + 1] !== undefined) {
    return sorted[base] + rest * (sorted[base + 1] - sorted[base]);
  }
  return sorted[base];
}

function stat(key: string, label: string, values: number[], unit?: string): KpiStat {
  if (values.length === 0) {
    return { key, label, unit, avg: 0, min: 0, max: 0, p90: 0 };
  }
  const sum = values.reduce((acc, v) => acc + v, 0);
  return {
    key,
    label,
    unit,
    avg: sum / values.length,
    min: Math.min(...values),
    max: Math.max(...values),
    p90: quantile(values, 0.9),
  };
}

/* Synthetische QA-Solving-Rate, konsistent mit der Inspector-Heuristik.
 * Verarbeitet keine Fast-Mode-spezifische Sonderlogik (Fast-Stories
 * tragen weder Exploration-QA noch Implementation-QA in Form, die wir
 * hier statistisch trennen koennten). */
function syntheticSolvingRate(story: Story, phase: 'exploration' | 'implementation'): number | null {
  if (story.mode === 'fast' && phase === 'exploration') return null;
  const rounds = phase === 'exploration' ? story.qaRoundsExploration ?? 0 : story.qaRoundsImplementation ?? story.qaRounds;
  if (rounds === 0) {
    return story.status === 'Done' ? 100 : null;
  }
  const base = phase === 'exploration' ? 70 : 72;
  const step = phase === 'exploration' ? 10 : 8;
  return Math.min(100, base + rounds * step);
}

export function selectProjectKpiStats(stories: Story[]): KpiStat[] {
  /* Wir aggregieren nur Stories, die operativ relevant sind: Done und
   * In Progress (Backlog/Approved liefern keine sinnvollen Werte). */
  const relevant = stories.filter((s) => s.status === 'Done' || s.status === 'In Progress');

  const runtimeTotals = relevant.map((s) => parseProcessingMinutes(s.processingTime)).filter((v): v is number => v !== null);
  const runtimeExpl = runtimeTotals.map((v, i) => (relevant[i].mode === 'fast' ? 0 : v * 0.2));
  const runtimeImpl = runtimeTotals.map((v, i) => (relevant[i].mode === 'fast' ? v * 0.75 : v * 0.6));
  const runtimeClosure = runtimeTotals.map((v, i) => (relevant[i].mode === 'fast' ? v * 0.25 : v * 0.2));

  const qaRoundsExpl = relevant.map((s) => s.qaRoundsExploration ?? 0);
  const qaRoundsImpl = relevant.map((s) => s.qaRoundsImplementation ?? s.qaRounds);

  /* Tokens: synthetisch aus QA-Runden + In-Progress-Penalty,
   * konsistent mit der Inspector-Logik (s. KpiTab). */
  const tokensIn = relevant.map((s) => Math.round(s.qaRounds * 22000 + 8000));
  const tokensOut = relevant.map((s) => Math.round(s.qaRounds * 8000 + 3000));
  const tokensTotal = tokensIn.map((v, i) => v + tokensOut[i]);
  const tokensCached = tokensIn.map((v) => Math.round(v * 0.32));

  const solvingExpl = relevant
    .map((s) => syntheticSolvingRate(s, 'exploration'))
    .filter((v): v is number => v !== null);
  const solvingImpl = relevant
    .map((s) => syntheticSolvingRate(s, 'implementation'))
    .filter((v): v is number => v !== null);

  return [
    stat('runtime_total', 'Laufzeit Total', runtimeTotals, 'min'),
    stat('runtime_exploration', 'Laufzeit Exploration', runtimeExpl, 'min'),
    stat('runtime_implementation', 'Laufzeit Implementation', runtimeImpl, 'min'),
    stat('runtime_closure', 'Laufzeit Closure', runtimeClosure, 'min'),
    stat('tokens_total', 'Token Total', tokensTotal),
    stat('tokens_in', 'Token In', tokensIn),
    stat('tokens_out', 'Token Out', tokensOut),
    stat('tokens_cached', 'Token Cached', tokensCached),
    stat('qa_rounds_exploration', 'QA-Runden Exploration', qaRoundsExpl),
    stat('solving_rate_exploration', 'Solving Rate Exploration', solvingExpl, '%'),
    stat('qa_rounds_implementation', 'QA-Runden Implementation', qaRoundsImpl),
    stat('solving_rate_implementation', 'Solving Rate Implementation', solvingImpl, '%'),
  ];
}

/* ---- Daily-Series Synthese ----
 *
 * Der Backend-Snapshot wird spaeter echte Per-Tag-Aggregationen liefern.
 * Bis dahin synthetisieren wir die letzten N Kalendertage aus dem
 * Story-Korpus: pro Tag wird ein deterministischer Wert berechnet, der
 * an die echten Werte angelehnt ist und um eine seedbasierte Schwankung
 * variiert. */

export interface KpiDailyPoint {
  date: string; // ISO YYYY-MM-DD
  values: Record<string, number>;
}

function seededNoise(seed: number): number {
  /* Lineare Kongruenz-Pseudozufall; reproduzierbar pro Tag. */
  const x = Math.sin(seed * 9301 + 49297) * 233280;
  return x - Math.floor(x);
}

export function selectKpiDailySeries(stories: Story[], days = 30): KpiDailyPoint[] {
  const base = selectProjectKpiStats(stories);
  const baseByKey = new Map(base.map((s) => [s.key, s] as const));
  const today = new Date('2026-05-11T00:00:00Z');
  const points: KpiDailyPoint[] = [];
  for (let offset = days - 1; offset >= 0; offset -= 1) {
    const day = new Date(today.getTime() - offset * 24 * 60 * 60 * 1000);
    const iso = day.toISOString().slice(0, 10);
    const wave = Math.sin(offset / 4) * 0.15;
    const values: Record<string, number> = {};
    for (const s of base) {
      const noise = seededNoise(offset * 17 + s.key.length);
      const swing = (noise - 0.5) * 0.25 + wave;
      const center = (baseByKey.get(s.key)?.avg ?? 0);
      let value = center * (1 + swing);
      if (s.unit === '%') value = Math.max(0, Math.min(100, value));
      values[s.key] = Math.round(value * 100) / 100;
    }
    points.push({ date: iso, values });
  }
  return points;
}

/* ---- Execution-Limits-Defaults ---- */

export const DEFAULT_EXECUTION_LIMITS: ExecutionLimits = {
  repoParallelCap: 3,
  mergeRiskCap: 5,
  maxParallelAgentCap: 8,
  llmPoolCap: 10,
  ciCapacityCap: 4,
};

export const EXECUTION_LIMIT_DESCRIPTORS: ExecutionLimitDescriptor[] = [
  {
    key: 'repoParallelCap',
    label: 'Repo Parallel Cap',
    description: 'Max. gleichzeitig laufende Stories pro Repo (gegen Merge-Konflikte).',
  },
  {
    key: 'mergeRiskCap',
    label: 'Merge Risk Cap',
    description: 'Aggregiertes Merge-Risiko-Budget über alle aktiven Stories.',
  },
  {
    key: 'maxParallelAgentCap',
    label: 'Max Parallel Agent Cap',
    description: 'Max. parallel laufende Worker-Agent-Sessions ueber alle Stories hinweg.',
  },
  {
    key: 'llmPoolCap',
    label: 'LLM Pool Cap',
    description: 'Summe der parallel belegbaren LLM-Pool-Slots (alle Backends).',
  },
  {
    key: 'ciCapacityCap',
    label: 'CI Capacity Cap',
    description: 'Max. parallele CI- und Build-Slots.',
  },
];
