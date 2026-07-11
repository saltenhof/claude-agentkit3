"""Project-local wrapper for official AK3 control-plane operations."""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.error import URLError

from pydantic import ValidationError

from agentkit.backend.config.loader import load_project_config
from agentkit.backend.control_plane.models import (
    ClosureCompleteRequest,
    CreateStoryInputs,
    PhaseMutationRequest,
    ProjectEdgeSyncRequest,
)
from agentkit.backend.exceptions import (
    ConfigError,
    ConflictAdjudicationUnavailableError,
    ControlPlaneApiError,
)
from agentkit.backend.story_creation.conflict_adjudicator import (
    CreateTimeConflictAdjudicationError,
)
from agentkit.backend.story_creation.runtime_factory import build_story_creation_reconciler
from agentkit.harness_client.projectedge import (
    ProjectEdgeClient,
    build_project_edge_client,
    process_open_commands,
)
from agentkit.integration_clients.vectordb import VectorDbError

if TYPE_CHECKING:
    from collections.abc import Callable

    from agentkit.backend.config.models import ProjectConfig
    from agentkit.backend.story_creation.create_flow import StoryCreationReconciler

    #: Factory that builds the official client from the project root (real
    #: default: :func:`build_project_edge_client`, the HTTPS transport).
    ClientFactory = Callable[[Path], ProjectEdgeClient]
    #: Factory that builds the real reconcile runtime (real default:
    #: :func:`build_story_creation_reconciler`, the fail-closed Weaviate gate).
    ReconcilerFactory = Callable[[ProjectConfig], StoryCreationReconciler]

#: Stable fail-closed exit code for a create that the boundary / reconciliation
#: rejected (distinct from argparse's exit 2 and a transport failure exit 1).
_CREATE_FAILCLOSED_EXIT = 3


def main(
    argv: list[str] | None = None,
    *,
    client_factory: ClientFactory | None = None,
    reconciler_factory: ReconcilerFactory | None = None,
) -> int:
    """Run one project-local control-plane operation.

    Args:
        argv: CLI argument vector (``None`` reads ``sys.argv``).
        client_factory: Seam to build the official :class:`ProjectEdgeClient`;
            defaults to the real HTTPS-transport factory. Injected ONLY by tests
            to drive the real route/service in-process (NO mock of the create
            boundary); production always uses the real default.
        reconciler_factory: Seam to build the real reconcile runtime; defaults to
            the real fail-closed Weaviate-gated factory. Injected ONLY by tests to
            fake the genuine external Weaviate/LLM edge; production always runs the
            real reconciliation.

    Returns:
        ``0`` on success, ``_CREATE_FAILCLOSED_EXIT`` (3) on a fail-closed create
        rejection, ``2`` on an argparse usage error.
    """
    parser = argparse.ArgumentParser(
        prog="python tools/agentkit/projectedge.py",
        description="Project-local wrapper for AgentKit control-plane calls",
    )
    parser.add_argument("--project-root", default=".")

    subparsers = parser.add_subparsers(dest="command", required=True)

    phase_parser = subparsers.add_parser("phase-start")
    _add_phase_args(phase_parser)

    phase_complete_parser = subparsers.add_parser("phase-complete")
    _add_phase_args(phase_complete_parser)

    phase_fail_parser = subparsers.add_parser("phase-fail")
    _add_phase_args(phase_fail_parser)

    closure_parser = subparsers.add_parser("closure-complete")
    closure_parser.add_argument("--project-key", required=True)
    closure_parser.add_argument("--story-id", required=True)
    closure_parser.add_argument("--run-id", required=True)
    closure_parser.add_argument("--session-id", required=True)
    closure_parser.add_argument("--op-id")

    sync_parser = subparsers.add_parser("sync")
    sync_parser.add_argument("--project-key", required=True)
    sync_parser.add_argument("--session-id", required=True)
    sync_parser.add_argument("--freshness-class", default="guarded_read")
    sync_parser.add_argument("--op-id")

    # AG3-145: the Edge-Command-Queue loop -- fetch this session's open commands
    # (FK-91 §91.1b), execute them dev-locally (provision/teardown/preflight,
    # sync-push, takeover-reconcile, and recovery reset), and report each result
    # with the edge's own op_id. Executors stay in the shared harness transport.
    commands_parser = subparsers.add_parser("run-commands")
    commands_parser.add_argument("--project-key", required=True)
    commands_parser.add_argument("--story-id", required=True)
    commands_parser.add_argument("--run-id", required=True)
    commands_parser.add_argument("--session-id", required=True)

    create_parser = subparsers.add_parser("create-story")
    _add_create_story_args(create_parser)

    args = parser.parse_args(argv)
    project_root = Path(args.project_root).resolve()

    if args.command == "create-story":
        return _run_create_story(
            project_root,
            args,
            client_factory=client_factory,
            reconciler_factory=reconciler_factory,
        )

    if args.command == "run-commands":
        return _run_commands(project_root, args, client_factory=client_factory)

    client = _build_client(project_root, client_factory)

    if args.command == "phase-start":
        result = client.start_phase(
            run_id=args.run_id,
            phase=args.phase,
            request=_phase_request(args),
        )
    elif args.command == "phase-complete":
        result = client.complete_phase(
            run_id=args.run_id,
            phase=args.phase,
            request=_phase_request(args),
        )
    elif args.command == "phase-fail":
        result = client.fail_phase(
            run_id=args.run_id,
            phase=args.phase,
            request=_phase_request(args),
        )
    elif args.command == "closure-complete":
        result = client.complete_closure(
            run_id=args.run_id,
            request=ClosureCompleteRequest(
                project_key=args.project_key,
                story_id=args.story_id,
                session_id=args.session_id,
                op_id=_client_op_id(args.op_id),
            ),
        )
    else:
        result = client.sync(
            ProjectEdgeSyncRequest(
                project_key=args.project_key,
                session_id=args.session_id,
                op_id=_client_op_id(args.op_id),
                freshness_class=args.freshness_class,
            ),
        )

    print(json.dumps(result.model_dump(mode="json"), indent=2, sort_keys=True))
    return 0


def _add_create_story_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--project-key", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--type", required=True, dest="story_type")
    parser.add_argument("--repo", action="append", dest="repos", required=True)
    parser.add_argument("--story-body", required=True)
    parser.add_argument("--epic", default="")
    parser.add_argument("--module", default="")
    parser.add_argument("--size")
    parser.add_argument("--mode")
    parser.add_argument("--label", action="append", dest="labels")
    parser.add_argument("--story-was-adapted", action="store_true")
    parser.add_argument("--op-id")


def _build_master_fields(args: argparse.Namespace) -> dict[str, object]:
    """Map the parsed ``create-story`` args to the master-field input mapping.

    Extracted from :func:`_run_create_story` to keep the input-mapping concern out
    of the fail-closed orchestration body (Sonar S3776 cognitive-complexity slim).
    """
    master_fields: dict[str, object] = {
        "project_key": args.project_key,
        "title": args.title,
        "type": args.story_type,
        "repos": list(args.repos),
        "epic": args.epic,
        "module": args.module,
        "labels": list(args.labels or []),
    }
    if args.size:
        master_fields["size"] = args.size
    if args.mode:
        master_fields["mode"] = args.mode
    return master_fields


def _run_create_story(
    project_root: Path,
    args: argparse.Namespace,
    *,
    client_factory: ClientFactory | None = None,
    reconciler_factory: ReconcilerFactory | None = None,
) -> int:
    """Run the agent-facing native create: reconcile -> evidence -> POST.

    Fail-closed (FK-21 §21.4.3 / FK-91 §91.1a Rule #3): the REAL reconciliation
    runtime produces the self-validating evidence; a Weaviate outage / a rejected
    boundary response blocks creation and prints a stable error contract on
    stderr with a non-zero exit. There is NO ``gh issue create`` here -- the
    Control Plane is the single story truth (Rule #9).

    Args:
        project_root: The target-project root.
        args: The parsed ``create-story`` arguments.
        client_factory: Optional client seam (real default).
        reconciler_factory: Optional reconcile-runtime seam (real default).

    Returns:
        ``0`` on a created story, ``_CREATE_FAILCLOSED_EXIT`` on a fail-closed
        reconciliation / boundary rejection.
    """
    op_id = args.op_id or f"op-{uuid.uuid4().hex}"
    correlation_id = f"corr-{uuid.uuid4().hex}"
    master_fields = _build_master_fields(args)

    # Config + reconciliation-runtime build. A missing / invalid project.yaml is a
    # stable ``configuration_error`` (AC3); an unconfigured / unready VectorDB is a
    # ``vectordb_unavailable`` (the factory fails closed at build time, NOT a
    # config defect); a bad input is ``validation_failed``.
    build_reconciler = reconciler_factory or _default_reconciler_factory
    try:
        project_config = load_project_config(project_root)
        reconciler = build_reconciler(project_config)
    except ConfigError as exc:
        return _emit_create_error(
            "configuration_error", str(exc), correlation_id, op_id
        )
    except VectorDbError as exc:
        # The runtime factory fails closed when the VectorDB is unconfigured /
        # unready (FK-21 §21.4.3). This escapes the ConfigError try, so map it to
        # the stable ``vectordb_unavailable`` contract (Codex R2 finding #3).
        return _emit_create_error(
            "vectordb_unavailable", str(exc), correlation_id, op_id
        )

    try:
        inputs = CreateStoryInputs.model_validate(master_fields)
    except ValidationError as exc:
        return _emit_create_error("validation_failed", str(exc), correlation_id, op_id)

    try:
        story_body = _read_story_body(args.story_body)
    except OSError as exc:
        # The story body was a path that could not be read (a configuration /
        # environment defect, not a reconciliation outcome).
        return _emit_create_error(
            "configuration_error", str(exc), correlation_id, op_id
        )

    # Client build can fail on a missing / invalid control-plane.json (a stable
    # ``configuration_error``) BEFORE any wire call.
    try:
        client = _build_client(project_root, client_factory)
    except (OSError, ValueError, KeyError) as exc:
        return _emit_create_error(
            "configuration_error", str(exc), correlation_id, op_id
        )

    # The fail-closed reconciliation now runs INSIDE the client boundary
    # (Codex R2 finding #1): the client drives ``reconcile_only`` and builds the
    # wire body from the real outcome, so no fabricated evidence can be handed in.
    # A Weaviate outage is ``vectordb_unavailable``; an above-threshold conflict
    # with no create-time adjudication owner is the TRUTHFUL
    # ``conflict_adjudication_unavailable``; an LLM-transport outage during the
    # create-time conflict assessment is ``conflict_adjudication_unavailable`` too
    # (both block creation fail-closed before any persistence, NOT a VectorDB
    # outage). A transport / JSON / protocol failure is ``transport_error``.
    try:
        result = client.create_story(
            inputs,
            reconciler=reconciler,
            story_body=story_body,
            op_id=op_id,
            correlation_id=correlation_id,
            story_was_adapted=args.story_was_adapted,
        )
    except (
        ConflictAdjudicationUnavailableError,
        CreateTimeConflictAdjudicationError,
    ) as exc:
        return _emit_create_error(
            "conflict_adjudication_unavailable", str(exc), correlation_id, op_id
        )
    except VectorDbError as exc:
        return _emit_create_error(
            "vectordb_unavailable", str(exc), correlation_id, op_id
        )
    except ControlPlaneApiError as exc:
        return _emit_create_error(
            exc.error_code, str(exc), exc.correlation_id or correlation_id, op_id
        )
    except URLError as exc:
        # A connection-level transport failure (the control plane is unreachable /
        # TLS handshake failed). urllib raises URLError, which is NOT a subclass of
        # RuntimeError, so it would otherwise escape (Codex R2 finding #3).
        return _emit_create_error("transport_error", str(exc), correlation_id, op_id)
    except (RuntimeError, json.JSONDecodeError) as exc:
        # A non-contract transport / protocol failure (a malformed control-plane
        # response, or a non-stable-contract HTTP error). The §91.1a stable-contract
        # error body is already surfaced as ControlPlaneApiError above. Stable
        # ``transport_error``.
        return _emit_create_error("transport_error", str(exc), correlation_id, op_id)

    # SUCCESS output carries op_id (Rule #5: the caller can GET
    # /v1/project-edge/operations/{op_id} after an ambiguous failure) and the full
    # §21.4.2 reconciliation counters the create surface owns (Codex R2 residual #3
    # / AG3-115): the persisted-story projection of these counters into the Story
    # model is owned by the story_context_manager BC (a FOREIGN owner) -- see the
    # report. AG3-114's create surface carries them here and on the wire body.
    output = {
        **result.summary.model_dump(mode="json"),
        "op_id": op_id,
        "reconciliation": result.reconciliation_counters,
    }
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0


def _run_commands(
    project_root: Path,
    args: argparse.Namespace,
    *,
    client_factory: ClientFactory | None = None,
) -> int:
    """Run the Edge command loop (AG3-145/147/151, FK-91 §91.1b).

    Fetches this session's open commands, executes provision/teardown/
    preflight_probe, the official ``sync_push`` Edge-Push-Gate path, AND the
    ``takeover_reconcile`` quarantine/reprovision path. The push path uses the
    backend-managed service identity and only the official ``story/{id}`` ref
    (FK-15 §15.5.4). All execute dev-locally, and the loop
    reports each result with the edge's own ``op_id``. The push mechanic is the
    SINGLE shared :func:`process_open_commands` (the harness-client executor) --
    this bundle wrapper adds no second copy. A missing / invalid project.yaml or
    control-plane.json is a stable ``configuration_error``. The per-command
    terminal outcomes are printed as JSON (completed / replayed / rejected).
    """
    try:
        project_config = load_project_config(project_root)
        client = _build_client(project_root, client_factory)
    except ConfigError as exc:
        return _emit_create_error(
            "configuration_error", str(exc), f"corr-{uuid.uuid4().hex}", ""
        )
    except (OSError, ValueError, KeyError) as exc:
        return _emit_create_error(
            "configuration_error", str(exc), f"corr-{uuid.uuid4().hex}", ""
        )

    outcomes = process_open_commands(
        client,
        project_config=project_config,
        project_root=project_root,
        run_id=args.run_id,
        project_key=args.project_key,
        session_id=args.session_id,
        story_id=args.story_id,
    )
    print(
        json.dumps(
            [outcome.model_dump(mode="json") for outcome in outcomes],
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _read_story_body(value: str) -> str:
    """Resolve the story body: a file path if it exists, else the literal text."""
    candidate = Path(value)
    if candidate.is_file():
        return candidate.read_text(encoding="utf-8")
    return value


def _emit_create_error(
    error_code: str, message: str, correlation_id: str, op_id: str
) -> int:
    """Print the stable §91.1a error contract on stderr and fail closed.

    The ``op_id`` is included so the caller can reconcile an ambiguous failure via
    ``GET /v1/project-edge/operations/{op_id}`` (Rule #5).
    """
    payload = {
        "error_code": error_code,
        "error": message,
        "correlation_id": correlation_id,
        "op_id": op_id,
    }
    print(json.dumps(payload, indent=2, sort_keys=True), file=sys.stderr)
    return _CREATE_FAILCLOSED_EXIT


def _add_phase_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--project-key", required=True)
    parser.add_argument("--story-id", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--phase", required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--principal-type", default="orchestrator")
    parser.add_argument("--worktree-root", action="append", dest="worktree_roots")
    parser.add_argument("--op-id")


def _client_op_id(op_id: str | None) -> str:
    """Return the caller op_id, minting one client-side when omitted.

    FK-91 §91.1a Rule 5 (AG3-140): op_id is the client-supplied idempotency key
    and the server no longer supplies a default. ``--op-id`` stays optional on the
    CLI, so a caller that omits it gets a fresh client-side mint here — no command
    ever relies on a server default that no longer exists.
    """
    return op_id or f"op-{uuid.uuid4().hex}"


def _phase_request(args: argparse.Namespace) -> PhaseMutationRequest:
    return PhaseMutationRequest(
        project_key=args.project_key,
        story_id=args.story_id,
        session_id=args.session_id,
        principal_type=args.principal_type,
        worktree_roots=args.worktree_roots or [str(Path.cwd())],
        op_id=_client_op_id(args.op_id),
    )


def _default_reconciler_factory(
    project_config: ProjectConfig,
) -> StoryCreationReconciler:
    """Build the real fail-closed reconcile runtime (production default)."""
    return build_story_creation_reconciler(project_config=project_config)


def _build_client(
    project_root: Path, client_factory: ClientFactory | None
) -> ProjectEdgeClient:
    factory = client_factory or build_project_edge_client
    return factory(project_root)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
