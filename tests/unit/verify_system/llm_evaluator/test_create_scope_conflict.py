"""Unit tests for the create-time conflict assessment (AG3-241 / FK-21 §21.4.1 Schritt 3).

Moved here from ``tests/unit/story_creation/test_conflict_adjudicator.py`` when
AG3-241 moved the adjudication itself out of the edge process: the assessment is
an LLM evaluation of the story being created, so it runs in the bounded context
that owns the evaluator, not in the process that owns the story.

These exercise the REAL collaborators end-to-end -- the real
:class:`StructuredEvaluator`, the real :class:`CreateScopePromptMaterializer`
(which resolves the real ``vectordb-conflict`` prompt from the pinned bundle) and
the real two-stage :class:`VectorDbReconciliation` for the port-compatibility
proof. A fake lives ONLY at the genuine LLM-hub/model edge (the
``LlmClient.complete`` boundary, the CLAUDE.md mocks-exception).

The whole point (§1.1): the adjudication runs WITHOUT any ``StoryContext`` /
``run_id`` / run-pin / story working directory. The tests assert that negative
explicitly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from agentkit.backend.config.models import (
    SUPPORTED_CONFIG_VERSION,
    Features,
    LlmRolesConfig,
    PipelineConfig,
    ProjectConfig,
    RepositoryConfig,
    VectorDbConfig,
)
from agentkit.backend.story_creation.vectordb_reconciliation import (
    VectorDbReconciliation,
)
from agentkit.backend.verify_system.llm_evaluator.bundle import ReviewBundle
from agentkit.backend.verify_system.llm_evaluator.create_scope_conflict import (
    CreateScopeConflictUnavailableError,
    CreateScopePromptMaterializer,
    CreateTimeConflictAdjudicator,
    _ConfigRolePoolResolver,
    build_conflict_bundle,
    build_create_time_conflict_adjudicator,
    request_round,
)
from agentkit.backend.verify_system.llm_evaluator.llm_client import (
    LlmClientError,
    LoginRequiredError,
)
from agentkit.backend.verify_system.llm_evaluator.roles import ReviewerRole
from agentkit.integration_clients.vectordb import StorySearchHit, VectorDbError
from agentkit_wire.verify_system import (
    ConflictCandidate,
    ConflictVerdict,
    StoryConflictAssessmentRequest,
)

if TYPE_CHECKING:
    from pathlib import Path

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
    return (
        f'[{{"check_id": "conflict_assessment", "status": "{status}", '
        f'"reason": "{reason}"}}]'
    )


def _concern_json(reason: str = "overlapping but not a clear duplicate") -> str:
    return _checks_json("PASS_WITH_CONCERNS", reason)


def _request(story_id: str = "DRAFT-AG3-999") -> StoryConflictAssessmentRequest:
    """Build a realistic create-time assessment request (new story + candidates)."""
    return StoryConflictAssessmentRequest(
        story_id=story_id,
        story_description="Add a retry/backoff path to the broker adapter.",
        candidates=(
            ConflictCandidate(
                story_id="AG3-012",
                score=0.94,
                title="Broker adapter resilience",
                snippet="adds retry",
            ),
        ),
    )


# -- AC2 / AC3: PASS + FAIL verdict over the real evaluator/transport path ---


def test_pass_verdict_no_conflict() -> None:
    """A clearly-distinct new story => binary PASS."""
    client = _FakeLlmClient(response=_checks_json("PASS", "sufficiently delimited"))
    adjudicator = CreateTimeConflictAdjudicator(client)  # type: ignore[arg-type]
    assert adjudicator.assess(_request()).verdict is ConflictVerdict.PASS


def test_fail_verdict_conflict_detected() -> None:
    """A duplicate/overlap candidate => binary FAIL."""
    client = _FakeLlmClient(
        response=_checks_json("FAIL", "duplicate of AG3-012 (broker retry)")
    )
    adjudicator = CreateTimeConflictAdjudicator(client)  # type: ignore[arg-type]
    assert adjudicator.assess(_request()).verdict is ConflictVerdict.FAIL


# -- binary collapse: PASS_WITH_CONCERNS becomes FAIL (fail-closed ambiguity) --


def test_pass_with_concerns_collapses_to_binary_fail() -> None:
    """An ambiguous PASS_WITH_CONCERNS is treated as a conflict.

    FK-21 §21.4.1 Schritt 3 is BINARY (PASS / FAIL). The shared evaluator can
    return PASS_WITH_CONCERNS, which downstream reconciliation (FAIL-only
    conflict) would have slipped through as "no conflict" -- a fail-open gap.
    The adjudicator collapses it to a blocking FAIL fail-closed.
    """
    client = _FakeLlmClient(response=_concern_json("overlaps AG3-012 partially"))
    adjudicator = CreateTimeConflictAdjudicator(client)  # type: ignore[arg-type]
    # No "PASS when in doubt": the ambiguous verdict is a conflict.
    assert adjudicator.assess(_request()).verdict is ConflictVerdict.FAIL


def test_wire_verdict_vocabulary_cannot_carry_the_ambiguous_value() -> None:
    """The collapse is structural: ``PASS_WITH_CONCERNS`` is not on the wire.

    The binary enum is what makes the collapse non-bypassable -- a third value
    on the boundary would be a value no producer may emit and that the single
    consumer reads as "no conflict".
    """
    assert set(ConflictVerdict) == {ConflictVerdict.PASS, ConflictVerdict.FAIL}


def test_binary_collapse_makes_concern_a_downstream_conflict() -> None:
    """The collapsed FAIL is seen as a conflict by the REAL reconciliation.

    Proves the fail-open gap is actually closed end-to-end: a PASS_WITH_CONCERNS
    from the model drives ``hits_classified_conflict == 1`` through the real
    two-stage reconciliation (which classifies only FAIL as a conflict).
    """
    client = _FakeLlmClient(response=_concern_json("partial overlap with AG3-012"))
    adjudicator = CreateTimeConflictAdjudicator(client)  # type: ignore[arg-type]
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
    assert result.verdict is ConflictVerdict.FAIL
    assert result.hits_classified_conflict == 1


def test_clear_pass_stays_pass() -> None:
    """A clean, unambiguous PASS is NOT promoted (binary collapse is one-way)."""
    client = _FakeLlmClient(response=_checks_json("PASS", "clearly distinct"))
    adjudicator = CreateTimeConflictAdjudicator(client)  # type: ignore[arg-type]
    assert adjudicator.assess(_request()).verdict is ConflictVerdict.PASS


# -- create scope works WITHOUT any story context (negative proof) -----------


def test_runs_without_story_context_run_id_or_run_pin() -> None:
    """The call succeeds with NO StoryContext/run_id/run-pin/story directory.

    The adjudicator is constructed with only an LLM client (no StoryContext, no
    story dir, no run-pin, no ArtifactManager). The assessment completes, proving
    the create-scope path needs none of the execution-scoped materialization
    inputs.
    """
    client = _FakeLlmClient(response=_checks_json("PASS"))
    adjudicator = CreateTimeConflictAdjudicator(client)  # type: ignore[arg-type]
    assert adjudicator.assess(_request()).verdict is ConflictVerdict.PASS


def test_create_scope_prompt_carries_new_story_and_candidates() -> None:
    """The real ``vectordb-conflict`` prompt + new_story/candidates is sent."""
    client = _FakeLlmClient(response=_checks_json("PASS"))
    adjudicator = CreateTimeConflictAdjudicator(client)  # type: ignore[arg-type]
    adjudicator.assess(_request("DRAFT-X"))
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
    bundle = build_conflict_bundle(_request("DRAFT-Y"))
    ctx, story_id = materializer.context_for(bundle)
    assert ctx is None  # negative proof: no StoryContext at create time
    assert story_id == "DRAFT-Y"
    prompt_text, template_sha256 = materializer.render(
        ReviewerRole.STORY_CREATION_REVIEW, None, "DRAFT-Y"
    )
    assert "DRAFT-Y" in prompt_text
    assert len(template_sha256) == 64  # verified digest of the pinned template


def test_bundle_has_no_remediation_round_and_no_previous_findings() -> None:
    """Create scope has exactly one round and no prior findings to carry.

    Replaces the old ``evaluate(role, bundle, previous_findings, round)``
    negative tests: the new ``assess(request)`` surface takes neither a role nor
    a ``previous_findings`` argument, so a caller can no longer supply either.
    What remains assertable -- and is asserted here -- is that the bundle the
    core builds carries the create-scope values that made those rejections
    necessary in the first place.
    """
    bundle = build_conflict_bundle(_request())
    assert bundle.previous_findings is None
    assert bundle.qa_cycle_round == request_round() == 1
    assert bundle.concept_refs == ["AG3-012"]
    assert isinstance(bundle, ReviewBundle)


# -- the create-scope transport only serves the create-time role -------------


def test_role_pool_resolver_serves_only_the_create_time_role() -> None:
    """An execution role must not be smuggled through the create-scope pool.

    Replaces the old ``evaluate(ReviewerRole.QA_REVIEW, ...)`` rejection: the
    adjudicator no longer takes a role, so the role fence moved to the only
    place a foreign role could still enter -- the pool resolver of the
    create-scope transport (FK-75 §75.3, no default pool).
    """
    resolver = _ConfigRolePoolResolver(story_creation_review_pool="chatgpt")
    assert resolver.resolve("story_creation_review") == "chatgpt"
    with pytest.raises(LlmClientError, match="story_creation_review"):
        resolver.resolve(ReviewerRole.QA_REVIEW.value)


# -- fail-closed on LLM outage with a truthful, non-vectordb error -----------


def test_llm_outage_fails_closed_with_truthful_distinguishable_error() -> None:
    """LLM transport down => CreateScopeConflictUnavailableError, NOT vectordb."""
    client = _FakeLlmClient(error=LlmClientError("hub unreachable"))
    adjudicator = CreateTimeConflictAdjudicator(client)  # type: ignore[arg-type]
    with pytest.raises(CreateScopeConflictUnavailableError) as exc_info:
        adjudicator.assess(_request())
    # Distinguishable from a VectorDB outage (NOT a VectorDbError subclass).
    assert not isinstance(exc_info.value, VectorDbError)
    message = str(exc_info.value)
    # Truthful message: BOTH LLM transport AND create-scope prompt resolution
    # are named (the error covers both fail-closed causes).
    assert "LLM transport or create-scope prompt resolution is unavailable" in message
    assert "VectorDB is healthy" in message
    # No dummy verdict was produced.


def test_prompt_resolution_failure_fails_closed_distinguishably(tmp_path: Path) -> None:
    """An unresolvable prompt bundle also fail-closes (not a VectorDB outage).

    A project root with no prompt-bundle lock makes the create-scope materializer
    raise ``LlmClientError`` (FK-44 §44.4.2 fail-closed); the adjudicator maps it
    to the truthful create-scope error, never a silent PASS and never a VectorDB
    outage.
    """
    client = _FakeLlmClient(response=_checks_json("PASS"))
    # A project root WITHOUT a prompt-bundle lock => the project binding cannot
    # be resolved => fail-closed at prompt resolution.
    adjudicator = CreateTimeConflictAdjudicator(
        client,  # type: ignore[arg-type]
        project_root=tmp_path,
    )
    with pytest.raises(CreateScopeConflictUnavailableError) as exc_info:
        adjudicator.assess(_request())
    assert not isinstance(exc_info.value, VectorDbError)
    # The LLM transport itself was never reached (prompt could not be built).
    assert client.prompts == []


def test_login_required_outage_also_fails_closed() -> None:
    """A login-required transport exit (LlmClientError subclass) fail-closes too."""
    client = _FakeLlmClient(
        error=LoginRequiredError("pool login required", operator_hint="pool=x")
    )
    adjudicator = CreateTimeConflictAdjudicator(client)  # type: ignore[arg-type]
    with pytest.raises(CreateScopeConflictUnavailableError):
        adjudicator.assess(_request())


def test_no_pass_when_in_doubt_on_malformed_llm_response() -> None:
    """A malformed LLM response fails closed (no traceback, no silent PASS).

    The real StructuredEvaluator rejects an unparseable / schema-invalid response
    after its bounded retry by raising ``StructuredEvaluatorError``. The core must
    WRAP that foreseeable failure in ``CreateScopeConflictUnavailableError`` so
    the route can map it to the stable ``story_conflict_assessment_unavailable``
    code -- never escaping as a raw ``StructuredEvaluatorError`` traceback and
    never masked as a PASS verdict.
    """
    from agentkit.backend.verify_system.llm_evaluator.structured_evaluator import (
        StructuredEvaluatorError,
    )

    client = _FakeLlmClient(response="not json at all, no checks here")
    adjudicator = CreateTimeConflictAdjudicator(client)  # type: ignore[arg-type]
    with pytest.raises(CreateScopeConflictUnavailableError) as exc_info:
        adjudicator.assess(_request())
    # The foreseeable malformed-output failure is wrapped fail-closed, NOT leaked
    # as a raw StructuredEvaluatorError traceback (stable error contract).
    assert not isinstance(exc_info.value, StructuredEvaluatorError)
    # Distinguishable from a VectorDB outage (NOT a VectorDbError subclass).
    assert not isinstance(exc_info.value, VectorDbError)
    # Truthful: the message names the malformed-output cause, so an operator is
    # not sent looking for a transport outage. (The "the VectorDB is healthy"
    # statement belongs to the EDGE half of this failure -- stage 1 runs there --
    # and is asserted in tests/unit/story_creation/test_conflict_adjudicator.py.)
    message = str(exc_info.value)
    assert "malformed" in message.lower()
    assert "fail-closed" in message.lower()


def test_malformed_output_chains_structured_evaluator_error() -> None:
    """The wrapped fail-closed error chains the underlying cause.

    The malformed-output ``CreateScopeConflictUnavailableError`` is raised
    ``from`` the original ``StructuredEvaluatorError``, so the truthful root
    cause is preserved for diagnostics while the stable, fail-closed type is what
    callers catch.
    """
    from agentkit.backend.verify_system.llm_evaluator.structured_evaluator import (
        StructuredEvaluatorError,
    )

    client = _FakeLlmClient(response="}{ definitely not a checks array")
    adjudicator = CreateTimeConflictAdjudicator(client)  # type: ignore[arg-type]
    with pytest.raises(CreateScopeConflictUnavailableError) as exc_info:
        adjudicator.assess(_request())
    assert isinstance(exc_info.value.__cause__, StructuredEvaluatorError)


# -- no configured pool BLOCKS; it never yields an unadjudicated pass --------


def _llm_roles(pool: str) -> LlmRolesConfig:
    """The mandatory execution roles plus the create-time role under test."""
    return LlmRolesConfig(
        qa_review="chatgpt",
        semantic_review="chatgpt",
        adversarial_sparring="chatgpt",
        doc_fidelity="chatgpt",
        governance_adjudication="chatgpt",
        story_creation_review=pool,
    )


def _project_config(*, pool: str | None) -> ProjectConfig:
    return ProjectConfig(
        project_key="ak3",
        project_name="AgentKit 3",
        repositories=[RepositoryConfig(name="ak3-backend", path="services/api")],
        story_types=["concept"],
        pipeline=PipelineConfig(
            config_version=SUPPORTED_CONFIG_VERSION,
            features=Features(multi_llm=False),
            llm_roles=None if pool is None else _llm_roles(pool),
        ),  # type: ignore[call-arg]
    )


def test_builder_without_a_configured_pool_raises_instead_of_returning_none() -> None:
    """No ``story_creation_review`` pool => fail-closed build, never ``None``.

    A builder that answered ``None`` would leave the caller holding "no
    adjudicator" and force it to invent what that means. The truthful blocker is
    raised at the build site (FK-75 §75.3 / FK-21 §21.4.3).
    """
    with pytest.raises(CreateScopeConflictUnavailableError, match="BLOCKED"):
        build_create_time_conflict_adjudicator(_project_config(pool=None))


def test_builder_rejects_a_pool_the_hub_does_not_know() -> None:
    """A configured-but-unknown pool is a defect, not a default (fail-closed)."""
    with pytest.raises(CreateScopeConflictUnavailableError, match="no default pool"):
        build_create_time_conflict_adjudicator(_project_config(pool="not-a-real-pool"))


# -- port compatibility with the reconciler expectation ---------------------


class _FakeAdapter:
    """Fake ONLY at the Weaviate edge (stage 1)."""

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


def test_port_substitutable_into_real_reconciler() -> None:
    """The core adjudicator fills the ``ConflictEvaluatorPort`` slot.

    The REAL :class:`VectorDbReconciliation` drives the adjudicator as its
    stage-2 evaluator -- proving the ``assess(request) -> response`` surface the
    edge's ``RestConflictAdjudicator`` also implements is the ONE contract. A
    fake lives only at the Weaviate adapter (stage 1) and the LLM hub (stage 2).
    """
    client = _FakeLlmClient(response=_checks_json("FAIL", "duplicate of AG3-012"))
    adjudicator = CreateTimeConflictAdjudicator(client)  # type: ignore[arg-type]
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
    assert result.verdict is ConflictVerdict.FAIL
    assert result.hits_classified_conflict == 1
    assert result.conflict_candidates == ("AG3-012",)


# -- §21.4.2 counters owner-faithfully (no shadow schema) -------------------


def test_abgleich_protocol_counters_from_reconciliation() -> None:
    """The §21.4.2 counters project owner-faithfully from the result."""
    from agentkit.backend.story_creation.vectordb_reconciliation import (
        AbgleichProtocol,
        ReconciliationResult,
    )

    result = ReconciliationResult(
        verdict=ConflictVerdict.FAIL,
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


# -- the old home is gone (a move, not a compatibility layer) ---------------


def test_the_create_scope_materializer_module_is_gone() -> None:
    """``story_creation.create_scope_materializer`` had no remainder after the move."""
    import importlib

    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(
            "agentkit.backend.story_creation.create_scope_materializer"
        )
