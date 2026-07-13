"""Backend-pure import consolidation over edge-collected file observations."""

from __future__ import annotations

import json
import posixpath
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from agentkit.backend.verify_system.evidence.authority import AuthorityClass, BundleEntry

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from agentkit.backend.core_types.verify_evidence import VerifyEvidenceFile
    from agentkit.backend.verify_system.evidence.repo_context import RepoContext

PY_IMPORT = re.compile(r"^(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))", re.MULTILINE)
TS_STATIC_IMPORT_NAMED = re.compile(
    r"""import\s+(?:type\s+)?\{(?P<named>[^}]*)\}\s+from\s+['"](?P<path_a>[^'"]+)['"]""",
    re.MULTILINE,
)
TS_STATIC_IMPORT_DEFAULT = re.compile(
    r"""import\s+(?:type\s+)?[\w*]+(?:\s*,\s*\{(?P<named2>[^}]*)\})?\s+from\s+['"](?P<path_b>[^'"]+)['"]""",
    re.MULTILINE,
)
TS_SIDE_EFFECT = re.compile(r"""import\s+['"]([^'"]+)['"]""", re.MULTILINE)
TS_REEXPORT = re.compile(r"""export\s+(?:\*|\{[^}]*\})\s+from\s+['"]([^'"]+)['"]""", re.MULTILINE)
TS_REQUIRE = re.compile(r"""(?:import\s+\w+\s*=\s*)?require\s*\(\s*['"]([^'"]+)['"]\s*\)""", re.MULTILINE)
TS_DYNAMIC = re.compile(r"""import\s*\(\s*['"]([^'"]+)['"]\s*\)""", re.MULTILINE)
JAVA_IMPORT = re.compile(r"^import\s+(?:static\s+)?([\w.]+(?:\.\*)?)\s*;", re.MULTILINE | re.ASCII)
JAVA_PACKAGE = re.compile(r"^package\s+([\w.]+)\s*;", re.MULTILINE | re.ASCII)
JAVA_TYPE_REFERENCE = re.compile(
    r"\b(?:extends|implements|new|private|protected|public|final)\s+([A-Z][\w]*)\b",
    re.ASCII,
)
JAVA_CLASS_DECL = re.compile(
    r"\b(?:class|interface|enum|record)\s+([A-Z][\w]*)\b", re.ASCII
)
SPRING_SCAN = re.compile(
    r"@(?:SpringBootApplication|ComponentScan|Import|EntityScan|EnableJpaRepositories)\s*\(([^)]*)\)",
    re.MULTILINE | re.DOTALL,
)
SPRING_MARKER = re.compile(r"@SpringBootApplication\b")
SPRING_PACKAGE_LITERAL = re.compile(
    r'"([\w.]+)"|basePackages\s*=\s*\{([^}]*)\}|scanBasePackages\s*=\s*\{([^}]*)\}'
)

TS_EXTENSIONS = (".ts", ".tsx", ".js", ".jsx", ".d.ts")
TS_INDEXES = ("index.ts", "index.tsx", "index.js", "index.jsx", "index.d.ts")


class ConfidenceLabel(StrEnum):
    """Import-resolution confidence labels ordered by evidence strength."""

    RESOLVED_IMPORT = "RESOLVED_IMPORT"
    RESOLVED_ALIAS = "RESOLVED_ALIAS"
    BARREL_CONTEXT = "BARREL_CONTEXT"
    SAME_PACKAGE_HEURISTIC = "SAME_PACKAGE_HEURISTIC"
    SPRING_SCAN_HEURISTIC = "SPRING_SCAN_HEURISTIC"
    UNRESOLVED_DYNAMIC = "UNRESOLVED_DYNAMIC"


CONFIDENCE_PRIORITY: dict[ConfidenceLabel, int] = {
    ConfidenceLabel.RESOLVED_IMPORT: 5,
    ConfidenceLabel.RESOLVED_ALIAS: 4,
    ConfidenceLabel.BARREL_CONTEXT: 3,
    ConfidenceLabel.SAME_PACKAGE_HEURISTIC: 2,
    ConfidenceLabel.SPRING_SCAN_HEURISTIC: 1,
    ConfidenceLabel.UNRESOLVED_DYNAMIC: 0,
}


@dataclass(frozen=True)
class ResolvedImport:
    """One deterministic import decision from the reported snapshot."""

    source_repo_id: str
    source_file: Path
    target_repo_id: str | None
    target_file: Path | None
    import_statement: str
    confidence: ConfidenceLabel


class ImportResolver:
    """Resolve Python, TypeScript/JavaScript, and Java imports without I/O."""

    def __init__(self, files: Iterable[VerifyEvidenceFile]) -> None:
        """Create the resolver from content-bound edge observations."""
        self._files = {(item.repo_id, item.path): item for item in files}
        self._repo_ids = tuple(sorted({item.repo_id for item in files}))
        self._java_packages: dict[str, list[tuple[str, str]]] | None = None

    def resolve(self, repo_id: str, source_file: Path) -> list[ResolvedImport]:
        """Resolve imports for one repo-relative source file."""
        path = _normal_path(source_file.as_posix())
        source = self._files.get((repo_id, path))
        if source is None:
            return []
        suffix = PurePosixPath(path).suffix.lower()
        if suffix == ".py":
            return self._resolve_python(repo_id, path, source.content)
        if suffix in {".ts", ".tsx", ".js", ".jsx"}:
            return self._resolve_typescript(repo_id, path, source.content)
        if suffix == ".java":
            return self._resolve_java(repo_id, path, source.content)
        return []

    def collect(
        self,
        repos: Mapping[str, RepoContext],
        changed_files_by_repo: Mapping[str, Sequence[Path]],
    ) -> Sequence[BundleEntry]:
        """Return unique resolved imports as secondary-context entries."""
        del repos
        entries: dict[tuple[str, str], BundleEntry] = {}
        for repo_id, paths in changed_files_by_repo.items():
            for path in paths:
                for result in self.resolve(repo_id, path):
                    candidate = self._entry_for_result(result)
                    if candidate is not None:
                        _retain_stronger_entry(entries, candidate)
        return tuple(entries[key] for key in sorted(entries))

    def _entry_for_result(self, result: ResolvedImport) -> BundleEntry | None:
        if result.target_repo_id is None or result.target_file is None:
            return None
        key = (result.target_repo_id, result.target_file.as_posix())
        file = self._files.get(key)
        if file is None:
            return None
        return BundleEntry(
            repo_id=key[0],
            path=result.target_file,
            authority=AuthorityClass.SECONDARY_CONTEXT,
            confidence=result.confidence.value,
            reason="Resolved import from Stage-2 import resolver",
            size=file.size,
            content=file.content,
        )

    @classmethod
    def from_collected_files(
        cls, files: Iterable[VerifyEvidenceFile]
    ) -> ImportResolver:
        """Create a resolver from the edge-reported snapshot."""
        return cls(files)

    def _resolve_python(
        self, repo_id: str, path: str, content: str
    ) -> list[ResolvedImport]:
        results: list[ResolvedImport] = []
        for match in PY_IMPORT.finditer(content):
            module = match.group(1) or match.group(2)
            if module is None:
                continue
            leading_dots = len(module) - len(module.lstrip("."))
            module_path = module.lstrip(".").replace(".", "/")
            raw_candidates = (f"{module_path}.py", f"{module_path}/__init__.py")
            if leading_dots:
                base = PurePosixPath(path).parent
                for _ in range(leading_dots - 1):
                    base = base.parent
                candidates = [
                    (repo_id, _normal_path((base / candidate).as_posix()))
                    for candidate in raw_candidates
                    if (repo_id, _normal_path((base / candidate).as_posix()))
                    in self._files
                ]
            else:
                candidates = self._ordered_candidates(repo_id, raw_candidates)
            results.extend(
                self._results(repo_id, path, match.group(0), candidates)
            )
        return results

    def _resolve_typescript(
        self, repo_id: str, path: str, content: str
    ) -> list[ResolvedImport]:
        results: list[ResolvedImport] = []
        for pattern, path_group, named_group in (
            (TS_STATIC_IMPORT_NAMED, "path_a", "named"),
            (TS_STATIC_IMPORT_DEFAULT, "path_b", "named2"),
        ):
            for match in pattern.finditer(content):
                named = _first_named_import(match.groupdict().get(named_group))
                results.extend(
                    self._ts_results(repo_id, path, match.group(path_group), match.group(0), named)
                )
        for pattern in (TS_SIDE_EFFECT, TS_REEXPORT, TS_REQUIRE):
            for match in pattern.finditer(content):
                results.extend(
                    self._ts_results(repo_id, path, match.group(1), match.group(0), None)
                )
        results.extend(
            ResolvedImport(
                repo_id,
                Path(path),
                None,
                None,
                match.group(0),
                ConfidenceLabel.UNRESOLVED_DYNAMIC,
            )
            for match in TS_DYNAMIC.finditer(content)
        )
        return results

    def _ts_results(
        self,
        repo_id: str,
        source: str,
        specifier: str,
        statement: str,
        named: str | None,
    ) -> list[ResolvedImport]:
        candidates, alias = self._ts_candidates_for_specifier(repo_id, source, specifier)
        results = self._results(
            repo_id,
            source,
            statement,
            candidates,
            confidence=ConfidenceLabel.RESOLVED_ALIAS if alias else ConfidenceLabel.RESOLVED_IMPORT,
        )
        if len(results) != 1 or results[0].target_file is None:
            return results
        target = results[0]
        target_file = target.target_file
        target_repo = target.target_repo_id
        if (
            target_file is None
            or target_repo is None
            or not target_file.name.startswith("index.")
        ):
            return results
        barrel = self._files.get((target_repo, target_file.as_posix()))
        if barrel is None:
            return results
        resolved: list[ResolvedImport] = []
        for match in TS_REEXPORT.finditer(barrel.content):
            if named is not None and named not in match.group(0) and "*" not in match.group(0):
                continue
            nested, _ = self._ts_candidates_for_specifier(
                target_repo, target_file.as_posix(), match.group(1)
            )
            resolved.extend(
                ResolvedImport(
                    repo_id,
                    Path(source),
                    nested_repo,
                    Path(nested_path),
                    statement,
                    ConfidenceLabel.BARREL_CONTEXT,
                )
                for nested_repo, nested_path in nested
            )
        return _unique_results(resolved) or results

    def _ts_candidates_for_specifier(
        self, repo_id: str, source: str, specifier: str
    ) -> tuple[list[tuple[str, str]], bool]:
        if specifier.startswith(("./", "../")):
            base = _join(PurePosixPath(source).parent.as_posix(), specifier)
            return self._ts_file_candidates(repo_id, base), False
        config = self._nearest_tsconfig(repo_id, source)
        if config is None:
            return [], False
        config_path, data = config
        options = data.get("compilerOptions")
        if not isinstance(options, dict) or not isinstance(options.get("paths"), dict):
            return [], False
        base_url = str(options.get("baseUrl") or ".")
        root = _join(PurePosixPath(config_path).parent.as_posix(), base_url)
        candidates: list[tuple[str, str]] = []
        for alias, targets in options["paths"].items():
            suffix = _alias_suffix(str(alias), specifier)
            if suffix is None or not isinstance(targets, list):
                continue
            for target in targets:
                if isinstance(target, str):
                    candidates.extend(
                        self._ts_file_candidates(
                            repo_id, _join(root, target.replace("*", suffix))
                        )
                    )
        return _unique_candidates(candidates), bool(candidates)

    def _nearest_tsconfig(
        self, repo_id: str, source: str
    ) -> tuple[str, dict[str, object]] | None:
        current = PurePosixPath(source).parent
        for directory in (current, *current.parents):
            for name in ("tsconfig.json", "jsconfig.json"):
                path = _join(directory.as_posix(), name)
                file = self._files.get((repo_id, path))
                if file is None:
                    continue
                try:
                    data = json.loads(file.content)
                except json.JSONDecodeError:
                    return None
                return (path, data) if isinstance(data, dict) else None
        return None

    def _ts_file_candidates(self, repo_id: str, base: str) -> list[tuple[str, str]]:
        paths = [base, *(f"{base}{ext}" for ext in TS_EXTENSIONS), *(f"{base}/{name}" for name in TS_INDEXES)]
        return [(repo_id, path) for path in paths if (repo_id, path) in self._files]

    def _resolve_java(
        self, repo_id: str, path: str, content: str
    ) -> list[ResolvedImport]:
        results: list[ResolvedImport] = []
        for match in JAVA_IMPORT.finditer(content):
            statement = match.group(1)
            candidates = self._java_import_candidates(statement)
            results.extend(self._results(repo_id, path, match.group(0), candidates))
        package = _java_package(content)
        results.extend(self._same_package_results(repo_id, path, content, package))
        packages = set(_spring_packages(content))
        if package is not None and SPRING_MARKER.search(content):
            packages.add(package)
        results.extend(self._spring_results(repo_id, path, packages))
        return _unique_results(results)

    def _same_package_results(
        self, repo_id: str, path: str, content: str, package: str | None
    ) -> list[ResolvedImport]:
        if package is None:
            return []
        references = set(JAVA_TYPE_REFERENCE.findall(content)) - set(
            JAVA_CLASS_DECL.findall(content)
        )
        return [
            ResolvedImport(
                repo_id,
                Path(path),
                candidate_repo,
                Path(candidate_path),
                f"same-package:{PurePosixPath(candidate_path).stem}",
                ConfidenceLabel.SAME_PACKAGE_HEURISTIC,
            )
            for candidate_repo, candidate_path in self._java_index().get(package, [])
            if candidate_path != path
            and PurePosixPath(candidate_path).stem in references
        ]

    def _spring_results(
        self, repo_id: str, path: str, packages: set[str]
    ) -> list[ResolvedImport]:
        return [
            ResolvedImport(
                repo_id,
                Path(path),
                candidate_repo,
                Path(candidate_path),
                "spring-scan",
                ConfidenceLabel.SPRING_SCAN_HEURISTIC,
            )
            for scan_package in packages
            for candidate_repo, candidate_path in self._java_index().get(
                scan_package, []
            )
            if candidate_path != path
        ]

    def _java_index(self) -> dict[str, list[tuple[str, str]]]:
        if self._java_packages is None:
            index: dict[str, list[tuple[str, str]]] = {}
            for (repo_id, path), file in self._files.items():
                if PurePosixPath(path).suffix != ".java":
                    continue
                package = _java_package(file.content)
                if package is not None:
                    index.setdefault(package, []).append((repo_id, path))
            self._java_packages = index
        return self._java_packages

    def _java_import_candidates(self, statement: str) -> list[tuple[str, str]]:
        if statement.endswith(".*"):
            return self._java_index().get(statement[:-2], [])
        parts = statement.split(".")
        package, type_name = ".".join(parts[:-1]), parts[-1]
        candidates = [
            item for item in self._java_index().get(package, [])
            if PurePosixPath(item[1]).stem == type_name
        ]
        if candidates:
            return candidates
        static_package = ".".join(parts[:-2])
        static_type = parts[-2] if len(parts) > 1 else type_name
        return [
            item for item in self._java_index().get(static_package, [])
            if PurePosixPath(item[1]).stem == static_type
        ]

    def _ordered_candidates(
        self, preferred_repo: str, paths: Sequence[str]
    ) -> list[tuple[str, str]]:
        repos = (preferred_repo, *(repo for repo in self._repo_ids if repo != preferred_repo))
        return [
            (repo_id, path)
            for repo_id in repos
            for path in paths
            if (repo_id, path) in self._files
        ]

    @staticmethod
    def _results(
        source_repo: str,
        source: str,
        statement: str,
        candidates: Sequence[tuple[str, str]],
        *,
        confidence: ConfidenceLabel = ConfidenceLabel.RESOLVED_IMPORT,
    ) -> list[ResolvedImport]:
        unique = _unique_candidates(candidates)
        if len(unique) == 1:
            target_repo, target = unique[0]
            return [ResolvedImport(source_repo, Path(source), target_repo, Path(target), statement, confidence)]
        if len(unique) > 1:
            return [ResolvedImport(source_repo, Path(source), None, None, statement, ConfidenceLabel.UNRESOLVED_DYNAMIC)]
        return []


def _normal_path(path: str) -> str:
    normalized = posixpath.normpath(path.replace("\\", "/"))
    if normalized == ".." or normalized.startswith("../") or normalized.startswith("/"):
        raise ValueError(f"snapshot path escapes repository: {path}")
    return normalized.removeprefix("./")


def _join(root: str, child: str) -> str:
    return _normal_path(posixpath.join(root, child))


def _unique_candidates(items: Iterable[tuple[str, str]]) -> list[tuple[str, str]]:
    return sorted(set(items))


def _retain_stronger_entry(
    entries: dict[tuple[str, str], BundleEntry], candidate: BundleEntry
) -> None:
    key = (candidate.repo_id, candidate.path.as_posix())
    current = entries.get(key)
    if current is None or _confidence_rank_value(
        candidate.confidence
    ) > _confidence_rank_value(current.confidence):
        entries[key] = candidate


def _unique_results(results: Iterable[ResolvedImport]) -> list[ResolvedImport]:
    selected: dict[tuple[str, str | None, str | None], ResolvedImport] = {}
    for result in results:
        key = (
            result.source_file.as_posix(),
            result.target_repo_id,
            result.target_file.as_posix() if result.target_file else None,
        )
        current = selected.get(key)
        if current is None or CONFIDENCE_PRIORITY[result.confidence] > CONFIDENCE_PRIORITY[current.confidence]:
            selected[key] = result
    return list(selected.values())


def _first_named_import(raw: str | None) -> str | None:
    if raw is None:
        return None
    first = raw.split(",", 1)[0].strip()
    return first.split(" as ", 1)[0].strip() or None


def _alias_suffix(alias: str, specifier: str) -> str | None:
    if "*" not in alias:
        return "" if alias == specifier else None
    prefix, suffix = alias.split("*", 1)
    if specifier.startswith(prefix) and specifier.endswith(suffix):
        return specifier[len(prefix) : len(specifier) - len(suffix) if suffix else None]
    return None


def _java_package(content: str) -> str | None:
    match = JAVA_PACKAGE.search(content)
    return match.group(1) if match else None


def _spring_packages(content: str) -> list[str]:
    packages: list[str] = []
    for scan_match in SPRING_SCAN.finditer(content):
        for match in SPRING_PACKAGE_LITERAL.finditer(scan_match.group(1)):
            literal = match.group(1)
            grouped = match.group(2) or match.group(3)
            if literal:
                packages.append(literal)
            if grouped:
                packages.extend(
                    item.strip().strip('"')
                    for item in grouped.split(",")
                    if item.strip()
                )
    return packages


def _confidence_rank_value(confidence: str | None) -> int:
    try:
        return CONFIDENCE_PRIORITY[ConfidenceLabel(confidence)] if confidence else -1
    except ValueError:
        return -1


__all__ = [
    "CONFIDENCE_PRIORITY",
    "ConfidenceLabel",
    "ImportResolver",
    "ResolvedImport",
]
