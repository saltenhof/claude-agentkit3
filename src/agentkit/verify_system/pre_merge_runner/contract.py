"""Port contract for the Pre-Merge-Verification-Runner (AG3-056).

This capability OWNS the port Protocols and result dataclasses that the
Closure pre-merge barrier (AG3-053, FK-29 §29.1a.3) consumes. The
dependency direction is strictly ``closure -> verify_system.pre_merge_runner``;
this module NEVER imports from ``agentkit.closure``.

The contract is deliberately minimal: the runner only needs enough to
(a) trigger/identify a CI run for the integrated candidate and (b) let the
consumer assert the tree-binding. It carries NO merge-lock / CAS / lease
concepts (those stay in Closure).

Field names match what the AG3-053 rewire expects, so wiring the real
runner into the barrier is trivial:

* ``ScanOutcome(produced, commit_sha, tree_hash, reason)``
* ``BuildTestOutcome(green, reason)``

FAIL-CLOSED (AG3-056 §2.1.4): a ``ScanOutcome`` is ``produced=True`` ONLY
when Sonar/CI itself proved the analysed revision equals
``candidate.commit_sha`` for the candidate branch; otherwise the outcome
is ``produced=False`` with a machine reason and ``commit_sha``/``tree_hash``
are ``None`` (never a locally-stapled commit on a foreign analysis).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from agentkit.verify_system.sonarqube_gate.attestation import SonarAttestation


@dataclass(frozen=True)
class CandidateRef:
    """The integrated-candidate commit a pre-merge run must verify.

    The Closure consumer builds this from its own ``IntegratedCandidate``;
    this capability uses it only to trigger/identify the run and to prove
    the Sonar/CI binding. No merge-lock concepts leak in.

    Attributes:
        branch: The integrated-candidate branch the scan/build runs on.
            Sonar's analysed branch MUST equal this for a bound result.
        commit_sha: The exact commit that MUST equal Sonar's analysed
            revision (``last_analyzed_revision``) for the candidate branch.
        tree_hash: The expected git tree hash of that commit, for the
            tree-binding the consumer asserts
            (``tree_hash(scan) == tree_hash(merge)``, FK-29 §29.1a.3).
    """

    branch: str
    commit_sha: str
    tree_hash: str


@dataclass(frozen=True)
class ScanOutcome:
    """Result of a commit-bound Sonar scan on the integrated candidate.

    Attributes:
        produced: ``True`` ONLY when a scan was executed BY the triggered
            run AND Sonar proved the analysed revision equals the candidate
            commit on the candidate branch (AG3-056 AC1/AC2). ``False`` for
            every fail-closed path.
        commit_sha: The proven analysed commit, echoed from the candidate
            ONLY after the proof succeeds; ``None`` when not produced.
        tree_hash: The git tree hash derived from the proven commit
            (``git rev-parse <commit_sha>^{tree}``); ``None`` when not
            produced. Never taken from a local ``HEAD``.
        reason: Machine reason for a not-produced outcome (which check
            failed); ``None`` on success.
        attestation: The FRESH, commit-bound :class:`SonarAttestation` the
            triggered run produced (FIX-1). Populated ONLY when
            ``produced is True``; ``None`` on every fail-closed path. The
            downstream consumer — the Closure IntegrityGate Dim 9 (FK-29
            §29.1a.3, FK-35 §35.2.4a) — MUST evaluate exactly THIS supplied
            attestation and MUST NOT re-read the worktree's local
            ``.scannerwork/report-task.txt`` (that stale-local-read path is
            the predecessor failure this story removes). The attestation is
            complete: ``tree_hash`` is bound to the proven candidate commit,
            ``exception_ledger_hash`` to the ledger actually used, and the
            gate/profile/scope/scanner metadata to the authoritative Sonar
            endpoints (FIX-4) — never empty-string-stamped.
    """

    produced: bool
    commit_sha: str | None = None
    tree_hash: str | None = None
    reason: str | None = None
    attestation: SonarAttestation | None = None


@dataclass(frozen=True)
class BuildTestOutcome:
    """Result of a commit-bound build+test run on the integrated candidate.

    Attributes:
        green: ``True`` ONLY when the triggered run's build AND test for the
            candidate commit passed (AG3-056 AC3). ``False`` for red/aborted/
            unreachable/timeout (fail-closed).
        reason: Machine reason for a not-green outcome; ``None`` on success.
    """

    green: bool
    reason: str | None = None


class PreMergeScanPort(Protocol):
    """Port that EXECUTES a commit-bound Sonar scan on the candidate.

    The Closure pre-merge barrier (AG3-053) depends on this Protocol, not
    on the concrete runner. The seam is fakeable so both this story and
    Closure can cover the positive AND negative paths in unit/integration
    tests.
    """

    def produce_attestation(self, candidate: CandidateRef) -> ScanOutcome:
        """Run/await a scan and return a binding-proven :class:`ScanOutcome`.

        Args:
            candidate: The integrated-candidate commit to verify.

        Returns:
            A ``produced=True`` outcome ONLY when Sonar proved the binding;
            otherwise a fail-closed ``produced=False`` outcome with a reason.
        """
        ...


class BuildTestPort(Protocol):
    """Port that EXECUTES a commit-bound build+test run on the candidate.

    Consumed by the Closure pre-merge barrier (AG3-053); fakeable seam.
    """

    def run(self, candidate: CandidateRef) -> BuildTestOutcome:
        """Run/await build+test for the candidate and return the outcome.

        Args:
            candidate: The integrated-candidate commit to build and test.

        Returns:
            A ``green=True`` outcome ONLY when build+test passed for exactly
            that commit; otherwise a fail-closed ``green=False`` outcome.
        """
        ...


__all__ = [
    "BuildTestOutcome",
    "BuildTestPort",
    "CandidateRef",
    "PreMergeScanPort",
    "ScanOutcome",
]
