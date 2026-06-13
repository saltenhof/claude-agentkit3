"""Rolling-window risk-score accumulation (FK-35 §35.3.1a / §35.3.5).

The score is computed as a pure READ of the ``execution_events`` table — no
in-memory state is kept between calls.  Each call issues the FK-35 §35.3.5
query: ``ORDER BY occurred_at DESC LIMIT window_size`` against
``governance_signal`` events, then sums ``payload.risk_points``.

The read is performed via an injected :class:`ExecutionEventReader` port so
the implementation remains testable without a live database.

Fail-closed payload contract (AC2/AC9)
--------------------------------------
Every ``governance_signal`` payload MUST carry ``signal_type`` (parseable via
:class:`~agentkit.governance.governance_observer.models.GovernanceSignalType`),
``risk_points`` (a real ``int``), and ``actor`` (present via the mandatory
payload contract in :data:`~agentkit.telemetry.events.MANDATORY_PAYLOAD_FIELDS`).

A malformed or unknown payload is a DATA INTEGRITY VIOLATION — it MUST NOT
silently lower the score.  :func:`_validate_signal_payload` raises on any
violation (FAIL-CLOSED).  Immediate-stop signals (GOVERNANCE_FILE_MANIPULATION /
SECRET_ACCESS) carry NO risk_points — they must never appear as scored
``governance_signal`` rows; seeing one in a DB window row is itself a contract
violation and is rejected with a clear error.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from agentkit.governance.governance_observer.models import (
    IMMEDIATE_STOP_SIGNALS,
    GovernanceSignalType,
)
from agentkit.telemetry.events import EventType, validate_event_payload

#: Source component label for governance-observer telemetry events.
SOURCE_COMPONENT: str = "agentkit.governance.governance_observer"

#: Wire value for the governance-signal event type (FK-35 §35.3.1a).
_GOVERNANCE_SIGNAL_WIRE: str = EventType.GOVERNANCE_SIGNAL.value


@runtime_checkable
class ExecutionEventReader(Protocol):
    """Port: read governance_signal events from the execution-events store.

    The production implementation delegates to
    :func:`~agentkit.state_backend.store.facade.load_execution_events_global`
    (or the story-dir-scoped variant for SQLite).  Tests inject a scripted
    fake at this boundary — never through the domain logic.

    The reader MUST return events ordered ``DESC`` by ``occurred_at`` and
    MUST apply the ``limit`` cap (rolling-window semantics per FK-35 §35.3.5).
    """

    def read_governance_signals(
        self,
        project_key: str,
        story_id: str,
        run_id: str,
        *,
        limit: int,
    ) -> list[dict[str, object]]:
        """Return the ``limit`` most-recent ``governance_signal`` event payloads.

        Args:
            project_key: Project scope.
            story_id: Story scope.
            run_id: Run scope.
            limit: Maximum events to return (rolling-window width).

        Returns:
            List of payload dicts ordered by ``occurred_at`` DESC.  Each dict
            MUST contain ``risk_points`` (int) at minimum.
        """
        ...

    def read_last_adjudication_ts(
        self,
        project_key: str,
        story_id: str,
        run_id: str,
        *,
        signal_type: str,
    ) -> float | None:
        """Return the UNIX timestamp of the last ``governance_adjudication`` event.

        Scoped to ``(project_key, story_id, run_id)`` and the given
        ``signal_type`` (FK-35 §35.3.11 cooldown is per-signal-type).

        Args:
            project_key: Project scope.
            story_id: Story scope.
            run_id: Run scope.
            signal_type: Signal type wire value to filter on.

        Returns:
            UNIX timestamp of the last adjudication for this signal type, or
            ``None`` if no prior adjudication exists.
        """
        ...


def compute_risk_score(
    reader: ExecutionEventReader,
    project_key: str,
    story_id: str,
    run_id: str,
    *,
    window_size: int,
) -> int:
    """Compute the current rolling-window risk score (FK-35 §35.3.1a / §35.3.5).

    Reads the ``window_size`` most-recent ``governance_signal`` events and sums
    their ``payload.risk_points`` values.  No in-memory state is retained; each
    call is an independent DB query.

    Payload integrity is enforced FAIL-CLOSED: each payload is validated via
    :func:`_validate_signal_payload` before its ``risk_points`` is summed.
    A malformed, unknown-signal_type, or immediate-stop-signal payload raises
    :class:`GovernanceSignalPayloadError` immediately — no silent coercion
    to 0, no skipping, no tolerance for corrupt stored data (AC2/AC9).

    Args:
        reader: Injected event reader port (DB or test double).
        project_key: Project scope.
        story_id: Story scope.
        run_id: Run scope.
        window_size: Number of most-recent events in the rolling window.

    Returns:
        Sum of ``risk_points`` across the window.

    Raises:
        GovernanceSignalPayloadError: When any payload in the window fails
            the fail-closed integrity contract.
    """
    payloads = reader.read_governance_signals(
        project_key, story_id, run_id, limit=window_size
    )
    return score_from_validated_payloads(payloads)


def score_from_validated_payloads(payloads: list[dict[str, object]]) -> int:
    """Validate and sum ``risk_points`` from a pre-read payload list.

    Applies the same fail-closed integrity contract as :func:`compute_risk_score`
    without issuing a DB query.  Callers that already hold the payload list
    (e.g. the observer's single-read path) use this to avoid a second read.

    Args:
        payloads: List of ``governance_signal`` payload dicts to validate and sum.

    Returns:
        Sum of ``risk_points`` across all validated payloads.

    Raises:
        GovernanceSignalPayloadError: When any payload fails the fail-closed
            integrity contract (unknown signal_type, immediate-stop signal_type,
            non-int risk_points, or missing mandatory field).
    """
    total = 0
    for payload in payloads:
        _validate_signal_payload(payload)
        # After _validate_signal_payload the risk_points value is a plain int.
        risk_points = payload["risk_points"]
        assert isinstance(risk_points, int)
        total += risk_points
    return total


class GovernanceSignalPayloadError(ValueError):
    """Raised when a scored ``governance_signal`` payload is malformed.

    FAIL-CLOSED (AC2/AC9): a stored ``governance_signal`` row that violates the
    mandatory payload contract or carries an immediate-stop signal type (which
    must NEVER appear as a scored row) is a data-integrity violation.  The score
    path does NOT silently coerce or skip malformed rows.

    Args:
        detail: Human-readable description of the offending field/value.
    """

    def __init__(self, detail: str) -> None:
        super().__init__(
            f"governance_signal payload integrity violation (FAIL-CLOSED): {detail}"
        )


def _validate_signal_payload(payload: dict[str, object]) -> None:
    """Enforce the fail-closed payload contract for a scored governance_signal row.

    Checks performed (in order):
    1. Mandatory field presence via ``validate_event_payload`` — raises
       :class:`~agentkit.telemetry.events.EventPayloadContractError` on missing
       fields (``risk_points``, ``signal_type``, ``actor``).
    2. ``signal_type`` is parseable via
       :class:`~agentkit.governance.governance_observer.models.GovernanceSignalType`
       — raises :class:`GovernanceSignalPayloadError` for unknown values.
    3. ``signal_type`` is NOT an immediate-stop signal — immediate-stop signals
       (GOVERNANCE_FILE_MANIPULATION / SECRET_ACCESS) have NO point value and
       MUST NOT appear as scored rows; seeing one here is a contract violation.
    4. ``risk_points`` is a real ``int`` (booleans excluded) — raises
       :class:`GovernanceSignalPayloadError` for missing, float, str, or other
       non-int values.

    Args:
        payload: The ``governance_signal`` event payload dict to validate.

    Raises:
        agentkit.telemetry.events.EventPayloadContractError: When a mandatory
            field (``risk_points``, ``signal_type``, ``actor``) is absent.
        GovernanceSignalPayloadError: When ``signal_type`` is unknown, is an
            immediate-stop signal, or ``risk_points`` is not a plain ``int``.
    """
    # Step 1 — mandatory field presence (raises EventPayloadContractError on miss)
    validate_event_payload(EventType.GOVERNANCE_SIGNAL, payload)

    # Step 2 — parse signal_type through the closed enum
    raw_signal = payload["signal_type"]
    try:
        signal_type = GovernanceSignalType(str(raw_signal))
    except ValueError as exc:
        valid = sorted(t.value for t in GovernanceSignalType)
        raise GovernanceSignalPayloadError(
            f"signal_type={raw_signal!r} is not a known GovernanceSignalType "
            f"(valid: {valid})"
        ) from exc

    # Step 3 — immediate-stop signals must NEVER be scored
    if signal_type in IMMEDIATE_STOP_SIGNALS:
        raise GovernanceSignalPayloadError(
            f"signal_type={signal_type.value!r} is an immediate-stop signal and "
            "must not appear as a scored governance_signal row — it bypasses the "
            "rolling-window accumulator entirely (FK-93 §93.6)"
        )

    # Step 4 — risk_points must be a plain int (not float, not str, not bool)
    risk_points = payload["risk_points"]
    if not isinstance(risk_points, int) or isinstance(risk_points, bool):
        raise GovernanceSignalPayloadError(
            f"risk_points={risk_points!r} is not an int "
            f"(type={type(risk_points).__name__!r}); FAIL-CLOSED"
        )
