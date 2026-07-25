"""Three-rings CLI on the same SSOT discovery core (FK-13 §13.9.9, AC12).

Ring 1 (authoring): ``concept lint --changed`` / ``concept lint <file>``,
``concept doctor`` (corpus-diff diagnostics).
Ring 2 (commit gate): ``concept validate --staged`` (candidate corpus =
staged + unchanged), ``concept validate --corpus --strict``.
Ring 3 (build): ``concept build``, productive ``concept sync``.

All operations call :func:`agentkit.concepts.parser.discover_concept_files` --
the single discovery source. The FIRING pre/post-commit installation is AG3-176
(out of scope); here only the productive operations. ``validate --staged`` is
FAIL-CLOSED: any git/read fault maps to exit 3 (R08). ``concept sync`` composes
the productive engine and writes for real (R07).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from agentkit.backend.vectordb.concept_corpus.builder import build_artifacts, write_artifacts
from agentkit.backend.vectordb.concept_corpus.candidate import build_candidate_corpus
from agentkit.backend.vectordb.concept_corpus.validator import ExitCode, validate_corpus
from agentkit.backend.vectordb.mcp_server import McpToolService
from agentkit.concepts.parser import discover_concept_files

if TYPE_CHECKING:
    from collections.abc import Sequence


class GitOperationError(RuntimeError):
    """A git operation failed unexpectedly -> maps to exit 3 (R08)."""


def _repo_root(start: Path) -> Path:
    """Resolve the git repo root from ``start`` (fail-closed, R08)."""
    try:
        out = subprocess.run(  # noqa: S603
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(start),
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        raise GitOperationError(f"could not resolve git repo root from {start}: {exc}") from exc
    return Path(out.stdout.strip())


def _staged_concept_overlays(repo_root: Path, concepts_dir: Path) -> dict[str, str]:
    """Return staged concept files as ``{rel_posix: content}`` via name-status.

    Consumes ``git diff --cached --name-status`` (incl. deletions ``D``). A
    deletion maps to an EMPTY overlay (the file is removed from the candidate).
    Any git/read fault raises :class:`GitOperationError` (exit 3, R08) -- never a
    silent skip.
    """
    try:
        out = subprocess.run(  # noqa: S603
            ["git", "diff", "--cached", "--name-status"],
            cwd=str(repo_root),
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        raise GitOperationError(f"git diff --cached failed: {exc}") from exc
    overlays: dict[str, str] = {}
    concept_root_rel = concepts_dir.resolve().relative_to(repo_root.resolve()).as_posix()
    for line in out.stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        status = parts[0].strip()
        path = (parts[-1] if len(parts) > 1 else "").strip().replace("\\", "/")
        if not path.endswith(".md"):
            continue
        # Only concept-corpus files are staged-overlay candidates.
        if not path.startswith(concept_root_rel):
            continue
        if status.startswith("D"):
            overlays[path] = ""  # staged deletion -> remove from candidate
            continue
        try:
            content = subprocess.run(  # noqa: S603
                ["git", "show", f":{path}"],
                cwd=str(repo_root),
                check=True,
                capture_output=True,
                text=True,
            ).stdout
        except (FileNotFoundError, subprocess.CalledProcessError) as exc:
            raise GitOperationError(f"git show :{path} failed: {exc}") from exc
        overlays[path] = content
    # Re-key overlays relative to the concept root (candidate is concept-rooted).
    rel_overlays: dict[str, str] = {}
    for path, content in overlays.items():
        rel = path.removeprefix(concept_root_rel).lstrip("/")
        rel_overlays[rel] = content
    return rel_overlays


def _changed_concept_files(repo_root: Path, concepts_dir: Path) -> list[str]:
    """Return concept files changed vs HEAD (for ``lint --changed``, R07)."""
    try:
        out = subprocess.run(  # noqa: S603
            ["git", "diff", "--name-only", "HEAD"],
            cwd=str(repo_root),
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        raise GitOperationError(f"git diff --name-only HEAD failed: {exc}") from exc
    concept_root_rel = concepts_dir.resolve().relative_to(repo_root.resolve()).as_posix()
    return [
        p.replace("\\", "/")
        for p in out.stdout.splitlines()
        if p.strip().endswith(".md") and p.strip().startswith(concept_root_rel)
    ]


def cmd_lint(args: argparse.Namespace) -> int:
    """Ring 1: lint changed files (``--changed``) or a single file (soft)."""
    concepts_dir = Path(args.concepts_dir)
    discovery = discover_concept_files(concepts_dir)
    findings = list(discovery.errors)
    target_files: set[str] = set()
    if getattr(args, "changed", False):
        try:
            repo_root = _repo_root(concepts_dir if concepts_dir.is_dir() else Path.cwd())
            target_files = set(_changed_concept_files(repo_root, concepts_dir))
            target_files = {f.rsplit("/", 1)[-1] for f in target_files}
        except GitOperationError as exc:
            print(json.dumps({"status": "lint", "error": str(exc)}))
            return int(ExitCode.INTERNAL_FAILURE)
    elif getattr(args, "file", None):
        target_files = {str(args.file).replace("\\", "/").rsplit("/", 1)[-1]}
    if target_files:
        findings = [f for f in findings if f.path.rsplit("/", 1)[-1] in target_files]
    payload = {"status": "lint", "findings": len(findings), "errors": [f.path for f in findings]}
    print(json.dumps(payload, indent=2))
    return 0  # lint is always non-blocking


def cmd_doctor(args: argparse.Namespace) -> int:
    """Ring 1: corpus-diff diagnostics (broken refs, orphans, unowned scopes)."""
    concepts_dir = Path(args.concepts_dir)
    discovery = discover_concept_files(concepts_dir)
    report = validate_corpus(discovery)
    diagnostics = {
        "parse_errors": [e.path for e in discovery.errors],
        "broken_defers_to": [f.message for f in report.errors if f.code == "E-REF-001"],
        "orphan_concepts": [f.concept_id for f in report.warnings if f.code == "W-ORPHAN-001"],
        "scopes_without_active_owner": [f.message for f in report.warnings if f.code == "W-SCOPE-001"],
        "authority_conflicts": [f.message for f in report.errors if f.code == "E-AUTH-001"],
    }
    payload = {
        "status": "doctor",
        "documents": len(discovery.documents),
        "chunks": len(discovery.chunks),
        "corpus_revision": discovery.corpus_revision,
        "diagnostics": diagnostics,
    }
    print(json.dumps(payload, indent=2))
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    """Ring 2: validate the candidate (``--staged``) or the working corpus."""
    concepts_dir = Path(args.concepts_dir)
    if getattr(args, "staged", False):
        # R08: EVERY unexpected failure in the staged path (git op, candidate
        # copy, relative-path resolution, decode, discovery/read) maps to exit 3
        # (INTERNAL_FAILURE) -- never a silent green exit. Triggered by real
        # faults, not a normalised exception.
        try:
            repo_root = _repo_root(concepts_dir if concepts_dir.is_dir() else Path.cwd())
            overlays = _staged_concept_overlays(repo_root, concepts_dir)
            import tempfile  # noqa: PLC0415

            with tempfile.TemporaryDirectory() as tmp:
                candidate = build_candidate_corpus(concepts_dir, overlays, dest=Path(tmp))
                discovery = discover_concept_files(candidate)
                report = validate_corpus(discovery, strict=getattr(args, "strict", False))
        except GitOperationError as exc:
            print(json.dumps({"status": "validate-staged-failed", "error": str(exc)}, indent=2))
            return int(ExitCode.INTERNAL_FAILURE)
        except Exception as exc:  # noqa: BLE001 -- any unexpected fault -> exit 3
            print(
                json.dumps(
                    {"status": "validate-staged-internal-failure", "error": f"{type(exc).__name__}: {exc}"},
                    indent=2,
                )
            )
            return int(ExitCode.INTERNAL_FAILURE)
    else:
        discovery = discover_concept_files(concepts_dir)
        report = validate_corpus(discovery, strict=getattr(args, "strict", False))
    print(json.dumps(report.as_dict(), indent=2, default=str))
    return int(report.exit_code)


def cmd_build(args: argparse.Namespace) -> int:
    """Ring 3: build INDEX.yaml + concept_graph.json (only if valid)."""
    concepts_dir = Path(args.concepts_dir)
    discovery = discover_concept_files(concepts_dir)
    report = validate_corpus(discovery)
    if report.has_errors:
        print(json.dumps({"status": "build-blocked", "errors": len(report.errors)}, indent=2))
        return int(ExitCode.ERRORS)
    artifacts = build_artifacts(discovery)
    out_dir = Path(args.out_dir) if getattr(args, "out_dir", None) else concepts_dir / "_build"
    index_path, graph_path = write_artifacts(artifacts, out_dir)
    print(
        json.dumps(
            {"status": "built", "corpus_revision": artifacts.corpus_revision,
             "index": str(index_path), "graph": str(graph_path)},
            indent=2,
        )
    )
    return 0


def _default_service_factory(concepts_dir: Path) -> McpToolService:
    """Compose the productive engine from the env (R07). Fails closed on outage."""
    import os  # noqa: PLC0415

    from agentkit.backend.vectordb.engine import compose_runtime  # noqa: PLC0415

    env = dict(os.environ)
    stories_dir = Path(env.get("AGENTKIT_STORIES_DIR", "stories")).resolve()
    service = compose_runtime(env, concepts_dir=concepts_dir.resolve(), stories_dir=stories_dir, cwd=os.getcwd())
    assert isinstance(service, McpToolService)
    return service


def cmd_sync(args: argparse.Namespace) -> int:
    """Ring 3: productive concept sync via the composed engine (R07).

    Composes the real SyncService/adapter from the env and WRITES. A connection
    or validation fault fails closed (non-zero), never reports success at zero
    written chunks. ``--service-factory`` is an injectable seam for tests.
    """
    concepts_dir = Path(args.concepts_dir)
    factory = getattr(args, "service_factory", None) or _default_service_factory
    from agentkit.backend.vectordb.mcp_server import handle_tool_call  # noqa: PLC0415

    try:
        service: McpToolService = factory(concepts_dir)
    except Exception as exc:  # noqa: BLE001 -- connection/binding fault -> fail closed
        print(json.dumps({"status": "sync-failed", "error": str(exc)}, indent=2))
        return int(ExitCode.INTERNAL_FAILURE)
    result = handle_tool_call(service, "concept_sync", {"full_reindex": bool(getattr(args, "full", False))})
    if result.get("error"):
        print(json.dumps({"status": "sync-blocked", **result}, indent=2))
        return int(ExitCode.ERRORS)
    print(json.dumps({"status": "synced", **result}, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(prog="concept", description="FK-13 concept corpus operations")
    # N20: NO default. The concept corpus root is project configuration
    # (``ProjectConfig.concepts_dir``); defaulting to the literal ``concept``
    # silently pointed every operation at AK3's OWN development corpus, which is
    # not an FK-13 target-project corpus. Fail closed instead of guessing.
    parser.add_argument(
        "--concepts-dir",
        required=True,
        help="Concept corpus root of the TARGET project (no default, fail-closed).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    lint = sub.add_parser("lint", help="Ring 1: lint (soft)")
    lint.add_argument("--changed", action="store_true")
    lint.add_argument("file", nargs="?")
    lint.set_defaults(func=cmd_lint)

    doctor = sub.add_parser("doctor", help="Ring 1: corpus diagnostics")
    doctor.add_argument("--summary", action="store_true")
    doctor.set_defaults(func=cmd_doctor)

    validate = sub.add_parser("validate", help="Ring 2: validate")
    validate.add_argument("--staged", action="store_true")
    validate.add_argument("--corpus", action="store_true")
    validate.add_argument("--strict", action="store_true")
    validate.set_defaults(func=cmd_validate)

    build = sub.add_parser("build", help="Ring 3: build artifacts")
    build.add_argument("--out-dir", default=None)
    build.set_defaults(func=cmd_build)

    sync = sub.add_parser("sync", help="Ring 3: productive concept sync")
    sync.add_argument("--full", action="store_true")
    sync.set_defaults(func=cmd_sync)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for the ``concept`` CLI."""
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())


__all__ = ["GitOperationError", "build_parser", "main"]
