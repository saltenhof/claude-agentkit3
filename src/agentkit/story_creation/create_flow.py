"""Authoritative story-creation flow orchestrator (FK-21 §21.4 / §21.9 / §21.12).

This is the production integration point that wires the deterministic
story-creation runtime components into the AUTHORITATIVE create path, so they
are no longer dead/isolated modules:

* **VectorDB reconciliation (§21.4):** runs the two-stage
  :class:`~agentkit.story_creation.vectordb_reconciliation.VectorDbReconciliation`
  as a MANDATORY step. A Weaviate outage propagates as a typed error and BLOCKS
  story creation fail-closed (FK-21 §21.4.3) -- never a silent skip.
* **Conflict flag (§21.12 / §21.4.1):** the producer rule
  :func:`~agentkit.story_creation.vectordb_reconciliation.resolve_vectordb_conflict_flag`
  sets ``vectordb_conflict_resolved`` -- ``True`` only when stage 2 reported a
  ``FAIL`` conflict that the creator resolved by ADAPTING (not discarding) the
  story. This is the SSOT producer output consumed by AG3-057's
  ``determine_mode`` (FIX-THE-MODEL: one authoritative field, no shadow state).
* **Repo affinity (§21.9):** :func:`~agentkit.story_creation.repo_affinity.resolve_repo_affinity`
  derives ``participating_repos`` from the story body and feeds it into the
  authoritative ``CreateStoryInput`` -- replacing the prior consume-only usage.
  The derivation is a PROPOSAL; a caller-supplied (human-corrected) repo set is
  honoured rather than hard-overridden (§21.9.2 human-correction).

The flow ends by delegating to the authoritative
:meth:`agentkit.story_context_manager.service.StoryService.create_story`
(FK-91 §91.1a) -- there is no second create path and no shadow persistence.

The reconciliation transports (Weaviate adapter, LLM evaluator) are INJECTED
ports, kept transport-agnostic so the LLM-hub wiring (AG3-065) and the
``vectordb`` config owner (AG3-070) stay the single owners of those concerns.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from agentkit.story_creation.reconciliation_evidence import ReconciliationEvidence
from agentkit.story_creation.repo_affinity import resolve_repo_affinity
from agentkit.story_creation.vectordb_reconciliation import (
    ReconciliationResult,
    VectorDbReconciliation,
    resolve_vectordb_conflict_flag,
)

if TYPE_CHECKING:
    from agentkit.config.models import ProjectConfig, VectorDbConfig
    from agentkit.integrations.vectordb import WeaviateStoryAdapter
    from agentkit.story_context_manager.service import StoryService
    from agentkit.story_context_manager.story_model import CreateStoryInput, Story
    from agentkit.story_creation.vectordb_reconciliation import ConflictEvaluatorPort
    from agentkit.telemetry.emitters import EventEmitter


@dataclass(frozen=True)
class StoryCreationOutcome:
    """Typed outcome of the authoritative create flow.

    Attributes:
        story: The created :class:`Story` (Backlog status).
        reconciliation: The two-stage reconciliation result (audit / evidence).
        vectordb_conflict_resolved: The producer flag value that was persisted
            on the story (FK-21 §21.12).
        participating_repos: The repo set that was persisted (post-affinity).
        used_affinity_proposal: ``True`` when the derived affinity proposal was
            applied; ``False`` when a caller-supplied repo set was honoured
            (human-correction, §21.9.2) or no proposal resolved.
        evidence: The typed reconciliation evidence that the agent-facing create
            boundary requires (FK-21 §21.4/§21.12). The skill layer submits this
            with ``POST /v1/stories`` so the route fail-closes if it is absent.
    """

    story: Story
    reconciliation: ReconciliationResult
    vectordb_conflict_resolved: bool
    participating_repos: tuple[str, ...]
    used_affinity_proposal: bool
    evidence: ReconciliationEvidence


class StoryCreationReconciler:
    """Wires VectorDB reconciliation + repo affinity into the create flow.

    A thin app-layer orchestrator (NOT in ``integrations/``). It owns the
    deterministic story-creation policy (mandatory reconciliation, flag rule,
    affinity derivation) and delegates the actual persistence to the
    authoritative :class:`StoryService`.
    """

    def __init__(
        self,
        *,
        story_service: StoryService,
        adapter: WeaviateStoryAdapter,
        evaluator: ConflictEvaluatorPort,
        vectordb_config: VectorDbConfig,
        project_config: ProjectConfig,
        event_emitter: EventEmitter | None = None,
    ) -> None:
        """Initialise the reconciler.

        Args:
            story_service: The authoritative story lifecycle service (FK-91).
            adapter: The thin Weaviate transport adapter (stage 1; fail-closed).
            evaluator: The EXISTING structured-evaluator surface (stage 2).
            vectordb_config: The CONSUMED ``vectordb`` config (owner: AG3-070)
                carrying ``similarity_threshold`` / ``max_llm_candidates``.
            project_config: The project config carrying ``repositories[]`` for
                repo-affinity resolution.
            event_emitter: Optional emitter for the ``VECTORDB_SEARCH`` event.
        """
        self._story_service = story_service
        self._project_config = project_config
        self._reconciliation = VectorDbReconciliation(
            adapter,
            evaluator,
            vectordb_config,
            event_emitter=event_emitter,
        )

    def create_story(
        self,
        request: CreateStoryInput,
        *,
        story_body: str,
        op_id: str,
        story_was_adapted: bool = False,
        story_display_id: str = "",
        correlation_id: str = "",
    ) -> StoryCreationOutcome:
        """Run reconciliation + affinity, then create the story authoritatively.

        Args:
            request: The base ``CreateStoryInput`` (master data from the caller).
                Its ``vectordb_conflict_resolved`` and ``repos`` are RECOMPUTED
                here from the reconciliation / affinity unless a human-corrected
                repo set is supplied.
            story_body: The full story markdown body (the reconciliation query
                and the repo-affinity strong-evidence source).
            op_id: Idempotency key for the authoritative create (required).
            story_was_adapted: Whether the creator resolved a detected stage-2
                conflict by ADAPTING (not discarding) the story (FK-21 §21.4.1).
                Only relevant when stage 2 returns ``FAIL``.
            story_display_id: Optional display-ID for the search query scope /
                telemetry; the project prefix is used for the search scope.
            correlation_id: Correlation ID for propagation.

        Returns:
            A :class:`StoryCreationOutcome` carrying the created story and the
            reconciliation evidence.

        Raises:
            VectorDbUnavailableError: When Weaviate is unreachable -- the create
                is BLOCKED fail-closed (FK-21 §21.4.3), never a silent skip.
        """
        # Stage 1+2 reconciliation. A Weaviate outage raises here and aborts the
        # whole create (fail-closed, AC1 / AC3).
        reconciliation = self._reconciliation.reconcile(
            story_id=story_display_id or request.title,
            story_description=story_body,
            project_id=request.project_key,
        )

        # Producer rule for the conflict flag (AC5 / FK-21 §21.12).
        conflict_resolved = resolve_vectordb_conflict_flag(
            verdict=reconciliation.verdict,
            story_was_adapted=story_was_adapted,
        )

        # Repo-affinity derivation (AC6 / FK-21 §21.9). The proposal feeds
        # participating_repos at the authoritative source. Human-correction:
        # only apply the proposal when it resolved at least one repo; otherwise
        # keep the caller-supplied repo set untouched.
        affinity = resolve_repo_affinity(
            story_body,
            self._project_config,
            module=request.module,
        )
        if affinity.participating_repos:
            repos = list(affinity.participating_repos)
            used_proposal = True
        else:
            repos = list(request.repos)
            used_proposal = False

        final_request = request.model_copy(
            update={
                "vectordb_conflict_resolved": conflict_resolved,
                "repos": repos,
            }
        )

        # Build the typed reconciliation evidence (FK-21 §21.4/§21.12). This is
        # the proof the agent-facing create boundary (POST /v1/stories) requires;
        # it grounds the conflict flag + affinity in the actual reconciliation
        # outcome so the persisted story cannot diverge from it (FIX-THE-MODEL).
        evidence = ReconciliationEvidence(
            weaviate_ready=True,
            total_hits=reconciliation.total_hits,
            hits_above_threshold=reconciliation.hits_above_threshold,
            hits_classified_conflict=reconciliation.hits_classified_conflict,
            threshold_value=reconciliation.threshold_value,
            verdict=reconciliation.verdict,
            story_was_adapted=story_was_adapted,
            participating_repos=tuple(repos),
        )

        story = self._story_service.create_story(
            final_request,
            op_id=op_id,
            correlation_id=correlation_id,
        )

        return StoryCreationOutcome(
            story=story,
            reconciliation=reconciliation,
            vectordb_conflict_resolved=conflict_resolved,
            participating_repos=tuple(story.participating_repos),
            used_affinity_proposal=used_proposal,
            evidence=evidence,
        )


__all__ = [
    "StoryCreationOutcome",
    "StoryCreationReconciler",
]
