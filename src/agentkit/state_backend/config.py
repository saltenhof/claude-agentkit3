"""Configuration helpers for canonical state backend selection."""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum

STATE_BACKEND_ENV = "AGENTKIT_STATE_BACKEND"
STATE_DATABASE_URL_ENV = "AGENTKIT_STATE_DATABASE_URL"
ALLOW_SQLITE_ENV = "AGENTKIT_ALLOW_SQLITE"


class StateBackendKind(StrEnum):
    SQLITE = "sqlite"
    POSTGRES = "postgres"


@dataclass(frozen=True)
class StateBackendConfig:
    """Resolved state-backend configuration for the current process."""

    backend: StateBackendKind
    database_url: str | None = None


def load_state_backend_config() -> StateBackendConfig:
    """Resolve backend kind and DSN from the environment."""

    raw_kind = os.environ.get(STATE_BACKEND_ENV, StateBackendKind.POSTGRES.value)
    try:
        backend = StateBackendKind(raw_kind)
    except ValueError as exc:
        raise RuntimeError(
            f"Unsupported {STATE_BACKEND_ENV}={raw_kind!r}; "
            "expected 'postgres' or 'sqlite'"
        ) from exc

    if backend is StateBackendKind.SQLITE and not _sqlite_allowed():
        raise RuntimeError(
            "SQLite backend is disabled for runtime/build/contract/integration/e2e "
            f"paths. Set {ALLOW_SQLITE_ENV}=1 only for narrow unit-test execution.",
        )

    database_url = os.environ.get(STATE_DATABASE_URL_ENV)
    return StateBackendConfig(
        backend=backend,
        database_url=database_url,
    )


def _sqlite_allowed() -> bool:
    raw = os.environ.get(ALLOW_SQLITE_ENV, "")
    return raw.lower() in {"1", "true", "yes", "on"}


__all__ = [
    "STATE_BACKEND_ENV",
    "STATE_DATABASE_URL_ENV",
    "ALLOW_SQLITE_ENV",
    "StateBackendConfig",
    "StateBackendKind",
    "load_state_backend_config",
]
