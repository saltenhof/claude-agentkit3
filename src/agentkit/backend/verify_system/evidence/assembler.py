"""Evidence assembly over edge-collected files and backend-local story docs."""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel, ConfigDict, Field

from agentkit.backend.core_types import HANDOVER_FILE, WORKER_MANIFEST_FILE
from agentkit.backend.verify_system.evidence.authority import AuthorityClass, BundleEntry
from agentkit.backend.verify_system.evidence.bundle_manifest import BundleManifest
from agentkit.backend.verify_system.structural.system_evidence import (
    ABSENT_CHANGE_EVIDENCE_PORT,
    ChangeEvidencePort,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence
    from datetime import datetime

    from agentkit.backend.core_types.verify_evidence import VerifyEvidenceFile
    from agentkit.backend.verify_system.evidence.repo_context import RepoContext
    from agentkit.backend.verify_system.structural.system_evidence import ChangeEvidence

BUNDLE_SIZE_LIMIT = 350 * 1024

_NEIGHBOR_EXTENSIONS = frozenset(
    {".cfg", ".css", ".ini", ".java", ".js", ".json", ".md", ".py", ".pyi", ".toml", ".ts", ".tsx", ".yaml", ".yml"}
)
_CONFIG_EXTENSIONS = frozenset({".json", ".toml", ".yaml", ".yml"})
_WORKER_HINT_FILES = (HANDOVER_FILE, WORKER_MANIFEST_FILE)
_PATH_KEYS = frozenset(
    {
        "file",
        "file_path",
        "file_paths",
        "files",
        "files_changed",
        "merge_paths",
        "path",
        "paths",
        "relevant_files",
        "tests_added",
    }
)


class ImportEvidenceProvider(Protocol):
    """Backend-pure Stage-2 import consolidation port."""

    def collect(
        self,
        repos: Mapping[str, RepoContext],
        changed_files_by_repo: Mapping[str, Sequence[Path]],
    ) -> Sequence[BundleEntry]:
        """Return import-derived entries from a pre-collected snapshot."""
        ...


class EvidenceAssemblyError(RuntimeError):
    """Raised when evidence assembly cannot produce a valid manifest."""


class EvidenceAssemblyResult(BaseModel):
    """Manifest plus deterministic review paths."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    manifest: BundleManifest
    merge_paths: tuple[str, ...] = Field(default_factory=tuple)


class EvidenceAssembler:
    """Assemble review evidence without target-worktree filesystem access."""

    def __init__(
        self,
        repos: Mapping[str, RepoContext],
        *,
        collected_files: Iterable[VerifyEvidenceFile] = (),
        change_evidence_port: ChangeEvidencePort | None = None,
        import_evidence_provider: ImportEvidenceProvider | None = None,
        import_entries: Iterable[BundleEntry] = (),
        collection_finding: str | None = None,
        bundle_size_limit: int = BUNDLE_SIZE_LIMIT,
    ) -> None:
        """Create an assembler over an immutable edge-reported file snapshot."""
        if not repos:
            raise EvidenceAssemblyError("at least one RepoContext is required")
        if bundle_size_limit <= 0:
            raise EvidenceAssemblyError("bundle_size_limit must be positive")
        for repo_id, repo in repos.items():
            if repo_id != repo.repo_id:
                raise EvidenceAssemblyError(
                    f"repo mapping key {repo_id!r} does not match RepoContext.repo_id {repo.repo_id!r}"
                )
        self._repos = dict(repos)
        self._files = _file_index(collected_files)
        self._change_evidence_port = change_evidence_port or ABSENT_CHANGE_EVIDENCE_PORT
        self._import_evidence_provider = import_evidence_provider
        self._import_entries = tuple(import_entries)
        self._collection_finding = collection_finding
        self._bundle_size_limit = bundle_size_limit

    @staticmethod
    def collect_change_inventory(
        repos: Mapping[str, RepoContext],
        change_evidence_port: ChangeEvidencePort,
    ) -> dict[str, ChangeEvidence]:
        """Use only the sanctioned AG3-147 change-evidence read surface."""
        return {
            repo.repo_id: change_evidence_port.collect(repo.repo_path)
            for repo in repos.values()
            if repo.affected
        }

    @staticmethod
    def collect_worker_hint_paths(story_dir: Path) -> tuple[str, ...]:
        """Read backend-local worker hint manifests before Stage-A commission."""
        hints: list[str] = []
        for filename in _WORKER_HINT_FILES:
            path = story_dir / filename
            if not path.is_file():
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise EvidenceAssemblyError(f"invalid worker hint JSON: {path}") from exc
            hints.extend(_extract_path_strings(payload))
        return tuple(sorted(dict.fromkeys(hints)))

    def assemble(
        self,
        *,
        story_dir: Path,
        evidence_epoch: datetime | str | None = None,
    ) -> EvidenceAssemblyResult:
        """Run the three assembly stages over reported content."""
        resolved_story_dir = story_dir.resolve()
        if not resolved_story_dir.is_dir():
            raise EvidenceAssemblyError(f"story_dir does not exist: {story_dir}")
        warnings = [self._collection_finding] if self._collection_finding else []
        changed_files_by_repo: dict[str, tuple[Path, ...]] = {}
        stage1 = self._stage1(resolved_story_dir, changed_files_by_repo, warnings)
        stage2 = self._stage2(changed_files_by_repo, warnings)
        stage3 = self._stage3(
            resolved_story_dir,
            changed_files_by_repo,
            _entry_keys([*stage1, *stage2]),
            warnings,
        )
        entries = self._deduplicate([*stage1, *stage2, *stage3])
        included, truncated = self._enforce_size_limit(entries, warnings)
        if not included:
            raise EvidenceAssemblyError("evidence assembly produced no entries")
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

    def _stage1(
        self,
        story_dir: Path,
        changed_files_by_repo: dict[str, tuple[Path, ...]],
        warnings: list[str],
    ) -> list[BundleEntry]:
        entries: list[BundleEntry] = []
        inventory = self.collect_change_inventory(
            self._repos, self._change_evidence_port
        )
        for repo in self._affected_repos():
            evidence = inventory[repo.repo_id]
            if not evidence.available:
                warnings.append(
                    f"EDGE_EVIDENCE_UNAVAILABLE: change inventory unavailable for {repo.repo_id}"
                )
                changed_files_by_repo[repo.repo_id] = ()
                continue
            paths = tuple(
                self._relative_path(repo, raw)
                for raw in sorted(set(evidence.changed_files))
            )
            changed_files_by_repo[repo.repo_id] = paths
            if not paths:
                warnings.append(
                    f"EDGE_EVIDENCE_UNAVAILABLE: changed-file inventory empty for {repo.repo_id}"
                )
            for path in paths:
                entry = self._entry_from_snapshot(
                    repo.repo_id,
                    path,
                    authority=AuthorityClass.PRIMARY_IMPLEMENTATION,
                    reason="Changed file from system change evidence",
                    confidence=None,
                )
                if entry is None:
                    warnings.append(
                        f"EDGE_EVIDENCE_UNAVAILABLE: missing changed file {repo.repo_id}:{path.as_posix()}"
                    )
                else:
                    entries.append(entry)
            entries.extend(self._module_neighbors(repo.repo_id, paths))
            entries.extend(self._config_entries(repo.repo_id, paths))
        entries.extend(self._normative_entries(story_dir))
        return entries

    def _stage2(
        self,
        changed_files_by_repo: Mapping[str, Sequence[Path]],
        warnings: list[str],
    ) -> list[BundleEntry]:
        entries = list(self._import_entries)
        if self._import_evidence_provider is not None:
            entries.extend(
                self._import_evidence_provider.collect(
                    self._repos, changed_files_by_repo
                )
            )
        validated: list[BundleEntry] = []
        for entry in entries:
            snapshot = self._files.get((entry.repo_id, entry.path.as_posix()))
            if snapshot is None:
                warnings.append(
                    f"EDGE_EVIDENCE_UNAVAILABLE: missing import file {entry.repo_id}:{entry.path.as_posix()}"
                )
                continue
            if snapshot.size != entry.size or snapshot.content != entry.content:
                raise EvidenceAssemblyError(
                    f"import entry size mismatch or content mismatch for {entry.repo_id}:{entry.path.as_posix()}"
                )
            validated.append(entry)
        return validated

    def _stage3(
        self,
        story_dir: Path,
        changed_files_by_repo: Mapping[str, Sequence[Path]],
        seeded_keys: set[tuple[str, str]],
        warnings: list[str],
    ) -> list[BundleEntry]:
        changed = {
            (repo_id, path.as_posix())
            for repo_id, paths in changed_files_by_repo.items()
            for path in paths
        }
        entries: list[BundleEntry] = []
        for hint in self._worker_hint_paths(story_dir):
            match = self._resolve_hint(hint)
            if match is None:
                warnings.append(f"EDGE_EVIDENCE_UNAVAILABLE: worker hint unresolved: {hint}")
                continue
            repo_id, path = match
            key = (repo_id, path.as_posix())
            if key in changed:
                warnings.append(
                    f"Self-reference WARNING: worker hint points to changed file {repo_id}:{path.as_posix()}"
                )
            if key in seeded_keys:
                continue
            entry = self._entry_from_snapshot(
                repo_id,
                path,
                authority=AuthorityClass.WORKER_ASSERTION,
                reason="Worker-provided context hint",
                confidence=None,
            )
            if entry is not None:
                entries.append(entry)
        return entries

    def _entry_from_snapshot(
        self,
        repo_id: str,
        path: Path,
        *,
        authority: AuthorityClass,
        reason: str,
        confidence: str | None,
    ) -> BundleEntry | None:
        file = self._files.get((repo_id, path.as_posix()))
        if file is None:
            return None
        return BundleEntry(
            repo_id=repo_id,
            path=path,
            authority=authority,
            confidence=confidence,
            reason=reason,
            size=file.size,
            content=file.content,
        )

    def _module_neighbors(
        self, repo_id: str, changed_paths: Sequence[Path]
    ) -> list[BundleEntry]:
        changed = {path.as_posix() for path in changed_paths}
        directories = {path.parent.as_posix() for path in changed_paths}
        candidates = sorted(
            path
            for candidate_repo, path in self._files
            if candidate_repo == repo_id
            and PurePosixPath(path).parent.as_posix() in directories
            and PurePosixPath(path).suffix.lower() in _NEIGHBOR_EXTENSIONS
            and path not in changed
        )
        return self._entries_for_paths(
            repo_id, candidates, "Module neighbor of changed file"
        )

    def _config_entries(
        self, repo_id: str, changed_paths: Sequence[Path]
    ) -> list[BundleEntry]:
        directories = {".", *(path.parent.as_posix() for path in changed_paths)}
        candidates = sorted(
            path
            for candidate_repo, path in self._files
            if candidate_repo == repo_id
            and PurePosixPath(path).parent.as_posix() in directories
            and PurePosixPath(path).suffix.lower() in _CONFIG_EXTENSIONS
        )
        return self._entries_for_paths(
            repo_id, candidates, "Repository configuration context"
        )

    def _entries_for_paths(
        self, repo_id: str, paths: Sequence[str], reason: str
    ) -> list[BundleEntry]:
        return [
            entry
            for raw in paths
            if (
                entry := self._entry_from_snapshot(
                    repo_id,
                    Path(raw),
                    authority=AuthorityClass.SECONDARY_CONTEXT,
                    reason=reason,
                    confidence=None,
                )
            )
            is not None
        ]

    def _normative_entries(self, story_dir: Path) -> list[BundleEntry]:
        names = ["story.md", "status.yaml", "remediation-r1.md", "remediation-r2.md"]
        entries: list[BundleEntry] = []
        for name in names:
            path = story_dir / name
            if not path.is_file():
                if name == "story.md":
                    raise EvidenceAssemblyError(f"mandatory story spec is missing: {path}")
                continue
            content = path.read_text(encoding="utf-8", errors="replace")
            entries.append(
                BundleEntry(
                    repo_id="_story",
                    path=Path(name),
                    authority=AuthorityClass.PRIMARY_NORMATIVE,
                    confidence=None,
                    reason="Story normative context",
                    size=len(content.encode("utf-8")),
                    content=content,
                )
            )
        return entries

    def _worker_hint_paths(self, story_dir: Path) -> list[str]:
        return list(self.collect_worker_hint_paths(story_dir))

    def _resolve_hint(self, hint: str) -> tuple[str, Path] | None:
        if ":" in hint:
            repo_id, raw_path = hint.split(":", 1)
            path = self._relative_path(self._repo_for_id(repo_id), raw_path)
            return (repo_id, path) if (repo_id, path.as_posix()) in self._files else None
        path = Path(_relative_path_string(hint))
        matches = [
            (repo.repo_id, path)
            for repo in self._affected_repos()
            if (repo.repo_id, path.as_posix()) in self._files
        ]
        return matches[0] if len(matches) == 1 else None

    def _relative_path(self, repo: RepoContext, raw_path: str) -> Path:
        del repo
        return Path(_relative_path_string(raw_path))

    def _affected_repos(self) -> list[RepoContext]:
        repos = sorted(
            (repo for repo in self._repos.values() if repo.affected),
            key=lambda repo: repo.repo_id,
        )
        if not repos:
            raise EvidenceAssemblyError("at least one affected repo is required")
        return repos

    def _repo_for_id(self, repo_id: str) -> RepoContext:
        repo = self._repos.get(repo_id)
        if repo is None:
            raise EvidenceAssemblyError(f"unknown repo_id: {repo_id}")
        return repo

    @staticmethod
    def _deduplicate(entries: Sequence[BundleEntry]) -> list[BundleEntry]:
        selected: dict[tuple[str, str], BundleEntry] = {}
        for entry in entries:
            key = (entry.repo_id, entry.path.as_posix())
            current = selected.get(key)
            if current is None or entry.authority > current.authority:
                selected[key] = entry
        return sorted(selected.values(), key=lambda entry: entry.sort_key)

    def _enforce_size_limit(
        self, entries: Sequence[BundleEntry], warnings: list[str]
    ) -> tuple[list[BundleEntry], bool]:
        included: list[BundleEntry] = []
        total = 0
        truncated = False
        for entry in entries:
            if total + entry.size <= self._bundle_size_limit:
                included.append(entry)
                total += entry.size
                continue
            truncated = True
            warnings.append(
                f"Bundle truncated WARNING: {entry.repo_id}:{entry.path.as_posix()} excluded ({entry.size} bytes)"
            )
        return included, truncated


def _file_index(
    files: Iterable[VerifyEvidenceFile],
) -> dict[tuple[str, str], VerifyEvidenceFile]:
    result: dict[tuple[str, str], VerifyEvidenceFile] = {}
    for file in files:
        key = (file.repo_id, file.path)
        existing = result.get(key)
        if existing is not None and existing.sha256 != file.sha256:
            raise EvidenceAssemblyError(
                f"conflicting edge file observations for {file.repo_id}:{file.path}"
            )
        result[key] = file
    return result


def _relative_path_string(raw_path: str) -> str:
    path = PurePosixPath(raw_path.replace("\\", "/"))
    if (
        path.is_absolute()
        or Path(raw_path).is_absolute()
        or ".." in path.parts
        or not raw_path.strip()
    ):
        raise EvidenceAssemblyError(
            f"path is outside repo or traverses outside repo: {raw_path}"
        )
    return path.as_posix()


def _entry_keys(entries: Iterable[BundleEntry]) -> set[tuple[str, str]]:
    return {(entry.repo_id, entry.path.as_posix()) for entry in entries}


def _extract_path_strings(value: object, *, key_hint: str | None = None) -> list[str]:
    hints: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            hints.extend(_extract_path_strings(item, key_hint=str(key).lower()))
    elif isinstance(value, list):
        for item in value:
            hints.extend(_extract_path_strings(item, key_hint=key_hint))
    elif isinstance(value, str) and key_hint in _PATH_KEYS and _looks_like_path(value):
        hints.append(value)
    return hints


def _looks_like_path(value: str) -> bool:
    path = value.strip()
    return bool(path) and not path.startswith("-") and (
        "/" in path or "\\" in path or "." in Path(path).name
    )


__all__ = [
    "BUNDLE_SIZE_LIMIT",
    "EvidenceAssembler",
    "EvidenceAssemblyError",
    "EvidenceAssemblyResult",
    "ImportEvidenceProvider",
]
