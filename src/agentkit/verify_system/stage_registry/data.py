"""Verbatim Layer-1 stage definitions copied from FK-27 §27.4 / FK-33.

Every severity below is copied VERBATIM from the FK-27 §27.4 tables
(§27.4.1 Artefakt-Pruefung, §27.4.2 Structural Checks, §27.4.3 Recurring
Guards, §27.4.4 ARE-Gate). Where the AG3-042 story summary table
(§2.1.1) and FK-27 §27.4.2 disagree on a severity, **FK-27 wins** (it is
the cited authoritative source): notably ``hygiene.disabled_tests`` is
**MINOR** per FK-27 §27.4.2 (the story summary said MAJOR).

Applicability (FK-33 §33.2.2/§33.2.4): all Layer-1 deterministic stages
apply to the code-producing story types ``implementation`` and ``bugfix``.
Concept/research stories do NOT traverse the verify pipeline (FK-33
§33.2.4 / §33.9) and therefore carry none of these stages.

REF-036 / FK-27 §27.4.3: ``guard.llm_reviews`` and ``guard.multi_llm`` are
two SEPARATE BLOCKING gates (the two-stage LLM-review check); they are
deliberately distinct ``StageDefinition`` entries, never merged.
"""

from __future__ import annotations

from agentkit.core_types import Severity
from agentkit.story_context_manager.types import StoryType
from agentkit.verify_system.stage_registry.stages import (
    ExecutionPolicy,
    StageDefinition,
)

__all__ = ["LAYER_1_STAGES"]

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
)
