"""Two-stage VectorDB story reconciliation (FK-13 §13.5 / FK-21 §21.4).

Deterministic app-layer component (NOT in ``integrations/``):

* **Stage 1 -- similarity filter:** ``story_search(search_mode="hybrid",
  project_id, limit=20)`` via the thin Weaviate adapter, then drop every hit
  with ``score < vectordb.similarity_threshold`` (default 0.7).
* **Stage 2 -- LLM conflict evaluation:** the top ``vectordb.max_llm_candidates``
  (default 5) surviving hits are evaluated by the EXISTING
  :class:`StructuredEvaluator` with role ``story_creation_review``, check
  ``conflict_assessment``, template ``vectordb-conflict`` -- there is no second
  LLM-evaluator path.

Fail-closed: a Weaviate outage raises (never a silent empty result, FK-21
§21.4.3). The reconciliation emits exactly one ``VECTORDB_SEARCH`` telemetry
event with the existing mandatory payload contract (FK-61 §61.12.1).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from agentkit.verify_system.llm_evaluator.roles import LlmVerdict, ReviewerRole

if TYPE_CHECKING:
    from agentkit.config.models import VectorDbConfig
    from agentkit.integrations.vectordb import StorySearchHit, WeaviateStoryAdapter
    from agentkit.telemetry.emitters import EventEmitter
    from agentkit.verify_system.llm_evaluator.bundle import ReviewBundle
    from agentkit.verify_system.llm_evaluator.structured_evaluator import (
        StructuredEvaluatorResult,
    )


@runtime_checkable
class ConflictEvaluatorPort(Protocol):
    """Thin seam over the EXISTING ``StructuredEvaluator.evaluate`` surface.

    Injected so the reconciliation depends on the role-based evaluator contract
    without reaching into LLM transport wiring (owned by AG3-065). A test double
    with the same surface satisfies the mocks exception (LLM boundary only).
    """

    def evaluate(
        self,
        role: ReviewerRole,
        bundle: ReviewBundle,
        previous_findings: list[object] | None,
        qa_cycle_round: int,
    ) -> StructuredEvaluatorResult:
        """Run one role evaluation; return the validated result."""
        ...


@dataclass(frozen=True)
class ReconciliationResult:
    """Typed outcome of the two-stage reconciliation.

    Attributes:
        verdict: ``PASS`` (no conflict) or ``FAIL`` (duplicate / overlap) from
            stage 2; ``PASS`` when stage 1 cleared all candidates so stage 2 was
            not run.
        total_hits: Number of raw hits returned by ``story_search`` (stage 1).
        hits_above_threshold: Hits with ``score >= similarity_threshold``.
        candidates_evaluated: Number of candidates sent to the LLM (capped at
            ``max_llm_candidates``).
        hits_classified_conflict: ``1`` when stage 2 returned ``FAIL``, else ``0``.
        threshold_value: The applied similarity threshold (audit).
        conflict_candidates: The story-ids of the candidates that were evaluated
            for a conflict (the stage-2 input set).
    """

    verdict: LlmVerdict
    total_hits: int
    hits_above_threshold: int
    candidates_evaluated: int
    hits_classified_conflict: int
    threshold_value: float
    conflict_candidates: tuple[str, ...]


#: The fixed search mode of the stage-1 similarity search (FK-21 §21.4.1
#: Schritt 1: ``story_search(search_mode="hybrid", ...)``). Surfaced as the
#: ``search_mode`` field of the §21.4.2 abgleich protocol.
RECONCILIATION_SEARCH_MODE: str = "hybrid"


@dataclass(frozen=True)
class AbgleichProtocol:
    """Typed FK-21 §21.4.2 abgleich-protocol counters (no new shadow schema).

    A pure, owner-faithful projection of the existing typed
    :class:`ReconciliationResult` onto the FK-21 §21.4.2 protocol wire keys
    (``total_hits`` / ``above_threshold`` / ``sent_to_llm`` / ``llm_conflicts`` /
    ``threshold_used`` / ``search_mode``). It carries no second source of truth:
    every field is read from the reconciliation result that the counter owner
    (:class:`VectorDbReconciliation`) already produced. It exists so the §21.4.2
    counters are available as a *typed* set (story.md §2.1.4 / guardrail
    "TYPISIERT STATT STRINGS") and fits the ``ReconciliationEvidence`` / abgleich
    protocol rather than an ad-hoc dict.

    Attributes:
        total_hits: Raw ``story_search`` hit count (stage 1).
        above_threshold: Hits with ``score >= similarity_threshold``.
        sent_to_llm: Candidates handed to the LLM (capped at
            ``max_llm_candidates``).
        llm_conflicts: ``1`` when stage 2 returned ``FAIL``, else ``0``.
        threshold_used: The applied similarity threshold.
        search_mode: The stage-1 search mode (always ``"hybrid"``).
    """

    total_hits: int
    above_threshold: int
    sent_to_llm: int
    llm_conflicts: int
    threshold_used: float
    search_mode: str

    @classmethod
    def from_result(cls, result: ReconciliationResult) -> AbgleichProtocol:
        """Project a :class:`ReconciliationResult` onto the §21.4.2 counters.

        Args:
            result: The two-stage reconciliation result (the counter owner).

        Returns:
            The typed §21.4.2 abgleich-protocol counters.
        """
        return cls(
            total_hits=result.total_hits,
            above_threshold=result.hits_above_threshold,
            sent_to_llm=result.candidates_evaluated,
            llm_conflicts=result.hits_classified_conflict,
            threshold_used=result.threshold_value,
            search_mode=RECONCILIATION_SEARCH_MODE,
        )

    def to_wire(self) -> dict[str, object]:
        """Return the §21.4.2 protocol as its canonical wire-key dict (audit).

        Returns:
            The exact FK-21 §21.4.2 keys: ``total_hits``, ``above_threshold``,
            ``sent_to_llm``, ``llm_conflicts``, ``threshold_used``,
            ``search_mode``.
        """
        return {
            "total_hits": self.total_hits,
            "above_threshold": self.above_threshold,
            "sent_to_llm": self.sent_to_llm,
            "llm_conflicts": self.llm_conflicts,
            "threshold_used": self.threshold_used,
            "search_mode": self.search_mode,
        }


def resolve_vectordb_conflict_flag(
    *,
    verdict: LlmVerdict,
    story_was_adapted: bool,
) -> bool:
    """Producer rule for ``vectordb_conflict_resolved`` (FK-21 §21.12 / §21.4.1).

    The flag is ``True`` ONLY when stage 2 reported a ``FAIL`` conflict AND the
    conflict was resolved by ADAPTING (not discarding) the story. A ``PASS`` or
    an unresolved / unadapted conflict leaves it ``False`` (fail-closed).

    Args:
        verdict: The stage-2 verdict.
        story_was_adapted: Whether the story creator resolved the detected
            conflict by adapting (not discarding) the story.

    Returns:
        ``True`` only for an adapted, resolved ``FAIL`` conflict; ``False``
        otherwise.
    """
    return verdict is LlmVerdict.FAIL and story_was_adapted


class VectorDbReconciliation:
    """Runs the deterministic two-stage story reconciliation (FK-21 §21.4)."""

    def __init__(
        self,
        adapter: WeaviateStoryAdapter,
        evaluator: ConflictEvaluatorPort,
        config: VectorDbConfig,
        *,
        event_emitter: EventEmitter | None = None,
    ) -> None:
        """Initialise the reconciliation.

        Args:
            adapter: The thin Weaviate transport adapter (stage 1).
            evaluator: The EXISTING structured-evaluator surface (stage 2).
            config: The CONSUMED ``vectordb`` config (owner: AG3-070) carrying
                ``similarity_threshold`` and ``max_llm_candidates``.
            event_emitter: Optional emitter for the ``VECTORDB_SEARCH`` event.
        """
        self._adapter = adapter
        self._evaluator = evaluator
        self._config = config
        self._event_emitter = event_emitter

    def reconcile(
        self,
        *,
        story_id: str,
        story_description: str,
        project_id: str,
    ) -> ReconciliationResult:
        """Run stage 1 + stage 2 and emit telemetry.

        Args:
            story_id: Display-ID of the new story being created.
            story_description: The new story description (the search query and
                the stage-2 ``new_story`` context).
            project_id: Project-prefix scope for ``story_search`` (FK-21 §21.4.1).

        Returns:
            The typed :class:`ReconciliationResult`.

        Raises:
            VectorDbUnavailableError: When Weaviate is unreachable (fail-closed;
                propagated from the adapter, never a silent empty result).
        """
        hits = self._adapter.story_search(
            story_description, project_id=project_id, limit=20
        )
        threshold = self._config.similarity_threshold
        above = [hit for hit in hits if hit.score >= threshold]
        # Deterministic order: score desc, then story_id asc for ties.
        above.sort(key=lambda hit: (-hit.score, hit.story_id))
        candidates = above[: self._config.max_llm_candidates]

        verdict = LlmVerdict.PASS
        if candidates:
            verdict = self._evaluate_conflict(
                story_id=story_id,
                story_description=story_description,
                candidates=candidates,
            )

        hits_classified_conflict = 1 if verdict is LlmVerdict.FAIL else 0
        result = ReconciliationResult(
            verdict=verdict,
            total_hits=len(hits),
            hits_above_threshold=len(above),
            candidates_evaluated=len(candidates),
            hits_classified_conflict=hits_classified_conflict,
            threshold_value=threshold,
            conflict_candidates=tuple(hit.story_id for hit in candidates),
        )
        self._emit_search_event(story_id=story_id, result=result)
        return result

    def _evaluate_conflict(
        self,
        *,
        story_id: str,
        story_description: str,
        candidates: list[StorySearchHit],
    ) -> LlmVerdict:
        """Run stage 2 via the existing structured evaluator (1 check)."""
        bundle = self._build_bundle(
            story_id=story_id,
            story_description=story_description,
            candidates=candidates,
        )
        evaluation = self._evaluator.evaluate(
            ReviewerRole.STORY_CREATION_REVIEW,
            bundle,
            None,
            1,
        )
        return evaluation.verdict

    @staticmethod
    def _build_bundle(
        *,
        story_id: str,
        story_description: str,
        candidates: list[StorySearchHit],
    ) -> ReviewBundle:
        """Build the evaluator bundle carrying ``new_story`` + ``candidates``."""
        from agentkit.verify_system.llm_evaluator.bundle import ReviewBundle

        candidate_lines = [
            f"- {hit.story_id} (score={hit.score:.3f}): {hit.title} -- {hit.snippet}"
            for hit in candidates
        ]
        diff_content = "## Candidates\n" + "\n".join(candidate_lines)
        return ReviewBundle(
            story_id=story_id,
            story_brief_excerpt=story_description,
            acceptance_criteria=[],
            diff_summary=f"{len(candidates)} similarity candidate(s) above threshold",
            diff_content=diff_content,
            concept_refs=[hit.story_id for hit in candidates],
            previous_findings=None,
            qa_cycle_round=1,
        )

    def _emit_search_event(
        self,
        *,
        story_id: str,
        result: ReconciliationResult,
    ) -> None:
        """Emit the single ``VECTORDB_SEARCH`` event (FK-21 §21.4.2).

        Uses the EXISTING event type with its EXISTING mandatory payload
        contract (``total_hits``, ``hits_above_threshold``,
        ``hits_classified_conflict``, ``threshold_value``). No new event type,
        no second log format. Telemetry never blocks the pipeline.
        """
        if self._event_emitter is None:
            return
        from agentkit.telemetry.events import Event, EventType

        event = Event(
            story_id=story_id,
            event_type=EventType.VECTORDB_SEARCH,
            source_component="vectordb_reconciliation",
            payload={
                "total_hits": result.total_hits,
                "hits_above_threshold": result.hits_above_threshold,
                "hits_classified_conflict": result.hits_classified_conflict,
                "threshold_value": result.threshold_value,
            },
        )
        self._event_emitter.emit(event)


__all__ = [
    "RECONCILIATION_SEARCH_MODE",
    "AbgleichProtocol",
    "ConflictEvaluatorPort",
    "ReconciliationResult",
    "VectorDbReconciliation",
    "resolve_vectordb_conflict_flag",
]
