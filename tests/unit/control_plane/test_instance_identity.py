"""Unit tests for the AG3-138 backend instance-identity resolution.

Blood-type A logic over an injectable identity port (no I/O): the first boot
mints a fresh id at incarnation 1; every later boot keeps the stable id and
increments the incarnation by exactly 1 -- deterministic, no wall-clock input.
"""

from __future__ import annotations

from datetime import UTC, datetime

from agentkit.backend.control_plane.instance_identity import (
    resolve_backend_instance_identity,
)
from agentkit.backend.control_plane.records import BackendInstanceIdentityRecord

_NOW = datetime(2026, 7, 2, 12, 0, tzinfo=UTC)


class _FakeIdentityRepo:
    """In-memory create-or-increment mirror of the identity store port."""

    def __init__(self) -> None:
        self.row: BackendInstanceIdentityRecord | None = None
        self.boot_calls = 0

    def boot_identity(
        self, candidate_id: str, now: datetime
    ) -> BackendInstanceIdentityRecord:
        self.boot_calls += 1
        if self.row is None:
            self.row = BackendInstanceIdentityRecord(
                backend_instance_id=candidate_id,
                instance_incarnation=1,
                updated_at=now,
            )
        else:
            self.row = BackendInstanceIdentityRecord(
                backend_instance_id=self.row.backend_instance_id,
                instance_incarnation=self.row.instance_incarnation + 1,
                updated_at=now,
            )
        return self.row


def test_first_boot_mints_candidate_id_at_incarnation_one() -> None:
    repo = _FakeIdentityRepo()
    identity = resolve_backend_instance_identity(
        repo,  # type: ignore[arg-type]
        candidate_id_factory=lambda: "inst-fresh",
        now_fn=lambda: _NOW,
    )
    assert identity.backend_instance_id == "inst-fresh"
    assert identity.instance_incarnation == 1


def test_backend_instance_id_is_stable_across_boots_incarnation_monotone() -> None:
    """AC3: id stable across restarts; incarnation strictly monotone by +1."""
    repo = _FakeIdentityRepo()
    first = resolve_backend_instance_identity(
        repo,  # type: ignore[arg-type]
        candidate_id_factory=lambda: "inst-a",
        now_fn=lambda: _NOW,
    )
    # A DIFFERENT candidate on the second boot is IGNORED -- the stored id wins.
    second = resolve_backend_instance_identity(
        repo,  # type: ignore[arg-type]
        candidate_id_factory=lambda: "inst-b-should-be-ignored",
        now_fn=lambda: _NOW,
    )
    third = resolve_backend_instance_identity(
        repo,  # type: ignore[arg-type]
        candidate_id_factory=lambda: "inst-c-should-be-ignored",
        now_fn=lambda: _NOW,
    )
    assert first.backend_instance_id == "inst-a"
    assert second.backend_instance_id == "inst-a"
    assert third.backend_instance_id == "inst-a"
    assert (
        first.instance_incarnation,
        second.instance_incarnation,
        third.instance_incarnation,
    ) == (1, 2, 3)
