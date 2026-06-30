"""AG3-126 AC1: the Story-BC read port hangs only on the Protocol.

Regression guard (FK-07 §7.6): ``agentkit.backend.story.repository`` must no
longer import the generic ``load_*_global`` story loaders from
``agentkit.backend.state_backend.store`` — the productive adapter
(``state_backend.store.story_read_repository``) is the single edge that knows
those loaders.
"""

from __future__ import annotations

import ast
from pathlib import Path

import agentkit.backend.story.repository as story_repository_module
from agentkit.backend.state_backend.store.story_read_repository import (
    StateBackendStoryReadRepository,
)
from agentkit.backend.story.repository import StoryReadPort

_STORY_LOADER_PREFIX = "load_"
_STATE_BACKEND_ROOT = "agentkit.backend.state_backend"


def _imported_names_from_state_backend(source: str) -> list[str]:
    """Return every name imported FROM an ``agentkit.backend.state_backend*`` module."""
    tree = ast.parse(source)
    imported: list[str] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.ImportFrom)
            and node.module is not None
            and (
                node.module == _STATE_BACKEND_ROOT
                or node.module.startswith(f"{_STATE_BACKEND_ROOT}.")
            )
        ):
            imported.extend(alias.name for alias in node.names)
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith(_STATE_BACKEND_ROOT):
                    imported.append(alias.name)
    return imported


def test_story_repository_does_not_import_state_backend_loaders() -> None:
    source = Path(story_repository_module.__file__).read_text(encoding="utf-8")
    imported = _imported_names_from_state_backend(source)

    assert imported == [], (
        "story.repository must not import anything from state_backend; "
        f"found: {imported}"
    )
    # Belt-and-braces: no ``load_*`` story loader leaked in under any alias.
    assert not any(name.startswith(_STORY_LOADER_PREFIX) for name in imported)


def test_productive_adapter_satisfies_runtime_checkable_port() -> None:
    # AC2 (structural, in addition to the real-backend behavioural test):
    # the productive adapter is a structural ``StoryReadPort``.
    assert isinstance(StateBackendStoryReadRepository(), StoryReadPort)
