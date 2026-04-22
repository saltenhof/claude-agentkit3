"""Project-local wrapper for official AK3 control-plane operations."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from agentkit.control_plane import (
    ClosureCompleteRequest,
    PhaseMutationRequest,
    ProjectEdgeSyncRequest,
)
from agentkit.projectedge import (
    ProjectEdgeClient,
    build_project_edge_client,
)


def main(argv: list[str] | None = None) -> int:
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

    args = parser.parse_args(argv)
    project_root = Path(args.project_root).resolve()
    client = _build_client(project_root)

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
                op_id=args.op_id,
            ),
        )
    else:
        result = client.sync(
            ProjectEdgeSyncRequest(
                project_key=args.project_key,
                session_id=args.session_id,
                op_id=args.op_id,
                freshness_class=args.freshness_class,
            ),
        )

    print(json.dumps(result.model_dump(mode="json"), indent=2, sort_keys=True))
    return 0


def _add_phase_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--project-key", required=True)
    parser.add_argument("--story-id", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--phase", required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--principal-type", default="orchestrator")
    parser.add_argument("--worktree-root", action="append", dest="worktree_roots")
    parser.add_argument("--op-id")


def _phase_request(args: argparse.Namespace) -> PhaseMutationRequest:
    return PhaseMutationRequest(
        project_key=args.project_key,
        story_id=args.story_id,
        session_id=args.session_id,
        principal_type=args.principal_type,
        worktree_roots=args.worktree_roots or [str(Path.cwd())],
        op_id=args.op_id,
    )


def _build_client(project_root: Path) -> ProjectEdgeClient:
    return build_project_edge_client(project_root)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
