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
    install_parser.add_argument("--project-key", required=True)
    install_parser.add_argument("--project-name", required=True)
    install_parser.add_argument("--project-root", required=True)
    # AG3-039 (FK-50 §50.3 CP 7): github_owner/github_repo are MANDATORY
    # registration coordinates. The flags take PRECEDENCE; when both are omitted
    # the installer derives them from the target project's ``origin`` git remote.
    # If neither flags nor a parseable origin remote exist, ``install`` fails
    # closed (CP 7 would otherwise FAIL after partial work — fail fast instead).
    install_parser.add_argument(
        "--github-owner",
        required=False,
        help=(
            "GitHub owner for State-Backend registration (FK-50 CP 7). "
            "Falls back to the project's origin remote when omitted."
        ),
    )
    install_parser.add_argument(
        "--github-repo",
        required=False,
        help=(
            "GitHub repo name for State-Backend registration (FK-50 CP 7). "
            "Falls back to the project's origin remote when omitted."
        ),
    )
    install_parser.add_argument(
        "--prompt-bundle-root",
        required=False,
        help="Optional prompt bundle root to bind into the project",
    )
    # AG3-052 (FK-03 §3): the SonarQube-Green-Gate is a mandatory runtime
    # dependency, so a code-producing scaffold DECLARES Sonar present by
    # default (``--sonarqube-available``). ``--no-sonarqube-available`` is the
    # CONSCIOUS operator opt-out (gate not applicable, FK-33 §33.6.5); the
    # default is ``True`` per FK-03 §3 (never an auto-disable).
    install_parser.add_argument(
        "--sonarqube-available",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Declare SonarQube present for this code-producing project "
            "(FK-03 §3 default). Use --no-sonarqube-available for the "
            "conscious opt-out (gate not applicable)."
        ),
    )
    uninstall_parser = subparsers.add_parser(
        "uninstall", help="Remove AgentKit from a target project",
    )
    uninstall_parser.add_argument("--project-root", required=True)

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
    control_plane_parser = subparsers.add_parser(
        "serve-control-plane",
        help="Run the AgentKit control-plane HTTP server",
    )
    control_plane_parser.add_argument("--host", default="127.0.0.1")
    control_plane_parser.add_argument("--port", type=int, default=9080)
    control_plane_parser.add_argument("--certfile", required=True)
    control_plane_parser.add_argument("--keyfile")

    args = parser.parse_args(argv)

    if args.version:
        from agentkit import __version__

        print(f"agentkit {__version__}")
        return 0

    if args.command == "install":
        return _cmd_install(args)
    if args.command == "uninstall":
        return _cmd_uninstall(args)
    if args.command == "run-story":
        return _cmd_run_story(args)
    if args.command == "doctor":
        return _cmd_doctor()
    if args.command == "serve-control-plane":
        return _cmd_serve_control_plane(args)

    parser.print_help()
    return 0


def _cmd_install(args: argparse.Namespace) -> int:
    """Handle ``agentkit install`` command.

    Creates the AgentKit directory structure in the target project
    using the installer from :mod:`agentkit.installer`.

    Args:
        args: Parsed CLI arguments with ``project_name`` and
            ``project_root``.

    Returns:
        Exit code: 0 on success, 1 on failure.
    """
    from pathlib import Path

    from agentkit.exceptions import InstallationError
    from agentkit.installer import InstallConfig, install_agentkit
    from agentkit.installer.github_coordinates import (
        derive_github_coordinates,
        validate_github_coordinate,
    )

    project_root = Path(args.project_root)

    # AG3-039 (FK-50 §50.3 CP 7): resolve the MANDATORY github coordinates.
    # Flags take precedence; otherwise derive from the project's origin remote.
    #
    # FAIL-FAST / FAIL-CLOSED (AG3-039 R6 E-a + E-b): the flag values are
    # normalised with ``.strip()`` FIRST. A whitespace-only flag (``"   "``) is
    # truthy as a raw string and would otherwise sail past the missing-coordinate
    # check and only blow up at CP 7 — AFTER a neutral scaffold / project.yaml was
    # written. Treat empty-after-strip as MISSING so derivation may still kick in,
    # and reject any value that is not a well-formed GitHub owner/repo BEFORE any
    # project write happens. The coordinates are never fabricated (ZERO DEBT).
    github_owner = args.github_owner.strip() if args.github_owner is not None else None
    github_repo = args.github_repo.strip() if args.github_repo is not None else None
    github_owner = github_owner or None
    github_repo = github_repo or None
    if github_owner is None or github_repo is None:
        derived = derive_github_coordinates(project_root)
        if derived is not None:
            derived_owner, derived_repo = derived
            github_owner = github_owner if github_owner is not None else derived_owner
            github_repo = github_repo if github_repo is not None else derived_repo
    if not github_owner or not github_repo:
        print(
            "Install failed [MissingGithubCoordinates]: --github-owner and "
            "--github-repo are required for State-Backend registration (FK-50 "
            "CP 7) and could not be derived from the project's origin git "
            "remote. Pass both flags explicitly.",
            file=sys.stderr,
        )
        return 1
    # FAIL-CLOSED (AG3-039 R6 E-b): the resolved coordinates — whether from the
    # flags or the derived remote — MUST be a valid GitHub owner/repo before they
    # are persisted into the project_registry. Reject path-traversal tokens,
    # embedded spaces, leading/trailing hyphens, over-long segments, etc. instead
    # of recording a meaningless row.
    if validate_github_coordinate(github_owner, github_repo) is None:
        print(
            "Install failed [InvalidGithubCoordinates]: "
            f"--github-owner {github_owner!r} / --github-repo {github_repo!r} "
            "are not a valid GitHub owner/repo (owner: 1-39 alphanumerics with "
            "single internal hyphens; repo: 1-100 chars of [A-Za-z0-9._-], not "
            "'.'/'..' and no leading dot). Pass valid coordinates.",
            file=sys.stderr,
        )
        return 1

    # AG3-048 (FK-43 §43.3.1, AC#5): the skill fields are intentionally left at
    # their defaults. ``skill_bundle_ids=None`` resolves to the four mandatory
    # skill bundles (DEFAULT_MANDATORY_SKILL_BUNDLE_IDS) — it does NOT skip
    # binding. A normal ``agentkit install`` therefore binds all four; if the
    # systemwide skill-bundle store has not been provisioned the install fails
    # closed with InstallationError(cause=BundleNotFound) (AC#7).
    config = InstallConfig(
        project_key=args.project_key,
        project_name=args.project_name,
        project_root=project_root,
        github_owner=github_owner,
        github_repo=github_repo,
        prompt_bundle_root=(
            Path(args.prompt_bundle_root)
            if args.prompt_bundle_root is not None
            else None
        ),
        # AG3-052 (FK-03 §3): default available:true; --no-sonarqube-available
        # is the conscious opt-out. CP 10d then verifies fail-closed (E5) or
        # SKIPs (opt-out).
        sonarqube_available=args.sonarqube_available,
    )
    try:
        result = install_agentkit(config)
    except InstallationError as exc:
        # FAIL-CLOSED (AC#7): mandatory-skill binding could not complete (e.g.
        # the systemwide skill-bundle store is not provisioned). Surface a
        # clean non-zero exit instead of a partial install or a traceback.
        cause = exc.detail.get("cause", "InstallationError")
        print(f"Install failed [{cause}]: {exc}", file=sys.stderr)
        return 1
    if result.success:
        print(f"AgentKit installed into {args.project_root}")
        for f in result.created_files:
            print(f"  + {f}")
        return 0

    print(f"Install failed: {'; '.join(result.errors)}", file=sys.stderr)
    return 1


def _cmd_uninstall(args: argparse.Namespace) -> int:
    """Handle ``agentkit uninstall`` command."""

    from pathlib import Path

    from agentkit.installer import uninstall_agentkit

    result = uninstall_agentkit(Path(args.project_root))
    if result.success:
        print(f"AgentKit uninstalled from {args.project_root}")
        for removed in result.removed_files:
            print(f"  - {removed}")
        return 0

    print(f"Uninstall failed: {'; '.join(result.errors)}", file=sys.stderr)
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


def _cmd_serve_control_plane(args: argparse.Namespace) -> int:
    """Handle ``agentkit serve-control-plane`` command."""

    from pathlib import Path

    from agentkit.control_plane.http import serve_control_plane

    serve_control_plane(
        host=args.host,
        port=args.port,
        certfile=Path(args.certfile),
        keyfile=Path(args.keyfile) if args.keyfile is not None else None,
    )
    return 0
