"""Test-Isolation fuer Unit-Tests (Befund 5).

Die ``tests/integration/conftest.py`` aktiviert das session-scoped
``postgres_runtime_env``-Fixture, das ``AGENTKIT_STATE_BACKEND=postgres``
fuer die gesamte pytest-Session setzt. Sobald Integration-Tests vor
Unit-Tests laufen (alphabetisch erst ``tests/integration``, dann
``tests/unit``), erbt jeder Unit-Test diesen Postgres-Backend-State und
faellt mit ``ConnectionError``/``CorruptStateError`` aus.

Diese autouse-Function-Fixture forciert pro Unit-Test ``sqlite`` und
resettet den ``_backend_module``-Cache vor und nach dem Test. Sie ist
function-scoped (Default) und greift damit nach dem session-scoped
postgres-Fixture, ohne dessen ``yield`` zu unterbrechen.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from agentkit.state_backend.store import reset_backend_cache_for_tests

if TYPE_CHECKING:
    from collections.abc import Generator


@pytest.fixture(autouse=True)
def _force_sqlite_for_unit_tests(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[None, None, None]:
    """Ueberschreibt etwaige session-globale Postgres-Setups fuer Unit-Tests."""

    monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
    monkeypatch.delenv("AGENTKIT_STATE_DATABASE_URL", raising=False)
    reset_backend_cache_for_tests()
    try:
        yield
    finally:
        reset_backend_cache_for_tests()
