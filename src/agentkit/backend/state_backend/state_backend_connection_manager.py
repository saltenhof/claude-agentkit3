"""State backend selection, backend guards, and core instance identity."""

from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from typing import TYPE_CHECKING

from agentkit.backend.state_backend.config import (
    StateBackendKind,
    load_state_backend_config,
)

if TYPE_CHECKING:
    from types import ModuleType

    from agentkit.backend.control_plane.records import BackendInstanceIdentityRecord


@lru_cache(maxsize=1)
def _backend_module() -> ModuleType:
    config = load_state_backend_config()
    if config.backend is StateBackendKind.SQLITE:
        from agentkit.backend.state_backend import sqlite_store

        return sqlite_store

    from agentkit.backend.state_backend import postgres_store

    return postgres_store


def active_backend_is_sqlite() -> bool:
    """Return ``True`` when the active backend is SQLite."""
    config = load_state_backend_config()
    return config.backend is StateBackendKind.SQLITE


def control_plane_backend_available() -> bool:
    """Return whether the active backend provides the control-plane store."""
    return hasattr(_backend_module(), "claim_control_plane_operation_global_row")


def _require_control_plane_backend() -> None:
    """Fail closed unless the active backend supports Postgres-only records."""
    if not control_plane_backend_available():
        from agentkit.backend.exceptions import ConfigError

        raise ConfigError(
            "The session-ownership store (run_ownership_records, "
            "object_mutation_claims, takeover_transfer_records, "
            "backend_instance_identity, edge_command_records, "
            "push_freshness_records, ref_protection_degradation_findings) "
            "requires the "
            "Postgres state backend: these tables are Postgres-only (AG3-137 / "
            "AG3-145 / AG3-147 K5) and have no SQLite implementation. Set "
            "AGENTKIT_STATE_BACKEND=postgres; fail-closed.",
        )


def save_backend_instance_identity_global(
    record: BackendInstanceIdentityRecord,
) -> None:
    """Upsert the backend-instance-identity record. Fail closed off Postgres."""
    _require_control_plane_backend()
    backend = _backend_module()
    backend.save_backend_instance_identity_global_row(
        _backend_instance_identity_to_row(record),
    )


def load_backend_instance_identity_global(
    backend_instance_id: str,
) -> BackendInstanceIdentityRecord | None:
    """Load the backend-instance-identity record, or ``None``."""
    _require_control_plane_backend()
    backend = _backend_module()
    row = backend.load_backend_instance_identity_global_row(backend_instance_id)
    if row is None:
        return None
    return _backend_instance_identity_row_to_record(row)


def boot_backend_instance_identity_global(
    candidate_backend_instance_id: str,
    now: datetime,
) -> BackendInstanceIdentityRecord:
    """Atomically resolve the boot-time backend instance identity."""
    _require_control_plane_backend()
    backend = _backend_module()
    row = backend.boot_backend_instance_identity_global_row(
        candidate_backend_instance_id=candidate_backend_instance_id,
        now=now.isoformat(),
    )
    return _backend_instance_identity_row_to_record(row)


def _backend_instance_identity_to_row(
    record: BackendInstanceIdentityRecord,
) -> dict[str, object]:
    return {
        "backend_instance_id": record.backend_instance_id,
        "instance_incarnation": record.instance_incarnation,
        "updated_at": record.updated_at.isoformat(),
    }


def _backend_instance_identity_row_to_record(
    row: dict[str, object],
) -> BackendInstanceIdentityRecord:
    from agentkit.backend.control_plane.records import BackendInstanceIdentityRecord

    return BackendInstanceIdentityRecord(
        backend_instance_id=str(row["backend_instance_id"]),
        instance_incarnation=int(str(row["instance_incarnation"])),
        updated_at=datetime.fromisoformat(str(row["updated_at"])),
    )


__all__ = [
    "active_backend_is_sqlite",
    "control_plane_backend_available",
    "save_backend_instance_identity_global",
    "load_backend_instance_identity_global",
    "boot_backend_instance_identity_global",
]
