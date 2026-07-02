"""Contract pins for the AG3-137 session-ownership record row formats.

Pins the mapper row shapes field-by-field against the formal entity attribute
sets (``formal.state-storage.entities`` v5, ``formal.operating-modes.entities``,
FK-17 §17.3a.15) — the concept is the single source of truth, so the expected
key sets below mirror the formal attribute lists, NOT a duplicate literal from
the mapper. Also pins the Postgres-only fail-closed gate (AK7) and the
``transferred``-has-no-writer rejection (AG3-137 scope §1). Pure and DB-free.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.control_plane.ownership import (
    OwnershipAcquisition,
    OwnershipStatus,
)
from agentkit.backend.control_plane.records import (
    BackendInstanceIdentityRecord,
    ObjectMutationClaimRecord,
    RunOwnershipRecord,
    TakeoverTransferRecord,
)
from agentkit.backend.exceptions import ConfigError
from agentkit.backend.state_backend.config import ALLOW_SQLITE_ENV, STATE_BACKEND_ENV
from agentkit.backend.state_backend.store import (
    insert_object_mutation_claim_global,
    insert_run_ownership_record_global,
    load_active_run_ownership_record_global,
    load_backend_instance_identity_global,
    load_object_mutation_claim_global,
    load_run_ownership_record_global,
    load_takeover_transfer_record_global,
    mappers,
    reset_backend_cache_for_tests,
    save_backend_instance_identity_global,
    save_takeover_transfer_record_global,
)

if TYPE_CHECKING:
    from collections.abc import Generator

_NOW = datetime(2026, 7, 2, 12, 0, 0, tzinfo=UTC)

# Expected row-dict key sets == the formal entity attribute sets (SSOT).
_RUN_OWNERSHIP_KEYS = {
    "project_key",
    "story_id",
    "run_id",
    "owner_session_id",
    "ownership_epoch",
    "status",
    "acquired_via",
    "acquired_at",
    "audit_ref",
}
_CLAIM_KEYS = {
    "project_key",
    "serialization_scope",
    "scope_key",
    "op_id",
    "backend_instance_id",
    "instance_incarnation",
    "acquired_at",
    "queue_position",
}
_TAKEOVER_KEYS = {
    "project_key",
    "story_id",
    "run_id",
    "ownership_epoch",
    "repo_id",
    "takeover_base_sha",
    "last_push_at",
    "push_lag_hint",
    "base_quality",
    "challenge_ref",
    "confirm_ref",
}
_INSTANCE_KEYS = {"backend_instance_id", "instance_incarnation", "updated_at"}


@pytest.mark.contract
def test_run_ownership_row_is_field_exact_and_roundtrips() -> None:
    record = RunOwnershipRecord(
        project_key="tenant-a",
        story_id="AG3-100",
        run_id="run-1",
        owner_session_id="sess-1",
        ownership_epoch=3,
        status=OwnershipStatus.ACTIVE,
        acquired_via=OwnershipAcquisition.TAKEOVER,
        acquired_at=_NOW,
        audit_ref="audit:x",
    )
    row = mappers.run_ownership_to_row(record)
    assert set(row) == _RUN_OWNERSHIP_KEYS
    assert row["status"] == "active"
    assert row["acquired_via"] == "takeover"
    assert mappers.run_ownership_row_to_record(row) == record


@pytest.mark.contract
def test_object_mutation_claim_row_is_field_exact_and_has_no_ttl() -> None:
    record = ObjectMutationClaimRecord(
        project_key="tenant-a",
        serialization_scope="story",
        scope_key="AG3-100",
        op_id="op-1",
        backend_instance_id="inst-1",
        instance_incarnation=2,
        acquired_at=_NOW,
        queue_position=5,
    )
    row = mappers.object_mutation_claim_to_row(record)
    assert set(row) == _CLAIM_KEYS
    assert not (set(row) & {"ttl", "expiry", "expires_at", "lease_ttl"})
    assert mappers.object_mutation_claim_row_to_record(row) == record


@pytest.mark.contract
def test_takeover_transfer_row_is_field_exact_and_has_no_snapshot() -> None:
    record = TakeoverTransferRecord(
        project_key="tenant-a",
        story_id="AG3-100",
        run_id="run-1",
        ownership_epoch=2,
        repo_id="repo-a",
        takeover_base_sha="abc123",
        last_push_at=_NOW,
        push_lag_hint="fresh",
        base_quality="clean",
        challenge_ref="challenge:1",
        confirm_ref="confirm:1",
    )
    row = mappers.takeover_transfer_to_row(record)
    assert set(row) == _TAKEOVER_KEYS
    assert not (set(row) & {"snapshot", "binary_diff", "index_status"})
    assert row["last_push_at"] == _NOW.isoformat()
    assert mappers.takeover_transfer_row_to_record(row) == record


@pytest.mark.contract
def test_backend_instance_identity_row_is_field_exact_and_roundtrips() -> None:
    record = BackendInstanceIdentityRecord("inst-1", 4, _NOW)
    row = mappers.backend_instance_identity_to_row(record)
    assert set(row) == _INSTANCE_KEYS
    assert mappers.backend_instance_identity_row_to_record(row) == record


@pytest.mark.contract
def test_transferred_status_has_no_writer_and_is_rejected() -> None:
    """AG3-137 §1: setting status='transferred' is fail-closed rejected (no writer)."""
    record = RunOwnershipRecord(
        project_key="tenant-a",
        story_id="AG3-100",
        run_id="run-1",
        owner_session_id="sess-1",
        ownership_epoch=1,
        status=OwnershipStatus.TRANSFERRED,
        acquired_via=OwnershipAcquisition.TAKEOVER,
        acquired_at=_NOW,
        audit_ref="audit:x",
    )
    with pytest.raises(ValueError, match="'transferred' has no writer"):
        insert_run_ownership_record_global(record)


# ---------------------------------------------------------------------------
# Postgres-only fail-closed gate (AK7, K5)
# ---------------------------------------------------------------------------


@pytest.fixture
def sqlite_backend_env(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[None, None, None]:
    monkeypatch.setenv(STATE_BACKEND_ENV, "sqlite")
    monkeypatch.setenv(ALLOW_SQLITE_ENV, "1")
    reset_backend_cache_for_tests()
    yield
    reset_backend_cache_for_tests()


@pytest.mark.contract
def test_every_new_repository_entrypoint_fails_closed_on_sqlite(
    sqlite_backend_env: None,
) -> None:
    """AK7/K5: the session-ownership store is Postgres-only.

    Every new repository entrypoint fails closed with an explicit ``ConfigError``
    on a non-Postgres backend — there is no SQLite implementation and no silent
    fallback.
    """
    del sqlite_backend_env
    record = RunOwnershipRecord(
        project_key="tenant-a",
        story_id="AG3-100",
        run_id="run-1",
        owner_session_id="sess-1",
        ownership_epoch=1,
        status=OwnershipStatus.ACTIVE,
        acquired_via=OwnershipAcquisition.SETUP,
        acquired_at=_NOW,
        audit_ref="audit:x",
    )
    claim = ObjectMutationClaimRecord(
        project_key="tenant-a",
        serialization_scope="story",
        scope_key="AG3-100",
        op_id="op-1",
        backend_instance_id="inst-1",
        instance_incarnation=1,
        acquired_at=_NOW,
        queue_position=0,
    )
    transfer = TakeoverTransferRecord(
        project_key="tenant-a",
        story_id="AG3-100",
        run_id="run-1",
        ownership_epoch=1,
        repo_id="repo-a",
    )
    identity = BackendInstanceIdentityRecord("inst-1", 1, _NOW)

    with pytest.raises(ConfigError, match="Postgres"):
        insert_run_ownership_record_global(record)
    with pytest.raises(ConfigError):
        load_run_ownership_record_global("tenant-a", "AG3-100", "run-1")
    with pytest.raises(ConfigError):
        load_active_run_ownership_record_global("tenant-a", "AG3-100")
    with pytest.raises(ConfigError):
        insert_object_mutation_claim_global(claim)
    with pytest.raises(ConfigError):
        load_object_mutation_claim_global("tenant-a", "story", "AG3-100")
    with pytest.raises(ConfigError):
        save_takeover_transfer_record_global(transfer)
    with pytest.raises(ConfigError):
        load_takeover_transfer_record_global("tenant-a", "AG3-100", "run-1", 1, "repo-a")
    with pytest.raises(ConfigError):
        save_backend_instance_identity_global(identity)
    with pytest.raises(ConfigError):
        load_backend_instance_identity_global("inst-1")
