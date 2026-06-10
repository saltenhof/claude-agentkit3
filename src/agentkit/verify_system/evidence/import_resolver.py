"""Language-specific import resolution for Stage-2 evidence enrichment."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from agentkit.verify_system.evidence.authority import AuthorityClass, BundleEntry

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from agentkit.verify_system.evidence.repo_context import RepoContext


PY_IMPORT = re.compile(r"^(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))", re.MULTILINE)
# Two simpler patterns cover the two TS static-import forms (split to avoid S5843):
# Form A: import [type] { named } from 'path'
TS_STATIC_IMPORT_NAMED = re.compile(
    r"""import\s+(?:type\s+)?\{(?P<named>[^}]*)\}\s+from\s+['"](?P<path_a>[^'"]+)['"]""",
    re.MULTILINE,
)
# Form B: import [type] default[, { named2 }] from 'path'
TS_STATIC_IMPORT_DEFAULT = re.compile(
    r"""import\s+(?:type\s+)?[\w*]+(?:\s*,\s*\{(?P<named2>[^}]*)\})?\s+from\s+['"](?P<path_b>[^'"]+)['"]""",
    re.MULTILINE,
)
TS_SIDE_EFFECT = re.compile(r"""import\s+['"]([^'"]+)['"]""", re.MULTILINE)
TS_REEXPORT = re.compile(r"""export\s+(?:\*|\{[^}]*\})\s+from\s+['"]([^'"]+)['"]""", re.MULTILINE)
TS_REQUIRE = re.compile(r"""(?:import\s+\w+\s*=\s*)?require\s*\(\s*['"]([^'"]+)['"]\s*\)""", re.MULTILINE)
TS_DYNAMIC = re.compile(r"""import\s*\(\s*['"]([^'"]+)['"]\s*\)""", re.MULTILINE)
JAVA_IMPORT = re.compile(r"^import\s+(?:static\s+)?([\w.]+(?:\.\*)?)\s*;", re.MULTILINE)
JAVA_PACKAGE = re.compile(r"^package\s+([\w.]+)\s*;", re.MULTILINE)
JAVA_TYPE_REFERENCE = re.compile(
    r"\b(?:extends|implements|new|private|protected|public|final)\s+([A-Z]\w*)\b"
)
JAVA_CLASS_DECL = re.compile(r"\b(?:class|interface|enum|record)\s+([A-Z]\w*)\b")
SPRING_SCAN = re.compile(
    r"@(?:SpringBootApplication|ComponentScan|Import|EntityScan|EnableJpaRepositories)\s*\(([^)]*)\)",
    re.MULTILINE | re.DOTALL,
)
SPRING_MARKER = re.compile(r"@SpringBootApplication\b")
SPRING_PACKAGE_LITERAL = re.compile(r'"([\w.]+)"|basePackages\s*=\s*\{([^}]*)\}|scanBasePackages\s*=\s*\{([^}]*)\}')

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
    """One import resolver result.

    ``target_file`` is ``None`` for intentionally unresolved dynamic or
    ambiguous imports. Such results are diagnostics, not bundle entries.
    """

    source_file: Path
    target_file: Path | None
    import_statement: str
    confidence: ConfidenceLabel


@dataclass(frozen=True)
class _RepoFile:
    repo_id: str
    repo_root: Path
    rel_path: Path
    abs_path: Path


class ImportResolver:
    """Resolve Python, TypeScript/JavaScript and Java imports across repos."""

    LANGUAGE_MAP: dict[str, str] = {
        ".py": "_resolve_python",
        ".ts": "_resolve_typescript",
        ".tsx": "_resolve_typescript",
        ".js": "_resolve_typescript",
        ".jsx": "_resolve_typescript",
        ".java": "_resolve_java",
    }

    def __init__(self, repos: Mapping[str, Path]) -> None:
        """Create an import resolver for repository roots keyed by repo id."""
        self._repos = {repo_id: repo_path.resolve() for repo_id, repo_path in repos.items()}
        self._tsconfig_cache: dict[Path, dict[str, Any] | None] = {}
        self._java_package_index: dict[str, list[Path]] | None = None

    def resolve(self, source_file: Path) -> list[ResolvedImport]:
        """Resolve imports for ``source_file`` based on its extension."""
        handler_name = self.LANGUAGE_MAP.get(source_file.suffix.lower())
        if handler_name is None:
            return []
        handler = cast("Callable[[Path], list[ResolvedImport]]", getattr(self, handler_name))
        return handler(source_file.resolve())

    def collect(
        self,
        repos: Mapping[str, RepoContext],
        changed_files_by_repo: Mapping[str, Sequence[Path]],
    ) -> Sequence[BundleEntry]:
        """Return resolved imports as ``SECONDARY_CONTEXT`` bundle entries."""
        del repos
        entries: dict[tuple[str, str], BundleEntry] = {}
        for repo_id, changed_paths in changed_files_by_repo.items():
            repo_root = self._repos[repo_id]
            for rel_path in changed_paths:
                for result in self.resolve(repo_root / rel_path):
                    repo_file = self._repo_file_for_result(result)
                    if repo_file is None:
                        continue
                    key = (repo_file.repo_id, repo_file.rel_path.as_posix())
                    current = entries.get(key)
                    if current is None or _confidence_rank(result.confidence) > _confidence_rank_value(current.confidence):
                        entries[key] = self._bundle_entry(repo_file, result.confidence)
        return tuple(entries[key] for key in sorted(entries))

    @classmethod
    def from_repo_contexts(cls, repos: Mapping[str, RepoContext]) -> ImportResolver:
        """Create a resolver from AG3-061 ``RepoContext`` values."""
        return cls({repo_id: repo.repo_path for repo_id, repo in repos.items()})

    def _resolve_python(self, source: Path) -> list[ResolvedImport]:
        results: list[ResolvedImport] = []
        content = source.read_text(encoding="utf-8", errors="replace")
        for match in PY_IMPORT.finditer(content):
            module_path = match.group(1) or match.group(2)
            if module_path is None:
                continue
            candidates = self._find_python_candidates(module_path, source)
            results.extend(self._result_for_candidates(source, match.group(0), candidates))
        return results

    def _find_python_candidates(self, module_path: str, source: Path) -> list[Path]:
        parts = module_path.split(".")
        source_repo_id = self._repo_id_for_path(source)
        candidates: list[Path] = []
        for repo_id, repo_root in self._repo_roots_for_source(source_repo_id):
            del repo_id
            module_file = repo_root / Path(*parts).with_suffix(".py")
            package_file = repo_root / Path(*parts) / "__init__.py"
            candidates.extend(path for path in (module_file, package_file) if path.is_file())
        return _unique_paths(candidates)

    def _resolve_typescript(self, source: Path) -> list[ResolvedImport]:
        content = source.read_text(encoding="utf-8", errors="replace")
        results: list[ResolvedImport] = []
        results.extend(self._resolve_ts_static_patterns(source, content))
        for pattern in (TS_SIDE_EFFECT, TS_REEXPORT, TS_REQUIRE):
            results.extend(self._resolve_ts_pattern(source, content, pattern, None))
        for match in TS_DYNAMIC.finditer(content):
            results.append(
                ResolvedImport(source, None, match.group(0), ConfidenceLabel.UNRESOLVED_DYNAMIC)
            )
        return results

    def _resolve_ts_static_patterns(self, source: Path, content: str) -> list[ResolvedImport]:
        results: list[ResolvedImport] = []
        for match in TS_STATIC_IMPORT_NAMED.finditer(content):
            named_import = _first_named_import(match.groupdict().get("named"))
            results.extend(self._ts_results_for_specifier(source, match.group("path_a"), match.group(0), named_import))
        for match in TS_STATIC_IMPORT_DEFAULT.finditer(content):
            named_import = _first_named_import(match.groupdict().get("named2"))
            results.extend(self._ts_results_for_specifier(source, match.group("path_b"), match.group(0), named_import))
        return results

    def _resolve_ts_pattern(
        self,
        source: Path,
        content: str,
        pattern: re.Pattern[str],
        named_import: str | None,
    ) -> list[ResolvedImport]:
        results: list[ResolvedImport] = []
        for match in pattern.finditer(content):
            results.extend(self._ts_results_for_specifier(source, match.group(1), match.group(0), named_import))
        return results

    def _ts_results_for_specifier(
        self,
        source: Path,
        specifier: str,
        import_statement: str,
        named_import: str | None,
    ) -> list[ResolvedImport]:
        candidates, used_alias = self._resolve_ts_specifier(specifier, source)
        resolved = self._result_for_candidates(
            source,
            import_statement,
            candidates,
            confidence=ConfidenceLabel.RESOLVED_ALIAS if used_alias else ConfidenceLabel.RESOLVED_IMPORT,
        )
        if len(resolved) == 1 and resolved[0].target_file is not None and resolved[0].target_file.name.startswith("index."):
            barrel = self._resolve_barrel(resolved[0].target_file, named_import)
            if barrel:
                return [
                    ResolvedImport(source, target, import_statement, ConfidenceLabel.BARREL_CONTEXT)
                    for target in barrel
                ]
        return resolved

    def _resolve_ts_specifier(self, specifier: str, source: Path) -> tuple[list[Path], bool]:
        if specifier.startswith(("./", "../")):
            return self._ts_candidates((source.parent / specifier).resolve()), False
        alias_candidates = self._resolve_ts_alias(specifier, source)
        if alias_candidates:
            return alias_candidates, True
        return [], False

    def _resolve_ts_alias(self, specifier: str, source: Path) -> list[Path]:
        tsconfig = self._load_tsconfig(source)
        if tsconfig is None:
            return []
        compiler_options = tsconfig.get("compilerOptions")
        if not isinstance(compiler_options, dict):
            return []
        paths = compiler_options.get("paths")
        if not isinstance(paths, dict):
            return []
        base_url = compiler_options.get("baseUrl")
        base_root = self._tsconfig_root(source) / str(base_url or ".")
        candidates: list[Path] = []
        for alias, raw_targets in paths.items():
            candidates.extend(self._alias_candidates(str(alias), raw_targets, specifier, base_root))
        return _unique_paths(candidates)

    def _alias_candidates(
        self,
        alias: str,
        raw_targets: object,
        specifier: str,
        base_root: Path,
    ) -> list[Path]:
        if not isinstance(raw_targets, list):
            return []
        suffix = _alias_suffix(alias, specifier)
        if suffix is None:
            return []
        candidates: list[Path] = []
        for target in raw_targets:
            if isinstance(target, str):
                candidates.extend(self._ts_candidates((base_root / target.replace("*", suffix)).resolve()))
        return candidates

    def _load_tsconfig(self, source: Path) -> dict[str, Any] | None:
        config_root = self._tsconfig_root(source)
        if config_root in self._tsconfig_cache:
            return self._tsconfig_cache[config_root]
        for name in ("tsconfig.json", "jsconfig.json"):
            config_path = config_root / name
            if config_path.is_file():
                try:
                    data = json.loads(config_path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    data = None
                self._tsconfig_cache[config_root] = data if isinstance(data, dict) else None
                return self._tsconfig_cache[config_root]
        self._tsconfig_cache[config_root] = None
        return None

    def _tsconfig_root(self, source: Path) -> Path:
        repo_root = self._repo_root_for_path(source)
        for directory in (source.parent, *source.parents):
            if directory == repo_root.parent:
                break
            if (directory / "tsconfig.json").is_file() or (directory / "jsconfig.json").is_file():
                return directory
        return repo_root

    def _ts_candidates(self, base: Path) -> list[Path]:
        candidates = [base] if base.is_file() else []
        candidates.extend(base.with_suffix(ext) for ext in TS_EXTENSIONS)
        candidates.extend(base / index_name for index_name in TS_INDEXES)
        return _unique_paths(path for path in candidates if path.is_file())

    def _resolve_barrel(self, barrel_file: Path, named_import: str | None) -> list[Path]:
        content = barrel_file.read_text(encoding="utf-8", errors="replace")
        results: list[Path] = []
        for match in TS_REEXPORT.finditer(content):
            if named_import is not None and named_import not in match.group(0) and "*" not in match.group(0):
                continue
            candidates, _used_alias = self._resolve_ts_specifier(match.group(1), barrel_file)
            results.extend(candidates)
        return _unique_paths(results)

    def _resolve_java(self, source: Path) -> list[ResolvedImport]:
        content = source.read_text(encoding="utf-8", errors="replace")
        package = _java_package(content)
        results = self._resolve_java_imports(source, content)
        if package is not None:
            results.extend(self._resolve_same_package(source, package, content))
        results.extend(self._resolve_spring_annotations(source, content, package))
        return _deduplicate_results(results)

    def _resolve_java_imports(self, source: Path, content: str) -> list[ResolvedImport]:
        results: list[ResolvedImport] = []
        for match in JAVA_IMPORT.finditer(content):
            candidates = self._resolve_java_import(match.group(1))
            results.extend(self._result_for_candidates(source, match.group(0), candidates))
        return results

    def _build_java_package_index(self) -> dict[str, list[Path]]:
        index: dict[str, list[Path]] = {}
        for repo_root in self._repos.values():
            for java_file in repo_root.rglob("*.java"):
                package = _java_package(java_file.read_text(encoding="utf-8", errors="replace"))
                if package is not None:
                    index.setdefault(package, []).append(java_file)
        return index

    def _java_index(self) -> dict[str, list[Path]]:
        if self._java_package_index is None:
            self._java_package_index = self._build_java_package_index()
        return self._java_package_index

    def _resolve_java_import(self, import_stmt: str) -> list[Path]:
        if import_stmt.endswith(".*"):
            return _unique_paths(self._java_index().get(import_stmt[:-2], []))
        parts = import_stmt.split(".")
        package = ".".join(parts[:-1])
        type_name = parts[-1]
        candidates = [
            path for path in self._java_index().get(package, []) if path.stem == type_name
        ]
        if candidates:
            return _unique_paths(candidates)
        static_package = ".".join(parts[:-2])
        static_type = parts[-2] if len(parts) > 1 else type_name
        return _unique_paths(
            path for path in self._java_index().get(static_package, []) if path.stem == static_type
        )

    def _resolve_same_package(
        self,
        source: Path,
        package: str,
        content: str,
    ) -> list[ResolvedImport]:
        references = set(JAVA_TYPE_REFERENCE.findall(content))
        declared = set(JAVA_CLASS_DECL.findall(content))
        candidates = [
            path
            for path in self._java_index().get(package, [])
            if path.resolve() != source.resolve() and path.stem in references - declared
        ]
        return [
            ResolvedImport(source, path, f"same-package:{path.stem}", ConfidenceLabel.SAME_PACKAGE_HEURISTIC)
            for path in _unique_paths(candidates)
        ]

    def _resolve_spring_annotations(
        self,
        source: Path,
        content: str,
        package: str | None,
    ) -> list[ResolvedImport]:
        packages = set(_spring_packages(content))
        if package is not None and SPRING_MARKER.search(content):
            packages.add(package)
        candidates = [
            path
            for scan_package in packages
            for path in self._java_index().get(scan_package, [])
            if path.resolve() != source.resolve()
        ]
        return [
            ResolvedImport(source, path, "spring-scan", ConfidenceLabel.SPRING_SCAN_HEURISTIC)
            for path in _unique_paths(candidates)
        ]

    def _result_for_candidates(
        self,
        source: Path,
        import_statement: str,
        candidates: list[Path],
        *,
        confidence: ConfidenceLabel = ConfidenceLabel.RESOLVED_IMPORT,
    ) -> list[ResolvedImport]:
        unique = _unique_paths(candidates)
        if len(unique) == 1:
            return [ResolvedImport(source, unique[0], import_statement, confidence)]
        if len(unique) > 1:
            return [
                ResolvedImport(
                    source,
                    None,
                    import_statement,
                    ConfidenceLabel.UNRESOLVED_DYNAMIC,
                )
            ]
        return []

    def _repo_file_for_result(self, result: ResolvedImport) -> _RepoFile | None:
        if result.target_file is None:
            return None
        repo_id = self._repo_id_for_path(result.target_file)
        repo_root = self._repos[repo_id]
        rel_path = Path(result.target_file.relative_to(repo_root).as_posix())
        return _RepoFile(repo_id, repo_root, rel_path, result.target_file)

    def _bundle_entry(self, repo_file: _RepoFile, confidence: ConfidenceLabel) -> BundleEntry:
        content = repo_file.abs_path.read_text(encoding="utf-8", errors="replace")
        return BundleEntry(
            repo_id=repo_file.repo_id,
            path=repo_file.rel_path,
            authority=AuthorityClass.SECONDARY_CONTEXT,
            confidence=confidence.value,
            reason="Resolved import from Stage-2 import resolver",
            size=len(content.encode("utf-8")),
            content=content,
        )

    def _repo_roots_for_source(self, source_repo_id: str) -> list[tuple[str, Path]]:
        preferred = [(source_repo_id, self._repos[source_repo_id])]
        rest = sorted((repo_id, root) for repo_id, root in self._repos.items() if repo_id != source_repo_id)
        return [*preferred, *rest]

    def _repo_id_for_path(self, path: Path) -> str:
        resolved = path.resolve()
        for repo_id, repo_root in self._repos.items():
            try:
                resolved.relative_to(repo_root)
            except ValueError:
                continue
            return repo_id
        msg = f"path is outside configured repositories: {path}"
        raise ValueError(msg)

    def _repo_root_for_path(self, path: Path) -> Path:
        return self._repos[self._repo_id_for_path(path)]


def _unique_paths(paths: Any) -> list[Path]:
    unique: dict[str, Path] = {}
    for path in paths:
        resolved = Path(path).resolve()
        unique[str(resolved)] = resolved
    return [unique[key] for key in sorted(unique)]


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
                packages.extend(item.strip().strip('"') for item in grouped.split(",") if item.strip())
    return packages


def _deduplicate_results(results: list[ResolvedImport]) -> list[ResolvedImport]:
    unique: dict[tuple[str, str | None], ResolvedImport] = {}
    for result in results:
        target = str(result.target_file) if result.target_file is not None else None
        key = (str(result.source_file), target)
        current = unique.get(key)
        if current is None or _confidence_rank(result.confidence) > _confidence_rank(current.confidence):
            unique[key] = result
    return list(unique.values())


def _confidence_rank(confidence: ConfidenceLabel) -> int:
    return CONFIDENCE_PRIORITY[confidence]


def _confidence_rank_value(confidence: str | None) -> int:
    if confidence is None:
        return -1
    try:
        return CONFIDENCE_PRIORITY[ConfidenceLabel(confidence)]
    except ValueError:
        return -1


__all__ = [
    "CONFIDENCE_PRIORITY",
    "ConfidenceLabel",
    "ImportResolver",
    "ResolvedImport",
]
