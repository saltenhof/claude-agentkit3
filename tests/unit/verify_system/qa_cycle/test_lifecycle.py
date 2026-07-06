"""Unit tests for QaCycleLifecycle (FK-27 §27.2.1-§27.2.3, AG3-041 AC1/AC2)."""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.verify_system.contract import PhaseEnvelopeView
from agentkit.backend.verify_system.errors import VerifySystemError
from agentkit.backend.verify_system.qa_cycle.invalidation import (
    CYCLE_BOUND_QA_ARTIFACTS,
    RecordingArtifactInvalidationSink,
    qa_artifact_dir,
)
from agentkit.backend.verify_system.qa_cycle.lifecycle import QaCycleLifecycle, QaCycleState

if TYPE_CHECKING:
    from pathlib import Path

_QA_CYCLE_ID_LEN = 12
_SHA256_HEX_LEN = 64
_STORY_ID = "AG3-041"


def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _init_repo(root: Path) -> None:
    _git(["init", "-b", "main"], root)
    _git(["config", "user.email", "t@example.com"], root)
    _git(["config", "user.name", "Test"], root)
    (root / "base.py").write_text("x = 1\n", encoding="utf-8")
    _git(["add", "."], root)
    _git(["commit", "-m", "base"], root)
    _git(["update-ref", "refs/remotes/origin/main", "HEAD"], root)
    _git(["checkout", "-b", "story-branch"], root)
    (root / "feature.py").write_text("y = 2\n", encoding="utf-8")
    _git(["add", "."], root)
    _git(["commit", "-m", "feature"], root)


class TestStartCycle:
    def test_start_cycle_sets_round1_epoch1(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        lifecycle = QaCycleLifecycle()

        state = lifecycle.start_cycle(tmp_path)

        assert state.round == 1
        assert state.epoch == 1
        assert len(state.qa_cycle_id) == _QA_CYCLE_ID_LEN
        assert all(c in "0123456789abcdef" for c in state.qa_cycle_id)
        assert len(state.evidence_fingerprint) == _SHA256_HEX_LEN
        assert state.evidence_epoch.tzinfo is not None

    def test_start_cycle_to_view_roundtrips(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        state = QaCycleLifecycle().start_cycle(tmp_path)
        view = state.to_view()
        assert view.qa_cycle_id == state.qa_cycle_id
        assert view.qa_cycle_round == 1


class TestAdvanceCycle:
    def test_advance_increments_round_and_epoch(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        lifecycle = QaCycleLifecycle()
        first = lifecycle.start_cycle(tmp_path)

        next_state, _events = lifecycle.advance_qa_cycle(
            first.to_view(), tmp_path, _STORY_ID
        )

        assert next_state.round == 2  # noqa: PLR2004
        assert next_state.epoch == 2  # noqa: PLR2004
        assert next_state.qa_cycle_id != first.qa_cycle_id

    def test_advance_blocks_fail_closed_on_qa_cycle_push_barrier(
        self, tmp_path: Path
    ) -> None:
        """AG3-147 AC2 (QA-cycle boundary): advancing to a new cycle round is
        fail-closed BLOCKED when the push-barrier gate refuses -- BEFORE any
        artefact invalidation or fingerprint recompute (no state change)."""
        from agentkit.backend.verify_system.qa_cycle.lifecycle import (
            QaCycleBarrierBlockedError,
        )

        class _BlockingGate:
            def __init__(self) -> None:
                self.seen: Path | None = None

            def enforce(self, story_dir: Path) -> None:
                self.seen = story_dir
                msg = "story branch not server-verified-pushed"
                raise QaCycleBarrierBlockedError(msg)

        gate = _BlockingGate()
        lifecycle = QaCycleLifecycle(push_barrier_gate=gate)  # type: ignore[arg-type]
        current = PhaseEnvelopeView(
            qa_cycle_id="abc123def456",
            qa_cycle_round=1,
            evidence_epoch=datetime(2026, 7, 6, tzinfo=UTC),
            evidence_fingerprint="a" * 64,
        )

        with pytest.raises(QaCycleBarrierBlockedError):
            lifecycle.advance_qa_cycle(current, tmp_path, _STORY_ID)
        assert gate.seen == tmp_path

    def test_advance_invalidates_cycle_artifacts(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        base = qa_artifact_dir(tmp_path, _STORY_ID, project_root=tmp_path)
        base.mkdir(parents=True, exist_ok=True)
        for name in CYCLE_BOUND_QA_ARTIFACTS:
            (base / name).write_text("{}", encoding="utf-8")

        sink = RecordingArtifactInvalidationSink.empty()
        lifecycle = QaCycleLifecycle(invalidation_sink=sink)
        first = lifecycle.start_cycle(tmp_path)

        _next_state, events = lifecycle.advance_qa_cycle(
            first.to_view(), tmp_path, _STORY_ID, project_root=tmp_path
        )

        assert len(events) == len(CYCLE_BOUND_QA_ARTIFACTS)
        assert len(sink.events) == len(CYCLE_BOUND_QA_ARTIFACTS)
        stale = base / "stale" / "1"
        for name in CYCLE_BOUND_QA_ARTIFACTS:
            assert (stale / name).is_file()

    def test_advance_without_active_cycle_fails_closed(self, tmp_path: Path) -> None:
        view = PhaseEnvelopeView()  # no qa_cycle_id
        with pytest.raises(VerifySystemError, match="active cycle"):
            QaCycleLifecycle().advance_qa_cycle(view, tmp_path, _STORY_ID)


class TestGetCurrentState:
    def test_returns_none_when_idle(self) -> None:
        assert QaCycleLifecycle.get_current_state(PhaseEnvelopeView()) is None

    def test_returns_state_when_active(self) -> None:
        view = PhaseEnvelopeView(
            qa_cycle_id="a1b2c3d4e5f6",
            qa_cycle_round=2,
            evidence_epoch=datetime(2026, 5, 19, tzinfo=UTC),
            evidence_fingerprint="f" * 64,
        )
        state = QaCycleLifecycle.get_current_state(view)
        assert isinstance(state, QaCycleState)
        assert state.round == 2  # noqa: PLR2004
        assert state.qa_cycle_id == "a1b2c3d4e5f6"
