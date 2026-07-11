"""Pure takeover-worktree reconcile classification (FK-56 §56.13e/f)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

type TakeoverReconcileResultType = Literal[
    "identity_ok",
    "remote_branch_diverged_after_takeover",
    "local_stale_or_dirty_takeover_target",
    "contested_local_writes",
]


@dataclass(frozen=True)
class TakeoverReconcileEvidence:
    """One repository's persistence-independent reconcile evidence."""

    repo_id: str
    takeover_base_sha: str | None
    remote_head_sha: str | None
    worktree_head_sha: str | None
    marker_present: bool
    reconcile_succeeded: bool
    target_stale_or_dirty: bool = False
    failure_detail: str = ""


@dataclass(frozen=True)
class TakeoverReconcileClassification:
    """Named, deterministic result for one repository reconcile."""

    repo_id: str
    result_type: TakeoverReconcileResultType
    detail: str

    @property
    def reconciled(self) -> bool:
        """Return whether this result permits the transfer obligation clear."""

        return self.result_type == "identity_ok"


def classify_takeover_reconcile(
    evidence: TakeoverReconcileEvidence,
) -> TakeoverReconcileClassification:
    """Classify one repo against its immutable transfer base.

    Missing server truth or ambiguous local identity fails closed into the
    contested freeze. Remote divergence takes precedence because it is a
    backend-owned ref read; a known stale/dirty target remains distinct from an
    otherwise ambiguous reconcile failure.
    """

    if evidence.takeover_base_sha is None or evidence.remote_head_sha is None:
        return _classification(
            evidence,
            "contested_local_writes",
            "takeover base or backend remote-head evidence is missing",
        )
    if evidence.remote_head_sha != evidence.takeover_base_sha:
        return _classification(
            evidence,
            "remote_branch_diverged_after_takeover",
            f"remote head {evidence.remote_head_sha} differs from takeover base "
            f"{evidence.takeover_base_sha}",
        )
    if evidence.target_stale_or_dirty:
        return _classification(
            evidence,
            "local_stale_or_dirty_takeover_target",
            evidence.failure_detail or "the local takeover target is stale or dirty",
        )
    if (
        not evidence.reconcile_succeeded
        or not evidence.marker_present
        or evidence.worktree_head_sha != evidence.takeover_base_sha
    ):
        return _classification(
            evidence,
            "contested_local_writes",
            evidence.failure_detail
            or "the reconciled worktree identity or head is not unambiguous",
        )
    return _classification(
        evidence,
        "identity_ok",
        "worktree marker, local head, remote head, and takeover base agree",
    )


def _classification(
    evidence: TakeoverReconcileEvidence,
    result_type: TakeoverReconcileResultType,
    detail: str,
) -> TakeoverReconcileClassification:
    return TakeoverReconcileClassification(
        repo_id=evidence.repo_id,
        result_type=result_type,
        detail=detail,
    )


__all__ = [
    "TakeoverReconcileClassification",
    "TakeoverReconcileEvidence",
    "TakeoverReconcileResultType",
    "classify_takeover_reconcile",
]
