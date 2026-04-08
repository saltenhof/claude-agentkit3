"""AgentKit CLI -- command-line interface for the orchestration engine."""

from __future__ import annotations

import argparse
import sys


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
        description=(
            "AgentKit -- deterministic orchestration engine "
            "for AI-driven story execution"
        ),
    )
    parser.add_argument(
        "--version", action="store_true", help="Show version and exit",
    )

    subparsers = parser.add_subparsers(dest="command")

    # install
    install_parser = subparsers.add_parser(
        "install", help="Install AgentKit into a target project",
    )
    install_parser.add_argument("--project-name", required=True)
    install_parser.add_argument("--project-root", required=True)

    # run-story (minimal -- reads issue, runs pipeline)
    run_parser = subparsers.add_parser(
        "run-story", help="Run a story through the pipeline",
    )
    run_parser.add_argument(
        "--story", required=True, help="Story ID",
    )
    run_parser.add_argument(
        "--issue-nr", type=int, required=True,
        help="GitHub issue number",
    )
    run_parser.add_argument(
        "--owner", required=True, help="GitHub repo owner",
    )
    run_parser.add_argument(
        "--repo", required=True, help="GitHub repo name",
    )
    run_parser.add_argument(
        "--project-root", required=True, help="Target project root",
    )

    # doctor (health check)
    subparsers.add_parser(
        "doctor", help="Check AgentKit installation health",
    )

    args = parser.parse_args(argv)

    if args.version:
        from agentkit import __version__

        print(f"agentkit {__version__}")
        return 0

    if args.command == "install":
        return _cmd_install(args)
    if args.command == "run-story":
        return _cmd_run_story(args)
    if args.command == "doctor":
        return _cmd_doctor()

    parser.print_help()
    return 0


def _cmd_install(args: argparse.Namespace) -> int:
    """Handle ``agentkit install`` command.

    Creates the AgentKit directory structure in the target project
    using the installer from :mod:`agentkit.project_ops.install`.

    Args:
        args: Parsed CLI arguments with ``project_name`` and
            ``project_root``.

    Returns:
        Exit code: 0 on success, 1 on failure.
    """
    from pathlib import Path

    from agentkit.project_ops.install import InstallConfig, install_agentkit

    config = InstallConfig(
        project_name=args.project_name,
        project_root=Path(args.project_root),
    )
    result = install_agentkit(config)
    if result.success:
        print(f"AgentKit installed into {args.project_root}")
        for f in result.created_files:
            print(f"  + {f}")
        return 0

    print(f"Install failed: {'; '.join(result.errors)}", file=sys.stderr)
    return 1


def _cmd_run_story(args: argparse.Namespace) -> int:
    """Handle ``agentkit run-story`` command.

    Minimal implementation that prints story information.
    Full pipeline integration is pending implementation of
    the remaining phase handlers.

    Args:
        args: Parsed CLI arguments with ``story``, ``issue_nr``,
            ``owner``, ``repo``, and ``project_root``.

    Returns:
        Exit code: 0 (always, as this is currently a stub).
    """
    print(f"Running story {args.story} (issue #{args.issue_nr})")
    print(
        f"  repo: {args.owner}/{args.repo}  "
        f"root: {args.project_root}"
    )
    print("Note: Full pipeline execution pending phase handler implementation")
    return 0


def _cmd_doctor() -> int:
    """Handle ``agentkit doctor`` command.

    Performs basic health checks: verifies that required external
    tools (``gh``, ``git``) are available and prints the AgentKit
    version.

    Returns:
        Exit code: 0 (always).
    """
    import shutil

    from agentkit import __version__

    print("AgentKit Doctor")
    print(f"  gh CLI: {'found' if shutil.which('gh') else 'NOT FOUND'}")
    print(f"  git:    {'found' if shutil.which('git') else 'NOT FOUND'}")
    print(f"  version: {__version__}")
    return 0
