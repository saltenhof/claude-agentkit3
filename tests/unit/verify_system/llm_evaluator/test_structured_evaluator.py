"""Unit tests for the fail-closed StructuredEvaluator (AG3-043 / FK-34).

The LLM transport (``LlmClient.complete``) and the prompt materializer
(``PromptRuntime.materialize_prompt``) are the only stubbed grenzen -- the
explicit Mock-Regel exception (story.md §8). The evaluator's JSON parsing,
schema validation, check-id whitelisting, finding mapping and
finding-resolution handling run for real (no core stubbing).
"""

from __future__ import annotations

import json

import pytest

from agentkit.story_context_manager.models import StoryContext
from agentkit.story_context_manager.types import StoryMode, StoryType
from agentkit.verify_system.llm_evaluator.bundle import ReviewBundle
from agentkit.verify_system.llm_evaluator.llm_client import (
    FailClosedLlmClient,
    LlmClientError,
)
from agentkit.verify_system.llm_evaluator.structured_evaluator import (
    QA_REVIEW_CHECK_IDS,
    LlmVerdict,
    ReviewerRole,
    StructuredEvaluator,
    StructuredEvaluatorError,
)
from agentkit.verify_system.protocols import Finding, Severity, TrustClass
from agentkit.verify_system.remediation.finding_resolution import (
    FindingResolutionStatus,
)

# ---------------------------------------------------------------------------
# Test doubles -- ONLY at the external grenzen (LLM + prompt-runtime).
# ---------------------------------------------------------------------------


class _ScriptedLlmClient:
    """LlmClient stub returning a pre-scripted completion (external grenze)."""

    def __init__(self, response: str, *, raise_transport: bool = False) -> None:
        self.response = response
        self.raise_transport = raise_transport
        self.calls: list[tuple[str, str]] = []

    def complete(self, *, role: str, prompt: str) -> str:
        self.calls.append((role, prompt))
        if self.raise_transport:
            raise LlmClientError("scripted transport failure")
        return self.response


class _StubMaterializer:
    """Prompt materializer stub (external prompt-runtime grenze)."""

    def __init__(self, template_text: str = "PROMPT", template_sha: str = "a" * 64) -> None:
        self.template_text = template_text
        self.template_sha = template_sha
        self.rendered_roles: list[ReviewerRole] = []

    def context_for(self, bundle: ReviewBundle) -> tuple[StoryContext, str]:
        ctx = StoryContext(
            project_key="test-project",
            story_id=bundle.story_id,
            story_type=StoryType.IMPLEMENTATION,
            execution_route=StoryMode.EXECUTION,
        )
        return ctx, bundle.story_id

    def render(
        self,
        role: ReviewerRole,
        ctx: StoryContext,
        story_id: str,
        template_override: str | None = None,
    ) -> tuple[str, str]:
        del ctx, story_id
        self.rendered_roles.append(role)
        name = template_override if template_override is not None else role.value
        return f"{self.template_text}:{name}", self.template_sha


def _bundle(story_id: str = "AG3-043", qa_cycle_round: int = 1) -> ReviewBundle:
    return ReviewBundle(
        story_id=story_id,
        story_brief_excerpt="brief",
        acceptance_criteria=["AC1"],
        diff_summary="1 file changed",
        diff_content="diff",
        concept_refs=["FK-34"],
        previous_findings=None,
        qa_cycle_round=qa_cycle_round,
    )


def _all_pass_qa() -> str:
    return json.dumps(
        [{"check_id": cid, "status": "PASS", "reason": "ok"} for cid in sorted(QA_REVIEW_CHECK_IDS)]
    )


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


def test_qa_review_all_pass_yields_pass_verdict_no_findings() -> None:
    client = _ScriptedLlmClient(_all_pass_qa())
    evaluator = StructuredEvaluator(client, _StubMaterializer())
    result = evaluator.evaluate(ReviewerRole.QA_REVIEW, _bundle(), None, 1)
    assert result.verdict is LlmVerdict.PASS
    assert result.findings == ()
    assert result.role is ReviewerRole.QA_REVIEW
    assert len(result.raw_response_hash) == 64
    assert result.template_sha256 == "a" * 64


def test_prompt_materializer_path_is_used_not_a_resource_read() -> None:
    """AK4: prompt comes via the materializer; the bundle JSON is appended."""
    client = _ScriptedLlmClient(_all_pass_qa())
    mat = _StubMaterializer(template_text="MATERIALIZED")
    evaluator = StructuredEvaluator(client, mat)
    evaluator.evaluate(ReviewerRole.QA_REVIEW, _bundle(), None, 1)
    assert mat.rendered_roles == [ReviewerRole.QA_REVIEW]
    _role, sent_prompt = client.calls[0]
    assert sent_prompt.startswith("MATERIALIZED:qa_review")
    assert "Review Bundle (JSON)" in sent_prompt


def test_fail_check_produces_blocking_finding_and_fail_verdict() -> None:
    checks = [{"check_id": cid, "status": "PASS", "reason": "ok"} for cid in sorted(QA_REVIEW_CHECK_IDS)]
    checks[0]["status"] = "FAIL"
    checks[0]["reason"] = "AC not met"
    client = _ScriptedLlmClient(json.dumps(checks))
    evaluator = StructuredEvaluator(client, _StubMaterializer())
    result = evaluator.evaluate(ReviewerRole.QA_REVIEW, _bundle(), None, 1)
    assert result.verdict is LlmVerdict.FAIL
    assert len(result.findings) == 1
    finding = result.findings[0]
    # FK-33 §33.8.2 / FK-34 §34.2.5: every Layer-2 FAIL blocks HARD and
    # threshold-independent -> BLOCKING severity (Trust B). The PolicyEngine
    # blocks on any BLOCKING finding regardless of max_major_findings.
    assert finding.severity is Severity.BLOCKING
    assert finding.trust_class is TrustClass.VERIFIED_LLM
    assert finding.check == sorted(QA_REVIEW_CHECK_IDS)[0]


def test_pass_with_concerns_is_non_blocking_minor_finding() -> None:
    checks = [{"check_id": cid, "status": "PASS", "reason": "ok"} for cid in sorted(QA_REVIEW_CHECK_IDS)]
    checks[0]["status"] = "PASS_WITH_CONCERNS"
    client = _ScriptedLlmClient(json.dumps(checks))
    evaluator = StructuredEvaluator(client, _StubMaterializer())
    result = evaluator.evaluate(ReviewerRole.QA_REVIEW, _bundle(), None, 1)
    assert result.verdict is LlmVerdict.PASS_WITH_CONCERNS
    assert len(result.findings) == 1
    assert result.findings[0].severity is Severity.MINOR


def test_semantic_review_single_check() -> None:
    client = _ScriptedLlmClient(
        json.dumps([{"check_id": "systemic_adequacy", "status": "PASS", "reason": "ok"}])
    )
    evaluator = StructuredEvaluator(client, _StubMaterializer())
    result = evaluator.evaluate(ReviewerRole.SEMANTIC_REVIEW, _bundle(), None, 1)
    assert result.verdict is LlmVerdict.PASS


def test_doc_fidelity_single_check() -> None:
    client = _ScriptedLlmClient(
        json.dumps([{"check_id": "impl_fidelity", "status": "FAIL", "reason": "drift"}])
    )
    evaluator = StructuredEvaluator(client, _StubMaterializer())
    result = evaluator.evaluate(ReviewerRole.DOC_FIDELITY, _bundle(), None, 1)
    assert result.verdict is LlmVerdict.FAIL
    assert result.findings[0].check == "impl_fidelity"


# ---------------------------------------------------------------------------
# AG3-068: story_creation_review role (FK-11 §11.5.1 / FK-21 §21.4.1)
# ---------------------------------------------------------------------------


def test_story_creation_review_role_is_registered_in_maps() -> None:
    """AC4: the new role is wired into the SHARED role maps (no 2nd path)."""
    from agentkit.verify_system.llm_evaluator.roles import (
        ROLE_CHECK_IDS,
        ROLE_TEMPLATE,
        STORY_CREATION_REVIEW_CHECK_IDS,
    )

    assert ReviewerRole.STORY_CREATION_REVIEW.value == "story_creation_review"
    assert frozenset(("conflict_assessment",)) == STORY_CREATION_REVIEW_CHECK_IDS
    assert ROLE_CHECK_IDS[ReviewerRole.STORY_CREATION_REVIEW] == frozenset(
        ("conflict_assessment",)
    )
    assert ROLE_TEMPLATE[ReviewerRole.STORY_CREATION_REVIEW] == "vectordb-conflict"


def test_story_creation_review_conflict_assessment_pass() -> None:
    """AC4: evaluate(story_creation_review) validates the conflict_assessment check."""
    client = _ScriptedLlmClient(
        json.dumps(
            [{"check_id": "conflict_assessment", "status": "PASS", "reason": "distinct"}]
        )
    )
    evaluator = StructuredEvaluator(client, _StubMaterializer())
    result = evaluator.evaluate(ReviewerRole.STORY_CREATION_REVIEW, _bundle(), None, 1)
    assert result.verdict is LlmVerdict.PASS
    assert result.role is ReviewerRole.STORY_CREATION_REVIEW


def test_story_creation_review_conflict_fail_blocks() -> None:
    """AC4/AC3: a duplicate/overlap conflict yields a FAIL verdict (one check)."""
    client = _ScriptedLlmClient(
        json.dumps(
            [
                {
                    "check_id": "conflict_assessment",
                    "status": "FAIL",
                    "reason": "duplicate of AG3-010",
                }
            ]
        )
    )
    evaluator = StructuredEvaluator(client, _StubMaterializer())
    result = evaluator.evaluate(ReviewerRole.STORY_CREATION_REVIEW, _bundle(), None, 1)
    assert result.verdict is LlmVerdict.FAIL
    assert result.findings[0].check == "conflict_assessment"


def test_story_creation_review_rejects_unknown_check_id_fail_closed() -> None:
    """Fail-closed: an off-whitelist check-id is rejected (exact-cover contract)."""
    client = _ScriptedLlmClient(
        json.dumps([{"check_id": "systemic_adequacy", "status": "PASS", "reason": "x"}])
    )
    evaluator = StructuredEvaluator(client, _StubMaterializer())
    with pytest.raises(StructuredEvaluatorError):
        evaluator.evaluate(ReviewerRole.STORY_CREATION_REVIEW, _bundle(), None, 1)


# ---------------------------------------------------------------------------
# Fail-closed: invalid JSON / schema / unknown ids (AK5)
# ---------------------------------------------------------------------------


def test_non_json_response_raises_structured_evaluator_error() -> None:
    # FK-11 §11.4.4: non-JSON text goes through all 3 stages (2 LLM calls),
    # then fails closed with a StructuredEvaluatorError.
    client = _ScriptedLlmClient("this is not json")
    evaluator = StructuredEvaluator(client, _StubMaterializer())
    with pytest.raises(StructuredEvaluatorError):
        evaluator.evaluate(ReviewerRole.SEMANTIC_REVIEW, _bundle(), None, 1)
    # Two LLM calls: initial attempt + one schema-hint retry (max 2, FK-11 §11.4.4).
    assert len(client.calls) == 2  # noqa: PLR2004


def test_non_array_response_raises_structured_evaluator_error() -> None:
    # FK-11 §11.4.4: dict response (not array) goes through all stages, then fails.
    client = _ScriptedLlmClient(json.dumps({"check_id": "systemic_adequacy"}))
    evaluator = StructuredEvaluator(client, _StubMaterializer())
    with pytest.raises(StructuredEvaluatorError):
        evaluator.evaluate(ReviewerRole.SEMANTIC_REVIEW, _bundle(), None, 1)
    assert len(client.calls) == 2  # noqa: PLR2004


def test_unknown_status_value_raises() -> None:
    # FK-11 §11.4.4: CheckResult schema violation → all stages fail → fail-closed.
    client = _ScriptedLlmClient(
        json.dumps([{"check_id": "systemic_adequacy", "status": "MAYBE"}])
    )
    evaluator = StructuredEvaluator(client, _StubMaterializer())
    with pytest.raises(StructuredEvaluatorError):
        evaluator.evaluate(ReviewerRole.SEMANTIC_REVIEW, _bundle(), None, 1)
    assert len(client.calls) == 2  # noqa: PLR2004


def test_extra_field_in_check_stage2_fails_stage3_recovers() -> None:
    """FK-11 §11.4.4: extra field causes Stage 2 Pydantic failure; Stage 3
    regex fallback recovers the meaningful check (PASS for systemic_adequacy).

    With 3-stage processing, a response with extra fields is not immediately
    rejected: Stage 2 fails the schema validation, but Stage 3 regex extracts
    the valid status/check_id and produces a correct result. This is the
    FK-11 §11.4.4 contract: the fallback chain exists precisely to recover
    from partially-malformed LLM responses.
    """
    client = _ScriptedLlmClient(
        json.dumps([{"check_id": "systemic_adequacy", "status": "PASS", "junk": 1}])
    )
    evaluator = StructuredEvaluator(client, _StubMaterializer())
    result = evaluator.evaluate(ReviewerRole.SEMANTIC_REVIEW, _bundle(), None, 1)
    assert result.verdict is LlmVerdict.PASS
    # Only one LLM call needed — Stage 3 recovered on attempt 1.
    assert len(client.calls) == 1


def test_unknown_check_id_for_role_raises() -> None:
    client = _ScriptedLlmClient(
        json.dumps([{"check_id": "totally_unknown", "status": "PASS"}])
    )
    evaluator = StructuredEvaluator(client, _StubMaterializer())
    # E2: an unexpected id is rejected by the exact-cover completeness check
    # (the expected systemic_adequacy is missing, totally_unknown is unexpected).
    with pytest.raises(StructuredEvaluatorError, match="not an exact cover"):
        evaluator.evaluate(ReviewerRole.SEMANTIC_REVIEW, _bundle(), None, 1)


# ---------------------------------------------------------------------------
# E2: fail-closed completeness -- exact cover, no dups, reason required.
# ---------------------------------------------------------------------------


def test_empty_array_is_not_silent_pass() -> None:
    """E2: an empty array must NOT be accepted as PASS (was the fail-open)."""
    client = _ScriptedLlmClient(json.dumps([]))
    evaluator = StructuredEvaluator(client, _StubMaterializer())
    with pytest.raises(StructuredEvaluatorError, match="not an exact cover"):
        evaluator.evaluate(ReviewerRole.QA_REVIEW, _bundle(), None, 1)


def test_partial_qa_array_rejected_not_pass() -> None:
    """E2: fewer than the 12 mandatory qa_review checks -> fail-closed."""
    partial = [
        {"check_id": cid, "status": "PASS"}
        for cid in sorted(QA_REVIEW_CHECK_IDS)[:5]
    ]
    client = _ScriptedLlmClient(json.dumps(partial))
    evaluator = StructuredEvaluator(client, _StubMaterializer())
    with pytest.raises(StructuredEvaluatorError, match="missing="):
        evaluator.evaluate(ReviewerRole.QA_REVIEW, _bundle(), None, 1)


def test_duplicate_check_id_rejected() -> None:
    """E2: the same mandatory check twice is a duplicate -> fail-closed."""
    checks = [{"check_id": cid, "status": "PASS"} for cid in sorted(QA_REVIEW_CHECK_IDS)]
    checks.append({"check_id": sorted(QA_REVIEW_CHECK_IDS)[0], "status": "PASS"})
    client = _ScriptedLlmClient(json.dumps(checks))
    evaluator = StructuredEvaluator(client, _StubMaterializer())
    with pytest.raises(StructuredEvaluatorError, match="duplicate check_id"):
        evaluator.evaluate(ReviewerRole.QA_REVIEW, _bundle(), None, 1)


def test_padded_array_with_extra_check_rejected() -> None:
    """E2: all 12 present PLUS an unexpected id -> fail-closed (no padding)."""
    checks = [{"check_id": cid, "status": "PASS"} for cid in sorted(QA_REVIEW_CHECK_IDS)]
    checks.append({"check_id": "systemic_adequacy", "status": "PASS"})  # wrong role
    client = _ScriptedLlmClient(json.dumps(checks))
    evaluator = StructuredEvaluator(client, _StubMaterializer())
    with pytest.raises(StructuredEvaluatorError, match="unexpected="):
        evaluator.evaluate(ReviewerRole.QA_REVIEW, _bundle(), None, 1)


def test_fail_check_without_reason_rejected() -> None:
    """E2: a FAIL with an empty reason is fail-closed (must be justified)."""
    checks = [{"check_id": cid, "status": "PASS"} for cid in sorted(QA_REVIEW_CHECK_IDS)]
    checks[0]["status"] = "FAIL"  # no reason field
    client = _ScriptedLlmClient(json.dumps(checks))
    evaluator = StructuredEvaluator(client, _StubMaterializer())
    with pytest.raises(StructuredEvaluatorError, match="empty 'reason'"):
        evaluator.evaluate(ReviewerRole.QA_REVIEW, _bundle(), None, 1)


def test_pass_with_concerns_whitespace_reason_rejected() -> None:
    """E2: a whitespace-only reason on PASS_WITH_CONCERNS is rejected."""
    checks = [{"check_id": cid, "status": "PASS"} for cid in sorted(QA_REVIEW_CHECK_IDS)]
    checks[0]["status"] = "PASS_WITH_CONCERNS"
    checks[0]["reason"] = "   "
    client = _ScriptedLlmClient(json.dumps(checks))
    evaluator = StructuredEvaluator(client, _StubMaterializer())
    with pytest.raises(StructuredEvaluatorError, match="empty 'reason'"):
        evaluator.evaluate(ReviewerRole.QA_REVIEW, _bundle(), None, 1)


def test_remediation_missing_resolution_check_rejected() -> None:
    """E2/E5: in remediation EVERY previous finding needs its resolution check."""
    prev = [_prev_finding("ac_fulfilled")]
    # All 12 base checks present, but the required resolution check is absent.
    checks = [{"check_id": cid, "status": "PASS"} for cid in sorted(QA_REVIEW_CHECK_IDS)]
    client = _ScriptedLlmClient(json.dumps(checks))
    evaluator = StructuredEvaluator(client, _StubMaterializer())
    with pytest.raises(StructuredEvaluatorError, match="finding_resolution_qa_review:ac_fulfilled"):
        evaluator.evaluate(ReviewerRole.QA_REVIEW, _bundle(qa_cycle_round=2), prev, 2)


def test_empty_completion_raises_llm_client_error() -> None:
    client = _ScriptedLlmClient("   \n  ")
    evaluator = StructuredEvaluator(client, _StubMaterializer())
    with pytest.raises(LlmClientError, match="empty completion"):
        evaluator.evaluate(ReviewerRole.SEMANTIC_REVIEW, _bundle(), None, 1)


def test_transport_failure_propagates_as_llm_client_error() -> None:
    client = _ScriptedLlmClient("", raise_transport=True)
    evaluator = StructuredEvaluator(client, _StubMaterializer())
    with pytest.raises(LlmClientError, match="scripted transport failure"):
        evaluator.evaluate(ReviewerRole.SEMANTIC_REVIEW, _bundle(), None, 1)


def test_fail_closed_llm_client_always_raises() -> None:
    """E6: the default productive client fails closed (no pool configured)."""
    client = FailClosedLlmClient()
    with pytest.raises(LlmClientError, match="No LLM pool is configured"):
        client.complete(role="qa_review", prompt="anything")


def test_fail_closed_client_drives_evaluator_to_failclosed() -> None:
    """E6: wired into the evaluator, the fail-closed client yields LlmClientError
    (Layer 2 RUNS and fails closed, never a silent PASS)."""
    evaluator = StructuredEvaluator(FailClosedLlmClient(), _StubMaterializer())
    with pytest.raises(LlmClientError, match="No LLM pool is configured"):
        evaluator.evaluate(ReviewerRole.QA_REVIEW, _bundle(), None, 1)


# ---------------------------------------------------------------------------
# Remediation mode / finding-resolution (AK6)
# ---------------------------------------------------------------------------


def _prev_finding(check: str = "ac_fulfilled") -> Finding:
    return Finding(
        layer="qa_review",
        check=check,
        severity=Severity.BLOCKING,
        message="prior",
        trust_class=TrustClass.VERIFIED_LLM,
    )


# E5: the resolution check-id encodes the canonical (layer, check) FindingKey.
_RES_ID = "finding_resolution_qa_review:ac_fulfilled"
_RES_KEY = ("qa_review", "ac_fulfilled")


def test_finding_resolution_fully_resolved_is_non_blocking() -> None:
    prev = [_prev_finding("ac_fulfilled")]
    checks = [{"check_id": cid, "status": "PASS"} for cid in sorted(QA_REVIEW_CHECK_IDS)]
    checks.append(
        {"check_id": _RES_ID, "status": "PASS", "resolution": "fully_resolved"}
    )
    client = _ScriptedLlmClient(json.dumps(checks))
    evaluator = StructuredEvaluator(client, _StubMaterializer())
    result = evaluator.evaluate(ReviewerRole.QA_REVIEW, _bundle(qa_cycle_round=2), prev, 2)
    assert result.verdict is LlmVerdict.PASS
    # E5: keyed by the canonical (layer, check) FindingKey, not a bare check id.
    assert result.finding_resolutions == {
        _RES_KEY: FindingResolutionStatus.FULLY_RESOLVED
    }


def test_finding_resolution_partially_resolved_blocks() -> None:
    prev = [_prev_finding("ac_fulfilled")]
    checks = [{"check_id": cid, "status": "PASS"} for cid in sorted(QA_REVIEW_CHECK_IDS)]
    checks.append(
        {"check_id": _RES_ID, "status": "PASS_WITH_CONCERNS",
         "resolution": "partially_resolved", "reason": "subcase still open"}
    )
    client = _ScriptedLlmClient(json.dumps(checks))
    evaluator = StructuredEvaluator(client, _StubMaterializer())
    result = evaluator.evaluate(ReviewerRole.QA_REVIEW, _bundle(qa_cycle_round=2), prev, 2)
    assert result.verdict is LlmVerdict.FAIL
    assert result.finding_resolutions[_RES_KEY] is FindingResolutionStatus.PARTIALLY_RESOLVED
    # The blocking resolution finding is BLOCKING (E1 unconditional block).
    assert result.findings[0].severity is Severity.BLOCKING


def test_finding_resolution_missing_resolution_field_raises() -> None:
    prev = [_prev_finding("ac_fulfilled")]
    checks = [{"check_id": cid, "status": "PASS"} for cid in sorted(QA_REVIEW_CHECK_IDS)]
    checks.append({"check_id": _RES_ID, "status": "PASS"})
    client = _ScriptedLlmClient(json.dumps(checks))
    evaluator = StructuredEvaluator(client, _StubMaterializer())
    with pytest.raises(StructuredEvaluatorError, match="invalid resolution"):
        evaluator.evaluate(ReviewerRole.QA_REVIEW, _bundle(qa_cycle_round=2), prev, 2)


def test_malformed_resolution_id_rejected() -> None:
    """E5 adversarial: a finding_resolution id without a 'layer:check' suffix
    is fail-closed (the previous finding's id is properly keyed)."""
    prev = [_prev_finding("ac_fulfilled")]
    checks = [{"check_id": cid, "status": "PASS"} for cid in sorted(QA_REVIEW_CHECK_IDS)]
    # Malformed suffix: no ':' separator. It is also not the required id, so it
    # fails completeness first (missing the proper key, unexpected this one).
    checks.append(
        {"check_id": "finding_resolution_nocolon", "status": "PASS",
         "resolution": "fully_resolved"}
    )
    client = _ScriptedLlmClient(json.dumps(checks))
    evaluator = StructuredEvaluator(client, _StubMaterializer())
    with pytest.raises(StructuredEvaluatorError):
        evaluator.evaluate(ReviewerRole.QA_REVIEW, _bundle(qa_cycle_round=2), prev, 2)


def test_finding_resolution_id_not_in_round_one_whitelist() -> None:
    """In round 1 the finding_resolution_* id is NOT expected (fail-closed)."""
    checks = [{"check_id": cid, "status": "PASS"} for cid in sorted(QA_REVIEW_CHECK_IDS)]
    checks.append(
        {"check_id": _RES_ID, "status": "PASS", "resolution": "fully_resolved"}
    )
    client = _ScriptedLlmClient(json.dumps(checks))
    evaluator = StructuredEvaluator(client, _StubMaterializer())
    # E2: round-1 cover is exactly the 12 base checks; the resolution id is
    # unexpected -> exact-cover failure.
    with pytest.raises(StructuredEvaluatorError, match="not an exact cover"):
        evaluator.evaluate(ReviewerRole.QA_REVIEW, _bundle(qa_cycle_round=1), None, 1)
