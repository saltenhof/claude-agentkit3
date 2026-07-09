"""Unit tests for the AG3-137 session-ownership records, enums and ports.

Pure, DB-free tests of the blood-type-A domain surface: record ``__post_init__``
validation (AK8 negative paths), the closed enum vocabularies (FK-17 §17.2c) and
the repository ports (injection seams, not god-objects). The Postgres-backed
constraint mechanics (partial-unique, schema field-exactness, backfill) are
proven in ``tests/integration/state_backend/test_run_ownership_schema_postgres.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from agentkit.backend.control_plane.ownership import (
    OWNERSHIP_TRANSFERRED_REVOCATION_REASON,
    BindingRevocationReason,
    BindingStatus,
    OwnershipAcquisition,
    OwnershipStatus,
    SessionId,
)
from agentkit.backend.control_plane.records import (
    BackendInstanceIdentityRecord,
    ObjectMutationClaimRecord,
    RunOwnershipRecord,
    SessionRunBindingRecord,
    TakeoverTransferRecord,
)
from agentkit.backend.control_plane.repository import (
    BackendInstanceIdentityRepository,
    ObjectMutationClaimRepository,
    RunOwnershipRepository,
    TakeoverTransferRepository,
)

_NOW = datetime(2026, 7, 2, 12, 0, 0, tzinfo=UTC)


def _ownership(**overrides: object) -> RunOwnershipRecord:
    base: dict[str, object] = {
        "project_key": "tenant-a",
        "story_id": "AG3-100",
        "run_id": "run-1",
        "owner_session_id": "sess-1",
        "ownership_epoch": 1,
        "status": OwnershipStatus.ACTIVE,
        "acquired_via": OwnershipAcquisition.SETUP,
        "acquired_at": _NOW,
        "audit_ref": "audit:setup-1",
    }
    base.update(overrides)
    return RunOwnershipRecord(**base)  # type: ignore[arg-type]


def _claim(**overrides: object) -> ObjectMutationClaimRecord:
    base: dict[str, object] = {
        "project_key": "tenant-a",
        "serialization_scope": "story",
        "scope_key": "AG3-100",
        "op_id": "op-1",
        "backend_instance_id": "inst-1",
        "instance_incarnation": 1,
        "acquired_at": _NOW,
        "queue_position": 0,
    }
    base.update(overrides)
    return ObjectMutationClaimRecord(**base)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Enum vocabularies (FK-17 §17.2c)
# ---------------------------------------------------------------------------


def test_ownership_status_vocabulary_matches_fk17() -> None:
    assert [s.value for s in OwnershipStatus] == [
        "active",
        "transferred",
        "ended",
        "reset",
        "split",
        "closed",
    ]


def test_ownership_acquisition_vocabulary_matches_fk17() -> None:
    assert [a.value for a in OwnershipAcquisition] == ["setup", "takeover", "recovery"]


def test_binding_status_and_revocation_reason_vocabulary() -> None:
    assert [s.value for s in BindingStatus] == ["active", "revoked"]
    assert OWNERSHIP_TRANSFERRED_REVOCATION_REASON == "ownership_transferred"
    assert (
        BindingRevocationReason.OWNERSHIP_TRANSFERRED.value == "ownership_transferred"
    )


def test_session_id_is_a_str_newtype() -> None:
    sid = SessionId("sess-42")
    assert sid == "sess-42"
    assert isinstance(sid, str)


# ---------------------------------------------------------------------------
# RunOwnershipRecord validation (AK8)
# ---------------------------------------------------------------------------


def test_run_ownership_record_valid_construction() -> None:
    record = _ownership()
    assert record.status is OwnershipStatus.ACTIVE
    assert record.ownership_epoch == 1


def test_run_ownership_epoch_below_one_is_rejected() -> None:
    with pytest.raises(ValueError, match="ownership_epoch must be >= 1"):
        _ownership(ownership_epoch=0)


def test_run_ownership_empty_audit_ref_is_rejected() -> None:
    with pytest.raises(ValueError, match="audit_ref is mandatory"):
        _ownership(audit_ref="   ")


def test_run_ownership_empty_owner_session_is_rejected() -> None:
    with pytest.raises(ValueError, match="owner_session_id must be a non-empty"):
        _ownership(owner_session_id="")


# ---------------------------------------------------------------------------
# ObjectMutationClaimRecord validation (AK8)
# ---------------------------------------------------------------------------


def test_claim_without_instance_identity_is_rejected() -> None:
    with pytest.raises(ValueError, match="requires an instance identity"):
        _claim(backend_instance_id="")


def test_claim_incarnation_below_one_is_rejected() -> None:
    with pytest.raises(ValueError, match="instance_incarnation must be >= 1"):
        _claim(instance_incarnation=0)


def test_claim_queue_position_below_zero_is_rejected() -> None:
    with pytest.raises(ValueError, match="queue_position must be >= 0"):
        _claim(queue_position=-1)


def test_claim_empty_op_id_is_rejected() -> None:
    with pytest.raises(ValueError, match="op_id must not be empty"):
        _claim(op_id="")


def test_claim_empty_scope_is_rejected() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        _claim(scope_key="")


def test_claim_has_no_ttl_or_expiry_field() -> None:
    """SOLL-051: a claim never expires by wall clock -> no ttl/expiry attribute."""
    fields = set(_claim().__dataclass_fields__)
    assert not (fields & {"ttl", "expiry", "expires_at", "lease_ttl", "lease_expiry"})


# ---------------------------------------------------------------------------
# TakeoverTransferRecord / BackendInstanceIdentityRecord validation
# ---------------------------------------------------------------------------


def test_takeover_transfer_optional_attributes_default_none() -> None:
    record = TakeoverTransferRecord(
        project_key="tenant-a",
        story_id="AG3-100",
        run_id="run-1",
        ownership_epoch=1,
        repo_id="repo-a",
    )
    assert record.takeover_base_sha is None
    assert record.confirm_ref is None


def test_takeover_transfer_epoch_below_one_is_rejected() -> None:
    with pytest.raises(ValueError, match="ownership_epoch must be >= 1"):
        TakeoverTransferRecord(
            project_key="tenant-a",
            story_id="AG3-100",
            run_id="run-1",
            ownership_epoch=0,
            repo_id="repo-a",
        )


def test_takeover_transfer_empty_repo_id_is_rejected() -> None:
    with pytest.raises(ValueError, match="repo_id is part of the identity"):
        TakeoverTransferRecord(
            project_key="tenant-a",
            story_id="AG3-100",
            run_id="run-1",
            ownership_epoch=1,
            repo_id="",
        )


def test_takeover_transfer_has_no_snapshot_fields() -> None:
    """SOLL-147: the transfer record REPLACES the worktree snapshot -> no snapshot."""
    fields = set(
        TakeoverTransferRecord(
            project_key="p",
            story_id="s",
            run_id="r",
            ownership_epoch=1,
            repo_id="repo",
        ).__dataclass_fields__
    )
    assert not (
        fields
        & {"snapshot", "binary_diff", "index_status", "untracked_manifest", "worktree"}
    )


def test_backend_instance_identity_validation() -> None:
    record = BackendInstanceIdentityRecord("inst-1", 1, _NOW)
    assert record.instance_incarnation == 1
    with pytest.raises(ValueError, match="backend_instance_id must not be empty"):
        BackendInstanceIdentityRecord("", 1, _NOW)
    with pytest.raises(ValueError, match="instance_incarnation must be >= 1"):
        BackendInstanceIdentityRecord("inst-1", 0, _NOW)


# ---------------------------------------------------------------------------
# SessionRunBindingRecord additive fields (rein additiv)
# ---------------------------------------------------------------------------


def _binding(**overrides: object) -> SessionRunBindingRecord:
    base: dict[str, object] = {
        "session_id": "sess-1",
        "project_key": "tenant-a",
        "story_id": "AG3-100",
        "run_id": "run-1",
        "principal_type": "orchestrator",
        "worktree_roots": ("wt",),
        "binding_version": "1",
        "updated_at": _NOW,
    }
    base.update(overrides)
    return SessionRunBindingRecord(**base)  # type: ignore[arg-type]


def test_session_binding_additive_fields_default_active() -> None:
    """Additive status/revocation_reason default so pre-AG3-137 constructors work."""
    binding = _binding()
    assert binding.status == "active"
    assert binding.revocation_reason is None


def test_session_binding_accepts_canonical_integer_versions() -> None:
    """Valid boundary values are ACCEPTED (no over-reject): 1, 2, large integers."""
    for value in ("1", "2", "999", "1000000"):
        assert _binding(binding_version=value).binding_version == value


@pytest.mark.parametrize(
    "bad_version",
    [
        "bind-not-int",  # Codex ERROR §4: the exact reproduced bypass
        "bind-001",
        "exit-abc",
        "",
        " ",
        "0",  # not >= 1
        "01",  # leading-zero ambiguity
        "007",
        "-1",
        "+1",
        "1.0",
        "1 ",
        "1\n",  # fullmatch anchors: no trailing-newline tolerance
        "١",  # non-ASCII digit (leading): rejected by the ASCII [1-9] class
        "١٢٣",  # S6353 guard: full Arabic-Indic "123" stays rejected
        "1٢",  # S6353 guard: ASCII head + Unicode tail — the case a naive
        # bare ``\d`` (without re.ASCII) would WRONGLY accept; re.ASCII keeps it out
    ],
)
def test_session_binding_rejects_non_canonical_version(bad_version: str) -> None:
    """AK8 / Codex ERROR §4: a non-integer binding_version fails closed at the record.

    Reproduces the exact bypass Codex demonstrated
    (``SessionRunBindingRecord(..., binding_version='bind-not-int')`` used to
    construct successfully). The value domain is now enforced at the record
    boundary, so NO path (direct constructor, mapper, store) can carry a
    ``bind-*``/``exit-*`` correlation token, empty/whitespace, sign, decimal,
    ``0`` or leading-zero form as a binding version.
    """
    with pytest.raises(ValueError, match="binding_version"):
        _binding(binding_version=bad_version)


def test_session_binding_rejects_unknown_status() -> None:
    """AK8 / Codex ERROR §9: an out-of-vocabulary status fails closed at the record."""
    with pytest.raises(ValueError, match="status"):
        _binding(status="bogus")


def test_session_binding_rejects_reason_on_active() -> None:
    """AK8: a revocation_reason on an ACTIVE binding is inconsistent (fail-closed)."""
    with pytest.raises(ValueError, match="active binding"):
        _binding(
            status=BindingStatus.ACTIVE.value,
            revocation_reason=OWNERSHIP_TRANSFERRED_REVOCATION_REASON,
        )


def test_session_binding_rejects_revoked_without_reason() -> None:
    """AK8: a REVOKED binding requires a machine-readable reason (FK-56 §56.7a)."""
    with pytest.raises(ValueError, match="revoked binding"):
        _binding(status=BindingStatus.REVOKED.value, revocation_reason=None)
    with pytest.raises(ValueError, match="revoked binding"):
        _binding(status=BindingStatus.REVOKED.value, revocation_reason="  ")


def test_session_binding_accepts_revoked_with_reason() -> None:
    """A REVOKED binding with a valid reason is accepted (no over-reject)."""
    binding = _binding(
        status=BindingStatus.REVOKED.value,
        revocation_reason=BindingRevocationReason.OWNERSHIP_TRANSFERRED.value,
    )
    assert binding.status == "revoked"
    assert binding.revocation_reason == "ownership_transferred"


# ---------------------------------------------------------------------------
# Repository ports (injection seams, single-writer surface)
# ---------------------------------------------------------------------------


def test_repository_ports_default_to_owner_globals() -> None:
    from agentkit.backend.state_backend.operation_ledger import insert_object_mutation_claim_global
    from agentkit.backend.state_backend.state_backend_connection_manager import (
        load_backend_instance_identity_global,
    )
    from agentkit.backend.state_backend.story_lifecycle_store import (
        insert_run_ownership_record_global,
        save_takeover_transfer_record_global,
    )

    assert RunOwnershipRepository().insert_ownership is (
        insert_run_ownership_record_global
    )
    assert ObjectMutationClaimRepository().insert_claim is (
        insert_object_mutation_claim_global
    )
    assert TakeoverTransferRepository().save_transfer is (
        save_takeover_transfer_record_global
    )
    assert BackendInstanceIdentityRepository().load_identity is (
        load_backend_instance_identity_global
    )


def test_repository_ports_accept_injected_fakes() -> None:
    """The ports are dependency seams: a fake writer routes without the real store."""
    calls: list[RunOwnershipRecord] = []
    port = RunOwnershipRepository(insert_ownership=calls.append)
    record = _ownership()
    port.insert_ownership(record)
    assert calls == [record]
