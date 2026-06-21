"""Unit tests for the two-stage VectorDB reconciliation (AG3-068 / FK-21 §21.4).

Mocks live ONLY at the adapter (Weaviate) and evaluator (LLM) boundaries. The
threshold filter, top-N selection, verdict mapping, flag rule and telemetry
emission run for real.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from agentkit.backend.config.models import VectorDbConfig
from agentkit.backend.story_creation.vectordb_reconciliation import (
    VectorDbReconciliation,
    resolve_vectordb_conflict_flag,
)
from agentkit.backend.telemetry.emitters import MemoryEmitter
from agentkit.backend.telemetry.events import EventType
from agentkit.backend.verify_system.llm_evaluator.roles import LlmVerdict, ReviewerRole
from agentkit.integration_clients.vectordb import StorySearchHit, VectorDbUnavailableError


@dataclass
class _FakeResult:
    verdict: LlmVerdict


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
    def __init__(self, verdict: LlmVerdict) -> None:
        self._verdict = verdict
        self.calls: list[ReviewerRole] = []
        self.last_candidate_count = 0

    def evaluate(
        self,
        role: ReviewerRole,
        bundle: object,
        previous_findings: object,
        qa_cycle_round: int,
    ) -> _FakeResult:
        del previous_findings, qa_cycle_round
        self.calls.append(role)
        self.last_candidate_count = len(getattr(bundle, "concept_refs", []))
        return _FakeResult(verdict=self._verdict)


def _hit(story_id: str, score: float) -> StorySearchHit:
    return StorySearchHit(story_id=story_id, title=f"T-{story_id}", score=score, snippet="s")


def _config() -> VectorDbConfig:
    return VectorDbConfig(similarity_threshold=0.7, max_llm_candidates=5)


def test_stage1_filters_below_threshold_no_llm_call() -> None:
    """All hits below threshold => no stage 2, PASS verdict."""
    adapter = _FakeAdapter([_hit("AG3-1", 0.5), _hit("AG3-2", 0.69)])
    evaluator = _FakeEvaluator(LlmVerdict.FAIL)
    recon = VectorDbReconciliation(adapter, evaluator, _config())  # type: ignore[arg-type]
    result = recon.reconcile(
        story_id="AG3-100", story_description="new story", project_id="AG3"
    )
    assert result.verdict is LlmVerdict.PASS
    assert evaluator.calls == []
    assert result.hits_above_threshold == 0


def test_stage1_search_passes_hybrid_project_limit() -> None:
    adapter = _FakeAdapter([])
    recon = VectorDbReconciliation(adapter, _FakeEvaluator(LlmVerdict.PASS), _config())  # type: ignore[arg-type]
    recon.reconcile(story_id="AG3-100", story_description="q", project_id="AG3")
    call = adapter.search_calls[0]
    assert call["search_mode"] == "hybrid"
    assert call["project_id"] == "AG3"
    assert call["limit"] == 20


def test_stage2_caps_at_max_llm_candidates() -> None:
    """AC3: >5 candidates above threshold => exactly 5 evaluated."""
    hits = [_hit(f"AG3-{i}", 0.9) for i in range(8)]
    adapter = _FakeAdapter(hits)
    evaluator = _FakeEvaluator(LlmVerdict.PASS)
    recon = VectorDbReconciliation(adapter, evaluator, _config())  # type: ignore[arg-type]
    result = recon.reconcile(story_id="AG3-100", story_description="q", project_id="AG3")
    assert result.hits_above_threshold == 8
    assert result.candidates_evaluated == 5
    assert evaluator.last_candidate_count == 5
    assert evaluator.calls == [ReviewerRole.STORY_CREATION_REVIEW]


def test_stage2_fail_sets_conflict_classification() -> None:
    adapter = _FakeAdapter([_hit("AG3-1", 0.95)])
    recon = VectorDbReconciliation(adapter, _FakeEvaluator(LlmVerdict.FAIL), _config())  # type: ignore[arg-type]
    result = recon.reconcile(story_id="AG3-100", story_description="q", project_id="AG3")
    assert result.verdict is LlmVerdict.FAIL
    assert result.hits_classified_conflict == 1


def test_unavailable_blocks_fail_closed() -> None:
    """NEGATIVE: Weaviate outage propagates, never an empty silent result."""
    adapter = _FakeAdapter([], raise_search=True)
    recon = VectorDbReconciliation(adapter, _FakeEvaluator(LlmVerdict.PASS), _config())  # type: ignore[arg-type]
    with pytest.raises(VectorDbUnavailableError):
        recon.reconcile(story_id="AG3-100", story_description="q", project_id="AG3")


def test_emits_single_vectordb_search_event_with_mandatory_payload() -> None:
    """AC9: exactly the existing VECTORDB_SEARCH mandatory payload, one event."""
    emitter = MemoryEmitter()
    adapter = _FakeAdapter([_hit("AG3-1", 0.95), _hit("AG3-2", 0.4)])
    recon = VectorDbReconciliation(
        adapter, _FakeEvaluator(LlmVerdict.FAIL), _config(), event_emitter=emitter  # type: ignore[arg-type]
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
    assert resolve_vectordb_conflict_flag(verdict=LlmVerdict.FAIL, story_was_adapted=True) is True


def test_flag_false_on_fail_without_adaptation() -> None:
    """NEGATIVE: a FAIL conflict NOT resolved by adapting the story => False."""
    assert (
        resolve_vectordb_conflict_flag(verdict=LlmVerdict.FAIL, story_was_adapted=False)
        is False
    )


def test_flag_false_on_pass() -> None:
    assert (
        resolve_vectordb_conflict_flag(verdict=LlmVerdict.PASS, story_was_adapted=True)
        is False
    )
