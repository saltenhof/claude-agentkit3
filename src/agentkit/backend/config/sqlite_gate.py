"""SQLite-backend gating policy (config foundation).

In AK3 the SQLite backend is permitted **only** for narrow unit-test
execution; productive use is forbidden (the canonical backend is
PostgreSQL). The gate is the ``AGENTKIT_ALLOW_SQLITE`` environment flag and
fails closed: unless it is explicitly truthy, SQLite paths refuse to run.

This predicate lives in the config foundation (``agentkit.backend.config``) so that
*any* layer -- including A-type governance components -- may consult the gate
without importing the T-type state-backend driver boundary
(``agentkit.backend.state_backend.config``). Importing the driver boundary from an
A-component violates architecture-conformance AC011 and the blood-type rule
"A must not import T directly" (``concept/methodology/software-blutgruppen.md``).
The state-backend driver config re-exports these names for backward
compatibility, so this module is the single source of truth.
"""

from __future__ import annotations

import os

ALLOW_SQLITE_ENV = "AGENTKIT_ALLOW_SQLITE"


def sqlite_allowed() -> bool:
    """Return ``True`` iff the SQLite backend is explicitly enabled.

    Returns:
        ``True`` when ``AGENTKIT_ALLOW_SQLITE`` is one of ``1/true/yes/on``
        (case-insensitive), else ``False``.
    """
    raw = os.environ.get(ALLOW_SQLITE_ENV, "")
    return raw.lower() in {"1", "true", "yes", "on"}


def assert_sqlite_allowed() -> None:
    """Raise unless the SQLite backend is explicitly enabled for tests.

    Fail-closed: SQLite is test-only in AK3; productive use is forbidden.

    Raises:
        RuntimeError: When ``AGENTKIT_ALLOW_SQLITE`` is not truthy.
    """
    if not sqlite_allowed():
        raise RuntimeError(
            "SQLite backend is disabled for this path. "
            f"Set {ALLOW_SQLITE_ENV}=1 only for narrow unit-test execution.",
        )


__all__ = ["ALLOW_SQLITE_ENV", "assert_sqlite_allowed", "sqlite_allowed"]
