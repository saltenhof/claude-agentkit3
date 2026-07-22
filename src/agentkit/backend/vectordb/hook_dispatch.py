"""Argv-safe concept hook dispatcher (AG3-176 R6).

Used by materialised pre-commit / post-commit hooks so ``concepts_dir`` is
never shell-interpolated. Invoked as::

    python -m agentkit.backend.vectordb.hook_dispatch pre-commit \\
        --project-root . --concepts-dir path/with spaces

    python -m agentkit.backend.vectordb.hook_dispatch post-commit \\
        --project-root . --concepts-dir path/with spaces
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    """CLI entry for hook dispatch."""
    parser = argparse.ArgumentParser(prog="agentkit-vectordb-hook-dispatch")
    parser.add_argument(
        "mode",
        choices=("pre-commit", "post-commit"),
        help="Hook ring to run.",
    )
    parser.add_argument("--project-root", required=True)
    parser.add_argument(
        "--concepts-dir",
        required=True,
        help="Configured concepts_dir (project-relative or absolute).",
    )
    args = parser.parse_args(argv)
    root = Path(args.project_root).resolve()
    concepts = Path(args.concepts_dir)
    if not concepts.is_absolute():
        concepts = (root / concepts).resolve()
    try:
        concepts.relative_to(root)
    except ValueError:
        print(
            f"concepts_dir {concepts} escapes project root {root} (fail-closed)",
            file=sys.stderr,
        )
        return 1

    if args.mode == "pre-commit":
        return _pre_commit(root, concepts)
    return _post_commit(root, concepts)


def _staged_paths(root: Path) -> list[str]:
    try:
        proc = subprocess.run(  # noqa: S603
            ["git", "-C", str(root), "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        print(f"git unavailable: {exc}", file=sys.stderr)
        return []
    if proc.returncode != 0:
        return []
    return [line.strip().replace("\\", "/") for line in proc.stdout.splitlines() if line.strip()]


def _commit_paths(root: Path) -> list[str]:
    try:
        proc = subprocess.run(  # noqa: S603
            ["git", "-C", str(root), "diff", "--name-only", "HEAD~1", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return []
    if proc.returncode != 0:
        return []
    return [line.strip().replace("\\", "/") for line in proc.stdout.splitlines() if line.strip()]


def _under_concepts(rel: str, concepts_rel: str) -> bool:
    prefix = concepts_rel.strip("/").replace("\\", "/")
    r = rel.replace("\\", "/")
    return r == prefix or r.startswith(prefix + "/")


def _pre_commit(root: Path, concepts: Path) -> int:
    concepts_rel = concepts.relative_to(root).as_posix()
    staged = _staged_paths(root)
    if not any(_under_concepts(p, concepts_rel) for p in staged):
        return 0
    print(f"[pre-commit] Concept changes under {concepts_rel}; validate --staged...")
    try:
        proc = subprocess.run(  # noqa: S603
            [
                sys.executable,
                "-m",
                "agentkit.backend.concept_catalog.cli",
                "--project-root",
                str(root),
                "validate",
                "--staged",
            ],
            cwd=str(root),
            check=False,
        )
    except OSError as exc:
        print(f"concept validate failed to start: {exc}", file=sys.stderr)
        return 1
    return int(proc.returncode)


def _post_commit(root: Path, concepts: Path) -> int:
    """Non-blocking: commit already landed; log errors, exit 0."""
    concepts_rel = concepts.relative_to(root).as_posix()
    changed = _commit_paths(root)
    if not any(_under_concepts(p, concepts_rel) for p in changed):
        return 0
    print("[post-commit] Concept changes; concept build BEFORE concept sync...")
    try:
        build = subprocess.run(  # noqa: S603
            [
                sys.executable,
                "-m",
                "agentkit.backend.concept_catalog.cli",
                "--project-root",
                str(root),
                "build",
            ],
            cwd=str(root),
            check=False,
        )
    except OSError as exc:
        print(f"[post-commit] concept build failed to start: {exc}", file=sys.stderr)
        return 0
    if build.returncode != 0:
        print(
            "[post-commit] concept build FAILED; leaving prior corpus_revision; "
            "no freshness advance",
            file=sys.stderr,
        )
        return 0
    try:
        sync = subprocess.run(  # noqa: S603
            [
                sys.executable,
                "-m",
                "agentkit.backend.concept_catalog.cli",
                "--project-root",
                str(root),
                "sync",
            ],
            cwd=str(root),
            check=False,
        )
    except OSError as exc:
        print(f"[post-commit] concept sync failed to start: {exc}", file=sys.stderr)
        return 0
    if sync.returncode != 0:
        print(
            "[post-commit] concept sync FAILED; leaving prior corpus_revision; "
            "no freshness advance",
            file=sys.stderr,
        )
        return 0
    print("[post-commit] concept build+sync OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
