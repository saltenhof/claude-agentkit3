"""Repository facade: stable public API for state persistence."""

from __future__ import annotations

from importlib import import_module

from agentkit.backend.state_backend.persistence_json_codec import (
    JsonRecord as JsonRecord,
)
from agentkit.backend.state_backend.persistence_json_codec import (
    load_json_safe as load_json_safe,
)
from agentkit.backend.state_backend.persistence_test_support import (
    reset_backend_cache_for_tests as reset_backend_cache_for_tests,
)
from agentkit.backend.state_backend.state_backend_connection_manager import (
    _backend_module as _backend_module,
)
from agentkit.backend.state_backend.state_backend_connection_manager import (
    active_backend_is_sqlite as active_backend_is_sqlite,
)
from agentkit.backend.state_backend.state_backend_connection_manager import (
    boot_backend_instance_identity_global as boot_backend_instance_identity_global,
)
from agentkit.backend.state_backend.state_backend_connection_manager import (
    control_plane_backend_available as control_plane_backend_available,
)
from agentkit.backend.state_backend.state_backend_connection_manager import (
    load_backend_instance_identity_global as load_backend_instance_identity_global,
)
from agentkit.backend.state_backend.state_backend_connection_manager import (
    save_backend_instance_identity_global as save_backend_instance_identity_global,
)

_MODULE_NAMES = (
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

_STATIC_EXPORTS = (
    "JsonRecord",
    "active_backend_is_sqlite",
    "control_plane_backend_available",
    "save_backend_instance_identity_global",
    "load_backend_instance_identity_global",
    "boot_backend_instance_identity_global",
    "load_json_safe",
    "reset_backend_cache_for_tests",
)


def _install_exports() -> tuple[str, ...]:
    names = list(_STATIC_EXPORTS)
    for module_name in _MODULE_NAMES:
        module = import_module(f"agentkit.backend.state_backend.store.{module_name}")
        for name in module.__all__:
            globals()[name] = getattr(module, name)
            names.append(name)
    return tuple(names)


__all__ = _install_exports()
