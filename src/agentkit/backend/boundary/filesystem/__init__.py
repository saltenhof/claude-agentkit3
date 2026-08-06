"""Infrastructure I/O boundary module for atomic filesystem operations.

Boundary kind: infrastructure_io
Blood group:   R
Importable by: any
May import:    boundary.shared
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agentkit.backend.boundary.filesystem.atomic import atomic_write_json
    from agentkit.backend.boundary.filesystem.path_identity import (
        AK3_OWNER_POLICIES,
        FilesystemContainmentError,
        FilesystemOwnerPolicies,
        assert_project_local_file_path,
        is_filesystem_link,
        matches_resolved_interpreter_owner,
        matches_resolved_path_owner,
    )
    from agentkit.backend.boundary.filesystem.read import (
        load_json_object,
        read_projection_json_object,
    )


def __getattr__(name: str) -> Any:
    """Load boundary operations only when a consumer requests them.

    The installer build backend imports the interpreter in an isolated PEP-517
    environment before runtime dependencies exist. Eagerly importing unrelated
    write helpers here would pull those dependencies across that preflight
    boundary even when the interpreter only needs stdlib path identity.
    """
    value: Any
    if name == "atomic_write_json":
        from agentkit.backend.boundary.filesystem.atomic import atomic_write_json

        value = atomic_write_json
    elif name in {
        "AK3_OWNER_POLICIES",
        "FilesystemContainmentError",
        "FilesystemOwnerPolicies",
        "assert_project_local_file_path",
        "is_filesystem_link",
        "matches_resolved_interpreter_owner",
        "matches_resolved_path_owner",
    }:
        from agentkit.backend.boundary.filesystem.path_identity import (
            AK3_OWNER_POLICIES,
            FilesystemContainmentError,
            FilesystemOwnerPolicies,
            assert_project_local_file_path,
            is_filesystem_link,
            matches_resolved_interpreter_owner,
            matches_resolved_path_owner,
        )

        value = {
            "AK3_OWNER_POLICIES": AK3_OWNER_POLICIES,
            "FilesystemContainmentError": FilesystemContainmentError,
            "FilesystemOwnerPolicies": FilesystemOwnerPolicies,
            "assert_project_local_file_path": assert_project_local_file_path,
            "is_filesystem_link": is_filesystem_link,
            "matches_resolved_interpreter_owner": matches_resolved_interpreter_owner,
            "matches_resolved_path_owner": matches_resolved_path_owner,
        }[name]
    elif name in {"load_json_object", "read_projection_json_object"}:
        from agentkit.backend.boundary.filesystem.read import (
            load_json_object,
            read_projection_json_object,
        )

        value = {
            "load_json_object": load_json_object,
            "read_projection_json_object": read_projection_json_object,
        }[name]
    else:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    globals()[name] = value
    return value

__all__ = [
    "AK3_OWNER_POLICIES",
    "FilesystemContainmentError",
    "FilesystemOwnerPolicies",
    "atomic_write_json",
    "assert_project_local_file_path",
    "is_filesystem_link",
    "load_json_object",
    "matches_resolved_interpreter_owner",
    "matches_resolved_path_owner",
    "read_projection_json_object",
]
