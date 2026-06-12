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

Source:
  - FK-34 §34.2 -- three roles, response schema, aggregation
  - FK-34 §34.5.1 -- error handling (fail-closed, no valid JSON -> FAIL)
  - FK-34 §34.9 / DK-04 §4.6 -- finding resolution in remediation mode
  - FK-27 §27.5.2 -- the 12 qa_review check IDs
  - FK-44 §44.4.2 -- prompt lookup via PromptRuntime.materialize_prompt
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, ValidationError

from agentkit.verify_system.llm_evaluator.llm_client import (
    _EVAL_DEADLINE_CV,
    TOTAL_TIMEOUT_SECONDS,
    LlmClientError,
    bind_eval_deadline,
)
from agentkit.verify_system.llm_evaluator.roles import (
    DOC_FIDELITY_CHECK_IDS,
    QA_REVIEW_CHECK_IDS,
    ROLE_CHECK_IDS,
    ROLE_TEMPLATE,
    SEMANTIC_REVIEW_CHECK_IDS,
    STATUS_SEVERITY,
    LlmVerdict,
    ReviewerRole,
)
from agentkit.verify_system.llm_evaluator.structured_evaluator_parsing import (
    _FINDING_RESOLUTION_PREFIX,
    _RESOLUTION_WIRE,
    StructuredEvaluatorError,
    _extract_check_near_id,
    _extract_json_fence,
    _finding_resolution_id,
    _parse_finding_resolution_key,
    _sequential_status_checks,
    _verdict,
)
from agentkit.verify_system.protocols import Finding, Severity, TrustClass
from agentkit.verify_system.remediation.finding_resolution import (
    FindingKey,
    FindingResolutionStatus,
)

if TYPE_CHECKING:
    from agentkit.artifacts import ArtifactManager
    from agentkit.story_context_manager.models import StoryContext
    from agentkit.telemetry.emitters import EventEmitter
    from agentkit.verify_system.llm_evaluator.bundle import ReviewBundle
    from agentkit.verify_system.llm_evaluator.llm_client import LlmClient

logger = logging.getLogger(__name__)

#: Schema hint injected on retry when the first attempt failed to parse (FK-11 §11.4.4).
_SCHEMA_RETRY_HINT: Final[str] = (
    "\n\n## Response Format Reminder (RETRY)\n"
    "The previous response could not be parsed as a JSON array of check objects.\n"
    "You MUST respond with ONLY a valid JSON array. Each entry must have:\n"
    '  {"check_id": "<id>", "status": "PASS|PASS_WITH_CONCERNS|FAIL", '
    '"reason": "<one-liner>", "description": "<optional>"}\n'
    "No prose, no markdown fences around the array, just the raw JSON array."
)


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
        rendered_prompt: The fully rendered prompt sent to the LLM (FK-11
            §11.4.6 full logging; ``None`` if logging was skipped).
        raw_response: The full raw LLM response text (FK-11 §11.4.6 full
            logging; ``None`` if logging was skipped).
        retry_count: Number of LLM calls made (1 = no retry, 2 = one retry).
        prompt_audit_status: Status of the prompt-audit persistence attempt
            (FK-11 §11.4.6a): ``"persisted"`` on success, ``"skipped"`` when
            pre-conditions are absent (no manager / no run_id), ``"error"`` on
            a write rejection by the ArtifactManager. A manager-present
            rejection is logged via logger.warning AND surfaced here (never
            silently swallowed, ERROR 4 fix).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    role: ReviewerRole
    verdict: LlmVerdict
    findings: tuple[Finding, ...]
    finding_resolutions: dict[FindingKey, FindingResolutionStatus]
    raw_response_hash: str
    template_sha256: str
    rendered_prompt: str | None = None
    raw_response: str | None = None
    retry_count: int = 1
    prompt_audit_status: str = "skipped"


class StructuredEvaluator:
    """Runs one fail-closed LLM evaluation role (FK-34 / FK-11 §11.4).

    Attributes are injected, not global: the
    :class:`~agentkit.verify_system.llm_evaluator.llm_client.LlmClient` port
    and the prompt materializer. The evaluator is pure apart from the injected
    LLM call and the prompt-runtime materialization side effect.

    FK-11 §11.4.4 three-stage response processing (exact order, fail-closed):
    1. Prompt template includes explicit JSON format spec (contract/golden test).
    2. Extract JSON block from possibly-embedded text (```json or [{).
    3. Regex fallback per check (status/reason/description from free text).
    All stages fail → exactly 1 retry with schema hint → fail-closed.
    Max 2 LLM calls per evaluation (hard cap).
    """

    def __init__(
        self,
        llm_client: LlmClient,
        prompt_materializer: _PromptMaterializer,
        *,
        event_emitter: EventEmitter | None = None,
        artifact_manager: ArtifactManager | None = None,
    ) -> None:
        """Initialise the evaluator.

        Args:
            llm_client: The LLM transport port (FK-34 / FK-11 §11.5.1).
            prompt_materializer: A callable resolving ``(role, ctx) ->
                (prompt_text, template_sha256)`` via
                ``PromptRuntime.materialize_prompt`` (FK-44 §44.4.2). Injected
                so the evaluator never reaches into prompt-runtime sub-modules
                nor reads a resource file directly.
            event_emitter: Optional telemetry emitter for ``llm_call`` events
                (FK-11 §11.4.6). ``None`` => no event emitted (skipped cleanly).
            artifact_manager: Optional ``ArtifactManager`` for persisting the
                full rendered prompt + raw response as a
                ``PROMPT_AUDIT`` envelope (FK-11 §11.4.6a). ``None`` =>
                persistence skipped (clean ``skipped`` status).
        """
        self._llm_client = llm_client
        self._materialize = prompt_materializer
        self._event_emitter = event_emitter
        self._artifact_manager = artifact_manager

    def evaluate(
        self,
        role: ReviewerRole,
        bundle: ReviewBundle,
        previous_findings: list[Finding] | None,
        qa_cycle_round: int,
        expected_check_ids: frozenset[str] | None = None,
        template_override: str | None = None,
        *,
        run_id: str | None = None,
        run_attempt: int = 1,
    ) -> StructuredEvaluatorResult:
        """Evaluate one role against the review bundle (fail-closed).

        Implements FK-11 §11.4.4 three-stage response processing with max-2-call
        retry and FK-11 §11.4.6 full logging (prompt + response + telemetry event).

        The full rendered prompt + raw response are persisted via the injected
        ``ArtifactManager`` as a ``PROMPT_AUDIT`` envelope (FK-11 §11.4.6a)
        when both ``artifact_manager`` and ``run_id`` are available; otherwise a
        clean ``skipped`` status is recorded.

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
            run_id: Optional run correlation ID for the prompt-audit envelope.
                When ``None``, prompt-audit persistence is skipped cleanly.
            run_attempt: The 1-based run-attempt counter for the prompt-audit
                envelope (default 1). Named ``run_attempt`` to avoid shadowing
                the inner LLM-call-attempt loop variable.

        Returns:
            The validated :class:`StructuredEvaluatorResult`.

        Raises:
            StructuredEvaluatorError: On an unparseable / schema-violating
                response after 2 attempts (fail-closed, FK-34 §34.5.1).
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

        mandatory, resolution_required = self._required_check_ids(
            role, previous_findings, qa_cycle_round, expected_check_ids
        )

        return self._evaluate_with_retry(
            role=role,
            bundle=bundle,
            full_prompt=full_prompt,
            template_sha256=template_sha256,
            mandatory=mandatory,
            resolution_required=resolution_required,
            run_id=run_id,
            run_attempt=run_attempt,
        )

    def _evaluate_with_retry(
        self,
        *,
        role: ReviewerRole,
        bundle: ReviewBundle,
        full_prompt: str,
        template_sha256: str,
        mandatory: frozenset[str],
        resolution_required: frozenset[str],
        run_id: str | None,
        run_attempt: int,
    ) -> StructuredEvaluatorResult:
        """Run the bounded max-two-call parse retry loop."""
        eval_start = time.monotonic()
        eval_deadline = eval_start + TOTAL_TIMEOUT_SECONDS
        _cv_token = bind_eval_deadline(eval_deadline)
        try:
            last_parse_error: StructuredEvaluatorError | None = None
            raw_response: str = ""
            retry_count = 0
            current_prompt = full_prompt

            for attempt in range(2):  # max 2 LLM calls
                retry_count = attempt + 1
                self._raise_if_retry_budget_exhausted(attempt, eval_start)
                raw_response = self._complete_attempt(
                    role=role,
                    bundle=bundle,
                    prompt=current_prompt,
                    attempt=attempt,
                )
                response, parse_error = self._parse_attempt(
                    raw_response, role, mandatory | resolution_required
                )

                if parse_error is not None:
                    last_parse_error = parse_error
                    current_prompt = self._prompt_after_parse_failure(
                        role=role,
                        bundle=bundle,
                        full_prompt=full_prompt,
                        attempt=attempt,
                        parse_error=parse_error,
                    )
                    continue  # next attempt

                # Parse succeeded — now validate completeness (no retry on this).
                assert response is not None
                self._validate_completeness(role, response, mandatory, resolution_required)

                # All good — build result and emit telemetry.
                findings, resolutions, verdict = self._aggregate(role, response)
                raw_hash = hashlib.sha256(raw_response.encode("utf-8")).hexdigest()
                self._emit_llm_call_event(
                    role=role,
                    bundle=bundle,
                    retry=attempt,
                    check_count=len(response.checks),
                    status="pass",
                )
                audit_status = self._persist_prompt_audit(
                    role=role,
                    story_id=bundle.story_id,
                    run_id=run_id,
                    attempt=run_attempt,
                    rendered_prompt=full_prompt,
                    raw_response=raw_response,
                    raw_response_hash=hashlib.sha256(raw_response.encode("utf-8")).hexdigest(),
                    template_sha256=template_sha256,
                    retry_count=retry_count,
                )
                result = StructuredEvaluatorResult(
                    role=role,
                    verdict=verdict,
                    findings=tuple(findings),
                    finding_resolutions=resolutions,
                    raw_response_hash=raw_hash,
                    template_sha256=template_sha256,
                    rendered_prompt=full_prompt,
                    raw_response=raw_response,
                    retry_count=retry_count,
                    prompt_audit_status=audit_status,
                )
                return result

            # Both parse attempts failed — fail-closed (events already emitted above
            # for each attempt, so no additional event here).
            raise StructuredEvaluatorError(
                f"LLM response for role={role.value!r} unparseable after 2 attempts "
                f"(FK-11 §11.4.4 fail-closed). Last parse error: {last_parse_error}"
            ) from last_parse_error
        finally:
            # Reset the per-evaluation deadline ContextVar so it never leaks to
            # the next task reusing this worker thread (concurrency-safe,
            # AG3-065 rem-4 ERROR 1 fix).
            _EVAL_DEADLINE_CV.reset(_cv_token)

    @staticmethod
    def _raise_if_retry_budget_exhausted(attempt: int, eval_start: float) -> None:
        if attempt != 1:
            return
        elapsed = time.monotonic() - eval_start
        if elapsed < TOTAL_TIMEOUT_SECONDS:
            return
        raise LlmClientError(
            f"StructuredEvaluator TOTAL_TIMEOUT_SECONDS budget exhausted after "
            f"first complete() attempt (elapsed={elapsed:.1f}s >= "
            f"{TOTAL_TIMEOUT_SECONDS}s): schema-retry refused "
            "(FK-11 §11.4.4 fail-closed)."
        )

    def _complete_attempt(
        self,
        *,
        role: ReviewerRole,
        bundle: ReviewBundle,
        prompt: str,
        attempt: int,
    ) -> str:
        try:
            raw_response = self._llm_client.complete(role=role.value, prompt=prompt)
        except LlmClientError:
            self._emit_llm_call_event(
                role=role,
                bundle=bundle,
                retry=attempt,
                check_count=0,
                status="transport_error",
            )
            raise
        if raw_response.strip():
            return raw_response
        self._emit_llm_call_event(
            role=role,
            bundle=bundle,
            retry=attempt,
            check_count=0,
            status="empty_response",
        )
        raise LlmClientError(
            f"LlmClient returned empty completion for role={role.value!r} "
            "(FK-34 §34.5.1 fail-closed)."
        )

    def _parse_attempt(
        self,
        raw_response: str,
        role: ReviewerRole,
        expected_ids: frozenset[str],
    ) -> tuple[LlmEvaluatorResponse | None, StructuredEvaluatorError | None]:
        try:
            return self._parse_response_three_stage(raw_response, role, expected_ids), None
        except StructuredEvaluatorError as exc:
            return None, exc

    def _prompt_after_parse_failure(
        self,
        *,
        role: ReviewerRole,
        bundle: ReviewBundle,
        full_prompt: str,
        attempt: int,
        parse_error: StructuredEvaluatorError,
    ) -> str:
        self._emit_llm_call_event(
            role=role,
            bundle=bundle,
            retry=attempt,
            check_count=0,
            status="parse_fail",
        )
        if attempt != 0:
            return full_prompt
        logger.warning(
            "StructuredEvaluator parse failed for role=%r (attempt 1/%d); "
            "retrying with schema hint: %s",
            role.value,
            2,
            parse_error,
        )
        return full_prompt + _SCHEMA_RETRY_HINT

    @staticmethod
    def _parse_response_three_stage(
        raw_response: str,
        role: ReviewerRole,
        expected_ids: frozenset[str],
    ) -> LlmEvaluatorResponse:
        """Three-stage response parsing (FK-11 §11.4.4, fail-closed).

        Stage 1: Template JSON format contract (enforced via contract/golden test
            on the prompt template; this method is Stage 2+3 execution only).
        Stage 2: Extract JSON block from possibly-embedded text (```json or [{),
            json.loads → list[CheckResult].
        Stage 3: Regex fallback per check (status/reason/description from free
            text), with correct check_id mapping from ``expected_ids``.

        All stages fail → :class:`StructuredEvaluatorError` (caller handles retry).

        Args:
            raw_response: The raw LLM completion text.
            role: The reviewer role (for error messages).
            expected_ids: All expected check-ids (base + resolution); used in
                Stage 3 to assign ``check_id`` correctly.

        Returns:
            Validated :class:`LlmEvaluatorResponse`.

        Raises:
            StructuredEvaluatorError: If all stages fail (fail-closed).
        """
        # Stage 2: Extract JSON block and deserialise.
        stage2_error: Exception | None = None
        try:
            return StructuredEvaluator._stage2_extract_json(raw_response, role)
        except StructuredEvaluatorError as exc:
            stage2_error = exc

        # Stage 3: Regex fallback.
        try:
            return StructuredEvaluator._stage3_regex_fallback(raw_response, role, expected_ids)
        except StructuredEvaluatorError as exc3:
            # Both Stage 2 and Stage 3 failed.
            raise StructuredEvaluatorError(
                f"LLM response for role={role.value!r} failed all parse stages "
                f"(FK-11 §11.4.4 fail-closed). "
                f"Stage 2: {stage2_error}; Stage 3: {exc3}"
            ) from exc3

    @staticmethod
    def _stage2_extract_json(raw_response: str, role: ReviewerRole) -> LlmEvaluatorResponse:
        """Stage 2: Extract JSON block from possibly-embedded text.

        Handles both:
        - A response that starts with a JSON array directly.
        - A response with a ```json ... ``` fenced block.
        - A response with an unenclosed JSON array starting with ``[{``.

        Args:
            raw_response: Raw LLM completion text.
            role: Reviewer role (for error messages).

        Returns:
            Validated :class:`LlmEvaluatorResponse`.

        Raises:
            StructuredEvaluatorError: If no valid JSON array can be extracted.
        """
        text = raw_response.strip()

        # Try direct JSON parse first (whole response is pure JSON).
        candidates: list[str] = []

        # 1. Try the whole response as JSON.
        candidates.append(text)

        # 2. Extract from ```json ... ``` fenced block via a non-backtracking
        #    string-index scan (S5852: the prior ``r"```json\s*(.*?)```"`` regex
        #    risked catastrophic backtracking). Find the ```json opener, skip the
        #    following whitespace, then take the slice up to the next ``` closer —
        #    yielding the EXACT same candidate the regex produced.
        fenced = _extract_json_fence(text)
        if fenced is not None:
            candidates.append(fenced)

        # 3. Extract from first "[{" to last "}]" pattern.
        array_start = text.find("[{")
        array_end = text.rfind("}]")
        if array_start != -1 and array_end > array_start:
            candidates.append(text[array_start : array_end + 2].strip())

        # 4. Extract from the first "[" to the last matching "]".
        first_bracket = text.find("[")
        last_bracket = text.rfind("]")
        if first_bracket != -1 and last_bracket > first_bracket:
            candidates.append(text[first_bracket : last_bracket + 1])

        last_error: Exception | None = None
        for candidate in candidates:
            try:
                parsed = json.loads(candidate)
            except json.JSONDecodeError as exc:
                last_error = exc
                continue
            if not isinstance(parsed, list):
                last_error = TypeError(f"Expected JSON array, got {type(parsed).__name__}")
                continue
            try:
                return LlmEvaluatorResponse(checks=tuple(parsed))
            except ValidationError as exc:
                last_error = exc
                continue

        raise StructuredEvaluatorError(
            f"Stage 2: LLM response for role={role.value!r} contains no valid "
            f"JSON array of check objects (FK-11 §11.4.4). Last error: {last_error}"
        )

    @staticmethod
    def _stage3_regex_fallback(
        raw_response: str,
        role: ReviewerRole,
        expected_ids: frozenset[str],
    ) -> LlmEvaluatorResponse:
        """Stage 3: Regex fallback — extract check fields from free text.

        Parses ``status``, ``reason``, and ``description`` from free-text LLM
        output and maps them to ``CheckResult`` objects with correct ``check_id``
        assignment. Uses ``expected_ids`` as the mapping source.

        Args:
            raw_response: Raw LLM completion text.
            role: Reviewer role (for error messages).
            expected_ids: All required check-ids (maps position to id).

        Returns:
            :class:`LlmEvaluatorResponse` with regex-extracted checks.

        Raises:
            StructuredEvaluatorError: If no checks can be extracted.
        """
        text = raw_response

        # Pattern: look for status values near known check-id strings or
        # in sequential blocks.
        checks: list[dict[str, object]] = []
        status_pattern = re.compile(
            r"\b(PASS_WITH_CONCERNS|PASS|FAIL)\b", re.IGNORECASE
        )
        reason_pattern = re.compile(
            r'"reason"\s*:\s*"([^"]*)"', re.IGNORECASE
        )
        desc_pattern = re.compile(
            r'"description"\s*:\s*"([^"]*)"', re.IGNORECASE
        )

        # Try to extract per-check_id from text by finding the check_id mention.
        sorted_ids = sorted(expected_ids)
        for check_id in sorted_ids:
            check = _extract_check_near_id(
                text,
                check_id,
                status_pattern=status_pattern,
                reason_pattern=reason_pattern,
                desc_pattern=desc_pattern,
            )
            if check is not None:
                checks.append(check)

        if not checks:
            # Last resort: find status values and zip with sorted ids.
            checks.extend(_sequential_status_checks(text, sorted_ids, status_pattern))

        if not checks:
            raise StructuredEvaluatorError(
                f"Stage 3: LLM response for role={role.value!r} contains no "
                "recognisable check entries even via regex fallback "
                "(FK-11 §11.4.4 fail-closed)."
            )

        try:
            return LlmEvaluatorResponse(checks=tuple(checks))
        except ValidationError as exc:
            raise StructuredEvaluatorError(
                f"Stage 3: regex-extracted checks for role={role.value!r} failed "
                f"schema validation: {exc}"
            ) from exc

    def _persist_prompt_audit(
        self,
        *,
        role: ReviewerRole,
        story_id: str,
        run_id: str | None,
        attempt: int,
        rendered_prompt: str | None,
        raw_response: str | None,
        raw_response_hash: str,
        template_sha256: str,
        retry_count: int,
    ) -> str:
        """Persist the full rendered prompt + raw response via ArtifactManager.write().

        FK-11 §11.4.6a: the full prompt and raw response MUST be persisted via
        the prompt-audit / ArtifactManager machinery — NOT a parallel loose-JSON
        channel (AG3-065 §2.1.8a / §2.1.5 "no parallel log channel"). Routed
        via the concept-owned ``prompt-runtime.materialization`` producer
        (registered in ``prompt_runtime.register``) with a role-specific stage
        id to avoid DB-key collisions across the three Layer-2 roles (ERROR 2
        fix: key is (story_id, run_id, stage, attempt, artifact_class,
        producer_name) — using stage=f"layer2-prompt-audit-{role_slug}" gives
        each role a unique row).

        A clean ``"skipped"`` status is returned only when:
        - no ``ArtifactManager`` was injected, or
        - ``run_id`` is absent (run-correlation unavailable).

        A manager-present write rejection is logged AND returned as ``"error"``
        (never silently swallowed, ERROR 4 fix for StructuredEvaluator).

        Args:
            role: The reviewer role (used to derive the role-specific stage).
            story_id: Story display-ID for the envelope.
            run_id: Run-correlation ID; ``None`` yields a ``skipped`` status.
            attempt: 1-based attempt counter for the envelope.
            rendered_prompt: The fully rendered prompt sent to the LLM.
            raw_response: The full raw LLM response text.
            raw_response_hash: SHA-256 of the raw response.
            template_sha256: SHA-256 of the prompt template.
            retry_count: Number of LLM calls made.

        Returns:
            ``"persisted"`` on success, ``"skipped"`` when pre-conditions
            are absent, ``"error"`` on a write rejection.
        """
        if self._artifact_manager is None:
            return "skipped"
        if not run_id:
            return "skipped"
        if rendered_prompt is None or raw_response is None:
            return "skipped"

        try:
            from agentkit.artifacts.envelope import ArtifactEnvelope
            from agentkit.artifacts.producer import Producer, ProducerId, ProducerType
            from agentkit.core_types import ArtifactClass, EnvelopeStatus
            from agentkit.prompt_runtime.audit import PROMPT_AUDIT_PRODUCER_NAME

            now = datetime.now(UTC)
            role_slug = role.value.replace("_", "-")
            # Role-specific stage ensures unique DB key per role:
            # key = (story_id, run_id, stage, attempt, artifact_class, producer_name)
            stage = f"layer2-prompt-audit-{role_slug}"
            record_key = f"verify-layer2-{role_slug}-{run_id}-{attempt:03d}"
            # Route via the concept-owned producer (no new producers invented,
            # AG3-065 §2.1.8a): ``prompt-runtime.materialization`` is already
            # registered by ``register_prompt_runtime_producers``.
            producer = Producer(
                type=ProducerType.DETERMINISTIC,
                name=PROMPT_AUDIT_PRODUCER_NAME,
                id=ProducerId(record_key),
            )
            envelope = ArtifactEnvelope(
                schema_version="3.0",
                story_id=story_id,
                run_id=run_id,
                stage=stage,
                attempt=attempt,
                producer=producer,
                started_at=now,
                finished_at=now,
                status=EnvelopeStatus.PASS,
                artifact_class=ArtifactClass.PROMPT_AUDIT,
                payload={
                    "role": role.value,
                    "rendered_prompt": rendered_prompt,
                    "raw_response": raw_response,
                    "raw_response_hash": raw_response_hash,
                    "template_sha256": template_sha256,
                    "retry_count": retry_count,
                },
            )
            self._artifact_manager.write(envelope)
            return "persisted"
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "StructuredEvaluator: prompt-audit persistence failed for "
                "role=%r story_id=%r run_id=%r: %s",
                role.value,
                story_id,
                run_id,
                exc,
            )
            return "error"

    def _emit_llm_call_event(
        self,
        *,
        role: ReviewerRole,
        bundle: ReviewBundle,
        retry: int,
        check_count: int,
        status: str,
    ) -> None:
        """Emit the ``llm_call`` telemetry event (FK-11 §11.4.6b).

        Silently skipped if no emitter is injected or emission fails
        (telemetry is never a pipeline blocker).

        Args:
            role: The evaluated role.
            bundle: The review bundle (carries story_id).
            retry: 0 = first attempt, 1 = retry.
            check_count: Number of parsed checks (0 on failure).
            status: ``"pass"`` or ``"fail"``.
        """
        if self._event_emitter is None:
            return
        try:
            from agentkit.telemetry.events import Event, EventType

            pool = getattr(self._llm_client, "_resolver", None)
            pool_name: str = "unknown"
            try:
                if pool is not None:
                    resolved = pool.resolve(role.value)
                    pool_name = str(resolved)
            except Exception:  # noqa: BLE001
                pass

            event = Event(
                story_id=bundle.story_id,
                event_type=EventType.LLM_CALL,
                source_component="structured_evaluator",
                payload={
                    "pool": pool_name,
                    "role": role.value,
                    "retry": retry,
                    "check_count": check_count,
                    "status": status,
                },
            )
            self._event_emitter.emit(event)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to emit llm_call telemetry event: %s", exc)

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
        "evaluate per finding whether it is resolved"). A finding belongs to the
        role that produced it (``finding.layer == role.value``) -- the
        ``qa_review`` evaluator resolves ``qa_review`` findings, the
        ``semantic_review`` evaluator its own, etc. Both sets are mandatory and
        exact-match enforced by :meth:`_validate_completeness` (fail-closed).
        """
        mandatory = expected_check_ids if expected_check_ids is not None else ROLE_CHECK_IDS[role]
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
                    # blocks hard (FK-34 §34.9.4 special rule).
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
        severity = STATUS_SEVERITY[check.status]
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
        *threshold-independently* (FK-34 §34.9.4 special rule) -- a partially
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
    return ROLE_TEMPLATE[role]


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
