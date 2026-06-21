"""Cooldown check for governance adjudication (FK-35 §35.3.11).

Adjudication is suppressed when the last ``governance_adjudication`` event
for the same ``(project_key, story_id, run_id, signal_type)`` is more recent
than ``cooldown_s`` seconds ago.  Other signal types are unaffected.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agentkit.backend.governance.governance_observer.score import ExecutionEventReader


def should_adjudicate(
    reader: ExecutionEventReader,
    project_key: str,
    story_id: str,
    run_id: str,
    *,
    signal_type: str,
    cooldown_s: int,
) -> bool:
    """Determine whether adjudication should run for this signal type.

    Returns ``True`` when no prior adjudication exists for this signal type or
    the last one occurred more than ``cooldown_s`` seconds ago (FK-35 §35.3.11).
    The cooldown is scoped to ``(project_key, story_id, run_id, signal_type)``
    — other signal types are never blocked by this check.

    Args:
        reader: Injected event reader port.
        project_key: Project scope.
        story_id: Story scope.
        run_id: Run scope.
        signal_type: Signal type wire value to check the cooldown for.
        cooldown_s: Cooldown window in seconds (``governance.cooldown_s``).

    Returns:
        ``True`` if adjudication is allowed, ``False`` if still in cooldown.
    """
    last_ts = reader.read_last_adjudication_ts(
        project_key, story_id, run_id, signal_type=signal_type
    )
    if last_ts is None:
        return True
    elapsed = _now_utc_ts() - last_ts
    return elapsed > cooldown_s


def _now_utc_ts() -> float:
    """Return the current UTC time as a UNIX timestamp.

    Returns:
        Current UTC UNIX timestamp.
    """
    return datetime.now(UTC).timestamp()
