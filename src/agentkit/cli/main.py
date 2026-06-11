"""AgentKit CLI -- command-line interface for the orchestration engine."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agentkit.verify_system.evidence import RepoContext
    from agentkit.verify_system.structural.system_evidence import ChangeEvidence


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
    # AG3-056 (FIX-5): mirror the Sonar discipline for the CI (Jenkins)
    # pre-merge runner. The closure pre-merge barrier needs a real CI trigger,
    # so a code-producing scaffold DECLARES Jenkins present by default
    # (``--ci-available``). ``--no-ci-available`` is the CONSCIOUS operator
    # opt-out (runner not applicable); the default is ``True`` (never an
    # auto-disable — that would silently skip the fail-closed CI preflight).
    install_parser.add_argument(
        "--ci-available",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Declare a CI (Jenkins) pre-merge runner present for this "
            "code-producing project. Use --no-ci-available for the conscious "
            "opt-out (pre-merge runner not applicable)."
        ),
    )
    uninstall_parser = subparsers.add_parser(
        "uninstall", help="Remove AgentKit from a target project",
    )
    uninstall_parser.add_argument("--project-root", required=True)

    # AG3-088 (FK-50 §50.2): the installer boundary controls. register-project
    # runs the checkpoint engine in ``register`` mode; verify-project runs it
    # read-only in ``verify`` mode.
    _add_register_verify_parsers(subparsers)

    # AG3-089 (FK-51): the upgrade boundary control. upgrade-project runs the
    # FK-51 upgrade flow THROUGH the shared checkpoint engine (engine-driven
    # flow, not a second installer).
    _add_upgrade_parser(subparsers)

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
    watch_worker_parser = subparsers.add_parser(
        "watch-worker", help="Run the worker-health LLM assessment sidecar",
    )
    watch_worker_parser.add_argument("story_id", help="Story ID to watch")
    watch_worker_parser.add_argument(
        "--project-root",
        default=".",
        help="Project root containing the AgentKit state backend",
    )
    exit_parser = subparsers.add_parser(
        "exit-story", help="Administratively exit a bound story run",
    )
    exit_parser.add_argument("--story", required=True, help="Story ID")
    exit_parser.add_argument("--reason", required=True, help="FK-58 exit reason code")
    exit_parser.add_argument("--note", required=False, help="Optional human note")
    exit_parser.add_argument(
        "--ak3-principal-attest",
        dest="ak3_principal_attest",
        required=False,
        help=argparse.SUPPRESS,
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
    # AG3-068 (FK-21 §21.11): deterministic story.md export + batch repair.
    export_story_md_parser = subparsers.add_parser(
        "export-story-md",
        help="Deterministically export a story as story.md (FK-21 §21.11)",
    )
    export_story_md_parser.add_argument("--story-id", required=True)
    export_story_md_parser.add_argument("--story-dir", required=True)
    export_story_md_parser.add_argument(
        "--project-root",
        required=False,
        help="Project root carrying .agentkit/config/project.yaml (Weaviate host/port).",
    )
    repair_story_md_parser = subparsers.add_parser(
        "repair-story-md",
        help="Scan, validate and re-export defective/missing story.md files (FK-21 §21.11.6)",
    )
    repair_story_md_parser.add_argument(
        "--stories-root",
        required=True,
        help="The stories/ directory holding {PREFIX}-* story sub-directories.",
    )
    repair_story_md_parser.add_argument(
        "--project-root",
        required=False,
        help="Project root carrying .agentkit/config/project.yaml (Weaviate host/port).",
    )

    evidence_parser = subparsers.add_parser(
        "evidence",
        help="Evidence assembly commands",
    )
    evidence_subparsers = evidence_parser.add_subparsers(dest="evidence_command")
    evidence_assemble_parser = evidence_subparsers.add_parser(
        "assemble",
        help="Assemble the review evidence bundle",
    )
    evidence_assemble_parser.add_argument("--story-id", required=True)
    evidence_assemble_parser.add_argument("--story-dir", required=True)
    evidence_assemble_parser.add_argument("--output-dir", required=True)
    evidence_assemble_parser.add_argument("--config")

    args = parser.parse_args(argv)

    if args.version:
        from agentkit import __version__

        print(f"agentkit {__version__}")
        return 0

    if args.command == "install":
        return _cmd_install(args)
    if args.command == "uninstall":
        return _cmd_uninstall(args)
    if args.command == "register-project":
        return _cmd_register_project(args)
    if args.command == "verify-project":
        return _cmd_verify_project(args)
    if args.command == "upgrade-project":
        return _cmd_upgrade_project(args)
    if args.command == "run-story":
        return _cmd_run_story(args)
    if args.command == "watch-worker":
        return _cmd_watch_worker(args)
    if args.command == "exit-story":
        return _cmd_exit_story(args, argv or sys.argv[1:])
    if args.command == "doctor":
        return _cmd_doctor()
    if args.command == "serve-control-plane":
        return _cmd_serve_control_plane(args)
    if args.command == "export-story-md":
        return _cmd_export_story_md(args)
    if args.command == "repair-story-md":
        return _cmd_repair_story_md(args)
    if args.command == "evidence" and args.evidence_command == "assemble":
        return _cmd_evidence_assemble(args)

    parser.print_help()
    return 0


def _resolve_github_coordinates(
    args: argparse.Namespace, project_root: Path,
) -> tuple[str, str] | None:
    """Resolve the MANDATORY github ``(owner, repo)`` for ``agentkit install``.

    AG3-039 (FK-50 §50.3 CP 7): the flags take PRECEDENCE; when a flag is omitted
    (or empty after ``.strip()``) the coordinate is derived from the target
    project's ``origin`` git remote. The resolved pair is validated against the
    SINGLE coordinate truth (:func:`validate_github_coordinate`) BEFORE any
    project write happens.

    FAIL-FAST / FAIL-CLOSED (AG3-039 R6 E-a + E-b): flag values are normalised
    with ``.strip()`` first so a whitespace-only flag (``"   "``) counts as
    MISSING (derivation may still kick in) rather than sailing past the
    missing-coordinate check and only blowing up at CP 7 — after a neutral
    scaffold / project.yaml was already written. Anything that is not a
    well-formed GitHub owner/repo is rejected; the coordinates are never
    fabricated (ZERO DEBT).

    Args:
        args: Parsed CLI arguments carrying ``github_owner``/``github_repo``.
        project_root: The target project root used for remote derivation.

    Returns:
        The validated ``(owner, repo)`` pair, or ``None`` when the coordinates
        are missing or invalid (the failure reason is printed to ``stderr``).
    """
    from agentkit.installer.github_coordinates import (
        derive_github_coordinates,
        validate_github_coordinate,
    )

    github_owner = args.github_owner.strip() if args.github_owner is not None else None
    github_repo = args.github_repo.strip() if args.github_repo is not None else None
    github_owner = github_owner or None
    github_repo = github_repo or None
    if github_owner is None or github_repo is None:
        derived = derive_github_coordinates(project_root)
        if derived is not None:
            github_owner = github_owner or derived[0]
            github_repo = github_repo or derived[1]
    if not github_owner or not github_repo:
        print(
            "Install failed [MissingGithubCoordinates]: --github-owner and "
            "--github-repo are required for State-Backend registration (FK-50 "
            "CP 7) and could not be derived from the project's origin git "
            "remote. Pass both flags explicitly.",
            file=sys.stderr,
        )
        return None
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
        return None
    return github_owner, github_repo


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

    project_root = Path(args.project_root)

    # AG3-039 (FK-50 §50.3 CP 7): resolve the MANDATORY github coordinates
    # (flags take precedence, else derive from origin) and validate them
    # fail-closed BEFORE any project write. A ``None`` result means the failure
    # reason was already printed to stderr.
    coordinates = _resolve_github_coordinates(args, project_root)
    if coordinates is None:
        return 1
    github_owner, github_repo = coordinates

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
        # AG3-056 (FIX-5): default ci.available:true; --no-ci-available is the
        # conscious opt-out. The CI preflight then verifies fail-closed or SKIPs.
        ci_available=args.ci_available,
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


def _add_register_verify_parsers(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Register the ``register-project`` / ``verify-project`` subcommands (FK-50 §50.2).

    Both take the same project coordinates; ``register-project`` adds a
    ``--dry-run`` flag (plan-only, no mutation). ``verify-project`` is always
    read-only.
    """
    register_parser = subparsers.add_parser(
        "register-project",
        help="Register a project via the installer checkpoint engine (FK-50 §50.2)",
    )
    register_parser.add_argument("--project-key", required=True)
    register_parser.add_argument("--project-name", required=True)
    register_parser.add_argument("--project-root", required=True)
    register_parser.add_argument("--github-owner", required=False)
    register_parser.add_argument("--github-repo", required=False)
    register_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Plan-only: report planned checkpoint outcomes without mutating.",
    )

    verify_parser = subparsers.add_parser(
        "verify-project",
        help="Read-only verification of a registered project (FK-50 §50.2)",
    )
    verify_parser.add_argument("--project-key", required=True)
    verify_parser.add_argument("--project-name", required=True)
    verify_parser.add_argument("--project-root", required=True)
    verify_parser.add_argument("--github-owner", required=False)
    verify_parser.add_argument("--github-repo", required=False)


def _build_engine_config(args: argparse.Namespace) -> object | None:
    """Build the :class:`InstallConfig` for the engine-driven subcommands.

    Resolves the github coordinates fail-closed (flags or origin remote) exactly
    like ``install``. Returns ``None`` (reason already printed) on a coordinate
    failure.
    """
    from agentkit.installer.repo_probe import GhCliRepoExistenceProbe
    from agentkit.installer.runner import InstallConfig

    project_root = Path(args.project_root)
    coordinates = _resolve_github_coordinates(args, project_root)
    if coordinates is None:
        return None
    github_owner, github_repo = coordinates
    return InstallConfig(
        project_key=args.project_key,
        project_name=args.project_name,
        project_root=project_root,
        github_owner=github_owner,
        github_repo=github_repo,
        # CP 2 probes the live GitHub repo via the productive gh probe (FK-50
        # §50.3 CP 2 / §50.6); a missing/unreachable repo FAILs closed.
        repo_existence_probe=GhCliRepoExistenceProbe(),
        # The engine boundary controls do not provision live Sonar/CI here.
        sonarqube_available=False,
        ci_available=False,
    )


def _print_checkpoint_results(result: object) -> None:
    """Print the per-checkpoint results of an install result (one line each)."""
    checkpoint_results = getattr(result, "checkpoint_results", None) or ()
    for cp in checkpoint_results:
        line = f"  {cp.checkpoint}: {cp.status.value}"
        if cp.reason:
            line += f" ({cp.reason})"
        print(line)


def _cmd_register_project(args: argparse.Namespace) -> int:
    """Handle ``agentkit register-project`` (FK-50 §50.2)."""
    from agentkit.exceptions import InstallationError, ProjectError
    from agentkit.installer.bootstrap_checkpoints.orchestrator import (
        run_checkpoint_install,
    )
    from agentkit.installer.checkpoint_engine.execution_mode import ExecutionMode

    config = _build_engine_config(args)
    if config is None:
        return 1
    mode = ExecutionMode.DRY_RUN if args.dry_run else ExecutionMode.REGISTER
    try:
        result = run_checkpoint_install(config, mode=mode)  # type: ignore[arg-type]
    except (InstallationError, ProjectError) as exc:
        print(f"register-project failed: {exc}", file=sys.stderr)
        return 1
    label = "planned" if args.dry_run else "registered"
    print(f"Project {label} ({mode.value}) at {args.project_root}")
    _print_checkpoint_results(result)
    return 0 if result.success else 1


def _cmd_verify_project(args: argparse.Namespace) -> int:
    """Handle ``agentkit verify-project`` (FK-50 §50.2, read-only)."""
    from agentkit.exceptions import InstallationError, ProjectError
    from agentkit.installer.bootstrap_checkpoints.orchestrator import (
        run_checkpoint_install,
    )
    from agentkit.installer.checkpoint_engine.execution_mode import ExecutionMode

    config = _build_engine_config(args)
    if config is None:
        return 1
    try:
        result = run_checkpoint_install(config, mode=ExecutionMode.VERIFY)  # type: ignore[arg-type]
    except (InstallationError, ProjectError) as exc:
        print(f"verify-project failed: {exc}", file=sys.stderr)
        return 1
    print(f"Project verification (read-only) at {args.project_root}")
    _print_checkpoint_results(result)
    return 0 if result.success else 1


def _add_upgrade_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Register the ``upgrade-project`` subcommand (FK-51, AG3-089).

    Runs the FK-51 upgrade flow through the shared checkpoint engine.
    ``--dry-run`` is plan-only (read-only ``dry_run`` mode); the default is the
    mutating ``register`` mode (``.bak`` + write config migration, hook + git-hook
    migration). ``--target-config-version`` is the desired
    ``pipeline.config_version`` (AG3-070 SSOT).
    """
    upgrade_parser = subparsers.add_parser(
        "upgrade-project",
        help="Run the FK-51 upgrade flow via the checkpoint engine (AG3-089)",
    )
    upgrade_parser.add_argument("--project-key", required=True)
    upgrade_parser.add_argument("--project-root", required=True)
    upgrade_parser.add_argument("--github-owner", required=False)
    upgrade_parser.add_argument("--github-repo", required=False)
    upgrade_parser.add_argument(
        "--target-config-version",
        required=True,
        help="Desired pipeline.config_version after migration (AG3-070 SSOT).",
    )
    upgrade_parser.add_argument(
        "--bundle-version-changed",
        action="store_true",
        help="The target bundle version differs from the bound one (FK-51 §51.3).",
    )
    upgrade_parser.add_argument(
        "--explicit-binding-switch",
        action="store_true",
        help="Explicitly switch the binding to the new bundle/profile (§51.3.3).",
    )
    upgrade_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Plan-only: report the planned upgrade without mutating.",
    )


def _cmd_upgrade_project(args: argparse.Namespace) -> int:
    """Handle ``agentkit upgrade-project`` (FK-51, AG3-089)."""
    from agentkit.exceptions import InstallationError, ProjectError
    from agentkit.installer.checkpoint_engine.execution_mode import ExecutionMode
    from agentkit.installer.upgrade.entry import run_checkpoint_upgrade
    from agentkit.installer.upgrade.footprint import CustomizationPreservationError

    project_root = Path(args.project_root)
    coordinates = _resolve_github_coordinates(args, project_root)
    if coordinates is None:
        return 1
    github_owner, github_repo = coordinates
    mode = ExecutionMode.DRY_RUN if args.dry_run else ExecutionMode.REGISTER
    try:
        result = run_checkpoint_upgrade(
            project_root,
            project_key=args.project_key,
            github_owner=github_owner,
            github_repo=github_repo,
            target_config_version=args.target_config_version,
            mode=mode,
            bundle_version_changed=args.bundle_version_changed,
            explicit_binding_switch=args.explicit_binding_switch,
        )
    except CustomizationPreservationError as exc:
        # F-51-023: a detected customization blocked a non-migrating write path.
        print(f"upgrade-project blocked (F-51-023): {exc}", file=sys.stderr)
        return 1
    except (InstallationError, ProjectError) as exc:
        print(f"upgrade-project failed: {exc}", file=sys.stderr)
        return 1
    label = "planned" if args.dry_run else "upgraded"
    print(
        f"Project {label} ({mode.value}) at {args.project_root}: "
        f"scenario {result.scenario.scenario.value!r}; {result.detail}"
    )
    return 0


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


def _cmd_watch_worker(args: argparse.Namespace) -> int:
    """Handle ``agentkit watch-worker`` sidecar command."""

    from pathlib import Path

    from agentkit.implementation.worker_health.sidecar import (
        run_worker_health_sidecar,
    )

    try:
        return run_worker_health_sidecar(
            args.story_id,
            project_root=Path(args.project_root),
        )
    except Exception as exc:  # noqa: BLE001
        print(f"watch-worker failed: {exc}", file=sys.stderr)
        return 1


def _cmd_exit_story(args: argparse.Namespace, cli_args: list[str]) -> int:
    """Handle ``agentkit exit-story``."""

    from agentkit.bootstrap.composition_root import build_story_exit_service
    from agentkit.governance.guard_evaluation import HookEvent
    from agentkit.governance.principal_capabilities.principals import PrincipalResolver
    from agentkit.story_exit import ExitReason, StoryExitRequest, StoryExitService

    try:
        reason = ExitReason(args.reason)
    except ValueError:
        print(f"exit-story failed: invalid reason code {args.reason!r}", file=sys.stderr)
        return 1

    project_key = os.environ.get("AGENTKIT_PROJECT_KEY", "").strip()
    run_id = os.environ.get("AGENTKIT_RUN_ID", "").strip()
    session_id = os.environ.get("AGENTKIT_SESSION_ID", "").strip()
    if not project_key or not run_id or not session_id:
        print(
            "exit-story failed: AGENTKIT_PROJECT_KEY, AGENTKIT_RUN_ID and "
            "AGENTKIT_SESSION_ID must identify the bound run.",
            file=sys.stderr,
        )
        return 1

    principal = PrincipalResolver().resolve(
        HookEvent(
            operation="bash_command",
            freshness_class="mutation",
            session_id=session_id,
            cli_args=cli_args,
            principal_kind="main",
        )
    )
    service = build_story_exit_service(project_key=project_key)
    if not isinstance(service, StoryExitService):
        print("exit-story failed: composition root returned invalid service", file=sys.stderr)
        return 1
    try:
        result = service.exit_story(
            StoryExitRequest(
                project_key=project_key,
                story_id=args.story,
                run_id=run_id,
                session_id=session_id,
                reason=reason,
                note=args.note,
                principal=principal,
            )
        )
    except Exception as exc:  # noqa: BLE001
        print(f"exit-story failed: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "status": "committed",
                "exit_id": result.exit_id,
                "story_id": result.record.story_id,
                "operating_mode": result.operating_mode,
                "artifact_dir": str(result.artifact_dir),
            },
            sort_keys=True,
        )
    )
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


def _build_weaviate_index(project_root: str | None) -> object:
    """Build the Weaviate story-index shim from the consumed vectordb config.

    The ``vectordb`` config stanza is owned exclusively by AG3-070; this only
    CONSUMES host/port. Fails closed when Weaviate / weaviate-client is absent.
    """
    from agentkit.integrations.vectordb import WeaviateStoryAdapter
    from agentkit.story_creation.weaviate_index import WeaviateStoryIndex
    from agentkit.vectordb.wait_for_weaviate import _resolve_host_port

    host, port = _resolve_host_port(project_root)
    adapter = WeaviateStoryAdapter.connect(host=host, port=port)
    return WeaviateStoryIndex(adapter)


def _build_story_attributes() -> object:
    """Build the authoritative AK3 story read surface (``StoryService``).

    Extracted as a seam so the CLI export/repair handlers can be exercised with
    an in-memory story source without a live state backend (mocks exception: the
    Weaviate / story-backend boundary).
    """
    from agentkit.story_context_manager.service import StoryService

    return StoryService()


def _cmd_export_story_md(args: argparse.Namespace) -> int:
    """Handle ``agentkit export-story-md`` (FK-21 §21.11)."""
    from pathlib import Path

    from agentkit.integrations.vectordb import VectorDbError
    from agentkit.story_creation.story_md_export import export_story_md

    try:
        index = _build_weaviate_index(args.project_root)
    except VectorDbError as exc:
        print(f"export-story-md failed [VectorDbUnavailable]: {exc}", file=sys.stderr)
        return 1

    result = export_story_md(
        args.story_id,
        Path(args.story_dir),
        story_attributes=_build_story_attributes(),  # type: ignore[arg-type]
        index=index,  # type: ignore[arg-type]  # structural StoryIndexPort
    )
    print(
        json.dumps(
            {
                "success": result.success,
                "story_md_path": result.story_md_path,
                "file_size_bytes": result.file_size_bytes,
                "error": result.error,
            },
            sort_keys=True,
        )
    )
    return 0 if result.success else 1


def _cmd_repair_story_md(args: argparse.Namespace) -> int:
    """Handle ``agentkit repair-story-md`` (FK-21 §21.11.6)."""
    from pathlib import Path

    from agentkit.integrations.vectordb import VectorDbError
    from agentkit.story_creation.repair_story_md import repair_story_md

    try:
        index = _build_weaviate_index(args.project_root)
    except VectorDbError as exc:
        print(f"repair-story-md failed [VectorDbUnavailable]: {exc}", file=sys.stderr)
        return 1

    report = repair_story_md(
        Path(args.stories_root),
        story_attributes=_build_story_attributes(),  # type: ignore[arg-type]
        index=index,  # type: ignore[arg-type]  # structural StoryIndexPort
    )
    print(
        json.dumps(
            {
                "checked": report.checked,
                "repaired": report.repaired,
                "errors": report.errors,
                "error_details": report.error_details,
            },
            sort_keys=True,
        )
    )
    return 0 if report.errors == 0 else 1


def _cmd_evidence_assemble(args: argparse.Namespace) -> int:
    """Handle ``agentkit evidence assemble`` command."""
    from pathlib import Path

    from agentkit.utils.io import atomic_write_text
    from agentkit.verify_system.evidence import (
        EvidenceAssembler,
        EvidenceAssemblyError,
        ImportResolver,
    )

    story_dir = Path(args.story_dir)
    output_dir = Path(args.output_dir)
    config_path = Path(args.config) if args.config is not None else story_dir / "context.json"
    try:
        cli_config = _load_evidence_cli_config(config_path)
        repos = {
            repo.repo_id: repo
            for repo in _repo_contexts_from_cli_config(cli_config, story_dir)
        }
        evidence_by_repo = _change_evidence_from_cli_config(cli_config)
        assembler = EvidenceAssembler(
            repos,
            change_evidence_port=_StaticChangeEvidencePort(
                evidence_by_repo=evidence_by_repo,
                repo_paths={repo_id: repo.repo_path for repo_id, repo in repos.items()},
            ),
            import_evidence_provider=ImportResolver.from_repo_contexts(repos),
        )
        result = assembler.assemble(story_dir=story_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = output_dir / "bundle_manifest.json"
        atomic_write_text(
            manifest_path,
            result.manifest.model_dump_json(indent=2) + "\n",
        )
    except (EvidenceAssemblyError, ValueError, OSError) as exc:
        print(f"Evidence assembly failed [{args.story_id}]: {exc}", file=sys.stderr)
        return 1

    print(result.manifest.model_dump_json(indent=2))
    print(json.dumps({"merge_paths": list(result.merge_paths)}, indent=2, sort_keys=True))
    return 0


def _load_evidence_cli_config(path: Path) -> dict[str, object]:
    """Load the CLI evidence config from JSON.

    Args:
        path: Explicit ``--config`` path or ``story_dir/context.json``.

    Returns:
        Parsed JSON mapping.

    Raises:
        ValueError: If the file is missing or is not a JSON object.
    """
    if not path.is_file():
        msg = (
            "evidence assemble requires explicit repo and changed-file evidence "
            f"in --config or story_dir/context.json; missing {path}"
        )
        raise ValueError(msg)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        msg = f"invalid evidence config JSON in {path}: {exc}"
        raise ValueError(msg) from exc
    if not isinstance(data, dict):
        msg = f"evidence config must be a JSON object: {path}"
        raise ValueError(msg)
    return data


def _repo_contexts_from_cli_config(
    config: dict[str, object],
    story_dir: Path,
) -> list[RepoContext]:
    """Build repo contexts from CLI config data."""
    from agentkit.verify_system.evidence import RepoContext

    repositories = config.get("repositories")
    if not isinstance(repositories, list) or not repositories:
        msg = "evidence config must contain a non-empty repositories list"
        raise ValueError(msg)
    repos: list[RepoContext] = []
    for item in repositories:
        if not isinstance(item, dict):
            msg = "each evidence repository config must be an object"
            raise ValueError(msg)
        repo_path_raw = item.get("repo_path")
        if not isinstance(repo_path_raw, str) or not repo_path_raw.strip():
            msg = "each evidence repository config requires repo_path"
            raise ValueError(msg)
        repo_path = Path(repo_path_raw)
        if not repo_path.is_absolute():
            repo_path = (story_dir / repo_path).resolve()
        repos.append(RepoContext.model_validate({**item, "repo_path": repo_path}))
    return repos


def _change_evidence_from_cli_config(
    config: dict[str, object],
) -> dict[str, ChangeEvidence]:
    """Build static change evidence from CLI config data."""
    from agentkit.verify_system.structural.system_evidence import ChangeEvidence

    raw_evidence = config.get("change_evidence")
    if not isinstance(raw_evidence, dict) or not raw_evidence:
        msg = "evidence config must contain non-empty change_evidence"
        raise ValueError(msg)
    evidence: dict[str, ChangeEvidence] = {}
    for repo_id, item in raw_evidence.items():
        if not isinstance(repo_id, str) or not isinstance(item, dict):
            msg = "each change_evidence entry must map a repo_id to an object"
            raise ValueError(msg)
        changed_files = item.get("changed_files")
        if not isinstance(changed_files, list) or not all(
            isinstance(path, str) for path in changed_files
        ):
            msg = f"change_evidence for {repo_id} requires changed_files string list"
            raise ValueError(msg)
        evidence[repo_id] = ChangeEvidence(
            available=True,
            changed_files=tuple(changed_files),
        )
    return evidence


@dataclass(frozen=True)
class _StaticChangeEvidencePort:
    """CLI adapter for pre-collected change evidence.

    This does not run git; it only passes operator-supplied/system-exported
    ``ChangeEvidence`` into the assembler's existing read-port shape.
    """

    evidence_by_repo: dict[str, ChangeEvidence]
    repo_paths: dict[str, Path]

    def collect(self, story_dir: Path) -> ChangeEvidence:
        """Return the configured evidence matching ``story_dir``."""
        resolved_story_dir = story_dir.resolve()
        for repo_id, repo_path in self.repo_paths.items():
            if repo_path.resolve() == resolved_story_dir:
                evidence = self.evidence_by_repo.get(repo_id)
                if evidence is not None:
                    return evidence
        from agentkit.verify_system.structural.system_evidence import ChangeEvidence

        return ChangeEvidence(available=False)
