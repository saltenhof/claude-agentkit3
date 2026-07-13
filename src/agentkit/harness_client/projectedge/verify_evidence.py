"""Project Edge executor for two-stage verify-evidence collection."""

from __future__ import annotations

import fnmatch
import re
import subprocess
import sys
import time
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import TYPE_CHECKING

from agentkit.backend.core_types.verify_evidence import (
    MAX_EVIDENCE_FILE_BYTES,
    MAX_EVIDENCE_RESULT_BYTES,
    CollectVerifyEvidenceCommandPayload,
    VerifyEvidenceFile,
    VerifyEvidenceObservation,
    VerifyEvidenceObservationStatus,
    VerifyEvidenceReport,
    VerifyEvidenceStage,
    VerifyTestCommand,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from agentkit.backend.config.models import ProjectConfig
    from agentkit.backend.core_types.verify_evidence import VerifyEvidenceRepository, VerifyEvidenceRequest

_SNAPSHOT_SUFFIXES = frozenset(
    {".cfg", ".env", ".ini", ".java", ".js", ".jsx", ".json", ".md", ".py", ".pyi", ".toml", ".ts", ".tsx", ".yaml", ".yml"}
)
_SOURCE_SUFFIXES = frozenset({".java", ".js", ".jsx", ".kt", ".md", ".py", ".pyi", ".ts", ".tsx"})
_CONFIG_SUFFIXES = frozenset({".yaml", ".yml", ".json", ".env"})
_MAX_DYNAMIC_CANDIDATES = 32
_MAX_REQUEST_RESULT_BYTES = MAX_EVIDENCE_RESULT_BYTES // 8
_PYTEST_CACHE_DIR = ".pytest_cache"
_PYTEST_CACHE_ROOT_FILES = frozenset({".gitignore", "CACHEDIR.TAG", "README.md"})
_PYTEST_CACHE_VALUE_FILES = frozenset(
    {"durations", "lastfailed", "nodeids", "stepwise"}
)


class VerifyEvidenceEdgeError(RuntimeError):
    """Raised when edge collection cannot safely produce bound evidence."""


def execute_collect_verify_evidence(
    payload: CollectVerifyEvidenceCommandPayload,
    *,
    project_config: ProjectConfig,
    project_root: Path,
) -> VerifyEvidenceReport:
    """Execute one typed verify-evidence batch in dev-local worktrees."""
    try:
        roots = {
            repo.repo_id: _worktree_root(
                project_config, project_root, repo.repo_id, payload.story_id
            )
            for repo in payload.repositories
        }
        for repository in payload.repositories:
            _verify_candidate_head(roots[repository.repo_id], repository)
        if payload.stage is VerifyEvidenceStage.BASE_COLLECTION:
            files = _collect_base_files(payload, roots)
            _verify_candidate_heads(roots, payload.repositories)
            return _report(payload, files=tuple(files))
        observations = tuple(
            _collect_request(request, roots, payload.spawn_worktree_repo)
            for request in payload.requests
        )
        _verify_candidate_heads(roots, payload.repositories)
        return _report(payload, observations=observations)
    except (OSError, subprocess.SubprocessError, VerifyEvidenceEdgeError):
        return _failure_report(payload)


def _report(
    payload: CollectVerifyEvidenceCommandPayload,
    *,
    files: tuple[VerifyEvidenceFile, ...] = (),
    observations: tuple[VerifyEvidenceObservation, ...] = (),
    finding_code: str | None = None,
) -> VerifyEvidenceReport:
    """Build the correlation-echoing typed report."""
    return VerifyEvidenceReport(
        stage=payload.stage,
        batch_id=payload.batch_id,
        generation=payload.generation,
        candidate_digest=payload.candidate_digest,
        request_digest=payload.request_digest,
        finding_code=finding_code,
        files=files,
        observations=observations,
    )


def _failure_report(
    payload: CollectVerifyEvidenceCommandPayload,
) -> VerifyEvidenceReport:
    """Return a correlated named finding instead of using a backend fallback."""
    if payload.stage is VerifyEvidenceStage.BASE_COLLECTION:
        return _report(payload, finding_code="EDGE_COLLECTION_FAILED")
    observations = tuple(
        VerifyEvidenceObservation(
            request_index=request.request_index,
            status=VerifyEvidenceObservationStatus.REJECTED,
            finding_code="EDGE_COLLECTION_FAILED",
        )
        for request in payload.requests
    )
    return _report(
        payload,
        observations=observations,
        finding_code="EDGE_COLLECTION_FAILED",
    )


def _worktree_root(
    config: ProjectConfig, project_root: Path, repo_id: str, story_id: str
) -> Path:
    for repo in config.repositories:
        if repo.name != repo_id:
            continue
        root = repo.path if repo.path.is_absolute() else project_root / repo.path
        worktree = root / "worktrees" / story_id
        if root.is_symlink() or worktree.is_symlink() or not worktree.is_dir():
            raise VerifyEvidenceEdgeError(
                f"verify evidence requires a non-symlinked worktree for {repo_id!r}"
            )
        return worktree.resolve(strict=True)
    raise VerifyEvidenceEdgeError(f"repo {repo_id!r} is not configured")


def _verify_candidate_head(root: Path, repository: VerifyEvidenceRepository) -> None:
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    if result.returncode != 0 or result.stdout.strip() != repository.expected_head_sha:
        raise VerifyEvidenceEdgeError(
            f"candidate head drift for repo {repository.repo_id!r}"
        )
    status = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain", "--untracked-files=all"],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    dirty_entries = tuple(
        line
        for line in status.stdout.splitlines()
        if line.strip() and not _allowed_untracked_artifact(line)
    )
    if status.returncode != 0 or dirty_entries:
        raise VerifyEvidenceEdgeError(
            f"candidate worktree is not clean for repo {repository.repo_id!r}"
        )


def _allowed_untracked_artifact(status_line: str) -> bool:
    """Allow only the known untracked files created by the pytest runner."""
    if not status_line.startswith("?? "):
        return False
    raw_path = status_line[3:].strip('"').replace("\\", "/")
    if raw_path == ".agentkit-story.json":
        return True
    parts = PurePosixPath(raw_path).parts
    return raw_path.endswith(".pyc") or _is_standard_pytest_cache_file(parts)


def _is_standard_pytest_cache_file(parts: tuple[str, ...]) -> bool:
    """Recognize only pytest's standard cache layout, not arbitrary content."""
    try:
        cache_index = parts.index(_PYTEST_CACHE_DIR)
    except ValueError:
        return False
    relative = parts[cache_index + 1 :]
    if len(relative) == 1:
        return relative[0] in _PYTEST_CACHE_ROOT_FILES
    return (
        len(relative) == 3
        and relative[:2] == ("v", "cache")
        and relative[2] in _PYTEST_CACHE_VALUE_FILES
    )


def _verify_candidate_heads(
    roots: dict[str, Path],
    repositories: tuple[VerifyEvidenceRepository, ...],
) -> None:
    """Recheck commit and cleanliness after collection to detect drift."""
    for repository in repositories:
        _verify_candidate_head(roots[repository.repo_id], repository)


def _collect_base_files(
    payload: CollectVerifyEvidenceCommandPayload, roots: dict[str, Path]
) -> list[VerifyEvidenceFile]:
    selected: dict[tuple[str, str], Path] = {}
    for repository in payload.repositories:
        selected.update(
            _base_repository_paths(
                repository,
                roots[repository.repo_id],
                payload.worker_hint_paths,
            )
        )
    selected.update(_import_target_paths(payload, roots))
    return _files_within_result_limit(selected)


def _base_repository_paths(
    repository: VerifyEvidenceRepository,
    root: Path,
    worker_hint_paths: tuple[str, ...],
) -> dict[tuple[str, str], Path]:
    selected: dict[tuple[str, str], Path] = {}
    mandatory = set(repository.changed_paths)
    mandatory.update(_worker_hints_for_repo(worker_hint_paths, repository.repo_id))
    for raw_path in mandatory:
        path = _safe_file(root, raw_path)
        if path is not None:
            selected[(repository.repo_id, raw_path)] = path
    for changed in repository.changed_paths:
        directory = PurePosixPath(changed).parent.as_posix()
        for path in _safe_directory_files(root, directory):
            if path.suffix.lower() in _SNAPSHOT_SUFFIXES:
                selected[(repository.repo_id, path.relative_to(root).as_posix())] = path
    for path in _safe_directory_files(root, "."):
        if path.suffix.lower() in _CONFIG_SUFFIXES:
            selected[(repository.repo_id, path.name)] = path
    return selected


def _files_within_result_limit(
    selected: dict[tuple[str, str], Path],
) -> list[VerifyEvidenceFile]:
    files: list[VerifyEvidenceFile] = []
    total = 0
    for (repo_id, rel_path), path in sorted(selected.items()):
        content = _read_bounded_text(path)
        file = VerifyEvidenceFile.from_content(
            repo_id=repo_id, path=rel_path, content=content
        )
        total += file.size
        if total > MAX_EVIDENCE_RESULT_BYTES:
            raise VerifyEvidenceEdgeError(
                "verify-evidence base snapshot exceeds the result limit"
            )
        files.append(file)
    return files


def _import_target_paths(
    payload: CollectVerifyEvidenceCommandPayload,
    roots: dict[str, Path],
) -> dict[tuple[str, str], Path]:
    """Discover import targets at the Edge, returning only bounded targets."""
    from agentkit.harness_client.projectedge.verify_imports import (
        collect_import_target_keys,
    )

    snapshot = tuple(
        file
        for repo_id, root in roots.items()
        for path in _snapshot_files(root)
        if (file := _snapshot_file(repo_id, root, path)) is not None
    )
    by_key = {(file.repo_id, file.path): file.content for file in snapshot}
    changed = {
        repository.repo_id: repository.changed_paths
        for repository in payload.repositories
    }
    targets: dict[tuple[str, str], Path] = {}
    for repo_id, target_path in collect_import_target_keys(by_key, changed):
        path = _safe_file(roots[repo_id], target_path)
        if path is not None:
            targets[(repo_id, target_path)] = path
    return targets


def _snapshot_file(repo_id: str, root: Path, path: Path) -> VerifyEvidenceFile | None:
    """Read one scan candidate, skipping files too large for the wire contract."""
    if path.stat().st_size > MAX_EVIDENCE_FILE_BYTES:
        return None
    return VerifyEvidenceFile.from_content(
        repo_id=repo_id,
        path=path.relative_to(root).as_posix(),
        content=path.read_text(encoding="utf-8", errors="replace"),
    )


def _snapshot_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        if (
            {".git", _PYTEST_CACHE_DIR, "__pycache__"}.intersection(path.parts)
            or path.is_symlink()
            or not path.is_file()
        ):
            continue
        if path.suffix.lower() in _SNAPSHOT_SUFFIXES or path.name.endswith(".env"):
            yield path


def _collect_request(
    request: VerifyEvidenceRequest,
    roots: dict[str, Path],
    spawn_repo: str,
) -> VerifyEvidenceObservation:
    start = time.monotonic()
    if request.request_type == "NEED_TEST_EVIDENCE":
        assert request.test_command is not None  # noqa: S101 -- contract validator
        return _run_test(request.request_index, request.test_command, roots[spawn_repo], start)
    try:
        candidates = _request_candidates(request, roots)
    except VerifyEvidenceEdgeError as exc:
        return VerifyEvidenceObservation(
            request_index=request.request_index,
            status=VerifyEvidenceObservationStatus.REJECTED,
            content=str(exc),
            finding_code="EDGE_REQUEST_INVALID",
            duration_ms=_elapsed_ms(start),
        )
    selected = tuple(candidates[:_MAX_DYNAMIC_CANDIDATES])
    if sum(candidate.size for candidate in selected) > _MAX_REQUEST_RESULT_BYTES:
        return VerifyEvidenceObservation(
            request_index=request.request_index,
            status=VerifyEvidenceObservationStatus.REJECTED,
            finding_code="EDGE_RESULT_LIMIT",
            duration_ms=_elapsed_ms(start),
        )
    return VerifyEvidenceObservation(
        request_index=request.request_index,
        status=(
            VerifyEvidenceObservationStatus.COLLECTED
            if candidates
            else VerifyEvidenceObservationStatus.UNRESOLVED
        ),
        candidates=selected,
        finding_code=None if candidates else "EDGE_NO_CANDIDATE",
        duration_ms=_elapsed_ms(start),
    )


def _request_candidates(
    request: VerifyEvidenceRequest, roots: dict[str, Path]
) -> list[VerifyEvidenceFile]:
    if request.request_type == "NEED_FILE":
        return _file_candidates(request.target, roots)
    if request.request_type == "NEED_SCHEMA":
        pattern = re.compile(
            rf"\b(?:class|interface|type|enum|record)\s+{re.escape(request.target)}\b"
        )
        return _text_candidates(pattern, roots, suffixes=_SOURCE_SUFFIXES)
    if request.request_type == "NEED_CALLSITE":
        return _text_candidates(
            re.compile(rf"\b{re.escape(request.target)}\s*\("),
            roots,
            suffixes=_SOURCE_SUFFIXES,
        )
    if request.request_type == "NEED_RUNTIME_BINDING":
        return _text_candidates(
            re.compile(re.escape(request.target)), roots, suffixes=_CONFIG_SUFFIXES
        )
    candidates = _file_candidates(request.target, roots)
    if request.region:
        return [
            VerifyEvidenceFile.from_content(
                repo_id=item.repo_id,
                path=item.path,
                content=_extract_region(item.content, request.region) or item.content,
            )
            for item in candidates
        ]
    return candidates


def _file_candidates(target: str, roots: dict[str, Path]) -> list[VerifyEvidenceFile]:
    normalized = _safe_target(target)
    selected = _exact_file_candidates(normalized, roots)
    if not selected:
        selected = _matching_file_candidates(normalized, roots)
    if not selected:
        selected = _substring_file_candidates(normalized, roots)
    return _files_from_paths(selected)


def _exact_file_candidates(
    normalized: str, roots: dict[str, Path]
) -> dict[tuple[str, str], Path]:
    return {
        (repo_id, normalized): exact
        for repo_id, root in roots.items()
        if (exact := _safe_file(root, normalized)) is not None
    }


def _matching_file_candidates(
    normalized: str, roots: dict[str, Path]
) -> dict[tuple[str, str], Path]:
    return {
        (repo_id, relative): path
        for repo_id, root in roots.items()
        for path in _snapshot_files(root)
        if fnmatch.fnmatch(
            (relative := path.relative_to(root).as_posix()), normalized
        )
    }


def _substring_file_candidates(
    normalized: str, roots: dict[str, Path]
) -> dict[tuple[str, str], Path]:
    lowered = normalized.lower()
    return {
        (repo_id, relative): path
        for repo_id, root in roots.items()
        for path in _snapshot_files(root)
        if lowered in (relative := path.relative_to(root).as_posix()).lower()
    }


def _text_candidates(
    pattern: re.Pattern[str],
    roots: dict[str, Path],
    *,
    suffixes: frozenset[str],
) -> list[VerifyEvidenceFile]:
    selected: dict[tuple[str, str], Path] = {}
    for repo_id, root in roots.items():
        for path in _snapshot_files(root):
            if path.suffix.lower() not in suffixes and path.name not in {".env"}:
                continue
            if pattern.search(_read_bounded_text(path)):
                selected[(repo_id, path.relative_to(root).as_posix())] = path
    return _files_from_paths(selected)


def _files_from_paths(selected: dict[tuple[str, str], Path]) -> list[VerifyEvidenceFile]:
    return [
        VerifyEvidenceFile.from_content(
            repo_id=repo_id, path=path, content=_read_bounded_text(file_path)
        )
        for (repo_id, path), file_path in sorted(selected.items())
    ]


def _run_test(
    request_index: int,
    command: VerifyTestCommand,
    root: Path,
    start: float,
) -> VerifyEvidenceObservation:
    target_error = _test_target_error(command, root)
    if target_error is not None:
        return VerifyEvidenceObservation(
            request_index=request_index,
            status=VerifyEvidenceObservationStatus.REJECTED,
            content=target_error,
            finding_code="TEST_COMMAND_REJECTED",
            duration_ms=_elapsed_ms(start),
        )
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", *command.arguments],
            cwd=root,
            shell=False,
            capture_output=True,
            text=True,
            check=False,
            timeout=command.timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return VerifyEvidenceObservation(
            request_index=request_index,
            status=VerifyEvidenceObservationStatus.TIMEOUT,
            finding_code="TEST_EVIDENCE_TIMEOUT",
            duration_ms=_elapsed_ms(start),
        )
    output = (
        f"exit_code={result.returncode}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
    return VerifyEvidenceObservation(
        request_index=request_index,
        status=VerifyEvidenceObservationStatus.COLLECTED,
        content=_bounded_text(output),
        duration_ms=_elapsed_ms(start),
    )


def _safe_target(target: str) -> str:
    path = PurePosixPath(target.replace("\\", "/"))
    windows_path = PureWindowsPath(target)
    if (
        path.is_absolute()
        or windows_path.is_absolute()
        or bool(windows_path.drive)
        or ".." in path.parts
        or not target.strip()
    ):
        raise VerifyEvidenceEdgeError("request target must stay inside a worktree")
    return path.as_posix()


def _safe_file(root: Path, raw_path: str) -> Path | None:
    normalized = _safe_target(raw_path)
    parts = PurePosixPath(normalized).parts
    if (
        normalized.endswith(".pyc")
        or _PYTEST_CACHE_DIR in parts
        or "__pycache__" in parts
    ):
        return None
    target = root / normalized
    if target.is_symlink() or not target.is_file():
        return None
    resolved = target.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise VerifyEvidenceEdgeError("request target escapes the worktree") from exc
    return resolved


def _safe_directory_files(root: Path, raw_path: str) -> Iterable[Path]:
    directory = root / _safe_target(raw_path or ".")
    if directory.is_symlink() or not directory.is_dir():
        return ()
    return tuple(
        child
        for child in directory.iterdir()
        if child.is_file() and not child.is_symlink()
    )


def _read_bounded_text(path: Path) -> str:
    if path.stat().st_size > MAX_EVIDENCE_FILE_BYTES:
        raise VerifyEvidenceEdgeError(f"evidence file exceeds limit: {path.name}")
    return path.read_text(encoding="utf-8", errors="replace")


def _extract_region(content: str, region: str) -> str | None:
    lines = content.splitlines()
    for index, line in enumerate(lines):
        if region in line:
            return "\n".join(lines[max(0, index - 30) : index + 31])
    return None


def _elapsed_ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)


def _worker_hints_for_repo(hints: tuple[str, ...], repo_id: str) -> tuple[str, ...]:
    """Select global and explicitly repo-scoped worker hint paths."""
    selected: list[str] = []
    for hint in hints:
        if ":" not in hint:
            selected.append(hint)
            continue
        scoped_repo, path = hint.split(":", 1)
        if scoped_repo == repo_id:
            selected.append(path)
    return tuple(selected)


def _test_target_error(command: VerifyTestCommand, root: Path) -> str | None:
    """Reject positional pytest targets that resolve outside the worktree."""
    value_flags = {"-k", "-m", "--maxfail", "--tb"}
    skip_value = False
    resolved_root = root.resolve(strict=True)
    for argument in command.arguments:
        if skip_value:
            skip_value = False
            continue
        if argument in value_flags:
            skip_value = True
            continue
        if argument.startswith("-"):
            continue
        raw_target = argument.split("::", maxsplit=1)[0]
        target = (resolved_root / raw_target).resolve(strict=False)
        try:
            target.relative_to(resolved_root)
        except ValueError:
            return "pytest target resolves outside the worktree"
    return None


def _bounded_text(content: str) -> str:
    """Truncate text to the wire byte limit without breaking UTF-8."""
    return content.encode("utf-8")[:_MAX_REQUEST_RESULT_BYTES].decode(
        "utf-8", errors="ignore"
    )


__all__ = ["VerifyEvidenceEdgeError", "execute_collect_verify_evidence"]
