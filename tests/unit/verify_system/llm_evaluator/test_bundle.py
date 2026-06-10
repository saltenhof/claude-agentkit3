"""Unit tests for build_review_bundle + ReviewBundle (AG3-043 / FK-27 §27.5.2)."""

from __future__ import annotations

import json

import pytest

from agentkit.verify_system.llm_evaluator.bundle import (
    BUNDLE_TOKEN_LIMIT,
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


def test_diff_content_is_section_packed_with_protocol() -> None:
    big = "\n".join(f"diff --git a/f{i}.py b/f{i}.py\n+{'x' * 200}" for i in range(300))
    bundle = build_review_bundle(
        _ri(handover=big), story_id="AG3-043", qa_cycle_round=1, bundle_token_limit=2_000
    )
    assert len(bundle.diff_summary) <= BUNDLE_TOKEN_LIMIT
    assert len(bundle.diff_content) <= 2_000
    assert bundle.packing_protocol["handover"]


def test_markdown_fields_are_packed_by_section() -> None:
    spec = "\n\n".join(f"## Section {i}\n{'z' * 500}" for i in range(100))
    bundle = build_review_bundle(
        _ri(story_spec=spec), story_id="AG3-043", qa_cycle_round=1, bundle_token_limit=2_500
    )
    assert len(bundle.story_brief_excerpt) <= 2_500
    assert "omitted" in bundle.story_brief_excerpt
    assert bundle.packing_protocol["story_spec"]


def test_six_semantic_context_fields_are_serialized() -> None:
    bundle = build_review_bundle(
        _ri(story_spec="story", diff_summary="diff", concept_excerpt="concept", handover="handover"),
        story_id="AG3-067",
        qa_cycle_round=1,
        arch_references="arch",
        evidence_manifest={"manifest_hash": "abc"},
    )
    parsed = json.loads(bundle.to_prompt_json())
    assert parsed["story_brief_excerpt"] == "story"
    assert parsed["diff_summary"] == "diff"
    assert parsed["concept_excerpt"] == "concept"
    assert parsed["diff_content"] == "handover"
    assert parsed["arch_references"] == "arch"
    assert parsed["evidence_manifest"] == {"manifest_hash": "abc"}


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
        concept_excerpt="",
        concept_refs=[],
        arch_references="",
        evidence_manifest=None,
        packing_protocol={},
        previous_findings=None,
        qa_cycle_round=1,
    )
    with pytest.raises(Exception, match="frozen|immutable"):
        bundle.story_id = "X"  # type: ignore[misc]
