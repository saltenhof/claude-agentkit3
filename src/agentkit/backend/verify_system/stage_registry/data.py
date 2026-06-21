"""Verbatim Layer-1 stage definitions copied from FK-27 §27.4 / FK-33."""

from __future__ import annotations

from agentkit.backend.core_types import Severity
from agentkit.backend.core_types.qa_artifact_names import (
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
    STABILITY_GATE_PRODUCER,
    STRUCTURAL_PRODUCER,
)
from agentkit.backend.story_context_manager.types import StoryType
from agentkit.backend.verify_system.protocols import TrustClass
from agentkit.backend.verify_system.stage_registry.stages import (
    ExecutionPolicy,
    StageDefinition,
    StageKind,
    StageOverridePolicy,
)

__all__ = ["ALL_STAGES", "LAYER_1_STAGES", "STANDARD_STAGES"]

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


def _make_layer_1_stages() -> tuple[StageDefinition, ...]:
    """Build the canonical Layer-1 stage tuple (FK-27 §27.4.1-§27.4.4).

    Wrapped in a factory so the definition does not count toward module-level
    top-level LOC (S107-analogous LOC rule: PY_MODULE_TOP_LEVEL_MAX_LOC_100).
    Severities are VERBATIM from FK-27 §27.4.
    """
    return (
        # --- §27.4.1 Artifact check (precondition) ----------------------------
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


def _make_standard_stages() -> tuple[StageDefinition, ...]:
    """Build the complete standard stage tuple (Layer-1 + Layer-2/3/4).

    Wrapped in a factory to keep module-level top-level LOC below the
    PY_MODULE_TOP_LEVEL_MAX_LOC_100 threshold.
    """
    return (
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


def _make_all_stages() -> tuple[StageDefinition, ...]:
    """Build the ONE canonical stage catalogue (standard + integration stages).

    This is the single source of truth for the registry. It is a superset of
    :data:`STANDARD_STAGES`; the integration-stabilization stages
    (``integration.*`` + ``stability_gate``) are filtered IN only for the
    ``integration_stabilization`` contract by the contract-aware query methods
    (:meth:`StageRegistry.stages_for` / :meth:`StageRegistry.stage_for_id`).
    There is NO parallel registry: standard and IS stories both consume this
    one catalogue through the contract filter (AG3-069 MAJOR H).

    Adds the four FK-37 §37.1.3 named fail-closed checks on top of the
    standard stage set:

    - ``integration.declared_surfaces_only`` (Layer 1, BLOCKING, SYSTEM)
    - ``integration.stabilization_budget_not_exhausted`` (Layer 1, BLOCKING,
      SYSTEM — primary enforcement; also audited in QA-subflow per §37.1.3)
    - ``integration.integration_target_matrix_passed`` (Layer 4, BLOCKING,
      SYSTEM — QA-subflow/closure precondition per §37.1.3)
    - ``stability_gate`` (Layer 4, BLOCKING, SYSTEM — dedicated gate that
      wraps all four FK-37 §37.1.3 checks; registered here per AC5/§6)

    Preconditions (additional, named, fail-closed per AC12):
    - ``integration.manifest_approval_required`` (Layer 1, BLOCKING, SYSTEM)
    - ``integration.binding_integrity`` (Layer 1, BLOCKING, SYSTEM)
    """
    _integration_contract: frozenset[StoryType] = frozenset(
        (StoryType.IMPLEMENTATION,)
    )
    return (
        *STANDARD_STAGES,
        # --- Layer-1: named preconditions (manifest approval + binding) --------
        StageDefinition(
            stage_id="integration.manifest_approval_required",
            layer=1,
            severity=Severity.BLOCKING,
            applies_to=_integration_contract,
            kind=StageKind.DETERMINISTIC,
            trust_class=TrustClass.SYSTEM,
            producer=STABILITY_GATE_PRODUCER,
            override_policy=StageOverridePolicy.NONE,
        ),
        StageDefinition(
            stage_id="integration.binding_integrity",
            layer=1,
            severity=Severity.BLOCKING,
            applies_to=_integration_contract,
            kind=StageKind.DETERMINISTIC,
            trust_class=TrustClass.SYSTEM,
            producer=STABILITY_GATE_PRODUCER,
            override_policy=StageOverridePolicy.NONE,
        ),
        # --- Layer-1: FK-37 §37.1.3 deterministic checks -----------------------
        StageDefinition(
            stage_id="integration.declared_surfaces_only",
            layer=1,
            severity=Severity.BLOCKING,
            applies_to=_integration_contract,
            kind=StageKind.DETERMINISTIC,
            trust_class=TrustClass.SYSTEM,
            producer=STABILITY_GATE_PRODUCER,
            override_policy=StageOverridePolicy.NONE,
        ),
        StageDefinition(
            stage_id="integration.stabilization_budget_not_exhausted",
            layer=1,
            severity=Severity.BLOCKING,
            applies_to=_integration_contract,
            kind=StageKind.DETERMINISTIC,
            trust_class=TrustClass.SYSTEM,
            producer=STABILITY_GATE_PRODUCER,
            override_policy=StageOverridePolicy.NONE,
        ),
        # --- Layer-4: QA-subflow/closure precondition checks -------------------
        StageDefinition(
            stage_id="integration.integration_target_matrix_passed",
            layer=4,
            severity=Severity.BLOCKING,
            applies_to=_integration_contract,
            kind=StageKind.POLICY,
            trust_class=TrustClass.SYSTEM,
            producer=STABILITY_GATE_PRODUCER,
            override_policy=StageOverridePolicy.NONE,
        ),
        # --- stability_gate: dedicated Verify-Stage (FK-05 §5.10, AC5) ---------
        # Wraps all four FK-37 §37.1.3 checks; registered as a Layer-4 POLICY
        # stage (QA-subflow + closure precondition). FAIL on undeclared_surface,
        # unmet integration_targets, or budget breach.
        StageDefinition(
            stage_id="stability_gate",
            layer=4,
            severity=Severity.BLOCKING,
            applies_to=_integration_contract,
            kind=StageKind.POLICY,
            trust_class=TrustClass.SYSTEM,
            producer=STABILITY_GATE_PRODUCER,
            override_policy=StageOverridePolicy.NONE,
        ),
    )


#: All Layer-1 deterministic stages (FK-27 §27.4.1-§27.4.4), execution order:
#: artifact check (precondition) -> structural -> hygiene -> recurring guards ->
#: ARE-Gate -> impact. See :func:`_make_layer_1_stages` for the full definition.
LAYER_1_STAGES: tuple[StageDefinition, ...] = _make_layer_1_stages()

#: All standard stages: Layer-1 + Layer-2/3/4 (FK-27 §27.4.1-§27.4.4+).
#: See :func:`_make_standard_stages` for the full definition.
STANDARD_STAGES: tuple[StageDefinition, ...] = _make_standard_stages()

#: The ONE canonical stage catalogue: standard stages + the six
#: integration-stabilization stages (four FK-37 §37.1.3 checks + two
#: preconditions + stability_gate). This is the registry default; the
#: integration-stabilization stages are filtered IN only for the
#: ``integration_stabilization`` contract via the contract-aware query methods
#: (no parallel registry, AG3-069 MAJOR H). See :func:`_make_all_stages`.
ALL_STAGES: tuple[StageDefinition, ...] = _make_all_stages()
