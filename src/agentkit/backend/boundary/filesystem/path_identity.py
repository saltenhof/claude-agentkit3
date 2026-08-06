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


def _contains_link_component(
    raw_path: str,
    *,
    allow_terminal_symlink: bool = False,
) -> bool:
    """Return whether a supplied path spelling traverses a forbidden link."""
    path = Path(raw_path)
    current = Path(path.anchor)
    parts = path.parts[1:] if path.anchor else path.parts
    meaningful_parts = tuple(part for part in parts if part not in {"", "."})
    for index, part in enumerate(meaningful_parts):
        current /= part
        if is_filesystem_link(current):
            is_terminal = index == len(meaningful_parts) - 1
            if (
                allow_terminal_symlink
                and os.name != "nt"
                and is_terminal
                and current.is_symlink()
                and not os.path.isjunction(current)
            ):
                continue
            return True
    return False


def matches_resolved_path_owner(
    candidate: object,
    resolved_owner_path: str | None,
    *,
    allow_descendants: bool = False,
    allow_terminal_symlink: bool = False,
) -> bool:
    """Return whether an absolute path is owned by a resolved path.

    Both spellings are compared after the current platform's path and case
    normalisation. Symbolic links and Windows junctions anywhere in either
    spelling are rejected before ``..`` is collapsed, including ancestors that
    lexical normalisation would otherwise erase. The narrow
    ``allow_terminal_symlink`` mode exists for the interpreter path of a POSIX
    virtual environment: that executable is deliberately a terminal symlink,
    while the venv remains the runtime owner. Even in that mode, symlink
    ancestors and every Windows junction remain forbidden. The central resolver
    remains responsible for proving that its returned owner exists and has the
    required file or directory type.
    """
    if (
        not isinstance(candidate, str)
        or not candidate.strip()
        or not resolved_owner_path
        or (allow_terminal_symlink and allow_descendants)
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
        if _contains_link_component(
            candidate,
            allow_terminal_symlink=allow_terminal_symlink,
        ) or _contains_link_component(
            resolved_owner_path,
            allow_terminal_symlink=allow_terminal_symlink,
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


def matches_resolved_interpreter_owner(
    candidate: object,
    resolved_owner_path: str | None,
) -> bool:
    """Match the exact central interpreter, including a POSIX venv symlink.

    This deliberately does not expose descendant matching. The only relaxed
    component is the terminal interpreter symlink created by a standard POSIX
    virtual environment; linked ancestors and junctions still fail closed.
    """
    return matches_resolved_path_owner(
        candidate,
        resolved_owner_path,
        allow_terminal_symlink=True,
    )


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
    "matches_resolved_interpreter_owner",
    "matches_resolved_path_owner",
]
