"""Binding proof for the Pre-Merge-Verification-Runner (AG3-056, AC1/AC2).

The heart of the story: a Sonar analysis is accepted as binding to the
integrated candidate ONLY when Sonar/CI itself proves it. We never staple a
local ``git rev-parse HEAD`` onto a foreign/stale analysis.

Proof obligations (ALL must hold for ``produced=True``):

1. A scan was executed BY the triggered run — i.e. the ``ce_task_id`` /
   ``analysis_id`` originate from the run's own ``report-task.txt`` artefact,
   not a pre-existing local ``.scannerwork/`` file. (Enforced upstream by
   the scan runner reading the artefact from the build, not the worktree.)
2. The branch is proven by Sonar, not by a report-task field (ERROR-2): the
   attestation's ``last_analyzed_revision`` is read from the BRANCH-SCOPED
   ``project_analyses/search(component, branch=candidate.branch)`` matched
   strictly by the resolved ``analysisId``. Finding the analysisId UNDER the
   candidate branch's analyses IS the branch proof; it must additionally
   carry ``revision == candidate.commit_sha``. If the analysisId is not found
   on the candidate branch, the revision read misses upstream and the
   attestation is never produced (fail-closed) — there is no separate,
   non-real ``branch`` field to compare against.
3. The ``tree_hash`` echoed into the outcome is the one already pinned to
   the proven candidate commit (``CandidateRef.tree_hash``), which the
   consumer in turn asserts against the merge tree
   (``tree_hash(scan) == tree_hash(merge)``, FK-29 §29.1a.3).

Green/attestation logic is REUSED from AG3-052 (``sonarqube_gate``); this
module does not re-derive the green criterion.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agentkit.verify_system.sonarqube_gate.attestation import SonarAttestation


@dataclass(frozen=True)
class BindingProof:
    """Outcome of the candidate-binding check over a Sonar attestation.

    Attributes:
        bound: ``True`` iff Sonar proved the analysis belongs to the
            candidate commit on the candidate branch.
        reason: Machine reason for an unbound result; ``None`` when bound.
    """

    bound: bool
    reason: str | None = None


def prove_binding(
    attestation: SonarAttestation | None,
    *,
    candidate_commit_sha: str,
) -> BindingProof:
    """Prove a Sonar attestation is bound to the integrated candidate.

    The branch is proven UPSTREAM (ERROR-2): the attestation's
    ``last_analyzed_revision`` was read from the candidate-branch-scoped
    ``project_analyses/search`` matched strictly by the resolved analysisId, so
    a non-empty attestation already implies the analysis exists ON the
    candidate branch. This function therefore only has to confirm that the
    proven revision equals the candidate commit; there is no separate (and
    non-real) ``analyzed_branch`` field to compare.

    Args:
        attestation: The attestation read from the run's analysis reference,
            or ``None`` when no analysis could be read (fail-closed).
        candidate_commit_sha: The exact commit the analysis must have
            measured (``CandidateRef.commit_sha``).

    Returns:
        A :class:`BindingProof` — ``bound=True`` ONLY when the attestation
        exists AND its ``last_analyzed_revision`` equals the candidate commit
        (via :meth:`SonarAttestation.is_bound_to`). Otherwise a fail-closed
        unbound result with a specific reason.
    """
    if attestation is None:
        return BindingProof(
            bound=False,
            reason="no_analysis_from_run",
        )
    if not candidate_commit_sha:
        return BindingProof(bound=False, reason="candidate_commit_sha_missing")
    if not attestation.is_bound_to(candidate_commit_sha):
        return BindingProof(
            bound=False,
            reason=(
                "revision_mismatch: "
                f"last_analyzed_revision={attestation.last_analyzed_revision!r} "
                f"candidate_commit_sha={candidate_commit_sha!r}"
            ),
        )
    return BindingProof(bound=True)


__all__ = ["BindingProof", "prove_binding"]
