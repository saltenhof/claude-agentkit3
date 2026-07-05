"""GitHub repository existence probe for installer CP 2 (FK-50 §50.3 CP 2).

CP 2 checks that the target GitHub repo exists and ``gh`` is authenticated.
AG3-146 (AC3): the live check is delegated to the code-backend port's
``repo_probe`` capability (:mod:`agentkit.backend.code_backend.provider_port`,
productively bound to the GitHub adapter via
:func:`agentkit.backend.bootstrap.composition_root.build_github_code_backend_port`)
so no ``gh`` subprocess runs here -- ``gh`` subprocess calls live exclusively
under ``integration_clients/github/`` (AC3/AC6 conformance grep). The probe
itself is still injected as a :class:`RepoExistenceProbe`: the productive CLI
wires :class:`GhCliRepoExistenceProbe`; tests inject a deterministic double;
an offline install leaves it ``None`` (CP 2 then validates the coordinate
FORMAT only and never fabricates a live verification).
"""

from __future__ import annotations

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
    """Productive repo-existence probe over the AG3-146 code-backend port.

    Fail-closed: a missing ``gh`` binary, an unauthenticated CLI or a missing
    repo all yield ``exists=False`` (CP 2 maps that to FAILED). Never raises —
    the boundary error becomes a clean negative result. The ``gh`` mechanics
    themselves live exclusively in
    :class:`agentkit.integration_clients.github.adapter.GitHubCodeBackendAdapter`
    (AG3-146 AC3); this probe only maps the port's
    :class:`agentkit.backend.code_backend.provider_port.RepoProbeResult` onto
    the installer's own CP 2 contract type above.

    Attributes:
        timeout_seconds: Per-invocation timeout for the GitHub adapter's
            ``gh`` subprocess.
    """

    timeout_seconds: int = 30

    def __call__(self, owner: str, repo: str) -> RepoProbeResult:
        """Probe ``owner/repo`` via the code-backend port's ``repo_probe``."""
        from agentkit.backend.bootstrap.composition_root import (
            build_github_code_backend_port,
        )

        port = build_github_code_backend_port(
            owner, repo, gh_timeout_seconds=self.timeout_seconds
        )
        outcome = port.repo_probe()
        return RepoProbeResult(exists=outcome.reachable, detail=outcome.detail)


__all__ = [
    "GhCliRepoExistenceProbe",
    "RepoExistenceProbe",
    "RepoProbeResult",
]
