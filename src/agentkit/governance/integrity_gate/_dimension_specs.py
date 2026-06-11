"""Module-level spec constants for the IntegrityGate dimensions.

Extracted from ``dimensions.py`` to keep that module's top-level LOC under the
Sonar ``PY_MODULE_TOP_LEVEL_MAX_LOC_100`` ceiling.  These are the FK-35 §35.2.4
verification thresholds, the dimension-classification tables and the canonical
QA stage/producer bindings the nine dimensions verify against.  Internal to
``agentkit.governance.integrity_gate``; not part of the public surface.
"""

from __future__ import annotations

from enum import StrEnum

from agentkit.core_types import EnvelopeStatus
from agentkit.core_types.qa_artifact_names import (
    ADVERSARIAL_PRODUCER,
    ADVERSARIAL_STAGE,
    QA_REVIEW_PRODUCER,
    QA_REVIEW_STAGE,
    SEMANTIC_REVIEW_PRODUCER,
    SEMANTIC_REVIEW_STAGE,
    STRUCTURAL_PRODUCER,
    STRUCTURAL_STAGE,
    VERIFY_DECISION_PRODUCER,
    VERIFY_DECISION_STAGE,
)


class IntegrityDimension(StrEnum):
    """Canonical integrity dimensions."""

    NO_QA_ARTIFACTS = "NO_QA_ARTIFACTS"
    CONTEXT_INVALID = "CONTEXT_INVALID"
    STRUCTURAL_SHALLOW = "STRUCTURAL_SHALLOW"
    DECISION_INVALID = "DECISION_INVALID"
    NO_LLM_REVIEW = "NO_LLM_REVIEW"
    NO_ADVERSARIAL = "NO_ADVERSARIAL"
    NO_VERIFY = "NO_VERIFY"
    TIMESTAMP_INVERSION = "TIMESTAMP_INVERSION"
    CONFLICT_FREEZE_PROOF = "CONFLICT_FREEZE_PROOF"
    SONARQUBE_GREEN = "SONARQUBE_GREEN"


#: FK-35 §35.2.4 depth thresholds (Dim 3 / Dim 4 / Dim 6).
STRUCTURAL_MIN_BYTES = 500
STRUCTURAL_MIN_CHECKS = 5
DECISION_MIN_BYTES = 200
ADVERSARIAL_MIN_BYTES = 200

#: AG3-079 (FK-48 §48.1.6/§48.1.8, FK-11 §11.8.2): the Dim-6 sparring/telemetry
#: expectations. The adversarial.json payload (the single source of truth the
#: gate already reads — no second telemetry-read port) mirrors the emitted-event
#: counts in its ``sparring`` proof AND its ``telemetry`` block. Dim 6 verifies
#: the FULL FK-48 §48.1.8 expectation table against those counts:
#:   * ``adversarial_start`` — EXACTLY 1,
#:   * ``adversarial_end`` — EXACTLY 1,
#:   * ``adversarial_sparring`` — >= 1 (AND >= 1 ``llm_call
#:     role=adversarial_sparring``, FK-11 §11.8.2),
#:   * ``adversarial_test_created`` — >= 0 (verified non-negative/consistent),
#:   * ``adversarial_test_executed`` — >= 1.
#: The start/end exactness is gate-verified (not merely assumed): a run that
#: emitted two starts or zero ends fails closed.
ADVERSARIAL_MIN_SPARRING_EVENTS = 1
ADVERSARIAL_MIN_LLM_CALL_SPARRING_EVENTS = 1
ADVERSARIAL_MIN_TESTS_EXECUTED = 1
ADVERSARIAL_EXPECTED_START = 1
ADVERSARIAL_EXPECTED_END = 1

#: Envelope statuses that mean a Layer-2 review did NOT produce a result
#: (FK-35 §35.2.4 Dim 5 "Status != SKIPPED").  AK3 has no ``SKIPPED`` status; a
#: genuinely skipped review writes NO envelope at all, and ``ERROR`` means
#: "Infrastruktur-Fehler (kein LLM-Ergebnis)" (FK-71) — i.e. no review result.
NON_REVIEW_STATUSES: frozenset[EnvelopeStatus] = frozenset({EnvelopeStatus.ERROR})

#: §35.2.3 pre-stage FAIL-codes (kept distinct from the §35.2.4 dimension IDs:
#: the pre-stage reports artifact ABSENCE, the dimensions report deeper
#: invariants).  Keyed by the dimension whose mandatory pre-condition failed.
MISSING_PRESTAGE_CODE: dict[IntegrityDimension, str] = {
    IntegrityDimension.NO_QA_ARTIFACTS: "MISSING_STRUCTURAL",
    IntegrityDimension.CONTEXT_INVALID: "MISSING_CONTEXT",
    IntegrityDimension.DECISION_INVALID: "MISSING_DECISION",
}

#: Mandatory-artifact pre-stage dimensions (hard pre-conditions, FK-35 §35.2.3).
#: NO_QA_ARTIFACTS/DECISION_INVALID are QA artifacts and apply only to code
#: stories (implementation/bugfix); concept/research carry no code-QA delivery
#: (FK-24 §24.3.1, profile ``uses_full_qa=False``) so for them only the context
#: dimension (CONTEXT_INVALID) is mandatory.
MANDATORY_DIMENSIONS: tuple[IntegrityDimension, ...] = (
    IntegrityDimension.NO_QA_ARTIFACTS,
    IntegrityDimension.DECISION_INVALID,
    IntegrityDimension.CONTEXT_INVALID,
)
#: Mandatory dimensions that only apply to code stories.
CODE_ONLY_MANDATORY: tuple[IntegrityDimension, ...] = (
    IntegrityDimension.NO_QA_ARTIFACTS,
    IntegrityDimension.DECISION_INVALID,
)

#: Dimensions evaluated only for implementation/bugfix (FK-35 §35.2.4 Dim 5/6).
#: These are the drift-fix dimensions whose ABSENCE for concept/research the
#: tests verify (governance-and-guards.C4, AK8).
CODE_ONLY_DIMENSIONS: tuple[IntegrityDimension, ...] = (
    IntegrityDimension.NO_LLM_REVIEW,
    IntegrityDimension.NO_ADVERSARIAL,
)
#: Post-mandatory dimensions evaluated only for code stories.  STRUCTURAL_SHALLOW
#: (Dim 3) verifies the structural QA *artifact* depth, which only code stories
#: produce (FK-24 §24.3.1, ``uses_full_qa=False``); concept/research have no
#: structural QA layer.  Dim 5/6 are the LLM/adversarial drift dimensions; the
#: QA-subflow flow_end (Dim 7, NO_VERIFY) reads the verify decision, which
#: concept/research never produce; Dim 9 (SONARQUBE_GREEN) is code-only AND
#: applicability-conditional (FK-35 §35.2.4a / FK-33 §33.6.5).
CODE_ONLY_EVALUATED: tuple[IntegrityDimension, ...] = (
    IntegrityDimension.STRUCTURAL_SHALLOW,
    IntegrityDimension.NO_LLM_REVIEW,
    IntegrityDimension.NO_ADVERSARIAL,
    IntegrityDimension.NO_VERIFY,
    IntegrityDimension.SONARQUBE_GREEN,
)

#: Mandatory dimensions that own a canonical QA envelope to field-validate.
MANDATORY_ENVELOPE_STAGE: dict[IntegrityDimension, str] = {
    IntegrityDimension.NO_QA_ARTIFACTS: STRUCTURAL_STAGE,
    IntegrityDimension.DECISION_INVALID: VERIFY_DECISION_STAGE,
}

#: Re-exported canonical QA stage/producer bindings (FK-27 §27.7) so dimension
#: logic references them from one place.
__all__ = [
    "ADVERSARIAL_EXPECTED_END",
    "ADVERSARIAL_EXPECTED_START",
    "ADVERSARIAL_MIN_BYTES",
    "ADVERSARIAL_MIN_LLM_CALL_SPARRING_EVENTS",
    "ADVERSARIAL_MIN_SPARRING_EVENTS",
    "ADVERSARIAL_MIN_TESTS_EXECUTED",
    "IntegrityDimension",
    "ADVERSARIAL_PRODUCER",
    "ADVERSARIAL_STAGE",
    "CODE_ONLY_DIMENSIONS",
    "CODE_ONLY_EVALUATED",
    "CODE_ONLY_MANDATORY",
    "DECISION_MIN_BYTES",
    "MANDATORY_DIMENSIONS",
    "MANDATORY_ENVELOPE_STAGE",
    "MISSING_PRESTAGE_CODE",
    "NON_REVIEW_STATUSES",
    "QA_REVIEW_PRODUCER",
    "QA_REVIEW_STAGE",
    "SEMANTIC_REVIEW_PRODUCER",
    "SEMANTIC_REVIEW_STAGE",
    "STRUCTURAL_MIN_BYTES",
    "STRUCTURAL_MIN_CHECKS",
    "STRUCTURAL_PRODUCER",
    "STRUCTURAL_STAGE",
    "VERIFY_DECISION_PRODUCER",
    "VERIFY_DECISION_STAGE",
]
