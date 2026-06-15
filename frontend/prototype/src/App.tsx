/**
 * App entry point — thin re-export of the BC-aligned Shell.
 *
 * The monolith has been decomposed into:
 *   app_shell/layout/Shell.tsx        — main orchestrator + state
 *   app_shell/routing/viewMode.ts     — hash routing helpers
 *   app_shell/inspector/             — DetailInspector + Detail
 *   app_shell/board/Kanban.tsx        — Kanban view
 *   app_shell/sheet/                 — StorySheet + SheetCell
 *   contexts/story_context_manager/  — SpecificationTab
 *   contexts/artifacts/              — EvidenceTab (fetched evidence + coverage)
 *   contexts/kpi_analytics/          — KpiTab + AnalyticsSlot
 *   contexts/execution_planning/     — GraphView + StoryNode + DependencyEdge
 *   foundation/multi_llm_hub/        — LlmHubView + hubFixtures
 *   foundation/bff/client.ts         — BffClient
 *   design_system/                   — Badge + Sparkline + Info
 */
export { App } from './app_shell/layout/Shell';
