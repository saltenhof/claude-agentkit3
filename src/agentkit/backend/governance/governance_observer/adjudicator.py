"""GovernanceAdjudicator port for LLM-based adjudication (FK-35 §35.3.7).

The adjudicator is a THIN port in the ``governance`` BC that:
1. Materialises the FK-35 §35.3.7 prompt from the incident candidate.
2. Sends it over the EXISTING LLM-pool transport (AG3-065 Multi-LLM Hub).
3. Validates the response against the dedicated
   :class:`~agentkit.backend.governance.governance_observer.models.GovernanceAdjudicationVerdict`
   schema (fail-closed on schema violation).

It does NOT reuse :class:`~agentkit.backend.verify_system.llm_evaluator.structured_evaluator.StructuredEvaluator`
(which validates CheckResult arrays and only knows ``qa_review`` / ``semantic_review``
/ ``doc_fidelity`` reviewer roles — FK-35 §35.3.7 forbids abusing that path).
No new value is smuggled into the foreign ``ReviewerRole`` enum.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, cast, runtime_checkable

from agentkit.backend.governance.governance_observer.models import GovernanceAdjudicationVerdict

if TYPE_CHECKING:
    from agentkit.backend.governance.governance_observer.models import GovernanceIncidentCandidate
    from agentkit.integration_clients.multi_llm_hub.client import HubClientProtocol
    from agentkit.integration_clients.multi_llm_hub.entities import HubBackendName, HubMessage

#: FK-35 §35.3.7 prompt template.  The LLM is instructed to respond ONLY with
#: a JSON object matching the GovernanceAdjudicationVerdict schema.
_ADJUDICATION_PROMPT_TEMPLATE = """\
You are a governance adjudicator for an AI-agent orchestration system.
Analyse the following incident candidate and classify it.

## Incident candidate

Project: {project_key}
Story: {story_id}
Run: {run_id}
Risk score: {risk_score}
Event count: {event_count}
Dominant signals: {dominant_signals}
Evidence summary: {evidence_summary}
Time span (seconds): {time_span_s}

## Story context summary

{story_context_summary}

## Response format

Respond ONLY with a JSON object — no prose, no markdown fences — matching
this exact schema:

{{
  "incident_type": "<role_violation|scope_drift|retry_loop|stagnation|governance_manipulation|secret_access>",
  "severity": "<low|medium|high|critical>",
  "confidence": <float 0.0-1.0>,
  "evidence_summary": "<concise human-readable summary>",
  "recommended_action": "<log_only|document_incident|increase_monitoring|pause_story|stop_process>"
}}
"""


@runtime_checkable
class GovernanceAdjudicatorPort(Protocol):
    """Port: send a governance incident candidate to the LLM and get a verdict.

    The production implementation sends via the Multi-LLM Hub (AG3-065).
    Unit tests inject a scripted fake AT THIS BOUNDARY — never through the
    domain logic.

    FAIL-CLOSED contract: any transport error or schema-validation failure
    MUST raise an exception; no silent fallback to a default verdict.
    """

    def adjudicate(
        self,
        candidate: GovernanceIncidentCandidate,
        *,
        story_context_summary: str,
    ) -> GovernanceAdjudicationVerdict:
        """Send the candidate to the LLM and return a typed verdict.

        Args:
            candidate: The governance incident candidate to adjudicate.
            story_context_summary: Brief human-readable story context.

        Returns:
            Parsed and validated :class:`GovernanceAdjudicationVerdict`.

        Raises:
            GovernanceAdjudicationError: On transport failure or schema
                violation (fail-closed).
        """
        ...


class GovernanceAdjudicationError(RuntimeError):
    """Raised when the LLM adjudication fails or returns an invalid schema.

    Fail-closed: the caller MUST treat this as an unresolved incident
    and escalate rather than silently swallowing the error.
    """


def build_adjudication_prompt(
    candidate: GovernanceIncidentCandidate,
    *,
    story_context_summary: str,
) -> str:
    """Materialise the FK-35 §35.3.7 adjudication prompt for a candidate.

    Args:
        candidate: The governance incident candidate.
        story_context_summary: Brief human-readable story context.

    Returns:
        Fully rendered prompt string ready to send to the LLM.
    """
    return _ADJUDICATION_PROMPT_TEMPLATE.format(
        project_key=candidate.project_key,
        story_id=candidate.story_id,
        run_id=candidate.run_id,
        risk_score=candidate.risk_score,
        event_count=candidate.event_count,
        dominant_signals=", ".join(candidate.dominant_signals),
        evidence_summary=candidate.evidence_summary,
        time_span_s=candidate.time_span_s,
        story_context_summary=story_context_summary,
    )


def parse_adjudication_response(raw_text: str) -> GovernanceAdjudicationVerdict:
    """Parse and validate the LLM response against the adjudication schema.

    FAIL-CLOSED: any JSON parse error or Pydantic validation failure raises
    :class:`GovernanceAdjudicationError` — no silent fallback.

    Args:
        raw_text: Raw LLM response text.

    Returns:
        Validated :class:`GovernanceAdjudicationVerdict`.

    Raises:
        GovernanceAdjudicationError: On parse failure or schema violation.
    """
    text = raw_text.strip()
    text = _strip_markdown_fence(text)
    try:
        return GovernanceAdjudicationVerdict.model_validate_json(text)
    except ValueError as exc:  # pydantic ValidationError is a ValueError subclass
        raise GovernanceAdjudicationError(
            f"LLM adjudication response is not valid JSON or failed schema validation:"
            f" {exc}\nRaw response (first 500 chars): {raw_text[:500]!r}"
        ) from exc


def _strip_markdown_fence(text: str) -> str:
    """Remove optional markdown code fences from LLM output.

    Args:
        text: Stripped LLM response text.

    Returns:
        Text with leading/trailing markdown fences removed.
    """
    if text.startswith("```"):
        lines = text.splitlines()
        # Drop first line (```json or ```) and last line (```)
        inner = lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
        return "\n".join(inner).strip()
    return text


class HubGovernanceAdjudicator:
    """Production GovernanceAdjudicator backed by the Multi-LLM Hub (AG3-065).

    Acquires a single LLM session, sends the adjudication prompt, releases the
    session, and validates the response against the GovernanceAdjudicationVerdict
    schema.  Fail-closed on any transport or schema error.

    Args:
        hub_client: The :class:`~agentkit.integration_clients.multi_llm_hub.client.HubClientProtocol`
            to use for acquire/send/release.
        backend: LLM backend name to use (default ``"chatgpt"``).
        send_timeout: Per-send timeout in seconds (default 120).
    """

    def __init__(
        self,
        hub_client: HubClientProtocol,
        *,
        backend: str = "chatgpt",
        send_timeout: float = 120.0,
    ) -> None:
        self._hub = hub_client
        self._backend = backend
        self._send_timeout = send_timeout

    def adjudicate(
        self,
        candidate: GovernanceIncidentCandidate,
        *,
        story_context_summary: str,
    ) -> GovernanceAdjudicationVerdict:
        """Send the candidate to the LLM Hub and return a validated verdict.

        Args:
            candidate: The governance incident candidate to adjudicate.
            story_context_summary: Brief human-readable story context.

        Returns:
            Validated :class:`GovernanceAdjudicationVerdict`.

        Raises:
            GovernanceAdjudicationError: On transport failure or schema violation.
        """
        prompt = build_adjudication_prompt(candidate, story_context_summary=story_context_summary)
        raw_response = self._send_to_hub(
            owner=f"governance-observer/{candidate.story_id}",
            description=f"Governance adjudication for story {candidate.story_id}",
            prompt=prompt,
        )
        return parse_adjudication_response(raw_response)

    def _send_to_hub(
        self,
        *,
        owner: str,
        description: str,
        prompt: str,
    ) -> str:
        """Acquire, send, and release a Hub session.

        Args:
            owner: Session owner label.
            description: Human-readable session description.
            prompt: The prompt to send.

        Returns:
            Raw LLM response text.

        Raises:
            GovernanceAdjudicationError: On any Hub error.
        """
        from agentkit.integration_clients.multi_llm_hub.errors import MultiLlmHubError

        try:
            lease = self._hub.acquire(
                owner=owner,
                description=description,
                llms=[cast("HubBackendName", self._backend)],
            )
            try:
                backend_name = cast("HubBackendName", self._backend)
                messages = self._hub.send(
                    session_id=lease.session_id,
                    token=lease.token,
                    message=prompt,
                    target=backend_name,
                    timeout=self._send_timeout,
                )
                msg: HubMessage | None = messages.get(backend_name)
                if msg is None or msg.status != "ok":
                    error_text: str = msg.text if msg is not None else "no response"
                    raise GovernanceAdjudicationError(f"LLM backend {self._backend!r} returned error: {error_text}")
                return str(msg.text)
            finally:
                import contextlib

                with contextlib.suppress(MultiLlmHubError):
                    self._hub.release(
                        session_id=lease.session_id,
                        token=lease.token,
                    )
        except GovernanceAdjudicationError:
            raise
        except MultiLlmHubError as exc:
            raise GovernanceAdjudicationError(f"Multi-LLM Hub transport error during adjudication: {exc}") from exc
