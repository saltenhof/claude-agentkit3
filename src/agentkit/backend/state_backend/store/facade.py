"""Repository facade: stable public API for state persistence."""

from __future__ import annotations

from importlib import import_module

_MODULE_NAMES = (
    "_facade_backend",
    "_facade_runtime_scope",
    "_facade_story_metadata",
    "_facade_runtime_records",
    "_facade_control_plane_ownership",
    "_facade_control_plane_records",
    "_facade_control_plane_operations",
    "_facade_purge_metrics",
    "_facade_qa_artifacts",
    "_facade_predicates",
)

_backend_impl = import_module(
    "agentkit.backend.state_backend.store._facade_backend",
)
_backend_module = _backend_impl._backend_module


def _install_exports() -> tuple[str, ...]:
    names: list[str] = []
    for module_name in _MODULE_NAMES:
        module = import_module(f"agentkit.backend.state_backend.store.{module_name}")
        for name in module.__all__:
            globals()[name] = getattr(module, name)
            names.append(name)
    return tuple(names)


__all__ = _install_exports()
