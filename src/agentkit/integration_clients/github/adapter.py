"""GitHub implementation of the AG3-146 code-backend port (FK-12 §12.1, blood R).

Binds a single ``owner/repo`` GitHub coordinate -- opaque to
:class:`agentkit.backend.code_backend.provider_port.CodeBackendPort` itself
(§12.1 provider-neutrality: the port carries no owner/repo semantics) -- and
thinly adapts it onto two mechanics:

* a ``gh`` CLI subprocess call for ``repo_probe`` -- the ONLY place under
  ``src/agentkit`` a ``gh`` subprocess may run (AG3-146 AC3/AC6);
* :class:`agentkit.backend.code_backend.git_protocol.GitLsRemoteReader` for
  ``ref_read`` -- the provider-neutral ``git ls-remote`` network-protocol read
  that never needs ``gh`` (AG3-146 AC4).

GitHub is the reference provider (FK-12 §12.1.1); an Azure DevOps adapter
would bind a project/repository coordinate instead and implement the same
:class:`agentkit.backend.code_backend.provider_port.CodeBackendPort` Protocol
-- see the capability matrix documented in
:mod:`agentkit.backend.code_backend.provider_port`. The capability model and
decision logic (which capability is minimal/declared/enforced) live in the
backend ``code_backend`` BC; only the ``gh``/``git`` mechanics live here
(thin adapter, CLAUDE.md architecture rule).
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field

from agentkit.backend.code_backend.git_protocol import GitLsRemoteReader, RefReader
from agentkit.backend.code_backend.provider_port import (
    CodeBackendCapability,
    CompareEvidenceResult,
    RefProtectionResult,
    RefReadResult,
    RepoProbeResult,
    StoryRefWriteCredentialResult,
)
from agentkit.integration_clients.github.service_identity import (
    EnvVarServiceIdentitySource,
    GhRulesetRefProtectionAdministrator,
    RefProtectionAdministrator,
    ServiceIdentitySource,
)

__all__ = ["GitHubCodeBackendAdapter"]

#: Default per-invocation timeout for the ``gh repo view`` subprocess.
_DEFAULT_GH_TIMEOUT_SECONDS = 30


def _gh_available() -> bool:
    """Whether the ``gh`` CLI binary is discoverable on ``PATH``."""
    return shutil.which("gh") is not None


@dataclass(frozen=True)
class GitHubCodeBackendAdapter:
    """GitHub :class:`CodeBackendPort` implementation (FK-12 §12.1, blood R).

    Attributes:
        owner: GitHub owner/organisation login. Adapter-internal binding
            detail; never surfaces on ``CodeBackendPort`` (§12.1).
        repo: GitHub repository name. Adapter-internal binding detail.
        ref_reader: The provider-neutral ``git ls-remote`` reader
            (:mod:`agentkit.backend.code_backend.git_protocol`, blood T).
        gh_timeout_seconds: Per-invocation timeout for the ``gh`` subprocess.
        remote_url_override: Test seam -- overrides the derived
            ``https://github.com/{owner}/{repo}.git`` remote URL used by
            ``ref_read`` so a contract/unit test can point at a local
            bare-repo fixture instead of a live GitHub remote (AG3-146
            AC2/AC5). ``None`` (the default) in production.
    """

    owner: str
    repo: str
    ref_reader: RefReader = field(default_factory=GitLsRemoteReader)
    gh_timeout_seconds: int = _DEFAULT_GH_TIMEOUT_SECONDS
    remote_url_override: str | None = None
    #: The backend-managed service identity used for ``story/*`` writes (AC8).
    #: The personal developer token (``gh auth token`` / credential file) is
    #: never used here -- it is a distinct credential class (FK-15 §15.5.1).
    service_identity_source: ServiceIdentitySource = field(
        default_factory=EnvVarServiceIdentitySource
    )
    #: Injectable ref-protection administration seam (AG3-147 AC7/AC9). ``None``
    #: builds the default ``gh api`` ruleset administrator bound to owner/repo;
    #: a unit test injects a scripted double (the isolated-unit-test seam).
    ref_protection_administrator: RefProtectionAdministrator | None = None

    def repo_probe(self) -> RepoProbeResult:
        """Probe repo existence/reachability via ``gh repo view``.

        Fail-closed and never raises: a missing ``gh`` binary, an
        unauthenticated CLI or a missing repo all yield
        ``RepoProbeResult(reachable=False, ...)`` with a named reason.
        """
        if not _gh_available():
            return RepoProbeResult(
                reachable=False,
                detail=(
                    "GitHub CLI 'gh' is not installed (FK-50 §50.6); "
                    "repo_probe capability unavailable."
                ),
            )
        try:
            # Fixed argv, no shell -- the only gh subprocess call this capability needs.
            completed = subprocess.run(  # noqa: S603
                ["gh", "repo", "view", f"{self.owner}/{self.repo}", "--json", "name"],  # noqa: S607
                capture_output=True,
                text=True,
                timeout=self.gh_timeout_seconds,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return RepoProbeResult(
                reachable=False, detail=f"gh repo view failed to execute: {exc}"
            )
        if completed.returncode != 0:
            stderr = (completed.stderr or "").strip()
            return RepoProbeResult(
                reachable=False,
                detail=(
                    f"gh repo view {self.owner}/{self.repo} failed: "
                    f"{stderr or 'non-zero exit'}"
                ),
            )
        return RepoProbeResult(
            reachable=True,
            detail=f"GitHub repo {self.owner}/{self.repo} exists and is reachable.",
        )

    def ref_read(self, ref: str) -> RefReadResult:
        """Resolve ``ref``'s head SHA via provider-neutral ``git ls-remote``."""
        return self.ref_reader.read_head_sha(self._remote_url(), ref)

    def read_compare_evidence(
        self, base_ref: str, head_ref: str
    ) -> CompareEvidenceResult:
        """Declared compare-/change-evidence surface (not yet backed, AG3-147+).

        GitHub mechanically supports this via the Compare API, but AG3-146
        stores only the ``ls-remote`` read surface (In-Scope #2); no
        productive consumer of this capability exists yet. Returns
        ``available=False`` -- an honest "not yet backed" signal, never a
        fabricated compare result.
        """
        return CompareEvidenceResult(
            base_ref=base_ref,
            head_ref=head_ref,
            available=False,
            detail=(
                "compare-evidence capability is declared but not yet backed by "
                "a GitHub compare-endpoint binding (AG3-146 declares the "
                "surface; productive consumers land in AG3-147+)."
            ),
        )

    def resolve_story_ref_write_credential(self) -> StoryRefWriteCredentialResult:
        """Resolve the backend-managed service credential for ``story/*`` (AC8).

        Delegates to the service-identity source; NEVER the personal developer
        token (``gh auth token`` / credential file). The returned
        ``credential_ref`` is an opaque handle, never the secret value.
        """
        return self.service_identity_source.resolve_write_credential()

    def administer_ref_protection(self, ref_pattern: str) -> RefProtectionResult:
        """Administer ``story/*`` ref protection via the administrator seam (AC7)."""
        return self._ref_protection_administrator().administer(ref_pattern)

    def capability_supported(self, capability: CodeBackendCapability) -> bool:
        """Whether *capability* is actually wired and usable on this adapter.

        ``repo_probe`` depends on ``gh`` being installed (AG3-146 AC4:
        missing ``gh`` is a named, deterministic capability finding, never a
        crash). ``ref_read`` never needs ``gh`` (SOLL-184). The declared
        ``compare_evidence`` capability is not yet backed by this adapter.
        ``ref_protection_administration`` is backed only when the administrator
        seam reports real work is possible (``gh`` + a backend service
        identity); otherwise it is ``False`` and the caller raises the FK-12
        §12.1.3 degradation WARNING (never a fabricated ``True``, ZERO DEBT).
        """
        if capability is CodeBackendCapability.REPO_PROBE:
            return _gh_available()
        if capability is CodeBackendCapability.REF_PROTECTION_ADMINISTRATION:
            return self._ref_protection_administrator().is_available()
        return capability is CodeBackendCapability.REF_READ

    def _ref_protection_administrator(self) -> RefProtectionAdministrator:
        """Return the injected administrator, or the default ``gh`` ruleset one."""
        if self.ref_protection_administrator is not None:
            return self.ref_protection_administrator
        return GhRulesetRefProtectionAdministrator(
            owner=self.owner,
            repo=self.repo,
            service_source=self.service_identity_source,
            gh_timeout_seconds=self.gh_timeout_seconds,
        )

    def _remote_url(self) -> str:
        """Resolve the git remote URL used by ``ref_read``."""
        if self.remote_url_override is not None:
            return self.remote_url_override
        return f"https://github.com/{self.owner}/{self.repo}.git"
