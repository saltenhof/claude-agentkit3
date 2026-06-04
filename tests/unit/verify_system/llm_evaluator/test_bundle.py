"""Unit tests for build_review_bundle + ReviewBundle (AG3-043 / FK-27 §27.5.2)."""

from __future__ import annotations

import json

import pytest

from agentkit.verify_system.llm_evaluator.bundle import (
    MAX_BUNDLE_TOTAL_BYTES,
    MAX_DIFF_CONTENT_BYTES,
    ReviewBundle,
    build_review_bundle,
)
from agentkit.verify_system.llm_evaluator.inputs import Layer2ReviewInput
from agentkit.verify_system.protocols import Finding, Severity, TrustClass


def _ri(**kw: str) -> Layer2ReviewInput:
    return Layer2ReviewInput(**kw)


def test_build_maps_fields_from_review_input() -> None:
    ri = _ri(
        story_spec="the brief",
        diff_summary="2 files changed",
        concept_excerpt="FK-27 §27.5",
        handover="the diff body",
    )
    bundle = build_review_bundle(ri, story_id="AG3-043", qa_cycle_round=1)
    assert bundle.story_id == "AG3-043"
    assert bundle.story_brief_excerpt == "the brief"
    assert bundle.diff_summary == "2 files changed"
    assert bundle.diff_content == "the diff body"
    assert bundle.concept_refs == ["FK-27 §27.5"]
    assert bundle.qa_cycle_round == 1


def test_empty_concept_excerpt_yields_empty_concept_refs() -> None:
    bundle = build_review_bundle(_ri(), story_id="AG3-043", qa_cycle_round=1)
    assert bundle.concept_refs == []


def test_round_below_one_is_rejected() -> None:
    with pytest.raises(ValueError, match="qa_cycle_round"):
        build_review_bundle(_ri(), story_id="AG3-043", qa_cycle_round=0)


def test_diff_content_is_capped_at_100kb() -> None:
    big = "x" * (MAX_DIFF_CONTENT_BYTES + 5000)
    bundle = build_review_bundle(
        _ri(handover=big), story_id="AG3-043", qa_cycle_round=1
    )
    assert len(bundle.diff_content.encode("utf-8")) <= MAX_DIFF_CONTENT_BYTES
    assert "TRUNCATED" in bundle.diff_content


def test_total_bundle_capped_at_200kb() -> None:
    big = "y" * (MAX_DIFF_CONTENT_BYTES)
    spec = "z" * (150 * 1024)
    bundle = build_review_bundle(
        _ri(story_spec=spec, handover=big), story_id="AG3-043", qa_cycle_round=1
    )
    assert len(bundle.to_prompt_json().encode("utf-8")) <= MAX_BUNDLE_TOTAL_BYTES


def test_to_prompt_json_is_deterministic_sorted() -> None:
    bundle = build_review_bundle(
        _ri(story_spec="b"), story_id="AG3-043", qa_cycle_round=1
    )
    first = bundle.to_prompt_json()
    second = bundle.to_prompt_json()
    assert first == second
    parsed = json.loads(first)
    assert parsed["story_id"] == "AG3-043"
    assert parsed["previous_findings"] is None


def test_previous_findings_are_projected_to_json() -> None:
    finding = Finding(
        layer="qa_review",
        check="ac_fulfilled",
        severity=Severity.BLOCKING,
        message="not met",
        trust_class=TrustClass.VERIFIED_LLM,
    )
    bundle = build_review_bundle(
        _ri(), story_id="AG3-043", qa_cycle_round=2, previous_findings=[finding]
    )
    parsed = json.loads(bundle.to_prompt_json())
    assert parsed["previous_findings"] == [
        {
            "layer": "qa_review",
            "check": "ac_fulfilled",
            "severity": "BLOCKING",
            "message": "not met",
        }
    ]


def test_review_bundle_is_frozen_and_forbids_extra() -> None:
    bundle = ReviewBundle(
        story_id="AG3-043",
        story_brief_excerpt="b",
        acceptance_criteria=[],
        diff_summary="",
        diff_content="",
        concept_refs=[],
        previous_findings=None,
        qa_cycle_round=1,
    )
    with pytest.raises(Exception, match="frozen|immutable"):
        bundle.story_id = "X"  # type: ignore[misc]
