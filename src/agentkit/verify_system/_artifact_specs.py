"""Module-level artifact spec constants for system.py.

Extracted to reduce ``system.py`` module-level LOC (Sonar S8396 /
PY_MODULE_TOP_LEVEL_MAX_LOC_100). These are internal implementation
details of the verify-system BC and MUST NOT be imported outside
``agentkit.verify_system``.

FK-27 §27.7 + AG3-026 §AK7.
"""

from __future__ import annotations

from dataclasses import dataclass

from agentkit.artifacts import ProducerType
from agentkit.core_types import ArtifactClass
from agentkit.core_types.qa_artifact_names import (
    ADVERSARIAL_PRODUCER,
    ADVERSARIAL_STAGE,
    DOC_FIDELITY_FILE,
    DOC_FIDELITY_PRODUCER,
    DOC_FIDELITY_STAGE,
    QA_REVIEW_PRODUCER,
    QA_REVIEW_STAGE,
    SEMANTIC_REVIEW_PRODUCER,
    SEMANTIC_REVIEW_STAGE,
    SONARQUBE_GATE_PRODUCER,
    STRUCTURAL_PRODUCER,
    STRUCTURAL_STAGE,
    VERIFY_DECISION_FILE,
    VERIFY_DECISION_PRODUCER,
    VERIFY_DECISION_STAGE,
)
from agentkit.verify_system.contract import VerifyTargetType


@dataclass(frozen=True)
class _LayerArtifactSpec:
    """One QA artefact write specification (FK-27 §27.7 + AG3-026 §AK7)."""

    filename: str
    stage: str
    producer_name: str
    producer_type: ProducerType


#: Layer 1 -- single artefact ``structural.json`` (FK-27 §27.7).  Stage/producer
#: strings come from the cross-cutting SSOT ``core_types.qa_artifact_names`` (no
#: second naming truth, AG3-034 R2-H).
LAYER_1_ARTIFACTS: tuple[_LayerArtifactSpec, ...] = (
    _LayerArtifactSpec(
        filename="structural.json",
        stage=STRUCTURAL_STAGE,
        producer_name=STRUCTURAL_PRODUCER,
        producer_type=ProducerType.DETERMINISTIC,
    ),
)

#: Layer 2 -- three artefacts (W1 / AG3-026 §AK7).
LAYER_2_SPECS: tuple[_LayerArtifactSpec, ...] = (
    _LayerArtifactSpec(
        filename="qa_review.json",
        stage=QA_REVIEW_STAGE,
        producer_name=QA_REVIEW_PRODUCER,
        producer_type=ProducerType.LLM_REVIEWER,
    ),
    _LayerArtifactSpec(
        filename="semantic_review.json",
        stage=SEMANTIC_REVIEW_STAGE,
        producer_name=SEMANTIC_REVIEW_PRODUCER,
        producer_type=ProducerType.LLM_REVIEWER,
    ),
    _LayerArtifactSpec(
        filename=DOC_FIDELITY_FILE,
        stage=DOC_FIDELITY_STAGE,
        producer_name=DOC_FIDELITY_PRODUCER,
        producer_type=ProducerType.LLM_REVIEWER,
    ),
)

#: Layer 3 -- single artefact ``adversarial.json``
LAYER_3_ARTIFACTS: tuple[_LayerArtifactSpec, ...] = (
    _LayerArtifactSpec(
        filename="adversarial.json",
        stage=ADVERSARIAL_STAGE,
        producer_name=ADVERSARIAL_PRODUCER,
        producer_type=ProducerType.LLM_REVIEWER,
    ),
)

#: SonarQube-Green-Gate artefact (FK-33 §33.2.3).
SONARQUBE_GATE_ARTIFACTS: tuple[_LayerArtifactSpec, ...] = (
    _LayerArtifactSpec(
        filename="sonarqube_gate.json",
        stage="sonarqube_gate",
        producer_name=SONARQUBE_GATE_PRODUCER,
        producer_type=ProducerType.DETERMINISTIC,
    ),
)

#: Policy/decision artefact (FK-27 §27.7 / AG3-026 §AK7: ``decision.json``).
POLICY_ARTIFACT_SPEC = _LayerArtifactSpec(
    filename=VERIFY_DECISION_FILE,
    stage=VERIFY_DECISION_STAGE,
    producer_name=VERIFY_DECISION_PRODUCER,
    producer_type=ProducerType.DETERMINISTIC,
)

#: Maps artifact_class to internal VerifyTargetType.
#: All others -> VerifyTargetUnknownError (fail-closed, AG3-026 §2.1.4).
#:
#: AG3-015 decision (FK-44 §44.6): ``ArtifactClass.PROMPT_AUDIT`` is
#: deliberately NOT a verify target. A prompt-audit record is a
#: reproducibility proof produced by the prompt-runtime materialization, not
#: a QA-reviewable deliverable; routing it into the QA layers would be a
#: category error. Its absence is enforced fail-closed via the ``.get(...)``
#: fallback in ``system.py`` (``VerifyTargetUnknownError``) and pinned by
#: ``tests/unit/verify_system/test_artifact_class_target_mapping.py``.
#: (Other non-target classes -- PIPELINE, TELEMETRY, GOVERNANCE -- are
#: excluded for the same structural reason.)
ARTIFACT_CLASS_TO_TARGET_TYPE: dict[ArtifactClass, VerifyTargetType] = {
    ArtifactClass.WORKER: VerifyTargetType.IMPLEMENTATION,
    ArtifactClass.QA: VerifyTargetType.IMPLEMENTATION,
    ArtifactClass.ENTWURF: VerifyTargetType.EXPLORATION,
    ArtifactClass.HANDOVER: VerifyTargetType.IMPLEMENTATION,
    ArtifactClass.ADVERSARIAL_TEST_SANDBOX: VerifyTargetType.IMPLEMENTATION,
}
