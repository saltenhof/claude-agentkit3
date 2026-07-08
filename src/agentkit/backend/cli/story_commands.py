"""Story administration and story document CLI command handlers."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
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
    """Handle ``agentkit watch-worker`` sidecar command."""

    from pathlib import Path

    from agentkit.backend.implementation.worker_health.sidecar import (
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
    from agentkit.backend.bootstrap.composition_root import build_story_split_service
    from agentkit.backend.governance.principal_capabilities.principals import Principal
    from agentkit.backend.story_split import StorySplitError, StorySplitRequest, StorySplitService
    from agentkit.backend.story_split.plan_loader import SplitPlanError, load_split_plan

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
    from agentkit.backend.bootstrap.composition_root import build_story_reset_service
    from agentkit.backend.story_reset import (
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

    from agentkit.backend.bootstrap.composition_root import build_story_exit_service
    from agentkit.backend.governance.guard_evaluation import HookEvent
    from agentkit.backend.governance.principal_capabilities.principals import PrincipalResolver
    from agentkit.backend.story_exit import ExitReason, StoryExitRequest, StoryExitService

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
    from agentkit.backend.story_creation.weaviate_index import WeaviateStoryIndex
    from agentkit.backend.vectordb.wait_for_weaviate import _resolve_host_port
    from agentkit.integration_clients.vectordb import WeaviateStoryAdapter

    host, port = _resolve_host_port(project_root)
    adapter = WeaviateStoryAdapter.connect(host=host, port=port)
    return WeaviateStoryIndex(adapter)


def _build_story_attributes() -> StoryAttributesPort:
    """Build the authoritative AK3 story read surface (``StoryService``).

    Extracted as a seam so the CLI export/repair handlers can be exercised with
    an in-memory story source without a live state backend (mocks exception: the
    Weaviate / story-backend boundary).
    """
    from agentkit.backend.story_context_manager.service import StoryService

    return StoryService()


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
        index = build_weaviate_index(args.project_root)
    except VectorDbError as exc:
        print(f"export-story-md failed [VectorDbUnavailable]: {exc}", file=sys.stderr)
        return 1

    result = export_story_md(
        args.story_id,
        Path(args.story_dir),
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
        index = build_weaviate_index(args.project_root)
    except VectorDbError as exc:
        print(f"repair-story-md failed [VectorDbUnavailable]: {exc}", file=sys.stderr)
        return 1

    report = repair_story_md(
        Path(args.stories_root),
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
