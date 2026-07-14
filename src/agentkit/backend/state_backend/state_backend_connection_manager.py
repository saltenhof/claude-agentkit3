"""State backend selection, backend guards, and core instance identity."""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

from agentkit.backend.state_backend.config import (
    StateBackendKind,
    load_state_backend_config,
)

if TYPE_CHECKING:
    from datetime import datetime
    from types import ModuleType

    from agentkit.backend.state_backend.backend_instance_identity_types import (
        BackendInstanceIdentityRecord,
    )


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
            "This record family requires the Postgres state backend: the "
            "requested persistence surface is Postgres-only and fails closed "
            "off Postgres. Set AGENTKIT_STATE_BACKEND=postgres.",
        )


def _require_postgres_control_plane_backend() -> None:
    """Fail closed unless the canonical Postgres control plane is active."""
    _require_control_plane_backend()


def save_backend_instance_identity_global(
    record: BackendInstanceIdentityRecord,
) -> None:
    """Upsert the backend-instance-identity record. Fail closed off Postgres."""
    _require_control_plane_backend()
    backend = _backend_module()
    from agentkit.backend.state_backend.persistence_mappers import (
        backend_instance_identity_to_row,
    )

    backend.save_backend_instance_identity_global_row(
        backend_instance_identity_to_row(record),
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
    from agentkit.backend.state_backend.persistence_mappers import (
        backend_instance_identity_row_to_record,
    )

    return backend_instance_identity_row_to_record(row)


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
    from agentkit.backend.state_backend.persistence_mappers import (
        backend_instance_identity_row_to_record,
    )

    return backend_instance_identity_row_to_record(row)


__all__ = [
    "active_backend_is_sqlite",
    "control_plane_backend_available",
    "save_backend_instance_identity_global",
    "load_backend_instance_identity_global",
    "boot_backend_instance_identity_global",
]
