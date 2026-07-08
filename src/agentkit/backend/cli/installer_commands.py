"""Installer and project-registration CLI command handlers."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlsplit, urlunsplit

if TYPE_CHECKING:
    from collections.abc import Sequence

    from agentkit.backend.installer.runner import InstallConfig
    from agentkit.integration_clients.sonar import SonarClient


def add_installer_parsers(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Register installer and project-registration subcommands."""
    # install -- deprecated compatibility alias.
    install_parser = subparsers.add_parser(
        "install",
        help="[deprecated] Use 'register-project' (level 3); see FK-10 §10.2.0",
    )
    install_parser.add_argument("--project-key", required=True)
    install_parser.add_argument("--project-name", required=True)
    install_parser.add_argument("--project-root", required=True)
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
    install_parser.add_argument(
        "--default-project-structure",
        action="store_true",
        help=(
            "Create the optional AgentKit default target-project structure "
            "(concepts/, codebase/, temp/, input/_meetings/, guardrails/, stories/)."
        ),
    )
    install_parser.add_argument(
        "--multi-repo",
        action="store_true",
        help=(
            "Use multi-repository mode. Only in this mode is codebase/ ignored "
            "by the root repository."
        ),
    )
    install_parser.add_argument(
        "--code-repo",
        action="append",
        default=[],
        metavar="NAME=URL",
        help=(
            "Explicit code repository for --multi-repo. Repeatable. The installer "
            "registers it at codebase/NAME and clones URL when the directory is absent."
        ),
    )
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
        "uninstall",
        help="[deprecated] Use 'detach' (level 3); see FK-10 §10.2.9",
    )
    uninstall_parser.add_argument("--project-root", required=True)

    _add_register_verify_parsers(subparsers)
    _add_upgrade_parser(subparsers)


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
    from agentkit.backend.installer.github_coordinates import (
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
    using the installer from :mod:`agentkit.backend.installer`.

    Args:
        args: Parsed CLI arguments with ``project_name`` and
            ``project_root``.

    Returns:
        Exit code: 0 on success, 1 on failure.
    """
    from pathlib import Path

    from agentkit.backend.exceptions import InstallationError
    from agentkit.backend.installer import InstallConfig, install_agentkit

    # AG3-122 (FK-10 §10.2.0): the generic 'install' verb conflated levels and is
    # retired to a deprecated alias. Point the operator at the level-3 verb.
    print(
        "agentkit install is deprecated (it conflated install levels). Use the "
        "level-specific verbs: 'register-project' (level 3 project), 'serve' "
        "(level 1 core), 'decommission' (level 1/2). See FK-10 §10.2.0.",
        file=sys.stderr,
    )
    project_root = Path(args.project_root)

    # AG3-039 (FK-50 §50.3 CP 7): resolve the MANDATORY github coordinates
    # (flags take precedence, else derive from origin) and validate them
    # fail-closed BEFORE any project write. A ``None`` result means the failure
    # reason was already printed to stderr.
    coordinates = _resolve_github_coordinates(args, project_root)
    if coordinates is None:
        return 1
    github_owner, github_repo = coordinates
    repositories = _parse_code_repo_args(getattr(args, "code_repo", ()))
    if repositories is None:
        return 1
    if repositories and not args.multi_repo:
        print("--code-repo requires --multi-repo.", file=sys.stderr)
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
        default_project_structure=bool(args.default_project_structure),
        multi_repo=bool(args.multi_repo),
        repositories=repositories,
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
    _wire_live_install_integrations(config)
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


def _wire_live_install_integrations(config: InstallConfig) -> None:
    """Attach productive Sonar/Jenkins clients for CLI installs when configured.

    The installer preflight checks are intentionally fail-closed. The CLI is the
    production composition boundary for a normal ``agentkit install`` invocation,
    so it must build the live adapters from environment/secret-store variables
    instead of relying on tests to inject them.
    """
    _wire_sonar_install_integration(config)
    _wire_ci_install_integration(config)
    _wire_branch_plugin_self_test_integration(config)


def _wire_sonar_install_integration(config: InstallConfig) -> None:
    if not bool(getattr(config, "sonarqube_available", False)):
        return

    sonar_url = os.environ.get("SONAR_URL")
    if sonar_url:
        config.sonarqube_base_url = sonar_url.rstrip("/")

    token_env = _first_present_env_name(
        "SONARQUBE_TOKEN",
        "SONAR_TOKEN",
        "SONAR_PASSWORD",
    )
    if token_env is not None:
        config.sonarqube_token_env = token_env

    base_url = str(config.sonarqube_base_url or "")
    resolved_token_env = str(config.sonarqube_token_env or "")
    token = os.environ.get(resolved_token_env, "")
    if base_url and token:
        from agentkit.integration_clients.sonar import SonarClient

        sonar_user = os.environ.get("SONAR_USER", "")
        config.sonar_client = SonarClient(base_url, token, user=sonar_user)
        if sonar_user.lower() == "admin":
            from agentkit.backend.installer.integration_checkpoints.sonar_preflight import (
                ADMINISTER_ISSUES,
            )

            config.sonar_token_permissions = frozenset({ADMINISTER_ISSUES})


def _wire_ci_install_integration(config: InstallConfig) -> None:
    if not bool(getattr(config, "ci_available", False)):
        return

    jenkins_url = os.environ.get("JENKINS_URL")
    if jenkins_url:
        base_url, pipeline = _split_jenkins_url(jenkins_url)
        config.ci_base_url = base_url
        if pipeline:
            config.ci_pipeline = pipeline

    token_env = _first_present_env_name(
        "JENKINS_API_TOKEN", "JENKINS_TOKEN", "JENKINS_PASSWORD"
    )
    if token_env is not None:
        config.ci_token_env = token_env

    base_url = str(config.ci_base_url or "")
    resolved_token_env = str(config.ci_token_env or "")
    token = os.environ.get(resolved_token_env, "")
    if base_url and token:
        from agentkit.integration_clients.jenkins import JenkinsClient

        config.ci_client = JenkinsClient(
            base_url,
            token,
            user=os.environ.get("JENKINS_USER", ""),
        )


def _wire_branch_plugin_self_test_integration(config: InstallConfig) -> None:
    if config.sonar_branch_plugin_self_test is not None:
        return
    if not bool(getattr(config, "sonarqube_available", False)):
        return
    if not bool(getattr(config, "ci_available", False)):
        return
    if config.sonar_client is None or config.ci_client is None or not config.ci_pipeline:
        return

    from agentkit.backend.installer.integration_checkpoints.branch_plugin_self_test import (
        run_branch_plugin_conformance_self_test,
    )
    from agentkit.backend.installer.integration_checkpoints.jenkins_selftest_harness import (
        JenkinsBranchPluginSelfTestHarness,
    )

    harness = JenkinsBranchPluginSelfTestHarness(
        sonar_client=config.sonar_client,
        jenkins_client=config.ci_client,
        pipeline=config.ci_pipeline,
    )

    def _self_test(client: SonarClient) -> bool:
        return run_branch_plugin_conformance_self_test(client, harness)

    config.sonar_branch_plugin_self_test = _self_test


def _first_present_env_name(*names: str) -> str | None:
    for name in names:
        if os.environ.get(name):
            return name
    return None


def _split_jenkins_url(raw_url: str) -> tuple[str, str | None]:
    """Return ``(jenkins_base_url, job_name)`` from root or job URLs."""
    parsed = urlsplit(raw_url.rstrip("/"))
    parts = [part for part in parsed.path.split("/") if part]
    job_name: str | None = None
    if "job" in parts:
        job_index = parts.index("job")
        if job_index + 1 < len(parts):
            job_name = parts[job_index + 1]
            parts = parts[:job_index]
    base_path = "/" + "/".join(parts) if parts else ""
    return urlunsplit((parsed.scheme, parsed.netloc, base_path, "", "")), job_name


def _cmd_uninstall(args: argparse.Namespace) -> int:
    """Handle ``agentkit uninstall`` command."""

    from pathlib import Path

    from agentkit.backend.installer import uninstall_agentkit

    # AG3-122 (FK-10 §10.2.9): 'uninstall' is retired to a deprecated alias that
    # delegates to the single level-3 detach teardown path (no second path).
    print(
        "agentkit uninstall is deprecated. Use 'agentkit detach' (level-3 "
        "project-detach). Delegating to the same teardown path.",
        file=sys.stderr,
    )
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
        "--default-project-structure",
        action="store_true",
        help="Create the optional AgentKit default target-project structure.",
    )
    register_parser.add_argument(
        "--multi-repo",
        action="store_true",
        help="Use multi-repository mode for the optional default structure.",
    )
    register_parser.add_argument(
        "--code-repo",
        action="append",
        default=[],
        metavar="NAME=URL",
        help=(
            "Explicit code repository for --multi-repo. Repeatable. The installer "
            "registers it at codebase/NAME and clones URL when the directory is absent."
        ),
    )
    _add_sonar_ci_availability_flags(register_parser)
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
    _add_sonar_ci_availability_flags(verify_parser)


def _add_sonar_ci_availability_flags(parser: argparse.ArgumentParser) -> None:
    """Add the shared Sonar/Jenkins applicability flags to installer commands."""
    parser.add_argument(
        "--sonarqube-available",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Declare SonarQube present for this code-producing project "
            "(FK-03 §3 default). Use --no-sonarqube-available only for the "
            "conscious opt-out."
        ),
    )
    parser.add_argument(
        "--ci-available",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Declare a CI (Jenkins) pre-merge runner present for this "
            "code-producing project. Use --no-ci-available only for the "
            "conscious opt-out."
        ),
    )


def _build_engine_config(args: argparse.Namespace) -> object | None:
    """Build the :class:`InstallConfig` for the engine-driven subcommands.

    Resolves the github coordinates fail-closed (flags or origin remote) exactly
    like ``install``. Returns ``None`` (reason already printed) on a coordinate
    failure.
    """
    from agentkit.backend.installer.repo_probe import GhCliRepoExistenceProbe
    from agentkit.backend.installer.runner import InstallConfig

    project_root = Path(args.project_root)
    coordinates = _resolve_github_coordinates(args, project_root)
    if coordinates is None:
        return None
    github_owner, github_repo = coordinates
    repositories = _parse_code_repo_args(getattr(args, "code_repo", ()))
    if repositories is None:
        return None
    if repositories and not bool(getattr(args, "multi_repo", False)):
        print("--code-repo requires --multi-repo.", file=sys.stderr)
        return None
    return InstallConfig(
        project_key=args.project_key,
        project_name=args.project_name,
        project_root=project_root,
        default_project_structure=bool(getattr(args, "default_project_structure", False)),
        multi_repo=bool(getattr(args, "multi_repo", False)),
        repositories=repositories,
        github_owner=github_owner,
        github_repo=github_repo,
        # CP 2 probes the live GitHub repo via the productive gh probe (FK-50
        # §50.3 CP 2 / §50.6); a missing/unreachable repo FAILs closed.
        repo_existence_probe=GhCliRepoExistenceProbe(),
        sonarqube_available=bool(getattr(args, "sonarqube_available", True)),
        ci_available=bool(getattr(args, "ci_available", True)),
    )


def _parse_code_repo_args(raw_values: Sequence[str] | None) -> list[dict[str, str]] | None:
    values = list(raw_values or [])
    repositories: list[dict[str, str]] = []
    for raw in values:
        if not isinstance(raw, str) or "=" not in raw:
            print(
                "--code-repo must use NAME=URL syntax, for example --code-repo frontend=https://github.example/frontend.git",
                file=sys.stderr,
            )
            return None
        name, remote_url = raw.split("=", 1)
        name = name.strip()
        remote_url = remote_url.strip()
        if not name or "/" in name or "\\" in name or not remote_url:
            print(
                "--code-repo requires a simple repository name and a non-empty URL.",
                file=sys.stderr,
            )
            return None
        repositories.append(
            {"name": name, "path": f"codebase/{name}", "remote_url": remote_url}
        )
    return repositories


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
    from agentkit.backend.exceptions import ProjectError
    from agentkit.backend.installer.bootstrap_checkpoints.orchestrator import (
        run_checkpoint_install,
    )
    from agentkit.backend.installer.checkpoint_engine.execution_mode import ExecutionMode

    config = _build_engine_config(args)
    if config is None:
        return 1
    _wire_live_install_integrations(config)  # type: ignore[arg-type]
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
    from agentkit.backend.exceptions import ProjectError
    from agentkit.backend.installer.bootstrap_checkpoints.orchestrator import (
        run_checkpoint_install,
    )
    from agentkit.backend.installer.checkpoint_engine.execution_mode import ExecutionMode

    config = _build_engine_config(args)
    if config is None:
        return 1
    _wire_live_install_integrations(config)  # type: ignore[arg-type]
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
    from agentkit.backend.exceptions import ProjectError
    from agentkit.backend.installer.checkpoint_engine.execution_mode import ExecutionMode
    from agentkit.backend.installer.upgrade.entry import run_checkpoint_upgrade
    from agentkit.backend.installer.upgrade.footprint import CustomizationPreservationError

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
