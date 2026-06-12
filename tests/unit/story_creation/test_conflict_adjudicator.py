"""Unit tests for the create-time conflict adjudicator (AG3-115 / FK-21 §21.4.1 Schritt 3).

These exercise the REAL collaborators end-to-end -- the real
:class:`StructuredEvaluator`, the real create-scope
:class:`CreateScopePromptMaterializer` (which resolves the real
``vectordb-conflict`` prompt from the pinned bundle), and the real two-stage
:class:`VectorDbReconciliation` for the port-compatibility proof. A fake lives
ONLY at the genuine LLM-hub/model edge (the ``LlmClient.complete`` boundary,
the CLAUDE.md mocks-exception).

The whole point of the story (§1.1): the adjudication runs WITHOUT any
``StoryContext`` / ``story_id`` / ``run_id`` / run-pin / story working
directory. The tests assert that negative explicitly.
"""

from __future__ import annotations

import pytest

from agentkit.config.models import VectorDbConfig
from agentkit.integrations.vectordb import StorySearchHit, VectorDbError
from agentkit.story_creation.conflict_adjudicator import (
    CreateScopePromptMaterializer,
    CreateTimeConflictAdjudicationError,
    CreateTimeConflictAdjudicator,
)
from agentkit.story_creation.vectordb_reconciliation import (
    VectorDbReconciliation,
)
from agentkit.verify_system.llm_evaluator.bundle import ReviewBundle
from agentkit.verify_system.llm_evaluator.llm_client import (
    LlmClientError,
    LoginRequiredError,
)
from agentkit.verify_system.llm_evaluator.roles import LlmVerdict, ReviewerRole

# ---------------------------------------------------------------------------
# Fake ONLY at the LLM-hub/model edge (CLAUDE.md mocks-exception).
# ---------------------------------------------------------------------------


class _FakeLlmClient:
    """A fake ``LlmClient`` -- the single permitted fake (LLM boundary only).

    Returns a canned raw completion text, or raises a transport error to
    simulate an LLM-hub outage. Records every prompt it received so the test
    can prove the create-scope prompt (no story context) was actually sent.
    """

    def __init__(
        self,
        *,
        response: str | None = None,
        error: LlmClientError | None = None,
    ) -> None:
        self._response = response
        self._error = error
        self.prompts: list[tuple[str, str]] = []

    def complete(self, *, role: str, prompt: str) -> str:
        self.prompts.append((role, prompt))
        if self._error is not None:
            raise self._error
        assert self._response is not None
        return self._response


def _checks_json(status: str, reason: str = "ok") -> str:
    return f'[{{"check_id": "conflict_assessment", "status": "{status}", "reason": "{reason}"}}]'


def _concern_json(reason: str = "overlapping but not a clear duplicate") -> str:
    return _checks_json("PASS_WITH_CONCERNS", reason)


def _bundle(story_id: str = "DRAFT-AG3-999") -> ReviewBundle:
    """Build a realistic create-time review bundle (new_story + candidates)."""
    return ReviewBundle(
        story_id=story_id,
        story_brief_excerpt="Add a retry/backoff path to the broker adapter.",
        acceptance_criteria=[],
        diff_summary="1 similarity candidate above threshold",
        diff_content=(
            "## Candidates\n"
            "- AG3-012 (score=0.940): Broker adapter resilience -- adds retry"
        ),
        concept_refs=["AG3-012"],
        previous_findings=None,
        qa_cycle_round=1,
    )


# -- AC2 / AC3: PASS + FAIL verdict over the real evaluator/transport path ---


def test_pass_verdict_no_conflict() -> None:
    """AC3: a clearly-distinct new story => PASS (conflict_assessment)."""
    client = _FakeLlmClient(response=_checks_json("PASS", "sufficiently delimited"))
    adjudicator = CreateTimeConflictAdjudicator(client)
    result = adjudicator.evaluate(
        ReviewerRole.STORY_CREATION_REVIEW, _bundle(), None, 1
    )
    assert result.verdict is LlmVerdict.PASS
    assert result.role is ReviewerRole.STORY_CREATION_REVIEW
    assert result.findings == ()


def test_fail_verdict_conflict_detected() -> None:
    """AC3: a duplicate/overlap candidate => FAIL with a recorded finding."""
    client = _FakeLlmClient(
        response=_checks_json("FAIL", "duplicate of AG3-012 (broker retry)")
    )
    adjudicator = CreateTimeConflictAdjudicator(client)
    result = adjudicator.evaluate(
        ReviewerRole.STORY_CREATION_REVIEW, _bundle(), None, 1
    )
    assert result.verdict is LlmVerdict.FAIL
    assert len(result.findings) == 1
    assert result.findings[0].check == "conflict_assessment"


# -- AC3 (binary): PASS_WITH_CONCERNS collapses to FAIL (fail-closed ambiguity) --


def test_pass_with_concerns_collapses_to_binary_fail() -> None:
    """Blocker fix: an ambiguous PASS_WITH_CONCERNS is treated as a conflict.

    FK-21 §21.4.1 Schritt 3 is BINARY (PASS / FAIL). The shared evaluator can
    return PASS_WITH_CONCERNS, which downstream reconciliation (FAIL-only
    conflict) would have slipped through as "no conflict" -- a fail-open gap.
    The adjudicator collapses it to a blocking FAIL fail-closed.
    """
    from agentkit.verify_system.protocols import Severity

    client = _FakeLlmClient(response=_concern_json("overlaps AG3-012 partially"))
    adjudicator = CreateTimeConflictAdjudicator(client)
    result = adjudicator.evaluate(
        ReviewerRole.STORY_CREATION_REVIEW, _bundle(), None, 1
    )
    # No "PASS when in doubt": the ambiguous verdict is a conflict.
    assert result.verdict is LlmVerdict.FAIL
    assert len(result.findings) == 1
    # The promoted concern finding is now BLOCKING (verdict/findings consistent).
    assert result.findings[0].severity is Severity.BLOCKING
    assert result.findings[0].check == "conflict_assessment"


def test_binary_collapse_makes_concern_a_downstream_conflict() -> None:
    """The collapsed FAIL is seen as a conflict by the REAL reconciliation.

    Proves the fail-open gap is actually closed end-to-end: a PASS_WITH_CONCERNS
    from the model drives ``hits_classified_conflict == 1`` through the real
    two-stage reconciliation (which classifies only FAIL as a conflict).
    """

    class _FakeAdapter:
        def story_search(
            self,
            query: str,
            *,
            search_mode: str = "hybrid",
            project_id: str,
            limit: int = 20,
        ) -> list[StorySearchHit]:
            del query, search_mode, project_id, limit
            return [
                StorySearchHit(
                    story_id="AG3-012",
                    title="Broker adapter resilience",
                    score=0.94,
                    snippet="adds retry",
                )
            ]

    client = _FakeLlmClient(response=_concern_json("partial overlap with AG3-012"))
    adjudicator = CreateTimeConflictAdjudicator(client)
    reconciliation = VectorDbReconciliation(
        _FakeAdapter(),  # type: ignore[arg-type]
        adjudicator,
        VectorDbConfig(similarity_threshold=0.7, max_llm_candidates=5),
    )
    result = reconciliation.reconcile(
        story_id="DRAFT-AG3-999",
        story_description="Add retry/backoff to the broker adapter.",
        project_id="AG3",
    )
    assert result.verdict is LlmVerdict.FAIL
    assert result.hits_classified_conflict == 1


def test_clear_pass_stays_pass() -> None:
    """A clean, unambiguous PASS is NOT promoted (binary collapse is one-way)."""
    client = _FakeLlmClient(response=_checks_json("PASS", "clearly distinct"))
    adjudicator = CreateTimeConflictAdjudicator(client)
    result = adjudicator.evaluate(
        ReviewerRole.STORY_CREATION_REVIEW, _bundle(), None, 1
    )
    assert result.verdict is LlmVerdict.PASS
    assert result.findings == ()


# -- AC2: create-scope works WITHOUT any story context (negative proof) ------


def test_runs_without_story_context_run_id_or_run_pin() -> None:
    """AC2: the call succeeds with NO StoryContext/story_id/run_id/run-pin.

    The adjudicator is constructed with only an LLM client (no StoryContext, no
    story dir, no run-pin, no ArtifactManager). The evaluation completes and the
    prompt-audit is cleanly ``skipped`` (no run_id), proving the create-scope
    path needs none of the execution-scoped materialization inputs.
    """
    client = _FakeLlmClient(response=_checks_json("PASS"))
    adjudicator = CreateTimeConflictAdjudicator(client)  # no story context at all
    result = adjudicator.evaluate(
        ReviewerRole.STORY_CREATION_REVIEW, _bundle(), None, 1
    )
    assert result.verdict is LlmVerdict.PASS
    # No run-pin existed => prompt-audit persistence is skipped cleanly, NOT an
    # error (the create-scope path never needs a run_id / story dir).
    assert result.prompt_audit_status == "skipped"


def test_create_scope_prompt_carries_new_story_and_candidates() -> None:
    """The real ``vectordb-conflict`` prompt + the bundle (new_story+candidates) is sent."""
    client = _FakeLlmClient(response=_checks_json("PASS"))
    adjudicator = CreateTimeConflictAdjudicator(client)
    adjudicator.evaluate(ReviewerRole.STORY_CREATION_REVIEW, _bundle("DRAFT-X"), None, 1)
    assert len(client.prompts) == 1
    role, prompt = client.prompts[0]
    assert role == "story_creation_review"
    # The real conflict-assessment template body is present (create-scope
    # resolved it from the pinned bundle, story_id placeholder substituted)...
    assert "VektorDB-Konfliktbewertung" in prompt
    assert "DRAFT-X" in prompt
    assert "{story_id}" not in prompt
    # ...and the bundle (new_story brief + candidates) is serialized in.
    assert "broker adapter" in prompt
    assert "AG3-012" in prompt


def test_materializer_needs_no_story_context() -> None:
    """The create-scope materializer resolves the prompt with ctx=None."""
    materializer = CreateScopePromptMaterializer()
    ctx, story_id = materializer.context_for(_bundle("DRAFT-Y"))
    assert ctx is None  # negative proof: no StoryContext at create time
    assert story_id == "DRAFT-Y"
    prompt_text, template_sha256 = materializer.render(
        ReviewerRole.STORY_CREATION_REVIEW, None, "DRAFT-Y"
    )
    assert "DRAFT-Y" in prompt_text
    assert len(template_sha256) == 64  # verified digest of the pinned template


# -- AC4: port compatibility with the AG3-114 reconciler expectation ---------


def test_port_substitutable_into_real_reconciler() -> None:
    """AC4: the adjudicator fills the ConflictEvaluatorPort slot AG3-114 injects.

    The REAL :class:`VectorDbReconciliation` (the consumer AG3-114 wires) drives
    the adjudicator as its stage-2 evaluator -- proving substitutability for the
    ``FailClosedConflictEvaluator`` slot WITHOUT modifying AG3-114. A fake lives
    only at the Weaviate adapter (stage 1) and the LLM hub (stage 2) edges.
    """

    class _FakeAdapter:
        def story_search(
            self,
            query: str,
            *,
            search_mode: str = "hybrid",
            project_id: str,
            limit: int = 20,
        ) -> list[StorySearchHit]:
            del query, search_mode, project_id, limit
            return [
                StorySearchHit(
                    story_id="AG3-012",
                    title="Broker adapter resilience",
                    score=0.94,
                    snippet="adds retry",
                )
            ]

    client = _FakeLlmClient(response=_checks_json("FAIL", "duplicate of AG3-012"))
    adjudicator = CreateTimeConflictAdjudicator(client)
    reconciliation = VectorDbReconciliation(
        _FakeAdapter(),  # type: ignore[arg-type]
        adjudicator,  # the create-time adjudicator IS the ConflictEvaluatorPort
        VectorDbConfig(similarity_threshold=0.7, max_llm_candidates=5),
    )
    result = reconciliation.reconcile(
        story_id="DRAFT-AG3-999",
        story_description="Add retry/backoff to the broker adapter.",
        project_id="AG3",
    )
    assert result.verdict is LlmVerdict.FAIL
    assert result.hits_classified_conflict == 1
    assert result.conflict_candidates == ("AG3-012",)


# -- AC5: §21.4.2 counters owner-faithfully (no shadow schema) ---------------


def test_abgleich_protocol_counters_from_reconciliation() -> None:
    """AC5: the §21.4.2 counters project owner-faithfully from the result."""
    from agentkit.story_creation.vectordb_reconciliation import (
        AbgleichProtocol,
        ReconciliationResult,
    )

    result = ReconciliationResult(
        verdict=LlmVerdict.FAIL,
        total_hits=47,
        hits_above_threshold=8,
        candidates_evaluated=5,
        hits_classified_conflict=1,
        threshold_value=0.7,
        conflict_candidates=("AG3-1", "AG3-2", "AG3-3", "AG3-4", "AG3-5"),
    )
    protocol = AbgleichProtocol.from_result(result)
    assert protocol.to_wire() == {
        "total_hits": 47,
        "above_threshold": 8,
        "sent_to_llm": 5,
        "llm_conflicts": 1,
        "threshold_used": 0.7,
        "search_mode": "hybrid",
    }


# -- AC6: fail-closed on LLM outage with a truthful, non-vectordb error -------


def test_llm_outage_fails_closed_with_truthful_distinguishable_error() -> None:
    """AC6: LLM transport down => CreateTimeConflictAdjudicationError, NOT vectordb."""
    client = _FakeLlmClient(error=LlmClientError("hub unreachable"))
    adjudicator = CreateTimeConflictAdjudicator(client)
    with pytest.raises(CreateTimeConflictAdjudicationError) as exc_info:
        adjudicator.evaluate(ReviewerRole.STORY_CREATION_REVIEW, _bundle(), None, 1)
    # Distinguishable from a VectorDB outage (NOT a VectorDbError subclass).
    assert not isinstance(exc_info.value, VectorDbError)
    message = str(exc_info.value)
    # Truthful message: BOTH LLM transport AND create-scope prompt resolution
    # are named (the error covers both fail-closed causes).
    assert "LLM transport or create-scope prompt resolution is unavailable" in message
    assert "VectorDB is healthy" in message
    # No dummy verdict was produced.


def test_prompt_resolution_failure_fails_closed_distinguishably(tmp_path: object) -> None:
    """AC6: an unresolvable prompt bundle also fail-closes (not a VectorDB outage).

    A project root with no prompt-bundle lock makes the create-scope materializer
    raise ``LlmClientError`` (FK-44 §44.4.2 fail-closed); the adjudicator maps it
    to the truthful create-time error, never a silent PASS and never a VectorDB
    outage.
    """
    from pathlib import Path

    client = _FakeLlmClient(response=_checks_json("PASS"))
    # A project root WITHOUT a prompt-bundle lock => the project binding cannot
    # be resolved => fail-closed at prompt resolution.
    adjudicator = CreateTimeConflictAdjudicator(
        client, project_root=Path(str(tmp_path))
    )
    with pytest.raises(CreateTimeConflictAdjudicationError) as exc_info:
        adjudicator.evaluate(ReviewerRole.STORY_CREATION_REVIEW, _bundle(), None, 1)
    assert not isinstance(exc_info.value, VectorDbError)
    # The LLM transport itself was never reached (prompt could not be built).
    assert client.prompts == []


def test_login_required_outage_also_fails_closed() -> None:
    """AC6: a login-required transport exit (LlmClientError subclass) fail-closes too."""
    client = _FakeLlmClient(
        error=LoginRequiredError("pool login required", operator_hint="pool=x")
    )
    adjudicator = CreateTimeConflictAdjudicator(client)
    with pytest.raises(CreateTimeConflictAdjudicationError):
        adjudicator.evaluate(ReviewerRole.STORY_CREATION_REVIEW, _bundle(), None, 1)


def test_no_pass_when_in_doubt_on_malformed_llm_response() -> None:
    """AC6: a structurally-invalid LLM response fails closed (no silent PASS).

    The real StructuredEvaluator rejects an unparseable/empty response after its
    bounded retry. The adjudicator must NOT mask that as a PASS verdict.
    """
    client = _FakeLlmClient(response="not json at all, no checks here")
    adjudicator = CreateTimeConflictAdjudicator(client)
    with pytest.raises(Exception) as exc_info:  # noqa: PT011 - assert type below
        adjudicator.evaluate(ReviewerRole.STORY_CREATION_REVIEW, _bundle(), None, 1)
    # It must never be a silent PASS; the structured-evaluator fail-closed error
    # propagates (it is NOT swallowed into a dummy verdict).
    assert "PASS" not in type(exc_info.value).__name__


# -- AC7-adjacent: the create-scope path only serves the create-time role -----


def test_rejects_execution_role_fail_closed() -> None:
    """An execution role must not be smuggled through the create-scope path."""
    client = _FakeLlmClient(response=_checks_json("PASS"))
    adjudicator = CreateTimeConflictAdjudicator(client)
    with pytest.raises(ValueError, match="story_creation_review"):
        adjudicator.evaluate(ReviewerRole.QA_REVIEW, _bundle(), None, 1)


def test_rejects_non_none_previous_findings_fail_closed() -> None:
    """Port-fidelity: a non-None create-time previous_findings list is rejected.

    The port surface is ``previous_findings: list[object] | None``. At create
    time there is no remediation round, so a non-None value cannot describe a
    real create-scope call -- it is rejected fail-closed before any LLM call.
    """
    client = _FakeLlmClient(response=_checks_json("PASS"))
    adjudicator = CreateTimeConflictAdjudicator(client)
    with pytest.raises(ValueError, match="previous_findings"):
        adjudicator.evaluate(
            ReviewerRole.STORY_CREATION_REVIEW, _bundle(), [object()], 1
        )
    # Fail-closed BEFORE the LLM transport was reached.
    assert client.prompts == []
