"""Concept/Research drift-fix routing tests (AG3-034 §2.1.4, governance-and-guards.C4).

Verifies the single-source ``required_phases_for`` / ``dimensions_for`` and that
Dim 5 (NO_LLM_REVIEW) and Dim 6 (NO_ADVERSARIAL) are evaluated
ONLY for implementation/bugfix; for concept/research they are absent from the
dimension results (AK8).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from agentkit.governance.integrity_gate import (
    IntegrityDimension,
    IntegrityGate,
    IntegrityGateStatus,
    required_phases_for,
)
from agentkit.governance.integrity_gate.dimensions import dimensions_for
from agentkit.story_context_manager.types import StoryType

if TYPE_CHECKING:
    from pathlib import Path


class _NonCodePort:
    """State-port stub for concept/research (no QA artifacts, only context)."""

    def resolve_runtime_scope(self, story_dir: object) -> object:
        from agentkit.exceptions import CorruptStateError

        raise CorruptStateError("no scope")

    def has_completed_snapshot(self, story_dir: object, phase: str) -> bool:
        _ = story_dir, phase
        return True

    def has_structural_artifact(self, story_dir: object) -> bool:
        _ = story_dir
        return False

    def has_structural_artifact_for_scope(self, scope: object) -> bool:
        _ = scope
        return False

    def has_valid_context(self, story_dir: object) -> bool:
        _ = story_dir
        return True

    def has_valid_phase_state(self, story_dir: object) -> bool:
        _ = story_dir
        return True

    def load_context_finished_at(self, story_dir: object, scope: object) -> None:
        # Concept/research carry a context but no decision -> Dim 8 is vacuously
        # satisfied (no inversion possible); a timestamp is irrelevant here.
        _ = story_dir, scope
        return None

    def validate_context_record(self, story_dir: object, scope: object) -> None:
        # Concept/research context records are valid (present + ids); the field
        # validation passes (None == no violation).
        _ = story_dir, scope
        return None

    def load_latest_verify_decision(self, story_dir: object) -> None:
        _ = story_dir
        return None

    def load_latest_verify_decision_for_scope(self, scope: object) -> None:
        _ = scope
        return None

    def read_phase_state_record(self, story_dir: object) -> None:
        _ = story_dir
        return None

    def find_latest_qa_envelope(
        self, story_dir: object, scope: object, stage: str
    ) -> None:
        _ = story_dir, scope, stage
        return None


def test_required_phases_for_is_type_dependent() -> None:
    assert required_phases_for(StoryType.IMPLEMENTATION) == (
        "setup",
        "implementation",
        "closure",
    )
    assert required_phases_for(StoryType.BUGFIX) == (
        "setup",
        "implementation",
        "closure",
    )
    assert required_phases_for(StoryType.CONCEPT) == ("setup", "closure")
    assert required_phases_for(StoryType.RESEARCH) == ("setup", "closure")


def test_required_phases_for_unknown_type_raises() -> None:
    with pytest.raises(ValueError, match="Unknown story_type"):
        required_phases_for("not-a-type")  # type: ignore[arg-type]


@pytest.mark.parametrize("story_type", [StoryType.CONCEPT, StoryType.RESEARCH])
def test_dim5_dim6_not_evaluated_for_noncode(story_type: StoryType) -> None:
    evaluated = dimensions_for(story_type)
    assert IntegrityDimension.NO_LLM_REVIEW not in evaluated
    assert IntegrityDimension.NO_ADVERSARIAL not in evaluated


@pytest.mark.parametrize(
    "story_type", [StoryType.IMPLEMENTATION, StoryType.BUGFIX]
)
def test_dim5_dim6_evaluated_for_code(story_type: StoryType) -> None:
    evaluated = dimensions_for(story_type)
    assert IntegrityDimension.NO_LLM_REVIEW in evaluated
    assert IntegrityDimension.NO_ADVERSARIAL in evaluated


@pytest.mark.parametrize("story_type", [StoryType.CONCEPT, StoryType.RESEARCH])
def test_noncode_gate_passes_without_qa_artifacts(
    tmp_path: Path, story_type: StoryType
) -> None:
    result = IntegrityGate(_NonCodePort()).evaluate(tmp_path, story_type)  # type: ignore[arg-type]
    assert result.overall is IntegrityGateStatus.PASS
    # Dim 5/6/7 are absent (drift fix); only context + snapshots + timestamp.
    assert IntegrityDimension.NO_LLM_REVIEW not in result.dimension_results
    assert IntegrityDimension.NO_ADVERSARIAL not in result.dimension_results
    assert IntegrityDimension.NO_VERIFY not in result.dimension_results
    assert IntegrityDimension.NO_QA_ARTIFACTS not in result.dimension_results
