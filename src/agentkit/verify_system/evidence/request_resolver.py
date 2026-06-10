"""Deterministic resolver for reviewer preflight request DSL."""

from __future__ import annotations

import json
import logging
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from agentkit.verify_system.evidence.request_types import (
    RequestResult,
    RequestType,
    ReviewerRequest,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping, Sequence

    from agentkit.verify_system.evidence.repo_context import RepoContext


logger = logging.getLogger(__name__)

REQUEST_TIMEOUT_S = 30
MAX_REQUESTS = 8

CONFIG_SUFFIXES = frozenset({".yaml", ".yml", ".json", ".env"})
SOURCE_SUFFIXES = frozenset({
    ".java",
    ".js",
    ".jsx",
    ".kt",
    ".md",
    ".py",
    ".pyi",
    ".ts",
    ".tsx",
})


@dataclass(frozen=True)
class _Candidate:
    repo_id: str
    repo_root: Path
    rel_path: Path
    content: str

    @property
    def scoped_path(self) -> str:
        return f"{self.repo_id}:{self.rel_path.as_posix()}"


def parse_preflight_response(raw_response: str) -> list[ReviewerRequest]:
    """Parse reviewer JSON into capped ``ReviewerRequest`` objects.

    Invalid JSON or schema returns an empty list and logs a WARNING. More than
    ``MAX_REQUESTS`` requests are deterministically capped to the first eight
    and also logged as a WARNING.
    """
    try:
        data = json.loads(raw_response)
        raw_requests = data["requests"]
        if not isinstance(raw_requests, list):
            msg = "requests must be a list"
            raise ValueError(msg)
        if len(raw_requests) > MAX_REQUESTS:
            logger.warning(
                "Preflight response contained %s requests; processing first %s.",
                len(raw_requests),
                MAX_REQUESTS,
            )
        return [ReviewerRequest(**item) for item in raw_requests[:MAX_REQUESTS]]
    except (KeyError, TypeError, ValueError) as exc:
        logger.warning("Preflight response could not be parsed: %s", exc)
        return []


class RequestResolver:
    """Resolve all seven reviewer request types across participating repos."""

    def __init__(
        self,
        repos: Mapping[str, RepoContext],
        spawn_worktree_repo: str,
        *,
        story_dir: Path,
    ) -> None:
        """Create a resolver for the full multi-repo context."""
        if spawn_worktree_repo not in repos:
            msg = f"spawn_worktree_repo is not part of repos: {spawn_worktree_repo}"
            raise ValueError(msg)
        self._repos = dict(repos)
        self._spawn_worktree_repo = spawn_worktree_repo
        self._story_dir = story_dir

    def resolve_all(self, requests: Sequence[ReviewerRequest]) -> list[RequestResult]:
        """Resolve up to ``MAX_REQUESTS`` requests and continue after timeouts."""
        if len(requests) > MAX_REQUESTS:
            logger.warning(
                "Preflight resolver received %s requests; processing first %s.",
                len(requests),
                MAX_REQUESTS,
            )
        return [self._resolve_single(request) for request in requests[:MAX_REQUESTS]]

    def _resolve_single(self, request: ReviewerRequest) -> RequestResult:
        handlers: dict[RequestType, Callable[[ReviewerRequest], RequestResult]] = {
            RequestType.NEED_FILE: self._resolve_file,
            RequestType.NEED_SCHEMA: self._resolve_schema,
            RequestType.NEED_CALLSITE: self._resolve_callsite,
            RequestType.NEED_RUNTIME_BINDING: self._resolve_runtime_binding,
            RequestType.NEED_TEST_EVIDENCE: self._resolve_test_evidence,
            RequestType.NEED_CONCEPT_SOURCE: self._resolve_concept_source,
            RequestType.NEED_DIFF_EXPANSION: self._resolve_diff_expansion,
        }
        return handlers[request.type](request)

    def _resolve_file(self, request: ReviewerRequest) -> RequestResult:
        """Resolve an exact file path or glob-like pattern."""
        candidates = self._exact_file_candidates(request.target)
        if not candidates:
            candidates = self._glob_candidates(request.target)
        if not candidates:
            candidates = self._filename_contains_candidates(request.target)
        return self._d3_result(request, candidates)

    def _resolve_schema(self, request: ReviewerRequest) -> RequestResult:
        """Resolve class, interface or type definitions by symbol name."""
        pattern = re.compile(
            rf"\b(?:class|interface|type|enum|record)\s+{re.escape(request.target)}\b"
        )
        return self._d3_result(request, self._text_match_candidates(pattern))

    def _resolve_callsite(self, request: ReviewerRequest) -> RequestResult:
        """Resolve call sites for a function or method name."""
        pattern = re.compile(rf"\b{re.escape(request.target)}\s*\(")
        return self._d3_result(request, self._text_match_candidates(pattern))

    def _resolve_runtime_binding(self, request: ReviewerRequest) -> RequestResult:
        """Resolve runtime config bindings in affected repositories."""
        pattern = re.compile(re.escape(request.target))
        files = (
            file_path
            for repo in self._ordered_repos(affected_only=True)
            for file_path in self._repo_files(repo)
            if file_path.suffix in CONFIG_SUFFIXES or file_path.name.endswith(".env")
        )
        return self._d3_result(request, self._text_match_candidates(pattern, files=files))

    def _resolve_test_evidence(self, request: ReviewerRequest) -> RequestResult:
        """Run a test command in the spawn worktree repo with a hard timeout."""
        start = time.monotonic()
        repo = self._repos[self._spawn_worktree_repo]
        try:
            result = subprocess.run(
                request.target,
                cwd=repo.repo_path,
                shell=True,
                check=False,
                capture_output=True,
                text=True,
                timeout=REQUEST_TIMEOUT_S,
            )
        except subprocess.TimeoutExpired as exc:
            return RequestResult(
                request=request,
                status="TIMEOUT",
                content=str(exc),
                duration_ms=_elapsed_ms(start),
            )
        output = f"exit_code={result.returncode}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        return RequestResult(
            request=request,
            status="RESOLVED",
            content=output,
            duration_ms=_elapsed_ms(start),
        )

    def _resolve_concept_source(self, request: ReviewerRequest) -> RequestResult:
        """Resolve a concept or story heading by text match."""
        pattern = re.compile(rf"^#+\s+.*{re.escape(request.target)}.*$", re.MULTILINE)
        project_root = _project_root_for_story_dir(self._story_dir)
        roots = (project_root / "concept", project_root / "stories", self._story_dir)
        files = (
            file_path
            for root in roots
            if root.exists()
            for file_path in root.rglob("*.md")
        )
        return self._d3_result(request, self._text_match_candidates(pattern, files=files))

    def _resolve_diff_expansion(self, request: ReviewerRequest) -> RequestResult:
        """Resolve extended diff context for one requested file."""
        candidates = self._exact_file_candidates(request.target)
        if len(candidates) != 1:
            return self._d3_result(request, candidates)
        candidate = candidates[0]
        command = [
            "git",
            "diff",
            f"--unified={REQUEST_TIMEOUT_S}",
            "--",
            candidate.rel_path.as_posix(),
        ]
        start = time.monotonic()
        result = subprocess.run(
            command,
            cwd=candidate.repo_root,
            check=False,
            capture_output=True,
            text=True,
            timeout=REQUEST_TIMEOUT_S,
        )
        content = result.stdout or candidate.content
        if request.region:
            content = _extract_region(content, request.region) or content
        return RequestResult(
            request=request,
            status="RESOLVED",
            content=content,
            file_path=candidate.rel_path.as_posix(),
            duration_ms=_elapsed_ms(start),
        )

    def _d3_result(
        self,
        request: ReviewerRequest,
        candidates: Sequence[_Candidate],
    ) -> RequestResult:
        start = time.monotonic()
        unique = _unique_candidates(candidates)
        if len(unique) == 1:
            candidate = unique[0]
            return RequestResult(
                request=request,
                status="RESOLVED",
                content=candidate.content,
                file_path=candidate.rel_path.as_posix(),
                duration_ms=_elapsed_ms(start),
            )
        if not unique:
            content = "No deterministic match found."
        else:
            content = "Ambiguous candidates:\n" + "\n".join(candidate.scoped_path for candidate in unique)
        return RequestResult(
            request=request,
            status="UNRESOLVED",
            content=content,
            duration_ms=_elapsed_ms(start),
        )

    def _exact_file_candidates(self, target: str) -> list[_Candidate]:
        raw_path = Path(target)
        candidates: list[_Candidate] = []
        for repo in self._ordered_repos():
            path = raw_path if raw_path.is_absolute() else repo.repo_path / raw_path
            candidate = path.resolve()
            if candidate.is_file() and _is_under(candidate, repo.repo_path):
                candidates.append(self._candidate(repo, candidate))
        return candidates

    def _glob_candidates(self, target: str) -> list[_Candidate]:
        candidates: list[_Candidate] = []
        for repo in self._ordered_repos():
            for candidate in repo.repo_path.glob(target):
                if candidate.is_file():
                    candidates.append(self._candidate(repo, candidate))
        return candidates

    def _filename_contains_candidates(self, target: str) -> list[_Candidate]:
        normalized = target.lower()
        return [
            self._candidate(repo, file_path)
            for repo in self._ordered_repos()
            for file_path in self._repo_files(repo)
            if normalized in file_path.as_posix().lower()
        ]

    def _text_match_candidates(
        self,
        pattern: re.Pattern[str],
        *,
        files: Iterable[Path] | None = None,
    ) -> list[_Candidate]:
        candidates: list[_Candidate] = []
        materialized = list(files) if files is not None else [
            file_path for repo in self._ordered_repos() for file_path in self._repo_files(repo)
        ]
        for file_path in materialized:
            if files is None and file_path.suffix not in SOURCE_SUFFIXES:
                continue
            content = file_path.read_text(encoding="utf-8", errors="replace")
            if pattern.search(content):
                candidates.append(self._candidate_for_path(file_path, content=content))
        return candidates

    def _ordered_repos(self, *, affected_only: bool = False) -> list[RepoContext]:
        repos = [repo for repo in self._repos.values() if not affected_only or repo.affected]
        return sorted(
            repos,
            key=lambda repo: (repo.repo_id != self._spawn_worktree_repo, repo.repo_id),
        )

    def _repo_files(self, repo: RepoContext) -> Iterable[Path]:
        return (path for path in repo.repo_path.rglob("*") if path.is_file() and ".git" not in path.parts)

    def _repo_for_path(self, file_path: Path) -> RepoContext:
        for repo in self._repos.values():
            if _is_under(file_path, repo.repo_path):
                return repo
        msg = f"path is outside configured repositories: {file_path}"
        raise ValueError(msg)

    def _candidate(
        self,
        repo: RepoContext,
        file_path: Path,
        *,
        content: str | None = None,
    ) -> _Candidate:
        resolved = file_path.resolve()
        rel_path = Path(resolved.relative_to(repo.repo_path.resolve()).as_posix())
        return _Candidate(
            repo_id=repo.repo_id,
            repo_root=repo.repo_path,
            rel_path=rel_path,
            content=content if content is not None else resolved.read_text(encoding="utf-8", errors="replace"),
        )

    def _candidate_for_path(self, file_path: Path, *, content: str) -> _Candidate:
        try:
            repo = self._repo_for_path(file_path)
        except ValueError:
            resolved = file_path.resolve()
            return _Candidate(
                repo_id="_context",
                repo_root=resolved.parent,
                rel_path=resolved,
                content=content,
            )
        return self._candidate(repo, file_path, content=content)


def _unique_candidates(candidates: Sequence[_Candidate]) -> list[_Candidate]:
    by_key = {(candidate.repo_id, candidate.rel_path.as_posix()): candidate for candidate in candidates}
    return [by_key[key] for key in sorted(by_key)]


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _project_root_for_story_dir(story_dir: Path) -> Path:
    resolved = story_dir.resolve()
    if resolved.parent.name == "stories":
        return resolved.parent.parent
    return resolved.parent


def _elapsed_ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)


def _extract_region(content: str, region: str) -> str | None:
    lines = content.splitlines()
    for index, line in enumerate(lines):
        if region in line:
            lower = max(0, index - REQUEST_TIMEOUT_S)
            upper = min(len(lines), index + REQUEST_TIMEOUT_S + 1)
            return "\n".join(lines[lower:upper])
    return None


__all__ = [
    "MAX_REQUESTS",
    "REQUEST_TIMEOUT_S",
    "RequestResolver",
    "parse_preflight_response",
]
