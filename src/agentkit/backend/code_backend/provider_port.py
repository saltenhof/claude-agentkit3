"""Provider-neutral code-backend capability port (FK-12 §12.1, AG3-146).

PO-Direktive III (`concept/_meta/decisions/2026-07-02-k1-worktree-topologie.md`):
AgentKit must not be welded to GitHub specifics -- an Azure DevOps deployment is
planned. This module is the single, minimal capability-set Protocol every
code-backend provider adapter implements. It is the ONLY contract a consumer
may depend on; provider-specific mechanics (the ``gh`` CLI, REST/GraphQL calls,
provider coordinate formats) never appear here (SOLL-179..184).

Provider-neutrality rules enforced by this module's shape:

* No provider CLI arguments, no GitHub URL forms, no owner/repo-slug
  semantics anywhere in the Protocol. A provider coordinate (GitHub
  ``owner/repo``, Azure DevOps ``project/repository``, ...) is an OPAQUE,
  adapter-internal binding detail: it is bound once at adapter construction
  time and never surfaces on :class:`CodeBackendPort` itself.
* No generic "run an arbitrary provider command" surface (that was the
  pre-AG3-146 ``run_gh`` command facade -- replaced by this typed, minimal
  capability set).
* No writing/merge capability. A writing code-backend adapter is explicitly
  out of scope (SOLL-181); a later API-merge strand needs an FK-29
  equivalence proof before it may add one.

Minimal capability set (FK-12 §12.1 "Code-Backend-Feature" table):

* ``repo_probe`` -- repository existence/reachability.
* ``ref_read`` -- head SHA of a ref (the basis of push verification).
* ``compare_evidence`` -- a compare-/change-evidence READ surface on a
  pushed ref range. Declared here; productive consumers land in AG3-147+
  (this story stores only the ``git ls-remote`` read surface, In-Scope #2).
* ``ref_protection_administration`` -- the ``story/*`` ref-protection
  capability is DECLARED (queryable via :meth:`CodeBackendPort.capability_supported`)
  but not administered/enforced here; enforcement is AG3-147.

Capability matrix (informative; the concrete mechanic is an adapter internal,
never a Protocol concern):

| Capability | GitHub mechanic | Azure DevOps mechanic |
|---|---|---|
| ``repo_probe`` | ``gh repo view`` / REST ``GET`` repo | REST ``GET`` repository |
| ``ref_read`` | ``git ls-remote`` (protocol-neutral) | ``git ls-remote`` (protocol-neutral) |
| ``compare_evidence`` | Compare API (REST/GraphQL) | Diffs/commits REST API |
| ``ref_protection_administration`` | Rulesets API + GitHub App identity | Branch Security policies + Service Principal |

``ref_read`` is identical across providers because it runs over the universal
git wire protocol (FK-12 §12.1, FK-10 §10.2.4a/§10.2.4b) -- it needs no
provider CLI at all (SOLL-184). The other three capabilities are inherently
provider-specific and stay behind the adapter.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable

__all__ = [
    "CodeBackendCapability",
    "CodeBackendPort",
    "CompareEvidenceResult",
    "RefReadResult",
    "RepoProbeResult",
]


class CodeBackendCapability(StrEnum):
    """The minimal code-backend capability set (FK-12 §12.1, ARCH-55 codes)."""

    REPO_PROBE = "repo_probe"
    REF_READ = "ref_read"
    COMPARE_EVIDENCE = "compare_evidence"
    REF_PROTECTION_ADMINISTRATION = "ref_protection_administration"


@dataclass(frozen=True)
class RepoProbeResult:
    """Outcome of a provider-neutral repository reachability probe.

    Attributes:
        reachable: Whether the bound repository was confirmed to exist and be
            reachable through the adapter's binding.
        detail: Human-readable evidence (the failing reason when ``reachable``
            is ``False``).
    """

    reachable: bool
    detail: str


@dataclass(frozen=True)
class RefReadResult:
    """Outcome of a provider-neutral ``ref_read`` capability call.

    FAIL-CLOSED (AG3-146 AC2): a non-resolvable ref or remote is a
    deterministic ``resolved=False`` result, never a fabricated success and
    never an exception -- callers branch on ``resolved``, they never assume a
    present ``head_sha`` without checking it first.

    Attributes:
        ref: The ref that was queried (echoed back for caller correlation).
        resolved: Whether the ref resolved to exactly one head SHA.
        head_sha: The resolved head SHA, or ``None`` when ``resolved`` is
            ``False``.
        detail: Human-readable evidence (resolution detail or failure
            reason).
    """

    ref: str
    resolved: bool
    head_sha: str | None
    detail: str


@dataclass(frozen=True)
class CompareEvidenceResult:
    """Declared compare-/change-evidence read surface (FK-12 §12.1, In-Scope #2).

    AG3-146 declares this surface (the Protocol shape below); no adapter backs
    it with a real provider call yet -- productive consumers and the REST/
    GraphQL wiring land in AG3-147+. ``available=False`` is therefore the
    honest default everywhere in this story: it signals "not yet backed", not
    a transient failure of a working capability (ZERO DEBT -- no Attrappe
    pretending to compute real evidence).

    Attributes:
        base_ref: The base ref of the compare range that was requested.
        head_ref: The head ref of the compare range that was requested.
        available: Whether this call actually produced provider-backed
            evidence. ``False`` in AG3-146 for every adapter (declared-only).
        changed_paths: Changed paths on the compare range, when available.
        detail: Human-readable evidence or the "not yet backed" reason.
    """

    base_ref: str
    head_ref: str
    available: bool
    changed_paths: tuple[str, ...] = ()
    detail: str = ""


@runtime_checkable
class CodeBackendPort(Protocol):
    """Provider-neutral code-backend capability port (FK-12 §12.1, blood A).

    A provider adapter binds exactly one repository coordinate at
    construction time (opaque to this Protocol -- see the module docstring)
    and implements every method below. Consumers depend on this Protocol
    only; swapping GitHub for Azure DevOps means swapping the adapter that
    satisfies it, never touching a consumer (PO-Direktive III).
    """

    def repo_probe(self) -> RepoProbeResult:
        """Probe whether the bound repository exists and is reachable."""
        ...

    def ref_read(self, ref: str) -> RefReadResult:
        """Resolve the head SHA of ``ref`` on the bound repository.

        Args:
            ref: The ref to resolve (e.g. ``refs/heads/main`` or a story
                branch). Callers should pass a fully-qualified ref when the
                short name could be ambiguous (matching more than one
                namespace yields a fail-closed ``resolved=False``).

        Returns:
            A :class:`RefReadResult`; ``resolved=False`` on any
            non-resolvable ref or unreachable remote (fail-closed, never an
            empty/fabricated success).
        """
        ...

    def read_compare_evidence(
        self, base_ref: str, head_ref: str
    ) -> CompareEvidenceResult:
        """Read compare-/change-evidence for the ``base_ref..head_ref`` range.

        Declared surface (AG3-146 In-Scope #2): every AG3-146 adapter returns
        ``available=False`` (not yet backed by a productive provider call).
        Productive consumers and the provider-backed implementation land in
        AG3-147+.

        Args:
            base_ref: The base ref of the compare range.
            head_ref: The head ref of the compare range.

        Returns:
            A :class:`CompareEvidenceResult`.
        """
        ...

    def capability_supported(self, capability: CodeBackendCapability) -> bool:
        """Whether *capability* is actually wired and usable on this adapter.

        This is a build-time/runtime capability query, not a theoretical
        provider-feature claim: it answers "will calling this capability on
        THIS adapter instance do real work", not "does the provider in
        principle support this". A capability that is declared but not yet
        backed (e.g. ``ref_protection_administration`` before AG3-147) MUST
        report ``False`` here -- never a fabricated ``True`` (ZERO DEBT).

        Args:
            capability: The capability to query.

        Returns:
            ``True`` iff invoking the capability performs real, provider-
            backed work on this adapter.
        """
        ...
