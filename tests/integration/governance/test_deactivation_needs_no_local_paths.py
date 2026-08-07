"""Lock deactivation must not depend on a developer-machine directory (AG3-239).

The defect this pins: ``deactivate_locks`` used to write a tombstone into
``_temp/governance/locks/{story_id}/`` **relative to the process CWD** and derive
its "guards are off" flag from whether that write succeeded. ``_temp/governance``
is the EDGE's projection directory -- FK-30 section 30.6.1 reads
``_temp/governance/current.json`` inside the hook process on the developer
machine. On a core host the directory never exists, the flag was always False,
and ``story_exit`` rejected every exit with
"exit_finalized rejected: guards were not deactivated".

These tests run with the CWD pointed at an empty directory that has no
``_temp/`` at all, which is exactly the core-host situation.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.governance.administration import Governance
from agentkit.backend.governance.errors import LockRecordNotFoundError
from agentkit.backend.governance.locks import DeactivationResult, LockRecordId

if TYPE_CHECKING:
    from collections.abc import Iterator


class _RecordingLockRepo:
    """Lock repository double that reports what the canonical state says."""

    def __init__(self, *, known: bool = True, deactivated: list[str] | None = None):
        self._known = known
        self._deactivated = deactivated if deactivated is not None else ["lock-1"]
        self.calls: list[str] = []

    def deactivate_locks_for_story(self, story_id: str) -> list[LockRecordId]:
        """Return the deactivated lock ids, or fail closed for an unknown story."""
        self.calls.append(story_id)
        if not self._known:
            raise LockRecordNotFoundError(f"no lock records for story {story_id}")
        return [LockRecordId(identifier) for identifier in self._deactivated]


@pytest.fixture
def core_host_cwd(tmp_path: Path) -> Iterator[Path]:
    """Run inside an empty directory -- no ``_temp/``, like a real core host."""
    root = tmp_path / "core-host"
    root.mkdir()
    previous = Path.cwd()
    os.chdir(root)
    try:
        yield root
    finally:
        os.chdir(previous)


@pytest.mark.integration
def test_guards_deactivated_without_any_local_directory(core_host_cwd: Path) -> None:
    """The good path is green on a host that has no ``_temp/governance``."""
    repo = _RecordingLockRepo()
    result = Governance(lock_repo=repo).deactivate_locks("AG3-239")  # type: ignore[arg-type]

    assert isinstance(result, DeactivationResult)
    assert result.guards_deactivated is True
    assert result.errors == []
    assert result.deactivated_locks == [LockRecordId("lock-1")]
    assert repo.calls == ["AG3-239"]
    # The operation created nothing on disk -- that is the point.
    assert list(core_host_cwd.iterdir()) == []


@pytest.mark.integration
def test_already_deactivated_story_still_reports_guards_off(
    core_host_cwd: Path,
) -> None:
    """Idempotent re-entry: no locks left to deactivate, guards still off."""
    result = Governance(lock_repo=_RecordingLockRepo(deactivated=[])).deactivate_locks(  # type: ignore[arg-type]
        "AG3-239"
    )

    assert result.deactivated_locks == []
    assert result.guards_deactivated is True
    assert result.errors == []
    assert list(core_host_cwd.iterdir()) == []


@pytest.mark.integration
def test_unknown_story_fails_closed(core_host_cwd: Path) -> None:
    """An unknown story proves nothing about its guards -- flag stays False."""
    result = Governance(lock_repo=_RecordingLockRepo(known=False)).deactivate_locks(  # type: ignore[arg-type]
        "AG3-239"
    )

    assert result.guards_deactivated is False
    assert result.deactivated_locks == []
    assert len(result.errors) == 1
    assert "AG3-239" in result.errors[0]


@pytest.mark.integration
def test_result_carries_no_developer_machine_paths() -> None:
    """The three filesystem-reporting fields are gone, not merely unused.

    Keeping them would invite the next caller to gate on a path the core host
    does not have -- which is the defect this story removed.
    """
    fields = set(DeactivationResult.model_fields)
    assert fields == {"deactivated_locks", "guards_deactivated", "errors"}
