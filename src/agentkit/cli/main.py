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

#: Shared ``--story`` help label, reused across the story-scoped subcommands.
_STORY_ID_FIELD_LABEL = "Story ID"


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
        "--story", required=True, help=_STORY_ID_FIELD_LABEL,
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
    # AG3-072 (FK-54 §54.6): administrative scope_explosion recovery split.
    split_parser = subparsers.add_parser(
        "split-story",
        help="Administratively split a scope-exploded story into successors",
    )
    # FK-54 §54.4: the human approval IS the human-started CLI invocation with a
    # valid --plan. The interface is EXACTLY --story/--plan/--reason; there is no
    # hidden attestation flag (a bare `agentkit split-story ...` must succeed).
    split_parser.add_argument("--story", required=True, help="Source story ID")
    split_parser.add_argument(
        "--plan", required=True, help="Path to the human-approved split-plan JSON"
    )
    split_parser.add_argument("--reason", required=True, help="Split reason")

    # AG3-071 (FK-53 §53.3): the official, human-triggered Story-Reset path. The
    # ONLY trigger for a destructive reset (no automatic path).
    reset_parser = subparsers.add_parser(
        "reset-story",
        help="Administratively reset an irreparably escalated story (FK-53)",
    )
    reset_parser.add_argument("--story", required=True, help=_STORY_ID_FIELD_LABEL)
    reset_parser.add_argument("--reason", required=True, help="FK-53 §53.3 reset reason")
    reset_parser.add_argument(
        "--escalation-ref",
        dest="escalation_ref",
        required=False,
        help="Optional reference to the escalation/exception finding (§53.5)",
    )
    reset_parser.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="Plan-only: report the planned purge domains without mutating (§53.3).",
    )
    reset_parser.add_argument(
        "--force",
        action="store_true",
        help="Bypass the escalation-finding precondition (conscious operator override).",
    )

    exit_parser = subparsers.add_parser(
        "exit-story", help="Administratively exit a bound story run",
    )
    exit_parser.add_argument("--story", required=True, help=_STORY_ID_FIELD_LABEL)
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

    # failure-corpus (FK-41 §41.9, AG3-078)
    _setup_failure_corpus_subparsers(subparsers)

    # AG3-076: operator/recovery commands
    _setup_operator_recovery_subparsers(subparsers)

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


def _dispatch_command(
    args: argparse.Namespace, cli_args: list[str]
) -> tuple[bool, int]:
    """Dispatch a parsed subcommand. Returns ``(handled, exit_code)``."""
    handlers = {
        "install": lambda: _cmd_install(args),
        "uninstall": lambda: _cmd_uninstall(args),
        "register-project": lambda: _cmd_register_project(args),
        "verify-project": lambda: _cmd_verify_project(args),
        "upgrade-project": lambda: _cmd_upgrade_project(args),
        "run-story": lambda: _cmd_run_story(args),
        "watch-worker": lambda: _cmd_watch_worker(args),
        "split-story": lambda: _cmd_split_story(args, cli_args),
        "reset-story": lambda: _cmd_reset_story(args),
        "exit-story": lambda: _cmd_exit_story(args, cli_args),
        "doctor": lambda: _cmd_doctor(),
        "serve-control-plane": lambda: _cmd_serve_control_plane(args),
        "export-story-md": lambda: _cmd_export_story_md(args),
        "repair-story-md": lambda: _cmd_repair_story_md(args),
        # failure-corpus (FK-41 §41.9, AG3-078)
        "failure-corpus": lambda: _cmd_failure_corpus(args),
        # AG3-076: operator/recovery commands
        "run-phase": lambda: _cmd_run_phase(args),
        "resume": lambda: _cmd_resume(args),
        "reset-escalation": lambda: _cmd_reset_escalation(args),
        "cleanup": lambda: _cmd_cleanup(args),
        "status": lambda: _cmd_status(args),
        "query-state": lambda: _cmd_query_state(args),
        "query-telemetry": lambda: _cmd_query_telemetry(args),
        "weekly-review": lambda: _cmd_weekly_review(args),
        "override-integrity": lambda: _cmd_override_integrity(args),
        "export-telemetry": lambda: _cmd_export_telemetry(args),
    }
    handler = handlers.get(str(args.command))
    if handler is not None:
        return True, handler()
    if args.command == "evidence" and args.evidence_command == "assemble":
        return True, _cmd_evidence_assemble(args)
    return False, 0


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
    # S5713: ``InstallationError`` derives from ``ProjectError`` (exceptions.py),
    # so catching ``ProjectError`` already covers it — the redundant subclass is
    # dropped from the import and the except clause (handling is shared).
    from agentkit.exceptions import ProjectError
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
    except ProjectError as exc:
        print(f"register-project failed: {exc}", file=sys.stderr)
        return 1
    label = "planned" if args.dry_run else "registered"
    print(f"Project {label} ({mode.value}) at {args.project_root}")
    _print_checkpoint_results(result)
    return 0 if result.success else 1


def _cmd_verify_project(args: argparse.Namespace) -> int:
    """Handle ``agentkit verify-project`` (FK-50 §50.2, read-only)."""
    # S5713: ``InstallationError`` derives from ``ProjectError``; catching the
    # parent already covers the subclass (shared handling), so the redundant
    # subclass is removed from the import and the except clause.
    from agentkit.exceptions import ProjectError
    from agentkit.installer.bootstrap_checkpoints.orchestrator import (
        run_checkpoint_install,
    )
    from agentkit.installer.checkpoint_engine.execution_mode import ExecutionMode

    config = _build_engine_config(args)
    if config is None:
        return 1
    try:
        result = run_checkpoint_install(config, mode=ExecutionMode.VERIFY)  # type: ignore[arg-type]
    except ProjectError as exc:
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
    # S5713: ``CustomizationPreservationError`` -> ``InstallationError`` ->
    # ``ProjectError``. The specific ``CustomizationPreservationError`` keeps its
    # OWN earlier except clause (distinct F-51-023 handling); the generic clause
    # then catches the remaining ``ProjectError`` subtree, so the redundant
    # ``InstallationError`` is dropped from the import and the generic except.
    from agentkit.exceptions import ProjectError
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
    except ProjectError as exc:
        print(f"upgrade-project failed: {exc}", file=sys.stderr)
        return 1
    label = "planned" if args.dry_run else "upgraded"
    print(
        f"Project {label} ({mode.value}) at {args.project_root}: "
        f"scenario {result.scenario.scenario.value!r}; {result.detail}"
    )
    return 0


def _setup_failure_corpus_subparsers(
    subparsers: argparse._SubParsersAction,  # type: ignore[type-arg]
) -> None:
    """Register the ``failure-corpus`` command and its sub-subcommands.

    Called from ``main()`` to wire all six AG3-078 subcommands into the CLI.
    The actual registration is delegated to the thin CLI adapter.

    Args:
        subparsers: The top-level subparsers action from the main parser.
    """
    from agentkit.failure_corpus.cli import register_subparsers as _fc_register

    fc_parser = subparsers.add_parser(
        "failure-corpus",
        help="Failure-corpus commands (FK-41 §41.9, AG3-078)",
    )
    fc_subparsers = fc_parser.add_subparsers(dest="fc_command")
    _fc_register(fc_subparsers)


def _cmd_failure_corpus(args: argparse.Namespace) -> int:
    """Handle ``agentkit failure-corpus`` subcommands (FK-41 §41.9, AG3-078).

    Delegates to the thin CLI adapter in ``agentkit.failure_corpus.cli``.

    Args:
        args: Parsed CLI arguments with ``fc_command`` attribute set by
            the ``failure-corpus`` subparser.

    Returns:
        Exit code (0 success, 1 failure).
    """
    from agentkit.failure_corpus.cli import dispatch as _fc_dispatch

    return _fc_dispatch(args)


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


def _cmd_split_story(args: argparse.Namespace, cli_args: list[str]) -> int:
    """Handle ``agentkit split-story`` (FK-54 §54.6, AG3-072)."""
    from agentkit.bootstrap.composition_root import build_story_split_service
    from agentkit.governance.principal_capabilities.principals import Principal
    from agentkit.story_split import StorySplitError, StorySplitRequest, StorySplitService
    from agentkit.story_split.plan_loader import SplitPlanError, load_split_plan

    del cli_args  # not consulted: the human-started CLI path IS the §54.4 approval.
    project_key = os.environ.get("AGENTKIT_PROJECT_KEY", "").strip()
    run_id = os.environ.get("AGENTKIT_RUN_ID", "").strip()
    project_root = os.environ.get("AGENTKIT_PROJECT_ROOT", "").strip() or None
    if not project_key or not run_id:
        print(
            "split-story failed: AGENTKIT_PROJECT_KEY and AGENTKIT_RUN_ID must "
            "identify the source run.",
            file=sys.stderr,
        )
        return 1

    # Read + validate the plan BEFORE any mutation (fail-closed, §54.6).
    try:
        plan, plan_text = load_split_plan(Path(args.plan))
    except SplitPlanError as exc:
        print(f"split-story failed [InvalidPlan]: {exc}", file=sys.stderr)
        return 1

    # FK-54 §54.4 / AK2+AK5: the human split approval is REPRESENTED by this
    # human-started administrative CLI path carrying a valid --plan. The CLI
    # invocation itself IS the approval, so the acting principal of this admin
    # subcommand is human_cli; the bare --story/--plan/--reason command succeeds
    # end to end (no hidden attestation flag).
    principal = Principal.HUMAN_CLI

    stories_root = Path("stories")
    service = build_story_split_service(
        project_key=project_key,
        stories_root=stories_root,
        project_root=project_root,
    )
    if not isinstance(service, StorySplitService):
        print(
            "split-story failed: composition root returned invalid service",
            file=sys.stderr,
        )
        return 1
    try:
        result = service.split_story(
            StorySplitRequest(
                project_key=project_key,
                source_story_id=args.story,
                plan=plan,
                plan_text=plan_text,
                reason=args.reason,
                requested_by=str(principal),
                run_id=run_id,
                principal=principal,
            )
        )
    except StorySplitError as exc:
        print(f"split-story failed: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "status": result.record.status.value,
                "split_id": result.split_id,
                "source_story_id": result.record.source_story_id,
                "successor_ids": list(result.successor_ids),
                "resumed": result.resumed,
            },
            sort_keys=True,
        )
    )
    return 0


def _cmd_reset_story(args: argparse.Namespace) -> int:
    """Handle ``agentkit reset-story`` (FK-53 §53.3, AG3-071).

    The official, human-triggered Story-Reset control path. ``--dry-run`` reports
    the planned purge domains without any destructive mutation; otherwise the full
    §53.7 flow runs (request -> execute) and the §53.8 clean-state verification is
    reported.
    """
    from agentkit.bootstrap.composition_root import build_story_reset_service
    from agentkit.story_reset import (
        PlannedPurge,
        StoryResetError,
        StoryResetRequest,
        StoryResetService,
    )

    project_key = os.environ.get("AGENTKIT_PROJECT_KEY", "").strip()
    if not project_key:
        print(
            "reset-story failed: AGENTKIT_PROJECT_KEY must identify the project.",
            file=sys.stderr,
        )
        return 1
    project_root = os.environ.get("AGENTKIT_PROJECT_ROOT", "").strip() or "."
    store_dir = Path(project_root)

    service = build_story_reset_service(
        project_key=project_key,
        store_dir=store_dir,
        project_root=store_dir,
    )
    if not isinstance(service, StoryResetService):
        print(
            "reset-story failed: composition root returned invalid service",
            file=sys.stderr,
        )
        return 1

    # The human-started CLI invocation IS the §53.2/§53.3 authorisation.
    request = StoryResetRequest(
        project_key=project_key,
        story_id=args.story,
        requested_by="human_cli",
        reason=args.reason,
        escalation_ref=args.escalation_ref,
        dry_run=bool(args.dry_run),
        force=bool(args.force),
    )
    try:
        outcome = service.request_reset(request)
        if isinstance(outcome, PlannedPurge):
            print(
                json.dumps(
                    {
                        "mode": "dry-run",
                        "story_id": outcome.story_id,
                        "run_id": outcome.run_id,
                        "planned_domains": [d.value for d in outcome.planned_domains],
                    },
                    sort_keys=True,
                )
            )
            return 0
        result = service.execute_reset(outcome.reset_id)
    except StoryResetError as exc:
        print(f"reset-story failed: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "status": result.record.status.value,
                "reset_id": result.reset_id,
                "story_id": result.record.story_id,
                "clean_state": result.clean_state.is_clean,
                "purge_summary": result.record.purge_summary,
                "resumed": result.resumed,
            },
            sort_keys=True,
        )
    )
    return 0 if result.clean_state.is_clean else 1


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


# ---------------------------------------------------------------------------
# AG3-076: operator/recovery command registration + handlers
# ---------------------------------------------------------------------------

_VALID_PHASES = frozenset({"setup", "exploration", "implementation", "closure"})


class _ConfigResolutionError(Exception):
    """Raised when ``--config`` is provided but fails to yield a project_key.

    Signals that the caller must fail-closed (non-zero) rather than falling
    through to the environment variable.  Never raised when ``--config`` is
    absent (the fallthrough path is intentional in that case).
    """


def _resolve_project_key(args: argparse.Namespace) -> str | None:
    """Resolve ``project_key`` from CLI args with config and env fallback.

    Resolution order (story §2.1.1):

    1. ``--project`` flag (explicit override).
    2. ``--config`` path: load :class:`~agentkit.config.models.ProjectConfig`
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
            from agentkit.config.loader import load_project_config

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


def _parse_since_cutoff(since_raw: str) -> object:
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
    run_phase_parser.add_argument("--run", required=True, help="Run ID")
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
    run_phase_parser.add_argument("--project", required=False, help="Project key override")
    run_phase_parser.add_argument("--config", required=False, help="Config path override")

    # resume
    resume_parser = subparsers.add_parser(
        "resume",
        help="Resume a PAUSED pipeline phase (AG3-076)",
    )
    resume_parser.add_argument("--story", required=True, help=_STORY_ID_FIELD_LABEL)
    resume_parser.add_argument("--trigger", required=True, help="Resume trigger event name")
    resume_parser.add_argument("--project-root", default=".", help="Project root directory")

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
    status_parser.add_argument("--project-root", default=".", help="Project root directory")

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
    query_state_parser.add_argument("--project-root", default=".", help="Project root directory")

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
    query_tel_parser.add_argument("--project", required=False, help="Project key override")
    query_tel_parser.add_argument("--config", required=False, help="Config path override")
    query_tel_parser.add_argument("--project-root", default=".", help="Project root directory")

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
    export_tel_parser.add_argument("--run", required=True, help="Run ID")
    export_tel_parser.add_argument("--output-dir", required=True, help="Directory to write the bundle into")
    export_tel_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Check output directory reachability/writability only",
    )


# --- run-phase -----------------------------------------------------------------


def _cmd_run_phase(args: argparse.Namespace) -> int:
    """Handle ``agentkit run-phase`` (AG3-076, FK-20).

    Dispatches a single pipeline phase via the control-plane runtime service.

    Args:
        args: Parsed CLI arguments.

    Returns:
        0 on committed/replayed, 1 on rejected/error.
    """
    from agentkit.control_plane.models import PhaseMutationRequest
    from agentkit.control_plane.runtime import ControlPlaneRuntimeService

    phase = args.phase
    if phase not in _VALID_PHASES:
        print(
            f"run-phase failed [InvalidPhase]: {phase!r} is not a valid phase. "
            f"Valid phases: {sorted(_VALID_PHASES)}. "
            "Note: 'verify' is a capability, not a top-level phase (see concept/_meta/bc-cut-decisions.md).",
            file=sys.stderr,
        )
        return 1

    # Resolve project_key: --project > --config > AGENTKIT_PROJECT_KEY (ERROR 2 fix).
    try:
        project_key = _resolve_project_key(args)
    except _ConfigResolutionError as exc:
        print(f"run-phase failed [ConfigResolutionError]: {exc}", file=sys.stderr)
        return 1
    if not project_key:
        print(
            "run-phase failed [MissingProjectKey]: --project, --config-derived key, "
            "or AGENTKIT_PROJECT_KEY is required to identify the project.",
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
        )
    except Exception as exc:  # noqa: BLE001
        print(f"run-phase failed [InvalidRequest]: {exc}", file=sys.stderr)
        return 1

    try:
        service = ControlPlaneRuntimeService()
        result = service.start_phase(
            run_id=args.run,
            phase=phase,
            request=request,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"run-phase failed: {exc}", file=sys.stderr)
        return 1

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
    print(json.dumps(payload, sort_keys=True))
    return 0 if result.status in ("committed", "replayed") else 1


# --- resume --------------------------------------------------------------------


def _cmd_resume(args: argparse.Namespace) -> int:
    """Handle ``agentkit resume`` (AG3-076, FK-45).

    Resumes a PAUSED pipeline phase by loading the StoryContext and the
    PAUSED PhaseEnvelope, building the pipeline engine, and calling
    ``resume_phase``.

    Args:
        args: Parsed CLI arguments.

    Returns:
        0 if status in (phase_completed, yielded), 1 if failed/escalated.
    """
    from agentkit.bootstrap.composition_root import (
        build_phase_envelope_store,
        build_pipeline_engine,
        cli_load_story_context,
    )
    from agentkit.pipeline_engine.phase_executor.models import PhaseName, PhaseStatus
    from agentkit.story_context_manager.types import StoryType

    project_root = Path(args.project_root)
    story_dir = project_root / "stories" / args.story

    ctx = cli_load_story_context(story_dir)
    if ctx is None:
        print(
            f"resume failed [MissingStoryContext]: no StoryContext found at {story_dir}",
            file=sys.stderr,
        )
        return 1

    # Load via public pipeline_engine surface (PhaseEnvelopeStore.load);
    # build_phase_envelope_store wraps the private adapter in bootstrap — CLI
    # must not import StateBackendPhaseEnvelopeRepository directly (ERROR 1 fix,
    # story §2.1.2 / §2.3 anchor: pipeline_engine/phase_envelope/store.py:60).
    envelope_store = build_phase_envelope_store(story_dir)

    # Find the PAUSED envelope across all known phases
    paused_envelope = None
    for phase_name_str in ("setup", "exploration", "implementation", "closure"):
        # PhaseName imported above at function scope

        try:
            phase_name = PhaseName(phase_name_str)
        except ValueError:
            continue
        candidate = envelope_store.load(args.story, phase_name)
        if candidate is not None and candidate.state.status == PhaseStatus.PAUSED:
            paused_envelope = candidate
            break

    if paused_envelope is None:
        print(
            f"resume failed [NoPausedEnvelope]: no PAUSED phase envelope found for story {args.story!r}",
            file=sys.stderr,
        )
        return 1

    story_type_raw = getattr(ctx, "story_type", None)
    try:
        story_type = StoryType(story_type_raw) if story_type_raw is not None else StoryType.IMPLEMENTATION
    except ValueError:
        story_type = StoryType.IMPLEMENTATION

    project_key = getattr(ctx, "project_key", "") or ""

    try:
        engine = build_pipeline_engine(
            story_dir,
            story_type=story_type,
            project_key=project_key,
        )
        result = engine.resume_phase(ctx, paused_envelope, args.trigger)
    except Exception as exc:  # noqa: BLE001
        print(f"resume failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps({"status": result.status, "phase": str(paused_envelope.state.phase)}, sort_keys=True))
    return 0 if result.status in ("phase_completed", "yielded") else 1


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
    from agentkit.bootstrap.composition_root import cli_read_phase_state_record

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

    from agentkit.bootstrap.composition_root import cli_read_phase_state_record

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
    """Validate ``--event`` value against :class:`~agentkit.telemetry.events.EventType`.

    ERROR 4 fix: unknown event type must fail-closed (non-zero + stderr) rather
    than silently dropping the filter or querying all events.

    Args:
        event_type_raw: The raw ``--event`` string from the CLI.

    Returns:
        0 when valid, 1 when the value is not a known :class:`EventType`.
    """
    from agentkit.telemetry.events import EventType

    try:
        EventType(event_type_raw)
        return 0
    except ValueError:
        valid = sorted(e.value for e in EventType)
        print(
            json.dumps(
                {
                    "finding": "InvalidEventType",
                    "value": event_type_raw,
                    "valid_values": valid,
                    "detail": (
                        f"--event {event_type_raw!r} is not a known EventType; "
                        "use one of the listed values."
                    ),
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


def _apply_since_filter(events: list[object], since_cutoff: object) -> list[object]:
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
    from datetime import UTC, datetime

    result = []
    for e in events:
        occ = _pick_event_time(e)
        if occ is None:
            # No recognisable time field present — skip rather than silently
            # retain; the event has no timestamp to compare.
            continue
        if isinstance(occ, str):
            try:
                occ_dt = datetime.fromisoformat(occ)
                if occ_dt.tzinfo is None:
                    occ_dt = occ_dt.replace(tzinfo=UTC)
            except ValueError:
                continue
        elif isinstance(occ, datetime):
            occ_dt = occ if occ.tzinfo is not None else occ.replace(tzinfo=UTC)
        else:
            continue
        if occ_dt >= since_cutoff:  # type: ignore[operator]
            result.append(e)
    return result


def _cmd_query_telemetry_story_form(
    story_id: str,
    project_root: Path,
    event_type_raw: str | None,
    since_cutoff: object,
) -> int:
    """Inner handler for the story-scoped ``query-telemetry`` form.

    Delegates to :class:`~agentkit.telemetry.storage.StateBackendEmitter.query`
    (story §2.1.7 / §2.3 anchor: telemetry/storage.py:89).

    Args:
        story_id: Story display ID.
        project_root: Project root path.
        event_type_raw: Optional validated event-type string.
        since_cutoff: Optional timezone-aware :class:`datetime` lower bound.

    Returns:
        0 on success, 1 on backend error.
    """
    from agentkit.telemetry.events import EventType
    from agentkit.telemetry.storage import StateBackendEmitter

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
    since_cutoff: object = None
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

    # run-scoped or event-type global form: needs project_key.
    # ERROR 2 fix: --config provided but broken -> fail-closed, not env fallback.
    # Note: when --config is present we already ran _resolve_project_key above and it
    # succeeded, so calling it again here is cheap and keeps the resolution logic in
    # one canonical place.
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

    from agentkit.bootstrap.composition_root import cli_load_execution_events_for_project_global

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
    :class:`~agentkit.telemetry.audit_bundle.AuditBundleExporter`.

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

    from agentkit.bootstrap.composition_root import build_projection_accessor
    from agentkit.telemetry.audit_bundle import AuditBundleExporter, AuditBundleExportError
    from agentkit.telemetry.storage import StateBackendEmitter

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
