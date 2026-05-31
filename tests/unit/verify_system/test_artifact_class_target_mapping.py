"""E3b (AG3-015 Review R1): pin the ArtifactClass -> VerifyTargetType mapping.

``ArtifactClass.PROMPT_AUDIT`` is deliberately NOT a verify target (FK-44
§44.6: a prompt-audit record is a reproducibility proof, not a QA-reviewable
deliverable). This test pins that decision fail-closed: every enum value is
either an explicit verify target or deliberately excluded, and resolving a
non-target raises ``VerifyTargetUnknownError`` rather than silently mapping.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentkit.artifacts import ArtifactReference
from agentkit.core_types import ArtifactClass, QaContext
from agentkit.verify_system._artifact_specs import ARTIFACT_CLASS_TO_TARGET_TYPE
from agentkit.verify_system.contract import VerifyContextBundle
from agentkit.verify_system.errors import VerifyTargetUnknownError
from agentkit.verify_system.system import VerifySystem

#: Classes that are deliberately not verify targets (structural, not QA-able).
_DELIBERATELY_EXCLUDED = frozenset(
    {
        ArtifactClass.PROMPT_AUDIT,
        ArtifactClass.PIPELINE,
        ArtifactClass.TELEMETRY,
        ArtifactClass.GOVERNANCE,
    },
)


def test_prompt_audit_is_not_a_verify_target() -> None:
    assert ArtifactClass.PROMPT_AUDIT not in ARTIFACT_CLASS_TO_TARGET_TYPE


def test_every_artifact_class_is_target_or_deliberately_excluded() -> None:
    """No enum value is silently un-handled: each is mapped or excluded."""
    for ac in ArtifactClass:
        mapped = ac in ARTIFACT_CLASS_TO_TARGET_TYPE
        excluded = ac in _DELIBERATELY_EXCLUDED
        assert mapped ^ excluded, (
            f"{ac!r} must be EITHER a verify target OR deliberately excluded, "
            f"not both/neither (fail-closed completeness pin)."
        )


class _RecordingManager:
    """ArtifactManager test-double: must never be written to (fail-closed first)."""

    def write(self, envelope: object) -> object:  # pragma: no cover - unused
        raise AssertionError("ArtifactManager.write must not be called")


def test_resolve_prompt_audit_target_is_fail_closed() -> None:
    """A prompt_audit target fails closed via VerifyTargetUnknownError."""
    vs = VerifySystem.create_default(artifact_manager=_RecordingManager())  # type: ignore[arg-type]
    ref = ArtifactReference(
        artifact_class=ArtifactClass.PROMPT_AUDIT,
        story_id="AG3-015",
        run_id="run-1",
        record_key="AG3-015|run-1|prompt-materialization|1|prompt_audit|p",
    )
    ctx = VerifyContextBundle(run_id="run-1", story_dir=Path("."), attempt=1)
    with pytest.raises(VerifyTargetUnknownError):
        vs.run_qa_subflow(
            ctx,
            story_id="AG3-015",
            qa_context=QaContext.IMPLEMENTATION_INITIAL,
            target=ref,
        )
