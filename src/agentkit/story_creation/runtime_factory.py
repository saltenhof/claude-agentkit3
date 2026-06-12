"""Factory wiring the reachable story-creation reconcile surface (FK-21 §21.4).

The agent-facing create path (FK-91 §91.1a Regel #3) runs the REAL fail-closed
VectorDB reconciliation BEFORE calling ``POST /v1/stories``, so the typed
:class:`~agentkit.story_creation.reconciliation_evidence.ReconciliationEvidence`
the non-bypassable create boundary requires is produced by the real runtime --
never hand-built in a tool/skill. This module constructs that runtime from the
target project's configuration:

* **Stage 1 (Weaviate) is wired for real** from ``vectordb.host`` / ``port`` via
  :meth:`WeaviateStoryAdapter.connect`. A Weaviate outage raises a typed
  :class:`VectorDbUnavailableError` at reconcile time, so the create path
  fail-closes BEFORE persistence (FK-21 §21.4.3) -- never a dummy / skipped
  evidence.
* **Stage 2 (LLM conflict adjudication)** runs the REAL FK-21 §21.4.1 Schritt 3
  conflict assessment via the create-scope
  :class:`~agentkit.story_creation.conflict_adjudicator.CreateTimeConflictAdjudicator`
  (AG3-115). That adjudicator reuses the unchanged
  :class:`~agentkit.verify_system.llm_evaluator.structured_evaluator.StructuredEvaluator`
  over the FK-65 / FK-11 :class:`HubLlmClient` transport, but with a create-scope
  prompt materializer -- so it needs NO ``StoryContext`` / ``run_id`` / story dir
  (none of which exist before the story is created). This factory builds that real
  transport from the target-project config: the Hub base URL is resolved via
  :func:`~agentkit.multi_llm_hub.config.load_multi_llm_hub_config` and the
  ``story_creation_review`` role -> pool routing is read from
  ``pipeline.llm_roles.story_creation_review`` through the config-faithful
  :class:`_ConfigRolePoolResolver` (FK-75 §75.3: the routing OWNER is config, not
  the transport). Once stage 1 surfaces above-threshold similarity candidates,
  stage 2 now produces a genuine binary PASS (no conflict, create proceeds) / FAIL
  (duplicate / overlap, create blocks) verdict -- no longer a blanket fail-close.
  An LLM-transport outage at stage 2 raises a TRUTHFUL
  :class:`~agentkit.story_creation.conflict_adjudicator.CreateTimeConflictAdjudicationError`
  (the VectorDB is healthy; only the create-time LLM assessment failed).

  **Fallback (truthful, not a bypass):** when the project config does NOT assign a
  ``story_creation_review`` pool, no real adjudicator can be built. The factory
  then injects the :class:`FailClosedConflictEvaluator`: an above-threshold
  candidate set is BLOCKED with the TRUTHFUL
  :class:`~agentkit.exceptions.ConflictAdjudicationUnavailableError` (mapped to the
  ``conflict_adjudication_unavailable`` wire code -- NOT a VectorDB outage) rather
  than silently passing an unadjudicated conflict (FK-21 §21.4.3 / NO ERROR
  BYPASSING). A productive ``ConflictEvaluatorPort`` may still be injected
  explicitly to override either default.

The factory deliberately does NOT wire a local ``StoryService``: the agent path
uses :meth:`StoryCreationReconciler.reconcile_only` (no in-process persistence) --
the authoritative create happens at the Control-Plane boundary via the official
:class:`~agentkit.projectedge.client.ProjectEdgeClient`, the single story truth.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast, get_args

from agentkit.exceptions import ConflictAdjudicationUnavailableError
from agentkit.integrations.vectordb import (
    VectorDbUnavailableError,
    WeaviateStoryAdapter,
)
from agentkit.multi_llm_hub.entities import HubBackendName
from agentkit.story_creation.create_flow import StoryCreationReconciler
from agentkit.verify_system.llm_evaluator.llm_client import LlmClientError

if TYPE_CHECKING:
    from agentkit.config.models import ProjectConfig, VectorDbConfig
    from agentkit.story_creation.vectordb_reconciliation import (
        ConflictEvaluatorPort,
        ReconciliationResult,
    )
    from agentkit.verify_system.llm_evaluator.bundle import ReviewBundle
    from agentkit.verify_system.llm_evaluator.roles import ReviewerRole
    from agentkit.verify_system.llm_evaluator.structured_evaluator import (
        StructuredEvaluatorResult,
    )


class FailClosedConflictEvaluator:
    """Fail-closed stage-2 conflict evaluator (no create-time LLM owner yet).

    Implements the :class:`ConflictEvaluatorPort` surface. It is only invoked
    when stage 1 surfaced above-threshold similarity candidates that need LLM
    adjudication. Until the productive create-time LLM wiring exists (AG3-065 /
    AG3-070; the story-execution-scoped ``StructuredEvaluator`` is not a pre-story
    owner), an above-threshold candidate set is a fail-closed blocker: the create
    is BLOCKED rather than silently passed (FK-21 §21.4.3 / NO ERROR BYPASSING).

    It raises a TRUTHFUL :class:`ConflictAdjudicationUnavailableError` -- NOT a
    :class:`VectorDbUnavailableError`: the VectorDB itself is healthy (stage 1
    just succeeded); only the create-time conflict-adjudication OWNER is missing.
    The tool maps this to the dedicated ``conflict_adjudication_unavailable`` wire
    code so the failure is never mislabelled as a VectorDB outage.
    """

    def evaluate(
        self,
        role: ReviewerRole,
        bundle: ReviewBundle,
        previous_findings: list[object] | None,
        qa_cycle_round: int,
    ) -> StructuredEvaluatorResult:
        """Raise fail-closed: no create-time LLM adjudicator is configured.

        Args:
            role: The reviewer role (unused; fail-closed).
            bundle: The review bundle (unused; fail-closed).
            previous_findings: Prior findings (unused; fail-closed).
            qa_cycle_round: The QA cycle round (unused; fail-closed).

        Raises:
            ConflictAdjudicationUnavailableError: Always -- an above-threshold
                similarity conflict needs create-time LLM adjudication that has no
                owner wired (the ``StructuredEvaluator`` is story-execution
                scoped). The create fail-closes rather than passing an
                unadjudicated conflict; the VectorDB is healthy, so this is NOT a
                VectorDB outage.
        """
        del role, bundle, previous_findings, qa_cycle_round
        raise ConflictAdjudicationUnavailableError(
            "story-creation stage-2 conflict adjudication has no create-time LLM "
            "owner wired (AG3-065/AG3-070; the StructuredEvaluator is story-"
            "execution scoped, needing a live StoryContext + run_id that do not "
            "exist before the story is created). Above-threshold similarity "
            "candidates cannot be adjudicated, so the create is BLOCKED fail-"
            "closed (FK-21 §21.4.3) -- no silent pass, no dummy verdict."
        )


class _ConfigRolePoolResolver:
    """Config-faithful ``RolePoolResolver`` for the create-time conflict role.

    Implements the FK-75 §75.3 ``RolePoolResolver`` surface
    (:meth:`resolve(role) -> HubBackendName`) by reading the
    ``pipeline.llm_roles.story_creation_review`` pool assignment from the target
    project's config. The routing OWNER is the config (AG3-070), not the LLM
    transport. A role with no configured pool -- or a pool string that is not a
    valid :data:`~agentkit.multi_llm_hub.entities.HubBackendName` -- fails closed
    with :class:`LlmClientError` (FK-75 §75.3: no default pool, never a silent
    fallback). This resolver intentionally serves ONLY the create-time
    ``story_creation_review`` role: any other role is rejected fail-closed so the
    create-scope transport cannot be reused for an execution role.

    Attributes:
        _pool: The validated ``story_creation_review`` pool name.
    """

    def __init__(self, *, story_creation_review_pool: HubBackendName) -> None:
        """Initialise the resolver with the validated create-time pool.

        Args:
            story_creation_review_pool: The validated Hub pool name assigned to
                the ``story_creation_review`` role.
        """
        self._pool = story_creation_review_pool

    def resolve(self, role: str) -> HubBackendName:
        """Resolve the ``story_creation_review`` role to its configured pool.

        Args:
            role: The reviewer role wire-string. Must be
                ``"story_creation_review"`` (the only create-time role).

        Returns:
            The configured :data:`HubBackendName` for the create-time role.

        Raises:
            LlmClientError: When ``role`` is not the create-time role (fail-closed:
                this resolver does not serve execution roles).
        """
        if role != "story_creation_review":
            raise LlmClientError(
                "create-time RolePoolResolver only serves role "
                f"'story_creation_review'; got {role!r} (fail-closed, no default "
                "pool, FK-75 §75.3)."
            )
        return self._pool


def build_create_time_conflict_evaluator(
    project_config: ProjectConfig,
) -> ConflictEvaluatorPort | None:
    """Build the real create-time conflict adjudicator from the project config.

    Wires the REAL FK-21 §21.4.1 Schritt 3 conflict assessment (AG3-115's
    :class:`~agentkit.story_creation.conflict_adjudicator.CreateTimeConflictAdjudicator`)
    over the FK-65 / FK-11 :class:`~agentkit.verify_system.llm_evaluator.llm_client.HubLlmClient`
    transport. The Hub base URL is resolved via
    :func:`~agentkit.multi_llm_hub.config.load_multi_llm_hub_config` (the SAME
    transport the rest of the LLM-evaluation path uses) and the
    ``story_creation_review`` role -> pool routing is read from
    ``pipeline.llm_roles.story_creation_review`` via :class:`_ConfigRolePoolResolver`
    (FK-75 §75.3).

    Args:
        project_config: The loaded target-project config (carries the
            ``pipeline.llm_roles`` role->pool assignments).

    Returns:
        A wired :class:`CreateTimeConflictAdjudicator` (typed as the
        ``ConflictEvaluatorPort`` slot the reconciler injects), or ``None`` when
        the config assigns NO valid ``story_creation_review`` pool -- in which case
        the caller falls back to the truthful :class:`FailClosedConflictEvaluator`
        (``conflict_adjudication_unavailable``), never a silent pass.
    """
    llm_roles = project_config.pipeline.llm_roles
    if llm_roles is None:
        return None
    pool_name = llm_roles.story_creation_review
    if pool_name is None or pool_name not in get_args(HubBackendName):
        # No (valid) create-time pool configured: the real adjudicator cannot be
        # built. The caller falls back to FailClosedConflictEvaluator (truthful
        # conflict_adjudication_unavailable), not a silent pass.
        return None

    from agentkit.multi_llm_hub.client import HubClient
    from agentkit.multi_llm_hub.config import load_multi_llm_hub_config
    from agentkit.story_creation.conflict_adjudicator import (
        CreateTimeConflictAdjudicator,
    )
    from agentkit.verify_system.llm_evaluator.llm_client import HubLlmClient

    hub = HubClient(load_multi_llm_hub_config().base_url)
    # pool_name was validated against get_args(HubBackendName) above; the cast
    # records that runtime narrowing for the type checker (the Literal cannot be
    # statically narrowed from a config ``str``).
    resolver = _ConfigRolePoolResolver(
        story_creation_review_pool=cast("HubBackendName", pool_name),
    )
    llm_client = HubLlmClient(hub, resolver, owner="agentkit-story-creation")
    return CreateTimeConflictAdjudicator(llm_client)


def build_story_creation_reconciler(
    *,
    project_config: ProjectConfig,
    conflict_evaluator: ConflictEvaluatorPort | None = None,
) -> StoryCreationReconciler:
    """Build the real reconcile runtime from the target project's config.

    Wires the real Weaviate adapter (stage 1, the fail-closed gate) from
    ``project_config.vectordb``. Stage 2 uses the injected ``conflict_evaluator``;
    when none is supplied the factory builds the REAL
    :class:`~agentkit.story_creation.conflict_adjudicator.CreateTimeConflictAdjudicator`
    from the config's ``story_creation_review`` pool assignment (FK-21 §21.4.1
    Schritt 3). When NO valid create-time pool is configured it falls back to the
    truthful :class:`FailClosedConflictEvaluator` so an above-threshold conflict
    fail-closes (``conflict_adjudication_unavailable``) instead of silently
    passing. No local ``StoryService`` is wired -- the agent path uses
    :meth:`StoryCreationReconciler.reconcile_only` and persists at the
    Control-Plane boundary via the official client.

    Args:
        project_config: The loaded target-project config (carries ``vectordb``
            host/port + tuning, ``repositories[]`` for repo-affinity and
            ``pipeline.llm_roles`` for the create-time conflict-pool routing).
        conflict_evaluator: Optional productive stage-2 evaluator; defaults to the
            real config-wired adjudicator, falling back to a fail-closed evaluator.

    Returns:
        A configured :class:`StoryCreationReconciler` (reconcile-only ready).

    Raises:
        VectorDbUnavailableError: When ``vectordb`` host/port are not configured
            (the VectorDB is mandatory infrastructure for story creation, FK-13
            §13.2 / FK-21 §21.4.3) -- fail-closed, never a silent skip.
    """
    vectordb: VectorDbConfig | None = project_config.pipeline.vectordb
    if vectordb is None or vectordb.host is None or vectordb.port is None:
        raise VectorDbUnavailableError(
            "vectordb.host/port are not configured; the VectorDB is mandatory "
            "for story creation (FK-13 §13.2 / FK-21 §21.4.3). Story creation "
            "fails closed -- no creation without the reconciliation runtime."
        )

    adapter = WeaviateStoryAdapter.connect(host=vectordb.host, port=vectordb.port)
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
        evaluator = build_create_time_conflict_evaluator(project_config)
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
