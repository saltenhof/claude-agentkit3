"""Verbatim Layer-1 stage definitions copied from FK-27 §27.4 / FK-33."""

from __future__ import annotations

from agentkit.core_types import Severity
from agentkit.core_types.qa_artifact_names import (
    ADVERSARIAL_PRODUCER,
    BUGFIX_GREEN_EVIDENCE_PRODUCER,
    BUGFIX_RED_EVIDENCE_PRODUCER,
    BUGFIX_RED_GREEN_CONSISTENCY_PRODUCER,
    BUGFIX_REPRODUCER_MANIFEST_PRODUCER,
    BUGFIX_SUITE_EVIDENCE_PRODUCER,
    CONCEPT_FEEDBACK_PRODUCER,
    CONTEXT_SUFFICIENCY_PRODUCER,
    DOC_FIDELITY_PRODUCER,
    POLICY_PRODUCER,
    QA_REVIEW_PRODUCER,
    RESEARCH_QUALITY_PRODUCER,
    SEMANTIC_REVIEW_PRODUCER,
    SONARQUBE_GATE_PRODUCER,
    STRUCTURAL_PRODUCER,
)
from agentkit.story_context_manager.types import StoryType
from agentkit.verify_system.protocols import TrustClass
from agentkit.verify_system.stage_registry.stages import (
    ExecutionPolicy,
    StageDefinition,
    StageKind,
    StageOverridePolicy,
)

__all__ = ["LAYER_1_STAGES", "STANDARD_STAGES"]

#: The code-producing story types every Layer-1 deterministic stage applies
#: to (FK-33 §33.2.2 ``implementation, bugfix``).
_CODE_PRODUCING: frozenset[StoryType] = frozenset(
    (StoryType.IMPLEMENTATION, StoryType.BUGFIX)
)


def _stage(
    stage_id: str,
    severity: Severity,
    *,
    execution_policy: ExecutionPolicy = ExecutionPolicy.ALWAYS,
    escalated: bool = False,
    feature_gated_are: bool = False,
) -> StageDefinition:
    """Build a Layer-1 code-producing ``StageDefinition`` (DRY helper)."""
    return StageDefinition(
        stage_id=stage_id,
        layer=1,
        severity=severity,
        applies_to=_CODE_PRODUCING,
        kind=StageKind.DETERMINISTIC,
        trust_class=TrustClass.SYSTEM,
        producer=STRUCTURAL_PRODUCER,
        execution_policy=execution_policy,
        escalated=escalated,
        feature_gated_are=feature_gated_are,
    )


#: All Layer-1 deterministic stages (FK-27 §27.4.1-§27.4.4), in execution
#: order: artifact check (precondition) -> structural -> hygiene -> recurring
#: guards -> ARE-Gate -> impact. Severities are VERBATIM from FK-27 §27.4.
LAYER_1_STAGES: tuple[StageDefinition, ...] = (
    # --- §27.4.1 Artefakt-Pruefung (precondition) ----------------------------
    _stage("artifact.protocol", Severity.BLOCKING),
    _stage("artifact.worker_manifest", Severity.BLOCKING),
    # §27.4.1: artifact.manifest_claims is BLOCKING in FK-27 §27.4.1 AND
    # FK-33 §33.3.2. (The AG3-042 summary table said MAJOR; FK-27/FK-33 win.)
    _stage("artifact.manifest_claims", Severity.BLOCKING),
    _stage("artifact.handover", Severity.BLOCKING),
    # --- §27.4.2 Structural Checks (run after artifact PASS) ------------------
    _stage(
        "branch.story",
        Severity.BLOCKING,
        execution_policy=ExecutionPolicy.IF_LAYER_PASSES,
    ),
    # §27.4.2: branch.commit_trailers is BLOCKING. (The AG3-042 summary said
    # MINOR; FK-27 §27.4.2 / FK-33 §33.3.2 win -> BLOCKING.)
    _stage(
        "branch.commit_trailers",
        Severity.BLOCKING,
        execution_policy=ExecutionPolicy.IF_LAYER_PASSES,
    ),
    _stage(
        "completion.commit",
        Severity.BLOCKING,
        execution_policy=ExecutionPolicy.IF_LAYER_PASSES,
    ),
    _stage(
        "completion.push",
        Severity.BLOCKING,
        execution_policy=ExecutionPolicy.IF_LAYER_PASSES,
    ),
    _stage(
        "security.secrets",
        Severity.BLOCKING,
        execution_policy=ExecutionPolicy.IF_LAYER_PASSES,
    ),
    _stage(
        "security.secrets_content",
        Severity.BLOCKING,
        execution_policy=ExecutionPolicy.IF_LAYER_PASSES,
    ),
    # §27.4.2 Build & Test
    _stage(
        "build.compile",
        Severity.BLOCKING,
        execution_policy=ExecutionPolicy.IF_LAYER_PASSES,
    ),
    _stage(
        "build.test_execution",
        Severity.BLOCKING,
        execution_policy=ExecutionPolicy.IF_LAYER_PASSES,
    ),
    _stage(
        "test.count",
        Severity.MAJOR,
        execution_policy=ExecutionPolicy.IF_LAYER_PASSES,
    ),
    _stage(
        "test.coverage",
        Severity.MAJOR,
        execution_policy=ExecutionPolicy.IF_LAYER_PASSES,
    ),
    # --- §27.4.2 Code-Hygiene -------------------------------------------------
    _stage(
        "hygiene.todo_fixme",
        Severity.MINOR,
        execution_policy=ExecutionPolicy.IF_LAYER_PASSES,
    ),
    # §27.4.2: hygiene.disabled_tests is MINOR (FK-27 §27.4.2 / FK-33
    # §33.3.2). The AG3-042 summary table said MAJOR; FK-27 wins -> MINOR.
    _stage(
        "hygiene.disabled_tests",
        Severity.MINOR,
        execution_policy=ExecutionPolicy.IF_LAYER_PASSES,
    ),
    _stage(
        "hygiene.commented_code",
        Severity.MINOR,
        execution_policy=ExecutionPolicy.IF_LAYER_PASSES,
    ),
    # --- §27.4.3 Recurring Guards (telemetry-based, run parallel) -------------
    # REF-036: guard.llm_reviews and guard.multi_llm are two SEPARATE BLOCKING
    # gates (the two-stage LLM-review check, FK-27 §27.4.3).
    _stage("guard.llm_reviews", Severity.BLOCKING),
    # §27.4.3: guard.review_compliance is MAJOR (source ``review_compliant``).
    _stage("guard.review_compliance", Severity.MAJOR),
    _stage("guard.no_violations", Severity.BLOCKING),
    _stage("guard.multi_llm", Severity.BLOCKING),
    # --- §27.4.4 ARE-Gate (only when features.are == true) -------------------
    _stage(
        "are.gate",
        Severity.BLOCKING,
        feature_gated_are=True,
    ),
    # --- §27.4.2 Impact (BLOCKING; FAIL routes to ESCALATED per §27.4.5) -----
    _stage(
        "impact.violation",
        Severity.BLOCKING,
        execution_policy=ExecutionPolicy.IF_LAYER_PASSES,
        escalated=True,
    ),
    # --- FK-26 §26.9 Bugfix Red-Green-Suite -------------------------------
    StageDefinition(
        stage_id="bugfix.reproducer_manifest",
        layer=1,
        severity=Severity.BLOCKING,
        applies_to=frozenset((StoryType.BUGFIX,)),
        kind=StageKind.DETERMINISTIC,
        trust_class=TrustClass.SYSTEM,
        producer=BUGFIX_REPRODUCER_MANIFEST_PRODUCER,
        override_policy=StageOverridePolicy.NONE,
    ),
    StageDefinition(
        stage_id="bugfix.red_evidence",
        layer=1,
        severity=Severity.BLOCKING,
        applies_to=frozenset((StoryType.BUGFIX,)),
        kind=StageKind.DETERMINISTIC,
        trust_class=TrustClass.SYSTEM,
        producer=BUGFIX_RED_EVIDENCE_PRODUCER,
        override_policy=StageOverridePolicy.NONE,
    ),
    StageDefinition(
        stage_id="bugfix.green_evidence",
        layer=1,
        severity=Severity.BLOCKING,
        applies_to=frozenset((StoryType.BUGFIX,)),
        kind=StageKind.DETERMINISTIC,
        trust_class=TrustClass.SYSTEM,
        producer=BUGFIX_GREEN_EVIDENCE_PRODUCER,
        override_policy=StageOverridePolicy.NONE,
    ),
    StageDefinition(
        stage_id="bugfix.suite_evidence",
        layer=1,
        severity=Severity.BLOCKING,
        applies_to=frozenset((StoryType.BUGFIX,)),
        kind=StageKind.DETERMINISTIC,
        trust_class=TrustClass.SYSTEM,
        producer=BUGFIX_SUITE_EVIDENCE_PRODUCER,
        override_policy=StageOverridePolicy.NONE,
    ),
    StageDefinition(
        stage_id="bugfix.red_green_consistency",
        layer=1,
        severity=Severity.BLOCKING,
        applies_to=frozenset((StoryType.BUGFIX,)),
        kind=StageKind.DETERMINISTIC,
        trust_class=TrustClass.SYSTEM,
        producer=BUGFIX_RED_GREEN_CONSISTENCY_PRODUCER,
        override_policy=StageOverridePolicy.NONE,
    ),
)


STANDARD_STAGES: tuple[StageDefinition, ...] = (
    *LAYER_1_STAGES,
    StageDefinition(
        stage_id="sonarqube_gate",
        layer=1,
        severity=Severity.BLOCKING,
        applies_to=_CODE_PRODUCING,
        kind=StageKind.DETERMINISTIC,
        trust_class=TrustClass.SYSTEM,
        producer=SONARQUBE_GATE_PRODUCER,
    ),
    StageDefinition(
        stage_id="research_quality",
        layer=1,
        severity=Severity.MINOR,
        applies_to=frozenset((StoryType.RESEARCH,)),
        kind=StageKind.DETERMINISTIC,
        trust_class=TrustClass.SYSTEM,
        producer=RESEARCH_QUALITY_PRODUCER,
    ),
    StageDefinition(
        stage_id="qa_review",
        layer=2,
        severity=Severity.BLOCKING,
        applies_to=_CODE_PRODUCING,
        kind=StageKind.LLM_EVALUATION,
        trust_class=TrustClass.VERIFIED_LLM,
        producer=QA_REVIEW_PRODUCER,
    ),
    StageDefinition(
        stage_id="semantic_review",
        layer=2,
        severity=Severity.BLOCKING,
        applies_to=_CODE_PRODUCING,
        kind=StageKind.LLM_EVALUATION,
        trust_class=TrustClass.VERIFIED_LLM,
        producer=SEMANTIC_REVIEW_PRODUCER,
    ),
    StageDefinition(
        stage_id="doc_fidelity_impl",
        layer=2,
        severity=Severity.BLOCKING,
        applies_to=_CODE_PRODUCING,
        kind=StageKind.LLM_EVALUATION,
        trust_class=TrustClass.VERIFIED_LLM,
        producer=DOC_FIDELITY_PRODUCER,
    ),
    StageDefinition(
        stage_id="context_sufficiency",
        layer=2,
        severity=Severity.MINOR,
        applies_to=_CODE_PRODUCING,
        kind=StageKind.DETERMINISTIC,
        trust_class=TrustClass.SYSTEM,
        producer=CONTEXT_SUFFICIENCY_PRODUCER,
        override_policy=StageOverridePolicy.NONE,
    ),
    StageDefinition(
        stage_id="concept_feedback",
        layer=2,
        severity=Severity.BLOCKING,
        applies_to=frozenset((StoryType.CONCEPT,)),
        kind=StageKind.LLM_EVALUATION,
        trust_class=TrustClass.VERIFIED_LLM,
        producer=CONCEPT_FEEDBACK_PRODUCER,
    ),
    StageDefinition(
        stage_id="adversarial",
        layer=3,
        severity=Severity.BLOCKING,
        applies_to=_CODE_PRODUCING,
        kind=StageKind.AGENT,
        trust_class=TrustClass.VERIFIED_LLM,
        producer=ADVERSARIAL_PRODUCER,
    ),
    StageDefinition(
        stage_id="policy",
        layer=4,
        severity=Severity.BLOCKING,
        applies_to=_CODE_PRODUCING,
        kind=StageKind.POLICY,
        trust_class=TrustClass.SYSTEM,
        producer=POLICY_PRODUCER,
        override_policy=StageOverridePolicy.NONE,
    ),
)
