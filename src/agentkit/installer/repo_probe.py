"""GitHub repository existence probe for installer CP 2 (FK-50 §50.3 CP 2).

CP 2 checks that the target GitHub repo exists and ``gh`` is authenticated via
``gh repo view {owner}/{repo} --json name``. The live ``gh`` invocation is an
operational boundary, so it is injected as a :class:`RepoExistenceProbe`: the
productive CLI wires :class:`GhCliRepoExistenceProbe`; tests inject a
deterministic double; an offline install leaves it ``None`` (CP 2 then validates
the coordinate FORMAT only and never fabricates a live verification).
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class RepoProbeResult:
    """Outcome of a GitHub-repo existence probe.

    Attributes:
        exists: Whether the repo was confirmed to exist and ``gh`` is
            authenticated.
        detail: Human-readable evidence (the failing reason when ``exists`` is
            ``False``).
    """

    exists: bool
    detail: str


class RepoExistenceProbe(Protocol):
    """Read-only probe verifying a GitHub repo exists (FK-50 §50.3 CP 2)."""

    def __call__(self, owner: str, repo: str) -> RepoProbeResult:
        """Return whether ``owner/repo`` exists and ``gh`` is authenticated."""


@dataclass(frozen=True)
class GhCliRepoExistenceProbe:
    """Productive ``gh repo view`` probe (FK-50 §50.3 CP 2 / §50.6).

    Fail-closed: a missing ``gh`` binary, an unauthenticated CLI or a missing
    repo all yield ``exists=False`` (CP 2 maps that to FAILED). Never raises —
    the boundary error becomes a clean negative result.

    Attributes:
        timeout_seconds: Per-invocation timeout for the ``gh`` subprocess.
    """

    timeout_seconds: int = 30

    def __call__(self, owner: str, repo: str) -> RepoProbeResult:
        """Run ``gh repo view {owner}/{repo} --json name``."""
        if shutil.which("gh") is None:
            return RepoProbeResult(
                exists=False,
                detail="GitHub CLI 'gh' is not installed (FK-50 §50.6).",
            )
        try:
            completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
                ["gh", "repo", "view", f"{owner}/{repo}", "--json", "name"],
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return RepoProbeResult(
                exists=False, detail=f"gh repo view failed to execute: {exc}"
            )
        if completed.returncode != 0:
            stderr = (completed.stderr or "").strip()
            return RepoProbeResult(
                exists=False,
                detail=(
                    f"gh repo view {owner}/{repo} failed: "
                    f"{stderr or 'non-zero exit'}"
                ),
            )
        return RepoProbeResult(
            exists=True, detail=f"GitHub repo {owner}/{repo} exists and is reachable."
        )


__all__ = [
    "GhCliRepoExistenceProbe",
    "RepoExistenceProbe",
    "RepoProbeResult",
]
