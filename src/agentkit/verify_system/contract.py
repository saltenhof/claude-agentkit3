"""verify-system contract models.

Defines the public input bundle (``VerifyContextBundle``) and the internal
wrapper model (``VerifyTarget`` + ``VerifyTargetType``).

Architecture rules:
- ``VerifyContextBundle`` is exported from ``agentkit.verify_system`` (public surface).
- ``VerifyTarget``, ``VerifyTargetType``, ``QaSubflowExecutionResult`` are
  INTERNAL. They are NEVER exported from ``agentkit.verify_system.__init__``
  and are never used as method parameters in the public API (AK11).

Quelle:
  - AG3-026 §2.1.1 -- VerifyContextBundle, VerifyTarget
  - AG3-026 §2.1.3 -- QaSubflowExecutionResult (optional internal detail)
  - ``concept/_meta/bc-cut-decisions.md §BC 2 verify-system``
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from agentkit.core_types import PolicyVerdict
from agentkit.pipeline_engine.phase_envelope.envelope import PhaseEnvelope
from agentkit.verify_system.protocols import LayerResult


class VerifyContextBundle(BaseModel):
    """Public input bundle for ``VerifySystem.run_qa_subflow``.

    Carries the run-time context that the VerifySystem needs to write
    QA artefacts and wire QA-cycle metadata into the produced envelopes.

    Attributes:
        run_id: Correlation ID of the current pipeline run.
        story_dir: Root directory of the story being verified.
        phase_envelope: Read-only snapshot of the current ``PhaseEnvelope``
            (or ``None`` if the caller has no envelope yet). The QA-cycle
            fields (``qa_cycle_id``, ``qa_cycle_round``, ``evidence_epoch``,
            ``evidence_fingerprint``) are read from
            ``phase_envelope.state.payload`` when present (AG3-026 §AK8;
            populated by AG3-041 / THEME-009).
        attempt: QA-subflow attempt counter (>= 1).
    """

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    run_id: str
    story_dir: Path
    phase_envelope: PhaseEnvelope | None = None
    attempt: int


class VerifyTargetType(StrEnum):
    """Classification of the artefact under review.

    Determines which QA-layer configuration is selected (routing.py).

    Attributes:
        IMPLEMENTATION: Normal implementation story output.
        EXPLORATION: Exploration/design-phase output.
        BUGFIX: Bugfix story output (treated identically to IMPLEMENTATION).
    """

    IMPLEMENTATION = "IMPLEMENTATION"
    EXPLORATION = "EXPLORATION"
    BUGFIX = "BUGFIX"


class VerifyTarget(BaseModel):
    """Internal wrapper resolved from ``ArtifactReference + VerifyContextBundle``.

    **NOT exported from ``agentkit.verify_system``** (AK11). Never used as
    a method parameter in the public API.

    Attributes:
        artifact_ref_record_key: Record key from the ``ArtifactReference``.
        target_type: Classification of the artefact under review.
        branch_ref: Optional git branch name relevant to this target.
        commit_sha: Optional git commit SHA relevant to this target.
        paths_in_scope: Tuple of paths that the QA-layers should evaluate.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    artifact_ref_record_key: str
    target_type: VerifyTargetType
    branch_ref: str | None = None
    commit_sha: str | None = None
    paths_in_scope: tuple[str, ...] = ()


class _QaSubflowExecutionResult(BaseModel):
    """Internal detail model for a completed QA-subflow run.

    **NOT exported from ``agentkit.verify_system``** (AK11). Callers see
    only the top-level ``PolicyVerdict`` return from ``run_qa_subflow``.

    Attributes:
        verdict: Overall PASS/FAIL decision.
        stage_results: Tuple of LayerResults from each executed layer.
        artifact_refs_written: Record keys of QA artefacts written.
        blocking_failures: Number of blocking findings.
        major_failures: Number of major findings.
        minor_failures: Number of minor findings.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    verdict: PolicyVerdict
    stage_results: tuple[LayerResult, ...]
    artifact_refs_written: tuple[str, ...]
    blocking_failures: int
    major_failures: int
    minor_failures: int


__all__ = [
    # Public
    "VerifyContextBundle",
    # Internal (listed for intra-BC imports only)
    "_QaSubflowExecutionResult",
    "VerifyTarget",
    "VerifyTargetType",
]
