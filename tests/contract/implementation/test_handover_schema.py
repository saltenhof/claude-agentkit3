"""Contract test: handover.json schema (FK-26 §26.7.3 -- seven mandatory fields).

Pins the producer (HandoverPackager, AG3-044) against the validator
(``artifact.handover`` Layer-1 check, AG3-042) so the two never drift: a
packaged ``handover.json`` MUST pass ``check_artifact_handover`` with no finding
(one consistent schema, no producer/validator divergence).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from agentkit.backend.bootstrap.composition_root import build_artifact_manager
from agentkit.backend.core_types import Severity, SpawnReason
from agentkit.backend.implementation.handover import (
    ACStatus,
    HandoverData,
    HandoverPackager,
)
from agentkit.backend.implementation.handover.packager import (
    DriftLogEntry,
    HandoverIncrement,
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
from agentkit.backend.verify_system.structural.checks.artifact_checks import (
    check_artifact_handover,
)

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

#: FK-26 §26.7.3 mandatory handover field-set -- the SAME set the AG3-042
#: ``artifact.handover`` validator enforces (one consistent schema).
_MANDATORY_FIELDS = frozenset(
    {
        "changes_summary",
        "increments",
        "assumptions",
        "existing_tests",
        "risks_for_qa",
        "drift_log",
        "acceptance_criteria_status",
    }
)


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


def test_handover_data_pins_seven_mandatory_fields() -> None:
    """HandoverData exposes exactly the seven FK-26 §26.7.3 fields."""
    assert frozenset(HandoverData.model_fields) == _MANDATORY_FIELDS


def test_handover_data_serialises_all_seven_keys() -> None:
    """A serialised HandoverData carries all seven keys (assumptions/drift empty)."""
    data = HandoverData(
        changes_summary="x",
        increments=[HandoverIncrement(description="i", commit_sha="abc")],
        drift_log=[DriftLogEntry(increment=1, drift="d", justification="j")],
        acceptance_criteria_status={"AC-1": ACStatus.ADDRESSED},
    )
    payload = data.model_dump(mode="json")
    assert frozenset(payload) == _MANDATORY_FIELDS
    assert payload["assumptions"] == []
    assert payload["acceptance_criteria_status"]["AC-1"] == "ADDRESSED"


def test_packaged_handover_passes_ag3_042_validator(tmp_path: Path) -> None:
    """A packaged handover.json passes the AG3-042 artifact.handover check.

    This is the cross-story consistency pin: producer (044) -> validator (042),
    no drift. The validator returns ``None`` (PASS) on a well-formed handover.
    """
    manager = build_artifact_manager(tmp_path)
    packager = HandoverPackager(manager)
    story_dir = tmp_path / "stories" / "AG3-044"
    story_dir.mkdir(parents=True)
    session = WorkerSession(
        SpawnReason.INITIAL, "AG3-044", "run-1", context_loader=_FakeLoader()
    )
    increment = IncrementResult(
        index=1,
        steps_completed=(IncrementStep.IMPLEMENT, IncrementStep.COMMIT),
        verify_passed=True,
        drift=DriftEvent(increment=1, drift_detected=False, skipped=True),
        summary=IncrementSummary(
            description="i", commit_sha="abc", tests_added=("tests/t.py",)
        ),
    )
    packager.package(
        session,
        [increment],
        story_dir=story_dir,
        changes_summary="implemented",
        risks_for_qa=["edge case"],
        acceptance_criteria_status={"AC-1": ACStatus.ADDRESSED},
    )

    ctx = _FakeLoader().load("AG3-044", "run-1")
    assert ctx is not None
    finding = check_artifact_handover(ctx, story_dir, severity=Severity.BLOCKING)
    assert finding is None, (
        f"packaged handover.json must pass the AG3-042 validator; got {finding}"
    )
