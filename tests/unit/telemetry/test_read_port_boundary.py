"""AG3-127 AC1/AC4: telemetry + project read edges hang only on their ports.

Regression guards (FK-07 §7.6/§7.8):

* ``agentkit.backend.telemetry.sse_stream`` must no longer import the generic
  ``load_execution_events_for_project_global`` loader from
  ``agentkit.backend.state_backend`` — the productive adapter
  (``state_backend.store.telemetry_read_repository``) is the single edge that
  knows that loader.
* ``agentkit.backend.project_management.repository`` (the ``ProjectRepository``
  read port) must not import anything from ``agentkit.backend.state_backend`` —
  the Protocol module hangs on nothing but the domain entity (AG3-126 mirror).
* ``agentkit.backend.project_management.read_model_routes`` (the project
  read-model surface) must not import the generic ``state_backend.store.facade``
  mega-facade nor any ``load_*`` global loader (FK-07 §7.8 Punkt 8). It composes
  read models through injected Protocol ports; its only sanctioned state-backend
  seam is the published ``StoryReadPort`` adapter (AG3-126) used as a fallback
  default — never the generic loader facade.
"""

from __future__ import annotations

import ast
from pathlib import Path

import agentkit.backend.project_management.read_model_routes as read_model_routes_module
import agentkit.backend.project_management.repository as project_repository_module
import agentkit.backend.telemetry.sse_stream as sse_stream_module
from agentkit.backend.state_backend.store.telemetry_read_repository import (
    StateBackendProjectTelemetryEventSource,
)
from agentkit.backend.telemetry.repository import ProjectTelemetryEventSource

_STATE_BACKEND_ROOT = "agentkit.backend.state_backend"
_FACADE_MODULE = "agentkit.backend.state_backend.store.facade"
_LOADER_PREFIX = "load_"


def _facade_or_loader_imports_from_state_backend(source: str) -> list[str]:
    """Return generic facade/``load_*`` loader imports from state_backend (FK-07 §7.8).

    The published port adapters (e.g. ``StateBackendStoryReadRepository``) are the
    sanctioned seam and are NOT flagged; only imports of the generic loader facade
    or of a bare ``load_*`` global loader are reported.
    """
    tree = ast.parse(source)
    flagged: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            if node.module == _FACADE_MODULE:
                flagged.extend(f"{node.module}.{alias.name}" for alias in node.names)
            elif node.module.startswith(f"{_STATE_BACKEND_ROOT}"):
                flagged.extend(
                    f"{node.module}.{alias.name}"
                    for alias in node.names
                    if alias.name.startswith(_LOADER_PREFIX)
                )
        if isinstance(node, ast.Import):
            flagged.extend(
                alias.name for alias in node.names if alias.name == _FACADE_MODULE
            )
    return flagged


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


def test_sse_stream_does_not_import_state_backend_loaders() -> None:
    source = Path(sse_stream_module.__file__).read_text(encoding="utf-8")
    imported = _imported_names_from_state_backend(source)

    assert imported == [], (
        "telemetry.sse_stream must not import anything from state_backend; "
        f"found: {imported}"
    )
    # Belt-and-braces: no ``load_*`` loader leaked in under any alias.
    assert not any(name.startswith(_LOADER_PREFIX) for name in imported)


def test_project_repository_port_hangs_only_on_protocol() -> None:
    # AC4 (AG3-126 mirror): the ProjectRepository read port imports nothing
    # from state_backend — the productive adapter is the single edge.
    source = Path(project_repository_module.__file__).read_text(encoding="utf-8")
    imported = _imported_names_from_state_backend(source)

    assert imported == [], (
        "project_management.repository (read port) must not import anything from "
        f"state_backend; found: {imported}"
    )


def test_project_read_model_routes_do_not_import_facade_loaders() -> None:
    # AC4: the project read-model surface never reaches for the generic
    # state_backend.store.facade / load_* mega-facade (FK-07 §7.8 Punkt 8); the
    # published StoryReadPort adapter (AG3-126) is the only sanctioned seam.
    source = Path(read_model_routes_module.__file__).read_text(encoding="utf-8")
    flagged = _facade_or_loader_imports_from_state_backend(source)

    assert flagged == [], (
        "project_management.read_model_routes must read through published ports, "
        f"never the generic state_backend loader facade; found: {flagged}"
    )


def test_productive_adapter_satisfies_runtime_checkable_port() -> None:
    # AC2 (structural, in addition to the real-backend behavioural test):
    # the productive adapter is a structural ``ProjectTelemetryEventSource``.
    assert isinstance(StateBackendProjectTelemetryEventSource(), ProjectTelemetryEventSource)
