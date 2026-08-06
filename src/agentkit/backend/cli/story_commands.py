"""Story administration and story document CLI command handlers."""

from __future__ import annotations

import getpass
import json
import os
import sys
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from agentkit.backend.vectordb.project_binding import (
    ProjectBindingError,
    resolve_authoritative_project_id,
)

if TYPE_CHECKING:
    import argparse
    from collections.abc import Callable

    from agentkit.backend.story_creation.story_md_export import (
        StoryAttributesPort,
        StoryIndexPort,
    )

_STORY_ID_FIELD_LABEL = "Story ID"
_PROJECT_ROOT_HELP = "Project root directory"


def add_story_parsers(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Register story-scoped administrative and document commands."""
    run_parser = subparsers.add_parser(
        "run-story", help="Run a story through the pipeline",
    )
    run_parser.add_argument(
        "--story", required=True, help=_STORY_ID_FIELD_LABEL,
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

    split_parser = subparsers.add_parser(
        "split-story",
        help="Administratively split a scope-exploded story into successors",
    )
    split_parser.add_argument("--story", required=True, help="Source story ID")
    split_parser.add_argument(
        "--plan", required=True, help="Path to the human-approved split-plan JSON"
    )
    split_parser.add_argument("--reason", required=True, help="Split reason")
    split_parser.add_argument("--project", required=False, help="Project key")
    split_parser.add_argument("--run", required=False, help="Source run ID")
    split_parser.add_argument("--project-root", default=None, help=_PROJECT_ROOT_HELP)
    split_parser.add_argument(
        "--base-url",
        required=False,
        help="Core Project-API base URL",
    )
    split_parser.add_argument("--username", default="admin", help="Strategist username")
    split_parser.add_argument("--ca-file", default=None, help="Trusted control-plane CA certificate")

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
    reset_parser.add_argument("--project", required=False, help="Project key")
    reset_parser.add_argument("--project-root", default=None, help=_PROJECT_ROOT_HELP)
    reset_parser.add_argument("--base-url", required=False, help="Core Project-API base URL")
    reset_parser.add_argument("--username", default="admin", help="Strategist username")
    reset_parser.add_argument("--ca-file", default=None, help="Trusted control-plane CA certificate")

    exit_parser = subparsers.add_parser(
        "exit-story", help="Administratively exit a bound story run",
    )
    exit_parser.add_argument("--story", required=True, help=_STORY_ID_FIELD_LABEL)
    exit_parser.add_argument("--reason", required=True, help="FK-58 exit reason code")
    exit_parser.add_argument("--note", required=False, help="Optional human note")
    exit_parser.add_argument("--project", required=False, help="Project key")
    exit_parser.add_argument("--run", required=False, help="Bound run ID")
    exit_parser.add_argument("--project-root", default=None, help=_PROJECT_ROOT_HELP)
    exit_parser.add_argument("--base-url", required=False, help="Core Project-API base URL")
    exit_parser.add_argument("--username", default="admin", help="Strategist username")
    exit_parser.add_argument("--ca-file", default=None, help="Trusted control-plane CA certificate")

    doctor_parser = subparsers.add_parser(
        "doctor", help="Check AgentKit installation health",
    )
    doctor_parser.add_argument(
        "--project-root",
        default=".",
        help=_PROJECT_ROOT_HELP,
    )

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
    export_story_md_parser.add_argument(
        "--project-id",
        required=False,
        help=(
            "Cross-check against the AUTHORITATIVE project id (project_prefix / "
            "PROJECT_ID). A divergent value is rejected (D2)."
        ),
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
    repair_story_md_parser.add_argument(
        "--project-id",
        required=False,
        help=(
            "Cross-check against the AUTHORITATIVE project id (project_prefix / "
            "PROJECT_ID). A divergent value is rejected (D2)."
        ),
    )


def _cmd_run_story(args: argparse.Namespace) -> int:
    """Handle ``agentkit run-story`` command.

    Minimal implementation that prints story information.
    Full pipeline integration is pending implementation of
    the remaining phase handlers.

    Args:
        args: Parsed CLI arguments with ``story``, ``owner``, ``repo``, and
            ``project_root``.

    Returns:
        Exit code: 0 (always, as this is currently a stub).
    """
    print(f"Running story {args.story}")
    print(
        f"  repo: {args.owner}/{args.repo}  "
        f"root: {args.project_root}"
    )
    print("Note: Full pipeline execution pending phase handler implementation")
    return 0


def _cmd_watch_worker(args: argparse.Namespace) -> int:
    """Handle ``agentkit watch-worker`` through the writer-owned REST state."""

    from pathlib import Path

    from agentkit.backend.implementation.worker_health.rest_repository import (
        RestWorkerHealthRepository,
    )
    from agentkit.backend.implementation.worker_health.sidecar import (
        run_worker_health_sidecar,
    )
    from agentkit.harness_client.projectedge.governance_client import (
        build_governance_edge_client,
    )

    try:
        project_root = Path(args.project_root)
        return run_worker_health_sidecar(
            args.story_id,
            project_root=project_root,
            repository=RestWorkerHealthRepository(
                build_governance_edge_client(project_root),
            ),
        )
    except Exception as exc:  # noqa: BLE001
        print(f"watch-worker failed: {exc}", file=sys.stderr)
        return 1


def _cmd_split_story(args: argparse.Namespace, cli_args: list[str]) -> int:
    """Handle ``agentkit split-story`` through the active writer's REST route."""
    from agentkit.backend.cli._operator_recovery_phase import (
        _build_strategist_control_plane_client,
    )
    from agentkit.backend.config.defaults import DEFAULT_CONTROL_PLANE_BASE_URL
    from agentkit.backend.story_split.http_models import StorySplitMutationRequest
    from agentkit.backend.story_split.plan_loader import SplitPlanError, load_split_plan

    del cli_args  # not consulted: the human-started CLI path IS the §54.4 approval.
    project_key = str(getattr(args, "project", "") or os.environ.get("AGENTKIT_PROJECT_KEY", "")).strip()
    run_id = str(getattr(args, "run", "") or os.environ.get("AGENTKIT_RUN_ID", "")).strip()
    project_root = str(
        getattr(args, "project_root", "")
        or os.environ.get("AGENTKIT_PROJECT_ROOT", "")
        or ".",
    )
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

    if plan.project_key != project_key or plan.source_story_id != args.story:
        print(
            "split-story failed [PlanScopeMismatch]: plan project/source does "
            "not match the requested route.",
            file=sys.stderr,
        )
        return 1
    base_url = str(getattr(args, "base_url", "") or DEFAULT_CONTROL_PLANE_BASE_URL)
    try:
        client = _build_strategist_control_plane_client(
            base_url,
            project_root,
            project_key,
            str(getattr(args, "username", "admin")),
            getpass.getpass("Strategist password: "),
            getattr(args, "ca_file", None),
        )
        result = client.split_story(
            project_key=project_key,
            story_id=str(args.story),
            request=StorySplitMutationRequest(
                plan_text=plan_text,
                reason=str(args.reason),
                run_id=run_id,
                project_root=project_root,
            ),
        )
    except Exception as exc:  # noqa: BLE001 - CLI maps the authenticated remote boundary
        from agentkit.backend.cli._operator_ownership_commands import _emit_error

        return _emit_error("split-story", exc)
    print(
        json.dumps(result.model_dump(mode="json"), sort_keys=True),
    )
    if result.status != "committed":
        return 1
    return 0


def _cmd_reset_story(args: argparse.Namespace) -> int:
    """Handle ``agentkit reset-story`` through the active writer's REST route."""
    from agentkit.backend.cli._operator_recovery_phase import (
        _build_strategist_control_plane_client,
    )
    from agentkit.backend.config.defaults import DEFAULT_CONTROL_PLANE_BASE_URL
    from agentkit.backend.story_reset.http_models import StoryResetMutationRequest

    project_key = str(
        getattr(args, "project", "") or os.environ.get("AGENTKIT_PROJECT_KEY", ""),
    ).strip()
    if not project_key:
        print(
            "reset-story failed: AGENTKIT_PROJECT_KEY must identify the project.",
            file=sys.stderr,
        )
        return 1
    project_root = str(
        getattr(args, "project_root", "")
        or os.environ.get("AGENTKIT_PROJECT_ROOT", "")
        or ".",
    )
    base_url = str(getattr(args, "base_url", "") or DEFAULT_CONTROL_PLANE_BASE_URL)
    try:
        client = _build_strategist_control_plane_client(
            base_url,
            project_root,
            project_key,
            str(getattr(args, "username", "admin")),
            getpass.getpass("Strategist password: "),
            getattr(args, "ca_file", None),
        )
        result = client.reset_story(
            project_key=project_key,
            story_id=str(args.story),
            request=StoryResetMutationRequest(
                op_id=f"story-reset-{uuid.uuid4().hex}",
                reason=str(args.reason),
                project_root=project_root,
                escalation_ref=getattr(args, "escalation_ref", None),
                dry_run=bool(args.dry_run),
                force=bool(args.force),
            ),
        )
    except Exception as exc:  # noqa: BLE001 - CLI maps the authenticated remote boundary
        from agentkit.backend.cli._operator_ownership_commands import _emit_error

        return _emit_error("reset-story", exc)
    print(json.dumps(result.model_dump(mode="json"), sort_keys=True))
    return 0 if result.mode == "dry-run" or result.clean_state else 1


def _cmd_exit_story(args: argparse.Namespace, cli_args: list[str]) -> int:
    """Handle ``agentkit exit-story`` through the active writer's REST route."""
    from agentkit.backend.cli._operator_recovery_phase import (
        _build_strategist_control_plane_client,
    )
    from agentkit.backend.config.defaults import DEFAULT_CONTROL_PLANE_BASE_URL
    from agentkit.backend.story_exit import ExitReason
    from agentkit.backend.story_exit.http_models import StoryExitMutationRequest

    del cli_args

    try:
        reason = ExitReason(args.reason)
    except ValueError:
        print(f"exit-story failed: invalid reason code {args.reason!r}", file=sys.stderr)
        return 1

    project_key = str(
        getattr(args, "project", "") or os.environ.get("AGENTKIT_PROJECT_KEY", ""),
    ).strip()
    run_id = str(getattr(args, "run", "") or os.environ.get("AGENTKIT_RUN_ID", "")).strip()
    if not project_key or not run_id:
        print(
            "exit-story failed: AGENTKIT_PROJECT_KEY and AGENTKIT_RUN_ID must "
            "identify the bound run.",
            file=sys.stderr,
        )
        return 1
    project_root = str(
        getattr(args, "project_root", "")
        or os.environ.get("AGENTKIT_PROJECT_ROOT", "")
        or ".",
    )
    base_url = str(getattr(args, "base_url", "") or DEFAULT_CONTROL_PLANE_BASE_URL)
    try:
        client = _build_strategist_control_plane_client(
            base_url,
            project_root,
            project_key,
            str(getattr(args, "username", "admin")),
            getpass.getpass("Strategist password: "),
            getattr(args, "ca_file", None),
        )
        result = client.exit_story(
            project_key=project_key,
            story_id=str(args.story),
            request=StoryExitMutationRequest(
                op_id=f"story-exit-{uuid.uuid4().hex}",
                run_id=run_id,
                reason=reason.value,
                note=getattr(args, "note", None),
            ),
        )
    except Exception as exc:  # noqa: BLE001 - CLI maps the authenticated remote boundary
        from agentkit.backend.cli._operator_ownership_commands import _emit_error

        return _emit_error("exit-story", exc)
    print(json.dumps(result.model_dump(mode="json"), sort_keys=True))
    return 0


def _cmd_doctor(args: argparse.Namespace) -> int:
    """Handle ``agentkit doctor`` command.

    Performs basic health checks: verifies that required external
    tools (``gh``, ``git``) are available and prints the AgentKit
    version.

    Returns:
        Exit code: 0 (always).
    """
    import shutil

    from agentkit import __version__

    project_root = Path(args.project_root).resolve()
    print("AgentKit Doctor")
    print(f"  project root: {project_root}")
    project_config = project_root / ".agentkit" / "config" / "project.yaml"
    print(f"  project config: {'found' if project_config.is_file() else 'NOT FOUND'}")
    print(f"  gh CLI: {'found' if shutil.which('gh') else 'NOT FOUND'}")
    print(f"  git:    {'found' if shutil.which('git') else 'NOT FOUND'}")
    print(f"  version: {__version__}")
    return 0


def _build_weaviate_index(project_root: str | None) -> StoryIndexPort:
    """Build the Weaviate story-index shim from the consumed vectordb config.

    The ``vectordb`` config stanza is owned exclusively by AG3-070; this only
    CONSUMES host/port. Fails closed when Weaviate / weaviate-client is absent.
    """
    from agentkit.backend.exceptions import ConfigError
    from agentkit.backend.story_creation.weaviate_index import WeaviateStoryIndex
    from agentkit.backend.vectordb.commit_recovery import (
        project_commit_recovery_journal,
    )
    from agentkit.backend.vectordb.wait_for_weaviate import resolve_adapter_endpoints
    from agentkit.integration_clients.vectordb import WeaviateStoryAdapter
    from agentkit.integration_clients.vectordb.errors import (
        VectorDbUnavailableError,
    )

    if project_root is None:
        raise VectorDbUnavailableError(
            "story indexing requires an explicit project root for durable "
            "completion recovery"
        )
    root = Path(project_root)
    try:
        connect_kwargs = resolve_adapter_endpoints(project_root)
    except ConfigError as exc:
        raise VectorDbUnavailableError(
            f"story indexing project configuration is unavailable: {exc}"
        ) from exc
    adapter = WeaviateStoryAdapter.connect(**connect_kwargs)  # type: ignore[arg-type]
    return WeaviateStoryIndex(
        adapter,
        recovery_journal=project_commit_recovery_journal(root),
    )


def _build_story_attributes() -> StoryAttributesPort:
    """Build the authoritative AK3 story read surface (``StoryService``).

    Extracted as a seam so the CLI export/repair handlers can be exercised with
    an in-memory story source without a live state backend (mocks exception: the
    Weaviate / story-backend boundary).
    """
    from agentkit.backend.story_context_manager.service import StoryService

    return StoryService()


def _authoritative_project_id(args: argparse.Namespace) -> str:
    """Derive the AUTHORITATIVE project id for a story-document command (N06/D2).

    The CLI ``--project-id`` is a cross-check, not a source of truth: the value
    comes from the project configuration (``project_prefix``) or, when no config
    is resolvable, from the ``PROJECT_ID`` environment binding. A missing
    authority and a divergent supplied value are both hard errors -- there is no
    empty fallback and no arbitrary project override.
    """
    return resolve_authoritative_project_id(
        project_root=getattr(args, "project_root", None),
        supplied=getattr(args, "project_id", None),
        env=os.environ,
    )


def _cmd_export_story_md(
    args: argparse.Namespace,
    *,
    build_weaviate_index: Callable[[str | None], StoryIndexPort] = _build_weaviate_index,
    build_story_attributes: Callable[[], StoryAttributesPort] = _build_story_attributes,
) -> int:
    """Handle ``agentkit export-story-md`` (FK-21 §21.11)."""
    from pathlib import Path

    from agentkit.backend.story_creation.story_md_export import export_story_md
    from agentkit.integration_clients.vectordb import VectorDbError

    try:
        project_id = _authoritative_project_id(args)
    except ProjectBindingError as exc:
        print(f"export-story-md failed [ProjectBinding]: {exc}", file=sys.stderr)
        return 1

    story_dir = Path(args.story_dir)
    project_root = (
        Path(args.project_root)
        if args.project_root
        else story_dir.parent.parent
    )
    try:
        index = build_weaviate_index(str(project_root))
    except VectorDbError as exc:
        print(f"export-story-md failed [VectorDbUnavailable]: {exc}", file=sys.stderr)
        return 1

    result = export_story_md(
        args.story_id,
        story_dir,
        project_id=project_id,
        # N31: the authoritative project root the corpus path is validated against.
        # ``--project-root`` when given, else the parent of the ``stories/`` root
        # the story directory lives in.
        project_root=project_root,
        story_attributes=build_story_attributes(),
        index=index,
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


def _cmd_repair_story_md(
    args: argparse.Namespace,
    *,
    build_weaviate_index: Callable[[str | None], StoryIndexPort] = _build_weaviate_index,
    build_story_attributes: Callable[[], StoryAttributesPort] = _build_story_attributes,
) -> int:
    """Handle ``agentkit repair-story-md`` (FK-21 §21.11.6)."""
    from pathlib import Path

    from agentkit.backend.story_creation.repair_story_md import repair_story_md
    from agentkit.integration_clients.vectordb import VectorDbError

    try:
        project_id = _authoritative_project_id(args)
    except ProjectBindingError as exc:
        print(f"repair-story-md failed [ProjectBinding]: {exc}", file=sys.stderr)
        return 1

    stories_root = Path(args.stories_root)
    project_root = (
        Path(args.project_root)
        if args.project_root
        else stories_root.parent
    )
    try:
        index = build_weaviate_index(str(project_root))
    except VectorDbError as exc:
        print(f"repair-story-md failed [VectorDbUnavailable]: {exc}", file=sys.stderr)
        return 1

    report = repair_story_md(
        stories_root,
        project_id=project_id,
        story_attributes=build_story_attributes(),
        index=index,
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
