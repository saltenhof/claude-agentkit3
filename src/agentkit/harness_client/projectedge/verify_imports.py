"""Edge-local import-target discovery over a bounded text snapshot."""

from __future__ import annotations

import posixpath
import re
from collections.abc import Mapping
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

_PY_IMPORT = re.compile(
    r"^(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))", re.MULTILINE
)
_TS_IMPORT = re.compile(
    r"(?:from\s+|import\s*\(|require\s*\()\s*['\"]([^'\"]+)['\"]"
    r"|^\s*import\s*['\"]([^'\"]+)['\"]",
    re.MULTILINE,
)
_JAVA_IMPORT = re.compile(
    r"^import\s+(?:static\s+)?([\w.]+(?:\.\*)?)\s*;", re.MULTILINE
)
_JAVA_PACKAGE = re.compile(r"^package\s+([\w.]+)\s*;", re.MULTILINE)
_SPRING_PACKAGE = re.compile(r"['\"]([a-zA-Z_]\w*(?:\.[a-zA-Z_]\w*)+)['\"]")
_TS_EXTENSIONS = (".ts", ".tsx", ".js", ".jsx", ".d.ts")
_TS_INDEXES = tuple(f"index{suffix}" for suffix in _TS_EXTENSIONS)

Snapshot = Mapping[tuple[str, str], str]


def collect_import_target_keys(
    snapshot: Snapshot,
    changed_paths: Mapping[str, Sequence[str]],
) -> set[tuple[str, str]]:
    """Return candidate import files needed by backend consolidation."""
    targets: set[tuple[str, str]] = set()
    java_packages = _java_package_index(snapshot)
    for repo_id, paths in changed_paths.items():
        for path in paths:
            content = snapshot.get((repo_id, path))
            if content is None:
                continue
            suffix = PurePosixPath(path).suffix.lower()
            if suffix == ".py":
                targets.update(_python_targets(snapshot, repo_id, path, content))
            elif suffix in {".ts", ".tsx", ".js", ".jsx"}:
                targets.update(_typescript_targets(snapshot, repo_id, path, content))
            elif suffix == ".java":
                targets.update(_java_targets(java_packages, path, content))
    return targets


def _python_targets(
    snapshot: Snapshot, repo_id: str, source_path: str, content: str
) -> set[tuple[str, str]]:
    targets: set[tuple[str, str]] = set()
    for match in _PY_IMPORT.finditer(content):
        raw_module = match.group(1) or match.group(2)
        module = raw_module.lstrip(".").replace(".", "/")
        candidates = {f"{module}.py", f"{module}/__init__.py"}
        if raw_module.startswith("."):
            parent = PurePosixPath(source_path).parent.as_posix()
            candidates.update(
                posixpath.normpath(f"{parent}/{candidate}")
                for candidate in tuple(candidates)
            )
        targets.update(key for key in snapshot if key[1] in candidates)
    return targets


def _typescript_targets(
    snapshot: Snapshot, repo_id: str, source_path: str, content: str
) -> set[tuple[str, str]]:
    targets: set[tuple[str, str]] = set()
    for match in _TS_IMPORT.finditer(content):
        specifier = match.group(1) or match.group(2)
        if specifier.startswith(("./", "../")):
            base = posixpath.normpath(
                f"{PurePosixPath(source_path).parent.as_posix()}/{specifier}"
            )
            candidates = {base, *(f"{base}{suffix}" for suffix in _TS_EXTENSIONS)}
            candidates.update(f"{base}/{index}" for index in _TS_INDEXES)
            targets.update(
                (repo_id, candidate)
                for candidate in candidates
                if (repo_id, candidate) in snapshot
            )
            continue
        tail = specifier.rstrip("/").split("/")[-1]
        targets.update(
            key
            for key in snapshot
            if key[1].endswith(tuple(f"/{tail}{suffix}" for suffix in _TS_EXTENSIONS))
            or any(key[1].endswith(f"/{tail}/{index}") for index in _TS_INDEXES)
        )
    return targets


def _java_package_index(snapshot: Snapshot) -> dict[str, set[tuple[str, str]]]:
    index: dict[str, set[tuple[str, str]]] = {}
    for key, content in snapshot.items():
        if not key[1].endswith(".java"):
            continue
        match = _JAVA_PACKAGE.search(content)
        if match is not None:
            index.setdefault(match.group(1), set()).add(key)
    return index


def _java_targets(
    packages: Mapping[str, set[tuple[str, str]]],
    source_path: str,
    content: str,
) -> set[tuple[str, str]]:
    del source_path
    targets: set[tuple[str, str]] = set()
    own_package = _JAVA_PACKAGE.search(content)
    if own_package is not None:
        targets.update(packages.get(own_package.group(1), set()))
    for imported in _JAVA_IMPORT.findall(content):
        package, _, type_name = imported.removesuffix(".*").rpartition(".")
        candidates = packages.get(imported.removesuffix(".*"), set()) if imported.endswith(".*") else packages.get(package, set())
        targets.update(
            key for key in candidates if imported.endswith(".*") or PurePosixPath(key[1]).stem == type_name
        )
    for package in _SPRING_PACKAGE.findall(content):
        targets.update(packages.get(package, set()))
    return targets


__all__ = ["collect_import_target_keys"]
