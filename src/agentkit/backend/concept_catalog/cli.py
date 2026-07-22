"""Three-ring concept CLI (FK-13 §13.9.9, AG3-174 R03/R13).

Productive operations use the real Weaviate adapter from project config /
runtime binding. No in-process memory default (R03).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from agentkit.backend.concept_catalog.corpus.discovery import discover_concept_files
from agentkit.backend.concept_catalog.corpus.domain_errors import ConceptParseError
from agentkit.backend.vectordb.concept_corpus.build import build_corpus_artifacts
from agentkit.backend.vectordb.concept_corpus.validate import validate_corpus
from agentkit.backend.vectordb.project_binding import ProjectBindingError, bind_project

if TYPE_CHECKING:
    from collections.abc import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint for ``agentkit-concept``."""
    parser = argparse.ArgumentParser(prog="agentkit-concept")
    parser.add_argument("--project-root", default=".", help="Project root.")
    parser.add_argument("--concepts-dir", default=None, help="Override concepts_dir.")
    sub = parser.add_subparsers(dest="command", required=True)

    lint = sub.add_parser("lint", help="Ring 1 authoring guard (soft).")
    lint.add_argument("--changed", action="store_true")
    lint.add_argument("files", nargs="*")

    doctor = sub.add_parser("doctor", help="Corpus diff summary.")
    doctor.add_argument("--summary", action="store_true")

    validate = sub.add_parser("validate", help="Ring 2/3 validation.")
    validate.add_argument("--staged", action="store_true")
    validate.add_argument("--corpus", action="store_true")
    validate.add_argument("--strict", action="store_true")

    sub.add_parser("build", help="Build INDEX.yaml and concept_graph.json.")
    sync = sub.add_parser("sync", help="Manual concept VectorDB sync.")
    sync.add_argument("--full-reindex", action="store_true")

    args = parser.parse_args(list(argv) if argv is not None else None)
    root = Path(args.project_root).resolve()
    try:
        binding = bind_project(root, concepts_dir=args.concepts_dir)
    except ProjectBindingError as exc:
        print(str(exc), file=sys.stderr)
        return 3

    if args.command == "lint":
        return _cmd_lint(binding.concepts_dir, changed=args.changed, files=args.files)
    if args.command == "doctor":
        return _cmd_doctor(binding.concepts_dir)
    if args.command == "validate":
        return _cmd_validate(
            binding.concepts_dir,
            staged=args.staged,
            corpus=args.corpus,
            strict=args.strict,
            project_root=root,
        )
    if args.command == "build":
        return _cmd_build(binding.concepts_dir)
    if args.command == "sync":
        return _cmd_sync(binding, full_reindex=args.full_reindex)
    parser.error(f"unknown command: {args.command}")
    return 2


def _cmd_lint(concepts_dir: Path, *, changed: bool, files: list[str]) -> int:
    targets: list[Path] = []
    if files:
        targets = [Path(f) for f in files]
    elif changed:
        targets = _git_changed_concept_files(concepts_dir)
    else:
        try:
            result = discover_concept_files(concepts_dir, strict=False)
        except FileNotFoundError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        print(json.dumps({"documents": len(result.documents), "excluded": list(result.excluded)}))
        return 0

    findings: list[dict[str, str]] = []
    for path in targets:
        try:
            data = path.read_bytes()
            from agentkit.backend.concept_catalog.corpus.frontmatter import (
                parse_frontmatter_yaml,
                split_frontmatter_bytes,
                validate_concept_frontmatter,
            )

            yb, _ = split_frontmatter_bytes(data, path=str(path))
            raw = parse_frontmatter_yaml(yb, path=str(path))
            validate_concept_frontmatter(raw, path=str(path))
        except (ConceptParseError, OSError, UnicodeError) as exc:
            findings.append({"path": str(path), "message": str(exc)})
    print(json.dumps({"findings": findings, "ok": not findings}, indent=2))
    return 0


def _cmd_doctor(concepts_dir: Path) -> int:
    result = validate_corpus(concepts_dir)
    summary = {
        "concept_count": result.graph.get("concept_count", 0),
        "active_count": result.graph.get("active_count", 0),
        "errors": len(result.errors),
        "warnings": len(result.warnings),
        "corpus_revision": result.corpus_revision,
        "error_codes": sorted({e.code for e in result.errors}),
        "warning_codes": sorted({w.code for w in result.warnings}),
    }
    print(json.dumps(summary, indent=2))
    return 0


def _cmd_validate(
    concepts_dir: Path,
    *,
    staged: bool,
    corpus: bool,
    strict: bool,
    project_root: Path,
) -> int:
    overlays: dict[str, bytes] | None = None
    if staged:
        try:
            overlays = _staged_candidate_overlays(project_root, concepts_dir)
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 3  # internal failure (R13)
    result = validate_corpus(
        concepts_dir,
        strict=strict or (corpus and strict),
        candidate_overlays=overlays,
        use_head_for_unmodified=staged,
        project_root=project_root if staged else None,
    )
    print(json.dumps(result.as_dict(), indent=2))
    return result.exit_code


def _cmd_build(concepts_dir: Path) -> int:
    try:
        artifacts = build_corpus_artifacts(concepts_dir, persist=True)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "corpus_revision": artifacts.corpus_revision,
                "index_path": str(artifacts.index_path),
                "graph_path": str(artifacts.graph_path),
            },
            indent=2,
        )
    )
    return 0


def _cmd_sync(binding: object, *, full_reindex: bool) -> int:
    # Sync orchestration lives in the VectorDB BC (may import integrations).
    # ConceptCatalog CLI only delegates — no Integrations import here (AC010).
    from agentkit.backend.vectordb.cli_sync import run_concept_sync_cli

    return run_concept_sync_cli(binding, full_reindex=full_reindex)


def _git_changed_concept_files(concepts_dir: Path) -> list[Path]:
    try:
        proc = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
            cwd=str(concepts_dir.parent),
        )
    except OSError:
        return []
    out: list[Path] = []
    for line in proc.stdout.splitlines():
        path = (concepts_dir.parent / line.strip()).resolve()
        try:
            path.relative_to(concepts_dir.resolve())
        except ValueError:
            continue
        if path.suffix == ".md" and path.is_file():
            out.append(path)
    return out


def _staged_candidate_overlays(  # noqa: C901
    project_root: Path, concepts_dir: Path
) -> dict[str, bytes]:
    """Build candidate overlays from Git index only (R13).

    * staged ACMR files → index blob (including empty blobs)
    * staged deletes → omit from candidate (not in overlays; discovery must
      also exclude paths deleted in the index)
    * unmodified concept files → HEAD content (not working tree)
    * ``.conceptignore`` from index/HEAD only — never working tree (R13)

    Any git failure raises RuntimeError → CLI exit 3.
    """
    from agentkit.backend.concept_catalog.corpus.discovery import IGNORE_OVERLAY_KEY

    try:
        name_status = subprocess.run(
            ["git", "diff", "--cached", "--name-status", "--diff-filter=ACDMR"],
            check=False,
            capture_output=True,
            text=True,
            cwd=str(project_root),
        )
    except OSError as exc:
        raise RuntimeError(f"git failed: {exc}") from exc
    if name_status.returncode != 0:
        raise RuntimeError(
            f"git diff --cached failed (exit {name_status.returncode}): "
            f"{name_status.stderr}"
        )

    root = concepts_dir.resolve()
    overlays: dict[str, bytes] = {}
    deleted: set[str] = set()
    for line in name_status.stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        status = parts[0]
        if status.startswith("R") or status.startswith("C"):
            if len(parts) < 3:
                continue
            rel_repo = parts[2].strip().replace("\\", "/")
            old_repo = parts[1].strip().replace("\\", "/")
            _maybe_delete(deleted, root, project_root, old_repo)
        elif status.startswith("D"):
            if len(parts) < 2:
                continue
            _maybe_delete(deleted, root, project_root, parts[1].strip().replace("\\", "/"))
            continue
        else:
            if len(parts) < 2:
                continue
            rel_repo = parts[1].strip().replace("\\", "/")
        _stage_repo_blob(overlays, project_root, root, rel_repo)

    if IGNORE_OVERLAY_KEY not in overlays:
        overlays[IGNORE_OVERLAY_KEY] = _head_or_empty_ignore(project_root, root)

    for rel in deleted:
        overlays[f"__deleted__:{rel}"] = b""
    return overlays


def _stage_repo_blob(
    overlays: dict[str, bytes],
    project_root: Path,
    concepts_root: Path,
    rel_repo: str,
) -> None:
    from agentkit.backend.concept_catalog.corpus.discovery import IGNORE_OVERLAY_KEY

    abs_path = (project_root / rel_repo).resolve()
    try:
        rel_concept = abs_path.relative_to(concepts_root).as_posix()
    except ValueError:
        return
    is_ignore = rel_concept == ".conceptignore" or rel_repo.endswith("/.conceptignore")
    if not (rel_repo.endswith(".md") or is_ignore):
        return
    show = subprocess.run(
        ["git", "show", f":{rel_repo}"],
        check=False,
        capture_output=True,
        cwd=str(project_root),
    )
    if show.returncode != 0:
        raise RuntimeError(
            f"git show :{rel_repo} failed (exit {show.returncode}); "
            "cannot build staged candidate (R13)."
        )
    if is_ignore:
        overlays[IGNORE_OVERLAY_KEY] = show.stdout
    else:
        overlays[rel_concept] = show.stdout


def _head_or_empty_ignore(project_root: Path, concepts_root: Path) -> bytes:
    ignore_repo = (
        concepts_root.relative_to(project_root.resolve()) / ".conceptignore"
    ).as_posix()
    head_ignore = subprocess.run(
        ["git", "show", f"HEAD:{ignore_repo}"],
        check=False,
        capture_output=True,
        cwd=str(project_root),
    )
    if head_ignore.returncode == 0:
        return head_ignore.stdout
    return b""


def _maybe_delete(
    deleted: set[str], root: Path, project_root: Path, rel_repo: str
) -> None:
    abs_path = (project_root / rel_repo).resolve()
    try:
        rel_concept = abs_path.relative_to(root).as_posix()
    except ValueError:
        return
    deleted.add(rel_concept)


if __name__ == "__main__":
    raise SystemExit(main())
