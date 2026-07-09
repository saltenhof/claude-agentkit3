"""Contract pins for the AG3-137 session-ownership record row formats.

Pins the mapper row shapes field-by-field against the formal entity attribute
sets (``formal.state-storage.entities`` v6, ``formal.operating-modes.entities``,
FK-17 §17.3a.15) — the concept is the single source of truth, so the expected
key sets below mirror the formal attribute lists, NOT a duplicate literal from
the mapper. Also pins the Postgres-only fail-closed gate (AK7) and the
``transferred``-has-no-writer rejection (AG3-137 scope §1). Pure and DB-free.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
import yaml

from agentkit.backend.control_plane.ownership import (
    BINDING_VERSION_SQL_CHECK,
    OwnershipAcquisition,
    OwnershipStatus,
)
from agentkit.backend.control_plane.records import (
    BackendInstanceIdentityRecord,
    ControlPlaneOperationRecord,
    EdgeCommandRecord,
    ObjectMutationClaimRecord,
    RunOwnershipRecord,
    TakeoverChallengeRecord,
    TakeoverChallengeRepoRecord,
    TakeoverTransferRecord,
)
from agentkit.backend.exceptions import ConfigError
from agentkit.backend.state_backend import persistence_mappers as mappers
from agentkit.backend.state_backend.config import ALLOW_SQLITE_ENV, STATE_BACKEND_ENV
from agentkit.backend.state_backend.harness_edge_command_store import (
    insert_edge_command_record_global,
    list_and_ack_open_edge_command_records_global,
    load_edge_command_record_global,
)
from agentkit.backend.state_backend.operation_ledger import (
    commit_edge_command_result_global,
    insert_object_mutation_claim_global,
    load_object_mutation_claim_global,
)
from agentkit.backend.state_backend.persistence_test_support import reset_backend_cache_for_tests
from agentkit.backend.state_backend.state_backend_connection_manager import (
    load_backend_instance_identity_global,
    save_backend_instance_identity_global,
)
from agentkit.backend.state_backend.story_closure_store import (
    list_push_freshness_records_global,
    load_push_freshness_record_global,
    upsert_push_freshness_record_global,
)
from agentkit.backend.state_backend.story_lifecycle_store import (
    insert_run_ownership_record_global,
    insert_takeover_challenge_global,
    load_active_run_ownership_record_global,
    load_run_ownership_record_global,
    load_takeover_challenge_global,
    load_takeover_transfer_record_global,
    save_takeover_transfer_record_global,
)

if TYPE_CHECKING:
    from collections.abc import Generator

_NOW = datetime(2026, 7, 2, 12, 0, 0, tzinfo=UTC)
_REPO_ROOT = Path(__file__).resolve().parents[3]
_FORMAL_BLOCK = re.compile(
    r"<!-- FORMAL-SPEC:BEGIN -->\s*```yaml\n(.*?)```\s*<!-- FORMAL-SPEC:END -->",
    re.DOTALL,
)
_PERSISTENCE_KEY_OVERRIDES = {
    "repos": "repos_json",
    "open_operation_ids": "open_operation_ids_json",
    "takeover_history_refs": "takeover_history_refs_json",
}


def _load_formal_entities(rel_path: str) -> dict[str, dict[str, Any]]:
    text = (_REPO_ROOT / "concept" / "formal-spec" / rel_path).read_text(
        encoding="utf-8",
    )
    match = _FORMAL_BLOCK.search(text)
    assert match is not None, f"FORMAL-SPEC block not found in {rel_path}"
    data = yaml.safe_load(match.group(1))
    assert isinstance(data, dict)
    entities = data["entities"]
    assert isinstance(entities, list)
    return {str(entity["id"]): entity for entity in entities}


_STATE_STORAGE_ENTITIES = _load_formal_entities("state-storage/entities.md")
_OPERATING_MODE_ENTITIES = _load_formal_entities("operating-modes/entities.md")


def _identity_fields(entity: dict[str, Any]) -> set[str]:
    raw = entity.get("identity_key", entity.get("identity", ""))
    return {part.strip() for part in str(raw).split("+") if part.strip()}


def _formal_persisted_keys(
    entity: dict[str, Any],
    *,
    include_identity: bool = False,
    additive: set[str] | None = None,
) -> set[str]:
    raw_attrs = entity["attributes"]
    assert isinstance(raw_attrs, list)
    names = {str(name) for name in raw_attrs}
    if include_identity:
        names |= _identity_fields(entity)
    persisted = {_PERSISTENCE_KEY_OVERRIDES.get(name, name) for name in names}
    return persisted | (additive or set())

# Expected row-dict key sets == the formal entity attribute sets (SSOT).
_RUN_OWNERSHIP_KEYS = _formal_persisted_keys(
    _OPERATING_MODE_ENTITIES["operating-modes.entity.run-ownership-record"],
    include_identity=True,
    additive={"audit_ref"},
)
_CLAIM_KEYS = _formal_persisted_keys(
    _STATE_STORAGE_ENTITIES["state-storage.entity.object-mutation-claim"],
)
_TAKEOVER_KEYS = _formal_persisted_keys(
    _STATE_STORAGE_ENTITIES["state-storage.entity.takeover-transfer-record"],
)
_TAKEOVER_CHALLENGE_KEYS = _formal_persisted_keys(
    _STATE_STORAGE_ENTITIES["state-storage.entity.takeover-challenge"],
)
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
        reconciled_at=_NOW,
        reconcile_ref="admin_transition:1",
    )
    row = mappers.takeover_transfer_to_row(record)
    assert set(row) == _TAKEOVER_KEYS
    assert not (set(row) & {"snapshot", "binary_diff", "index_status"})
    assert row["last_push_at"] == _NOW.isoformat()
    assert mappers.takeover_transfer_row_to_record(row) == record


@pytest.mark.contract
def test_takeover_challenge_row_is_field_exact_and_roundtrips() -> None:
    record = TakeoverChallengeRecord(
        challenge_id="challenge-1",
        request_op_id="op-request",
        project_key="tenant-a",
        story_id="AG3-100",
        run_id="run-1",
        requesting_session_id="sess-b",
        requesting_principal_type="orchestrator",
        reason="stalled owner",
        owner_session_id="sess-a",
        ownership_epoch=2,
        binding_version="3",
        phase_status="ACTIVE",
        issued_at=_NOW,
        expires_at=_NOW.replace(minute=15),
        repos=(
            TakeoverChallengeRepoRecord(
                repo_id="repo-a",
                takeover_base_sha="abc123",
                last_push_at=_NOW,
                push_lag_hint="fresh",
                base_quality="verified_pushed",
            ),
        ),
        open_operation_ids=("op-live",),
        takeover_history_refs=("confirm-old",),
    )
    row = mappers.takeover_challenge_to_row(record)
    assert set(row) == _TAKEOVER_CHALLENGE_KEYS
    assert mappers.takeover_challenge_row_to_record(row) == record


@pytest.mark.contract
def test_backend_instance_identity_row_is_field_exact_and_roundtrips() -> None:
    record = BackendInstanceIdentityRecord("inst-1", 4, _NOW)
    row = mappers.backend_instance_identity_to_row(record)
    assert set(row) == _INSTANCE_KEYS
    assert mappers.backend_instance_identity_row_to_record(row) == record


@pytest.mark.contract
def test_postgres_schema_binding_version_check_is_single_sourced() -> None:
    """target-3 / SSOT: the fresh-schema DDL CHECK regex == BINDING_VERSION_SQL_CHECK.

    ``ownership.BINDING_VERSION_SQL_CHECK`` is the ONE canonical source for the
    ``binding_version`` value domain: the record-boundary predicate
    (``is_canonical_binding_version``) and the existing-schema ALTER in
    ``postgres_store._ensure_session_binding_constraints`` both derive from it. The
    static ``postgres_schema.sql`` fresh-schema CREATE TABLE cannot interpolate a
    Python constant, so this guard pins its literal against the constant instead —
    a drift between the fresh-schema CHECK and the constant turns this contract red
    (Codex ERROR §4 / target-3, no second value-domain source).
    """
    from agentkit.backend.state_backend import postgres_store

    sql_text = (
        Path(postgres_store.__file__)
        .with_name("postgres_schema.sql")
        .read_text(encoding="utf-8")
    )
    expected = f"CHECK (binding_version ~ '{BINDING_VERSION_SQL_CHECK}')"
    assert expected in sql_text, (
        "postgres_schema.sql binding_version CHECK regex drifted from "
        "ownership.BINDING_VERSION_SQL_CHECK (target-3 SSOT guard)"
    )


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
        insert_takeover_challenge_global(
            TakeoverChallengeRecord(
                challenge_id="challenge-1",
                request_op_id="op-request",
                project_key="tenant-a",
                story_id="AG3-100",
                run_id="run-1",
                requesting_session_id="sess-b",
                requesting_principal_type="orchestrator",
                reason="stalled owner",
                owner_session_id="sess-a",
                ownership_epoch=1,
                binding_version="1",
                phase_status="ACTIVE",
                issued_at=_NOW,
                expires_at=_NOW.replace(minute=15),
                repos=(),
                open_operation_ids=(),
                takeover_history_refs=(),
            )
        )
    with pytest.raises(ConfigError):
        load_takeover_challenge_global("challenge-1")
    with pytest.raises(ConfigError):
        save_backend_instance_identity_global(identity)
    with pytest.raises(ConfigError):
        load_backend_instance_identity_global("inst-1")


@pytest.mark.contract
def test_push_freshness_entrypoints_fail_closed_on_sqlite(
    sqlite_backend_env: None,
) -> None:
    """AG3-147 AC13: the push-freshness / push-backlog store is Postgres-only (K5).

    Every ``push_freshness_records`` facade entrypoint fails closed with an
    explicit ``ConfigError`` on a non-Postgres backend
    (``_require_control_plane_backend``, the SAME gate AG3-137/AG3-145 use) --
    there is NO SQLite mirror and no silent fallback (negative test).
    """
    del sqlite_backend_env
    from datetime import UTC, datetime

    from agentkit.backend.control_plane.push_sync import PushFreshnessRecord

    record = PushFreshnessRecord(
        project_key="tenant-a",
        story_id="AG3-147",
        run_id="run-1",
        repo_id="repo-a",
        last_reported_head_sha="a" * 40,
        last_pushed_head_sha="a" * 40,
        last_reported_at=datetime(2026, 7, 6, tzinfo=UTC),
        last_sync_point_id="phase_completion:op-1",
        last_command_id="run-1::sync_push::phase_completion:op-1::repo-a",
        backlog=False,
        backlog_detail=None,
    )

    with pytest.raises(ConfigError, match="Postgres"):
        upsert_push_freshness_record_global(record)
    with pytest.raises(ConfigError):
        load_push_freshness_record_global("tenant-a", "AG3-147", "run-1", "repo-a")
    with pytest.raises(ConfigError):
        list_push_freshness_records_global("tenant-a", "AG3-147", "run-1")


@pytest.mark.contract
def test_edge_command_entrypoints_fail_closed_on_sqlite(
    sqlite_backend_env: None,
) -> None:
    """AG3-145 AC10: the Edge-Command-Queue store is Postgres-only (K5).

    Every ``edge_command_records`` entrypoint fails closed with an explicit
    ``ConfigError`` on a non-Postgres backend (``_require_control_plane_backend``,
    the SAME gate AG3-137 already established) -- no SQLite implementation, no
    silent fallback.
    """
    del sqlite_backend_env
    command = EdgeCommandRecord(
        command_id="cmd-1",
        project_key="tenant-a",
        story_id="AG3-100",
        run_id="run-1",
        session_id="sess-1",
        command_kind="provision_worktree",
        payload={},
        status="created",
        ownership_epoch=1,
        created_at=_NOW,
    )
    op_record = ControlPlaneOperationRecord(
        op_id="op-1",
        project_key="tenant-a",
        story_id="AG3-100",
        run_id="run-1",
        session_id="sess-1",
        operation_kind="edge_command_result",
        phase=None,
        status="committed",
        response_payload={},
        created_at=_NOW,
        updated_at=_NOW,
    )

    with pytest.raises(ConfigError, match="Postgres"):
        insert_edge_command_record_global(command)
    with pytest.raises(ConfigError, match="Postgres"):
        load_edge_command_record_global("cmd-1")
    with pytest.raises(ConfigError, match="Postgres"):
        list_and_ack_open_edge_command_records_global(
            project_key="tenant-a", run_id="run-1", session_id="sess-1", delivered_at=_NOW,
        )
    with pytest.raises(ConfigError, match="Postgres"):
        commit_edge_command_result_global(
            op_record,
            command_id="cmd-1",
            result_status="completed",
            completed_at=_NOW,
            result_op_id="op-1",
            result_type="worktree_report",
            result_payload={},
            expected_ownership_epoch=1,
        )
