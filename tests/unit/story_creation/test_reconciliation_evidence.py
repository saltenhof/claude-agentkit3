"""Unit tests for the ReconciliationEvidence precondition model (AG3-068).

The model is the fail-closed precondition consumed by the agent-facing create
boundary (FK-21 §21.4/§21.12). These tests pin its self-validation (a Weaviate
outage / inconsistent counters cannot be attested) and the grounded
``vectordb_conflict_resolved`` derivation.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agentkit.story_creation.reconciliation_evidence import ReconciliationEvidence
from agentkit.verify_system.llm_evaluator.roles import LlmVerdict


def _evidence(**overrides: object) -> ReconciliationEvidence:
    base: dict[str, object] = {
        "weaviate_ready": True,
        "total_hits": 5,
        "hits_above_threshold": 2,
        "hits_classified_conflict": 0,
        "threshold_value": 0.7,
        "verdict": LlmVerdict.PASS,
    }
    base.update(overrides)
    return ReconciliationEvidence.model_validate(base)


def test_pass_evidence_is_valid_and_flag_false() -> None:
    evidence = _evidence()
    assert evidence.weaviate_ready is True
    assert evidence.vectordb_conflict_resolved is False


def test_fail_with_adaptation_grounds_flag_true() -> None:
    evidence = _evidence(
        verdict=LlmVerdict.FAIL,
        hits_classified_conflict=1,
        story_was_adapted=True,
    )
    assert evidence.vectordb_conflict_resolved is True


def test_fail_without_adaptation_leaves_flag_false() -> None:
    evidence = _evidence(
        verdict=LlmVerdict.FAIL,
        hits_classified_conflict=1,
        story_was_adapted=False,
    )
    assert evidence.vectordb_conflict_resolved is False


def test_weaviate_not_ready_is_rejected_fail_closed() -> None:
    with pytest.raises(ValidationError, match="weaviate_ready must be True"):
        _evidence(weaviate_ready=False)


def test_above_threshold_exceeding_total_is_rejected() -> None:
    with pytest.raises(ValidationError, match="exceeds total_hits"):
        _evidence(total_hits=1, hits_above_threshold=3)


def test_fail_verdict_without_classified_conflict_is_rejected() -> None:
    with pytest.raises(ValidationError, match="does not match verdict"):
        _evidence(verdict=LlmVerdict.FAIL, hits_classified_conflict=0)


def test_pass_verdict_with_classified_conflict_is_rejected() -> None:
    with pytest.raises(ValidationError, match="does not match verdict"):
        _evidence(verdict=LlmVerdict.PASS, hits_classified_conflict=1)


def test_negative_counter_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _evidence(total_hits=-1)


def test_threshold_out_of_range_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _evidence(threshold_value=1.5)


def test_extra_fields_are_forbidden() -> None:
    with pytest.raises(ValidationError):
        _evidence(unexpected_field="x")


def test_participating_repos_default_empty() -> None:
    assert _evidence().participating_repos == ()


def test_participating_repos_roundtrip() -> None:
    evidence = _evidence(participating_repos=["a", "b"])
    assert evidence.participating_repos == ("a", "b")
