"""Unit tests for formal spec compilation."""

from __future__ import annotations

from pathlib import Path

import pytest

from agentkit.concept_compiler.compiler import FormalCompilationError, compile_formal_specs

FIXTURES = Path("tests/fixtures/concept_compiler")

def test_compile_formal_specs_collects_ids_and_resolves_refs() -> None:
    result = compile_formal_specs(FIXTURES / "compile_ok")

    assert len(result.documents) == 2
    assert "example.state.initial" in result.declared_ids
    assert "example.invariant.can_finish" in result.declared_ids
    assert any(reference.target_id == "example.invariant.can_finish" for reference in result.references)


def test_compile_formal_specs_rejects_unresolved_refs() -> None:
    with pytest.raises(FormalCompilationError, match="Unresolved formal references"):
        compile_formal_specs(FIXTURES / "compile_unresolved")


def test_compile_repo_story_workflow_specs() -> None:
    root = Path("concept/formal-spec/story-workflow")

    result = compile_formal_specs(root)

    assert len(result.documents) == 5
    assert "story-workflow.phase.setup" in result.declared_ids
    assert "story-workflow.command.run-phase" in result.declared_ids
    assert "story-workflow.event.phase.started" in result.declared_ids
