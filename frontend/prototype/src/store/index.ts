/*
 * Barrel-Export fuer den Store. Komponenten importieren ausschliesslich
 * von hier (`from '../store'`) und nicht von einzelnen Files.
 */

export type {
  ChangeImpact,
  ConceptQuality,
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
} from './storyModel';

export {
  ACTIVE_PROJECT,
  CONCEPT_ANCHORS,
  PHASE_SUBSTEP_SEQUENCE,
  PROJECT_FIXTURES,
  STORY_FIXTURES,
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
  selectReadyStacks,
  selectStoryCounters,
} from './storySelectors';
export type { KpiTileData, ReadyStack, StoryCounters } from './storySelectors';
