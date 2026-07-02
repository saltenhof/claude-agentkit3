"""Hook-side REST edge seam for governance state mediation (AG3-129).

FK-10 §10.1.0 I1/I3: the short-lived hook process is a REST *requester* at the
core, never a direct-DB reader/writer. This module is the ONE seam through which
every hook path builds its REST client and REST telemetry emitter, so guard
dispatch (``runner``) and the generic guard-evaluation chain
(``guard_evaluation``) share a single client factory (and a single test
monkeypatch point).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.backend.telemetry.emitters import EventEmitter
    from agentkit.backend.telemetry.events import Event, EventType
    from agentkit.harness_client.projectedge.governance_client import (
        GovernanceEdgeClient,
    )

logger = logging.getLogger(__name__)


def governance_edge_client(project_root: Path) -> GovernanceEdgeClient:
    """Build the hook-side governance REST client (AG3-129).

    The client mediates guard-counter, worker-health, telemetry and story-type
    reads at the core over REST (FK-10 §10.1.0 I1). It reads only the local
    control-plane config -- never a database DSN, never ``psycopg``.

    Args:
        project_root: Project root carrying the local control-plane config.

    Returns:
        A configured governance edge client.
    """
    from agentkit.harness_client.projectedge.governance_client import (
        build_governance_edge_client,
    )

    return build_governance_edge_client(project_root)


def build_rest_event_emitter(
    project_root: Path,
    *,
    project_key: str,
    run_id: str,
    default_source_component: str = "telemetry_service",
    strict_query: bool = False,
) -> EventEmitter:
    """Build the hook's REST telemetry emitter, fail-soft to a ``NullEmitter``.

    AG3-129: telemetry is server-mediated (FK-10 §10.1.0 I1) and non-blocking
    (FK-30). When the local control-plane config is unreadable the emitter
    degrades to a ``NullEmitter`` -- emits are dropped and observability reads
    return ``[]`` (the same fail-soft the direct-DB emitter had on a backend
    fault), NEVER a direct-DB fallback and NEVER a silent block.

    Args:
        project_root: Project root carrying the local control-plane config.
        project_key: Active project scope for events omitting their own key.
        run_id: Active run scope for events omitting their own run id.
        default_source_component: Source-component label applied to generic
            ``telemetry_service`` events.
        strict_query: When ``True`` (enforcement readers, e.g. the web-call
            budget guard), ``query`` RAISES on a core-unreachable read so the
            caller can fail CLOSED -- ``[]`` must NOT be mistaken for "zero
            events" (AC5 / §2.1.4). Observability emitters keep ``False``.

    Returns:
        A REST-backed emitter, or a ``NullEmitter`` when the client is
        unavailable (non-strict) / a fail-closed strict null when the client is
        unavailable and ``strict_query`` is set.
    """
    from agentkit.backend.telemetry.emitters import NullEmitter
    from agentkit.backend.telemetry.rest_emitter import RestEventEmitter

    try:
        client = governance_edge_client(project_root)
    except Exception:  # noqa: BLE001 -- unreadable config -> fail-soft null emitter (no DB fallback)
        logger.warning(
            "Governance REST client unavailable; telemetry degraded to NullEmitter "
            "(non-blocking; no direct-DB fallback)",
            exc_info=True,
        )
        if strict_query:
            # An enforcement reader with no reachable core must not silently read
            # ``[]`` as zero -- surface the unavailability so the guard blocks.
            return _UnavailableStrictEmitter()
        return NullEmitter()
    return RestEventEmitter(
        client,
        project_key=project_key,
        run_id=run_id,
        default_source_component=default_source_component,
        strict_query=strict_query,
    )


class _UnavailableStrictEmitter:
    """Strict fail-closed emitter used when no core client can be built.

    ``emit`` is a non-blocking no-op (telemetry never blocks); ``query`` RAISES
    so an enforcement reader (web-call budget guard) fails CLOSED instead of
    reading a spurious empty counter.
    """

    def emit(self, event: Event) -> None:
        """Drop the event (non-blocking); no direct-DB fallback."""
        _ = event

    def query(
        self, story_id: str, event_type: EventType | None = None
    ) -> list[Event]:
        """Fail closed: the counter cannot be read without a reachable core."""
        _ = story_id, event_type
        raise RuntimeError(
            "web_call_counter_unavailable: no reachable core to read the "
            "canonical counter (fail-closed; no direct-DB fallback)",
        )


__all__ = ["build_rest_event_emitter", "governance_edge_client"]
