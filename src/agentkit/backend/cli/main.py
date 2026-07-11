"""AgentKit CLI -- command-line interface for the orchestration engine."""

from __future__ import annotations

import argparse
import sys
from typing import TYPE_CHECKING

from agentkit.backend.cli import (
    evidence_commands as _evidence_commands,
)
from agentkit.backend.cli import (
    failure_corpus_commands as _failure_corpus_commands,
)
from agentkit.backend.cli import (
    installer_commands as _installer_commands,
)
from agentkit.backend.cli import (
    operator_recovery_commands as _operator_recovery_commands,
)
from agentkit.backend.cli import (
    story_commands as _story_commands,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from agentkit.backend.control_plane.models import ControlPlaneMutationResult
    from agentkit.harness_client.projectedge.client import ProjectEdgeClient

_cmd_failure_corpus = _failure_corpus_commands._cmd_failure_corpus
_setup_failure_corpus_subparsers = _failure_corpus_commands._setup_failure_corpus_subparsers

_build_engine_config = _installer_commands._build_engine_config
_split_jenkins_url = _installer_commands._split_jenkins_url
_wire_live_install_integrations = _installer_commands._wire_live_install_integrations

_prepare_phase_call = _operator_recovery_commands._prepare_phase_call

_build_story_attributes = _story_commands._build_story_attributes
_build_weaviate_index = _story_commands._build_weaviate_index
_cmd_exit_story = _story_commands._cmd_exit_story
_cmd_reset_story = _story_commands._cmd_reset_story
_cmd_split_story = _story_commands._cmd_split_story
_cmd_watch_worker = _story_commands._cmd_watch_worker

__all__ = [
    "_build_control_plane_client",
    "_build_engine_config",
    "_build_story_attributes",
    "_build_weaviate_index",
    "_cmd_exit_story",
    "_cmd_failure_corpus",
    "_cmd_reset_story",
    "_cmd_resume",
    "_cmd_run_phase",
    "_cmd_split_story",
    "_cmd_watch_worker",
    "_dispatch_command",
    "_invoke_control_plane_phase",
    "_prepare_phase_call",
    "_setup_failure_corpus_subparsers",
    "_split_jenkins_url",
    "_wire_live_install_integrations",
    "main",
]


def main(argv: list[str] | None = None) -> int:
    """Main CLI entrypoint.

    Parses command-line arguments and dispatches to the appropriate
    subcommand handler. Returns an integer exit code (0 for success,
    non-zero for failure).

    Args:
        argv: Command-line arguments. Defaults to ``sys.argv[1:]``
            when ``None``.

    Returns:
        Exit code: 0 on success, 1 on failure.
    """
    parser = argparse.ArgumentParser(
        prog="agentkit",
        description=("AgentKit -- deterministic orchestration engine for AI-driven story execution"),
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="Show version and exit",
    )

    subparsers = parser.add_subparsers(dest="command")
    _installer_commands.add_installer_parsers(subparsers)
    _story_commands.add_story_parsers(subparsers)
    _evidence_commands.add_evidence_parsers(subparsers)
    _setup_failure_corpus_subparsers(subparsers)
    _operator_recovery_commands._setup_operator_recovery_subparsers(subparsers)

    from agentkit.backend.cli.lifecycle import add_lifecycle_parsers

    add_lifecycle_parsers(subparsers)

    args = parser.parse_args(argv)

    if args.version:
        from agentkit import __version__

        print(f"agentkit {__version__}")
        return 0

    handled, exit_code = _dispatch_command(args, argv or sys.argv[1:])
    if handled:
        return exit_code

    parser.print_help()
    return 0


def _dispatch_command(args: argparse.Namespace, cli_args: list[str]) -> tuple[bool, int]:
    """Dispatch a parsed subcommand. Returns ``(handled, exit_code)``."""
    from agentkit.backend.cli import lifecycle

    handlers = {
        "install": lambda: _installer_commands._cmd_install(args),
        "uninstall": lambda: _installer_commands._cmd_uninstall(args),
        "register-project": lambda: _installer_commands._cmd_register_project(args),
        "verify-project": lambda: _installer_commands._cmd_verify_project(args),
        "upgrade-project": lambda: _installer_commands._cmd_upgrade_project(args),
        "run-story": lambda: _story_commands._cmd_run_story(args),
        "watch-worker": lambda: _cmd_watch_worker(args),
        "split-story": lambda: _cmd_split_story(args, cli_args),
        "reset-story": lambda: _cmd_reset_story(args),
        "exit-story": lambda: _cmd_exit_story(args, cli_args),
        "doctor": lambda: _story_commands._cmd_doctor(args),
        "serve": lambda: lifecycle.cmd_serve(args),
        "ui": lambda: lifecycle.cmd_ui(args),
        "update": lambda: lifecycle.cmd_update(args),
        "detach": lambda: lifecycle.cmd_detach(args),
        "decommission": lambda: lifecycle.cmd_decommission(args),
        "serve-control-plane": lambda: lifecycle.cmd_serve_control_plane_alias(args),
        "export-story-md": lambda: _cmd_export_story_md(args),
        "repair-story-md": lambda: _cmd_repair_story_md(args),
        "failure-corpus": lambda: _cmd_failure_corpus(args),
        "run-phase": lambda: _cmd_run_phase(args),
        "resume": lambda: _cmd_resume(args),
        "admin-abort": lambda: _cmd_admin_abort(args),
        "takeover-request": lambda: _operator_recovery_commands._cmd_takeover_request(args),
        "takeover-confirm": lambda: _operator_recovery_commands._cmd_takeover_confirm(args),
        "recover-story": lambda: _operator_recovery_commands._cmd_recover_story(args),
        "reset-escalation": lambda: _operator_recovery_commands._cmd_reset_escalation(args),
        "cleanup": lambda: _operator_recovery_commands._cmd_cleanup(args),
        "status": lambda: _operator_recovery_commands._cmd_status(args),
        "query-state": lambda: _operator_recovery_commands._cmd_query_state(args),
        "query-telemetry": lambda: _operator_recovery_commands._cmd_query_telemetry(args),
        "weekly-review": lambda: _operator_recovery_commands._cmd_weekly_review(args),
        "override-integrity": lambda: _operator_recovery_commands._cmd_override_integrity(args),
        "export-telemetry": lambda: _operator_recovery_commands._cmd_export_telemetry(args),
    }
    handler = handlers.get(str(args.command))
    if handler is not None:
        return True, handler()
    if args.command == "evidence" and args.evidence_command == "assemble":
        return True, _evidence_commands._cmd_evidence_assemble(args)
    return False, 0


def _build_control_plane_client(base_url: str, project_root: str) -> ProjectEdgeClient:
    """Build the official REST client for operator phase calls (AG3-130)."""
    return _operator_recovery_commands._build_control_plane_client(base_url, project_root)


def _invoke_control_plane_phase(
    verb: str,
    ctx: _operator_recovery_commands._PhaseCallContext,
    call: Callable[[ProjectEdgeClient], ControlPlaneMutationResult],
) -> ControlPlaneMutationResult | None:
    """Run a control-plane phase call through the public CLI facade seam."""
    return _operator_recovery_commands._invoke_control_plane_phase(verb, ctx, call, client_builder=_build_control_plane_client)


def _cmd_export_story_md(args: argparse.Namespace) -> int:
    """Handle ``agentkit export-story-md`` through the stable main-module seams."""
    return _story_commands._cmd_export_story_md(
        args,
        build_weaviate_index=_build_weaviate_index,
        build_story_attributes=_build_story_attributes,
    )


def _cmd_repair_story_md(args: argparse.Namespace) -> int:
    """Handle ``agentkit repair-story-md`` through the stable main-module seams."""
    return _story_commands._cmd_repair_story_md(
        args,
        build_weaviate_index=_build_weaviate_index,
        build_story_attributes=_build_story_attributes,
    )


def _cmd_run_phase(args: argparse.Namespace) -> int:
    """Handle ``agentkit run-phase`` through the stable main-module seam."""
    return _operator_recovery_commands._cmd_run_phase(args, client_builder=_build_control_plane_client)


def _cmd_resume(args: argparse.Namespace) -> int:
    """Handle ``agentkit resume`` through the stable main-module seam."""
    return _operator_recovery_commands._cmd_resume(args, client_builder=_build_control_plane_client)


def _cmd_admin_abort(args: argparse.Namespace) -> int:
    """Handle ``agentkit admin-abort`` through the stable main-module seam."""
    return _operator_recovery_commands._cmd_admin_abort(args, client_builder=_build_control_plane_client)
