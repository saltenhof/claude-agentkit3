"""Factory wiring the reachable story-creation reconcile surface (FK-21 §21.4).

The agent-facing create path (FK-91 §91.1a Regel #3) runs the REAL fail-closed
VectorDB reconciliation BEFORE calling ``POST /v1/stories``, so the typed
:class:`~agentkit.backend.story_creation.reconciliation_evidence.ReconciliationEvidence`
the non-bypassable create boundary requires is produced by the real runtime --
never hand-built in a tool/skill. This module constructs that runtime from the
target project's configuration:

* **Stage 1 (Weaviate) is wired for real** from ``vectordb.weaviate_http_endpoint`` via
  :meth:`WeaviateStoryAdapter.connect`. A Weaviate outage raises a typed
  :class:`VectorDbUnavailableError` at reconcile time, so the create path
  fail-closes BEFORE persistence (FK-21 §21.4.3) -- never a dummy / skipped
  evidence.
* **Stage 2 (conflict adjudication) is ASKED FOR, not run** (AG3-241). The FK-21
  §21.4.1 Schritt 3 assessment is an LLM evaluation, and an LLM evaluation of the
  story being created may not run in the process creating it. The factory wires
  the thin
  :class:`~agentkit.backend.story_creation.conflict_adjudicator.RestConflictAdjudicator`
  against ``POST /v1/projects/{project_key}/story-conflict-assessments``; the
  transport, the pool routing (FK-75 §75.3) and the prompt resolution
  (FK-44 §44.4.2) all live in the core with the evaluator they belong to.

  **Fallback (truthful, not a bypass):** without a ``project_root`` no
  Project-Edge client exists, so no adjudicator can be built. The factory then
  injects the :class:`FailClosedConflictEvaluator`: an above-threshold candidate
  set is BLOCKED with the TRUTHFUL
  :class:`~agentkit.backend.exceptions.ConflictAdjudicationUnavailableError` (mapped to the
  ``conflict_adjudication_unavailable`` wire code -- NOT a VectorDB outage) rather
  than silently passing an unadjudicated conflict (FK-21 §21.4.3 / NO ERROR
  BYPASSING). A productive ``ConflictEvaluatorPort`` may still be injected
  explicitly to override either default.

The factory deliberately does NOT wire a local ``StoryService``: the agent path
uses :meth:`StoryCreationReconciler.reconcile_only` (no in-process persistence) --
the authoritative create happens at the Control-Plane boundary via the official
:class:`~agentkit.harness_client.projectedge.client.ProjectEdgeClient`, the single story truth.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.backend.exceptions import ConflictAdjudicationUnavailableError
from agentkit.backend.story_creation.create_flow import StoryCreationReconciler
from agentkit.backend.vectordb.endpoints import split_grpc_endpoint, split_http_endpoint
from agentkit.integration_clients.vectordb import (
    VectorDbUnavailableError,
    WeaviateStoryAdapter,
)

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.backend.config.models import ProjectConfig, VectorDbConfig
    from agentkit.backend.story_creation.vectordb_reconciliation import (
        ConflictEvaluatorPort,
        ReconciliationResult,
    )
    from agentkit_wire.verify_system import (
        StoryConflictAssessmentRequest,
        StoryConflictAssessmentResponse,
    )


class FailClosedConflictEvaluator:
    """Fail-closed stage-2 conflict evaluator (no reachable core wired).

    Implements the :class:`ConflictEvaluatorPort` surface. It is only invoked
    when stage 1 surfaced above-threshold similarity candidates that need
    adjudication. Without a Project-Edge client there is no way to ask the core,
    and there is no local substitute: an above-threshold candidate set is then a
    fail-closed blocker -- the create is BLOCKED rather than silently passed
    (FK-21 §21.4.3 / NO ERROR BYPASSING).

    It raises a TRUTHFUL :class:`ConflictAdjudicationUnavailableError` -- NOT a
    :class:`VectorDbUnavailableError`: the VectorDB itself is healthy (stage 1
    just succeeded); only the create-time conflict-adjudication OWNER is missing.
    The tool maps this to the dedicated ``conflict_adjudication_unavailable`` wire
    code so the failure is never mislabelled as a VectorDB outage.
    """

    def assess(
        self, request: StoryConflictAssessmentRequest
    ) -> StoryConflictAssessmentResponse:
        """Raise fail-closed: no route to the create-time adjudication exists.

        Args:
            request: The assessment request (unused; fail-closed).

        Raises:
            ConflictAdjudicationUnavailableError: Always -- an above-threshold
                similarity conflict needs the core's create-time assessment, and
                no reachable core was wired. The create fail-closes rather than
                passing an unadjudicated conflict; the VectorDB is healthy, so
                this is NOT a VectorDB outage.
        """
        del request
        raise ConflictAdjudicationUnavailableError(
            "story-creation stage-2 conflict adjudication has no reachable owner: "
            "no Project-Edge client was wired for the create-time assessment "
            "(AG3-241; the assessment runs in the core, never in this process). "
            "Above-threshold similarity candidates cannot be adjudicated, so the "
            "create is BLOCKED fail-closed (FK-21 §21.4.3) -- no silent pass, no "
            "dummy verdict."
        )


def build_create_time_conflict_evaluator(
    project_config: ProjectConfig,
    *,
    project_root: Path | None = None,
) -> ConflictEvaluatorPort | None:
    """Build the edge half of the create-time conflict assessment (AG3-241).

    The assessment itself runs in the core
    (``POST /v1/projects/{project_key}/story-conflict-assessments``); what is
    built here is the thin adjudicator that asks for it over the official
    Project-Edge client. Nothing about the LLM -- transport, pool routing, prompt
    -- is decided in this process any more; that is the point of the story.

    Args:
        project_config: The loaded target-project config (carries the project
            key that scopes the assessment).
        project_root: The target-project root the Project-Edge client is built
            from (base URL, project credential, CA file). ``None`` means no
            client can be built.

    Returns:
        A wired :class:`RestConflictAdjudicator`, or ``None`` when no
        ``project_root`` was supplied -- in which case the caller falls back to
        the truthful :class:`FailClosedConflictEvaluator`
        (``conflict_adjudication_unavailable``), never a silent pass.
    """
    if project_root is None:
        return None

    from agentkit.backend.story_creation.conflict_adjudicator import (
        RestConflictAdjudicator,
    )
    from agentkit.harness_client.projectedge.runtime import build_project_edge_client

    client = build_project_edge_client(project_root)
    return RestConflictAdjudicator(client, project_key=project_config.project_key)


def build_story_creation_reconciler(
    *,
    project_config: ProjectConfig,
    project_root: Path | None = None,
    conflict_evaluator: ConflictEvaluatorPort | None = None,
) -> StoryCreationReconciler:
    """Build the real reconcile runtime from the target project's config.

    Wires the real Weaviate adapter (stage 1, the fail-closed gate) from
    ``project_config.vectordb``. Stage 2 uses the injected ``conflict_evaluator``;
    when none is supplied the factory builds the REAL
    :class:`~agentkit.backend.story_creation.conflict_adjudicator.CreateTimeConflictAdjudicator`
    from the config's ``story_creation_review`` pool assignment (FK-21 §21.4.1
    Schritt 3). When NO valid create-time pool is configured it falls back to the
    truthful :class:`FailClosedConflictEvaluator` so an above-threshold conflict
    fail-closes (``conflict_adjudication_unavailable``) instead of silently
    passing. No local ``StoryService`` is wired -- the agent path uses
    :meth:`StoryCreationReconciler.reconcile_only` and persists at the
    Control-Plane boundary via the official client.

    Args:
        project_config: The loaded target-project config (carries ``vectordb``
            host/port + tuning and ``repositories[]`` for repo-affinity).
        project_root: The target-project root the Project-Edge client is built
            from, so stage 2 can reach the core's assessment endpoint.
        conflict_evaluator: Optional productive stage-2 evaluator; defaults to the
            REST adjudicator, falling back to a fail-closed evaluator.

    Returns:
        A configured :class:`StoryCreationReconciler` (reconcile-only ready).

    Raises:
        VectorDbUnavailableError: When ``vectordb.weaviate_http_endpoint`` is unset
            (the VectorDB is mandatory infrastructure for story creation, FK-13
            §13.2 / FK-21 §21.4.3) -- fail-closed, never a silent skip.
    """
    vectordb: VectorDbConfig | None = project_config.pipeline.vectordb
    if vectordb is None or not vectordb.weaviate_http_endpoint:
        raise VectorDbUnavailableError(
            "vectordb.weaviate_http_endpoint is not configured; the VectorDB is "
            "mandatory for story creation (FK-13 §13.2 / FK-21 §21.4.3). Story "
            "creation fails closed -- no creation without the reconciliation "
            "runtime."
        )

    # PO decision D-2: the configured endpoint is the ONLY way to say where
    # Weaviate is. host/port come from the single public splitter, never from a
    # second parser -- a duplicated split is exactly the drift this consolidation
    # removed.
    if not vectordb.weaviate_grpc_endpoint:
        raise VectorDbUnavailableError(
            "vectordb.weaviate_grpc_endpoint is not configured; both endpoints are "
            "mandatory configuration (PO decision D-2: no synthesised endpoint). "
            "Story creation fails closed."
        )
    host, port, secure = split_http_endpoint(vectordb.weaviate_http_endpoint)
    grpc_host, grpc_port, grpc_secure = split_grpc_endpoint(vectordb.weaviate_grpc_endpoint)
    adapter = WeaviateStoryAdapter.connect(
        host=host,
        port=port,
        http_secure=secure,
        grpc_host=grpc_host,
        grpc_port=grpc_port,
        grpc_secure=grpc_secure,
    )
    if not adapter.is_ready():
        # A reachable-but-not-ready node is still a fail-closed blocker
        # (FK-21 §21.11.4): never proceed to create with an unready VectorDB.
        adapter.close()
        raise VectorDbUnavailableError(
            "Weaviate is reachable but not ready; story creation fails closed "
            "(FK-21 §21.11.4) -- no creation without a ready reconciliation runtime."
        )

    # Stage-2 evaluator resolution order: an explicitly injected evaluator wins;
    # otherwise build the REAL config-wired adjudicator (FK-21 §21.4.1 Schritt 3);
    # otherwise fall back to the truthful fail-closed evaluator.
    evaluator = conflict_evaluator
    if evaluator is None:
        evaluator = build_create_time_conflict_evaluator(
            project_config, project_root=project_root
        )
    if evaluator is None:
        evaluator = FailClosedConflictEvaluator()

    return StoryCreationReconciler(
        adapter=adapter,
        evaluator=evaluator,
        vectordb_config=vectordb,
        project_config=project_config,
    )


def reconciliation_to_evidence_dict(result: ReconciliationResult) -> dict[str, object]:
    """Project a raw reconciliation result to the evidence wire keys (audit).

    A small helper kept here for callers that need the counter view; the
    canonical typed evidence is produced by
    :meth:`StoryCreationReconciler.reconcile_only`.

    Args:
        result: The two-stage reconciliation result.

    Returns:
        The mandatory counter payload (FK-21 §21.4.2) as wire keys.
    """
    return {
        "total_hits": result.total_hits,
        "hits_above_threshold": result.hits_above_threshold,
        "hits_classified_conflict": result.hits_classified_conflict,
        "threshold_value": result.threshold_value,
    }


__all__ = [
    "FailClosedConflictEvaluator",
    "build_create_time_conflict_evaluator",
    "build_story_creation_reconciler",
    "reconciliation_to_evidence_dict",
]
