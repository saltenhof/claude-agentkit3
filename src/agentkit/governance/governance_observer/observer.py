"""GovernanceObserver: rolling-window risk-score + LLM adjudication (FK-35 §35.3).

This is the aggregating observation / adjudication layer above the hook-sensor
signals (AG3-086).  It orchestrates:

1. Rolling-window score computation (no in-memory state — pure DB query).
2. Immediate-stop detection for hard governance violations.
3. Threshold check and cooldown gate.
4. LLM adjudication via the dedicated GovernanceAdjudicatorPort.
5. Deterministic measure selection.
6. Failure-corpus handoff for severity >= medium.
7. Telemetry emission for all four FK-91 event types.

Boundary note (FK-35 §35.3.8 / §35.4.1 — AG3-085 scope limit)
---------------------------------------------------------------
The observer **SELECTS** the deterministic governance measure and **EMITS**
``governance_measure_applied`` as the governance decision record.  The ACTUAL
enforcement — immediate-stop via hook per FK-35 §35.3.8 / FK-06-118 (owned by
AG3-086 hook/sensorik layer); ``pause_story`` = Phase-State PAUSED; ``stop_process``
= orchestrator halt per FK-35 §35.3.8 / §35.4.1 — is owned by the hook/escalation
layer and is EXPLICITLY out of AG3-085 scope (see story §2.2 Out of Scope).

For immediate-stop signals (``governance_file_manipulation`` / ``secret_access``)
the observer emits ONLY ``governance_measure_applied`` (FK-35 §35.3.8 FK-06-118)
— no ``governance_incident_opened`` and no ``governance_adjudication`` event are
emitted on this path, consistent with the direct hard-stop bypass.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from agentkit.governance.governance_observer.config import (
    get_cooldown_s,
    get_risk_threshold,
    get_window_size,
)
from agentkit.governance.governance_observer.cooldown import should_adjudicate
from agentkit.governance.governance_observer.mapper import to_corpus_incident_candidate
from agentkit.governance.governance_observer.measures import select_measure
from agentkit.governance.governance_observer.models import (
    IMMEDIATE_STOP_SIGNALS,
    RISK_POINTS,
    AdjudicationSeverity,
    GovernanceAdjudicationVerdict,
    GovernanceIncidentCandidate,
    GovernanceMeasure,
    GovernanceSignalType,
)
from agentkit.governance.governance_observer.score import (
    SOURCE_COMPONENT,
    ExecutionEventReader,
    _validate_signal_payload,
    score_from_validated_payloads,
)
from agentkit.telemetry.events import Event, EventType, validate_event_payload

if TYPE_CHECKING:
    from agentkit.config.models import GovernanceConfig
    from agentkit.failure_corpus.top import FailureCorpus
    from agentkit.governance.governance_observer.adjudicator import GovernanceAdjudicatorPort
    from agentkit.telemetry.emitters import EventEmitter

#: Severities that require failure-corpus handoff (FK-35 §35.3.9).
_CORPUS_SEVERITIES: frozenset[AdjudicationSeverity] = frozenset(
    {
        AdjudicationSeverity.MEDIUM,
        AdjudicationSeverity.HIGH,
        AdjudicationSeverity.CRITICAL,
    }
)

#: Source phase label for governance telemetry events.
_PHASE: str = "implementation"


class GovernanceObserver:
    """Rolling-window risk-score + LLM adjudication subsystem (FK-35 §35.3).

    Instantiate once per story run and call :meth:`handle_signal` for each
    incoming governance signal.  All state lives in the DB — the observer
    itself is stateless between calls (SINGLE SOURCE OF TRUTH, no in-memory
    rolling buffer).

    Args:
        reader: Injected execution-event reader port (DB or test double).
        adjudicator: Injected GovernanceAdjudicatorPort (Hub or test double).
        emitter: Telemetry event emitter.
        failure_corpus: Optional :class:`~agentkit.failure_corpus.top.FailureCorpus`
            for incident handoff (FK-35 §35.3.9).
        config: Optional :class:`~agentkit.config.models.GovernanceConfig`
            (FK-93 §93.5 defaults apply when ``None``).
    """

    def __init__(
        self,
        reader: ExecutionEventReader,
        adjudicator: GovernanceAdjudicatorPort,
        emitter: EventEmitter,
        failure_corpus: FailureCorpus | None = None,
        config: GovernanceConfig | None = None,
    ) -> None:
        self._reader = reader
        self._adjudicator = adjudicator
        self._emitter = emitter
        self._failure_corpus = failure_corpus
        self._config = config

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def handle_signal(
        self,
        project_key: str,
        story_id: str,
        run_id: str,
        *,
        signal_type_wire: str,
        story_context_summary: str = "",
    ) -> GovernanceMeasure:
        """Process one incoming governance signal and return the measure.

        For immediate-stop signals (governance-file-manipulation / secret-access)
        this returns :attr:`~GovernanceMeasure.STOP_PROCESS` WITHOUT consulting
        the LLM (FK-35 §35.3.8 FK-06-118).

        For all other signals: compute the rolling-window score, check the
        threshold and cooldown, run adjudication if required, apply the
        deterministic measure, and emit telemetry.

        Args:
            project_key: Project scope.
            story_id: Story scope.
            run_id: Run scope.
            signal_type_wire: Wire value of the incoming signal type.
            story_context_summary: Brief context summary passed to adjudication.

        Returns:
            The :class:`GovernanceMeasure` that was applied.

        Raises:
            ValueError: When ``signal_type_wire`` is not a known
                :class:`~GovernanceSignalType` value (fail-closed per ARCH-55).
        """
        signal_type = _parse_signal_type(signal_type_wire)

        if signal_type in IMMEDIATE_STOP_SIGNALS:
            return self._apply_immediate_stop(project_key, story_id, run_id)

        return self._process_scored_signal(
            project_key,
            story_id,
            run_id,
            signal_type=signal_type,
            story_context_summary=story_context_summary,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _apply_immediate_stop(
        self,
        project_key: str,
        story_id: str,
        run_id: str,
    ) -> GovernanceMeasure:
        """Apply stop_process for an immediate-stop signal without adjudication.

        Args:
            project_key: Project scope.
            story_id: Story scope.
            run_id: Run scope.

        Returns:
            :attr:`~GovernanceMeasure.STOP_PROCESS`.
        """
        measure = GovernanceMeasure.STOP_PROCESS
        self._emit_measure_applied(
            story_id,
            run_id,
            project_key=project_key,
            measure=measure,
            severity="critical",
        )
        return measure

    def _process_scored_signal(
        self,
        project_key: str,
        story_id: str,
        run_id: str,
        *,
        signal_type: GovernanceSignalType,
        story_context_summary: str,
    ) -> GovernanceMeasure:
        """Process a scored (non-immediate-stop) governance signal.

        Single-read path (AC2/AC9 FAIL-CLOSED): the rolling window is read
        ONCE and ALL payloads are validated before any score computation,
        candidate construction, or telemetry emission.  A malformed payload
        in the window raises immediately — no silent pass-through.

        Args:
            project_key: Project scope.
            story_id: Story scope.
            run_id: Run scope.
            signal_type: The signal type.
            story_context_summary: Brief context for adjudication.

        Returns:
            The :class:`GovernanceMeasure` that was applied.

        Raises:
            GovernanceSignalPayloadError: When any payload in the window is
                malformed, carries an unknown signal_type, or is an
                immediate-stop signal (FAIL-CLOSED per AC2/AC9).
        """
        window_size = get_window_size(self._config)
        threshold = get_risk_threshold(self._config)
        cooldown_s = get_cooldown_s(self._config)

        # Single validated read: raises fail-closed before any further processing
        # if any payload in the window violates the mandatory contract.
        window_payloads = self._reader.read_governance_signals(project_key, story_id, run_id, limit=window_size)
        _validate_window_payloads(window_payloads)

        score = score_from_validated_payloads(window_payloads)

        if score < threshold:
            return GovernanceMeasure.GOVERNANCE_LOG_ONLY

        # Cooldown check BEFORE building the candidate or emitting incident_opened.
        # Story §2.1.3: GovernanceIncidentCandidate is created "bei score >=
        # risk_threshold (und nicht im Cooldown)".  Emitting incident_opened before
        # the cooldown check would produce duplicate telemetry on every signal while
        # the cooldown is active — a contract violation (FK-91 Kap.35).
        if not should_adjudicate(
            self._reader,
            project_key,
            story_id,
            run_id,
            signal_type=signal_type.value,
            cooldown_s=cooldown_s,
        ):
            return GovernanceMeasure.GOVERNANCE_LOG_ONLY

        candidate = self._build_candidate(
            project_key,
            story_id,
            run_id,
            score=score,
            validated_payloads=window_payloads,
        )
        self._emit_incident_opened(story_id, run_id, project_key=project_key, candidate=candidate)

        verdict = self._run_adjudication(candidate, story_context_summary=story_context_summary)
        self._emit_adjudication(
            story_id,
            run_id,
            project_key=project_key,
            verdict=verdict,
            signal_type=signal_type.value,
        )

        measure = select_measure(verdict.severity, verdict.confidence)
        self._emit_measure_applied(
            story_id,
            run_id,
            project_key=project_key,
            measure=measure,
            severity=verdict.severity.value,
        )

        self._maybe_handoff_to_corpus(candidate, verdict)
        return measure

    def _build_candidate(
        self,
        project_key: str,
        story_id: str,
        run_id: str,
        *,
        score: int,
        validated_payloads: list[dict[str, object]],
    ) -> GovernanceIncidentCandidate:
        """Build a GovernanceIncidentCandidate from pre-validated window payloads.

        Accepts the already-validated payload list from the single-read path in
        :meth:`_process_scored_signal` — no second DB read is issued here.

        Args:
            project_key: Project scope.
            story_id: Story scope.
            run_id: Run scope.
            score: Current risk score (pre-computed from ``validated_payloads``).
            validated_payloads: Payload list already read and validated
                fail-closed by :func:`_validate_window_payloads`.

        Returns:
            A populated :class:`GovernanceIncidentCandidate`.
        """
        event_count = len(validated_payloads)
        dominant_signals = _dominant_signals(validated_payloads)
        time_span = _time_span_s(validated_payloads)
        evidence_summary = _summarise_payloads(validated_payloads)
        return GovernanceIncidentCandidate(
            project_key=project_key,
            story_id=story_id,
            run_id=run_id,
            created_at=datetime.now(UTC),
            risk_score=score,
            event_count=event_count,
            dominant_signals=dominant_signals,
            evidence_summary=evidence_summary,
            time_span_s=time_span,
        )

    def _run_adjudication(
        self,
        candidate: GovernanceIncidentCandidate,
        *,
        story_context_summary: str,
    ) -> GovernanceAdjudicationVerdict:
        """Invoke the LLM adjudicator (fail-closed on error).

        Args:
            candidate: The incident candidate to adjudicate.
            story_context_summary: Brief context for the LLM.

        Returns:
            Validated :class:`GovernanceAdjudicationVerdict`.

        Raises:
            GovernanceAdjudicationError: When adjudication fails.
        """
        return self._adjudicator.adjudicate(candidate, story_context_summary=story_context_summary)

    def _maybe_handoff_to_corpus(
        self,
        candidate: GovernanceIncidentCandidate,
        verdict: GovernanceAdjudicationVerdict,
    ) -> None:
        """Hand off to the Failure Corpus if severity >= medium (FK-35 §35.3.9).

        Args:
            candidate: The governance incident candidate.
            verdict: The adjudication verdict.
        """
        if self._failure_corpus is None:
            return
        if verdict.severity not in _CORPUS_SEVERITIES:
            return
        corpus_candidate = to_corpus_incident_candidate(candidate, verdict)
        self._failure_corpus.record_incident(corpus_candidate)

    # ------------------------------------------------------------------
    # Telemetry helpers
    # ------------------------------------------------------------------

    def _emit_incident_opened(
        self,
        story_id: str,
        run_id: str,
        *,
        project_key: str,
        candidate: GovernanceIncidentCandidate,
    ) -> None:
        """Emit governance_incident_opened event (FK-35 §35.3.6, FK-91).

        Validates payload against the mandatory contract before emission
        (FAIL-CLOSED per ARCH-55 / events.py:332 region).

        Args:
            story_id: Story identifier.
            run_id: Run identifier.
            project_key: Project key.
            candidate: The newly created incident candidate.
        """
        payload: dict[str, object] = {
            "risk_score": candidate.risk_score,
            "event_count": candidate.event_count,
            "dominant_signals": candidate.dominant_signals,
        }
        validate_event_payload(EventType.GOVERNANCE_INCIDENT_OPENED, payload)
        self._emitter.emit(
            Event(
                story_id=story_id,
                event_type=EventType.GOVERNANCE_INCIDENT_OPENED,
                project_key=project_key,
                source_component=SOURCE_COMPONENT,
                phase=_PHASE,
                run_id=run_id,
                payload=payload,
            )
        )

    def _emit_adjudication(
        self,
        story_id: str,
        run_id: str,
        *,
        project_key: str,
        verdict: GovernanceAdjudicationVerdict,
        signal_type: str,
    ) -> None:
        """Emit governance_adjudication event (FK-35 §35.3.7, FK-91).

        Validates payload against the mandatory contract before emission
        (FAIL-CLOSED per ARCH-55 / events.py:332 region).

        Args:
            story_id: Story identifier.
            run_id: Run identifier.
            project_key: Project key.
            verdict: The adjudication verdict.
            signal_type: The triggering signal type wire value.
        """
        payload: dict[str, object] = {
            "incident_type": verdict.incident_type.value,
            "severity": verdict.severity.value,
            "confidence": verdict.confidence,
            "recommended_action": verdict.recommended_action.value,
            "signal_type": signal_type,
        }
        validate_event_payload(EventType.GOVERNANCE_ADJUDICATION, payload)
        self._emitter.emit(
            Event(
                story_id=story_id,
                event_type=EventType.GOVERNANCE_ADJUDICATION,
                project_key=project_key,
                source_component=SOURCE_COMPONENT,
                phase=_PHASE,
                run_id=run_id,
                payload=payload,
            )
        )

    def _emit_measure_applied(
        self,
        story_id: str,
        run_id: str,
        *,
        project_key: str,
        measure: GovernanceMeasure,
        severity: str,
    ) -> None:
        """Emit governance_measure_applied event (FK-35 §35.3.8, FK-91).

        Validates payload against the mandatory contract before emission
        (FAIL-CLOSED per ARCH-55 / events.py:332 region).

        Args:
            story_id: Story identifier.
            run_id: Run identifier.
            project_key: Project key.
            measure: The applied governance measure.
            severity: Severity wire value.
        """
        payload: dict[str, object] = {
            "measure": measure.value,
            "severity": severity,
        }
        validate_event_payload(EventType.GOVERNANCE_MEASURE_APPLIED, payload)
        self._emitter.emit(
            Event(
                story_id=story_id,
                event_type=EventType.GOVERNANCE_MEASURE_APPLIED,
                project_key=project_key,
                source_component=SOURCE_COMPONENT,
                phase=_PHASE,
                run_id=run_id,
                payload=payload,
            )
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _validate_window_payloads(payloads: list[dict[str, object]]) -> None:
    """Validate all payloads in a rolling-window list fail-closed (AC2/AC9).

    Applies :func:`~agentkit.governance.governance_observer.score._validate_signal_payload`
    to every payload in the list.  The first violation raises immediately —
    no partial processing, no silent skip.

    This function is the single authoritative validation gate for the
    ``handle_signal`` scored path.  It MUST be called BEFORE any score
    computation, candidate construction, or telemetry emission so that a
    corrupt DB row never silently passes through to the candidate path.

    Args:
        payloads: List of ``governance_signal`` payload dicts to validate.

    Raises:
        agentkit.telemetry.events.EventPayloadContractError: When a mandatory
            field (``risk_points``, ``signal_type``, ``actor``) is absent.
        agentkit.governance.governance_observer.score.GovernanceSignalPayloadError:
            When ``signal_type`` is unknown, is an immediate-stop signal, or
            ``risk_points`` is not a plain ``int``.
    """
    for payload in payloads:
        _validate_signal_payload(payload)


def _parse_signal_type(wire: str) -> GovernanceSignalType:
    """Parse a signal-type wire value (fail-closed on unknown value).

    Args:
        wire: Wire string value to look up.

    Returns:
        The matching :class:`GovernanceSignalType`.

    Raises:
        ValueError: When ``wire`` is not a known :class:`GovernanceSignalType`
            value (FAIL-CLOSED — no silent default, no mere logging).
    """
    try:
        return GovernanceSignalType(wire)
    except ValueError as exc:
        valid = sorted(t.value for t in GovernanceSignalType)
        raise ValueError(f"Unknown governance signal type: {wire!r}. FAIL-CLOSED: must be one of {valid}.") from exc


def _dominant_signals(payloads: list[dict[str, object]]) -> list[str]:
    """Return the top-3 most frequent signal types from the payloads.

    Args:
        payloads: List of event payload dicts.

    Returns:
        Up to 3 signal-type wire strings ordered by frequency (descending).
    """
    counter: Counter[str] = Counter()
    for p in payloads:
        st = p.get("signal_type")
        if isinstance(st, str):
            counter[st] += 1
    return [sig for sig, _ in counter.most_common(3)]


def _time_span_s(payloads: list[dict[str, object]]) -> float:
    """Compute elapsed seconds between the oldest and newest payload timestamps.

    ``occurred_at`` is injected by the reader from ``ExecutionEventRecord``
    (not part of the stored payload contract) and is expected to be a UNIX
    float.  A present-but-invalid value (non-numeric) is treated as a data
    integrity violation and raises ``ValueError`` rather than silently
    producing a corrupt ``0.0`` span (FAIL-CLOSED per ARCH-55).

    Args:
        payloads: List of event payload dicts (may include ``occurred_at``).

    Returns:
        Elapsed seconds, or ``0.0`` if fewer than two ``occurred_at`` values
        are present.

    Raises:
        ValueError: When a payload carries an ``occurred_at`` key whose value
            is present but is not a numeric type (int or float).
    """
    timestamps: list[float] = []
    for p in payloads:
        raw = p.get("occurred_at")
        if raw is None:
            continue
        if not isinstance(raw, (int, float)):
            raise ValueError(
                f"occurred_at value {raw!r} (type={type(raw).__name__!r}) is "
                "not numeric; FAIL-CLOSED — cannot compute time_span_s from a "
                "corrupt timestamp (ExecutionEventRecord integrity violation)"
            )
        timestamps.append(float(raw))
    if len(timestamps) < 2:
        return 0.0
    return max(timestamps) - min(timestamps)


def _summarise_payloads(payloads: list[dict[str, object]]) -> str:
    """Build a concise evidence summary from payloads.

    Args:
        payloads: List of event payload dicts.

    Returns:
        Human-readable summary string.
    """
    if not payloads:
        return "No governance signals in window."
    total: int = sum(int(rp) for p in payloads if isinstance(rp := p.get("risk_points"), (int, float)))
    signal_types = _dominant_signals(payloads)
    return (
        f"{len(payloads)} governance_signal events; total risk_points={total}; top signals: {', '.join(signal_types) or 'none'}"
    )


def lookup_risk_points(signal_type: GovernanceSignalType) -> int:
    """Return the risk-point weight for a scored signal type.

    Immediate-stop signals are not in :data:`RISK_POINTS` — this function
    MUST only be called for non-immediate-stop signal types.

    Args:
        signal_type: The signal type to look up.

    Returns:
        Risk-point weight.

    Raises:
        ValueError: When ``signal_type`` is an immediate-stop signal (which
            has no point value — it bypasses the scoring path entirely).
    """
    if signal_type in IMMEDIATE_STOP_SIGNALS:
        raise ValueError(
            f"{signal_type!r} is an immediate-stop signal and has no point value. It must be handled via the hard-stop path."
        )
    return RISK_POINTS[signal_type]
