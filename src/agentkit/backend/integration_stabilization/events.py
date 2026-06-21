"""Telemetry event helpers for the integration-stabilization BC.

Events are aligned with formal-spec/integration-stabilization/events.md.
Producers per formal-spec:
- ``integration_manifest_approved``     → human_cli
- ``stabilization_campaign_started``    → pipeline_deterministic
- ``integration_verify_passed``         → pipeline_deterministic
- ``integration_verify_failed``         → pipeline_deterministic
- ``undeclared_surface_detected``       → guard_system
- ``stabilization_budget_exhausted``    → guard_system
- ``manifest_amendment_requested``      → human_cli
- ``stability_gate_passed``             → pipeline_deterministic

This module owns the wire-key constants (ARCH-55: English, SSOT) and the
factory helpers that produce correctly-keyed ``Event`` payloads.
"""

from __future__ import annotations

from datetime import UTC, datetime

from agentkit.backend.telemetry.events import Event, EventType, validate_event_payload

__all__ = [
    "INTEGRATION_MANIFEST_APPROVED",
    "UNDECLARED_SURFACE_DETECTED",
    "STABILIZATION_BUDGET_EXHAUSTED",
    "STABILITY_GATE_PASSED",
    "STABILIZATION_CAMPAIGN_STARTED",
    "INTEGRATION_VERIFY_PASSED",
    "INTEGRATION_VERIFY_FAILED",
    "MANIFEST_AMENDMENT_REQUESTED",
    "emit_integration_manifest_approved",
    "emit_undeclared_surface_detected",
    "emit_stabilization_budget_exhausted",
    "emit_stability_gate_passed",
]

#: Wire-key constants for integration-stabilization events (ARCH-55).
INTEGRATION_MANIFEST_APPROVED: str = "integration_manifest_approved"
UNDECLARED_SURFACE_DETECTED: str = "undeclared_surface_detected"
STABILIZATION_BUDGET_EXHAUSTED: str = "stabilization_budget_exhausted"
STABILITY_GATE_PASSED: str = "stability_gate_passed"
STABILIZATION_CAMPAIGN_STARTED: str = "stabilization_campaign_started"
INTEGRATION_VERIFY_PASSED: str = "integration_verify_passed"
INTEGRATION_VERIFY_FAILED: str = "integration_verify_failed"
MANIFEST_AMENDMENT_REQUESTED: str = "manifest_amendment_requested"

#: Producer wire-keys per formal-spec events.md.
_PRODUCER_GUARD_SYSTEM: str = "guard_system"
_PRODUCER_PIPELINE_DETERMINISTIC: str = "pipeline_deterministic"
_PRODUCER_HUMAN_CLI: str = "human_cli"


def emit_integration_manifest_approved(
    *,
    story_id: str,
    project_key: str,
    run_id: str,
    manifest_version: int,
    manifest_hash: str,
) -> Event:
    """Build an ``integration_manifest_approved`` telemetry event.

    Producer: human_cli (formal-spec events.md).

    Args:
        story_id: Story identifier.
        project_key: Project key.
        run_id: Active run identifier.
        manifest_version: Version of the approved manifest.
        manifest_hash: Content hash of the approved manifest.

    Returns:
        A frozen ``Event`` ready for emission.
    """
    payload: dict[str, object] = {
        "event_name": INTEGRATION_MANIFEST_APPROVED,
        "manifest_version": manifest_version,
        "manifest_hash": manifest_hash,
    }
    validate_event_payload(EventType.INTEGRATION_MANIFEST_APPROVED, payload)
    return Event(
        story_id=story_id,
        event_type=EventType.INTEGRATION_MANIFEST_APPROVED,
        timestamp=datetime.now(UTC),
        project_key=project_key,
        run_id=run_id,
        source_component=_PRODUCER_HUMAN_CLI,
        phase="setup",
        payload=payload,
    )


def emit_undeclared_surface_detected(
    *,
    story_id: str,
    project_key: str,
    run_id: str,
    surface_path: str,
    check_layer: str = "layer_1_structural",
) -> Event:
    """Build an ``undeclared_surface_detected`` telemetry event.

    Producer: guard_system (formal-spec events.md).
    Invariant: declared_surfaces_only_is_deterministic — this event is
    emitted by a deterministic structural check, never by LLM judgment.

    Args:
        story_id: Story identifier.
        project_key: Project key.
        run_id: Active run identifier.
        surface_path: The path of the undeclared surface detected.
        check_layer: The check layer that detected the violation.

    Returns:
        A frozen ``Event`` ready for emission.
    """
    payload: dict[str, object] = {
        "event_name": UNDECLARED_SURFACE_DETECTED,
        "surface_path": surface_path,
        "check_layer": check_layer,
        "guard": "seam_allowlist_guard",
        "detail": f"undeclared surface detected: {surface_path!r}",
    }
    validate_event_payload(EventType.UNDECLARED_SURFACE_DETECTED, payload)
    return Event(
        story_id=story_id,
        event_type=EventType.UNDECLARED_SURFACE_DETECTED,
        timestamp=datetime.now(UTC),
        project_key=project_key,
        run_id=run_id,
        source_component=_PRODUCER_GUARD_SYSTEM,
        phase="implementation",
        payload=payload,
    )


def emit_stabilization_budget_exhausted(
    *,
    story_id: str,
    project_key: str,
    run_id: str,
    exhausted_caps: list[str],
) -> Event:
    """Build a ``stabilization_budget_exhausted`` telemetry event.

    Producer: guard_system (formal-spec events.md).
    Invariant: budget_exhaustion_blocks_live_capability.

    Args:
        story_id: Story identifier.
        project_key: Project key.
        run_id: Active run identifier.
        exhausted_caps: Names of the exhausted budget caps.

    Returns:
        A frozen ``Event`` ready for emission.
    """
    payload: dict[str, object] = {
        "event_name": STABILIZATION_BUDGET_EXHAUSTED,
        "exhausted_caps": exhausted_caps,
        "guard": "stabilization_budget_guard",
        "detail": f"stabilization budget exhausted: {exhausted_caps}",
    }
    validate_event_payload(EventType.STABILIZATION_BUDGET_EXHAUSTED, payload)
    return Event(
        story_id=story_id,
        event_type=EventType.STABILIZATION_BUDGET_EXHAUSTED,
        timestamp=datetime.now(UTC),
        project_key=project_key,
        run_id=run_id,
        source_component=_PRODUCER_GUARD_SYSTEM,
        phase="implementation",
        payload=payload,
    )


def emit_stability_gate_passed(
    *,
    story_id: str,
    project_key: str,
    run_id: str,
    achieved_targets: list[str],
) -> Event:
    """Build a ``stability_gate_passed`` telemetry event.

    Producer: pipeline_deterministic (formal-spec events.md).

    Args:
        story_id: Story identifier.
        project_key: Project key.
        run_id: Active run identifier.
        achieved_targets: Names of integration targets that passed.

    Returns:
        A frozen ``Event`` ready for emission.
    """
    payload: dict[str, object] = {
        "event_name": STABILITY_GATE_PASSED,
        "achieved_targets": achieved_targets,
    }
    validate_event_payload(EventType.STABILITY_GATE_PASSED, payload)
    return Event(
        story_id=story_id,
        event_type=EventType.STABILITY_GATE_PASSED,
        timestamp=datetime.now(UTC),
        project_key=project_key,
        run_id=run_id,
        source_component=_PRODUCER_PIPELINE_DETERMINISTIC,
        phase="implementation",
        payload=payload,
    )
