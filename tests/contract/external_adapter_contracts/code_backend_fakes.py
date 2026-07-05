"""Non-GitHub ``CodeBackendPort`` test-double (AG3-146 AC5 substitutability proof).

:class:`FakeAzureDevOpsCodeBackendAdapter` is a REAL ``CodeBackendPort``
implementation for a fictitious Azure-DevOps-shaped provider -- not a mock of
productive core logic (project MOCKS/STUBS rule: this is the permitted
"real port implementation for a contract suite" exception). It binds a
``project``/``repository`` coordinate (a shape distinct from GitHub's
``owner``/``repo``, demonstrating that the port itself carries no
GitHub-specific semantics) and genuinely performs ``git ls-remote`` reads via
the SAME provider-neutral
:mod:`agentkit.backend.code_backend.git_protocol` module the GitHub adapter
uses -- proving ``ref_read`` is truly provider-neutral (SOLL-184). Its
``repo_probe``/``capability_supported`` never depend on a provider CLI at
all, in deliberate contrast to GitHub's ``gh``-dependent ``repo_probe`` --
a genuine provider-capability divergence the contract suite exercises.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field

from agentkit.backend.code_backend.git_protocol import GitLsRemoteReader
from agentkit.backend.code_backend.provider_port import (
    CodeBackendCapability,
    CompareEvidenceResult,
    RefReadResult,
    RepoProbeResult,
)

__all__ = ["FakeAzureDevOpsCodeBackendAdapter"]

#: Per-invocation timeout for this fake's own ``git ls-remote`` reachability probe.
_PROBE_TIMEOUT_SECONDS = 15


@dataclass(frozen=True)
class FakeAzureDevOpsCodeBackendAdapter:
    """Real, non-GitHub ``CodeBackendPort`` implementation for contract tests.

    Attributes:
        project: Azure-DevOps-shaped project coordinate (opaque outside this
            adapter -- a distinct shape from GitHub's owner/repo).
        repository: Azure-DevOps-shaped repository coordinate.
        remote_url: The git remote used for ``ls-remote`` reads (a local
            bare-repo fixture path in tests).
        ref_reader: The SAME provider-neutral git-protocol reader the GitHub
            adapter uses -- ``ref_read`` genuinely needs no provider mechanic.
    """

    project: str
    repository: str
    remote_url: str
    ref_reader: GitLsRemoteReader = field(default_factory=GitLsRemoteReader)

    def repo_probe(self) -> RepoProbeResult:
        """Probe reachability via a genuine, ref-agnostic ``git ls-remote`` call.

        Deliberately does NOT ask for a specific ref (unlike ``ref_read``): a
        bare remote's symbolic ``HEAD`` may not point at any existing branch
        yet, so "no ref matched" would be a false negative for plain
        reachability. Listing the remote's refs at all -- regardless of how
        many -- is the honest, provider-CLI-free reachability signal.
        """
        try:
            completed = subprocess.run(  # noqa: S603
                ["git", "ls-remote", self.remote_url],  # noqa: S607
                capture_output=True,
                text=True,
                timeout=_PROBE_TIMEOUT_SECONDS,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return RepoProbeResult(
                reachable=False, detail=f"git ls-remote failed to execute: {exc}"
            )
        if completed.returncode != 0:
            stderr = (completed.stderr or "").strip()
            return RepoProbeResult(
                reachable=False,
                detail=f"git ls-remote {self.remote_url} failed: {stderr or 'unreachable'}",
            )
        return RepoProbeResult(
            reachable=True, detail=f"remote {self.remote_url} is reachable."
        )

    def ref_read(self, ref: str) -> RefReadResult:
        """Resolve ``ref``'s head SHA via the shared ``git ls-remote`` reader."""
        return self.ref_reader.read_head_sha(self.remote_url, ref)

    def read_compare_evidence(
        self, base_ref: str, head_ref: str
    ) -> CompareEvidenceResult:
        """Declared-only surface; this fictitious provider never backs it."""
        return CompareEvidenceResult(
            base_ref=base_ref,
            head_ref=head_ref,
            available=False,
            detail="compare-evidence not backed by this test-double adapter.",
        )

    def capability_supported(self, capability: CodeBackendCapability) -> bool:
        """``repo_probe``/``ref_read`` are wired; the rest are declared-only."""
        return capability in (
            CodeBackendCapability.REPO_PROBE,
            CodeBackendCapability.REF_READ,
        )
