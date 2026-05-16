"""Verify-System bounded context.

Re-exports the central types that consumers need.

The Capability-A-Top-Komponente ``VerifySystem`` is the sole entry
point for cross-BC callers (FK-07 §7.4.2, FK-27,
``concept/_meta/bc-cut-decisions.md`` §"BC 2: verify-system"). Importing
internal sub-components such as ``policy_engine`` or
``adversarial_orchestrator`` from outside this BC is an AC001 violation.
"""

from __future__ import annotations

from agentkit.verify_system.artifacts import (
    GUARDRAIL_FILE,
    LAYER_ARTIFACT_FILES,
    PROTECTED_QA_ARTIFACTS,
    VERIFY_DECISION_FILE,
    build_verify_decision_artifact,
    load_verify_decision_artifact,
    serialize_finding,
    serialize_layer_result,
    verify_decision_passed,
    write_layer_artifacts,
    write_verify_decision_artifacts,
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
    "GUARDRAIL_FILE",
    "LAYER_ARTIFACT_FILES",
    "LayerResult",
    "PROTECTED_QA_ARTIFACTS",
    "QALayer",
    "Severity",
    "TrustClass",
    "VERIFY_DECISION_FILE",
    "VerifyDecision",
    "VerifySystem",
    "build_verify_decision_artifact",
    "load_verify_decision_artifact",
    "serialize_finding",
    "serialize_layer_result",
    "verify_decision_passed",
    "write_layer_artifacts",
    "write_verify_decision_artifacts",
]
