"""Thin operator CLI adapters for takeover and recovery ownership routes."""

from __future__ import annotations

import getpass
import json
import sys
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import argparse

    from agentkit.backend.control_plane.models import ControlPlaneMutationResult
    from agentkit.harness_client.projectedge.client import ProjectEdgeClient

from ._operator_recovery_config import _ConfigResolutionError, _resolve_project_key

ClientBuilder = Callable[[str, str, str, str, str], "ProjectEdgeClient"]
PasswordReader = Callable[[str], str]
ConfirmationReader = Callable[[str], str]


def _build_strategist_client(
    base_url: str,
    project_root: str,
    project_key: str,
    username: str,
    password: str,
) -> ProjectEdgeClient:
    """Build an official client authenticated by a genuine strategist login."""
    from agentkit.harness_client.projectedge.client import (
        HttpsJsonTransport,
        LocalEdgePublisher,
        ProjectEdgeClient,
    )
    from agentkit.harness_client.projectedge.runtime import read_bound_skill_bundle_version

    root = Path(project_root)
    transport = HttpsJsonTransport(
        base_url=base_url,
        skill_bundle_version=read_bound_skill_bundle_version(root),
    ).authenticate_strategist(
        username=username,
        password=password,
        project_key=project_key,
    )
    return ProjectEdgeClient(
        transport=transport,
        publisher=LocalEdgePublisher(project_root=root),
    )


def _ownership_context(args: argparse.Namespace, verb: str) -> tuple[str, str, str] | int:
    """Resolve the common project, base URL, and project-root inputs."""
    try:
        project_key = _resolve_project_key(args)
    except _ConfigResolutionError as exc:
        print(f"{verb} failed [ConfigResolutionError]: {exc}", file=sys.stderr)
        return 1
    if not project_key:
        print(f"{verb} failed [MissingProjectKey]: --project is required", file=sys.stderr)
        return 1
    base_url = getattr(args, "base_url", None)
    if not base_url:
        print(f"{verb} failed [MissingBaseUrl]: --base-url is required", file=sys.stderr)
        return 1
    return project_key, str(base_url), str(getattr(args, "project_root", ".") or ".")


def _authenticated_client(
    args: argparse.Namespace,
    verb: str,
    *,
    client_builder: ClientBuilder,
    password_reader: PasswordReader,
) -> ProjectEdgeClient | int:
    """Obtain a strategist session and return its ProjectEdge client."""
    context = _ownership_context(args, verb)
    if isinstance(context, int):
        return context
    project_key, base_url, project_root = context
    try:
        password = password_reader("Strategist password: ")
        return client_builder(base_url, project_root, project_key, args.username, password)
    except Exception as exc:  # noqa: BLE001 - boundary maps stable transport errors
        return _emit_error(verb, exc)


def _emit_error(verb: str, exc: Exception) -> int:
    """Map stable API and transport failures to stable stderr codes."""
    from urllib.error import URLError

    from agentkit.backend.exceptions import ControlPlaneApiError

    if isinstance(exc, ControlPlaneApiError):
        print(
            f"{verb} failed [{exc.error_code}] HTTP {exc.http_status}: {exc}",
            file=sys.stderr,
        )
    elif isinstance(exc, URLError):
        print(f"{verb} failed [BackendUnreachable]: {exc}", file=sys.stderr)
    elif isinstance(exc, json.JSONDecodeError):
        print(f"{verb} failed [TransportError]: {exc}", file=sys.stderr)
    elif isinstance(exc, ValueError):
        print(f"{verb} failed [InvalidRequest]: {exc}", file=sys.stderr)
    else:
        print(f"{verb} failed [TransportError]: {exc}", file=sys.stderr)
    return 1


def _print_result(result: ControlPlaneMutationResult) -> None:
    """Print the complete wire result and any loss-corridor text verbatim."""
    print(json.dumps(result.model_dump(mode="json"), sort_keys=True))
    challenge = result.takeover_challenge
    if challenge is not None:
        print(challenge.loss_corridor_notice_text)


def _cmd_takeover_request(
    args: argparse.Namespace,
    *,
    client_builder: ClientBuilder = _build_strategist_client,
    password_reader: PasswordReader = getpass.getpass,
) -> int:
    """Request a takeover and display the complete informed challenge."""
    from agentkit.backend.control_plane.models import TakeoverRequest

    client = _authenticated_client(args, "takeover-request", client_builder=client_builder, password_reader=password_reader)
    if isinstance(client, int):
        return client
    try:
        result = client.takeover_request(
            run_id=args.run,
            request=TakeoverRequest(
                project_key=_resolve_project_key(args) or "",
                story_id=args.story,
                session_id=args.session,
                principal_type="human_cli",
                op_id=args.op_id or f"op-{uuid.uuid4().hex}",
                reason=args.reason,
                worktree_roots=args.worktree,
            ),
        )
    except Exception as exc:  # noqa: BLE001 - boundary maps stable transport errors
        return _emit_error("takeover-request", exc)
    _print_result(result)
    return 0 if result.status in ("offered", "pending_human_approval") else 1


def _cmd_takeover_confirm(
    args: argparse.Namespace,
    *,
    client_builder: ClientBuilder = _build_strategist_client,
    password_reader: PasswordReader = getpass.getpass,
    confirmation_reader: ConfirmationReader = input,
) -> int:
    """Confirm an echoed challenge through the strategist-session-only gate."""
    from agentkit.backend.control_plane.models import TakeoverConfirmRequest

    print(json.dumps({"challenge_id": args.challenge_id}, sort_keys=True))
    if confirmation_reader("Confirm this takeover challenge? Type YES: ") != "YES":
        print("takeover-confirm cancelled [ConfirmationRequired]", file=sys.stderr)
        return 1
    client = _authenticated_client(args, "takeover-confirm", client_builder=client_builder, password_reader=password_reader)
    if isinstance(client, int):
        return client
    try:
        result = client.takeover_confirm(
            run_id=args.run,
            request=TakeoverConfirmRequest(
                project_key=_resolve_project_key(args) or "",
                story_id=args.story,
                op_id=args.op_id or f"op-{uuid.uuid4().hex}",
                challenge_id=args.challenge_id,
                reason=args.reason,
            ),
        )
    except Exception as exc:  # noqa: BLE001 - boundary maps stable transport errors
        return _emit_error("takeover-confirm", exc)
    _print_result(result)
    return 0 if result.status in ("committed", "replayed", "challenge_reissued") else 1


def _cmd_recover_story(
    args: argparse.Namespace,
    *,
    client_builder: ClientBuilder = _build_strategist_client,
    password_reader: PasswordReader = getpass.getpass,
    confirmation_reader: ConfirmationReader = input,
) -> int:
    """Recover a crashed story, explicitly adopting or discarding its worktree."""
    from agentkit.backend.control_plane.models import RecoveryRequest

    disposition = "reset" if args.discard else "adopt"
    if (
        args.discard
        and confirmation_reader("Discard ALL uncommitted work and reset the worktree to HEAD? Type DISCARD: ") != "DISCARD"
    ):
        print("recover-story cancelled [DestructiveConfirmationRequired]", file=sys.stderr)
        return 1
    client = _authenticated_client(args, "recover-story", client_builder=client_builder, password_reader=password_reader)
    if isinstance(client, int):
        return client
    try:
        result = client.recover(
            run_id=args.run,
            request=RecoveryRequest(
                project_key=_resolve_project_key(args) or "",
                story_id=args.story,
                op_id=args.op_id or f"op-{uuid.uuid4().hex}",
                reason=args.reason,
                worktree_disposition=disposition,
            ),
        )
    except Exception as exc:  # noqa: BLE001 - boundary maps stable transport errors
        return _emit_error("recover-story", exc)
    _print_result(result)
    return 0 if result.status in ("committed", "replayed") else 1


__all__ = [
    "_build_strategist_client",
    "_cmd_recover_story",
    "_cmd_takeover_confirm",
    "_cmd_takeover_request",
]
