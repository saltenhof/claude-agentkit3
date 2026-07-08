"""Operator recovery and telemetry CLI command handlers."""

from __future__ import annotations

import json
import os
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import argparse
    from collections.abc import Callable
    from datetime import datetime

    from agentkit.backend.control_plane.models import (
        ControlPlaneMutationResult,
        PhaseMutationRequest,
    )
    from agentkit.harness_client.projectedge.client import ProjectEdgeClient

_STORY_ID_FIELD_LABEL = "Story ID"
_PROJECT_ROOT_HELP = "Project root directory"
_RUN_ID_HELP = "Run ID"
_OP_ID_HELP = (
    "Client-supplied idempotency key (FK-91 Rule 5). Omit to mint one "
    "client-side; reuse the SAME value to safely retry an ambiguous call."
)
_PROJECT_KEY_OVERRIDE_HELP = "Project key override"
_CONFIG_PATH_OVERRIDE_HELP = "Config path override"


_VALID_PHASES = frozenset({"setup", "exploration", "implementation", "closure"})


class _ConfigResolutionError(Exception):
    """Raised when ``--config`` is provided but fails to yield a project_key."""



def _resolve_project_key(args: argparse.Namespace) -> str | None:
    """Resolve ``project_key`` from CLI args with config and env fallback.

    Resolution order (story §2.1.1):

    1. ``--project`` flag (explicit override).
    2. ``--config`` path: load :class:`~agentkit.backend.config.models.ProjectConfig`
       and read ``project_key``.  When ``--config`` IS provided but the config
       cannot be loaded or yields no key, raises :class:`_ConfigResolutionError`
       (fail-closed — do NOT silently fall through to the env var).
    3. ``AGENTKIT_PROJECT_KEY`` environment variable (only reached when
       ``--config`` was NOT provided).

    Args:
        args: Parsed argparse namespace (may have ``project`` and/or ``config``).

    Returns:
        The resolved project key string, or ``None`` if none found.

    Raises:
        _ConfigResolutionError: When ``--config`` is provided but missing,
            unreadable, or yields no ``project_key``.
    """
    explicit = getattr(args, "project", None)
    if explicit:
        return str(explicit)

    config_path_raw = getattr(args, "config", None)
    if config_path_raw is not None:
        # --config was explicitly provided (even if blank/empty): fail-closed.
        # An empty string is an invalid path — do NOT fall through to the env
        # var.  Only when --config is completely absent (None, the argparse
        # default) may resolution continue to AGENTKIT_PROJECT_KEY.
        stripped = config_path_raw.strip() if isinstance(config_path_raw, str) else ""
        if not stripped:
            raise _ConfigResolutionError(
                "--config was provided but the value is empty or blank. "
                "Pass a valid config file path or omit --config entirely."
            )
        try:
            from agentkit.backend.config.loader import load_project_config

            cfg = load_project_config(Path(stripped))
            key = getattr(cfg, "project_key", None)
            if key:
                return str(key)
            raise _ConfigResolutionError(
                f"Config at {stripped!r} loaded successfully but "
                "contains no project_key."
            )
        except _ConfigResolutionError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise _ConfigResolutionError(
                f"Failed to load config from {stripped!r}: {exc}"
            ) from exc

    env_key = os.environ.get("AGENTKIT_PROJECT_KEY", "").strip()
    return env_key or None


def _parse_since_cutoff(since_raw: str) -> datetime:
    """Parse a ``--since`` value into a timezone-aware :class:`datetime`.

    Supported forms (MAJOR 5 fix):

    - Window: ``{N}d``, ``{N}h``, ``{N}m`` (e.g. ``7d``, ``24h``, ``30m``).
      Resolved as ``now(UTC) - timedelta``.
    - ISO-8601 timestamp (with or without timezone).  When no timezone is
      given the value is treated as UTC (tz-aware comparison requires a
      timezone).

    Args:
        since_raw: Raw ``--since`` string from the CLI.

    Returns:
        A timezone-aware :class:`datetime` representing the cutoff.

    Raises:
        ValueError: When the value cannot be parsed into either form.
    """
    import re
    from datetime import UTC, datetime, timedelta

    # Window form: Nd / Nh / Nm
    window_match = re.fullmatch(r"(\d+)([dhm])", since_raw.strip())
    if window_match:
        qty = int(window_match.group(1))
        unit = window_match.group(2)
        if unit == "d":
            delta = timedelta(days=qty)
        elif unit == "h":
            delta = timedelta(hours=qty)
        else:
            delta = timedelta(minutes=qty)
        return datetime.now(UTC) - delta

    # ISO-8601 form: try fromisoformat (Python 3.11+ handles Z suffix too)
    try:
        dt = datetime.fromisoformat(since_raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    except ValueError:
        pass

    raise ValueError(
        f"Cannot parse --since {since_raw!r}: expected a window like 7d/24h/30m "
        "or an ISO-8601 timestamp (e.g. 2025-01-01T00:00:00Z)."
    )


def _setup_operator_recovery_subparsers(
    subparsers: argparse._SubParsersAction,  # type: ignore[type-arg]
) -> None:
    """Register AG3-076 operator/recovery CLI subcommands (FK-20, FK-68, FK-54).

    Args:
        subparsers: The top-level subparsers action from the main parser.
    """
    # run-phase
    run_phase_parser = subparsers.add_parser(
        "run-phase",
        help="Dispatch a single pipeline phase via the control plane (AG3-076)",
    )
    run_phase_parser.add_argument("phase", help="Phase name: setup/exploration/implementation/closure")
    run_phase_parser.add_argument("--story", required=True, help=_STORY_ID_FIELD_LABEL)
    run_phase_parser.add_argument("--run", required=True, help=_RUN_ID_HELP)
    run_phase_parser.add_argument("--session", required=True, help="Session ID")
    run_phase_parser.add_argument("--principal", required=True, help="Principal type")
    run_phase_parser.add_argument(
        "--worktree",
        action="append",
        nargs=1,
        required=True,
        dest="worktree",
        metavar="PATH",
        help="Worktree root path (may be repeated)",
    )
    run_phase_parser.add_argument("--project", required=False, help=_PROJECT_KEY_OVERRIDE_HELP)
    run_phase_parser.add_argument("--config", required=False, help=_CONFIG_PATH_OVERRIDE_HELP)
    run_phase_parser.add_argument("--project-root", default=".", help=_PROJECT_ROOT_HELP)
    run_phase_parser.add_argument("--op-id", required=False, help=_OP_ID_HELP)
    run_phase_parser.add_argument(
        "--base-url",
        required=False,
        help="Core control-plane base URL for the phase-dispatch REST call (AG3-130).",
    )

    # resume
    resume_parser = subparsers.add_parser(
        "resume",
        help="Resume a PAUSED pipeline phase via the control plane (AG3-130)",
    )
    resume_parser.add_argument("phase", help="Phase name: setup/exploration/implementation/closure")
    resume_parser.add_argument("--story", required=True, help=_STORY_ID_FIELD_LABEL)
    resume_parser.add_argument("--run", required=True, help=_RUN_ID_HELP)
    resume_parser.add_argument("--session", required=True, help="Session ID")
    resume_parser.add_argument("--principal", required=True, help="Principal type")
    resume_parser.add_argument(
        "--worktree",
        action="append",
        nargs=1,
        required=True,
        dest="worktree",
        metavar="PATH",
        help="Worktree root path (may be repeated)",
    )
    resume_parser.add_argument("--trigger", required=True, help="Resume trigger event name")
    resume_parser.add_argument("--project", required=False, help=_PROJECT_KEY_OVERRIDE_HELP)
    resume_parser.add_argument("--config", required=False, help=_CONFIG_PATH_OVERRIDE_HELP)
    resume_parser.add_argument("--project-root", default=".", help=_PROJECT_ROOT_HELP)
    resume_parser.add_argument("--op-id", required=False, help=_OP_ID_HELP)
    resume_parser.add_argument(
        "--base-url",
        required=False,
        help="Core control-plane base URL for the resume REST call (AG3-130).",
    )

    # admin-abort (AG3-138: admin_abort_inflight_operation, admin_transition)
    admin_abort_parser = subparsers.add_parser(
        "admin-abort",
        help="Administratively abort a hanging server-owned in-flight operation (AG3-138)",
    )
    admin_abort_parser.add_argument("op_id", help="Target in-flight operation id")
    admin_abort_parser.add_argument("--session", required=True, help="Admin session ID (audited)")
    admin_abort_parser.add_argument(
        "--principal", required=True, help="Admin principal type (audited)"
    )
    admin_abort_parser.add_argument(
        "--reason", required=True, help="Mandatory audited justification for the abort"
    )
    admin_abort_parser.add_argument("--project-root", default=".", help=_PROJECT_ROOT_HELP)
    admin_abort_parser.add_argument(
        "--base-url",
        required=False,
        help="Core control-plane base URL for the admin-abort REST call (AG3-138).",
    )

    # reset-escalation (Class C — service gap)
    reset_esc_parser = subparsers.add_parser(
        "reset-escalation",
        help="[ServiceGap] Reset an escalation record (AG3-076 — not yet implemented)",
    )
    reset_esc_parser.add_argument("--story", required=True, help=_STORY_ID_FIELD_LABEL)

    # cleanup (Class C — fail-closed without PID/TTL liveness)
    cleanup_parser = subparsers.add_parser(
        "cleanup",
        help="[ServiceGap] Cleanup story locks/worktree — aborted fail-closed (AG3-076)",
    )
    cleanup_parser.add_argument("--story", required=True, help=_STORY_ID_FIELD_LABEL)

    # status
    status_parser = subparsers.add_parser(
        "status",
        help="Show story phase state and weekly-review frame (AG3-076)",
    )
    status_parser.add_argument("--story", required=False, help=_STORY_ID_FIELD_LABEL)
    status_parser.add_argument("--project-root", default=".", help=_PROJECT_ROOT_HELP)

    # query-state
    query_state_parser = subparsers.add_parser(
        "query-state",
        help="Query story phase state or lock state (AG3-076)",
    )
    query_state_parser.add_argument("--story", required=False, help=_STORY_ID_FIELD_LABEL)
    query_state_parser.add_argument(
        "--locks",
        action="store_true",
        help="Query lock state (Class C — service gap)",
    )
    query_state_parser.add_argument("--project-root", default=".", help=_PROJECT_ROOT_HELP)

    # query-telemetry
    query_tel_parser = subparsers.add_parser(
        "query-telemetry",
        help="Query canonical telemetry events (AG3-076)",
    )
    query_tel_parser.add_argument("--story", required=False, help=_STORY_ID_FIELD_LABEL)
    query_tel_parser.add_argument("--run", required=False, help="Run ID filter")
    query_tel_parser.add_argument("--event", required=False, help="Event type filter")
    query_tel_parser.add_argument(
        "--since",
        required=False,
        help=(
            "Lower-bound window for event filtering. "
            "Supports {N}d/{N}h/{N}m (e.g. 7d, 24h, 30m) or an ISO-8601 timestamp."
        ),
    )
    query_tel_parser.add_argument("--project", required=False, help=_PROJECT_KEY_OVERRIDE_HELP)
    query_tel_parser.add_argument("--config", required=False, help=_CONFIG_PATH_OVERRIDE_HELP)
    query_tel_parser.add_argument("--project-root", default=".", help=_PROJECT_ROOT_HELP)

    # weekly-review (Class C for Failure-Corpus sections / Class A for renderer frame)
    subparsers.add_parser(
        "weekly-review",
        help="Weekly operator review frame with service-gap findings (AG3-076)",
    )

    # override-integrity (Class C — service gap)
    override_parser = subparsers.add_parser(
        "override-integrity",
        help="[ServiceGap] Override integrity gate (AG3-076 — not yet implemented)",
    )
    override_parser.add_argument("--story", required=True, help=_STORY_ID_FIELD_LABEL)
    override_parser.add_argument("--reason", required=True, help="Override justification (mandatory)")

    # export-telemetry
    export_tel_parser = subparsers.add_parser(
        "export-telemetry",
        help="Export a completed story run as a JSONL audit bundle (AG3-076, FK-68)",
    )
    export_tel_parser.add_argument("--story", required=True, help=_STORY_ID_FIELD_LABEL)
    export_tel_parser.add_argument("--run", required=True, help=_RUN_ID_HELP)
    export_tel_parser.add_argument("--output-dir", required=True, help="Directory to write the bundle into")
    export_tel_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Check output directory reachability/writability only",
    )


# --- run-phase / resume (REST to the control plane, AG3-130) --------------------


@dataclass(frozen=True)
class _PhaseCallContext:
    """Validated inputs for a control-plane phase REST call (AG3-130)."""

    project_key: str
    base_url: str
    project_root: str
    request: PhaseMutationRequest


def _build_control_plane_client(base_url: str, project_root: str) -> ProjectEdgeClient:
    """Build the official REST client for operator phase calls (AG3-130).

    The operator CLI is a thin Dev-Edge REST requester (FK-10 §10.1.0 I3): it
    reaches the core over the ``ProjectEdgeClient`` transport (urllib, structured
    ``ApiError``) -- no second HTTP stack and no in-process runtime build. The
    transport carries the FK-91 §91.1a Rule 11 version handshake: ``X-AK3-Client``
    (the installed package version, resolved inside the transport) plus
    ``X-AK3-Skill-Bundle`` from the project's authoritative prompt-bundle lock, so
    the production listener does not fail the mutation closed with HTTP 426
    (Codex B2). The publisher is required by the client constructor but never
    exercised here (operator dispatch is a pure core call; it publishes no local
    edge bundle).

    Args:
        base_url: The core control-plane base URL.
        project_root: The project root whose prompt-bundle lock supplies the bound
            skill-bundle version for the handshake header.

    Returns:
        A configured :class:`ProjectEdgeClient`.
    """
    from agentkit.harness_client.projectedge.client import (
        HttpsJsonTransport,
        LocalEdgePublisher,
        ProjectEdgeClient,
    )
    from agentkit.harness_client.projectedge.runtime import (
        read_bound_skill_bundle_version,
    )

    root = Path(project_root)
    return ProjectEdgeClient(
        transport=HttpsJsonTransport(
            base_url=base_url,
            skill_bundle_version=read_bound_skill_bundle_version(root),
        ),
        publisher=LocalEdgePublisher(project_root=root),
    )


def _phase_result_payload(result: ControlPlaneMutationResult) -> dict[str, object]:
    """Build the CLI stdout payload for a control-plane phase mutation result."""
    payload: dict[str, object] = {
        "status": result.status,
        "op_id": result.op_id,
        "operation_kind": result.operation_kind,
        "run_id": result.run_id,
        "phase": result.phase,
    }
    if result.phase_dispatch is not None:
        payload["phase_dispatch"] = {
            "phase": result.phase_dispatch.phase,
            "status": result.phase_dispatch.status,
            "reaction": result.phase_dispatch.reaction,
            "dispatched": result.phase_dispatch.dispatched,
            "next_phase": result.phase_dispatch.next_phase,
            "yield_status": result.phase_dispatch.yield_status,
            "rejection_reason": result.phase_dispatch.rejection_reason,
            "errors": list(result.phase_dispatch.errors),
        }
    return payload


def _prepare_phase_call(
    args: argparse.Namespace,
    verb: str,
    *,
    detail: dict[str, object] | None,
) -> _PhaseCallContext | int:
    """Validate CLI inputs and build the phase request (CLI-side, AG3-130).

    Local argument / phase validation stays on the CLI (story §2.1); the phase
    EXECUTION is delegated to the core over REST. Returns the validated call
    context, or an integer exit code when a fail-closed validation error was
    printed to stderr.

    Args:
        args: Parsed CLI arguments.
        verb: The CLI verb name for error messages (``run-phase`` / ``resume``).
        detail: Optional request ``detail`` payload (e.g. the resume trigger).

    Returns:
        A :class:`_PhaseCallContext` on success, or a non-zero exit code.
    """
    from agentkit.backend.control_plane.models import PhaseMutationRequest

    phase = args.phase
    if phase not in _VALID_PHASES:
        print(
            f"{verb} failed [InvalidPhase]: {phase!r} is not a valid phase. "
            f"Valid phases: {sorted(_VALID_PHASES)}. "
            "Note: 'verify' is a capability, not a top-level phase (see concept/_meta/bc-cut-decisions.md).",
            file=sys.stderr,
        )
        return 1

    # Resolve project_key: --project > --config > AGENTKIT_PROJECT_KEY (ERROR 2 fix).
    try:
        project_key = _resolve_project_key(args)
    except _ConfigResolutionError as exc:
        print(f"{verb} failed [ConfigResolutionError]: {exc}", file=sys.stderr)
        return 1
    if not project_key:
        print(
            f"{verb} failed [MissingProjectKey]: --project, --config-derived key, "
            "or AGENTKIT_PROJECT_KEY is required to identify the project.",
            file=sys.stderr,
        )
        return 1

    base_url = getattr(args, "base_url", None)
    if not base_url:
        print(
            f"{verb} failed [MissingBaseUrl]: --base-url is required to reach the "
            "control plane over REST (AG3-130; the operator CLI never runs the "
            "core in-process).",
            file=sys.stderr,
        )
        return 1

    # --worktree is action="append", nargs=1 -> list of single-element lists
    worktree_roots = [w[0] for w in args.worktree]

    try:
        request = PhaseMutationRequest(
            project_key=project_key,
            story_id=args.story,
            session_id=args.session,
            principal_type=args.principal,
            worktree_roots=worktree_roots,
            detail=detail or {},
            # FK-91 §91.1a Rule 5 (AG3-140): op_id is the client-supplied
            # idempotency key; the operator CLI mints one when --op-id is omitted
            # (the server no longer supplies a default). A replay of the SAME
            # op_id returns the stored result; a parallel same op_id is rejected
            # in-flight.
            op_id=getattr(args, "op_id", None) or f"op-{uuid.uuid4().hex}",
        )
    except Exception as exc:  # noqa: BLE001
        print(f"{verb} failed [InvalidRequest]: {exc}", file=sys.stderr)
        return 1

    return _PhaseCallContext(
        project_key=project_key,
        base_url=str(base_url),
        project_root=str(getattr(args, "project_root", ".") or "."),
        request=request,
    )


def _invoke_control_plane_phase(
    verb: str,
    ctx: _PhaseCallContext,
    call: Callable[[ProjectEdgeClient], ControlPlaneMutationResult],
    *,
    client_builder: Callable[[str, str], ProjectEdgeClient] = _build_control_plane_client,
) -> ControlPlaneMutationResult | None:
    """Run a control-plane phase call, mapping transport failures fail-closed.

    A structured core error (4xx/5xx stable-contract body) surfaces as
    :class:`ControlPlaneApiError`; an unreachable backend surfaces as
    ``URLError``; an invalid ``--base-url`` (unknown/malformed URL) surfaces as
    ``ValueError``; a malformed / non-contract response is a transport error. All
    map to a structured stderr message and a ``None`` return so the caller exits
    non-zero -- there is NO in-process fallback (FAIL-CLOSED, FK-10 §10.1.0 I3;
    Codex M2).

    Args:
        verb: The CLI verb name for error messages.
        ctx: The validated phase-call context (base URL + project root).
        call: The client call to run (returns a mutation result).

    Returns:
        The core :class:`ControlPlaneMutationResult`, or ``None`` on failure.
    """
    from urllib.error import URLError

    from agentkit.backend.exceptions import ControlPlaneApiError

    try:
        client = client_builder(ctx.base_url, ctx.project_root)
        return call(client)
    except ControlPlaneApiError as exc:
        print(f"{verb} failed [{exc.error_code}]: {exc}", file=sys.stderr)
    except URLError as exc:
        print(f"{verb} failed [BackendUnreachable]: {exc}", file=sys.stderr)
    # ``json.JSONDecodeError`` is a ``ValueError`` subclass: a malformed / non-
    # contract response is a TransportError (docstring), so this clause MUST come
    # BEFORE the bare ``ValueError`` (an invalid --base-url) — otherwise the
    # ValueError clause would swallow it (Sonar S1045: already-caught exception).
    except (RuntimeError, json.JSONDecodeError) as exc:
        print(f"{verb} failed [TransportError]: {exc}", file=sys.stderr)
    except ValueError as exc:
        print(f"{verb} failed [InvalidBaseUrl]: {exc}", file=sys.stderr)
    return None


def _cmd_run_phase(
    args: argparse.Namespace,
    *,
    client_builder: Callable[[str, str], ProjectEdgeClient] = _build_control_plane_client,
) -> int:
    """Handle ``agentkit run-phase`` (AG3-130, FK-10 §10.1.0 I3, FK-45).

    Dispatches a single pipeline phase by calling the canonical project-scoped
    control-plane route over REST. The CLI validates inputs locally and delegates
    the phase EXECUTION to the core -- it never instantiates a
    ``ControlPlaneRuntimeService`` in-process and opens no PostgreSQL connection.

    Args:
        args: Parsed CLI arguments.

    Returns:
        0 on committed/replayed, 1 on rejected/error/unreachable.
    """
    prepared = _prepare_phase_call(args, "run-phase", detail=None)
    if isinstance(prepared, int):
        return prepared

    result = _invoke_control_plane_phase(
        "run-phase",
        prepared,
        lambda client: client.run_phase(
            project_key=prepared.project_key,
            run_id=args.run,
            phase=args.phase,
            request=prepared.request,
        ),
        client_builder=client_builder,
    )
    if result is None:
        return 1

    print(json.dumps(_phase_result_payload(result), sort_keys=True))
    return 0 if result.status in ("committed", "replayed") else 1


def _cmd_resume(
    args: argparse.Namespace,
    *,
    client_builder: Callable[[str, str], ProjectEdgeClient] = _build_control_plane_client,
) -> int:
    """Handle ``agentkit resume`` (AG3-130, FK-45, FK-10 §10.1.0 I3).

    Resumes a PAUSED pipeline phase by calling the canonical project-scoped
    ``.../phases/{phase}/resume`` route over REST. The core drives the pipeline
    engine's resume path server-side; the CLI never builds a pipeline engine
    in-process and opens no PostgreSQL connection. The resume trigger travels in
    the request ``detail`` (``resume_trigger``).

    Args:
        args: Parsed CLI arguments.

    Returns:
        0 when the resume completed or yielded, 1 on failed/escalated/rejected
        or an unreachable/erroring backend.
    """
    prepared = _prepare_phase_call(
        args, "resume", detail={"resume_trigger": args.trigger}
    )
    if isinstance(prepared, int):
        return prepared

    result = _invoke_control_plane_phase(
        "resume",
        prepared,
        lambda client: client.resume_phase(
            project_key=prepared.project_key,
            run_id=args.run,
            phase=args.phase,
            request=prepared.request,
        ),
        client_builder=client_builder,
    )
    if result is None:
        return 1

    print(json.dumps(_phase_result_payload(result), sort_keys=True))
    # A resume succeeds only when the core actually resumed the phase to a
    # completed/yielded outcome; a rejected mutation or a failed/escalated
    # dispatch is a non-zero exit (fail-closed).
    if result.status not in ("committed", "replayed"):
        return 1
    dispatch = result.phase_dispatch
    if dispatch is None:
        return 0
    return 0 if dispatch.status in ("phase_completed", "yielded") else 1


# --- admin-abort (REST to the control plane, AG3-138) --------------------------


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


# --- reset-escalation (Class C) ------------------------------------------------


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


# --- cleanup (Class C — fail-closed without PID/TTL liveness) -----------------


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


# --- status --------------------------------------------------------------------


def _cmd_status(args: argparse.Namespace) -> int:
    """Handle ``agentkit status`` (AG3-076, FK-29).

    With ``--story``: reads the phase state via the state backend and renders a
    weekly-review frame inline.  Without ``--story``: renders the weekly-review
    frame only.

    Args:
        args: Parsed CLI arguments.

    Returns:
        0 on success, 1 on error.
    """
    from agentkit.backend.bootstrap.composition_root import cli_read_phase_state_record

    project_root = Path(getattr(args, "project_root", "."))
    story_id: str | None = getattr(args, "story", None)

    phase_state_payload: object = None
    if story_id:
        story_dir = project_root / "stories" / story_id
        try:
            phase_state_payload = cli_read_phase_state_record(story_dir)
        except Exception as exc:  # noqa: BLE001
            print(f"status failed [PhaseStateReadError]: {exc}", file=sys.stderr)
            return 1

        # ERROR 3 fix (NEW): None phase-state for a named story is fail-closed.
        # Story §2.3 anchor: an unresolvable story -> non-zero + stderr finding.
        if phase_state_payload is None:
            print(
                json.dumps(
                    {
                        "finding": "PhaseStateNotFound",
                        "story_id": story_id,
                        "detail": "no phase-state record found for the specified story",
                    },
                    sort_keys=True,
                ),
                file=sys.stderr,
            )
            return 1

    weekly_frame = _build_weekly_review_frame()

    # Class-A overview goes to stdout (exit 0 on success).
    # The FC review-block sections are Class-C service gaps: they go to stderr as
    # explicit machine-readable findings (§2.1.5 "no silent empty report"),
    # while the status exit code reflects Class-A success.
    # Distinction vs. weekly-review (§2.1.8 / §2.1.5 rationale):
    #   - weekly-review: all content is Class-C → stderr + non-zero
    #   - status: Class-A overview (run/pool/phase-state) → stdout + exit 0;
    #             FC service-gap markers → stderr (explicit, never silent/empty)
    print(json.dumps({"weekly_review_service_gaps": weekly_frame}, sort_keys=True, indent=2), file=sys.stderr)

    output: dict[str, object] = {}
    if story_id is not None:
        output["story_id"] = story_id
        if phase_state_payload is not None and hasattr(phase_state_payload, "model_dump"):
            output["phase_state"] = phase_state_payload.model_dump()

    print(json.dumps(output, sort_keys=True, default=str))
    return 0


# --- query-state ---------------------------------------------------------------


def _cmd_query_state(args: argparse.Namespace) -> int:
    """Handle ``agentkit query-state`` (AG3-076).

    Without ``--locks``: reads and outputs the phase state record (Class A).
    With ``--locks``: reports a service gap (Class C).

    Args:
        args: Parsed CLI arguments.

    Returns:
        0 on success, 1 on error or service gap.
    """
    if args.locks:
        print(
            "[ServiceGap] no lock-listing read repository — reported as service gap "
            "(owner: Lock-State-Backend/PO-assignment-required)",
            file=sys.stderr,
        )
        return 1

    from agentkit.backend.bootstrap.composition_root import cli_read_phase_state_record

    story_id: str | None = getattr(args, "story", None)
    if not story_id:
        print(
            "query-state failed [MissingStoryId]: --story is required for phase-state queries",
            file=sys.stderr,
        )
        return 1

    project_root = Path(getattr(args, "project_root", "."))
    story_dir = project_root / "stories" / story_id

    try:
        record = cli_read_phase_state_record(story_dir)
    except Exception as exc:  # noqa: BLE001
        print(f"query-state failed [PhaseStateReadError]: {exc}", file=sys.stderr)
        return 1

    # ERROR 3 fix (NEW): None record means the story/phase-state is not found.
    # Story §2.3: an unresolvable story is fail-closed (non-zero + stderr finding).
    if record is None:
        print(
            json.dumps(
                {
                    "finding": "PhaseStateNotFound",
                    "story_id": story_id,
                    "detail": "no phase-state record found for the specified story",
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1

    payload = record.model_dump() if hasattr(record, "model_dump") else None

    print(json.dumps({"story_id": story_id, "phase_state": payload}, sort_keys=True, default=str))
    return 0


# --- query-telemetry ----------------------------------------------------------


def _validate_event_type(event_type_raw: str) -> int:
    """Validate ``--event`` value against :class:`~agentkit.backend.telemetry.events.EventType`.

    ERROR 4 fix: unknown event type must fail-closed (non-zero + stderr) rather
    than silently dropping the filter or querying all events.

    Args:
        event_type_raw: The raw ``--event`` string from the CLI.

    Returns:
        0 when valid, 1 when the value is not a known :class:`EventType`.
    """
    from agentkit.backend.telemetry.events import EventType

    try:
        EventType(event_type_raw)
        return 0
    except ValueError:
        valid = sorted(e.value for e in EventType)
        detail = f"--event {event_type_raw!r} is not a known EventType; use one of the listed values."
        print(
            json.dumps(
                {
                    "finding": "InvalidEventType",
                    "value": event_type_raw,
                    "valid_values": valid,
                    "detail": detail,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1


def _pick_event_time(event: object) -> object:
    """Return the first non-``None`` time value from an event object.

    Priority order: ``occurred_at`` → ``occurred`` → ``timestamp``.
    This is the single source of truth for "the event's time" — used by
    both ``_apply_since_filter`` (for comparison) and the output serializer
    (for display), so the two always agree on which field carries the time.

    Args:
        event: Any event object that may have time fields as attributes.

    Returns:
        The raw time value (str or datetime) from the first populated field,
        or ``None`` when no recognisable time field is present.
    """
    for field in ("occurred_at", "occurred", "timestamp"):
        val = getattr(event, field, None)
        if val is not None:
            return val
    return None


def _coerce_to_aware_datetime(value: object) -> datetime | None:
    """Coerce a raw event time value to a timezone-aware :class:`datetime`.

    Accepts an ISO-8601 string or a :class:`datetime`; naive values are
    treated as UTC.  Returns ``None`` when the value is missing, not a
    recognised type, or an unparseable string (fail-closed: such an event
    has no comparable timestamp).

    Args:
        value: A raw time value from :func:`_pick_event_time` (str, datetime,
            or ``None``).

    Returns:
        A timezone-aware :class:`datetime`, or ``None`` when not coercible.
    """
    from datetime import UTC, datetime

    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return None


def _apply_since_filter(events: list[object], since_cutoff: datetime) -> list[object]:
    """Filter ``events`` to those whose timestamp is >= ``since_cutoff``.

    MAJOR 5 fix: filters by parsed datetime (not raw string comparison) so
    window-form cutoffs (``7d``, ``24h``) work correctly.

    MAJOR 2 fix: reads the event timestamp from whichever field is present —
    ``occurred_at``, ``occurred``, or ``timestamp`` — so that story-scoped
    ``Event`` objects (which use ``.timestamp``) are not silently dropped.
    The first non-``None`` value found in that priority order is used.
    Delegates field selection to :func:`_pick_event_time` (single source of
    truth shared with the output serializer).

    Args:
        events: Iterable of event objects whose timestamp may live in
            ``occurred_at``, ``occurred``, or ``timestamp`` attributes.
        since_cutoff: A timezone-aware :class:`datetime` lower bound.

    Returns:
        Subset of ``events`` that fall at or after ``since_cutoff``.
    """
    result = []
    for e in events:
        occ_dt = _coerce_to_aware_datetime(_pick_event_time(e))
        # ``None`` means no recognisable/parseable time field — skip rather than
        # silently retain; the event has no timestamp to compare.
        if occ_dt is not None and occ_dt >= since_cutoff:
            result.append(e)
    return result


def _cmd_query_telemetry_story_form(
    story_id: str,
    project_root: Path,
    event_type_raw: str | None,
    since_cutoff: datetime | None,
) -> int:
    """Inner handler for the story-scoped ``query-telemetry`` form.

    Delegates to :class:`~agentkit.backend.telemetry.storage.StateBackendEmitter.query`
    (story §2.1.7 / §2.3 anchor: telemetry/storage.py:89).

    Args:
        story_id: Story display ID.
        project_root: Project root path.
        event_type_raw: Optional validated event-type string.
        since_cutoff: Optional timezone-aware :class:`datetime` lower bound.

    Returns:
        0 on success, 1 on backend error.
    """
    from agentkit.backend.telemetry.events import EventType
    from agentkit.backend.telemetry.storage import StateBackendEmitter

    story_dir = project_root / "stories" / story_id
    event_type_filter: EventType | None = EventType(event_type_raw) if event_type_raw else None

    try:
        emitter = StateBackendEmitter(story_dir)
        events: list[object] = list(emitter.query(story_id, event_type_filter))
    except Exception as exc:  # noqa: BLE001
        print(f"query-telemetry failed: {exc}", file=sys.stderr)
        return 1

    if since_cutoff is not None:
        events = _apply_since_filter(events, since_cutoff)

    events_out = [
        {
            "event_id": str(getattr(e, "event_id", "")),
            "event_type": str(getattr(e, "event_type", "")),
            # Use _pick_event_time for the same priority order as _apply_since_filter
            # (occurred_at -> occurred -> timestamp) so the displayed time matches
            # whichever field the event actually uses (MINOR 2 fix).
            "occurred_at": str(_pick_event_time(e) or ""),
            "story_id": str(getattr(e, "story_id", "")),
        }
        for e in events
    ]
    print(json.dumps({"story_id": story_id, "events": events_out}, sort_keys=True))
    return 0


def _cmd_query_telemetry(args: argparse.Namespace) -> int:
    """Handle ``agentkit query-telemetry`` (AG3-076, FK-68).

    Requires at least one of --story, --run, or --event.

    Args:
        args: Parsed CLI arguments.

    Returns:
        0 on success, 1 on error.
    """
    story_id: str | None = getattr(args, "story", None)
    run_id: str | None = getattr(args, "run", None)
    event_type_raw: str | None = getattr(args, "event", None)
    since_raw: str | None = getattr(args, "since", None)

    if not story_id and not run_id and not event_type_raw:
        print(
            "query-telemetry failed [MissingFilter]: at least one of --story, --run, "
            "or --event is required.",
            file=sys.stderr,
        )
        return 1

    # ERROR 4 fix: validate --event fail-closed before any query.
    if event_type_raw is not None and _validate_event_type(event_type_raw) != 0:
        return 1

    # MAJOR 5 fix: parse --since into a timezone-aware datetime (fail-closed).
    since_cutoff: datetime | None = None
    if since_raw is not None:
        try:
            since_cutoff = _parse_since_cutoff(since_raw)
        except ValueError as exc:
            print(
                json.dumps(
                    {"finding": "InvalidSinceValue", "value": since_raw, "detail": str(exc)},
                    sort_keys=True,
                ),
                file=sys.stderr,
            )
            return 1

    # ERROR 1 fix: when --config is explicitly provided, validate it BEFORE branching
    # on story_id.  A broken --config must fail-closed (non-zero + structured stderr
    # finding) regardless of which query form is used (story or non-story).
    # When --config is absent, the story form proceeds without requiring a project_key.
    config_path_raw = getattr(args, "config", None)
    if config_path_raw is not None:
        try:
            _resolve_project_key(args)
        except _ConfigResolutionError as exc:
            print(f"query-telemetry failed [ConfigResolutionError]: {exc}", file=sys.stderr)
            return 1

    if story_id:
        project_root = Path(getattr(args, "project_root", "."))
        return _cmd_query_telemetry_story_form(
            story_id, project_root, event_type_raw, since_cutoff
        )

    # run-scoped or event-type global form: needs project_key (handled in helper).
    return _cmd_query_telemetry_global_form(args, run_id, event_type_raw, since_cutoff)


def _cmd_query_telemetry_global_form(
    args: argparse.Namespace,
    run_id: str | None,
    event_type_raw: str | None,
    since_cutoff: datetime | None,
) -> int:
    """Inner handler for the project-global ``query-telemetry`` forms (--run / --event).

    Resolves the project key fail-closed, reads project-global execution events
    via the composition-root wrapper, and applies adapter-side run/event/since
    filters (story §2.1.7).

    Args:
        args: Parsed CLI arguments (for project-key resolution).
        run_id: Optional run-ID filter.
        event_type_raw: Optional validated event-type filter.
        since_cutoff: Optional timezone-aware :class:`datetime` lower bound.

    Returns:
        0 on success, 1 on error.
    """
    # ERROR 2 fix: --config provided but broken -> fail-closed, not env fallback.
    # When --config is present the caller already validated it; resolving again
    # here keeps the resolution logic in one canonical place.
    try:
        project_key = _resolve_project_key(args)
    except _ConfigResolutionError as exc:
        print(f"query-telemetry failed [ConfigResolutionError]: {exc}", file=sys.stderr)
        return 1
    if not project_key:
        print(
            "query-telemetry failed [MissingProjectKey]: --project, --config-derived key, "
            "or AGENTKIT_PROJECT_KEY is required for run-scoped or event-type queries.",
            file=sys.stderr,
        )
        return 1

    from agentkit.backend.bootstrap.composition_root import cli_load_execution_events_for_project_global

    try:
        all_records = cli_load_execution_events_for_project_global(project_key)
    except Exception as exc:  # noqa: BLE001
        print(f"query-telemetry failed: {exc}", file=sys.stderr)
        return 1

    filtered: list[object] = list(all_records)
    if run_id:
        filtered = [r for r in filtered if str(getattr(r, "run_id", "")) == run_id]
    if event_type_raw:
        filtered = [r for r in filtered if str(getattr(r, "event_type", "")) == event_type_raw]
    if since_cutoff is not None:
        filtered = _apply_since_filter(filtered, since_cutoff)

    events_out = [
        {
            "event_id": str(getattr(r, "event_id", "")),
            "event_type": str(getattr(r, "event_type", "")),
            "story_id": str(getattr(r, "story_id", "")),
            "run_id": str(getattr(r, "run_id", "")),
            "occurred_at": str(getattr(r, "occurred_at", "")),
        }
        for r in filtered
    ]
    print(json.dumps({"project_key": project_key, "events": events_out}, sort_keys=True))
    return 0


# --- weekly-review -------------------------------------------------------------


def _build_weekly_review_frame() -> dict[str, object]:
    """Build the structured weekly-review frame with inline service-gap findings.

    The renderer frame itself (Class A) always succeeds. Data sections backed
    by ``FailureCorpus`` are Class C (service gaps reported inline).

    Returns:
        Dict suitable for JSON serialisation.
    """
    return {
        "pattern_candidates": {
            "status": "service_gap",
            "finding": "[ServiceGap] FailureCorpus.suggest_patterns not implemented (owner: AG3-078)",
        },
        "check_proposals": {
            "status": "service_gap",
            "finding": "[ServiceGap] FailureCorpus.derive_check not implemented (owner: AG3-078)",
        },
        "effectiveness_alerts": {
            "status": "service_gap",
            "finding": "[ServiceGap] FailureCorpus.report_effectiveness not implemented (owner: AG3-078)",
        },
    }


def _cmd_weekly_review(args: argparse.Namespace) -> int:
    """Handle ``agentkit weekly-review`` (AG3-076).

    Renders the operator weekly-review frame.  All sections are Class C
    (Failure-Corpus service gap) — their substantive content is absent until
    AG3-078 delivers the producers.  Per §2.1 preamble, Class-C parts emit a
    machine-readable finding to STDERR and return non-zero.

    Args:
        args: Parsed CLI arguments.

    Returns:
        Always 1 — all data sections are Class-C service gaps (non-zero exit
        per §2.1 preamble); the machine-readable findings go to stderr.
    """
    _ = args
    frame = _build_weekly_review_frame()
    # Class-C: machine-readable service-gap findings -> stderr (§2.1 preamble)
    print(json.dumps({"weekly_review": frame}, sort_keys=True, indent=2), file=sys.stderr)
    return 1


# --- override-integrity (Class C) ---------------------------------------------


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


# --- export-telemetry ---------------------------------------------------------


def _cmd_export_telemetry(args: argparse.Namespace) -> int:
    """Handle ``agentkit export-telemetry`` (AG3-076, FK-68 §68.3.6).

    Exports a completed story run as a JSONL audit bundle via
    :class:`~agentkit.backend.telemetry.audit_bundle.AuditBundleExporter`.

    Args:
        args: Parsed CLI arguments.

    Returns:
        0 on success, 1 on error.
    """
    output_dir = Path(args.output_dir)

    if args.dry_run:
        # Check output_dir reachability/writability only — NO filesystem mutation.
        # Story §2.1.10: checks reachability/writability only, no writes,
        # no export call (ERROR 4 fix).
        import os

        # Walk up to the nearest existing ancestor to check writability.
        check_target = output_dir
        while not check_target.exists() and check_target != check_target.parent:
            check_target = check_target.parent

        if not check_target.exists():
            print(
                f"export-telemetry dry-run failed [OutputDirNotWritable]: "
                f"no existing ancestor found for {output_dir}",
                file=sys.stderr,
            )
            return 1

        if not os.access(check_target, os.W_OK):
            print(
                f"export-telemetry dry-run failed [OutputDirNotWritable]: "
                f"{check_target} is not writable",
                file=sys.stderr,
            )
            return 1

        print(json.dumps({"dry_run": True, "output_dir": str(output_dir), "writable": True}, sort_keys=True))
        return 0

    from agentkit.backend.bootstrap.composition_root import build_projection_accessor
    from agentkit.backend.telemetry.audit_bundle import AuditBundleExporter, AuditBundleExportError
    from agentkit.backend.telemetry.storage import StateBackendEmitter

    project_root = Path(getattr(args, "project_root", "."))
    story_dir = project_root / "stories" / args.story

    try:
        accessor = build_projection_accessor(story_dir)
        event_store = StateBackendEmitter(story_dir)
        exporter = AuditBundleExporter(
            projection_accessor=accessor,
            event_store=event_store,
        )
        bundle = exporter.export(args.story, args.run, output_dir)
    except AuditBundleExportError as exc:
        print(f"export-telemetry failed [AuditBundleExportError]: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"export-telemetry failed: {exc}", file=sys.stderr)
        return 1

    file_info = [
        {"name": f.name, "path": str(f.path), "sha256": f.sha256, "size_bytes": f.size_bytes}
        for f in bundle.files
    ]
    print(
        json.dumps(
            {
                "story_id": bundle.story_id,
                "run_id": bundle.run_id,
                "output_dir": str(bundle.output_dir),
                "manifest_path": str(bundle.manifest_path),
                "files": file_info,
            },
            sort_keys=True,
        )
    )
    return 0
