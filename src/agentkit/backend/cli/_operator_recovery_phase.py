"""Run-phase and resume operator recovery command handlers."""

from __future__ import annotations

import json
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import argparse
    from collections.abc import Callable

    from agentkit.backend.control_plane.models import (
        ControlPlaneMutationResult,
        PhaseMutationRequest,
    )
    from agentkit.harness_client.projectedge.client import ProjectEdgeClient

from ._operator_recovery_config import (
    _ConfigResolutionError as _ConfigResolutionError,
)
from ._operator_recovery_config import _resolve_project_key as _resolve_project_key

_VALID_PHASES = frozenset({"setup", "exploration", "implementation", "closure"})


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
    prepared = _prepare_phase_call(args, "resume", detail={"resume_trigger": args.trigger})
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


__all__ = [
    "_PhaseCallContext",
    "_build_control_plane_client",
    "_cmd_resume",
    "_cmd_run_phase",
    "_invoke_control_plane_phase",
    "_phase_result_payload",
    "_prepare_phase_call",
]
