"""Tests for FK-37 ContextSufficiencyBuilder."""

from __future__ import annotations

import json

from agentkit.verify_system.llm_evaluator.context_sufficiency import (
    CONTEXT_SUFFICIENCY_STAGE,
    ContextSufficiencyBuilder,
    SufficiencyLevel,
)
from agentkit.verify_system.llm_evaluator.inputs import Layer2ReviewInput


def test_builder_loads_four_loader_fields_and_caller_fields(tmp_path) -> None:
    story_dir = tmp_path / "stories" / "AG3-067"
    concept_dir = tmp_path / "concept" / "technical-design"
    story_dir.mkdir(parents=True)
    concept_dir.mkdir(parents=True)
    (story_dir / "story.md").write_text("# Story\nbody", encoding="utf-8")
    (story_dir / "handover.json").write_text(
        json.dumps({"risks_for_qa": ["risk"]}),
        encoding="utf-8",
    )
    (concept_dir / "37_verify_context_und_qa_bundle.md").write_text(
        "# FK-37\nprimary concept",
        encoding="utf-8",
    )
    (story_dir / "context.json").write_text(
        json.dumps(
            {
                "diff_summary": "diff",
                "evidence_manifest": "manifest",
                "concept_paths": ["37_verify_context_und_qa_bundle.md"],
                "external_sources": [{"url": "https://example.invalid"}],
            }
        ),
        encoding="utf-8",
    )

    builder = ContextSufficiencyBuilder.from_story_dir(
        story_id="AG3-067",
        story_dir=story_dir,
    )
    result = builder.build(
        Layer2ReviewInput(),
        caller_diff_summary=builder.caller_diff_summary(),
        caller_evidence_manifest=builder.caller_evidence_manifest(),
    )

    assert result.sufficiency is SufficiencyLevel.SUFFICIENT
    assert result.artifact.stage == CONTEXT_SUFFICIENCY_STAGE
    assert result.artifact.bundles["story_spec"].status == "present"
    assert result.artifact.bundles["diff_summary"].status == "present"
    assert result.artifact.bundles["evidence_manifest"].status == "present"
    assert "External Sources" in result.arch_references


def test_caller_side_fields_missing_when_not_injected(tmp_path) -> None:
    story_dir = tmp_path / "stories" / "AG3-067"
    story_dir.mkdir(parents=True)
    (story_dir / "story.md").write_text("# Story\nbody", encoding="utf-8")
    (story_dir / "handover.json").write_text("{}", encoding="utf-8")
    (story_dir / "context.json").write_text(
        json.dumps({"diff_summary": "exists on disk", "evidence_manifest": "exists"}),
        encoding="utf-8",
    )

    result = ContextSufficiencyBuilder.from_story_dir(
        story_id="AG3-067",
        story_dir=story_dir,
    ).build(Layer2ReviewInput(concept_excerpt="# Concept\nbody"))

    assert result.sufficiency is SufficiencyLevel.PARTIALLY_REVIEWABLE
    assert result.artifact.bundles["diff_summary"].status == "missing"
    assert result.artifact.bundles["evidence_manifest"].status == "missing"


def test_truncated_diff_is_reviewable_with_gaps(tmp_path) -> None:
    story_dir = tmp_path / "stories" / "AG3-067"
    concept_dir = tmp_path / "concept" / "technical-design"
    story_dir.mkdir(parents=True)
    concept_dir.mkdir(parents=True)
    (story_dir / "story.md").write_text("# Story\nbody", encoding="utf-8")
    (story_dir / "handover.json").write_text("{}", encoding="utf-8")
    (concept_dir / "37.md").write_text("# Concept\nbody", encoding="utf-8")
    builder = ContextSufficiencyBuilder(
        story_id="AG3-067",
        story_dir=story_dir,
        context_json={"concept_paths": ["37.md"]},
        worktree_root=tmp_path,
    )

    result = builder.build(
        Layer2ReviewInput(),
        caller_diff_summary="x" * 40_000,
        caller_evidence_manifest="manifest",
    )

    assert result.sufficiency is SufficiencyLevel.REVIEWABLE_WITH_GAPS
    assert result.artifact.bundles["diff_summary"].status == "truncated"
