"""Argparse registration for operator recovery commands."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import argparse


from ._operator_recovery_config import (
    _CONFIG_PATH_OVERRIDE_HELP as _CONFIG_PATH_OVERRIDE_HELP,
)
from ._operator_recovery_config import (
    _PROJECT_KEY_OVERRIDE_HELP as _PROJECT_KEY_OVERRIDE_HELP,
)

_STORY_ID_FIELD_LABEL = "Story ID"
_PROJECT_ROOT_HELP = "Project root directory"
_RUN_ID_HELP = "Run ID"
_OP_ID_HELP = (
    "Client-supplied idempotency key (FK-91 Rule 5). Omit to mint one "
    "client-side; reuse the SAME value to safely retry an ambiguous call."
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
    run_phase_parser.add_argument("--run", required=True, help=_RUN_ID_HELP)
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
    run_phase_parser.add_argument("--project", required=False, help=_PROJECT_KEY_OVERRIDE_HELP)
    run_phase_parser.add_argument("--config", required=False, help=_CONFIG_PATH_OVERRIDE_HELP)
    run_phase_parser.add_argument("--project-root", default=".", help=_PROJECT_ROOT_HELP)
    run_phase_parser.add_argument("--op-id", required=False, help=_OP_ID_HELP)
    run_phase_parser.add_argument(
        "--base-url",
        required=False,
        help="Core control-plane base URL for the phase-dispatch REST call (AG3-130).",
    )

    # resume
    resume_parser = subparsers.add_parser(
        "resume",
        help="Resume a PAUSED pipeline phase via the control plane (AG3-130)",
    )
    resume_parser.add_argument("phase", help="Phase name: setup/exploration/implementation/closure")
    resume_parser.add_argument("--story", required=True, help=_STORY_ID_FIELD_LABEL)
    resume_parser.add_argument("--run", required=True, help=_RUN_ID_HELP)
    resume_parser.add_argument("--session", required=True, help="Session ID")
    resume_parser.add_argument("--principal", required=True, help="Principal type")
    resume_parser.add_argument(
        "--worktree",
        action="append",
        nargs=1,
        required=True,
        dest="worktree",
        metavar="PATH",
        help="Worktree root path (may be repeated)",
    )
    resume_parser.add_argument("--trigger", required=True, help="Resume trigger event name")
    resume_parser.add_argument("--project", required=False, help=_PROJECT_KEY_OVERRIDE_HELP)
    resume_parser.add_argument("--config", required=False, help=_CONFIG_PATH_OVERRIDE_HELP)
    resume_parser.add_argument("--project-root", default=".", help=_PROJECT_ROOT_HELP)
    resume_parser.add_argument("--op-id", required=False, help=_OP_ID_HELP)
    resume_parser.add_argument(
        "--base-url",
        required=False,
        help="Core control-plane base URL for the resume REST call (AG3-130).",
    )

    # admin-abort (AG3-138: admin_abort_inflight_operation, admin_transition)
    admin_abort_parser = subparsers.add_parser(
        "admin-abort",
        help="Administratively abort a hanging server-owned in-flight operation (AG3-138)",
    )
    admin_abort_parser.add_argument("op_id", help="Target in-flight operation id")
    admin_abort_parser.add_argument("--session", required=True, help="Admin session ID (audited)")
    admin_abort_parser.add_argument("--principal", required=True, help="Admin principal type (audited)")
    admin_abort_parser.add_argument("--reason", required=True, help="Mandatory audited justification for the abort")
    admin_abort_parser.add_argument("--project-root", default=".", help=_PROJECT_ROOT_HELP)
    admin_abort_parser.add_argument(
        "--base-url",
        required=False,
        help="Core control-plane base URL for the admin-abort REST call (AG3-138).",
    )

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
    status_parser.add_argument("--project-root", default=".", help=_PROJECT_ROOT_HELP)

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
    query_state_parser.add_argument("--project-root", default=".", help=_PROJECT_ROOT_HELP)

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
        help=("Lower-bound window for event filtering. Supports {N}d/{N}h/{N}m (e.g. 7d, 24h, 30m) or an ISO-8601 timestamp."),
    )
    query_tel_parser.add_argument("--project", required=False, help=_PROJECT_KEY_OVERRIDE_HELP)
    query_tel_parser.add_argument("--config", required=False, help=_CONFIG_PATH_OVERRIDE_HELP)
    query_tel_parser.add_argument("--project-root", default=".", help=_PROJECT_ROOT_HELP)

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
    export_tel_parser.add_argument("--run", required=True, help=_RUN_ID_HELP)
    export_tel_parser.add_argument("--output-dir", required=True, help="Directory to write the bundle into")
    export_tel_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Check output directory reachability/writability only",
    )


__all__ = ["_setup_operator_recovery_subparsers"]
