"""Compatibility import surface for the PostgreSQL state backend."""

from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORT_MODULES = (
    "._sql_script",
    "._compat",
    "._json_projection",
    "._connection",
    "._schema",
    "._story_project_rows",
    "._runtime_rows",
    "._mutation_commit_rows",
    "._ownership_rows",
    "._control_plane_rows",
    "._takeover_rows",
    "._ccag_request_rows",
    "._ccag_lease_rows",
    "._recovery_rows",
    "._qa_artifact_rows",
    "._purge_rows",
)

_EXPORTED_CONSTANTS = {
    "_AG3_137_ADDITIVE_COLUMNS",
    "_AG3_137_BINDING_CONSTRAINTS",
    "_AG3_147_PUSH_FRESHNESS_COLUMNS",
    "_BACKEND_INSTANCE_IDENTITY_BOOT_LOCK_KEY",
    "_DEFAULT_STATE_POOL_MAX_SIZE",
    "_FACT_TABLE_NAMES",
    "_JsonRecord",
    "_OptionalString",
    "_POOL",
    "_POOL_LOCK",
    "_POOL_URL",
    "_PROJECT_KEY_FILTER",
    "_RUN_ID_FILTER",
    "_SCHEMA_ENSURED_NAMES",
    "_SCHEMA_ENSURE_LOCK",
    "_STATE_POOL_MAX_SIZE_ENV",
    "_STORY_ID_FILTER",
}


def _is_owned_export(module_name: str, name: str, value: Any) -> bool:
    return name in _EXPORTED_CONSTANTS or getattr(value, "__module__", None) == module_name


_exported_names: list[str] = []
for _module_ref in _EXPORT_MODULES:
    _module = import_module(_module_ref, __name__)
    for _name, _value in vars(_module).items():
        if not _name.startswith("__") and _is_owned_export(_module.__name__, _name, _value):
            globals()[_name] = _value
            _exported_names.append(_name)

__all__ = tuple(sorted(set(_exported_names)))

del _exported_names, _module, _module_ref, _name, _value
