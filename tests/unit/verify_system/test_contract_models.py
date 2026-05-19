"""Unit tests for verify_system contract models.

Tests VerifyContextBundle (public) and VerifyTarget (internal).

AG3-026 §2.1.1, §4 AK3.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from agentkit.verify_system.contract import (
    VerifyContextBundle,
    VerifyTarget,
    VerifyTargetType,
)


class TestVerifyContextBundle:
    """VerifyContextBundle: Pydantic v2, frozen, extra=forbid."""

    def test_valid_construction(self, tmp_path: Path) -> None:
        bundle = VerifyContextBundle(
            run_id="run-001",
            story_dir=tmp_path,
            phase_envelope=None,
            attempt=1,
        )
        assert bundle.run_id == "run-001"
        assert bundle.story_dir == tmp_path
        assert bundle.attempt == 1
        assert bundle.phase_envelope is None

    def test_is_frozen(self, tmp_path: Path) -> None:
        """VerifyContextBundle must be immutable (frozen=True)."""
        bundle = VerifyContextBundle(
            run_id="run-001",
            story_dir=tmp_path,
            phase_envelope=None,
            attempt=1,
        )
        with pytest.raises(ValidationError):
            bundle.run_id = "mutated"  # type: ignore[misc]

    def test_extra_fields_forbidden(self, tmp_path: Path) -> None:
        """extra=forbid: unknown fields are rejected at construction."""
        with pytest.raises(ValidationError):
            VerifyContextBundle(  # type: ignore[call-arg]
                run_id="run-001",
                story_dir=tmp_path,
                phase_envelope=None,
                attempt=1,
                unknown_field="bad",
            )

    def test_required_fields_enforced(self) -> None:
        """All four fields are required; missing fields raise ValidationError."""
        with pytest.raises(ValidationError):
            VerifyContextBundle()  # type: ignore[call-arg]

    def test_run_id_is_string(self, tmp_path: Path) -> None:
        bundle = VerifyContextBundle(
            run_id="abc-123",
            story_dir=tmp_path,
            phase_envelope=None,
            attempt=1,
        )
        assert isinstance(bundle.run_id, str)

    def test_story_dir_accepts_path(self, tmp_path: Path) -> None:
        bundle = VerifyContextBundle(
            run_id="run-x",
            story_dir=tmp_path,
            phase_envelope=None,
            attempt=2,
        )
        assert isinstance(bundle.story_dir, Path)

    def test_phase_envelope_accepts_phase_envelope_instance(
        self, tmp_path: Path
    ) -> None:
        """AG3-026 Re-Review: ``phase_envelope`` ist typisiert
        ``PhaseEnvelope | None``, kein freier dict mehr."""
        from agentkit.pipeline_engine.phase_envelope.envelope import PhaseEnvelope
        from agentkit.pipeline_engine.phase_envelope.runtime import (
            PhaseOrigin,
            RuntimeMetadata,
        )
        from agentkit.story_context_manager.models import (
            ImplementationPayload,
            PhaseName,
            PhaseState,
            PhaseStatus,
        )

        state = PhaseState(
            story_id="TEST-001",
            phase=PhaseName.IMPLEMENTATION,
            status=PhaseStatus.IN_PROGRESS,
            payload=ImplementationPayload(),
        )
        runtime = RuntimeMetadata(
            origin=PhaseOrigin.NEW,
            loaded_at=None,
            process_id=1,
            worker_id=None,
        )
        envelope = PhaseEnvelope(state=state, runtime=runtime)
        bundle = VerifyContextBundle(
            run_id="run-x",
            story_dir=tmp_path,
            phase_envelope=envelope,
            attempt=1,
        )
        assert bundle.phase_envelope is envelope

    def test_attempt_is_integer(self, tmp_path: Path) -> None:
        bundle = VerifyContextBundle(
            run_id="run-y",
            story_dir=tmp_path,
            phase_envelope=None,
            attempt=3,
        )
        assert bundle.attempt == 3


class TestVerifyTargetInternal:
    """VerifyTarget: internal model (frozen, extra=forbid)."""

    def test_minimal_construction(self) -> None:
        vt = VerifyTarget(
            artifact_ref_record_key="envelopes/qa/TEST-001/1",
            target_type=VerifyTargetType.IMPLEMENTATION,
        )
        assert vt.artifact_ref_record_key == "envelopes/qa/TEST-001/1"
        assert vt.target_type is VerifyTargetType.IMPLEMENTATION

    def test_optional_fields_default_to_none_or_empty(self) -> None:
        vt = VerifyTarget(
            artifact_ref_record_key="key-1",
            target_type=VerifyTargetType.EXPLORATION,
        )
        assert vt.branch_ref is None
        assert vt.commit_sha is None
        assert vt.paths_in_scope == ()

    def test_full_construction(self) -> None:
        vt = VerifyTarget(
            artifact_ref_record_key="key-2",
            target_type=VerifyTargetType.BUGFIX,
            branch_ref="feature/ag3-026",
            commit_sha="abc123",
            paths_in_scope=("src/foo.py", "tests/test_foo.py"),
        )
        assert vt.branch_ref == "feature/ag3-026"
        assert vt.commit_sha == "abc123"
        assert vt.paths_in_scope == ("src/foo.py", "tests/test_foo.py")

    def test_is_frozen(self) -> None:
        vt = VerifyTarget(
            artifact_ref_record_key="key-3",
            target_type=VerifyTargetType.IMPLEMENTATION,
        )
        with pytest.raises(ValidationError):
            vt.target_type = VerifyTargetType.BUGFIX  # type: ignore[misc]

    def test_extra_fields_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            VerifyTarget(  # type: ignore[call-arg]
                artifact_ref_record_key="key-4",
                target_type=VerifyTargetType.IMPLEMENTATION,
                rogue_field="evil",
            )


class TestVerifyTargetType:
    """VerifyTargetType StrEnum values."""

    def test_all_three_values_present(self) -> None:
        assert VerifyTargetType.IMPLEMENTATION == "IMPLEMENTATION"
        assert VerifyTargetType.EXPLORATION == "EXPLORATION"
        assert VerifyTargetType.BUGFIX == "BUGFIX"

    def test_is_str_enum(self) -> None:
        assert isinstance(VerifyTargetType.IMPLEMENTATION, str)
