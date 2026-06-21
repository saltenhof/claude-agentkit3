"""Integrity-gate conflict-freeze proof dimension tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.backend.governance.integrity_gate import IntegrityGateContext
from agentkit.backend.governance.integrity_gate._dimension_specs import IntegrityDimension
from agentkit.backend.governance.integrity_gate.dimensions import evaluate_dimension
from agentkit.backend.story_context_manager.types import StoryType

if TYPE_CHECKING:
    from pathlib import Path


class _StatePort:
    def __init__(self, *, frozen: bool, proof: bool) -> None:
        self._frozen = frozen
        self._proof = proof

    def has_active_conflict_freeze(self, story_dir: Path, scope: object) -> bool:
        del story_dir, scope
        return self._frozen

    def has_conflict_freeze_proof(self, story_dir: Path, scope: object) -> bool:
        del story_dir, scope
        return self._proof


def test_conflict_freeze_without_proof_blocks_closure(tmp_path: Path) -> None:
    result = evaluate_dimension(
        IntegrityDimension.CONFLICT_FREEZE_PROOF,
        IntegrityGateContext(tmp_path, StoryType.IMPLEMENTATION),
        state_port=_StatePort(frozen=True, proof=False),  # type: ignore[arg-type]
        runtime_scope=None,
    )
    assert result.passed is False
    assert result.failure_reason == "CONFLICT_FREEZE_PROOF"


def test_conflict_freeze_with_proof_passes(tmp_path: Path) -> None:
    result = evaluate_dimension(
        IntegrityDimension.CONFLICT_FREEZE_PROOF,
        IntegrityGateContext(tmp_path, StoryType.IMPLEMENTATION),
        state_port=_StatePort(frozen=True, proof=True),  # type: ignore[arg-type]
        runtime_scope=None,
    )
    assert result.passed is True
