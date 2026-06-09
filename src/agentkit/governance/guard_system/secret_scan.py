"""Pre-commit secret scan entry point backed by the shared pattern source."""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from agentkit.governance.guard_system.secret_patterns import (
    SecretContentHit,
    SecretFileHit,
    find_secret_content_hits,
    find_secret_file_hits,
)


@dataclass(frozen=True)
class SecretScanResult:
    """Result of scanning a staged or supplied diff."""

    file_hits: tuple[SecretFileHit, ...]
    content_hits: tuple[SecretContentHit, ...]

    @property
    def clean(self) -> bool:
        """Return ``True`` when no secret hit was found."""
        return not self.file_hits and not self.content_hits


def scan_paths_and_diff(
    paths: tuple[str, ...],
    diff_text: str,
) -> SecretScanResult:
    """Scan changed paths and unified diff additions for canonical secret patterns."""
    return SecretScanResult(
        file_hits=find_secret_file_hits(paths),
        content_hits=find_secret_content_hits(_added_lines_from_unified_diff(diff_text)),
    )


def scan_staged_diff(repo_root: Path) -> SecretScanResult:
    """Scan the git staged diff for canonical secret file and content patterns."""
    paths = _git_lines(
        repo_root,
        "diff",
        "--cached",
        "--name-only",
        "--diff-filter=ACMR",
    )
    diff_text = _git_text(
        repo_root,
        "diff",
        "--cached",
        "--unified=0",
        "--no-ext-diff",
        "--diff-filter=ACMR",
    )
    return scan_paths_and_diff(paths, diff_text)


def _added_lines_from_unified_diff(diff_text: str) -> tuple[tuple[str, str], ...]:
    current_path = ""
    added: list[tuple[str, str]] = []
    for raw_line in diff_text.splitlines():
        if raw_line.startswith("+++ b/"):
            current_path = raw_line.removeprefix("+++ b/")
            continue
        if raw_line.startswith("+") and not raw_line.startswith("+++"):
            added.append((current_path, raw_line[1:]))
    return tuple(added)


def _git_lines(repo_root: Path, *args: str) -> tuple[str, ...]:
    text = _git_text(repo_root, *args)
    return tuple(line.strip() for line in text.splitlines() if line.strip())


def _git_text(repo_root: Path, *args: str) -> str:
    try:
        result = subprocess.run(  # noqa: S603
            ["git", "-C", str(repo_root), *args],  # noqa: S607
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise RuntimeError(f"git unavailable for secret scan: {exc}") from exc
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"git secret scan command failed: {message}")
    return result.stdout


def main(argv: list[str] | None = None) -> int:
    """Run the pre-commit staged secret scan."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--staged", action="store_true", required=True)
    parser.add_argument("--repo-root", default=".")
    args = parser.parse_args(argv)
    try:
        result = scan_staged_diff(Path(str(args.repo_root)).resolve())
    except Exception as exc:  # noqa: BLE001 -- hook must fail closed
        print(f"[pre-commit] Secret scan failed closed: {exc}", file=sys.stderr)
        return 1
    if result.clean:
        return 0
    print("[pre-commit] Secret scan rejected this commit:", file=sys.stderr)
    for file_hit in result.file_hits:
        print(
            f"  file: {file_hit.path} matched {file_hit.pattern.kind.value} "
            f"{file_hit.pattern.value!r}",
            file=sys.stderr,
        )
    for content_hit in result.content_hits:
        print(
            f"  content: {content_hit.path} matched {content_hit.pattern.value!r}",
            file=sys.stderr,
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "SecretScanResult",
    "main",
    "scan_paths_and_diff",
    "scan_staged_diff",
]
