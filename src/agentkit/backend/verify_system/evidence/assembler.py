"""Evidence assembler for deterministic review bundle preparation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel, ConfigDict, Field

from agentkit.backend.core_types import HANDOVER_FILE, WORKER_MANIFEST_FILE
from agentkit.backend.verify_system.evidence.authority import AuthorityClass, BundleEntry
from agentkit.backend.verify_system.evidence.bundle_manifest import BundleManifest
from agentkit.backend.verify_system.evidence.repo_context import RepoContext
from agentkit.backend.verify_system.structural.system_evidence import (
    ABSENT_CHANGE_EVIDENCE_PORT,
    ChangeEvidencePort,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence
    from datetime import datetime

BUNDLE_SIZE_LIMIT = 350 * 1024

_NEIGHBOR_EXTENSIONS = frozenset({
    ".cfg",
    ".css",
    ".ini",
    ".java",
    ".js",
    ".json",
    ".md",
    ".py",
    ".pyi",
    ".toml",
    ".ts",
    ".tsx",
    ".yaml",
    ".yml",
})
_CONFIG_EXTENSIONS = frozenset({".json", ".toml", ".yaml", ".yml"})
_WORKER_HINT_FILES = (HANDOVER_FILE, WORKER_MANIFEST_FILE)
_PATH_KEYS = frozenset({
    "file",
    "file_path",
    "file_paths",
    "files",
    "merge_paths",
    "path",
    "paths",
    "relevant_files",
})


class ImportEvidenceProvider(Protocol):
    """Stage-2 port for import-derived evidence entries.

    AG3-062 can implement this protocol with the FK-46 import resolver without
    changing the assembler contract.
    """

    def collect(
        self,
        repos: Mapping[str, RepoContext],
        changed_files_by_repo: Mapping[str, Sequence[Path]],
    ) -> Sequence[BundleEntry]:
        """Return import-derived bundle entries."""
        ...


class EvidenceAssemblyError(RuntimeError):
    """Raised when evidence assembly cannot produce a valid manifest."""


class EvidenceAssemblyResult(BaseModel):
    """Result of one evidence assembly run.

    Attributes:
        manifest: Bundle manifest for the included entries.
        merge_paths: Deterministically sorted, deduplicated manifest paths.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    manifest: BundleManifest
    merge_paths: tuple[str, ...] = Field(default_factory=tuple)


class EvidenceAssembler:
    """Assemble deterministic review evidence from system-owned inputs."""

    def __init__(
        self,
        repos: Mapping[str, RepoContext],
        *,
        change_evidence_port: ChangeEvidencePort | None = None,
        import_evidence_provider: ImportEvidenceProvider | None = None,
        import_entries: Iterable[BundleEntry] = (),
        bundle_size_limit: int = BUNDLE_SIZE_LIMIT,
    ) -> None:
        """Create an assembler for a repo set.

        Args:
            repos: Participating repositories keyed by ``repo_id``.
            change_evidence_port: Existing system-evidence read port. The
                assembler never shells out to git.
            import_evidence_provider: Optional Stage-2 provider for AG3-062.
            import_entries: Optional pre-resolved Stage-2 entries.
            bundle_size_limit: Hard uncompressed bundle size limit in bytes.

        Raises:
            EvidenceAssemblyError: If repos or the size limit are invalid.
        """
        if not repos:
            msg = "at least one RepoContext is required for evidence assembly"
            raise EvidenceAssemblyError(msg)
        if bundle_size_limit <= 0:
            msg = "bundle_size_limit must be positive"
            raise EvidenceAssemblyError(msg)
        normalized: dict[str, RepoContext] = {}
        for repo_id, repo in repos.items():
            if repo_id != repo.repo_id:
                msg = f"repo mapping key {repo_id!r} does not match RepoContext.repo_id {repo.repo_id!r}"
                raise EvidenceAssemblyError(msg)
            normalized[repo_id] = repo
        self._repos = normalized
        self._change_evidence_port = change_evidence_port or ABSENT_CHANGE_EVIDENCE_PORT
        self._import_evidence_provider = import_evidence_provider
        self._import_entries = tuple(import_entries)
        self._bundle_size_limit = bundle_size_limit

    def assemble(
        self,
        *,
        story_dir: Path,
        evidence_epoch: datetime | str | None = None,
    ) -> EvidenceAssemblyResult:
        """Run the FK-28 three-stage assembly and return a manifest result.

        Args:
            story_dir: Directory containing story evidence artifacts.
            evidence_epoch: Optional injected manifest epoch.

        Returns:
            An :class:`EvidenceAssemblyResult`.

        Raises:
            EvidenceAssemblyError: If mandatory evidence is missing or invalid.
        """
        resolved_story_dir = story_dir.resolve()
        if not resolved_story_dir.is_dir():
            msg = f"story_dir does not exist or is not a directory: {story_dir}"
            raise EvidenceAssemblyError(msg)

        warnings: list[str] = []
        changed_files_by_repo: dict[str, tuple[Path, ...]] = {}
        stage1_entries = self._stage1_deterministic(
            story_dir=resolved_story_dir,
            changed_files_by_repo=changed_files_by_repo,
        )
        stage2_entries = self._stage2_imports(changed_files_by_repo)
        seeded_keys = _entry_keys([*stage1_entries, *stage2_entries])
        stage3_entries = self._stage3_worker_hints(
            story_dir=resolved_story_dir,
            seeded_keys=seeded_keys,
            changed_files_by_repo=changed_files_by_repo,
            warnings=warnings,
        )

        deduplicated = self._deduplicate(
            [*stage1_entries, *stage2_entries, *stage3_entries]
        )
        included, truncated = self._enforce_size_limit(deduplicated, warnings)
        if not included:
            msg = "evidence assembly produced no entries after validation"
            raise EvidenceAssemblyError(msg)
        manifest = BundleManifest.from_entries(
            included,
            truncated=truncated,
            warnings=warnings,
            evidence_epoch=evidence_epoch,
        )
        return EvidenceAssemblyResult(
            manifest=manifest,
            merge_paths=tuple(dict.fromkeys(manifest.file_paths)),
        )

    def _stage1_deterministic(
        self,
        *,
        story_dir: Path,
        changed_files_by_repo: dict[str, tuple[Path, ...]],
    ) -> list[BundleEntry]:
        entries: list[BundleEntry] = []
        changed_entry_count = 0
        for repo in self._affected_repos():
            self._ensure_repo_path(repo)
            evidence = self._change_evidence_port.collect(repo.repo_path)
            if not evidence.available:
                msg = f"change evidence is unavailable for affected repo {repo.repo_id}"
                raise EvidenceAssemblyError(msg)
            changed_paths = tuple(
                self._resolve_repo_relative_path(repo, changed)
                for changed in sorted(set(evidence.changed_files))
            )
            if not changed_paths:
                msg = f"mandatory changed-file evidence is empty for affected repo {repo.repo_id}"
                raise EvidenceAssemblyError(msg)
            changed_files_by_repo[repo.repo_id] = changed_paths
            for rel_path in changed_paths:
                entries.append(
                    self._entry_from_file(
                        repo=repo,
                        rel_path=rel_path,
                        authority=AuthorityClass.PRIMARY_IMPLEMENTATION,
                        reason="Changed file from system change evidence",
                        confidence=None,
                    )
                )
                changed_entry_count += 1
            entries.extend(self._module_neighbors(repo=repo, changed_paths=changed_paths))
            entries.extend(self._config_entries(repo=repo, changed_paths=changed_paths))
        if changed_entry_count == 0:
            msg = "mandatory changed-file evidence is missing"
            raise EvidenceAssemblyError(msg)
        entries.extend(self._normative_entries(story_dir))
        return entries

    def _stage2_imports(
        self,
        changed_files_by_repo: Mapping[str, Sequence[Path]],
    ) -> list[BundleEntry]:
        entries = list(self._import_entries)
        if self._import_evidence_provider is not None:
            entries.extend(
                self._import_evidence_provider.collect(self._repos, changed_files_by_repo)
            )
        return [self._validated_external_entry(entry) for entry in entries]

    def _stage3_worker_hints(
        self,
        *,
        story_dir: Path,
        seeded_keys: set[tuple[str, str]],
        changed_files_by_repo: Mapping[str, Sequence[Path]],
        warnings: list[str],
    ) -> list[BundleEntry]:
        entries: list[BundleEntry] = []
        seen_hints: set[tuple[str, str]] = set()
        changed_keys = {
            (repo_id, rel_path.as_posix())
            for repo_id, paths in changed_files_by_repo.items()
            for rel_path in paths
        }
        for hint in self._worker_hint_paths(story_dir):
            repo, rel_path = self._resolve_hint_path(hint)
            key = (repo.repo_id, rel_path.as_posix())
            if key in changed_keys:
                warnings.append(
                    f"Self-reference WARNING: worker hint points to changed file "
                    f"{repo.repo_id}:{rel_path.as_posix()}"
                )
            if key in seeded_keys or key in seen_hints:
                continue
            entries.append(
                self._entry_from_file(
                    repo=repo,
                    rel_path=rel_path,
                    authority=AuthorityClass.WORKER_ASSERTION,
                    reason="Worker-suggested evidence hint",
                    confidence=None,
                )
            )
            seen_hints.add(key)
        return entries

    def _deduplicate(self, entries: list[BundleEntry]) -> list[BundleEntry]:
        selected: dict[tuple[str, str], BundleEntry] = {}
        for entry in entries:
            key = (entry.repo_id, entry.path.as_posix())
            current = selected.get(key)
            if current is None or entry.authority > current.authority:
                selected[key] = entry
        return sorted(selected.values(), key=lambda entry: entry.sort_key)

    def _enforce_size_limit(
        self,
        entries: list[BundleEntry],
        warnings: list[str],
    ) -> tuple[list[BundleEntry], bool]:
        included: list[BundleEntry] = []
        total_size = 0
        truncated = False
        for entry in sorted(entries, key=lambda item: item.sort_key):
            if total_size + entry.size <= self._bundle_size_limit:
                included.append(entry)
                total_size += entry.size
                continue
            truncated = True
            warnings.append(
                "Bundle truncated WARNING: "
                f"{entry.repo_id}:{entry.path.as_posix()} ({entry.authority.name}) "
                f"excluded ({entry.size} bytes)"
            )
        return included, truncated

    def _affected_repos(self) -> list[RepoContext]:
        repos = sorted(
            (repo for repo in self._repos.values() if repo.affected),
            key=lambda repo: repo.repo_id,
        )
        if not repos:
            msg = "at least one affected repo is required for evidence assembly"
            raise EvidenceAssemblyError(msg)
        return repos

    def _ensure_repo_path(self, repo: RepoContext) -> None:
        if not repo.repo_path.is_dir():
            msg = f"repo_path does not exist or is not a directory: {repo.repo_path}"
            raise EvidenceAssemblyError(msg)

    def _entry_from_file(
        self,
        *,
        repo: RepoContext,
        rel_path: Path,
        authority: AuthorityClass,
        reason: str,
        confidence: str | None,
    ) -> BundleEntry:
        abs_path = _safe_join(repo.repo_path, rel_path)
        if not abs_path.is_file():
            msg = f"bundle entry path does not exist: {repo.repo_id}:{rel_path.as_posix()}"
            raise EvidenceAssemblyError(msg)
        content = abs_path.read_text(encoding="utf-8", errors="replace")
        return BundleEntry(
            repo_id=repo.repo_id,
            path=rel_path,
            authority=authority,
            confidence=confidence,
            reason=reason,
            size=len(content.encode("utf-8")),
            content=content,
        )

    def _validated_external_entry(self, entry: BundleEntry) -> BundleEntry:
        repo = self._repo_for_id(entry.repo_id)
        abs_path = _safe_join(repo.repo_path, entry.path)
        if not abs_path.is_file():
            msg = f"bundle entry path does not exist: {entry.repo_id}:{entry.path.as_posix()}"
            raise EvidenceAssemblyError(msg)
        actual_size = len(abs_path.read_text(encoding="utf-8", errors="replace").encode("utf-8"))
        if actual_size != entry.size:
            msg = (
                f"bundle entry size mismatch for {entry.repo_id}:{entry.path.as_posix()}: "
                f"entry={entry.size}, actual={actual_size}"
            )
            raise EvidenceAssemblyError(msg)
        return entry

    def _resolve_repo_relative_path(self, repo: RepoContext, raw_path: str) -> Path:
        rel_path = Path(raw_path)
        if rel_path.is_absolute():
            try:
                rel_path = rel_path.resolve().relative_to(repo.repo_path.resolve())
            except ValueError as exc:
                msg = f"changed file is outside repo {repo.repo_id}: {raw_path}"
                raise EvidenceAssemblyError(msg) from exc
        if any(part == ".." for part in rel_path.parts):
            msg = f"changed file traverses outside repo {repo.repo_id}: {raw_path}"
            raise EvidenceAssemblyError(msg)
        return Path(rel_path.as_posix())

    def _module_neighbors(
        self,
        *,
        repo: RepoContext,
        changed_paths: Sequence[Path],
    ) -> list[BundleEntry]:
        changed_set = {path.as_posix() for path in changed_paths}
        candidates: dict[str, Path] = {}
        for changed_path in changed_paths:
            directory = changed_path.parent
            abs_dir = _safe_join(repo.repo_path, directory)
            if not abs_dir.is_dir():
                continue
            for child in abs_dir.iterdir():
                rel_child = Path(directory, child.name)
                if (
                    child.is_file()
                    and child.suffix.lower() in _NEIGHBOR_EXTENSIONS
                    and rel_child.as_posix() not in changed_set
                ):
                    candidates[rel_child.as_posix()] = rel_child
        return [
            self._entry_from_file(
                repo=repo,
                rel_path=path,
                authority=AuthorityClass.SECONDARY_CONTEXT,
                reason="Module neighbor of changed file",
                confidence=None,
            )
            for path in sorted(candidates.values(), key=lambda item: item.as_posix())
        ]

    def _config_entries(
        self,
        *,
        repo: RepoContext,
        changed_paths: Sequence[Path],
    ) -> list[BundleEntry]:
        candidates: dict[str, Path] = {}
        for changed_path in changed_paths:
            for directory in (Path("."), changed_path.parent):
                abs_dir = _safe_join(repo.repo_path, directory)
                if not abs_dir.is_dir():
                    continue
                for child in abs_dir.iterdir():
                    rel_child = Path(directory, child.name)
                    if child.is_file() and child.suffix.lower() in _CONFIG_EXTENSIONS:
                        candidates[rel_child.as_posix()] = rel_child
        return [
            self._entry_from_file(
                repo=repo,
                rel_path=path,
                authority=AuthorityClass.SECONDARY_CONTEXT,
                reason="Repository YAML/JSON configuration context",
                confidence=None,
            )
            for path in sorted(candidates.values(), key=lambda item: item.as_posix())
        ]

    def _normative_entries(self, story_dir: Path) -> list[BundleEntry]:
        story_repo = RepoContext(
            repo_id="_story",
            repo_path=story_dir,
            git_base_branch="n/a",
            role="story",
            affected=True,
        )
        story_spec = story_dir / "story.md"
        if not story_spec.is_file():
            msg = f"mandatory story spec is missing: {story_spec}"
            raise EvidenceAssemblyError(msg)
        entries = [
            self._entry_from_file(
                repo=story_repo,
                rel_path=Path("story.md"),
                authority=AuthorityClass.PRIMARY_NORMATIVE,
                reason="Story specification",
                confidence=None,
            )
        ]
        for optional_name in ("status.yaml", "remediation-r1.md", "remediation-r2.md"):
            optional_path = story_dir / optional_name
            if optional_path.is_file():
                entries.append(
                    self._entry_from_file(
                        repo=story_repo,
                        rel_path=Path(optional_name),
                        authority=AuthorityClass.PRIMARY_NORMATIVE,
                        reason="Story normative context",
                        confidence=None,
                    )
                )
        return entries

    def _worker_hint_paths(self, story_dir: Path) -> list[str]:
        hints: list[str] = []
        for filename in _WORKER_HINT_FILES:
            path = story_dir / filename
            if not path.is_file():
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                msg = f"invalid worker hint JSON in {path}: {exc}"
                raise EvidenceAssemblyError(msg) from exc
            hints.extend(_extract_path_strings(payload))
        return sorted(dict.fromkeys(hints))

    def _resolve_hint_path(self, hint: str) -> tuple[RepoContext, Path]:
        if ":" in hint:
            repo_id, raw_path = hint.split(":", 1)
            repo = self._repo_for_id(repo_id)
            rel_path = self._resolve_repo_relative_path(repo, raw_path)
            _safe_join(repo.repo_path, rel_path)
            return repo, rel_path
        matches: list[tuple[RepoContext, Path]] = []
        for repo in self._affected_repos():
            rel_path = self._resolve_repo_relative_path(repo, hint)
            if _safe_join(repo.repo_path, rel_path).is_file():
                matches.append((repo, rel_path))
        if len(matches) == 1:
            return matches[0]
        if not matches:
            msg = f"worker hint path does not exist in any affected repo: {hint}"
        else:
            msg = f"worker hint path is ambiguous across affected repos: {hint}"
        raise EvidenceAssemblyError(msg)

    def _repo_for_id(self, repo_id: str) -> RepoContext:
        repo = self._repos.get(repo_id)
        if repo is None:
            msg = f"unknown repo_id in evidence entry: {repo_id}"
            raise EvidenceAssemblyError(msg)
        return repo


def _entry_keys(entries: Iterable[BundleEntry]) -> set[tuple[str, str]]:
    return {(entry.repo_id, entry.path.as_posix()) for entry in entries}


def _safe_join(repo_path: Path, rel_path: Path) -> Path:
    candidate = (repo_path / rel_path).resolve()
    repo_root = repo_path.resolve()
    try:
        candidate.relative_to(repo_root)
    except ValueError as exc:
        msg = f"path escapes repo root: {rel_path.as_posix()}"
        raise EvidenceAssemblyError(msg) from exc
    return candidate


def _extract_path_strings(value: object, *, key_hint: str | None = None) -> list[str]:
    hints: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            normalized_key = str(key).lower()
            hints.extend(_extract_path_strings(item, key_hint=normalized_key))
        return hints
    if isinstance(value, list):
        for item in value:
            hints.extend(_extract_path_strings(item, key_hint=key_hint))
        return hints
    if isinstance(value, str) and key_hint in _PATH_KEYS and _looks_like_path(value):
        hints.append(value)
    return hints


def _looks_like_path(value: str) -> bool:
    path = value.strip()
    return bool(path) and not path.startswith("-") and ("/" in path or "\\" in path or "." in Path(path).name)


__all__ = [
    "BUNDLE_SIZE_LIMIT",
    "EvidenceAssembler",
    "EvidenceAssemblyError",
    "EvidenceAssemblyResult",
    "ImportEvidenceProvider",
]
