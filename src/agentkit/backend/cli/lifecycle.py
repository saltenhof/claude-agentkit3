"""CLI operator adapter for the install-trinity lifecycle verbs (AG3-122).

Thin entry-boundary wiring for the level-specific lifecycle verbs of FK-10
§10.2.0 (``serve``/``ui`` for level 1, ``update`` for level 2, ``detach`` for
level 3, ``decommission`` for level 1/2). All business logic lives in the owner
modules (``cli.serve``, ``installer.lifecycle.*``); this module only parses
operator input and renders results.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import argparse
    from collections.abc import Callable, Sequence

    from agentkit.backend.installer.lifecycle.decommission import PinnedProject

#: Shared ``--project-root`` help label.
_PROJECT_ROOT_HELP = "Project root directory"


def add_lifecycle_parsers(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Register the level-specific lifecycle subcommands (FK-10 §10.2.0)."""
    _add_serve_parser(subparsers)
    _add_ui_parser(subparsers)
    _add_update_parser(subparsers)
    _add_detach_parser(subparsers)
    _add_decommission_parser(subparsers)


def _add_serve_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    serve_parser = subparsers.add_parser(
        "serve",
        help="Run the AK3 Core backend listener (level 1, FK-10 §10.2.5)",
    )
    profile = serve_parser.add_mutually_exclusive_group(required=True)
    profile.add_argument(
        "--ui-bff", action="store_true", help="UI-BFF profile (default port 9701)"
    )
    profile.add_argument(
        "--project-api",
        action="store_true",
        help="Project-API profile (default port 9702)",
    )
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=None)
    serve_parser.add_argument("--certfile", required=True)
    serve_parser.add_argument("--keyfile")


def _add_ui_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    ui_parser = subparsers.add_parser(
        "ui", help="Serve the AK3 SPA frontend (level 1, FK-10 §10.2.5)"
    )
    ui_parser.add_argument("--host", default="127.0.0.1")
    ui_parser.add_argument("--port", type=int, default=None)
    ui_parser.add_argument(
        "--dist-dir", default=None, help="SPA bundle dir (defaults to the packaged bundle)"
    )


def _add_update_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    update_parser = subparsers.add_parser(
        "update",
        help="Hybrid update driver: read the Core compat window (level 2, FK-10 §10.2.8)",
    )
    update_parser.add_argument(
        "--base-url",
        required=True,
        help="Core control-plane base URL for GET /v1/compat (AG3-121).",
    )
    update_parser.add_argument(
        "--skill-bundle-version",
        default=None,
        help="Locally bound skill-bundle version (handshake header).",
    )


def _add_detach_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    detach_parser = subparsers.add_parser(
        "detach", help="Remove AK3 bindings from a project (level 3, FK-10 §10.2.9)"
    )
    detach_parser.add_argument("--project-root", required=True, help=_PROJECT_ROOT_HELP)


def _add_decommission_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    decommission_parser = subparsers.add_parser(
        "decommission",
        help="Machine-uninstall (level 2) or core-decommission (level 1) (FK-10 §10.2.9)",
    )
    level = decommission_parser.add_mutually_exclusive_group(required=True)
    level.add_argument(
        "--machine", action="store_true", help="Level-2 machine-uninstall"
    )
    level.add_argument(
        "--core",
        action="store_true",
        help="Level-1 core-decommission (DESTRUCTIVE: requires --confirm + --export-dir)",
    )
    decommission_parser.add_argument(
        "--bundle-store-root", default=None, help="Bundle store root (machine-uninstall)"
    )
    decommission_parser.add_argument(
        "--bundle-version",
        default=None,
        help="Single bundle version to remove (machine-uninstall); default removes all.",
    )
    decommission_parser.add_argument(
        "--pinned-project",
        action="append",
        default=[],
        metavar="KEY=VERSION=ROOT",
        help="A project pinned to a bundle version (repeatable); used for orphaned warnings.",
    )
    decommission_parser.add_argument(
        "--confirm",
        action="store_true",
        help="Explicit confirmation for the destructive core-decommission.",
    )
    decommission_parser.add_argument(
        "--export-dir",
        default=None,
        help="Mandatory state-backend export destination (core-decommission).",
    )


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


def cmd_serve(args: argparse.Namespace) -> int:
    """Handle ``agentkit serve --ui-bff|--project-api`` (FK-10 §10.2.5)."""
    from agentkit.backend.cli.serve import ServeProfile, run_serve

    profile = ServeProfile.UI_BFF if args.ui_bff else ServeProfile.PROJECT_API
    return run_serve(
        profile=profile,
        host=args.host,
        port=args.port,
        certfile=Path(args.certfile),
        keyfile=Path(args.keyfile) if args.keyfile is not None else None,
    )


def cmd_serve_control_plane_alias(args: argparse.Namespace) -> int:
    """Handle the deprecated ``serve-control-plane`` compat alias (FK-10 §10.2.5).

    Delegates to the SINGLE serve implementation with the Project-API profile —
    no second transport path. The port default migrated from the legacy ``9080``
    to the Project-API ``9702`` (cert/key flags stay functionally compatible).
    """
    print(
        "agentkit serve-control-plane is deprecated; use 'agentkit serve "
        "--project-api' (the canonical level-1 Core bootstrap). Delegating to the "
        "same serve implementation.",
        file=sys.stderr,
    )
    from agentkit.backend.cli.serve import ServeProfile, run_serve

    return run_serve(
        profile=ServeProfile.PROJECT_API,
        host=args.host,
        port=args.port,
        certfile=Path(args.certfile),
        keyfile=Path(args.keyfile) if args.keyfile is not None else None,
    )


def cmd_ui(args: argparse.Namespace) -> int:
    """Handle ``agentkit ui`` (FK-10 §10.2.5)."""
    from agentkit.backend.cli.serve import run_ui

    return run_ui(
        host=args.host,
        port=args.port,
        dist_dir=Path(args.dist_dir) if args.dist_dir is not None else None,
    )


def cmd_update(args: argparse.Namespace) -> int:
    """Handle ``agentkit update`` (level 2, FK-10 §10.2.8)."""
    from agentkit import __version__
    from agentkit.backend.bootstrap.composition_root import build_compat_window_reader
    from agentkit.backend.installer.lifecycle.update import (
        UpdateCompatError,
        UpdateStatus,
        evaluate_update,
    )

    reader = build_compat_window_reader(
        args.base_url, skill_bundle_version=args.skill_bundle_version
    )
    try:
        compat_window = reader()
        decision = evaluate_update(__version__, compat_window)
    except UpdateCompatError as exc:
        print(f"update failed [CompatWindowInvalid]: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001
        # A transport/contract failure must fail closed (no silent PASS).
        print(f"update failed [CompatReadError]: {exc}", file=sys.stderr)
        return 1

    payload = {
        "status": decision.status.value,
        "local_version": decision.local_version,
        "min_version": decision.min_version,
        "recommended_version": decision.recommended_version,
        "blocked": list(decision.blocked),
        "reason": decision.reason,
        "reinstall_hint": decision.reinstall_hint,
    }
    stream = sys.stderr if decision.status is UpdateStatus.BLOCKED else sys.stdout
    print(json.dumps(payload, sort_keys=True), file=stream)
    return 0 if decision.is_pass else 1


def cmd_detach(args: argparse.Namespace) -> int:
    """Handle ``agentkit detach`` (level 3, FK-10 §10.2.9)."""
    from agentkit.backend.installer.lifecycle.detach import detach_project

    try:
        result = detach_project(Path(args.project_root))
    except FileNotFoundError as exc:
        print(f"detach failed [ProjectRootMissing]: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "project_root": str(result.project_root),
                "detached_junctions": list(result.detached_junctions),
                "removed_bindings": list(result.removed_bindings),
                "removed_ak3_hooks": list(result.removed_ak3_hooks),
                "preserved_foreign_hooks": list(result.preserved_foreign_hooks),
            },
            sort_keys=True,
        )
    )
    return 0 if result.success else 1


def cmd_decommission(args: argparse.Namespace) -> int:
    """Handle ``agentkit decommission --machine|--core`` (FK-10 §10.2.9)."""
    if args.machine:
        return _cmd_decommission_machine(args)
    return _cmd_decommission_core(args)


def _cmd_decommission_machine(args: argparse.Namespace) -> int:
    """Run the level-2 machine-uninstall branch."""
    from agentkit.backend.installer.lifecycle.decommission import (
        MachineDecommissionError,
        decommission_machine,
    )

    if args.bundle_store_root is None:
        print(
            "decommission --machine failed [MissingBundleStore]: --bundle-store-root "
            "is required for the level-2 machine-uninstall.",
            file=sys.stderr,
        )
        return 1
    pinned = _parse_pinned_projects(args.pinned_project)
    if pinned is None:
        return 1
    try:
        result = decommission_machine(
            bundle_store_root=Path(args.bundle_store_root),
            pinned_projects=pinned,
            bundle_version=args.bundle_version,
        )
    except MachineDecommissionError as exc:
        print(
            f"decommission --machine aborted [UnsafeBundleVersion]: {exc}",
            file=sys.stderr,
        )
        return 1
    if result.orphaned_projects:
        print(
            "decommission --machine WARNING [orphaned]: the following pinned "
            f"projects are orphaned by removing the bundle version(s): "
            f"{list(result.orphaned_projects)}",
            file=sys.stderr,
        )
    print(
        json.dumps(
            {
                "level": "machine",
                "removed_bundle_versions": list(result.removed_bundle_versions),
                "orphaned_projects": list(result.orphaned_projects),
                "operator_step": (
                    "Remove the shared 'agentkit' package + shims manually "
                    "(never self-uninstalled; would break a co-installed AK2)."
                ),
            },
            sort_keys=True,
        )
    )
    return 0 if result.success else 1


def _cmd_decommission_core(args: argparse.Namespace) -> int:
    """Run the level-1 core-decommission branch (destructive, fail-closed)."""
    from agentkit.backend.installer.lifecycle.decommission import (
        CoreDecommissionError,
        CoreDecommissionRequest,
        ServiceTeardownError,
        decommission_core,
    )

    request = CoreDecommissionRequest(
        confirm=bool(args.confirm),
        export_dir=Path(args.export_dir) if args.export_dir is not None else None,
    )
    try:
        result = decommission_core(
            request, service_controller=_OperatorServiceController()
        )
    except CoreDecommissionError as exc:
        print(f"decommission --core aborted [Precondition]: {exc}", file=sys.stderr)
        return 1
    except ServiceTeardownError as exc:
        print(f"decommission --core failed [Teardown]: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "level": "core",
                "exported_to": str(result.exported_to),
                "stopped_services": list(result.stopped_services),
                "db_volume_preserved": result.db_volume_preserved,
            },
            sort_keys=True,
        )
    )
    return 0 if result.success else 1


def _parse_pinned_projects(raw_values: list[str]) -> list[PinnedProject] | None:
    """Parse ``KEY=VERSION=ROOT`` pinned-project flags (fail-closed)."""
    from agentkit.backend.installer.lifecycle.decommission import PinnedProject

    pinned: list[PinnedProject] = []
    for raw in raw_values:
        parts = raw.split("=", 2)
        if len(parts) != 3 or not all(part.strip() for part in parts):
            print(
                f"decommission --machine failed [InvalidPinnedProject]: {raw!r} "
                "must use KEY=VERSION=ROOT syntax.",
                file=sys.stderr,
            )
            return None
        pinned.append(
            PinnedProject(
                project_key=parts[0].strip(),
                bundle_version=parts[1].strip(),
                project_root=parts[2].strip(),
            )
        )
    return pinned


class _OperatorServiceController:
    """Default core service controller: EXECUTES the approved teardown command.

    The canonical teardown command is ``docker compose down`` — explicitly
    WITHOUT ``-v``/``--volumes``, so the DB volume (the canonical state) survives
    a service uninstall (FK-10 §10.2.9). The ``-v``/``--volumes`` guard runs
    BEFORE execution. The default productive controller actually runs the command
    (``subprocess.run``); a teardown that cannot run (orchestrator unavailable) or
    that exits non-zero FAILS CLOSED with :class:`ServiceTeardownError` — services
    are never reported "stopped" when the teardown did not actually succeed (AC6,
    "kein Stub-Echo als 'done'").

    The ``runner`` is an injectable seam: tests provide a recording fake to assert
    the executed argv without a real Docker daemon; the productive default runs
    the real subprocess.

    Args:
        runner: Callable executing the teardown argv; defaults to
            ``subprocess.run``.
    """

    #: The safe teardown argv — never carries a volume-deleting flag.
    TEARDOWN_COMMAND = ("docker", "compose", "down")

    def __init__(
        self,
        runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
    ) -> None:
        self._runner: Callable[..., subprocess.CompletedProcess[str]] = (
            runner if runner is not None else subprocess.run
        )

    def stop_services(self) -> Sequence[str]:
        from agentkit.backend.installer.lifecycle.decommission import (
            ServiceTeardownError,
        )

        forbidden = {"-v", "--volumes"}
        if forbidden & set(self.TEARDOWN_COMMAND):
            msg = "teardown command must never delete the DB volume (down -v forbidden)"
            raise AssertionError(msg)
        argv = list(self.TEARDOWN_COMMAND)
        print(
            f"decommission --core: stopping backend/frontend services with "
            f"'{' '.join(argv)}' (NEVER 'down -v' — the DB volume is preserved).",
            file=sys.stderr,
        )
        try:
            completed = self._runner(
                argv, check=False, capture_output=True, text=True
            )
        except OSError as exc:
            msg = (
                f"core teardown command {argv!r} could not be executed "
                f"({exc}); services NOT stopped (fail-closed)."
            )
            raise ServiceTeardownError(msg) from exc
        if completed.returncode != 0:
            stderr = (completed.stderr or "").strip()
            msg = (
                f"core teardown command {argv!r} failed (exit "
                f"{completed.returncode}): {stderr}; services NOT stopped "
                "(fail-closed)."
            )
            raise ServiceTeardownError(msg)
        return ("backend", "frontend")


__all__ = [
    "add_lifecycle_parsers",
    "cmd_decommission",
    "cmd_detach",
    "cmd_serve",
    "cmd_serve_control_plane_alias",
    "cmd_ui",
    "cmd_update",
]
