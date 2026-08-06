"""Compatibility import surface for the SQLite state backend."""

from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORT_MODULES = (
    "._common",
    "._story_identity",
    "._schema_runtime",
    "._schema",
    "._connection",
    "._story_project_rows",
    "._runtime_rows",
    "._qa_artifact_rows",
    "._ownership_rows",
    "._purge_rows",
    "._backend_checks",
)

_EXPORTED_CONSTANTS = {
    "_CLAUSE_EVENT_TYPE",
    "_CLAUSE_PROJECT_KEY",
    "_CLAUSE_RUN_ID",
    "_CLAUSE_STORY_ID",
    "_JsonRecord",
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
