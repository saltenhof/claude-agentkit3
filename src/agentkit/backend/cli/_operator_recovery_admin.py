"""Administrative and service-gap operator recovery command handlers."""

from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import argparse
    from collections.abc import Callable

    from agentkit.harness_client.projectedge.client import ProjectEdgeClient

from ._operator_recovery_phase import _build_control_plane_client


def _cmd_admin_abort(
    args: argparse.Namespace,
    *,
    client_builder: Callable[[str, str], ProjectEdgeClient] = _build_control_plane_client,
) -> int:
    """Handle ``agentkit admin-abort`` (AG3-138, FK-91 Rule 10, FK-55 §55.5).

    A thin REST adapter onto ``POST /v1/project-edge/operations/{op_id}/
    admin-abort`` (``admin_abort_inflight_operation``): it validates inputs
    locally and delegates the abort EXECUTION (epoch-fence, partial write->repair
    routing, audit) to the core. It NEVER opens a DB connection and builds no
    second semantics -- no own runtime/DB path (Rule 10; the delegation is
    test-pinned).

    Args:
        args: Parsed CLI arguments.

    Returns:
        0 on a successful terminal ``aborted``/``repair``/``resolved`` result, 1 on
        error/unreachable. (``resolved`` is returned when the target was an open
        ``repair`` state that this call closed out, lifting the mutation lock, AC10.)
    """
    from urllib.error import URLError

    from agentkit.backend.control_plane.models import AdminAbortRequest
    from agentkit.backend.exceptions import ControlPlaneApiError

    base_url = getattr(args, "base_url", None)
    if not base_url:
        print(
            "admin-abort failed [MissingBaseUrl]: --base-url is required to reach "
            "the control plane over REST (the operator CLI never runs the core "
            "in-process; FK-10 §10.1.0 I3).",
            file=sys.stderr,
        )
        return 1
    try:
        request = AdminAbortRequest(
            session_id=args.session,
            principal_type=args.principal,
            reason=args.reason,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"admin-abort failed [InvalidRequest]: {exc}", file=sys.stderr)
        return 1

    project_root = str(getattr(args, "project_root", ".") or ".")
    try:
        client = client_builder(str(base_url), project_root)
        result = client.admin_abort_operation(op_id=args.op_id, request=request)
    except ControlPlaneApiError as exc:
        print(f"admin-abort failed [{exc.error_code}]: {exc}", file=sys.stderr)
        return 1
    except URLError as exc:
        print(f"admin-abort failed [BackendUnreachable]: {exc}", file=sys.stderr)
        return 1
    except (RuntimeError, json.JSONDecodeError) as exc:
        print(f"admin-abort failed [TransportError]: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"admin-abort failed [InvalidBaseUrl]: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result.model_dump(mode="json"), sort_keys=True))
    # 'aborted'/'repair' (claimed target) and 'resolved' (repair target closed out,
    # AC10) are all successful terminal outcomes of the admin-abort path.
    return 0 if result.status in ("aborted", "repair", "resolved") else 1


def _cmd_reset_escalation(args: argparse.Namespace) -> int:
    """Handle ``agentkit reset-escalation`` (AG3-076, Class C — service gap).

    Args:
        args: Parsed CLI arguments.

    Returns:
        Always 1 (service gap).
    """
    _ = args  # story ID acknowledged but no authorized service exists
    print(
        "[ServiceGap] no authorized reset-escalation service — reported as service gap "
        "(owner: Lifecycle-Wave-3/PO-assignment-required)",
        file=sys.stderr,
    )
    return 1


def _cmd_cleanup(args: argparse.Namespace) -> int:
    """Handle ``agentkit cleanup`` (AG3-076, Class C — fail-closed).

    Aborts fail-closed because the PID/TTL liveness check service is missing.
    No locks are deactivated and no worktree is removed.

    Args:
        args: Parsed CLI arguments.

    Returns:
        Always 1 (fail-closed service gap).
    """
    _ = args  # story ID acknowledged but cleanup is unsafe without liveness check
    print(
        "[ServiceGap] PID/TTL liveness check service missing — cleanup aborted fail-closed "
        "(owner: FK-71 §67.3 / PO-assignment-required). "
        "No locks were deactivated, no worktree was removed.",
        file=sys.stderr,
    )
    return 1


def _cmd_override_integrity(args: argparse.Namespace) -> int:
    """Handle ``agentkit override-integrity`` (AG3-076, Class C — service gap).

    Args:
        args: Parsed CLI arguments (``--story`` and ``--reason`` are present).

    Returns:
        Always 1 (service gap).
    """
    _ = args  # story/reason acknowledged; no authorized service exists
    print(
        "[ServiceGap] no authorized integrity-override service — reported as service gap "
        "(owner: AG3-060/Closure-Override/PO-assignment-required)",
        file=sys.stderr,
    )
    return 1


__all__ = ["_cmd_admin_abort", "_cmd_cleanup", "_cmd_override_integrity", "_cmd_reset_escalation"]
