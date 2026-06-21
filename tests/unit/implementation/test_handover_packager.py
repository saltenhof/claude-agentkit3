"""Unit tests for HandoverPackager (FK-26 §26.7) producing handover.json."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.bootstrap.composition_root import build_artifact_manager
from agentkit.backend.core_types import SpawnReason
from agentkit.backend.implementation.handover import (
    HANDOVER_FILENAME,
    ACStatus,
    HandoverPackager,
)
from agentkit.backend.implementation.worker_loop import (
    DriftEvent,
    IncrementResult,
    IncrementStep,
    IncrementSummary,
)
from agentkit.backend.implementation.worker_session import WorkerSession
from agentkit.backend.state_backend.config import ALLOW_SQLITE_ENV, STATE_BACKEND_ENV
from agentkit.backend.state_backend.store import reset_backend_cache_for_tests
from agentkit.backend.story_context_manager.models import StoryContext
from agentkit.backend.story_context_manager.types import StoryMode, StoryType

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path


@pytest.fixture(autouse=True)
def _sqlite_backend(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    monkeypatch.setenv(STATE_BACKEND_ENV, "sqlite")
    monkeypatch.setenv(ALLOW_SQLITE_ENV, "1")
    reset_backend_cache_for_tests()
    yield
    reset_backend_cache_for_tests()


class _FakeLoader:
    def load(self, story_id: str, run_id: str) -> StoryContext | None:
        del run_id
        return StoryContext(
            project_key="test-project",
            story_id=story_id,
            story_type=StoryType.IMPLEMENTATION,
            execution_route=StoryMode.EXECUTION,
        )


def _session() -> WorkerSession:
    return WorkerSession(
        SpawnReason.INITIAL, "AG3-044", "run-1", context_loader=_FakeLoader()
    )


def _increment(index: int, *, drift: bool = False) -> IncrementResult:
    return IncrementResult(
        index=index,
        steps_completed=(IncrementStep.IMPLEMENT, IncrementStep.COMMIT),
        verify_passed=True,
        drift=DriftEvent(
            increment=index,
            drift_detected=drift,
            skipped=False,
            reason="circuit breaker" if drift else None,
        ),
        summary=IncrementSummary(
            description=f"increment {index}",
            commit_sha=f"sha{index}",
            tests_added=(f"tests/test_{index}.py",),
        ),
    )


def test_package_writes_handover_json_with_seven_fields(tmp_path: Path) -> None:
    """package writes story_dir/handover.json with all seven mandatory fields."""
    manager = build_artifact_manager(tmp_path)
    packager = HandoverPackager(manager)
    story_dir = tmp_path / "stories" / "AG3-044"
    story_dir.mkdir(parents=True)

    packager.package(
        _session(),
        [_increment(1), _increment(2, drift=True)],
        story_dir=story_dir,
        changes_summary="implemented worker loop",
        risks_for_qa=["race condition not tested"],
        acceptance_criteria_status={"AC-1": ACStatus.ADDRESSED},
        commit_sha="sha2",
        branch_ref="story/AG3-044",
    )

    handover_path = story_dir / HANDOVER_FILENAME
    assert handover_path.is_file()
    data = json.loads(handover_path.read_text(encoding="utf-8"))
    assert set(data) == {
        "changes_summary",
        "increments",
        "assumptions",
        "existing_tests",
        "risks_for_qa",
        "drift_log",
        "acceptance_criteria_status",
    }
    # Increments + drift_log derived from the recorded increments.
    assert len(data["increments"]) == 2
    assert len(data["drift_log"]) == 1
    assert data["existing_tests"] == ["tests/test_1.py", "tests/test_2.py"]
    assert data["acceptance_criteria_status"] == {"AC-1": "ADDRESSED"}


def test_package_persists_handover_envelope(tmp_path: Path) -> None:
    """package writes a HANDOVER envelope via the ArtifactManager."""
    manager = build_artifact_manager(tmp_path)
    packager = HandoverPackager(manager)
    story_dir = tmp_path / "stories" / "AG3-044"
    story_dir.mkdir(parents=True)

    ref = packager.package(
        _session(),
        [_increment(1)],
        story_dir=story_dir,
        changes_summary="x",
        risks_for_qa=[],
        acceptance_criteria_status={},
    )
    # The reference resolves to a readable HANDOVER envelope.
    envelope = manager.read(ref)
    assert envelope.artifact_class.value == "handover"
    assert envelope.story_id == "AG3-044"


def test_ac_status_values() -> None:
    """ACStatus follows FK-26 §26.7.3 (ADDRESSED/NOT_APPLICABLE/BLOCKED)."""
    assert {s.value for s in ACStatus} == {
        "ADDRESSED",
        "NOT_APPLICABLE",
        "BLOCKED",
    }
