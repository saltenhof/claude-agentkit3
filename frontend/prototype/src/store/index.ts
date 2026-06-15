/*
 * Barrel export for the store. Components import exclusively
 * from here (`from '../store'`), not from individual files.
 */

export type {
  ChangeImpact,
  ConceptQuality,
  ExecutionLifecycle,
  ExecutionLimitDescriptor,
  ExecutionLimits,
  Mode,
  Phase,
  PhaseStatus,
  RuntimeState,
  Story,
  StorySize,
  StoryStatus,
  StoryType,
  Substep,
  SubstepMeta,
} from './storyModel';

export {
  ACTIVE_PROJECT,
  CONCEPT_ANCHORS,
  LOOP_GROUP_LABELS,
  LOOP_GROUP_MAX_ITERATIONS,
  PHASE_LABELS,
  PHASE_ORDER,
  PHASE_SUBSTEP_SEQUENCE,
  PHASE_SUBSTEP_SEQUENCE_FAST,
  PROJECT_FIXTURES,
  STORY_FIXTURES,
  SUBSTEP_LABELS,
  SUBSTEP_META,
  substepLabel,
} from './storyFixtures';
export type { ProjectFixture } from './storyFixtures';

/* Backward-compatible aliases for legacy importers. */
export {
  ACTIVE_PROJECT as project,
  CONCEPT_ANCHORS as conceptAnchors,
  PROJECT_FIXTURES as projects,
} from './storyFixtures';

export {
  buildStoryKpiTiles,
  DEFAULT_EXECUTION_LIMITS,
  EXECUTION_LIMIT_DESCRIPTORS,
  selectActiveProjectMode,
  selectExecutionInput,
  selectKpiDailySeries,
  selectProjectKpiStats,
  selectReadyStacks,
  selectStoryCounters,
  selectStoryFlow,
  selectStorySubstepSequence,
} from './storySelectors';
export type {
  ExecutionInputSnapshot,
  FlowPhase,
  FlowState,
  FlowSubstep,
  KpiDailyPoint,
  KpiStat,
  KpiTileData,
  ProjectModeLock,
  ReadyStack,
  StoryCounters,
} from './storySelectors';
