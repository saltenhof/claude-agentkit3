"""Backend driver selection and backend-kind guards for the store facade."""

from __future__ import annotations

import sys
from functools import lru_cache
from typing import TYPE_CHECKING, cast

from agentkit.backend.state_backend.config import (
    StateBackendKind,
    load_state_backend_config,
)

if TYPE_CHECKING:
    from pathlib import Path
    from types import ModuleType


JsonRecord = dict[str, object]


@lru_cache(maxsize=1)
def _backend_module() -> ModuleType:
    config = load_state_backend_config()
    if config.backend is StateBackendKind.SQLITE:
        from agentkit.backend.state_backend import sqlite_store

        return sqlite_store

    from agentkit.backend.state_backend import postgres_store

    return postgres_store


def reset_backend_cache_for_tests() -> None:
    """Clear cached backend selection for test-time env switching."""

    _backend_module.cache_clear()
    postgres_store = sys.modules.get("agentkit.backend.state_backend.postgres_store")
    if postgres_store is not None:
        reset_schema_cache = getattr(
            postgres_store,
            "_reset_schema_bootstrap_cache_for_tests",
            None,
        )
        if callable(reset_schema_cache):
            reset_schema_cache()
    schema_bootstrap = sys.modules.get(
        "agentkit.backend.state_backend.schema_bootstrap",
    )
    if schema_bootstrap is not None:
        reset_versioned_schema_cache = getattr(
            schema_bootstrap,
            "_reset_versioned_schema_cache_for_tests",
            None,
        )
        if callable(reset_versioned_schema_cache):
            reset_versioned_schema_cache()


def active_backend_is_sqlite() -> bool:
    """Return ``True`` when the active backend is SQLite.

    Exposes the backend-kind discriminant at the sanctioned ``state_backend.store``
    surface so BCs that need to adapt their construction contract for SQLite
    (e.g. GovernanceObserver reader FIX C) can check without importing the
    restricted ``state_backend.config`` module (architecture conformance AC010/AC011).

    Returns:
        ``True`` iff the active configured backend is SQLite.
    """
    config = load_state_backend_config()
    return config.backend is StateBackendKind.SQLITE


def control_plane_backend_available() -> bool:
    """Whether the active backend provides the control-plane operation store (#3).

    The control-plane runtime store (operation/claim, session-binding and lock
    records) is Postgres-only by design (FK-22 §22.9). This reports whether the
    ACTIVE backend exposes the global control-plane operation row methods, so the
    control plane can fail closed CLEARLY (a non-Postgres backend has none) at the
    sanctioned ``state_backend.store`` surface -- without the control plane
    importing the raw ``state_backend.config`` driver module (architecture
    conformance AC010/AC011).

    Returns:
        ``True`` iff the active backend supports the control-plane store.
    """
    return hasattr(_backend_module(), "claim_control_plane_operation_global_row")


def _require_control_plane_backend() -> None:
    """Fail closed with a ``ConfigError`` unless the Postgres control plane is active.

    AG3-137 (AK7, K5): the session-ownership tables (``run_ownership_records``,
    ``object_mutation_claims``, ``takeover_transfer_records``,
    ``backend_instance_identity``) are Postgres-only by design. AG3-145 reuses
    this SAME gate for the Edge-Command-Queue table (``edge_command_records``)
    -- one more Postgres-only table, the identical fail-closed contract. Access
    through a non-Postgres backend is a configuration error, surfaced explicitly
    at the sanctioned ``state_backend.store`` surface (the same fail-closed
    contract as ``control_plane.runtime._require_postgres_control_plane_backend``),
    never a silent no-op or a SQLite fallback.

    Raises:
        ConfigError: When the active backend does not provide the control-plane
            store.
    """
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


def _cast_json_record(value: object) -> JsonRecord | None:
    return cast("JsonRecord | None", value)


def load_json_safe(path: Path) -> JsonRecord | None:
    return _cast_json_record(_backend_module().load_json_safe(path))


__all__ = [
    "JsonRecord",
    "reset_backend_cache_for_tests",
    "active_backend_is_sqlite",
    "control_plane_backend_available",
    "load_json_safe",
]
