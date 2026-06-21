"""QA-cycle mechanics for the verify-system BC (FK-27 §27.2).

Internal sub-package: NOT a cross-BC surface. Holds the atomic QA-cycle
lifecycle (:class:`QaCycleLifecycle`), the deterministic evidence-fingerprint
computation and the cycle-bound artefact invalidation (FK-27 §27.2.3).

Source: FK-27 §27.2 / AG3-041.
"""

from __future__ import annotations

from agentkit.backend.verify_system.qa_cycle.fingerprint import (
    FingerprintComputationError,
    compute_evidence_fingerprint,
)
from agentkit.backend.verify_system.qa_cycle.invalidation import (
    CYCLE_BOUND_QA_ARTIFACTS,
    ArtifactInvalidationEvent,
    ArtifactInvalidationSink,
    NullArtifactInvalidationSink,
    RecordingArtifactInvalidationSink,
    invalidate_cycle_artifacts,
)
from agentkit.backend.verify_system.qa_cycle.lifecycle import QaCycleLifecycle, QaCycleState

__all__ = [
    "CYCLE_BOUND_QA_ARTIFACTS",
    "ArtifactInvalidationEvent",
    "ArtifactInvalidationSink",
    "FingerprintComputationError",
    "NullArtifactInvalidationSink",
    "QaCycleLifecycle",
    "QaCycleState",
    "RecordingArtifactInvalidationSink",
    "compute_evidence_fingerprint",
    "invalidate_cycle_artifacts",
]
