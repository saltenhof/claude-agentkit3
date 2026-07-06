"""Deterministic QA-cycle evidence fingerprint from reported pushed heads.

The QA-cycle fingerprint is anchored in the pushed-only model (FK-10 §10.2.4b):
the backend no longer inspects a physical worktree with ``git diff`` or
untracked-file scans. Its input is the boundary evidence AgentKit can own in a
remote topology: Edge-reported/server-verified story-branch heads, optionally
augmented by provider compare evidence when that surface is wired.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from agentkit.backend.verify_system.errors import VerifySystemError

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

DEFAULT_DIFF_BASE = "origin/main"

_SECTION_HEADS = "## reported_heads"
_SECTION_COMPARE = "## compare_evidence"


class FingerprintComputationError(VerifySystemError):
    """Raised when the evidence fingerprint cannot be computed (fail-closed)."""


@dataclass(frozen=True)
class ReportedHeadEvidence:
    """One repo's pushed-head evidence for the QA-cycle fingerprint.

    Attributes:
        repo_id: Participating repository id.
        head_sha: The Edge-reported head SHA that the hard push barrier verifies
            server-side before a QA-cycle boundary opens.
        compare_paths: Optional provider compare/change-evidence paths for the
            base..head range. Empty until a provider-backed compare surface is
            wired.
    """

    repo_id: str
    head_sha: str
    compare_paths: tuple[str, ...] = ()


@runtime_checkable
class QaCycleFingerprintSource(Protocol):
    """Source of pushed-head evidence for QA-cycle fingerprinting."""

    def collect(self, story_dir: Path) -> Sequence[ReportedHeadEvidence]:
        """Return reported pushed heads for the story run resolved by ``story_dir``."""
        ...


class MissingFingerprintEvidenceSource:
    """Fail-closed default used when no productive fingerprint source is wired."""

    def collect(self, story_dir: Path) -> Sequence[ReportedHeadEvidence]:
        msg = (
            "QA-cycle evidence fingerprint source is not wired; backend-local "
            f"git/worktree fingerprinting is forbidden (story_dir={story_dir})"
        )
        raise FingerprintComputationError(msg)


class SyntheticFingerprintEvidenceSource:
    """Deterministic non-git fallback for legacy unit/unwired lifecycle users.

    This source never inspects a backend-local worktree. It produces a stable
    pseudo head from the story identity so direct ``QaCycleLifecycle`` tests and
    old lightweight constructors can still exercise QA-cycle transitions without
    regressing to forbidden local-git evidence.
    """

    def collect(self, story_dir: Path) -> Sequence[ReportedHeadEvidence]:
        digest = f"{uuid.uuid5(uuid.NAMESPACE_URL, str(story_dir)).int:040x}"[-40:]
        return (ReportedHeadEvidence(repo_id="unwired", head_sha=digest),)


def compute_evidence_fingerprint(
    story_dir: Path,
    *,
    reported_heads: Sequence[ReportedHeadEvidence],
    diff_base: str = DEFAULT_DIFF_BASE,
) -> str:
    """Compute the deterministic SHA-256 fingerprint from reported pushed heads.

    Args:
        story_dir: Story runtime directory, used only for diagnostics. It is not
            treated as a git/worktree root.
        reported_heads: One pushed-head evidence record per participating repo.
        diff_base: The logical compare base label included in the hash document.

    Returns:
        A 64-char lowercase hex SHA-256 digest.

    Raises:
        FingerprintComputationError: If no valid reported head is supplied.
    """
    del story_dir
    if not reported_heads:
        raise FingerprintComputationError(
            "cannot compute QA-cycle evidence fingerprint without reported "
            "pushed heads"
        )
    lines: list[str] = []
    compare_lines: list[str] = []
    for evidence in sorted(reported_heads, key=lambda item: item.repo_id):
        repo_id = evidence.repo_id.strip()
        head_sha = evidence.head_sha.strip().lower()
        if not repo_id or not _is_sha_like(head_sha):
            raise FingerprintComputationError(
                "invalid reported pushed head for QA-cycle fingerprint: "
                f"repo_id={evidence.repo_id!r}, head_sha={evidence.head_sha!r}"
            )
        lines.append(f"{repo_id}\n{head_sha}")
        for path in sorted({p.strip().replace('\\', '/') for p in evidence.compare_paths if p.strip()}):
            compare_lines.append(f"{repo_id}\n{path}")
    document = "\n".join(
        (
            f"base={diff_base}",
            _SECTION_HEADS,
            "\n".join(lines),
            _SECTION_COMPARE,
            "\n".join(compare_lines),
        )
    )
    return hashlib.sha256(document.encode("utf-8")).hexdigest()


def _is_sha_like(value: str) -> bool:
    return len(value) == 40 and all(c in "0123456789abcdef" for c in value)


__all__ = [
    "DEFAULT_DIFF_BASE",
    "FingerprintComputationError",
    "MissingFingerprintEvidenceSource",
    "QaCycleFingerprintSource",
    "ReportedHeadEvidence",
    "SyntheticFingerprintEvidenceSource",
    "compute_evidence_fingerprint",
]
