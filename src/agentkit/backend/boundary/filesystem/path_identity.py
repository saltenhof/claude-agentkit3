"""Fail-closed filesystem identity used by destructive ownership decisions."""

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath, PureWindowsPath


class FilesystemContainmentError(ValueError):
    """Raised when a managed filesystem path can escape its declared root."""


def is_filesystem_link(path: Path) -> bool:
    """Return whether ``path`` is a symbolic link or Windows junction.

    ``Path.is_symlink`` deliberately does not recognise Windows junctions.
    Both are mutable filesystem indirections and therefore carry the same
    meaning for ownership and deletion decisions.
    """
    return path.is_symlink() or os.path.isjunction(path)


def _contains_link_component(raw_path: str) -> bool:
    """Return whether a supplied path spelling traverses a filesystem link."""
    path = Path(raw_path)
    current = Path(path.anchor)
    parts = path.parts[1:] if path.anchor else path.parts
    for part in parts:
        if part in {"", "."}:
            continue
        current /= part
        if is_filesystem_link(current):
            return True
    return False


def matches_resolved_path_owner(
    candidate: object,
    resolved_owner_path: str | None,
    *,
    allow_descendants: bool = False,
) -> bool:
    """Return whether an absolute path is owned by a resolved path.

    Both spellings are compared after the current platform's path and case
    normalisation. Symbolic links and Windows junctions anywhere in either
    spelling are rejected before ``..`` is collapsed, including ancestors that
    lexical normalisation would otherwise erase. The central resolver remains
    responsible for proving that its returned owner exists and has the required
    file or directory type.
    """
    if (
        not isinstance(candidate, str)
        or not candidate.strip()
        or not resolved_owner_path
    ):
        return False
    candidate_is_absolute = PurePosixPath(candidate).is_absolute() or PureWindowsPath(
        candidate
    ).is_absolute()
    owner_is_absolute = PurePosixPath(
        resolved_owner_path
    ).is_absolute() or PureWindowsPath(resolved_owner_path).is_absolute()
    if not candidate_is_absolute or not owner_is_absolute:
        return False
    try:
        if _contains_link_component(candidate) or _contains_link_component(
            resolved_owner_path
        ):
            return False
        candidate_identity = os.path.normcase(
            os.path.normpath(os.path.abspath(candidate))
        )
        owner_identity = os.path.normcase(
            os.path.normpath(os.path.abspath(resolved_owner_path))
        )
        if candidate_identity == owner_identity:
            return True
        return allow_descendants and os.path.commonpath(
            (candidate_identity, owner_identity)
        ) == owner_identity
    except (OSError, RuntimeError, ValueError):
        return False


def assert_project_local_file_path(project_root: Path, relative_path: Path) -> Path:
    """Return a project-local file path after rejecting mutable indirections."""
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise FilesystemContainmentError(
            f"managed path must be project-relative without '..': {relative_path}"
        )
    candidate = project_root / relative_path
    try:
        if _contains_link_component(str(candidate)):
            raise FilesystemContainmentError(
                f"{candidate} traverses a symbolic link or junction"
            )
        root = project_root.resolve()
        resolved_parent = candidate.parent.resolve()
    except FilesystemContainmentError:
        raise
    except (OSError, RuntimeError) as exc:
        raise FilesystemContainmentError(
            f"cannot prove containment of {candidate}: {exc}"
        ) from exc
    if not resolved_parent.is_relative_to(root):
        raise FilesystemContainmentError(
            f"{resolved_parent} resolves outside project root {root}"
        )
    return candidate


__all__ = [
    "FilesystemContainmentError",
    "assert_project_local_file_path",
    "is_filesystem_link",
    "matches_resolved_path_owner",
]
