"""Provider-neutral ``git ls-remote`` read capability (FK-12 §12.1, blood T).

FK-10 §10.2.4a draws a hard line between "backend-seitige Subprocess-Git-
Zugriffe" (a malfunction -- physical worktree/repo access the backend must
never have) and the explicitly carved-out exception: Ref-Reads/Push-
Verifikation "bevorzugt via provider-neutralem git-Protokoll (`git
ls-remote`, kein Worktree noetig)". ``git ls-remote`` is a NETWORK-PROTOCOL
read against a remote URL -- it needs no local checkout, no working tree and
no physical repository on the backend host; it is invoked from an arbitrary
working directory. That is exactly the capability this module implements.

This module is a pure mechanic: it knows nothing about GitHub, Azure DevOps
or any other provider. It takes an opaque ``remote`` string (any URL/path
``git`` accepts as a remote) and a ``ref`` name; the CALLER (a provider
adapter) is responsible for deriving the ``remote`` from its own
provider-specific coordinate binding. Subprocess is encapsulated entirely
here (blood T); the :mod:`agentkit.backend.code_backend.provider_port`
A-core never imports this module.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from agentkit.backend.code_backend.provider_port import RefReadResult

__all__ = ["GitLsRemoteReader", "RefReader"]

#: Default per-invocation timeout for the ``git ls-remote`` subprocess.
_DEFAULT_LS_REMOTE_TIMEOUT_SECONDS = 15


@runtime_checkable
class RefReader(Protocol):
    """Structural shape of a ``ref_read`` mechanic (what :class:`GitLsRemoteReader`
    implements). Lets a provider adapter's ``ref_reader`` field be typed
    against this narrow Protocol instead of the concrete class, so tests can
    inject a recording/scripted double without subclassing.
    """

    def read_head_sha(self, remote: str, ref: str) -> RefReadResult:
        """Resolve the head SHA of ``ref`` on ``remote``."""
        ...


@dataclass(frozen=True)
class GitLsRemoteReader:
    """Provider-neutral ``ref_read`` mechanic over ``git ls-remote``.

    Runs ``git ls-remote --exit-code <remote> <ref>``: no local checkout, no
    worktree and no physical repository access on the backend host (FK-10
    §10.2.4a's git-protocol read exception). A non-resolvable ref/remote or an
    ambiguous match (more than one ref matched the given name) is a
    deterministic :class:`RefReadResult` with ``resolved=False`` -- never a
    raised exception and never a fabricated success.

    Attributes:
        timeout_seconds: Per-invocation timeout for the ``git`` subprocess.
    """

    timeout_seconds: int = _DEFAULT_LS_REMOTE_TIMEOUT_SECONDS

    def read_head_sha(self, remote: str, ref: str) -> RefReadResult:
        """Resolve the head SHA of ``ref`` on ``remote`` via ``git ls-remote``.

        Args:
            remote: Any remote ``git`` accepts (URL or local path). Opaque to
                this module -- the caller owns coordinate derivation.
            ref: The ref name or pattern to resolve (e.g. ``main`` or
                ``refs/heads/story/AG3-146``).

        Returns:
            A :class:`RefReadResult`; ``resolved=False`` on any subprocess
            failure, unreachable remote, unresolved ref or ambiguous match.
        """
        try:
            # Fixed argv (no shell); remote/ref are data, never shell-interpreted.
            completed = subprocess.run(  # noqa: S603
                ["git", "ls-remote", "--exit-code", remote, ref],  # noqa: S607
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return RefReadResult(
                ref=ref,
                resolved=False,
                head_sha=None,
                detail=f"git ls-remote failed to execute: {exc}",
            )
        if completed.returncode != 0:
            stderr = (completed.stderr or "").strip()
            return RefReadResult(
                ref=ref,
                resolved=False,
                head_sha=None,
                detail=(
                    f"git ls-remote {remote} {ref} failed (exit "
                    f"{completed.returncode}): {stderr or 'ref or remote not found'}"
                ),
            )
        lines = [line for line in completed.stdout.splitlines() if line.strip()]
        if not lines:
            return RefReadResult(
                ref=ref,
                resolved=False,
                head_sha=None,
                detail=f"git ls-remote {remote} {ref} returned no matching ref.",
            )
        if len(lines) > 1:
            return RefReadResult(
                ref=ref,
                resolved=False,
                head_sha=None,
                detail=(
                    f"git ls-remote {remote} {ref} matched {len(lines)} refs "
                    "(ambiguous); pass a fully-qualified ref."
                ),
            )
        head_sha = lines[0].split("\t", 1)[0].strip()
        if not head_sha:
            return RefReadResult(
                ref=ref,
                resolved=False,
                head_sha=None,
                detail=(
                    f"git ls-remote {remote} {ref} returned an unparsable line: "
                    f"{lines[0]!r}"
                ),
            )
        return RefReadResult(
            ref=ref,
            resolved=True,
            head_sha=head_sha,
            detail=f"resolved {ref} -> {head_sha}",
        )
