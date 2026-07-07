"""Runtime dependency-injection defaults and test adapters."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from agentkit.backend.control_plane.execution_contract_assembly import (
    ExecutionContractDigestOutcome,
)
from agentkit.backend.control_plane.repository import (
    ControlPlaneRuntimeRepository,
    EdgeCommandRepository,
    ObjectMutationClaimRepository,
)
from agentkit.backend.exceptions import (
    EdgeCommandNotOpenError,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from agentkit.backend.control_plane.models import (
        PhaseMutationRequest,
    )
    from agentkit.backend.control_plane.records import (
        BackendInstanceIdentityRecord,
        ControlPlaneOperationRecord,
        EdgeCommandRecord,
    )

logger = logging.getLogger(__name__)

def _require_postgres_control_plane_backend() -> None:
    """Fail closed unless the active state backend supports the control plane (#3).

    The control-plane runtime store (session bindings, story-execution locks and
    the idempotent operation/claim records) lives ONLY in the canonical central
    PostgreSQL runtime persistence (FK-22 §22.9). The SQLite backend is a narrow,
    gated unit-test backend that does not provide the global control-plane tables,
    so a productive ``ControlPlaneRuntimeService`` on SQLite would raise an opaque
    ``RuntimeError`` mid-call inside ``start_phase`` (the atomic claim). This
    surfaces that as an explicit, early ``ConfigError`` at construction instead.

    Raises:
        ConfigError: When the active backend lacks the control-plane store.
    """
    from agentkit.backend.exceptions import ConfigError
    from agentkit.backend.state_backend.store import control_plane_backend_available

    # Resolve the backend support through the sanctioned ``state_backend.store``
    # surface (architecture conformance AC010/AC011: the control plane must not
    # import the raw ``state_backend.config`` driver module directly).
    if not control_plane_backend_available():
        raise ConfigError(
            "The control-plane runtime requires the Postgres state backend: the "
            "control-plane operation/claim, session-binding and lock records are "
            "part of the canonical central PostgreSQL runtime persistence (FK-22 "
            "§22.9) and have no SQLite implementation. Set "
            "AGENTKIT_STATE_BACKEND=postgres for any productive / control-plane "
            "path; fail-closed (#3).",
        )

def _default_di_instance_identity() -> BackendInstanceIdentityRecord:
    """Build the deterministic DI-seam backend instance identity (AG3-138).

    Bound automatically when a repository is DI-injected without an explicit
    identity (test / alternative wiring). A stable, well-formed value keeps the
    claim stamp and the ownership fencing sound; it is NEVER used on the
    productive default-store path (which requires the startup hook).
    """
    from agentkit.backend.control_plane.records import BackendInstanceIdentityRecord

    return BackendInstanceIdentityRecord(
        backend_instance_id="di-wiring-instance",
        instance_incarnation=1,
        updated_at=datetime.now(tz=UTC),
    )


def _default_di_object_claim_repository() -> ObjectMutationClaimRepository:
    """Build a self-contained in-memory object-claim repository (DI seam, AG3-141).

    Mirrors :func:`_default_di_instance_identity`: a directly-constructed
    service with an injected ``repository`` but no explicit
    ``object_claim_repository`` gets THIS in-memory claim store instead of the
    productive Postgres-backed default -- so a DI-injected unit test (a fake
    ``ControlPlaneRuntimeRepository``, no database) is never forced to also
    wire Postgres for the object claim. It honors the SAME per-Story semantics
    as the productive acquire (an object PK collision IS the serialization: the
    Story object cannot be acquired while already held) and the SAME
    ownership-scoped (op_id) release -- never used on the productive
    default-store path.
    """
    held: dict[tuple[str, str, str], tuple[str, str, int]] = {}

    def _acquire(
        *,
        project_key: str,
        serialization_scope: str,
        scope_key: str,
        op_id: str,
        backend_instance_id: str,
        instance_incarnation: int,
        acquired_at: datetime,
    ) -> bool:
        del acquired_at
        #: Mirror ``postgres_store.acquire_object_mutation_claim_global_row``:
        #: INSERT-if-absent on the object PK. The Story object is free -> win;
        #: already claimed (by ANY op) -> busy. That PK collision IS the
        #: serialization -- no cross-scope/project fairness (removed).
        key = (project_key, serialization_scope, scope_key)
        if key in held:
            return False
        held[key] = (op_id, backend_instance_id, instance_incarnation)
        return True

    def _release(project_key: str, serialization_scope: str, scope_key: str, op_id: str) -> bool:
        key = (project_key, serialization_scope, scope_key)
        current = held.get(key)
        if current is None or current[0] != op_id:
            return False
        del held[key]
        return True

    return ObjectMutationClaimRepository(acquire_claim=_acquire, release_claim=_release)


def _resolve_edge_command_repository(
    edge_command_repository: EdgeCommandRepository | None,
    repository: ControlPlaneRuntimeRepository | None,
) -> EdgeCommandRepository:
    """Resolve the Edge-Command-Queue DI seam (AG3-145).

    Mirrors the ``object_claim_repository`` resolution: a DI-injected
    ``repository`` (test / alternative wiring) that does not ALSO inject an
    explicit ``edge_command_repository`` gets a self-contained in-memory fake
    (:func:`_default_di_edge_command_repository`) -- never the productive
    Postgres-backed default -- so a DB-free unit test is never forced to also
    wire Postgres for the command queue.
    """
    if edge_command_repository is not None:
        return edge_command_repository
    if repository is not None:
        return _default_di_edge_command_repository()
    return EdgeCommandRepository()


class _InMemoryEdgeCommandStore:
    """Self-contained in-memory Edge-Command store for DI tests."""

    def __init__(self) -> None:
        self._commands: dict[str, EdgeCommandRecord] = {}

    def insert(self, record: EdgeCommandRecord) -> None:
        if record.command_id in self._commands:
            raise ValueError(f"duplicate command_id {record.command_id!r}")
        self._commands[record.command_id] = record

    def commission(self, record: EdgeCommandRecord) -> bool:
        if record.command_id in self._commands:
            return False
        self._commands[record.command_id] = record
        return True

    def load(self, command_id: str) -> EdgeCommandRecord | None:
        return self._commands.get(command_id)

    def list_and_ack(
        self,
        *,
        project_key: str,
        run_id: str,
        session_id: str,
        delivered_at: datetime,
    ) -> tuple[EdgeCommandRecord, ...]:
        from dataclasses import replace

        acked: list[EdgeCommandRecord] = []
        for record in self._matching_open(project_key, run_id, session_id):
            if record.status == "created":
                record = replace(record, status="delivered", delivered_at=delivered_at)
                self._commands[record.command_id] = record
            acked.append(record)
        return tuple(sorted(acked, key=lambda r: (r.created_at, r.command_id)))

    def commit_result(
        self,
        op_record: ControlPlaneOperationRecord,
        *,
        command_id: str,
        result_status: str,
        completed_at: datetime,
        result_op_id: str,
        result_type: str,
        result_payload: dict[str, object],
        expected_ownership_epoch: int,
    ) -> None:
        from dataclasses import replace

        del op_record, expected_ownership_epoch
        current = self._commands.get(command_id)
        if current is None or current.status not in {"created", "delivered"}:
            raise EdgeCommandNotOpenError(command_id)
        self._commands[command_id] = replace(
            current,
            status=result_status,
            completed_at=completed_at,
            result_op_id=result_op_id,
            result_type=result_type,
            result_payload=result_payload,
        )

    def supersede_command(
        self,
        *,
        command_id: str,
        completed_at: datetime,
        result_payload: dict[str, object],
    ) -> bool:
        from dataclasses import replace

        current = self._commands.get(command_id)
        if current is None or current.status not in {"created", "delivered"}:
            return False
        self._commands[command_id] = replace(
            current,
            status="superseded",
            completed_at=completed_at,
            result_type="command_superseded",
            result_payload=result_payload,
        )
        return True

    def _matching_open(
        self,
        project_key: str,
        run_id: str,
        session_id: str,
    ) -> tuple[EdgeCommandRecord, ...]:
        return tuple(
            record
            for record in self._commands.values()
            if record.project_key == project_key
            and record.run_id == run_id
            and record.session_id == session_id
            and record.status in {"created", "delivered"}
        )


def _default_di_edge_command_repository() -> EdgeCommandRepository:
    """Build a self-contained in-memory Edge-Command repository (DI seam, AG3-145)."""

    store = _InMemoryEdgeCommandStore()
    return EdgeCommandRepository(
        insert_command=store.insert,
        commission_command=store.commission,
        load_command=store.load,
        list_and_ack_open_commands=store.list_and_ack,
        commit_result=store.commit_result,
        supersede_command=store.supersede_command,
    )


def _default_di_execution_contract_digest_reader() -> Callable[[PhaseMutationRequest, str], ExecutionContractDigestOutcome]:
    """Build a trivial, always-succeeding digest reader (DI seam, AG3-143).

    Mirrors :func:`_default_di_object_claim_repository`: a directly
    constructed service with an injected ``repository`` but no explicit
    ``execution_contract_digest_reader`` gets THIS reader instead of the
    productive state-backend/filesystem gathering (project registration,
    story specification, skill bindings, run-prompt-pin) -- so a DI-injected
    unit test (a fake ``ControlPlaneRuntimeRepository``, no database) is
    never forced to also wire a real project/story-spec/skill-binding/
    prompt-bundle fixture just to exercise a fresh setup start. It still
    exercises the REAL digest FORMATION
    (``compute_execution_contract_digest``) over fixed, deterministic
    placeholder inputs -- never a hand-faked digest STRING -- so the
    persisted-digest code path is genuinely exercised end to end.
    """

    def _reader(
        request: PhaseMutationRequest,
        run_id: str,
    ) -> ExecutionContractDigestOutcome:
        del request, run_id
        from agentkit.backend.prompt_runtime.execution_contract import (
            ExecutionContractInputs,
            RunPromptPinComponent,
            StorySpecComponent,
            compute_execution_contract_digest,
        )

        inputs = ExecutionContractInputs(
            story_spec=StorySpecComponent(),
            project_config_version="di-fake-config-version",
            project_config_digest="di-fake-config-digest",
            capability_version="di-fake-capability-version",
            run_prompt_pin=RunPromptPinComponent(
                prompt_bundle_id="di-fake-bundle",
                prompt_bundle_version="di-fake-bundle-version",
                prompt_manifest_sha256="0" * 64,
            ),
        )
        return ExecutionContractDigestOutcome(
            digest=compute_execution_contract_digest(inputs),
            rejection_reason=None,
        )

    return _reader
