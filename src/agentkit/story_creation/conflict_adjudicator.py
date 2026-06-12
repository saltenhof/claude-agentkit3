"""Create-time conflict adjudicator (FK-21 §21.4.1 Schritt 3, pre-story scope).

FK-21 §21.4.1 Schritt 3 runs the **LLM conflict assessment** over the
above-threshold similarity candidates of a *new* story: role
``story_creation_review``, prompt template ``vectordb-conflict``, context
``{new_story, candidates}``, single check ``conflict_assessment`` -> ``PASS``
(no conflict) / ``FAIL`` (duplicate / overlap). The assessment **gates** the
creation, so it runs while the story does *not* yet exist.

The only :class:`StructuredEvaluator` materializer wired so far
(:class:`~agentkit.verify_system.llm_evaluator.prompt_materializer.PromptRuntimeMaterializer`)
is **story-execution scoped**: it requires a live ``StoryContext`` with a
resolved ``project_root``, a story working directory and a resolvable run-pin
(``resolve_run_scope`` -> non-``None`` ``run_id``; ``ensure_run_pin``). NONE of
those exist at create time (story.md §1.1). This module resolves that tension
**without weakening the execution scope and without a second LLM-call truth**:

* It REUSES the unchanged
  :class:`~agentkit.verify_system.llm_evaluator.structured_evaluator.StructuredEvaluator`
  and the unchanged FK-65 / FK-11 LLM transport (``LlmClient``). The evaluator
  body never needs a ``StoryContext`` -- that requirement lives *entirely* in
  the execution-scoped materializer. Its ``run_id`` parameter is optional and
  only drives the (skippable) prompt-audit envelope.
* It injects a dedicated **create-scope materializer**
  (:class:`CreateScopePromptMaterializer`) that resolves the ``vectordb-conflict``
  template from the pinned/bootstrap prompt bundle (FK-44 §44.4.2, the SAME
  bundle source) with NO ``StoryContext`` / ``run_id`` / run-pin / story dir.

The adjudicator implements exactly the ``ConflictEvaluatorPort`` surface that
AG3-114's ``runtime_factory`` injects (the slot the placeholder
``FailClosedConflictEvaluator`` holds today), so AG3-114-resume can substitute
the real adjudicator without touching AG3-114's create path.

Binary verdict (FK-21 §21.4.1 Schritt 3 / story.md §2.1.5): FK-21 §21.4.1
Schritt 3 specifies a BINARY outcome -- ``PASS`` (no conflict) **or** ``FAIL``
(duplicate / overlap). The shared :class:`StructuredEvaluator` aggregation,
however, can also return ``PASS_WITH_CONCERNS`` (an ambiguous / overlapping
candidate the model flagged but did not classify as a hard duplicate). On the
create-scope conflict-gate path that third state is a FAIL-OPEN gap: the
downstream reconciliation treats ONLY ``FAIL`` as a conflict, so a
``PASS_WITH_CONCERNS`` would slip an ambiguous candidate through as
"no conflict". This adjudicator therefore COLLAPSES the verdict to binary
fail-closed on ambiguity: an unambiguous ``PASS`` stays ``PASS``; anything else
(``PASS_WITH_CONCERNS``, ``FAIL``) becomes a blocking ``FAIL`` (no
"PASS when in doubt"). The execution-scoped QA/review aggregation is untouched
-- the collapse happens only here, on the create-time gate.

Fail-closed (story.md §2.1.5): when the LLM transport is unavailable the
adjudicator raises a TRUTHFUL :class:`CreateTimeConflictAdjudicationError` --
NOT a :class:`~agentkit.integrations.vectordb.VectorDbError`: the VectorDB is
healthy (stage 1 already succeeded); only the create-time LLM assessment could
not run. No dummy verdict, no "PASS when in doubt".

Source:
  - FK-21 §21.4.1 Schritt 3 -- the LLM conflict assessment (binary PASS/FAIL).
  - FK-21 §21.4.3 -- fail-closed (no soft fallback).
  - FK-34 / FK-11 §11.5.1 -- StructuredEvaluator + LlmClient (the ONE mechanic).
  - FK-44 §44.4.2 -- prompt resolution via the pinned bundle (no direct read).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from agentkit.story_creation.create_scope_materializer import (
    CreateScopePromptMaterializer,
)
from agentkit.verify_system.llm_evaluator.llm_client import LlmClientError
from agentkit.verify_system.llm_evaluator.roles import LlmVerdict, ReviewerRole
from agentkit.verify_system.llm_evaluator.structured_evaluator import (
    StructuredEvaluator,
    StructuredEvaluatorError,
    StructuredEvaluatorResult,
)
from agentkit.verify_system.protocols import Finding, Severity, TrustClass

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.verify_system.llm_evaluator.bundle import ReviewBundle
    from agentkit.verify_system.llm_evaluator.llm_client import LlmClient
    from agentkit.verify_system.llm_evaluator.structured_evaluator import (
        _PromptMaterializer,
    )


class CreateTimeConflictAdjudicationError(Exception):
    """Fail-closed: the create-time LLM conflict assessment could not run.

    Raised when the FK-65 / FK-11 LLM transport (or the create-scope prompt
    resolution) is unavailable, so the FK-21 §21.4.1 Schritt 3 conflict
    assessment over above-threshold candidates cannot be performed.

    This is DELIBERATELY a distinct type from
    :class:`~agentkit.integrations.vectordb.VectorDbError` /
    :class:`~agentkit.integrations.vectordb.VectorDbUnavailableError`: the
    VectorDB itself is healthy (stage-1 similarity search already returned the
    candidates that triggered stage 2); only the create-time LLM adjudication
    owner is unavailable. The create fail-closes (FK-21 §21.4.3 / NO ERROR
    BYPASSING) rather than passing an unadjudicated conflict, and the failure is
    never mislabelled as a VectorDB outage (story.md §2.1.5 / AC6). It carries no
    dummy verdict -- there is no "PASS when in doubt".
    """


class CreateTimeConflictAdjudicator:
    """Runs the FK-21 §21.4.1 Schritt 3 conflict assessment in create scope.

    Implements the ``ConflictEvaluatorPort`` surface
    (:meth:`evaluate(role, bundle, previous_findings, qa_cycle_round)
    -> StructuredEvaluatorResult`) that the two-stage
    :class:`~agentkit.story_creation.vectordb_reconciliation.VectorDbReconciliation`
    consumes and that AG3-114's ``runtime_factory`` injects. It delegates to the
    REAL :class:`StructuredEvaluator` (the single LLM-evaluation mechanic) wired
    with a :class:`CreateScopePromptMaterializer`, so the call runs WITHOUT any
    ``StoryContext`` / ``story_id`` / ``run_id`` / run-pin / story dir.
    """

    def __init__(
        self,
        llm_client: LlmClient,
        *,
        project_root: Path | None = None,
    ) -> None:
        """Initialise the adjudicator over the real LLM transport.

        Args:
            llm_client: The FK-65 / FK-11 LLM transport port (the SAME
                ``LlmClient`` the execution-scoped Layer-2 evaluations use; in
                production the injectable
                :class:`~agentkit.verify_system.llm_evaluator.llm_client.HubLlmClient`).
                A test double satisfies the mocks exception (LLM boundary only).
            project_root: Optional target-project root used ONLY to resolve the
                project-pinned prompt bundle binding (FK-44 §44.3). ``None`` ->
                the internal bootstrap bundle is used (non-project contexts).
                No ``StoryContext`` and no run-pin are derived from it.
        """
        materializer = CreateScopePromptMaterializer(project_root=project_root)
        # The StructuredEvaluator is reused UNCHANGED. No ArtifactManager / no
        # event emitter is wired here: create scope has no run-pinned artifact
        # store, so the prompt-audit persistence skips cleanly (run_id stays
        # None below) -- the execution-scoped QA/review path is untouched.
        #
        # The create-scope materializer matches the ``_PromptMaterializer``
        # SURFACE (``context_for`` + ``render``) but returns ``None`` for the
        # story-context slot the evaluator treats as an opaque pass-through token
        # (story.md §1.1). The cast records that intentional create-scope narrowing
        # without weakening the execution-scoped Protocol's ``StoryContext`` type.
        self._evaluator = StructuredEvaluator(
            llm_client, cast("_PromptMaterializer", materializer)
        )

    def evaluate(
        self,
        role: ReviewerRole,
        bundle: ReviewBundle,
        previous_findings: list[object] | None,
        qa_cycle_round: int,
    ) -> StructuredEvaluatorResult:
        """Adjudicate one create-time conflict assessment (FK-21 §21.4.1 Schritt 3).

        The signature matches the ``ConflictEvaluatorPort`` surface AG3-114
        injects EXACTLY (``previous_findings: list[object] | None``). ``role`` is
        asserted to be ``story_creation_review`` (the only create-time role) so a
        misrouted execution role cannot smuggle through the create-scope
        materializer.

        The verdict is COLLAPSED to binary (FK-21 §21.4.1 Schritt 3): an
        unambiguous ``PASS`` (no conflict) stays ``PASS``; ANY other aggregated
        verdict -- ``FAIL`` (hard duplicate / overlap) **and** the ambiguous
        ``PASS_WITH_CONCERNS`` -- becomes a blocking ``FAIL`` (fail-closed on
        ambiguity, story.md §2.1.5). This closes the fail-open gap where a
        ``PASS_WITH_CONCERNS`` candidate would slip through the downstream
        FAIL-only conflict check as "no conflict".

        Args:
            role: The reviewer role; must be
                :attr:`ReviewerRole.STORY_CREATION_REVIEW` (fail-closed).
            bundle: The review bundle carrying ``new_story`` (the new story
                description) + ``candidates`` (the above-threshold hits) built by
                the reconciliation. Its ``story_id`` is the draft display-id /
                search scope, NOT a persisted story id.
            previous_findings: Prior-round findings. Typed as ``list[object] |
                None`` to match the port surface; at create time there is NO
                remediation round before the story exists, so a non-``None``
                value is rejected fail-closed (the create scope carries no prior
                findings).
            qa_cycle_round: 1-based round (always ``1`` at create time).

        Returns:
            The validated :class:`StructuredEvaluatorResult` -- ``verdict``
            BINARY ``PASS`` (no conflict) or ``FAIL`` (duplicate / overlap /
            ambiguity), with the single ``conflict_assessment`` check.

        Raises:
            CreateTimeConflictAdjudicationError: When the LLM transport (or the
                create-scope prompt resolution) is unavailable, OR when the model
                returns malformed / schema-invalid output that cannot be parsed
                into a verdict after the evaluator's fail-closed retries --
                fail-closed, TRUTHFUL and distinguishable from a VectorDB outage.
                No dummy verdict, never a leaked traceback.
            ValueError: When ``role`` is not ``story_creation_review``, or when a
                non-``None`` ``previous_findings`` list is passed (fail-closed:
                the create-scope path serves only the create-time role and has no
                prior findings).
        """
        if role is not ReviewerRole.STORY_CREATION_REVIEW:
            msg = (
                "CreateTimeConflictAdjudicator only serves role "
                f"{ReviewerRole.STORY_CREATION_REVIEW.value!r}; got {role.value!r} "
                "(fail-closed: the create-scope path is not an execution-role "
                "evaluator)."
            )
            raise ValueError(msg)
        if previous_findings is not None:
            msg = (
                "CreateTimeConflictAdjudicator received non-None previous_findings "
                f"({len(previous_findings)} entr(y/ies)); the create-scope conflict "
                "gate runs before the story exists and has NO prior findings "
                "(fail-closed: no remediation round at create time)."
            )
            raise ValueError(msg)
        try:
            # run_id stays None: at create time there is no run-pin, so the
            # prompt-audit envelope is skipped cleanly (status "skipped"). The
            # conflict assessment itself is fully performed (no degraded path).
            # previous_findings is always None here (rejected above), so the
            # narrower execution-scoped evaluator signature is satisfied.
            result = self._evaluator.evaluate(
                role,
                bundle,
                None,
                qa_cycle_round,
                run_id=None,
            )
        except LlmClientError as exc:
            # The LLM transport (or create-scope prompt resolution, which raises
            # LlmClientError on a missing bundle) is unavailable. Fail-closed with
            # a TRUTHFUL, VectorDB-distinguishable error (story.md §2.1.5 / AC6).
            raise CreateTimeConflictAdjudicationError(
                "create-time conflict adjudication (FK-21 §21.4.1 Schritt 3) could "
                "not run: the LLM transport or create-scope prompt resolution is "
                "unavailable. The VectorDB is healthy (stage-1 similarity already "
                "returned the candidates); only the create-time LLM assessment "
                "failed. Story creation is BLOCKED fail-closed (FK-21 §21.4.3) -- "
                f"no dummy verdict, no PASS-when-in-doubt. Cause: {exc}"
            ) from exc
        except StructuredEvaluatorError as exc:
            # The LLM transport answered, but the model output is malformed /
            # schema-invalid and could not be parsed into a structured verdict even
            # after the evaluator's fail-closed retries (FK-11 §11.4.4). This is a
            # FORESEEABLE create-time LLM-assessment failure: it must fail closed
            # with the SAME truthful CreateTimeConflictAdjudicationError (mapped to
            # the stable ``conflict_adjudication_unavailable`` wire code) -- NEVER a
            # leaked traceback (stable tool error contract) and NEVER a dummy
            # verdict / PASS-when-in-doubt. The VectorDB is healthy (stage-1
            # similarity already returned the candidates); only the create-time LLM
            # assessment could not produce a usable verdict (story.md §2.1.5 / AC6).
            raise CreateTimeConflictAdjudicationError(
                "create-time conflict adjudication (FK-21 §21.4.1 Schritt 3) could "
                "not run: the create-time LLM produced malformed / schema-invalid "
                "output that could not be parsed into a conflict verdict (FK-11 "
                "§11.4.4 fail-closed after retries). The VectorDB is healthy "
                "(stage-1 similarity already returned the candidates); only the "
                "create-time LLM assessment failed. Story creation is BLOCKED "
                "fail-closed (FK-21 §21.4.3) -- no dummy verdict, no "
                f"PASS-when-in-doubt. Cause: {exc}"
            ) from exc
        return self._collapse_to_binary(result)

    @staticmethod
    def _collapse_to_binary(
        result: StructuredEvaluatorResult,
    ) -> StructuredEvaluatorResult:
        """Collapse the verdict to binary PASS/FAIL (FK-21 §21.4.1 Schritt 3).

        An unambiguous ``PASS`` is returned unchanged. ANY other aggregated
        verdict (the hard ``FAIL`` or the ambiguous ``PASS_WITH_CONCERNS``)
        becomes a blocking ``FAIL`` so the create-time conflict gate is
        fail-closed on ambiguity (story.md §2.1.5: no "PASS when in doubt"). When
        a ``PASS_WITH_CONCERNS`` is promoted, its concern findings are re-stamped
        to BLOCKING so the verdict and the findings stay consistent (a blocking
        verdict cannot carry only MINOR findings).

        Args:
            result: The raw structured-evaluator result (possibly ternary).

        Returns:
            The result with a BINARY verdict (``PASS`` or ``FAIL``).
        """
        if result.verdict is LlmVerdict.PASS:
            return result
        if result.verdict is LlmVerdict.FAIL:
            return result
        # PASS_WITH_CONCERNS -> blocking FAIL (fail-closed on ambiguity). Promote
        # the concern findings to BLOCKING so the model stays consistent.
        promoted_findings = tuple(
            f
            if f.severity is Severity.BLOCKING
            else Finding(
                layer=f.layer,
                check=f.check,
                severity=Severity.BLOCKING,
                message=(
                    f"[create-time conflict gate: ambiguity treated as conflict] "
                    f"{f.message}"
                ),
                trust_class=f.trust_class,
            )
            for f in result.findings
        )
        if not promoted_findings:
            # Defensive: a concern verdict with no findings cannot describe a
            # real outcome; still fail-closed with an explicit conflict finding.
            promoted_findings = (
                Finding(
                    layer=ReviewerRole.STORY_CREATION_REVIEW.value,
                    check="conflict_assessment",
                    severity=Severity.BLOCKING,
                    message=(
                        "create-time conflict gate: ambiguous PASS_WITH_CONCERNS "
                        "verdict treated as a conflict (fail-closed on ambiguity)."
                    ),
                    trust_class=TrustClass.VERIFIED_LLM,
                ),
            )
        return result.model_copy(
            update={"verdict": LlmVerdict.FAIL, "findings": promoted_findings}
        )


__all__ = [
    "CreateScopePromptMaterializer",
    "CreateTimeConflictAdjudicationError",
    "CreateTimeConflictAdjudicator",
]
