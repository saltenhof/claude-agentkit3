"""Create-time conflict assessment, run where the evaluator lives (FK-21 §21.4.1).

FK-21 §21.4.1 Schritt 3 is an **LLM evaluation**: role ``story_creation_review``,
prompt template ``vectordb-conflict``, single check ``conflict_assessment``,
binary outcome ``PASS`` (no conflict) / ``FAIL`` (duplicate / overlap). It is not
a second evaluator path -- role, check-id whitelist and template have always been
registered in this bounded context (``roles.ROLE_TEMPLATE``,
``stage_registry.check_origins.STORY_CREATION_REVIEW_CHECK_IDS``). Until AG3-241
the machinery that *runs* it lived on the developer machine: the edge held
``HubLlmClient``, ``StructuredEvaluator`` and the prompt materializer as plain
Python symbols and evaluated its own story. This module is that machinery, on the
side that owns it.

Two things travel together here because they are one indivisible act:

* :class:`CreateScopePromptMaterializer` resolves the ``vectordb-conflict``
  template through the pinned/bootstrap prompt bundle (FK-44 §44.4.2 -- the SAME
  bundle source the execution-scoped path uses, never a loose-file read) WITHOUT
  a live ``StoryContext`` / ``run_id`` / run-pin / story directory. None of those
  exist before the story is created, and the execution-scoped
  ``PromptRuntimeMaterializer`` requires all of them.
* :class:`CreateTimeConflictAdjudicator` reuses the UNCHANGED
  :class:`StructuredEvaluator` over the FK-65 / FK-11 ``LlmClient`` transport and
  collapses the aggregated verdict to binary.

**Why the collapse is not a simplification.** The shared aggregation can return
``PASS_WITH_CONCERNS`` -- an ambiguous candidate the model flagged without
classifying it as a hard duplicate. The single downstream consumer treats only
``FAIL`` as a conflict, so an ambiguous verdict would slip through as "no
conflict". An unambiguous ``PASS`` stays ``PASS``; everything else becomes a
blocking ``FAIL``. The execution-scoped QA/review aggregation is untouched.

Source:
  - FK-21 §21.4.1 Schritt 3 -- the LLM conflict assessment (binary PASS/FAIL)
  - FK-21 §21.4.3 -- fail-closed, no soft fallback
  - FK-34 / FK-11 §11.5.1 -- StructuredEvaluator + LlmClient (the ONE mechanic)
  - FK-44 §44.4.2 -- prompt resolution via the pinned bundle
  - FK-75 §75.3 -- the role->pool routing owner is the config, not the transport
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast, get_args

from agentkit.backend.exceptions import ProjectError
from agentkit.backend.prompt_runtime.resources import (
    load_prompt_template,
    prompt_template_sha256,
)
from agentkit.backend.verify_system.llm_evaluator.bundle import ReviewBundle
from agentkit.backend.verify_system.llm_evaluator.llm_client import LlmClientError
from agentkit.backend.verify_system.llm_evaluator.roles import LlmVerdict, ReviewerRole
from agentkit.backend.verify_system.llm_evaluator.structured_evaluator import (
    StructuredEvaluator,
    StructuredEvaluatorError,
    template_name_for_role,
)
from agentkit.integration_clients.multi_llm_hub.entities import HubBackendName
from agentkit_wire.verify_system import (
    ConflictVerdict,
    StoryConflictAssessmentRequest,
    StoryConflictAssessmentResponse,
)

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.backend.config.models import ProjectConfig
    from agentkit.backend.verify_system.llm_evaluator.llm_client import LlmClient
    from agentkit.backend.verify_system.llm_evaluator.structured_evaluator import (
        _PromptMaterializer,
    )


class CreateScopeConflictUnavailableError(Exception):
    """Fail-closed: the create-time LLM conflict assessment could not run.

    Raised when no create-time pool is configured, when the FK-65 / FK-11 LLM
    transport (or the create-scope prompt resolution) is unavailable, or when the
    model output cannot be parsed into a verdict after the evaluator's fail-closed
    retries. It carries no dummy verdict -- there is no "PASS when in doubt".
    """


class CreateScopePromptMaterializer:
    """Resolve the conflict-assessment prompt with NO story context / run-pin.

    Satisfies the ``_PromptMaterializer`` *surface* consumed by
    :class:`StructuredEvaluator` (``context_for`` + ``render``) but returns
    ``None`` for the story-context slot: the evaluator treats that value as an
    opaque pass-through token (it hands it straight back into ``render`` and never
    inspects it), so no ``StoryContext`` is needed. The execution-scoped
    materializer is left completely untouched.

    Attributes:
        _project_root: Optional project root used ONLY to resolve the
            project-pinned prompt-bundle binding (FK-44 §44.3). ``None`` -> the
            internal bootstrap bundle. No ``StoryContext`` is derived from it.
    """

    def __init__(self, *, project_root: Path | None = None) -> None:
        """Initialise the create-scope materializer.

        Args:
            project_root: Optional target-project root for the project-pinned
                prompt bundle binding. ``None`` uses the internal bootstrap
                bundle.
        """
        self._project_root = project_root

    def context_for(self, bundle: ReviewBundle) -> tuple[None, str]:
        """Return ``(None, story_id)`` for the create-scope evaluation.

        Args:
            bundle: The review bundle carrying the draft display-id.

        Returns:
            ``(None, bundle.story_id)``.
        """
        return None, bundle.story_id

    def render(
        self,
        role: ReviewerRole,
        ctx: None,
        story_id: str,
        template_override: str | None = None,
    ) -> tuple[str, str]:
        """Resolve ``(prompt_text, template_sha256)`` from the pinned bundle.

        Args:
            role: The reviewer role; selects the template when
                ``template_override`` is ``None`` (here: ``vectordb-conflict``).
            ctx: Always ``None`` in create scope (the opaque pass-through token).
            story_id: The draft display-id used for the ``{story_id}`` placeholder.
            template_override: Optional explicit template name (unused on the
                create-scope path; kept for surface fidelity).

        Returns:
            ``(prompt_text, template_sha256)``.

        Raises:
            LlmClientError: When the prompt bundle / template cannot be resolved
                (fail-closed: the assessment cannot proceed without a verified
                prompt).
        """
        del ctx  # No story context at create time (opaque pass-through token).
        template_name = (
            template_override
            if template_override is not None
            else template_name_for_role(role)
        )
        try:
            template_text = load_prompt_template(
                template_name, project_root=self._project_root
            )
            template_sha256 = prompt_template_sha256(
                template_name, project_root=self._project_root
            )
        except ProjectError as exc:
            raise LlmClientError(
                "create-scope prompt resolution failed for template "
                f"{template_name!r} (FK-44 §44.4.2 fail-closed): {exc}"
            ) from exc
        prompt_text = template_text.replace("{story_id}", story_id)
        # The sha256 stays the digest of the canonical (un-substituted) template
        # bytes (FK-44 §44.6) -- it matches the execution-scoped audit hash.
        return prompt_text, template_sha256


class CreateTimeConflictAdjudicator:
    """Runs the FK-21 §21.4.1 Schritt 3 conflict assessment in create scope."""

    def __init__(
        self,
        llm_client: LlmClient,
        *,
        project_root: Path | None = None,
    ) -> None:
        """Initialise the adjudicator over the real LLM transport.

        Args:
            llm_client: The FK-65 / FK-11 LLM transport port (the SAME
                ``LlmClient`` the execution-scoped Layer-2 evaluations use).
            project_root: Optional target-project root used ONLY to resolve the
                project-pinned prompt bundle binding (FK-44 §44.3).
        """
        materializer = CreateScopePromptMaterializer(project_root=project_root)
        # The StructuredEvaluator is reused UNCHANGED. No ArtifactManager and no
        # event emitter is wired: create scope has no run-pinned artifact store,
        # so the prompt-audit persistence skips cleanly (run_id stays None below).
        # The cast records the intentional create-scope narrowing of the
        # story-context slot without weakening the execution-scoped Protocol.
        self._evaluator = StructuredEvaluator(
            llm_client, cast("_PromptMaterializer", materializer)
        )

    def assess(
        self, request: StoryConflictAssessmentRequest
    ) -> StoryConflictAssessmentResponse:
        """Adjudicate one create-time conflict assessment.

        Args:
            request: The draft story plus its above-threshold similarity
                candidates.

        Returns:
            The BINARY verdict (``PASS`` -- no conflict, ``FAIL`` -- duplicate,
            overlap or ambiguity).

        Raises:
            CreateScopeConflictUnavailableError: When the LLM transport, the
                create-scope prompt resolution or the model output cannot produce
                a usable verdict -- fail-closed, never a dummy verdict.
        """
        bundle = build_conflict_bundle(request)
        try:
            # run_id stays None: at create time there is no run-pin, so the
            # prompt-audit envelope skips cleanly. The assessment itself is fully
            # performed -- there is no degraded path.
            result = self._evaluator.evaluate(
                ReviewerRole.STORY_CREATION_REVIEW,
                bundle,
                None,
                request_round(),
                run_id=None,
            )
        except LlmClientError as exc:
            raise CreateScopeConflictUnavailableError(
                "create-time conflict adjudication (FK-21 §21.4.1 Schritt 3) could "
                "not run: the LLM transport or create-scope prompt resolution is "
                "unavailable. The VectorDB is healthy (stage-1 similarity already "
                "returned the candidates); only the create-time LLM assessment "
                f"failed. Cause: {exc}"
            ) from exc
        except StructuredEvaluatorError as exc:
            raise CreateScopeConflictUnavailableError(
                "create-time conflict adjudication (FK-21 §21.4.1 Schritt 3) could "
                "not run: the create-time LLM produced malformed / schema-invalid "
                "output that could not be parsed into a conflict verdict (FK-11 "
                f"§11.4.4 fail-closed after retries). Cause: {exc}"
            ) from exc
        # PASS_WITH_CONCERNS is ambiguity, and ambiguity is a conflict here.
        verdict = (
            ConflictVerdict.PASS
            if result.verdict is LlmVerdict.PASS
            else ConflictVerdict.FAIL
        )
        return StoryConflictAssessmentResponse(verdict=verdict)


def request_round() -> int:
    """Return the QA-cycle round of a create-time assessment.

    There is exactly one: the gate runs before the story exists, so there is no
    remediation round it could be the second of.

    Returns:
        Always ``1``.
    """
    return 1


def build_conflict_bundle(request: StoryConflictAssessmentRequest) -> ReviewBundle:
    """Build the evaluator bundle carrying ``new_story`` + ``candidates``.

    Args:
        request: The wire request of the create-time conflict assessment.

    Returns:
        The :class:`ReviewBundle` handed to the shared structured evaluator.
    """
    candidate_lines = [
        f"- {candidate.story_id} (score={candidate.score:.3f}): "
        f"{candidate.title} -- {candidate.snippet}"
        for candidate in request.candidates
    ]
    return ReviewBundle(
        story_id=request.story_id,
        story_brief_excerpt=request.story_description,
        acceptance_criteria=[],
        diff_summary=(
            f"{len(request.candidates)} similarity candidate(s) above threshold"
        ),
        diff_content="## Candidates\n" + "\n".join(candidate_lines),
        concept_refs=[candidate.story_id for candidate in request.candidates],
        previous_findings=None,
        qa_cycle_round=request_round(),
    )


class _ConfigRolePoolResolver:
    """Config-faithful ``RolePoolResolver`` for the create-time conflict role.

    Implements the FK-75 §75.3 ``RolePoolResolver`` surface by reading the
    ``pipeline.llm_roles.story_creation_review`` pool assignment from the target
    project's config. The routing OWNER is the config, not the LLM transport.
    This resolver serves ONLY the create-time role; any other role is rejected
    fail-closed so the create-scope transport cannot be reused for an execution
    role.

    Attributes:
        _pool: The validated ``story_creation_review`` pool name.
    """

    def __init__(self, *, story_creation_review_pool: HubBackendName) -> None:
        """Initialise the resolver with the validated create-time pool.

        Args:
            story_creation_review_pool: The validated Hub pool name assigned to
                the ``story_creation_review`` role.
        """
        self._pool = story_creation_review_pool

    def resolve(self, role: str) -> HubBackendName:
        """Resolve the ``story_creation_review`` role to its configured pool.

        Args:
            role: The reviewer role wire-string.

        Returns:
            The configured pool name for the create-time role.

        Raises:
            LlmClientError: When ``role`` is not the create-time role
                (fail-closed: no default pool, FK-75 §75.3).
        """
        if role != ReviewerRole.STORY_CREATION_REVIEW.value:
            raise LlmClientError(
                "create-time RolePoolResolver only serves role "
                f"'{ReviewerRole.STORY_CREATION_REVIEW.value}'; got {role!r} "
                "(fail-closed, no default pool, FK-75 §75.3)."
            )
        return self._pool


def build_create_time_conflict_adjudicator(
    project_config: ProjectConfig,
    *,
    project_root: Path | None = None,
) -> CreateTimeConflictAdjudicator:
    """Build the real create-time adjudicator from the project config.

    Args:
        project_config: The loaded target-project config carrying the
            ``pipeline.llm_roles`` role->pool assignments.
        project_root: Optional target-project root for the project-pinned prompt
            bundle binding (FK-44 §44.3).

    Returns:
        A wired :class:`CreateTimeConflictAdjudicator`.

    Raises:
        CreateScopeConflictUnavailableError: When the config assigns no valid
            ``story_creation_review`` pool. An above-threshold candidate set then
            BLOCKS the create (FK-21 §21.4.3 / NO ERROR BYPASSING) rather than
            passing an unadjudicated conflict -- never a silent pass.
    """
    llm_roles = project_config.pipeline.llm_roles
    pool_name = None if llm_roles is None else llm_roles.story_creation_review
    if pool_name is None or pool_name not in get_args(HubBackendName):
        raise CreateScopeConflictUnavailableError(
            "story-creation stage-2 conflict adjudication has no configured LLM "
            "pool: pipeline.llm_roles.story_creation_review is unset or names a "
            "pool the Hub does not know (FK-75 §75.3, no default pool). "
            "Above-threshold similarity candidates cannot be adjudicated, so the "
            "create is BLOCKED fail-closed (FK-21 §21.4.3)."
        )

    from agentkit.backend.verify_system.llm_evaluator.llm_client import HubLlmClient
    from agentkit.integration_clients.multi_llm_hub.client import HubClient
    from agentkit.integration_clients.multi_llm_hub.config import (
        load_multi_llm_hub_config,
    )

    hub = HubClient(load_multi_llm_hub_config().base_url)
    resolver = _ConfigRolePoolResolver(
        # pool_name was validated against get_args(HubBackendName) above; the cast
        # records that runtime narrowing (a config ``str`` cannot be narrowed to
        # the Literal statically).
        story_creation_review_pool=cast("HubBackendName", pool_name),
    )
    llm_client = HubLlmClient(hub, resolver, owner="agentkit-story-creation")
    return CreateTimeConflictAdjudicator(llm_client, project_root=project_root)


def assess_story_conflict(
    request: StoryConflictAssessmentRequest,
    *,
    project_config: ProjectConfig,
    project_root: Path | None = None,
) -> StoryConflictAssessmentResponse:
    """Run one create-time conflict assessment end to end.

    Args:
        request: The draft story plus its above-threshold similarity candidates.
        project_config: The loaded target-project config.
        project_root: Optional target-project root for the prompt-bundle binding.

    Returns:
        The binary verdict.

    Raises:
        CreateScopeConflictUnavailableError: Fail-closed, when the assessment
            cannot be performed at all.
    """
    adjudicator = build_create_time_conflict_adjudicator(
        project_config, project_root=project_root
    )
    return adjudicator.assess(request)


__all__ = [
    "CreateScopeConflictUnavailableError",
    "CreateScopePromptMaterializer",
    "CreateTimeConflictAdjudicator",
    "assess_story_conflict",
    "build_conflict_bundle",
    "build_create_time_conflict_adjudicator",
    "request_round",
]
