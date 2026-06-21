"""SonarQube-Green-Gate capability (FK-33 §33.6).

Public, callable capability surface for the deterministic "SonarQube
green?" gate. Exposed as a ``sub_exposed`` verify-system subcomponent so
the three lifecycle gate points can consume it without touching this
story (AC8):

* QA-subflow gate point (wired here, in this story, via
  ``verify_system.system``).
* Setup-green-main precondition (FK-22) -- consumer, AG3-034.
* Closure pre-merge / Integrity-Gate Dim 9 (FK-29/FK-35) -- consumer.

Contains the commit-bound attestation, the Broken-Window green
criterion, the 3-state applicability resolution, the accepted-exception
ledger, the deterministic single-match reconciler, and the
``sonarqube_gate`` stage definition. The external HTTP boundary lives in
``agentkit.integration_clients.sonar`` (thin adapter); no business logic there.
"""

from __future__ import annotations

from agentkit.backend.verify_system.sonarqube_gate.adapter import (
    BoundAnalysis,
    ConfiguredSonarGateInputPort,
    build_issue_applier,
    read_commit_bound_attestation,
    read_last_analyzed_revision,
    resolve_analysis_id,
)
from agentkit.backend.verify_system.sonarqube_gate.applicability import (
    SonarApplicability,
    is_code_producing_story,
    resolve_applicability,
)
from agentkit.backend.verify_system.sonarqube_gate.attestation import (
    QUALITY_GATE_OK,
    SonarAttestation,
    is_green,
    is_green_status,
)
from agentkit.backend.verify_system.sonarqube_gate.errors import (
    AttestationUnreadableError,
    LedgerInvalidError,
    ReconcilerApplyError,
    ReconcilerFailClosedError,
    SonarGateError,
)
from agentkit.backend.verify_system.sonarqube_gate.gate import (
    SonarGateOutcome,
    evaluate_sonarqube_gate,
    resolve_for_context,
)
from agentkit.backend.verify_system.sonarqube_gate.ledger import (
    AcceptedExceptionLedger,
    AcceptedExceptionLedgerEntry,
)
from agentkit.backend.verify_system.sonarqube_gate.reconciler import (
    ReconciliationResult,
    SonarIssue,
    reconcile_single_match,
)
from agentkit.backend.verify_system.sonarqube_gate.runtime_wiring import (
    SonarCoordinatesUnavailableError,
    build_sonar_gate_port_for_run,
)
from agentkit.backend.verify_system.sonarqube_gate.stage import (
    SONARQUBE_GATE_STAGE,
    SonarStageDefinition,
)

__all__ = [
    "QUALITY_GATE_OK",
    "SONARQUBE_GATE_STAGE",
    "AcceptedExceptionLedger",
    "AcceptedExceptionLedgerEntry",
    "AttestationUnreadableError",
    "BoundAnalysis",
    "ConfiguredSonarGateInputPort",
    "LedgerInvalidError",
    "ReconcilerApplyError",
    "ReconcilerFailClosedError",
    "ReconciliationResult",
    "SonarApplicability",
    "SonarCoordinatesUnavailableError",
    "SonarAttestation",
    "SonarGateError",
    "SonarGateOutcome",
    "SonarIssue",
    "SonarStageDefinition",
    "build_issue_applier",
    "build_sonar_gate_port_for_run",
    "evaluate_sonarqube_gate",
    "is_code_producing_story",
    "is_green",
    "is_green_status",
    "read_commit_bound_attestation",
    "read_last_analyzed_revision",
    "reconcile_single_match",
    "resolve_analysis_id",
    "resolve_applicability",
    "resolve_for_context",
]
