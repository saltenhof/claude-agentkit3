"""AG3-127 AC5: the telemetry read adapter preserves the fail-closed contract.

The adapter delegates 1:1 to ``load_execution_events_for_project_global``. A
backend failure (e.g. a missing event table) must propagate unchanged — never be
masked by a silent empty-OK result — while a legitimately-empty project passes
through as an empty list exactly as the loader defines it.
"""

from __future__ import annotations

import pytest

import agentkit.backend.state_backend.store.telemetry_read_repository as adapter_module
from agentkit.backend.state_backend.store.telemetry_read_repository import (
    StateBackendProjectTelemetryEventSource,
)


class _MissingTableError(RuntimeError):
    """Stand-in for the backend error a missing event table would raise."""


def test_missing_backend_error_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(project_key: str, *, limit: int | None = None) -> list[object]:
        raise _MissingTableError("no such table: execution_events")

    monkeypatch.setattr(
        adapter_module, "load_execution_events_for_project_global", _boom
    )

    with pytest.raises(_MissingTableError):
        StateBackendProjectTelemetryEventSource().events_for_project("tenant-a")


def test_absent_project_passes_through_as_empty_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def _empty(project_key: str, *, limit: int | None = None) -> list[object]:
        captured["project_key"] = project_key
        captured["limit"] = limit
        return []

    monkeypatch.setattr(
        adapter_module, "load_execution_events_for_project_global", _empty
    )

    result = StateBackendProjectTelemetryEventSource().events_for_project(
        "tenant-a", limit=50
    )

    assert result == []
    # The project scope and limit are forwarded as keyword args (no silent default).
    assert captured == {"project_key": "tenant-a", "limit": 50}
