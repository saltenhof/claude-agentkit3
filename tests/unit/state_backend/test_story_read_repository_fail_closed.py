"""AG3-126 AC5: the StoryReadPort adapter preserves the fail-closed contract.

The adapter delegates 1:1 to the global story loaders. A backend failure (e.g. a
missing table) must propagate unchanged — never be masked by a silent
empty-OK result — while a legitimately-absent row passes through as
``None``/an empty list exactly as the loaders define it.
"""

from __future__ import annotations

import pytest

import agentkit.backend.state_backend.store.story_read_repository as adapter_module
from agentkit.backend.state_backend.store.story_read_repository import (
    StateBackendStoryReadRepository,
)


class _MissingTableError(RuntimeError):
    """Stand-in for the backend error a missing story table would raise."""


def test_missing_backend_error_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(project_key: str, store_dir: object = None) -> list[object]:
        raise _MissingTableError("no such table: story_contexts")

    monkeypatch.setattr(adapter_module, "load_story_contexts_global", _boom)

    with pytest.raises(_MissingTableError):
        StateBackendStoryReadRepository().list_story_contexts("tenant-a")


def test_absent_row_passes_through_as_none(monkeypatch: pytest.MonkeyPatch) -> None:
    def _absent(project_key: str, story_id: str, store_dir: object = None) -> None:
        return None

    monkeypatch.setattr(adapter_module, "load_story_context_global", _absent)

    result = StateBackendStoryReadRepository().load_story_context("tenant-a", "AG3-1")

    assert result is None


def test_absent_events_pass_through_as_empty_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def _none(
        project_key: str,
        story_id: str,
        *,
        run_id: str | None = None,
        event_type: str | None = None,
        limit: int | None = None,
    ) -> list[object]:
        captured["run_id"] = run_id
        captured["limit"] = limit
        return []

    monkeypatch.setattr(adapter_module, "load_execution_events_global", _none)

    result = StateBackendStoryReadRepository().load_recent_execution_events(
        "tenant-a", "AG3-1", "run-1", 25
    )

    assert result == []
    # The run scope and limit are forwarded as keyword args (no silent default).
    assert captured == {"run_id": "run-1", "limit": 25}
