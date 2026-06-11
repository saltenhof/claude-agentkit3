"""Deterministic evidence-fingerprint computation (FK-27 §27.2.1).

The ``evidence_fingerprint`` is a SHA-256 hex digest over the canonicalised
content of the story branch's code delta against ``origin/main``. It is the
*content* integrity signal of an atomic QA cycle (FK-27 §27.2.1, decision
2026-04-08 Element 19): the same code-state ALWAYS yields the same fingerprint,
a changed code-state yields a different one. ``evidence_epoch`` (a timestamp)
is a separate field and is NOT computed here.

Canonicalisation rules (deterministic by construction):

* The ``git diff origin/main..HEAD --stat`` output is rendered with a PINNED
  git config (``-c color.ui=false -c core.quotepath=false``), ``--no-color`` and
  a FIXED stat width (``--stat=9999,9999``) so the summary is independent of
  terminal width, locale colouring or unicode path quoting; it is then
  normalised to LF line endings with trailing whitespace stripped.
* The change-set is the UNION of (a) the committed delta vs ``origin/main``,
  (b) the working-tree delta vs ``HEAD`` (uncommitted modifications/deletions)
  and (c) untracked, non-ignored files. This captures the FULL current code
  state, not just what is committed (E8). Each present path contributes a
  ``"<posix_path>\\n<sha256-of-bytes>"`` line; a path in the change-set with no
  readable bytes (a working-tree DELETION) contributes a fixed tombstone line
  ``"<posix_path>\\n<deleted>"`` so the deletion reliably changes the
  fingerprint (fail-closed; a deletion is never silently ignored). The lines
  are sorted by path so the ordering is independent of the git/OS enumeration
  order.
* ``handover.json`` (relative to the story dir), when present, contributes its
  content hash under the fixed key ``handover.json``.

All segments are joined with ``\\n`` under a fixed section order and hashed once.
Subprocess failures (no git, detached tree, missing ref) FAIL CLOSED: they
raise :class:`FingerprintComputationError` rather than silently degrading to a
weaker signal (NO ERROR BYPASSING).

Source:
  - FK-27 §27.2.1 -- evidence_fingerprint (SHA-256, content integrity)
  - AG3-041 §2.1.2 -- compute_evidence_fingerprint
"""

from __future__ import annotations

import hashlib
import subprocess
from typing import TYPE_CHECKING

from agentkit.core_types import HANDOVER_FILE
from agentkit.verify_system.errors import VerifySystemError

if TYPE_CHECKING:
    from pathlib import Path

#: Default git revision range for the story-branch delta (FK-27 §27.2.1).
DEFAULT_DIFF_BASE = "origin/main"

#: Pinned git config flags for deterministic, locale-/terminal-independent
#: output (E8): no ANSI colour, no octal-quoting of non-ASCII paths. Applied to
#: EVERY git invocation so the captured strings never drift with the
#: environment.
_PINNED_GIT_CONFIG = ("-c", "color.ui=false", "-c", "core.quotepath=false")

#: Fixed ``--stat`` width so the diffstat rendering never depends on terminal
#: width (``COLUMNS``/tty). Large enough that no path/graph column is truncated.
_STAT_WIDTH = "--stat=9999,9999"

#: Fixed section markers keep the hashed document stable across refactors.
_SECTION_DIFFSTAT = "## diffstat"
_SECTION_FILES = "## files"
_SECTION_HANDOVER = "## handover"

#: Story-relative handover artefact contributing to the fingerprint.
_HANDOVER_FILENAME = HANDOVER_FILE

#: Fixed marker emitted in place of a content hash for a path that is in the
#: change-set but has no readable bytes (a working-tree deletion). Using a
#: distinct, fixed token — rather than dropping the line — makes a deletion
#: change the fingerprint deterministically (fail-closed toward closure). The
#: token cannot collide with a real SHA-256 digest (it is not 64 hex chars).
_DELETION_TOMBSTONE = "<deleted>"


class FingerprintComputationError(VerifySystemError):
    """Raised when the evidence fingerprint cannot be computed (fail-closed)."""


def compute_evidence_fingerprint(
    story_dir: Path,
    *,
    diff_base: str = DEFAULT_DIFF_BASE,
) -> str:
    """Compute the deterministic SHA-256 evidence fingerprint for a story.

    The fingerprint covers the story branch's code delta against
    ``diff_base`` plus the optional ``handover.json``. It is stable: the same
    code-state yields the same digest on repeated invocation (FK-27 §27.2.1).

    Args:
        story_dir: Story working directory. Used both as the git working
            directory and as the root for resolving ``handover.json``.
        diff_base: Git revision the delta is taken against. Defaults to
            ``origin/main`` (the story-branch base, FK-27 §27.2.1).

    Returns:
        A 64-char lowercase hex SHA-256 digest.

    Raises:
        FingerprintComputationError: If git is unavailable or the diff/stat
            cannot be produced (fail-closed; no weak-signal fallback).
    """
    diffstat = _run_git(
        ["diff", f"{diff_base}..HEAD", "--no-color", _STAT_WIDTH], story_dir
    )
    changed_paths = _changed_paths(diff_base, story_dir)

    file_lines: list[str] = []
    for rel_path in sorted(changed_paths):
        content_hash = _hash_file(story_dir / rel_path)
        if content_hash is not None:
            file_lines.append(f"{rel_path}\n{content_hash}")
        else:
            # A path that is in the change-set but has no readable bytes is a
            # working-tree DELETION (or an unreadable entry). It MUST still
            # contribute deterministically: drop a tombstone marker instead of
            # silently omitting the line. Otherwise a `git rm`/working-tree
            # deletion would leave the fingerprint unchanged — old QA evidence
            # would falsely appear valid (fail-open toward closure). The marker
            # is fixed text, so the same deletion always yields the same
            # fingerprint (determinism preserved).
            file_lines.append(f"{rel_path}\n{_DELETION_TOMBSTONE}")

    segments: list[str] = [
        _SECTION_DIFFSTAT,
        _canonical_text(diffstat),
        _SECTION_FILES,
        "\n".join(file_lines),
    ]

    handover = story_dir / _HANDOVER_FILENAME
    handover_hash = _hash_file(handover)
    if handover_hash is not None:
        segments.extend((_SECTION_HANDOVER, f"{_HANDOVER_FILENAME}\n{handover_hash}"))

    document = "\n".join(segments)
    return hashlib.sha256(document.encode("utf-8")).hexdigest()


def _changed_paths(diff_base: str, story_dir: Path) -> tuple[str, ...]:
    """Return the POSIX paths making up the FULL current code state (E8).

    The change-set is the UNION of three enumerations, so the fingerprint
    reflects the actual working tree, not just the committed delta:

    * committed delta vs ``diff_base`` (``diff {base}..HEAD --name-only``),
    * working-tree delta vs ``HEAD`` (``diff HEAD --name-only`` — uncommitted
      modifications and deletions),
    * untracked, non-ignored files (``ls-files --others --exclude-standard``).

    ``--name-only`` enumeration is independent of the ``--stat`` rendering.
    Paths are returned unsorted (the caller sorts); a deleted path stays in the
    set and the caller emits a tombstone line for it (its bytes hash to
    ``None``), so the deletion changes the fingerprint (fail-closed).

    Args:
        diff_base: Git revision the committed delta is taken against.
        story_dir: Story git working directory.

    Returns:
        Tuple of repository-relative POSIX path strings (de-duplicated).
    """
    committed = _run_git(
        ["diff", f"{diff_base}..HEAD", "--name-only"], story_dir
    )
    worktree = _run_git(["diff", "HEAD", "--name-only"], story_dir)
    untracked = _run_git(
        ["ls-files", "--others", "--exclude-standard"], story_dir
    )
    paths: set[str] = set()
    for raw in (committed, worktree, untracked):
        paths.update(line.strip() for line in raw.splitlines() if line.strip())
    return tuple(paths)


def _hash_file(path: Path) -> str | None:
    """Return the SHA-256 hex of a file's bytes, or ``None`` if absent.

    ``None`` signals "no readable bytes" — the caller turns that into a fixed
    deletion tombstone line so the absence still changes the fingerprint
    deterministically (it is NOT silently dropped). Directories and unreadable
    entries are treated as absent.

    Args:
        path: Absolute path to hash.

    Returns:
        64-char lowercase hex digest, or ``None`` when the file does not exist.
    """
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_text(text: str) -> str:
    """Normalise text to LF line endings with stripped trailing whitespace.

    Args:
        text: Raw subprocess output.

    Returns:
        Canonicalised text (LF endings, no trailing blank lines).
    """
    normalised = text.replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(line.rstrip() for line in normalised.split("\n")).strip()


def _run_git(args: list[str], cwd: Path) -> str:
    """Run a read-only git command and return stdout (fail-closed).

    Args:
        args: Git arguments after the ``git`` executable.
        cwd: Working directory for the git invocation.

    Returns:
        Captured stdout (UTF-8 decoded).

    Raises:
        FingerprintComputationError: If git is missing or returns non-zero.
    """
    try:
        # Fixed git argv (no shell, no user-controlled input); S603 reviewed as safe.
        completed = subprocess.run(  # noqa: S603
            ["git", *_PINNED_GIT_CONFIG, *args],
            cwd=cwd,
            capture_output=True,
            check=True,
            text=True,
            encoding="utf-8",
        )
    except FileNotFoundError as exc:
        msg = "git executable not found; cannot compute evidence fingerprint"
        raise FingerprintComputationError(msg) from exc
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.strip()
        msg = f"git {' '.join(args)} failed in {cwd} (exit {exc.returncode}): {detail}"
        raise FingerprintComputationError(msg) from exc
    return completed.stdout


__all__ = [
    "DEFAULT_DIFF_BASE",
    "FingerprintComputationError",
    "compute_evidence_fingerprint",
]
