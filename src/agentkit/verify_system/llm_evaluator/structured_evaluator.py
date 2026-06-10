"""StructuredEvaluator -- one fail-closed LLM evaluation per role (FK-34 / FK-11 §11.4).

A :class:`StructuredEvaluator` runs *one* role of the Layer-2 LLM evaluation
(FK-27 §27.5): it materializes the role's prompt template via
``PromptRuntime.materialize_prompt`` (FK-44 §44.4.2 -- never a direct resource
read), sends it together with the serialized
:class:`~agentkit.verify_system.llm_evaluator.bundle.ReviewBundle` through the
:class:`~agentkit.verify_system.llm_evaluator.llm_client.LlmClient` port, and
validates the JSON response fail-closed against the role's expected check-id
whitelist (FK-34 §34.5.1). An invalid structure raises
:class:`StructuredEvaluatorError` -- never a silent skip or a default PASS.

The three roles and their check-id whitelists are the concept SSOT:

* ``qa_review``       -- 12 checks (FK-27 §27.5.2 / FK-38 §38.2)
* ``semantic_review`` -- 1 check ``systemic_adequacy`` (FK-34 §34.2.3)
* ``doc_fidelity``    -- 1 check ``impl_fidelity`` (FK-34 §34.2.4)

In remediation mode (``qa_cycle_round > 1``) the response may additionally
carry ``finding_resolution_{finding_id}`` checks (FK-34 §34.9.5); each maps to
a :class:`~agentkit.verify_system.remediation.finding_resolution.FindingResolutionStatus`
(AG3-041) in :attr:`StructuredEvaluatorResult.finding_resolutions`.

Quelle:
  - FK-34 §34.2 -- drei Rollen, Antwort-Schema, Aggregation
  - FK-34 §34.5.1 -- Fehlerbehandlung (fail-closed, kein valides JSON -> FAIL)
  - FK-34 §34.9 / DK-04 §4.6 -- Finding-Resolution im Remediation-Modus
  - FK-27 §27.5.2 -- die 12 qa_review Check-IDs
  - FK-44 §44.4.2 -- Prompt-Lookup via PromptRuntime.materialize_prompt
"""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import TYPE_CHECKING, Final, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, ValidationError

from agentkit.verify_system.errors import VerifySystemError
from agentkit.verify_system.llm_evaluator.llm_client import LlmClientError
from agentkit.verify_system.protocols import Finding, Severity, TrustClass
from agentkit.verify_system.remediation.finding_resolution import (
    FindingKey,
    FindingResolutionStatus,
    finding_key,
)

if TYPE_CHECKING:
    from agentkit.story_context_manager.models import StoryContext
    from agentkit.verify_system.llm_evaluator.bundle import ReviewBundle
    from agentkit.verify_system.llm_evaluator.llm_client import LlmClient

#: Prefix of a remediation finding-resolution check-id (FK-34 §34.9.5).
_FINDING_RESOLUTION_PREFIX: Final[str] = "finding_resolution_"

#: Separator between ``layer`` and ``check`` inside a finding-resolution id.
#: The resolution check-id is ``finding_resolution_{layer}:{check}`` so it
#: round-trips to the canonical AG3-041 ``FindingKey = (layer, check)`` -- the
#: ONE resolution-map key (E5). ``layer`` (a role value, e.g. ``qa_review``)
#: and ``check`` (e.g. ``ac_fulfilled``) never contain ``:``.
_FINDING_KEY_SEP: Final[str] = ":"

#: A ``layer:check`` key splits into exactly this many parts.
_FINDING_KEY_PARTS: Final[int] = 2


def _finding_resolution_id(finding: Finding) -> str:
    """Return the ``{layer}:{check}`` id encoding a finding's canonical key.

    Args:
        finding: The previous-round finding to encode.

    Returns:
        ``"{layer}:{check}"`` -- the suffix of the ``finding_resolution_*``
        check-id, decodable back to the AG3-041 ``FindingKey``.
    """
    layer, check = finding_key(finding)
    return f"{layer}{_FINDING_KEY_SEP}{check}"


def _parse_finding_resolution_key(suffix: str) -> FindingKey:
    """Decode a ``finding_resolution_`` suffix into a ``FindingKey``.

    Args:
        suffix: The id suffix after the ``finding_resolution_`` prefix, of the
            form ``{layer}:{check}``.

    Returns:
        The ``(layer, check)`` :data:`FindingKey`.

    Raises:
        StructuredEvaluatorError: If the suffix is not exactly ``layer:check``
            (fail-closed: no malformed resolution id silently accepted).
    """
    parts = suffix.split(_FINDING_KEY_SEP)
    if len(parts) != _FINDING_KEY_PARTS or not parts[0] or not parts[1]:
        msg = (
            f"finding-resolution id suffix {suffix!r} is not a valid "
            f"'layer:check' key (FK-34 §34.9.5 fail-closed)."
        )
        raise StructuredEvaluatorError(msg)
    return (parts[0], parts[1])


class LlmVerdict(StrEnum):
    """LLM-domain verdict of a single evaluation role (FK-34 §34.2).

    Domain values that the ``ProducerRegistry.map_llm_status_to_envelope_status``
    maps onto ``EnvelopeStatus`` (FK-71 §71.2). ``PASS_WITH_CONCERNS`` does not
    block in the regular checks (FK-05-166) but is blocking for
    finding-resolution checks (FK-34 §34.9.4).

    Attributes:
        PASS: All checks passed.
        FAIL: At least one regular check failed (blocking, FK-05-164).
        PASS_WITH_CONCERNS: Passed with non-blocking concerns.
    """

    PASS = "PASS"
    FAIL = "FAIL"
    PASS_WITH_CONCERNS = "PASS_WITH_CONCERNS"


class ReviewerRole(StrEnum):
    """The three Layer-2 evaluation roles (FK-27 §27.5 / FK-34 §34.2).

    Attributes:
        QA_REVIEW: 12-check QA review (FK-27 §27.5.2).
        SEMANTIC_REVIEW: 1-check systemic-adequacy review (FK-34 §34.2.3).
        DOC_FIDELITY: 1-check implementation-fidelity review (FK-34 §34.2.4).
    """

    QA_REVIEW = "qa_review"
    SEMANTIC_REVIEW = "semantic_review"
    DOC_FIDELITY = "doc_fidelity"


#: The 12 canonical qa_review check-ids (FK-27 §27.5.2 / FK-34 §34.9.5).
#: SINGLE SOURCE OF TRUTH for the qa_review whitelist; the prompt template and
#: the contract test pin against these (no second list).
QA_REVIEW_CHECK_IDS: Final[frozenset[str]] = frozenset({
    "ac_fulfilled",
    "impl_fidelity",
    "scope_compliance",
    "impact_violation",
    "arch_conformity",
    "proportionality",
    "error_handling",
    "authz_logic",
    "silent_data_loss",
    "backward_compat",
    "observability",
    "doc_impact",
})

#: The single semantic_review check-id (FK-34 §34.2.3).
SEMANTIC_REVIEW_CHECK_IDS: Final[frozenset[str]] = frozenset({"systemic_adequacy"})

#: The single doc_fidelity check-id (FK-34 §34.2.4).
DOC_FIDELITY_CHECK_IDS: Final[frozenset[str]] = frozenset({"impl_fidelity"})

#: Role -> expected static check-id whitelist (FK-34 §34.9.5 base set per role).
_ROLE_CHECK_IDS: Final[dict[ReviewerRole, frozenset[str]]] = {
    ReviewerRole.QA_REVIEW: QA_REVIEW_CHECK_IDS,
    ReviewerRole.SEMANTIC_REVIEW: SEMANTIC_REVIEW_CHECK_IDS,
    ReviewerRole.DOC_FIDELITY: DOC_FIDELITY_CHECK_IDS,
}

#: Role -> logical prompt-template name (FK-44 §44.4.2 / story.md §2.1.1).
_ROLE_TEMPLATE: Final[dict[ReviewerRole, str]] = {
    ReviewerRole.QA_REVIEW: "qa-review",
    ReviewerRole.SEMANTIC_REVIEW: "qa-semantic-review",
    ReviewerRole.DOC_FIDELITY: "qa-doc-fidelity",
}

#: LLM resolution wire-string -> FindingResolutionStatus (FK-34 §34.9.4).
_RESOLUTION_WIRE: Final[dict[str, FindingResolutionStatus]] = {
    "fully_resolved": FindingResolutionStatus.FULLY_RESOLVED,
    "partially_resolved": FindingResolutionStatus.PARTIALLY_RESOLVED,
    "not_resolved": FindingResolutionStatus.NOT_RESOLVED,
}

#: LLM check-status -> finding severity for FAIL/PASS_WITH_CONCERNS checks.
#: PASS produces no finding. A FAIL maps to ``BLOCKING`` (not ``MAJOR``):
#: FK-33 §33.8.2 / FK-34 §34.2.5 require that **every** Layer-2 FAIL blocks the
#: Schicht-2 -> Schicht-3 gate HARD and *schwellenunabhaengig* ("jeder FAIL
#: blockiert, FK-05-164") -- NOT gated on ``max_major_findings``. A Layer-2
#: role is a *blocking stage* (FK-33 §33.7.2), so its FAIL maps to the
#: unconditional ``BLOCKING`` severity; the PolicyEngine (the single blocking
#: SSOT) blocks on any ``BLOCKING`` finding regardless of trust class or
#: threshold. ``PASS_WITH_CONCERNS`` is ``MINOR`` (never blocking; surfaced for
#: the policy engine + adversarial layer, FK-05-166).
_STATUS_SEVERITY: Final[dict[LlmVerdict, Severity]] = {
    LlmVerdict.FAIL: Severity.BLOCKING,
    LlmVerdict.PASS_WITH_CONCERNS: Severity.MINOR,
}


class StructuredEvaluatorError(VerifySystemError):
    """Raised when the LLM response is not a valid evaluation result (fail-closed).

    FK-34 §34.5.1: an unparseable or schema-violating response is a hard FAIL,
    never a silent skip. Covers non-JSON output, wrong top-level type, unknown
    check-ids, illegal status values, and (in remediation mode) a missing or
    invalid ``resolution`` field on a finding-resolution check.
    """


class CheckResult(BaseModel):
    """One check entry from the LLM response (FK-34 §34.2 / FK-11 §11.4).

    Attributes:
        check_id: The check identifier (must be in the role whitelist, or a
            ``finding_resolution_{id}`` id in remediation mode).
        status: ``PASS`` | ``FAIL`` | ``PASS_WITH_CONCERNS``.
        reason: One-line justification.
        description: Optional longer description (max 300 chars per FK-34).
        resolution: Only on ``finding_resolution_*`` checks: ``fully_resolved``
            | ``partially_resolved`` | ``not_resolved`` (FK-34 §34.9.4).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    check_id: str
    status: LlmVerdict
    reason: str = ""
    description: str = ""
    resolution: str | None = None


class LlmEvaluatorResponse(BaseModel):
    """The parsed LLM response: a list of check results (FK-34 §34.2).

    The wire format is a bare JSON array of check objects; this wrapper holds
    the parsed list. ``extra="forbid"`` is intentionally NOT applied to the
    individual array entries' container here -- entry-level strictness lives on
    :class:`CheckResult`.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    checks: tuple[CheckResult, ...]


class StructuredEvaluatorResult(BaseModel):
    """The validated outcome of one role's evaluation (story.md §2.1.1).

    Attributes:
        role: The evaluated role.
        verdict: Aggregated LLM verdict across the role's checks.
        findings: Findings derived from FAIL / PASS_WITH_CONCERNS checks.
        finding_resolutions: ``FindingKey -> FindingResolutionStatus`` map,
            keyed by the canonical AG3-041 ``(layer, check)`` identity (E5) so
            it feeds the ONE finding-resolution SSOT directly; populated only in
            remediation mode (FK-34 §34.9).
        raw_response_hash: SHA-256 over the raw LLM output (audit).
        template_sha256: SHA-256 of the materialized prompt template (audit).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    role: ReviewerRole
    verdict: LlmVerdict
    findings: tuple[Finding, ...]
    finding_resolutions: dict[FindingKey, FindingResolutionStatus]
    raw_response_hash: str
    template_sha256: str


class StructuredEvaluator:
    """Runs one fail-closed LLM evaluation role (FK-34 / FK-11 §11.4).

    Attributes are injected, not global: the
    :class:`~agentkit.verify_system.llm_evaluator.llm_client.LlmClient` port
    and the prompt materializer. The evaluator is pure apart from the injected
    LLM call and the prompt-runtime materialization side effect.
    """

    def __init__(
        self,
        llm_client: LlmClient,
        prompt_materializer: _PromptMaterializer,
    ) -> None:
        """Initialise the evaluator.

        Args:
            llm_client: The LLM transport port (FK-34 / FK-11 §11.5.1).
            prompt_materializer: A callable resolving ``(role, ctx) ->
                (prompt_text, template_sha256)`` via
                ``PromptRuntime.materialize_prompt`` (FK-44 §44.4.2). Injected
                so the evaluator never reaches into prompt-runtime sub-modules
                nor reads a resource file directly.
        """
        self._llm_client = llm_client
        self._materialize = prompt_materializer

    def evaluate(
        self,
        role: ReviewerRole,
        bundle: ReviewBundle,
        previous_findings: list[Finding] | None,
        qa_cycle_round: int,
        expected_check_ids: frozenset[str] | None = None,
        template_override: str | None = None,
    ) -> StructuredEvaluatorResult:
        """Evaluate one role against the review bundle (fail-closed).

        Args:
            role: The reviewer role to run.
            bundle: The immutable review input bundle.
            previous_findings: Prior-round findings (remediation context only);
                their identity is used to validate ``finding_resolution_*``
                check-ids. ``None`` / empty in the initial round.
            qa_cycle_round: 1-based QA-cycle round (``> 1`` => remediation).
            expected_check_ids: Override the role's default check-id whitelist.
            template_override: Use this logical template name instead of the
                role's default (FK-32 conformance levels use level-specific
                templates over the DOC_FIDELITY role; ``None`` => role default).

        Returns:
            The validated :class:`StructuredEvaluatorResult`.

        Raises:
            StructuredEvaluatorError: On an unparseable / schema-violating
                response, an unknown check-id, or an invalid resolution
                (fail-closed, FK-34 §34.5.1).
            LlmClientError: If the LLM transport fails (propagated; fail-closed).
        """
        ctx, story_id = self._materialize.context_for(bundle)
        prompt_text, template_sha256 = self._materialize.render(
            role, ctx, story_id, template_override
        )
        full_prompt = f"{prompt_text}\n\n## Review Bundle (JSON)\n{bundle.to_prompt_json()}"
        if expected_check_ids is not None:
            full_prompt = (
                f"{full_prompt}\n\n## Expected Check IDs\n"
                f"{json.dumps(sorted(expected_check_ids), ensure_ascii=False)}"
            )

        raw_response = self._llm_client.complete(role=role.value, prompt=full_prompt)
        if not raw_response.strip():
            raise LlmClientError(
                f"LlmClient returned empty completion for role={role.value!r} "
                "(FK-34 §34.5.1 fail-closed)."
            )

        response = self._parse_response(raw_response, role)
        mandatory, resolution_required = self._required_check_ids(
            role, previous_findings, qa_cycle_round, expected_check_ids
        )
        self._validate_completeness(role, response, mandatory, resolution_required)
        findings, resolutions, verdict = self._aggregate(role, response)
        raw_hash = hashlib.sha256(raw_response.encode("utf-8")).hexdigest()
        return StructuredEvaluatorResult(
            role=role,
            verdict=verdict,
            findings=tuple(findings),
            finding_resolutions=resolutions,
            raw_response_hash=raw_hash,
            template_sha256=template_sha256,
        )

    @staticmethod
    def _parse_response(
        raw_response: str, role: ReviewerRole
    ) -> LlmEvaluatorResponse:
        """Parse the raw LLM text into a validated response (fail-closed)."""
        try:
            parsed = json.loads(raw_response)
        except json.JSONDecodeError as exc:
            msg = f"LLM response for role={role.value!r} is not valid JSON (FK-34 §34.5.1 fail-closed): {exc}"
            raise StructuredEvaluatorError(msg) from exc
        if not isinstance(parsed, list):
            msg = (
                f"LLM response for role={role.value!r} must be a JSON array of "
                f"check objects (FK-34 §34.2); got {type(parsed).__name__}."
            )
            raise StructuredEvaluatorError(msg)
        try:
            return LlmEvaluatorResponse(checks=tuple(parsed))
        except ValidationError as exc:
            msg = f"LLM response for role={role.value!r} violates the CheckResult schema (FK-34 §34.2 fail-closed): {exc}"
            raise StructuredEvaluatorError(msg) from exc

    @staticmethod
    def _required_check_ids(
        role: ReviewerRole,
        previous_findings: list[Finding] | None,
        qa_cycle_round: int,
        expected_check_ids: frozenset[str] | None,
    ) -> tuple[frozenset[str], frozenset[str]]:
        """Return ``(mandatory_base, required_resolution)`` check-ids for the round.

        FK-34 §34.9.5: the static base set per role (12 / 1 / 1) is ALWAYS
        mandatory. In remediation mode (``qa_cycle_round > 1`` with previous
        findings) every previous finding *belonging to this role* additionally
        requires its ``finding_resolution_{layer}:{check}`` check (FK-34 §34.9:
        "Bewerte pro Finding, ob es resolved ist"). A finding belongs to the
        role that produced it (``finding.layer == role.value``) -- the
        ``qa_review`` evaluator resolves ``qa_review`` findings, the
        ``semantic_review`` evaluator its own, etc. Both sets are mandatory and
        exact-match enforced by :meth:`_validate_completeness` (fail-closed).
        """
        mandatory = expected_check_ids if expected_check_ids is not None else _ROLE_CHECK_IDS[role]
        if qa_cycle_round < 2 or not previous_findings:
            return mandatory, frozenset()
        resolution_ids = frozenset(
            f"{_FINDING_RESOLUTION_PREFIX}{_finding_resolution_id(f)}"
            for f in previous_findings
            if f.layer == role.value
        )
        return mandatory, resolution_ids

    @staticmethod
    def _validate_completeness(
        role: ReviewerRole,
        response: LlmEvaluatorResponse,
        mandatory: frozenset[str],
        resolution_required: frozenset[str],
    ) -> None:
        """Enforce exact, fail-closed check coverage (FK-34 §34.2 / §34.9.5).

        Rejects (raising :class:`StructuredEvaluatorError`) any response that is
        not an *exact* cover of the required checks -- no silent PASS on an
        empty, partial, padded or duplicate array (E2):

        * duplicate ``check_id`` (same id twice),
        * a missing mandatory base check (e.g. fewer than 12 for qa_review),
        * a missing required finding-resolution check (remediation mode),
        * an unexpected/unknown ``check_id`` (outside base + required
          resolution).

        Args:
            role: The evaluated role (for the error message).
            response: The parsed response.
            mandatory: The role's mandatory base check-ids (12 / 1 / 1).
            resolution_required: The finding-resolution ids required this round.
        """
        seen: list[str] = [c.check_id for c in response.checks]
        seen_set = set(seen)
        duplicates = sorted({cid for cid in seen if seen.count(cid) > 1})
        if duplicates:
            msg = (
                f"LLM response for role={role.value!r} has duplicate check_id(s) "
                f"{duplicates} (FK-34 §34.2 fail-closed; each check exactly once)."
            )
            raise StructuredEvaluatorError(msg)
        required = mandatory | resolution_required
        missing = sorted(required - seen_set)
        unexpected = sorted(seen_set - required)
        if missing or unexpected:
            msg = (
                f"LLM response for role={role.value!r} is not an exact cover of "
                f"the required checks (FK-34 §34.2/§34.9.5 fail-closed). "
                f"missing={missing} unexpected={unexpected} "
                f"required={sorted(required)}."
            )
            raise StructuredEvaluatorError(msg)

    def _aggregate(
        self,
        role: ReviewerRole,
        response: LlmEvaluatorResponse,
    ) -> tuple[list[Finding], dict[FindingKey, FindingResolutionStatus], LlmVerdict]:
        """Aggregate the checks into findings + resolutions + verdict.

        Exact coverage / no-dups / no-unknown-ids are already enforced by
        :meth:`_validate_completeness` before this runs, so this only maps each
        check. A non-PASS regular check additionally requires a non-empty
        ``reason`` (E2 fail-closed: no unjustified FAIL / PASS_WITH_CONCERNS).
        """
        findings: list[Finding] = []
        resolutions: dict[FindingKey, FindingResolutionStatus] = {}
        has_blocking = False
        has_concern = False
        for check in response.checks:
            if check.check_id.startswith(_FINDING_RESOLUTION_PREFIX):
                status = self._handle_resolution(role, check, resolutions)
                if status is not FindingResolutionStatus.FULLY_RESOLVED:
                    # FK-34 §34.9.4: not_resolved AND partially_resolved are
                    # blocking. Emit a BLOCKING finding (the policy engine acts
                    # on findings) regardless of the LLM check.status, because a
                    # partially_resolved reports PASS_WITH_CONCERNS yet still
                    # blocks hard (FK-34 §34.9.4 Sonderregel).
                    has_blocking = True
                    findings.append(self._resolution_finding(role, check, status))
                continue
            self._require_reason(role, check)
            if check.status is LlmVerdict.FAIL:
                has_blocking = True
                findings.append(self._finding_from_check(role, check))
            elif check.status is LlmVerdict.PASS_WITH_CONCERNS:
                has_concern = True
                findings.append(self._finding_from_check(role, check))
        return findings, resolutions, _verdict(has_blocking, has_concern)

    @staticmethod
    def _require_reason(role: ReviewerRole, check: CheckResult) -> None:
        """Enforce a non-empty ``reason`` on a non-PASS check (E2, fail-closed).

        FK-34 §34.2: every FAIL / PASS_WITH_CONCERNS check carries a
        justification ("reason"). A blank/whitespace-only reason on a
        non-PASS check is rejected so the verdict can never be a blocking /
        concern outcome without a recorded reason.
        """
        if check.status is LlmVerdict.PASS:
            return
        if not check.reason.strip():
            msg = (
                f"check {check.check_id!r} for role={role.value!r} has status "
                f"{check.status.value!r} but an empty 'reason' (FK-34 §34.2 "
                "fail-closed: every FAIL/PASS_WITH_CONCERNS must be justified)."
            )
            raise StructuredEvaluatorError(msg)

    def _handle_resolution(
        self,
        role: ReviewerRole,
        check: CheckResult,
        resolutions: dict[FindingKey, FindingResolutionStatus],
    ) -> FindingResolutionStatus:
        """Validate + record a finding-resolution check (fail-closed).

        The resolution is keyed by the canonical AG3-041 ``FindingKey``
        ``(layer, check)`` decoded from the ``finding_resolution_{layer}:{check}``
        id (E5) so it feeds the ONE finding-resolution SSOT, and a non-PASS
        resolution additionally requires a non-empty ``reason``.
        """
        if check.resolution is None or check.resolution not in _RESOLUTION_WIRE:
            msg = (
                f"finding-resolution check {check.check_id!r} for "
                f"role={role.value!r} has invalid resolution "
                f"{check.resolution!r} (FK-34 §34.9.4 fail-closed). "
                f"Allowed: {sorted(_RESOLUTION_WIRE)}"
            )
            raise StructuredEvaluatorError(msg)
        self._require_reason(role, check)
        suffix = check.check_id[len(_FINDING_RESOLUTION_PREFIX):]
        key = _parse_finding_resolution_key(suffix)
        status = _RESOLUTION_WIRE[check.resolution]
        resolutions[key] = status
        return status

    @staticmethod
    def _finding_from_check(role: ReviewerRole, check: CheckResult) -> Finding:
        """Build a verify-system :class:`Finding` from a non-PASS check."""
        severity = _STATUS_SEVERITY[check.status]
        message = check.reason or check.description or f"{check.check_id}: {check.status}"
        return Finding(
            layer=role.value,
            check=check.check_id,
            severity=severity,
            message=message,
            trust_class=TrustClass.VERIFIED_LLM,
        )

    @staticmethod
    def _resolution_finding(
        role: ReviewerRole,
        check: CheckResult,
        status: FindingResolutionStatus,
    ) -> Finding:
        """Build a blocking finding for an open finding-resolution (FK-34 §34.9.4).

        Both ``not_resolved`` and ``partially_resolved`` are blocking, so the
        severity is ``BLOCKING`` regardless of the LLM check.status (which is
        ``PASS_WITH_CONCERNS`` for partially_resolved). Mapped to the
        unconditional ``BLOCKING`` so the PolicyEngine blocks
        *schwellenunabhaengig* (FK-34 §34.9.4 Sonderregel) -- a partially
        resolved finding is a hard blocker, not a threshold-gated MAJOR.
        """
        message = (
            check.reason
            or check.description
            or f"{check.check_id}: {status.value}"
        )
        return Finding(
            layer=role.value,
            check=check.check_id,
            severity=Severity.BLOCKING,
            message=message,
            trust_class=TrustClass.VERIFIED_LLM,
        )


def _verdict(has_blocking: bool, has_concern: bool) -> LlmVerdict:
    """Aggregate the per-check outcome into a role verdict (FK-34 §34.2.5).

    Args:
        has_blocking: Whether any FAIL (or open finding-resolution) was seen.
        has_concern: Whether any PASS_WITH_CONCERNS was seen.

    Returns:
        ``FAIL`` if blocking, else ``PASS_WITH_CONCERNS`` if concerns, else ``PASS``.
    """
    if has_blocking:
        return LlmVerdict.FAIL
    if has_concern:
        return LlmVerdict.PASS_WITH_CONCERNS
    return LlmVerdict.PASS


@runtime_checkable
class _PromptMaterializer(Protocol):
    """Port resolving role prompts via ``PromptRuntime.materialize_prompt``.

    A thin, injected seam (FK-44 §44.4.2) so :class:`StructuredEvaluator` never
    reaches into prompt-runtime sub-modules nor reads a resource file directly,
    and stays unit-testable without a real prompt bundle. The concrete
    materialization (real ``PromptRuntime``) is wired by
    :class:`~agentkit.verify_system.llm_evaluator.parallel_runner.ParallelEvalRunner`
    / the composition root; tests inject a double with the same surface.
    """

    def context_for(self, bundle: ReviewBundle) -> tuple[StoryContext, str]:
        """Return ``(story_context, story_id)`` resolved for ``bundle``."""
        ...

    def render(
        self,
        role: ReviewerRole,
        ctx: StoryContext,
        story_id: str,
        template_override: str | None = None,
    ) -> tuple[str, str]:
        """Return ``(prompt_text, template_sha256)`` for ``role``.

        Args:
            role: The reviewer role (used to select the template when
                ``template_override`` is ``None``).
            ctx: The resolved story context.
            story_id: Story display-ID.
            template_override: When set, use this logical template name
                instead of the role's default template (FK-32 conformance
                levels use level-specific templates over DOC_FIDELITY role).
        """
        ...


def template_name_for_role(role: ReviewerRole) -> str:
    """Return the logical prompt-template name for a role (FK-44 §44.4.2).

    Args:
        role: The reviewer role.

    Returns:
        The logical template name (e.g. ``"qa-review"``).
    """
    return _ROLE_TEMPLATE[role]


__all__ = [
    "DOC_FIDELITY_CHECK_IDS",
    "QA_REVIEW_CHECK_IDS",
    "SEMANTIC_REVIEW_CHECK_IDS",
    "CheckResult",
    "LlmEvaluatorResponse",
    "LlmVerdict",
    "ReviewerRole",
    "StructuredEvaluator",
    "StructuredEvaluatorError",
    "StructuredEvaluatorResult",
    "template_name_for_role",
]
