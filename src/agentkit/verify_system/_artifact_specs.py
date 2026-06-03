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
from agentkit.verify_system.contract import VerifyTargetType


@dataclass(frozen=True)
class _LayerArtifactSpec:
    """One QA artefact write specification (FK-27 §27.7 + AG3-026 §AK7)."""

    filename: str
    stage: str
    producer_name: str
    producer_type: ProducerType


#: Layer 1 -- single artefact ``structural.json`` (FK-27 §27.7)
LAYER_1_ARTIFACTS: tuple[_LayerArtifactSpec, ...] = (
    _LayerArtifactSpec(
        filename="structural.json",
        stage="qa-layer-structural",
        producer_name="verify-system.layer-1-structural",
        producer_type=ProducerType.DETERMINISTIC,
    ),
)

#: Layer 2 -- three artefacts (W1 / AG3-026 §AK7).
LAYER_2_SPECS: tuple[_LayerArtifactSpec, ...] = (
    _LayerArtifactSpec(
        filename="qa_review.json",
        stage="qa-layer-qa-review",
        producer_name="verify-system.layer-2-qa-review",
        producer_type=ProducerType.LLM_REVIEWER,
    ),
    _LayerArtifactSpec(
        filename="semantic_review.json",
        stage="qa-layer-semantic-review",
        producer_name="verify-system.layer-2-semantic-review",
        producer_type=ProducerType.LLM_REVIEWER,
    ),
    _LayerArtifactSpec(
        filename="doc_fidelity.json",
        stage="qa-layer-doc-fidelity",
        producer_name="verify-system.layer-2-doc-fidelity",
        producer_type=ProducerType.LLM_REVIEWER,
    ),
)

#: Layer 3 -- single artefact ``adversarial.json``
LAYER_3_ARTIFACTS: tuple[_LayerArtifactSpec, ...] = (
    _LayerArtifactSpec(
        filename="adversarial.json",
        stage="qa-layer-adversarial",
        producer_name="verify-system.layer-3-adversarial",
        producer_type=ProducerType.LLM_REVIEWER,
    ),
)

#: SonarQube-Green-Gate artefact (FK-33 §33.2.3; producer ``qa-sonarqube-gate``).
SONARQUBE_GATE_ARTIFACTS: tuple[_LayerArtifactSpec, ...] = (
    _LayerArtifactSpec(
        filename="sonarqube_gate.json",
        stage="qa-sonarqube-gate",
        producer_name="qa-sonarqube-gate",
        producer_type=ProducerType.DETERMINISTIC,
    ),
)

#: Policy/decision artefact (FK-27 §27.7 / AG3-026 §AK7: ``decision.json``).
POLICY_ARTIFACT_SPEC = _LayerArtifactSpec(
    filename="decision.json",
    stage="qa-policy-decision",
    producer_name="verify-system.layer-4-policy",
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
