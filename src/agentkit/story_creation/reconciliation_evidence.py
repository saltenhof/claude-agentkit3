"""Reconciliation evidence — the fail-closed precondition for story creation.

The interactive two-stage VectorDB reconciliation (FK-21 §21.4) and the human
conflict-resolution loop run in the ``create-userstory`` skill layer (FK-21 §21.1
"primarily skill-driven", §21.13). The agent-facing HTTP create path
(``POST /v1/stories``) must therefore NOT be able to persist a story without
proof that the deterministic, fail-closed reconciliation actually ran. This
module owns that proof as a typed, self-validating model.

:class:`ReconciliationEvidence` is the SINGLE SOURCE OF TRUTH for the
reconciliation outcome (FIX-THE-MODEL): it is produced by the deterministic
reconciliation runtime
(:class:`~agentkit.story_creation.create_flow.StoryCreationReconciler`) and
consumed as a mandatory precondition by the authoritative create boundary. It
carries:

* ``weaviate_ready`` — whether the Weaviate readiness/search step succeeded.
  A Weaviate outage means the skill could not produce ``True`` here, so the
  create boundary fail-closes (FK-21 §21.4.3) — never a silent skip.
* the four mandatory ``VECTORDB_SEARCH`` telemetry counters (FK-21 §21.4.2) —
  proof that ``story_search`` was actually performed.
* ``verdict`` + ``story_was_adapted`` — the grounded inputs of the
  ``vectordb_conflict_resolved`` producer rule (FK-21 §21.12), so the flag can
  never be asserted without a reconciliation outcome behind it.
* ``participating_repos`` — the repo-affinity result (FK-21 §21.9) that feeds
  the authoritative ``participating_repos`` instead of an unchecked caller list.

The model is self-validating (a Weaviate outage cannot coexist with search
counters; a resolved conflict cannot be claimed without a stage-2 ``FAIL``), so
an inconsistent attestation is rejected fail-closed at construction time.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agentkit.story_creation.vectordb_reconciliation import (
    RECONCILIATION_SEARCH_MODE,
    resolve_vectordb_conflict_flag,
)
from agentkit.verify_system.llm_evaluator.roles import LlmVerdict


class ReconciliationEvidence(BaseModel):
    """Typed, self-validating proof that the VectorDB reconciliation ran.

    Produced by the deterministic reconciliation runtime and required by the
    agent-facing create boundary (``POST /v1/stories``). Construction fails
    fail-closed when the attested fields are internally inconsistent.

    Attributes:
        weaviate_ready: Whether the Weaviate readiness + ``story_search`` step
            succeeded. Must be ``True`` for the create boundary to proceed
            (FK-21 §21.4.3): a Weaviate outage blocks creation.
        total_hits: Raw ``story_search`` hit count (telemetry contract).
        hits_above_threshold: Hits at/above ``similarity_threshold``.
        candidates_evaluated: Candidates handed to the LLM, capped at
            ``max_llm_candidates`` (FK-21 §21.4.2 ``sent_to_llm`` counter).
        hits_classified_conflict: ``1`` when stage 2 returned ``FAIL``, else 0.
        threshold_value: The applied similarity threshold (audit).
        search_mode: The stage-1 ``story_search`` mode (FK-21 §21.4.2
            ``search_mode`` counter; always ``"hybrid"``).
        verdict: The stage-2 verdict (``PASS`` when stage 1 cleared all hits).
        story_was_adapted: Whether a detected stage-2 conflict was resolved by
            ADAPTING (not discarding) the story (FK-21 §21.4.1).
        participating_repos: The repo-affinity result (FK-21 §21.9) feeding the
            authoritative ``participating_repos``.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    weaviate_ready: bool
    total_hits: int = Field(ge=0)
    hits_above_threshold: int = Field(ge=0)
    candidates_evaluated: int = Field(default=0, ge=0)
    hits_classified_conflict: int = Field(ge=0)
    threshold_value: float = Field(ge=0.0, le=1.0)
    search_mode: str = RECONCILIATION_SEARCH_MODE
    verdict: LlmVerdict
    story_was_adapted: bool = False
    participating_repos: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _validate_consistency(self) -> ReconciliationEvidence:
        """Reject internally inconsistent attestations fail-closed.

        Raises:
            ValueError: When the counters/verdict combination cannot describe a
                real reconciliation outcome.
        """
        if not self.weaviate_ready:
            raise ValueError(
                "reconciliation evidence is invalid: weaviate_ready must be True "
                "(a Weaviate outage blocks story creation fail-closed, FK-21 §21.4.3)"
            )
        if self.hits_above_threshold > self.total_hits:
            raise ValueError(
                "reconciliation evidence is invalid: hits_above_threshold "
                f"({self.hits_above_threshold}) exceeds total_hits ({self.total_hits})"
            )
        if self.candidates_evaluated > self.hits_above_threshold:
            raise ValueError(
                "reconciliation evidence is invalid: candidates_evaluated "
                f"({self.candidates_evaluated}) exceeds hits_above_threshold "
                f"({self.hits_above_threshold}): the LLM cannot evaluate more "
                "candidates than survived the threshold filter (FK-21 §21.4.2)"
            )
        if self.search_mode != RECONCILIATION_SEARCH_MODE:
            raise ValueError(
                "reconciliation evidence is invalid: search_mode "
                f"({self.search_mode!r}) must be the fixed stage-1 search mode "
                f"{RECONCILIATION_SEARCH_MODE!r} (FK-21 §21.4.2)"
            )
        conflict_expected = 1 if self.verdict is LlmVerdict.FAIL else 0
        if self.hits_classified_conflict != conflict_expected:
            raise ValueError(
                "reconciliation evidence is invalid: hits_classified_conflict "
                f"({self.hits_classified_conflict}) does not match verdict "
                f"{self.verdict.value!r} (expected {conflict_expected})"
            )
        return self

    @property
    def vectordb_conflict_resolved(self) -> bool:
        """Derive the grounded ``vectordb_conflict_resolved`` flag (FK-21 §21.12).

        The flag is ``True`` ONLY when stage 2 reported a ``FAIL`` conflict that
        was resolved by adapting the story — it cannot be asserted without this
        evidence behind it.
        """
        return resolve_vectordb_conflict_flag(
            verdict=self.verdict,
            story_was_adapted=self.story_was_adapted,
        )


__all__ = ["ReconciliationEvidence"]
