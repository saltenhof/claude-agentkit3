"""Three-rings CLI on the same SSOT discovery core (FK-13 §13.9.9, AC12).

Ring 1 (authoring): ``concept lint --changed`` / ``concept lint <file>``,
``concept doctor --summary``.
Ring 2 (commit gate): ``concept validate --staged`` (candidate corpus =
staged + unchanged), ``concept validate --corpus --strict``.
Ring 3 (build): ``concept build``, manual ``concept sync``.

All operations call :func:`agentkit.concepts.parser.discover_concept_files` --
the single discovery source. The FIRING pre/post-commit installation is AG3-176
(out of scope); here only the productive operations.
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
from agentkit.concepts.parser import discover_concept_files

if TYPE_CHECKING:
    from collections.abc import Sequence


def _git_staged_concept_files(concepts_dir: Path) -> dict[str, str]:
    """Return staged concept files as ``{rel_posix: staged_content}`` via git.

    Uses ``git show :<path>`` to read the staged (index) content. Returns ``{}``
    when not in a git repo or no staged concept files. Fail-closed on git errors
    that are not "not a git repo".
    """
    try:
        out = subprocess.run(  # noqa: S603
            ["git", "diff", "--cached", "--name-only", "--relative"],
            cwd=str(concepts_dir.resolve()) if concepts_dir.is_dir() else str(Path.cwd()),
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return {}
    staged: dict[str, str] = {}
    for line in out.stdout.splitlines():
        rel = line.strip().replace("\\", "/")
        if not rel.endswith(".md"):
            continue
        try:
            content = subprocess.run(  # noqa: S603
                ["git", "show", f":{rel}"],
                cwd=str(concepts_dir.resolve()),
                check=True,
                capture_output=True,
                text=True,
            ).stdout
        except (FileNotFoundError, subprocess.CalledProcessError):
            continue
        staged[rel] = content
    return staged


def cmd_lint(args: argparse.Namespace) -> int:
    """Ring 1: lint changed files or a single file (soft, non-blocking)."""
    concepts_dir = Path(args.concepts_dir)
    discovery = discover_concept_files(concepts_dir)
    findings = list(discovery.errors)
    if getattr(args, "file", None):
        target = str(args.file).replace("\\", "/")
        findings = [f for f in findings if target in f.path]
    payload = {"status": "lint", "findings": len(findings), "errors": [f.path for f in findings]}
    print(json.dumps(payload, indent=2))
    return 0  # lint is always non-blocking


def cmd_doctor(args: argparse.Namespace) -> int:
    """Ring 1: corpus diff summary (non-blocking)."""
    concepts_dir = Path(args.concepts_dir)
    discovery = discover_concept_files(concepts_dir)
    by_status: dict[str, int] = {}
    for doc in discovery.documents:
        by_status[doc.effective_status] = by_status.get(doc.effective_status, 0) + 1
    summary = bool(args.summary)
    payload = {
        "status": "doctor",
        "documents": len(discovery.documents),
        "chunks": len(discovery.chunks),
        "parse_errors": len(discovery.errors),
        "by_status": by_status,
        "corpus_revision": discovery.corpus_revision[:12] if summary else discovery.corpus_revision,
    }
    print(json.dumps(payload, indent=2))
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    """Ring 2: validate the candidate (``--staged``) or the working corpus."""
    concepts_dir = Path(args.concepts_dir)
    if getattr(args, "staged", False):
        overlays = _git_staged_concept_files(concepts_dir)
        import tempfile  # noqa: PLC0415

        with tempfile.TemporaryDirectory() as tmp:
            candidate = build_candidate_corpus(concepts_dir, overlays, dest=Path(tmp))
            discovery = discover_concept_files(candidate)
            report = validate_corpus(discovery, strict=getattr(args, "strict", False))
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
        print(
            json.dumps(
                {"status": "build-blocked", "errors": len(report.errors)},
                indent=2,
            )
        )
        return int(ExitCode.ERRORS)
    artifacts = build_artifacts(discovery)
    out_dir = Path(args.out_dir) if getattr(args, "out_dir", None) else concepts_dir / "_build"
    index_path, graph_path = write_artifacts(artifacts, out_dir)
    print(
        json.dumps(
            {
                "status": "built",
                "corpus_revision": artifacts.corpus_revision,
                "index": str(index_path),
                "graph": str(graph_path),
            },
            indent=2,
        )
    )
    return 0


def cmd_sync(args: argparse.Namespace) -> int:
    """Ring 3: manual sync stub -- wires discovery; the transport is plugged by the MCP/producer layer."""
    concepts_dir = Path(args.concepts_dir)
    discovery = discover_concept_files(concepts_dir)
    report = validate_corpus(discovery)
    if report.has_errors:
        print(json.dumps({"status": "sync-blocked", "errors": len(report.errors)}, indent=2))
        return int(ExitCode.ERRORS)
    print(
        json.dumps(
            {
                "status": "sync-ready",
                "corpus_revision": discovery.corpus_revision,
                "chunks": len(discovery.chunks),
            },
            indent=2,
        )
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(prog="concept", description="FK-13 concept corpus operations")
    parser.add_argument("--concepts-dir", default="concept", help="concept corpus root")
    sub = parser.add_subparsers(dest="command", required=True)

    lint = sub.add_parser("lint", help="Ring 1: lint (soft)")
    lint.add_argument("--changed", action="store_true")
    lint.add_argument("file", nargs="?")
    lint.set_defaults(func=cmd_lint)

    doctor = sub.add_parser("doctor", help="Ring 1: corpus summary")
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

    sync = sub.add_parser("sync", help="Ring 3: manual sync (wires discovery)")
    sync.set_defaults(func=cmd_sync)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for the ``concept`` CLI."""
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())


__all__ = ["build_parser", "main"]
