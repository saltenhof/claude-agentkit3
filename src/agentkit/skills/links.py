"""Platform-aware thin directory-link operations for skill bindings.

Implements the binding mechanism mandated by FK-43 §43.4.1.1 and the invariant
``project_binding_is_link_only`` (formal.skills-and-bundles.invariants):

* **POSIX** — a symbolic link (:func:`os.symlink` via :meth:`Path.symlink_to`).
* **Windows** — a **directory junction** (``_winapi.CreateJunction``). A junction
  needs **no** Developer Mode and **no** ``SeCreateSymbolicLinkPrivilege`` — unlike
  a Windows *symlink*, which requires one of them and is therefore not assumable on
  AK3 target machines. AK3 installs centrally on Windows and binds N projects to one
  central, versioned bundle store via these thin links; a file copy is forbidden on
  every platform.

Junction caveats this module encapsulates (so callers never special-case them):

* A junction is **not** recognised by :func:`os.path.islink`; detection uses
  :func:`os.path.isjunction` (Python 3.12+).
* Removing a junction with :func:`shutil.rmtree` would delete the **central target**.
  :func:`remove_directory_link` therefore uses :func:`os.rmdir` for a junction (which
  detaches the link only) and :meth:`Path.unlink` for a symlink — never a recursive
  delete through the link.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

from agentkit.skills.binding import SkillBindingMode

_IS_WINDOWS = sys.platform == "win32"

#: Windows extended-length path prefix ``os.readlink`` returns for a junction
#: target. Stripped by :func:`read_directory_link_target` so the resolved target
#: compares equal to an ordinary ``Path`` (a digest-keyed variant dir vs. the raw
#: ``bundle_root``) without callers special-casing the prefix.
_WINDOWS_EXTENDED_LENGTH_PREFIX = "\\\\?\\"


def platform_binding_mode() -> SkillBindingMode:
    """Return the binding mode this platform uses (``JUNCTION`` on Windows)."""
    return SkillBindingMode.JUNCTION if _IS_WINDOWS else SkillBindingMode.SYMLINK


def create_directory_link(link_path: Path, target: Path) -> SkillBindingMode:
    """Create a thin directory link ``link_path`` -> ``target``.

    On POSIX a symbolic link is created; on Windows a directory junction. The
    junction stores an absolute target path, so the target is resolved to an
    absolute path before the link is created.

    Args:
        link_path: The link to create (must not already exist).
        target: The central bundle directory the link points to.

    Returns:
        The :class:`SkillBindingMode` actually used.

    Raises:
        OSError: When the underlying OS link call fails.
    """
    if _IS_WINDOWS:
        # ``_winapi`` is a Windows-only stdlib extension. Import it DYNAMICALLY
        # (not a static ``import _winapi``) so a cross-platform mypy/CI run on
        # POSIX — e.g. the Linux Jenkins — never tries to resolve a module (and
        # its ``CreateJunction`` attribute) that does not exist there. The branch
        # is unreachable on POSIX at runtime (``_IS_WINDOWS`` is False), so the
        # dynamic import only ever executes on Windows. Using a static import +
        # ``# type: ignore`` would be WRONG: the ignore is needed on POSIX but
        # flagged unused on Windows (warn_unused_ignores).
        winapi = importlib.import_module("_winapi")
        # CreateJunction(target, junction): a junction stores an ABSOLUTE path.
        winapi.CreateJunction(str(target.resolve()), str(link_path))
        return SkillBindingMode.JUNCTION
    # Codex-r7-r2: resolve the target to an ABSOLUTE path (symmetric to the
    # junction branch). A relative target would be stored relative to the link
    # location and resolve to a broken symlink in the project.
    link_path.symlink_to(target.resolve())
    return SkillBindingMode.SYMLINK


def is_directory_link(path: Path) -> bool:
    """Return ``True`` when *path* is a binding link (symlink OR Windows junction).

    A POSIX symlink is detected by :meth:`Path.is_symlink`; a Windows junction by
    :func:`os.path.isjunction` (which is ``False`` on POSIX for every path).
    """
    return path.is_symlink() or os.path.isjunction(path)


def remove_directory_link(path: Path) -> None:
    """Detach a binding link WITHOUT deleting its target.

    A junction is removed via :func:`os.rmdir` (detaches the reparse point only,
    never recurses into the central target); a symlink via :meth:`Path.unlink`.
    A junction must be checked first because :meth:`Path.is_symlink` is ``False``
    for it.

    Raises:
        OSError: When the link cannot be removed (caller decides how to surface).
    """
    if os.path.isjunction(path):
        os.rmdir(path)
    else:
        path.unlink()


def read_directory_link_target(link_path: Path) -> Path:
    """Resolve the target a binding link points at (AG3-111 §2.1 item 1b).

    A link-introspection helper (NOT a schema/state-format change): it lets
    ``resolve_binding`` / Verify / cleanup derive the materialized-vs-raw binding
    mode from the REAL link target — a digest-keyed variant directory in the AK3
    install store (materialized) versus the systemwide ``bundle_root`` (raw) —
    WITHOUT adding a ``SkillBinding`` field.

    Resolution is platform-aware, symmetric to :func:`create_directory_link`:

    * **POSIX symlink** — :func:`os.readlink` returns the stored absolute target.
    * **Windows junction** — :func:`os.readlink` (Python 3.8+) reads the
      reparse-point target; it is returned with the extended-length ``\\\\?\\``
      prefix, which this function strips so the result compares equal to an
      ordinary absolute :class:`~pathlib.Path`.

    Args:
        link_path: The binding-point link to introspect (must be a symlink or a
            Windows directory junction).

    Returns:
        The absolute :class:`~pathlib.Path` the link points at.

    Raises:
        OSError: When *link_path* is not a link or its target cannot be read.
    """
    raw_target = os.readlink(link_path)
    if _IS_WINDOWS and raw_target.startswith(_WINDOWS_EXTENDED_LENGTH_PREFIX):
        raw_target = raw_target[len(_WINDOWS_EXTENDED_LENGTH_PREFIX):]
    return Path(raw_target)
