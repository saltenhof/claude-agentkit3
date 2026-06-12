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
    AbgleichProtocol,
    ReconciliationResult,
    VectorDbReconciliation,
)

if TYPE_CHECKING:
    from agentkit.config.models import ProjectConfig, VectorDbConfig
    from agentkit.control_plane.models import CreateStoryInputs
    from agentkit.integrations.vectordb import WeaviateStoryAdapter
    from agentkit.story_context_manager.service import StoryService

    # ``CreateStoryInput`` is explicitly re-exported (``as``) so the ProjectEdge
    # boundary can type its reconcile entry point through this create-flow surface
    # without importing the ``story_context_manager`` component directly (AC010).
    from agentkit.story_context_manager.story_model import (
        CreateStoryInput as CreateStoryInput,
    )
    from agentkit.story_context_manager.story_model import Story
    from agentkit.story_creation.vectordb_reconciliation import ConflictEvaluatorPort
    from agentkit.telemetry.emitters import EventEmitter


@dataclass(frozen=True)
class ReconciliationOutcome:
    """Typed outcome of a reconcile-only run (no persistence).

    Produced by :meth:`StoryCreationReconciler.reconcile_only` for the
    agent-facing create path (FK-91 §91.1a Regel #3): the agent runs the real
    fail-closed reconciliation, obtains the self-validating evidence here, then
    submits it with ``POST /v1/stories`` through the official client. The
    reconciliation is NOT persisted in-process on this path — the authoritative
    create happens at the Control-Plane boundary, which re-enforces the evidence.

    Attributes:
        evidence: The typed, self-validating reconciliation evidence the create
            boundary requires (FK-21 §21.4/§21.12).
        reconciliation: The raw two-stage reconciliation result (audit).
        participating_repos: The resolved repo set (post repo-affinity) that the
            create request should carry; it also rides on the evidence.
        used_affinity_proposal: ``True`` when the derived affinity proposal was
            applied; ``False`` when the caller-supplied repo set was honoured
            (human-correction, §21.9.2) or no proposal resolved.
    """

    evidence: ReconciliationEvidence
    reconciliation: ReconciliationResult
    participating_repos: tuple[str, ...]
    used_affinity_proposal: bool


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
        adapter: WeaviateStoryAdapter,
        evaluator: ConflictEvaluatorPort,
        vectordb_config: VectorDbConfig,
        project_config: ProjectConfig,
        story_service: StoryService | None = None,
        event_emitter: EventEmitter | None = None,
    ) -> None:
        """Initialise the reconciler.

        Args:
            story_service: The authoritative story lifecycle service (FK-91).
                Required ONLY for the in-process :meth:`create_story` (Zone-2/admin
                exemption, FK-21 §21.13.2). The agent-facing path uses
                :meth:`reconcile_only` (no in-process persistence) and may leave
                this ``None`` -- the authoritative create then happens at the
                Control-Plane boundary via the official client.
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
            RuntimeError: When the reconciler was constructed without a
                ``story_service`` (the in-process create path is unavailable; the
                agent-facing path must use :meth:`reconcile_only` + the client).
        """
        if self._story_service is None:
            raise RuntimeError(
                "in-process create_story requires a story_service; the "
                "agent-facing path must use reconcile_only + ProjectEdgeClient"
            )

        outcome = self.reconcile_only(
            request,
            story_body=story_body,
            story_was_adapted=story_was_adapted,
            story_display_id=story_display_id,
        )

        conflict_resolved = outcome.evidence.vectordb_conflict_resolved
        final_request = request.model_copy(
            update={
                "vectordb_conflict_resolved": conflict_resolved,
                "repos": list(outcome.participating_repos),
            }
        )

        story = self._story_service.create_story(
            final_request,
            op_id=op_id,
            correlation_id=correlation_id,
        )

        return StoryCreationOutcome(
            story=story,
            reconciliation=outcome.reconciliation,
            vectordb_conflict_resolved=conflict_resolved,
            participating_repos=tuple(story.participating_repos),
            used_affinity_proposal=outcome.used_affinity_proposal,
            evidence=outcome.evidence,
        )

    def reconcile_only(
        self,
        request: CreateStoryInput,
        *,
        story_body: str,
        story_was_adapted: bool = False,
        story_display_id: str = "",
    ) -> ReconciliationOutcome:
        """Run the fail-closed reconciliation + affinity and PRODUCE evidence.

        This is the reachable reconcile surface the agent-facing create path
        (FK-91 §91.1a Regel #3) needs: it runs the REAL two-stage VectorDB
        reconciliation (FK-21 §21.4) and the repo-affinity derivation (§21.9),
        then builds the self-validating :class:`ReconciliationEvidence` — WITHOUT
        persisting any story. The agent submits the returned evidence with
        ``POST /v1/stories`` through the official client; the Control-Plane
        boundary is the single authoritative create (it re-enforces the evidence
        fail-closed). There is therefore no second story-creation truth here.

        A Weaviate outage raises (``VectorDbUnavailableError``) before any
        evidence is produced, so the agent path fail-closes BEFORE the create
        call — never a dummy / skipped evidence (FK-21 §21.4.3).

        Args:
            request: The base ``CreateStoryInput`` (master data from the caller);
                its ``repos`` may be overridden by the affinity proposal.
            story_body: The full story markdown body (reconciliation query +
                repo-affinity strong-evidence source).
            story_was_adapted: Whether a detected stage-2 conflict was resolved by
                ADAPTING (not discarding) the story (FK-21 §21.4.1).
            story_display_id: Optional display-ID for the search query scope /
                telemetry; the project prefix scopes the search.

        Returns:
            A :class:`ReconciliationOutcome` carrying the typed evidence, the raw
            reconciliation result and the resolved ``participating_repos``.

        Raises:
            VectorDbUnavailableError: When Weaviate is unreachable -- the agent
                create path is BLOCKED fail-closed (FK-21 §21.4.3).
        """
        # Stage 1+2 reconciliation. A Weaviate outage raises here and aborts the
        # whole create (fail-closed, AC2).
        reconciliation = self._reconciliation.reconcile(
            story_id=story_display_id or request.title,
            story_description=story_body,
            project_id=request.project_key,
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

        # Build the typed reconciliation evidence (FK-21 §21.4/§21.12). This is
        # the proof the agent-facing create boundary (POST /v1/stories) requires;
        # it grounds the conflict flag + affinity in the actual reconciliation
        # outcome so the persisted story cannot diverge from it (FIX-THE-MODEL).
        #
        # The §21.4.2 abgleich-protocol counters (incl. ``sent_to_llm`` and
        # ``search_mode``) are projected from the reconciliation result via the
        # owner-faithful ``AbgleichProtocol`` so the full §21.4.2 counter set is
        # carried through the AUTHORITATIVE evidence path -- no second/shadow
        # schema, the protocol is genuinely produced in the real flow.
        protocol = AbgleichProtocol.from_result(reconciliation)
        evidence = ReconciliationEvidence(
            weaviate_ready=True,
            total_hits=protocol.total_hits,
            hits_above_threshold=protocol.above_threshold,
            candidates_evaluated=protocol.sent_to_llm,
            hits_classified_conflict=protocol.llm_conflicts,
            threshold_value=protocol.threshold_used,
            search_mode=protocol.search_mode,
            verdict=reconciliation.verdict,
            story_was_adapted=story_was_adapted,
            participating_repos=tuple(repos),
        )

        return ReconciliationOutcome(
            evidence=evidence,
            reconciliation=reconciliation,
            participating_repos=tuple(repos),
            used_affinity_proposal=used_proposal,
        )

    def reconcile_only_from_inputs(
        self,
        inputs: CreateStoryInputs,
        *,
        story_body: str,
        story_was_adapted: bool = False,
        story_display_id: str = "",
    ) -> ReconciliationOutcome:
        """Reconcile from the agent-facing ``CreateStoryInputs`` master data.

        The agent-facing create surface (FK-91 §91.1a Regel #3) carries a SINGLE
        ``CreateStoryInputs`` master object that is BOTH reconciled and persisted.
        This method derives the reconciler's ``CreateStoryInput`` INTERNALLY from
        that one object, so the ProjectEdge boundary never has to construct a
        second input (it would otherwise have to import ``story_context_manager``,
        violating architecture-conformance AC010) and there is no split-input seam
        where a caller could reconcile object A while object B is persisted (FK-21
        §21.4 SSOT, FIX-THE-MODEL / Codex R2 finding #2). ``CreateStoryInput``
        accepts the SAME wire keys (with the ``type`` alias and enum coercion), so
        the by-alias round-trip of the master data introduces no second source of
        truth.

        Args:
            inputs: The single typed story master data the create surface carries
                (no reconciliation evidence). Both the reconciliation query / repo-
                affinity scope and the persisted body derive from this one object.
            story_body: The full story markdown body (reconciliation query + repo-
                affinity strong-evidence source).
            story_was_adapted: Whether a detected stage-2 conflict was resolved by
                ADAPTING (not discarding) the story (FK-21 §21.4.1).
            story_display_id: Optional display-ID for the search query scope /
                telemetry; the project prefix scopes the search.

        Returns:
            A :class:`ReconciliationOutcome` carrying the typed evidence, the raw
            reconciliation result and the resolved ``participating_repos``.

        Raises:
            VectorDbUnavailableError: When Weaviate is unreachable -- the agent
                create path is BLOCKED fail-closed (FK-21 §21.4.3).
        """
        # ``CreateStoryInput`` is constructed HERE, inside the ``story_creation``
        # owner, from the single master-data object (function-local import keeps the
        # module-level import set unchanged). The by-alias dump round-trips the wire
        # keys (``type`` alias + enum coercion) so no second master source exists.
        from agentkit.story_context_manager.story_model import CreateStoryInput

        # ``exclude_none`` so optional fields the caller left unset (``size`` /
        # ``change_impact`` / ``concept_quality`` / ``risk``, which default to
        # ``None`` on ``CreateStoryInputs``) fall through to ``CreateStoryInput``'s
        # own typed defaults instead of an explicit ``None`` overriding them (the
        # same convention the persisted wire body uses, ``to_wire_body``).
        request = CreateStoryInput.model_validate(
            inputs.model_dump(by_alias=True, exclude_none=True)
        )
        return self.reconcile_only(
            request,
            story_body=story_body,
            story_was_adapted=story_was_adapted,
            story_display_id=story_display_id,
        )


__all__ = [
    "ReconciliationOutcome",
    "StoryCreationOutcome",
    "StoryCreationReconciler",
]
