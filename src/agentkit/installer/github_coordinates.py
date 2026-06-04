"""Derive GitHub owner/repo coordinates for the installer (AG3-039 R5).

FK-50 §50.3 CP 7 records ``github_owner``/``github_repo`` as MANDATORY
coordinates and CP 7 fails closed when they are absent. The ``agentkit install``
CLI therefore needs the coordinates before it can register the project.

The operator may pass ``--github-owner``/``--github-repo`` explicitly (these take
precedence). When they are omitted, this module derives them from the target
project's ``origin`` git remote — but only when that remote can be parsed
UNAMBIGUOUSLY into a GitHub owner/repo. Anything unparseable yields ``None`` so
the caller fails closed (it never fabricates a coordinate; ZERO DEBT /
FAIL-CLOSED).
"""

from __future__ import annotations

import re
import subprocess
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

# A GitHub remote URL in any of the canonical shapes that ``git remote`` emits:
#   https://github.com/<owner>/<repo>(.git)
#   https://user@github.com/<owner>/<repo>(.git)
#   git@github.com:<owner>/<repo>(.git)
#   ssh://git@github.com/<owner>/<repo>(.git)
# Only ``github.com`` hosts are accepted (no GH-Enterprise guessing — fail-closed
# rather than mis-attributing a non-github remote to a github owner/repo).
#
# The owner/repo segments are captured permissively here (``[^/]+``); their
# CONTENT is validated separately by :func:`validate_github_coordinate`. Coupling
# the structural URL match to the lenient segment grab keeps the regex anchored
# and free of nested quantifiers (no ReDoS); the strict name rules live in a
# single, reusable predicate so the CLI flags and the derived remote share one
# validation truth (FAIL-CLOSED — anything that is not a well-formed GitHub
# owner/repo is rejected, never guessed).
_GITHUB_REMOTE_RE = re.compile(
    r"""
    ^
    (?:
        https://(?:[^@/]+@)?github\.com/   # https[ + userinfo ]
      | (?:ssh://)?git@github\.com[:/]      # scp-style or ssh:// git@host
    )
    (?P<owner>[^/]+)
    /
    (?P<repo>[^/]+?)
    (?:\.git)?
    /?
    $
    """,
    re.VERBOSE,
)

# GitHub username/organisation rules (FAIL-CLOSED, AG3-039 R6 E-b):
#   * 1-39 characters
#   * alphanumeric or single hyphens
#   * may NOT start or end with a hyphen
#   * may NOT contain consecutive hyphens
# Single-pass (one optional repeated group of ``-?alnum``) — no nested
# quantifiers, so no catastrophic backtracking / ReDoS. Matched with
# :func:`re.fullmatch` (NOT ``^…$`` + ``.match``): in Python ``$`` also matches
# just before a trailing ``\n``, so an owner like ``"acme\n"`` would slip
# through a ``.match`` check. ``fullmatch`` anchors the WHOLE string, rejecting
# any trailing newline / control char (FAIL-CLOSED).
_GITHUB_OWNER_RE = re.compile(r"[A-Za-z0-9](?:-?[A-Za-z0-9]){0,38}")

# GitHub repository name rules (FAIL-CLOSED, AG3-039 R6 E-b):
#   * 1-100 characters drawn from ``[A-Za-z0-9._-]``
#   * may NOT be exactly ``.`` or ``..`` (path-traversal / current-dir tokens)
#   * may NOT start with a dot (no hidden / ``.git``-style bare names)
# The character class is anchored with a bounded repetition — no nested
# quantifiers, so no ReDoS. The ``.``/``..``/leading-dot checks are applied
# separately because they are not expressible as a single safe character class.
# Matched with :func:`re.fullmatch` (NOT ``^…$`` + ``.match``) so a trailing
# ``\n`` (which ``$`` would tolerate) or any embedded control char is rejected.
_GITHUB_REPO_RE = re.compile(r"[A-Za-z0-9_-][A-Za-z0-9._-]{0,99}")


def validate_github_coordinate(owner: str, repo: str) -> tuple[str, str] | None:
    """Validate a ``(owner, repo)`` pair against GitHub's naming rules.

    This is the SINGLE validation truth (SSOT) shared by every entry point that
    can persist GitHub coordinates: the URL parser (derived coordinates), the
    ``agentkit install`` CLI flags, the installer CP 7 port
    (``_run_cp7_state_backend_registration``) and the ``ProjectRegistration``
    model validator. It is strictly fail-closed: any value that is not a
    well-formed GitHub owner/repo — whitespace, path-traversal tokens
    (``.``/``..``), embedded spaces or slashes, a leading/trailing hyphen,
    consecutive hyphens, an over-long segment, an empty string, or ANY embedded
    control character / trailing newline (rejected via :func:`re.fullmatch`) —
    yields ``None`` rather than a guessed coordinate (ZERO DEBT, FAIL-CLOSED).

    Args:
        owner: Candidate GitHub owner/organisation login.
        repo: Candidate GitHub repository name (without the ``.git`` suffix).

    Returns:
        The validated ``(owner, repo)`` pair, or ``None`` when either segment
        violates the GitHub naming rules.
    """
    if _GITHUB_OWNER_RE.fullmatch(owner) is None:
        return None
    if repo in {".", ".."}:
        return None
    if _GITHUB_REPO_RE.fullmatch(repo) is None:
        return None
    return owner, repo


def parse_github_remote_url(url: str) -> tuple[str, str] | None:
    """Parse a git remote URL into ``(owner, repo)`` for github.com hosts.

    Args:
        url: A git remote URL as emitted by ``git remote get-url``.

    Returns:
        The ``(owner, repo)`` pair when *url* is an unambiguous github.com
        remote with a well-formed owner/repo, otherwise ``None`` (fail-closed:
        a non-github / malformed / path-traversal URL yields no coordinates
        rather than a guessed one).
    """
    match = _GITHUB_REMOTE_RE.match(url.strip())
    if match is None:
        return None
    owner = match.group("owner").strip()
    repo = match.group("repo").strip()
    return validate_github_coordinate(owner, repo)


def derive_github_coordinates(project_root: Path) -> tuple[str, str] | None:
    """Derive ``(owner, repo)`` from the target project's ``origin`` remote.

    Runs ``git -C <project_root> remote get-url origin`` and parses the result
    via :func:`parse_github_remote_url`. Every failure mode — git not installed,
    no repository, no ``origin`` remote, an unparseable / non-github URL — is
    treated identically: it returns ``None`` so the caller fails closed and
    demands the explicit flags. It NEVER raises and NEVER fabricates a value.

    Args:
        project_root: The target project root (the git working tree).

    Returns:
        The derived ``(owner, repo)`` pair, or ``None`` when it cannot be
        derived unambiguously.
    """
    try:
        result = subprocess.run(  # noqa: S603 — fixed argv, no shell
            ["git", "-C", str(project_root), "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0:
        return None
    url = result.stdout.strip()
    if not url:
        return None
    return parse_github_remote_url(url)
