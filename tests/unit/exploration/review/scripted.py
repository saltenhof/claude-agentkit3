"""Test doubles for the exploration-review stages -- mock ONLY at the LLM grenze.

The orchestration logic (``ExplorationReview`` + the three stage runners + the
real :class:`StructuredEvaluator` validation) is exercised against REAL
components. The only seam that is doubled is the LLM transport
(:class:`ScriptedLlmClient`) and the prompt materializer
(:class:`StubMaterializer`) -- the prompt-resource / run-scope boundary, which is
not orchestration logic. This matches the AG3-046 rule: real components +
tmp_path; mocks only at the LLM boundary, not the orchestration.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from agentkit.bootstrap.composition_root import build_artifact_manager
from agentkit.exploration.review.persistence import ArtifactReviewResultSink
from agentkit.verify_system.llm_evaluator.structured_evaluator import (
    DOC_FIDELITY_CHECK_IDS,
    SEMANTIC_REVIEW_CHECK_IDS,
    ReviewerRole,
    StructuredEvaluator,
)

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.exploration.review.persistence import ReviewResultSink
    from agentkit.story_context_manager.models import StoryContext
    from agentkit.verify_system.llm_evaluator.bundle import ReviewBundle
    from agentkit.verify_system.llm_evaluator.llm_client import LlmClient

#: The single check-id each exploration-review role expects (FK-34 §34.2.3/.4).
_ROLE_CHECK_ID = {
    ReviewerRole.DOC_FIDELITY: next(iter(DOC_FIDELITY_CHECK_IDS)),
    ReviewerRole.SEMANTIC_REVIEW: next(iter(SEMANTIC_REVIEW_CHECK_IDS)),
}


def _check_obj(check_id: str, status: str) -> dict[str, str]:
    """Build one base-check object for ``check_id`` + ``status``."""
    reason = "" if status == "PASS" else f"{check_id} did not hold"
    return {"check_id": check_id, "status": status, "reason": reason}


def _resolution_obj(finding_key: str, resolution: str) -> dict[str, str]:
    """Build one ``finding_resolution_*`` check object (FK-34 §34.9.4).

    Args:
        finding_key: The ``{layer}:{check}`` key of the resolved finding.
        resolution: ``fully_resolved`` | ``partially_resolved`` | ``not_resolved``.

    Returns:
        A check object whose ``check_id`` is ``finding_resolution_{key}`` and
        whose ``status`` is ``PASS`` for a clean resolution (a non-PASS status
        would need its own reason; resolution blocking is driven by the
        ``resolution`` field, not the status).
    """
    return {
        "check_id": f"finding_resolution_{finding_key}",
        "status": "PASS",
        "reason": f"{finding_key} resolution: {resolution}",
        "resolution": resolution,
    }


def _check_json(check_id: str, status: str) -> str:
    """Build a one-check LLM response array for ``check_id`` + ``status``."""
    return json.dumps([_check_obj(check_id, status)])


def _check_id_for_prompt(role: str, prompt: str) -> str:
    """Resolve the expected check-id from a conformance-aware prompt."""
    marker = "## Expected Check IDs"
    if marker in prompt:
        _, expected = prompt.rsplit(marker, maxsplit=1)
        parsed = json.loads(expected.strip())
        assert isinstance(parsed, list)
        assert len(parsed) == 1
        value = parsed[0]
        assert isinstance(value, str)
        return value
    return _ROLE_CHECK_ID[ReviewerRole(role)]


class ScriptedLlmClient:
    """A ``LlmClient`` double returning scripted verdicts per role (LLM grenze).

    Each ``complete`` call pops the next scripted verdict for the requested role
    and returns a single-check JSON response the real
    :class:`StructuredEvaluator` then validates. This doubles ONLY the LLM
    transport; all schema validation / aggregation runs for real.
    """

    def __init__(
        self,
        *,
        doc_fidelity: list[str] | None = None,
        semantic_review: list[str] | None = None,
    ) -> None:
        """Initialize the scripted client.

        Args:
            doc_fidelity: Ordered verdict wire-strings for the doc-fidelity role
                (e.g. ``["PASS"]`` / ``["FAIL"]``).
            semantic_review: Ordered verdict wire-strings for the semantic-review
                role (one per design-review round).
        """
        self._scripts: dict[str, list[str]] = {
            ReviewerRole.DOC_FIDELITY.value: list(doc_fidelity or []),
            ReviewerRole.SEMANTIC_REVIEW.value: list(semantic_review or []),
        }
        self.calls: list[str] = []

    def complete(self, *, role: str, prompt: str) -> str:
        """Return the next scripted single-check JSON response for ``role``.

        Args:
            role: The reviewer-role wire-string.
            prompt: The materialized prompt (unused; the verdict is scripted).

        Returns:
            A one-check JSON array string for the role's single check-id.

        Raises:
            AssertionError: If the role's script is exhausted (a test wired too
                few verdicts -- surfaces an orchestration bug rather than hiding
                it behind a default PASS).
        """
        self.calls.append(role)
        script = self._scripts[role]
        assert script, f"no scripted verdict left for role {role!r}"
        verdict = script.pop(0)
        check_id = _check_id_for_prompt(role, prompt)
        return _check_json(check_id, verdict)


class ResolutionScriptedLlmClient:
    """A ``semantic_review`` ``LlmClient`` double that scripts resolution checks.

    Used for the design-review reviser path (FK-34 §34.9): on the revised round
    the response must additionally carry the ``finding_resolution_*`` check for
    the prior-round finding. Each script entry is the base verdict plus the
    resolution status to emit for the round-1 ``semantic_review:systemic_adequacy``
    finding (``None`` => emit only the base check, e.g. the first round).
    """

    def __init__(
        self, rounds: list[tuple[str, str | None]]
    ) -> None:
        """Initialize the scripted client.

        Args:
            rounds: Ordered ``(base_verdict, resolution_or_none)`` per round. The
                resolution (when given) targets the round-1 finding key
                ``semantic_review:systemic_adequacy``.
        """
        self._rounds = list(rounds)
        self.calls: list[str] = []

    def complete(self, *, role: str, prompt: str) -> str:
        """Return the next scripted (base [+ resolution]) JSON response.

        Args:
            role: The reviewer-role wire-string (must be ``semantic_review``).
            prompt: The materialized prompt (unused; scripted).

        Returns:
            A JSON array with the base check and, when scripted, the
            finding-resolution check for the round-1 finding.

        Raises:
            AssertionError: If the script is exhausted (surfaces a wiring bug).
        """
        del prompt
        self.calls.append(role)
        assert self._rounds, f"no scripted round left for role {role!r}"
        verdict, resolution = self._rounds.pop(0)
        check_id = _ROLE_CHECK_ID[ReviewerRole(role)]
        checks = [_check_obj(check_id, verdict)]
        if resolution is not None:
            checks.append(
                _resolution_obj(f"{role}:{check_id}", resolution)
            )
        return json.dumps(checks)


class StubMaterializer:
    """A ``_PromptMaterializer`` double (prompt-resource boundary, not the LLM).

    Returns a fixed prompt text + template hash; the real evaluator still parses
    and validates the (scripted) LLM response.
    """

    def __init__(self, ctx: StoryContext) -> None:
        """Initialize with the story context the bundle must match."""
        self._ctx = ctx

    def context_for(self, bundle: ReviewBundle) -> tuple[StoryContext, str]:
        """Return ``(ctx, story_id)`` (no run-scope resolution in the stub)."""
        del bundle
        return self._ctx, self._ctx.story_id

    def render(
        self, role: ReviewerRole, ctx: StoryContext, story_id: str
    ) -> tuple[str, str]:
        """Return a fixed ``(prompt_text, template_sha256)``."""
        del ctx, story_id
        return f"PROMPT[{role.value}]", "0" * 64


def build_scripted_evaluator(
    ctx: StoryContext, client: LlmClient
) -> StructuredEvaluator:
    """Build a REAL ``StructuredEvaluator`` over the scripted LLM + stub prompt."""
    return StructuredEvaluator(client, StubMaterializer(ctx))


def build_real_sink(story_dir: Path) -> ReviewResultSink:
    """Build a REAL ``ArtifactReviewResultSink`` over a tmp_path artifact store."""
    return ArtifactReviewResultSink(build_artifact_manager(story_dir))


__all__ = [
    "ResolutionScriptedLlmClient",
    "ScriptedLlmClient",
    "StubMaterializer",
    "build_real_sink",
    "build_scripted_evaluator",
]
