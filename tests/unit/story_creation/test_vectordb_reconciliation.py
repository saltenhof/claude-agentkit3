"""Unit tests for the two-stage VectorDB reconciliation (AG3-068 / FK-21 §21.4).

Mocks live ONLY at the adapter (Weaviate) and evaluator (LLM) boundaries. The
threshold filter, top-N selection, verdict mapping, flag rule and telemetry
emission run for real.
"""

from __future__ import annotations

import pytest

from agentkit.backend.config.models import VectorDbConfig
from agentkit.backend.story_creation.vectordb_reconciliation import (
    VectorDbReconciliation,
    resolve_vectordb_conflict_flag,
)
from agentkit.backend.telemetry.emitters import MemoryEmitter
from agentkit.backend.telemetry.events import EventType
from agentkit.integration_clients.vectordb import StorySearchHit, VectorDbUnavailableError
from agentkit_wire.verify_system import (
    ConflictVerdict,
    StoryConflictAssessmentRequest,
    StoryConflictAssessmentResponse,
)


class _FakeAdapter:
    def __init__(self, hits: list[StorySearchHit], *, raise_search: bool = False) -> None:
        self._hits = hits
        self._raise = raise_search
        self.search_calls: list[dict[str, object]] = []

    def story_search(
        self,
        query: str,
        *,
        search_mode: str = "hybrid",
        project_id: str,
        limit: int = 20,
    ) -> list[StorySearchHit]:
        self.search_calls.append(
            {"query": query, "search_mode": search_mode, "project_id": project_id, "limit": limit}
        )
        if self._raise:
            raise VectorDbUnavailableError("down")
        return self._hits


class _FakeEvaluator:
    """Double at the ONE boundary this BC crosses: the core's assessment (AG3-241)."""

    def __init__(self, verdict: ConflictVerdict) -> None:
        self._verdict = verdict
        self.calls: list[StoryConflictAssessmentRequest] = []
        self.last_candidate_count = 0

    def assess(
        self, request: StoryConflictAssessmentRequest
    ) -> StoryConflictAssessmentResponse:
        self.calls.append(request)
        self.last_candidate_count = len(request.candidates)
        return StoryConflictAssessmentResponse(verdict=self._verdict)


def _hit(story_id: str, score: float) -> StorySearchHit:
    return StorySearchHit(story_id=story_id, title=f"T-{story_id}", score=score, snippet="s")


def _config() -> VectorDbConfig:
    return VectorDbConfig(similarity_threshold=0.7, max_llm_candidates=5)


def test_stage1_filters_below_threshold_no_llm_call() -> None:
    """All hits below threshold => no stage 2, PASS verdict."""
    adapter = _FakeAdapter([_hit("AG3-1", 0.5), _hit("AG3-2", 0.69)])
    evaluator = _FakeEvaluator(ConflictVerdict.FAIL)
    recon = VectorDbReconciliation(adapter, evaluator, _config())  # type: ignore[arg-type]
    result = recon.reconcile(
        story_id="AG3-100", story_description="new story", project_id="AG3"
    )
    assert result.verdict is ConflictVerdict.PASS
    assert evaluator.calls == []
    assert result.hits_above_threshold == 0


def test_stage1_search_passes_hybrid_project_limit() -> None:
    adapter = _FakeAdapter([])
    recon = VectorDbReconciliation(adapter, _FakeEvaluator(ConflictVerdict.PASS), _config())  # type: ignore[arg-type]
    recon.reconcile(story_id="AG3-100", story_description="q", project_id="AG3")
    call = adapter.search_calls[0]
    assert call["search_mode"] == "hybrid"
    assert call["project_id"] == "AG3"
    assert call["limit"] == 20


def test_stage2_caps_at_max_llm_candidates() -> None:
    """AC3: >5 candidates above threshold => exactly 5 evaluated."""
    hits = [_hit(f"AG3-{i}", 0.9) for i in range(8)]
    adapter = _FakeAdapter(hits)
    evaluator = _FakeEvaluator(ConflictVerdict.PASS)
    recon = VectorDbReconciliation(adapter, evaluator, _config())  # type: ignore[arg-type]
    result = recon.reconcile(story_id="AG3-100", story_description="q", project_id="AG3")
    assert result.hits_above_threshold == 8
    assert result.candidates_evaluated == 5
    assert evaluator.last_candidate_count == 5
    assert len(evaluator.calls) == 1


def test_stage2_request_carries_the_candidates_the_core_must_judge() -> None:
    """AG3-241: the edge ships the surviving candidates, not a rendered prompt.

    Stage 1 runs here because only this side reaches the index; the judgement is
    the core's. What crosses is therefore the observation -- the draft story plus
    each above-threshold hit with its score -- and nothing that pre-empts the
    verdict.
    """
    adapter = _FakeAdapter([_hit("AG3-1", 0.95), _hit("AG3-2", 0.4)])
    evaluator = _FakeEvaluator(ConflictVerdict.PASS)
    recon = VectorDbReconciliation(adapter, evaluator, _config())  # type: ignore[arg-type]

    recon.reconcile(
        story_id="AG3-100", story_description="new story", project_id="AG3"
    )

    request = evaluator.calls[0]
    assert request.story_id == "AG3-100"
    assert request.story_description == "new story"
    # Only the above-threshold hit crosses, with its score preserved.
    assert [c.story_id for c in request.candidates] == ["AG3-1"]
    assert request.candidates[0].score == pytest.approx(0.95)
    assert request.candidates[0].title == "T-AG3-1"


def test_stage2_fail_sets_conflict_classification() -> None:
    adapter = _FakeAdapter([_hit("AG3-1", 0.95)])
    recon = VectorDbReconciliation(adapter, _FakeEvaluator(ConflictVerdict.FAIL), _config())  # type: ignore[arg-type]
    result = recon.reconcile(story_id="AG3-100", story_description="q", project_id="AG3")
    assert result.verdict is ConflictVerdict.FAIL
    assert result.hits_classified_conflict == 1


def test_unavailable_blocks_fail_closed() -> None:
    """NEGATIVE: Weaviate outage propagates, never an empty silent result."""
    adapter = _FakeAdapter([], raise_search=True)
    recon = VectorDbReconciliation(adapter, _FakeEvaluator(ConflictVerdict.PASS), _config())  # type: ignore[arg-type]
    with pytest.raises(VectorDbUnavailableError):
        recon.reconcile(story_id="AG3-100", story_description="q", project_id="AG3")


def test_emits_single_vectordb_search_event_with_mandatory_payload() -> None:
    """AC9: exactly the existing VECTORDB_SEARCH mandatory payload, one event."""
    emitter = MemoryEmitter()
    adapter = _FakeAdapter([_hit("AG3-1", 0.95), _hit("AG3-2", 0.4)])
    recon = VectorDbReconciliation(
        adapter, _FakeEvaluator(ConflictVerdict.FAIL), _config(), event_emitter=emitter  # type: ignore[arg-type]
    )
    recon.reconcile(story_id="AG3-100", story_description="q", project_id="AG3")
    events = emitter.query("AG3-100", EventType.VECTORDB_SEARCH)
    assert len(events) == 1
    payload = events[0].payload
    assert set(payload) == {
        "total_hits",
        "hits_above_threshold",
        "hits_classified_conflict",
        "threshold_value",
    }
    assert payload["total_hits"] == 2
    assert payload["hits_above_threshold"] == 1
    assert payload["hits_classified_conflict"] == 1
    assert payload["threshold_value"] == pytest.approx(0.7)


# -- flag producer rule (FK-21 §21.12 / §21.4.1) ----------------------------


def test_flag_true_only_on_fail_and_adapted() -> None:
    assert resolve_vectordb_conflict_flag(verdict=ConflictVerdict.FAIL, story_was_adapted=True) is True


def test_flag_false_on_fail_without_adaptation() -> None:
    """NEGATIVE: a FAIL conflict NOT resolved by adapting the story => False."""
    assert (
        resolve_vectordb_conflict_flag(verdict=ConflictVerdict.FAIL, story_was_adapted=False)
        is False
    )


def test_flag_false_on_pass() -> None:
    assert (
        resolve_vectordb_conflict_flag(verdict=ConflictVerdict.PASS, story_was_adapted=True)
        is False
    )
