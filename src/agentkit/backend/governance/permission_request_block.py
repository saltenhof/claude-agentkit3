"""Visible fail-closed blocking around central permission-request persistence."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING
from uuid import uuid4

from agentkit.backend.governance.capability_blocks import CAPABILITY_DENIED_REASON
from agentkit.backend.governance.hook_event_inputs import _event_tool
from agentkit.backend.governance.protocols import GuardVerdict, ViolationType

if TYPE_CHECKING:
    from collections.abc import Callable

    from agentkit.backend.governance.guard_evaluation import HookEvent
    from agentkit.backend.governance.principal_capabilities import CapabilityHull
    from agentkit.harness_client.projectedge.governance_client import GovernanceEdgeClient


def open_permission_request_block(
    event: HookEvent,
    verdict: object,
    *,
    project_key: str | None,
    story_id: str | None,
    run_id: str | None,
    hull: CapabilityHull | None,
    client_factory: Callable[[], GovernanceEdgeClient],
    ttl_seconds: int,
) -> GuardVerdict:
    """Persist the canonical request or return a named persistence-fault block."""
    from agentkit.backend.control_plane.models import PermissionRequestOpenRequest

    request_id = str(uuid4())
    try:
        if project_key is None or story_id is None or run_id is None or hull is None:
            raise RuntimeError("canonical permission request context is incomplete")
        request = PermissionRequestOpenRequest(
            request_id=request_id,
            project_key=project_key,
            story_id=story_id,
            run_id=run_id,
            principal_type=hull.principal_type,
            tool_name=_event_tool(event),
            operation_class=hull.operation_class,
            path_classes=hull.path_classes,
            request_fingerprint=_request_fingerprint(event, hull),
            ttl_seconds=ttl_seconds,
        )
        request_id = client_factory().open_permission_request(request).request_id
    except Exception as exc:  # noqa: BLE001 -- mapped to a visible hard block
        reason = getattr(verdict, "reason", CAPABILITY_DENIED_REASON)
        return GuardVerdict.block(
            "principal_capability",
            ViolationType.UNAUTHORIZED_OPERATION,
            f"{reason}; canonical permission request persistence failed closed: {exc}",
            detail={
                "capability_rule_id": getattr(verdict, "rule_id", None),
                "permission_request_persist_failed": True,
                "fault_class": type(exc).__name__,
            },
        )
    return GuardVerdict.block(
        "principal_capability",
        ViolationType.UNAUTHORIZED_OPERATION,
        getattr(verdict, "reason", CAPABILITY_DENIED_REASON),
        detail={
            "capability_rule_id": getattr(verdict, "rule_id", None),
            "permission_request_opened": True,
            "permission_request_id": request_id,
        },
    )


def _request_fingerprint(event: HookEvent, hull: CapabilityHull) -> str:
    payload = {
        "operation": event.operation,
        "operation_args": event.operation_args,
        "principal_type": hull.principal_type,
        "operation_class": hull.operation_class,
        "path_classes": hull.path_classes,
    }
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


__all__ = ["open_permission_request_block"]
