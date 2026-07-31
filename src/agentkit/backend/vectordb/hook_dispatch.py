"""Git-hook dispatcher for mandatory concept validation/build/sync."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from agentkit.backend.config.loader import load_project_config
from agentkit.backend.exceptions import ConfigError


def pre_commit_commands(
    project_root: Path,
    concepts_dir: Path,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return the exact secret-scan then staged-validation argv contract."""
    return (
        (
            sys.executable,
            "-m",
            "agentkit.backend.governance.guard_system.secret_scan",
            "--staged",
        ),
        (
            sys.executable,
            "-m",
            "agentkit.backend.vectordb.cli",
            "--concepts-dir",
            str(project_root / concepts_dir),
            "validate",
            "--staged",
        ),
    )


def post_commit_commands(
    project_root: Path,
    concepts_dir: Path,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return the exact build-before-incremental-sync argv contract."""
    common = (
        sys.executable,
        "-m",
        "agentkit.backend.vectordb.cli",
        "--concepts-dir",
        str(project_root / concepts_dir),
    )
    return common + ("build",), common + ("sync",)


def _changed_paths(project_root: Path, *, staged: bool) -> tuple[str, ...]:
    command = (
        ["git", "diff", "--cached", "--name-only", "-z"]
        if staged
        else [
            "git",
            "diff-tree",
            "--root",
            "--no-commit-id",
            "--name-only",
            "-r",
            "-z",
            "HEAD",
        ]
    )
    completed = subprocess.run(
        command,
        cwd=project_root,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"git changed-path discovery failed: {detail}")
    try:
        decoded = completed.stdout.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RuntimeError("git returned non-UTF-8 changed paths") from exc
    return tuple(path for path in decoded.split("\0") if path)


def _run(command: list[str], *, project_root: Path, env: dict[str, str] | None = None) -> int:
    return subprocess.run(
        command,
        cwd=project_root,
        env=env,
        check=False,
    ).returncode


def _concept_changed(paths: tuple[str, ...], concepts_dir: Path) -> bool:
    prefix = concepts_dir.as_posix().rstrip("/") + "/"
    return any(path.replace("\\", "/").startswith(prefix) for path in paths)


def dispatch(project_root: Path, *, phase: str) -> int:
    """Dispatch one hook phase; every discovery or command fault is non-zero."""
    try:
        config = load_project_config(project_root)
        staged = phase == "pre-commit"
        paths = _changed_paths(project_root, staged=staged)
    except (ConfigError, RuntimeError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    concepts_dir = Path(config.concepts_dir)
    if phase == "pre-commit":
        secret_command, validate_command = pre_commit_commands(
            project_root,
            concepts_dir,
        )
        secret_status = _run(
            list(secret_command),
            project_root=project_root,
        )
        if secret_status != 0:
            return secret_status
        if not _concept_changed(paths, concepts_dir):
            return 0
        return _run(
            list(validate_command),
            project_root=project_root,
        )

    if phase != "post-commit":
        print(f"unsupported hook phase: {phase}", file=sys.stderr)
        return 2
    if not _concept_changed(paths, concepts_dir):
        return 0
    build_command, sync_command = post_commit_commands(project_root, concepts_dir)
    build_status = _run(
        list(build_command),
        project_root=project_root,
    )
    if build_status != 0:
        return build_status
    vectordb = config.pipeline.vectordb
    if vectordb is None or vectordb.weaviate_http_endpoint is None or vectordb.weaviate_grpc_endpoint is None:
        print("mandatory VectorDB endpoints are missing", file=sys.stderr)
        return 1
    project_id = config.project_prefix
    if not isinstance(project_id, str) or not project_id:
        print("mandatory project_prefix is missing", file=sys.stderr)
        return 1
    env = dict(os.environ)
    env.update(
        {
            "PROJECT_ID": project_id,
            "WEAVIATE_HTTP_ENDPOINT": vectordb.weaviate_http_endpoint,
            "WEAVIATE_GRPC_ENDPOINT": vectordb.weaviate_grpc_endpoint,
            "AGENTKIT_CONCEPTS_DIR": str(project_root / concepts_dir),
            "AGENTKIT_STORIES_DIR": str(project_root / config.wiki_stories_dir),
        }
    )
    return _run(
        list(sync_command),
        project_root=project_root,
        env=env,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--phase", required=True, choices=("pre-commit", "post-commit"))
    args = parser.parse_args(argv)
    return dispatch(args.project_root.resolve(), phase=args.phase)


if __name__ == "__main__":
    raise SystemExit(main())
