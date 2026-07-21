"""Read-only concept-gate CLI (FK-78 section 78.14).

Subcommands: ``frontmatter | references | formal | decision-gate --base
<rev> [--trailer <slug>] | incubator <run-dir> | promotion <run-dir> |
projection | semantic-status <run-dir> | all [--base <rev>] [--trailer
<slug>] [--run <run-dir>]``. Global options: ``--project-root`` (default:
current directory) and ``--json`` (emit the FK-78 envelope instead of
human-readable output).

``all`` runs the corpus-wide checks including ``projection``; with
``--run`` it additionally runs ``incubator``, ``promotion`` and
``semantic-status`` for that run directory.

Exit codes: ``0`` PASS, ``1`` findings, ``2`` missing prerequisites or a
declared incomplete run (INCOMPLETE sub-checks such as an unavailable git
baseline are never a silent PASS), ``3`` usage or configuration errors.
This CLI performs no write operations.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, NoReturn

try:
    from .config import (
        GovernanceConfig,
        GovernanceConfigError,
        GovernanceConfigMissingError,
        load_governance_config,
    )
    from .decision_gate import run_decision_gate
    from .findings import (
        EXIT_INCOMPLETE,
        EXIT_USAGE,
        CheckResult,
        exit_code,
        to_envelope,
    )
    from .formal_check import run_formal_check
    from .frontmatter_check import run_frontmatter_check
    from .incubator_check import run_incubator_check
    from .projection_check import run_projection_check
    from .promotion_check import run_promotion_check
    from .reference_check import run_reference_check
    from .runmodel import load_projection_manifest
    from .semantic_status import run_semantic_status
except ImportError:  # pragma: no cover - direct script execution path
    # Executed as a plain script (``python tools/agentkit/concept_toolchain/check.py``):
    # relative imports have no parent package, so re-run this module under its
    # canonical package name and delegate the whole invocation to it.
    import importlib

    _package_parent = str(Path(__file__).resolve().parent.parent)
    if _package_parent not in sys.path:
        sys.path.insert(0, _package_parent)
    _cli = importlib.import_module("concept_toolchain.check")
    if __name__ == "__main__":
        raise SystemExit(_cli.main()) from None
    raise

if TYPE_CHECKING:
    from collections.abc import Sequence


class _UsageErrorParser(argparse.ArgumentParser):
    """Argument parser that exits with the FK-78 usage exit code (3)."""

    def error(self, message: str) -> NoReturn:
        self.print_usage(sys.stderr)
        print(f"{self.prog}: error: {message}", file=sys.stderr)
        raise SystemExit(EXIT_USAGE)


def build_parser() -> argparse.ArgumentParser:
    """Build the read-only concept-gate argument parser."""
    parser = _UsageErrorParser(
        prog="python tools/agentkit/concept_toolchain/check.py",
        description="Read-only deterministic concept gates (FK-78).",
    )
    parser.add_argument("--project-root", default=".", help="Target-project root (default: current directory).")
    parser.add_argument("--json", action="store_true", help="Emit the FK-78 JSON envelope instead of human-readable output.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("frontmatter", help="Frontmatter/authority contract.")
    subparsers.add_parser("references", help="Reference integrity with baseline support.")
    subparsers.add_parser("formal", help="Formal-spec structural compile.")
    decision = subparsers.add_parser("decision-gate", help="W4 decision-record gate.")
    decision.add_argument("--base", required=True, help="Git base revision to diff against.")
    decision.add_argument("--trailer", action="append", default=[], help="Concept-Decision slug for uncommitted work.")
    incubator = subparsers.add_parser("incubator", help="Incubation-run layout, schema and lifecycle validation.")
    incubator.add_argument("run_dir", help="Incubation run directory.")
    promotion = subparsers.add_parser("promotion", help="Promotion-closure rules 1-7.")
    promotion.add_argument("run_dir", help="Incubation run directory.")
    subparsers.add_parser("projection", help="Corpus-wide projection-manifest validation.")
    semantic = subparsers.add_parser("semantic-status", help="Semantic-gate request/receipt accounting.")
    semantic.add_argument("run_dir", help="Incubation run directory.")
    run_all = subparsers.add_parser("all", help="All corpus-wide checks (decision-gate only when --base is given).")
    run_all.add_argument("--base", help="Git base revision; enables the decision-gate check.")
    run_all.add_argument("--trailer", action="append", default=[], help="Concept-Decision slug for uncommitted work.")
    run_all.add_argument("--run", help="Run directory; enables incubator, promotion and semantic-status.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the requested read-only checks and return the FK-78 exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    project_root = Path(args.project_root).resolve()
    if not project_root.is_dir():
        print(f"[config] INCOMPLETE: project root does not exist: {project_root}", file=sys.stderr)
        _emit_empty_envelope(args, str(args.command))
        return EXIT_INCOMPLETE
    try:
        config = load_governance_config(project_root)
    except GovernanceConfigMissingError as exc:
        print(f"[config] INCOMPLETE: {exc}", file=sys.stderr)
        _emit_empty_envelope(args, str(args.command))
        return EXIT_INCOMPLETE
    except GovernanceConfigError as exc:
        print(f"[config] ERROR: {exc}", file=sys.stderr)
        return EXIT_USAGE
    results = _run_checks(args, project_root, config)
    check_set = [result.check_id for result in results]
    if args.json:
        print(json.dumps(to_envelope(str(args.command), check_set, results), indent=2, sort_keys=True))
    else:
        _print_human(results)
    return exit_code(results)


def _resolve_run_dir(project_root: Path, argument: str) -> Path:
    run_dir = Path(argument)
    return run_dir if run_dir.is_absolute() else project_root / run_dir


def _run_checks(args: argparse.Namespace, project_root: Path, config: GovernanceConfig) -> list[CheckResult]:
    command = str(args.command)
    if command == "frontmatter":
        return [run_frontmatter_check(project_root, config)]
    if command == "references":
        return [run_reference_check(project_root, config)]
    if command == "formal":
        return [run_formal_check(project_root, config)]
    if command == "decision-gate":
        return [run_decision_gate(project_root, config, str(args.base), list(args.trailer))]
    if command == "incubator":
        return [run_incubator_check(project_root, config, _resolve_run_dir(project_root, str(args.run_dir)))]
    if command == "promotion":
        return [run_promotion_check(project_root, config, _resolve_run_dir(project_root, str(args.run_dir)))]
    if command == "projection":
        return [run_projection_check(project_root, config)]
    if command == "semantic-status":
        return [run_semantic_status(project_root, config, _resolve_run_dir(project_root, str(args.run_dir)))]
    results = [
        run_frontmatter_check(project_root, config),
        run_reference_check(project_root, config),
        run_formal_check(project_root, config),
    ]
    if args.base is not None:
        results.append(run_decision_gate(project_root, config, str(args.base), list(args.trailer)))
    results.append(run_projection_check(project_root, config))
    explicit = str(args.run) if args.run is not None else None
    for run_id in _referenced_run_ids(project_root, config):
        run_dir = project_root / config.incubator_root / "runs" / run_id
        if explicit is not None and _resolve_run_dir(project_root, explicit) == run_dir:
            continue
        results.append(run_promotion_check(project_root, config, run_dir))
    if explicit is not None:
        run_dir = _resolve_run_dir(project_root, explicit)
        results.append(run_incubator_check(project_root, config, run_dir))
        results.append(run_promotion_check(project_root, config, run_dir))
        results.append(run_semantic_status(project_root, config, run_dir))
    return results


def _referenced_run_ids(project_root: Path, config: GovernanceConfig) -> list[str]:
    """Return the run ids that projection-manifest entries activate from.

    ``all`` re-runs the promotion closure for each of them, so an entry
    can never rely on a run that never passed ``check.py promotion``.
    """
    manifest_path = project_root / config.concept_roots["meta"] / "projection-manifest.json"
    if not manifest_path.is_file():
        return []
    manifest, _ = load_projection_manifest(manifest_path)
    if manifest is None:
        return []
    seen: list[str] = []
    for entry in manifest.entries:
        if entry.last_run_id is not None and entry.last_run_id not in seen:
            seen.append(entry.last_run_id)
    return seen


def _print_human(results: Sequence[CheckResult]) -> None:
    for result in results:
        for finding in sorted(result.findings, key=lambda item: (item.path, item.locator, item.check_id, item.message)):
            print(f"[ERROR] {finding.check_id} {finding.path}:{finding.locator} - {finding.message}")
        for report in result.reports:
            print(report)
        if not result.complete:
            print(f"[{result.check_id}] INCOMPLETE: {result.incomplete_reason}")
        elif result.findings:
            print(f"[{result.check_id}] FAILED: {len(result.findings)} error(s)")
        else:
            suffix = f": {result.summary}" if result.summary else ""
            print(f"[{result.check_id}] OK{suffix}")


def _emit_empty_envelope(args: argparse.Namespace, command: str) -> None:
    if args.json:
        print(json.dumps(to_envelope(command, [], []) | {"complete": False}, indent=2, sort_keys=True))


if __name__ == "__main__":
    raise SystemExit(main())
