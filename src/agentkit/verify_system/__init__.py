"""Verify-System bounded context.

Re-exports the central types that consumers need.

The Capability-A-Top-Komponente ``VerifySystem`` is the sole entry
point for cross-BC callers (FK-07 §7.4.2, FK-27,
``concept/_meta/bc-cut-decisions.md`` §"BC 2: verify-system"). Importing
internal sub-components such as ``policy_engine`` or
``adversarial_orchestrator`` from outside this BC is an AC001 violation.

AG3-026 additions (public surface only):
  - ``VerifyContextBundle``: input bundle for ``run_qa_subflow``.
  - ``VerifySystemError``, ``VerifyTargetUnknownError``,
    ``LayerExecutionError``: exception hierarchy.

NOT exported (AK11):
  - ``VerifyTarget``, ``VerifyTargetType``, ``QaSubflowExecutionResult``,
    ``PolicyVerdictResult`` -- all internal implementation detail.
"""

from __future__ import annotations

from agentkit.verify_system.artifacts import (
    build_verify_decision_artifact,
    load_verify_decision_artifact,
    serialize_finding,
    serialize_layer_result,
    verify_decision_passed,
    write_layer_artifacts,
    write_verify_decision_artifacts,
)
from agentkit.verify_system.contract import (
    PhaseEnvelopeView,
    QaSubflowOutcome,
    VerifyContextBundle,
)
from agentkit.verify_system.errors import (
    LayerExecutionError,
    VerifySystemError,
    VerifyTargetUnknownError,
)
from agentkit.verify_system.policy_engine.engine import VerifyDecision
from agentkit.verify_system.protocols import (
    Finding,
    LayerResult,
    QALayer,
    Severity,
    TrustClass,
)
from agentkit.verify_system.system import VerifySystem

__all__ = [
    "Finding",
    "LayerExecutionError",
    "LayerResult",
    "PhaseEnvelopeView",
    "QALayer",
    "QaSubflowOutcome",
    "Severity",
    "TrustClass",
    "VerifyContextBundle",
    "VerifyDecision",
    "VerifySystem",
    "VerifySystemError",
    "VerifyTargetUnknownError",
    "build_verify_decision_artifact",
    "load_verify_decision_artifact",
    "serialize_finding",
    "serialize_layer_result",
    "verify_decision_passed",
    "write_layer_artifacts",
    "write_verify_decision_artifacts",
]
