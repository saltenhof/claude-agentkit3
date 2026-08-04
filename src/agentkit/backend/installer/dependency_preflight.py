"""Declared-runtime dependency preflight for the AgentKit installation.

The installed distribution metadata is the runtime declaration owner.  This
module deliberately contains no maintained package list: every base
``Requires-Dist`` entry of the installed AgentKit artifact is discovered at
run time and checked against the current interpreter environment.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import re
import shlex
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from time import monotonic
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

_DISTRIBUTION_NAME = "agentkit"
_REQUIREMENT_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")
_NORMALIZED_NAME_SEPARATOR = re.compile(r"[-_.]+")


@dataclass(frozen=True)
class DependencyFailure:
    """One declared dependency that the current interpreter cannot import."""

    requirement: str
    distribution: str
    detail: str
    install_command: str


@dataclass(frozen=True)
class DependencyPreflightReport:
    """Complete result of checking one artifact's runtime declaration."""

    declared_count: int
    failures: tuple[DependencyFailure, ...]
    duration_ms: int

    @property
    def passed(self) -> bool:
        """Return whether every declared runtime dependency is importable."""
        return not self.failures


class DependencyDeclarationError(RuntimeError):
    """Raised when the authoritative dependency declaration is unusable."""

    def __init__(self, message: str, *, duration_ms: int = 0) -> None:
        super().__init__(message)
        self.duration_ms = duration_ms


class RuntimeDependencyError(RuntimeError):
    """Raised before runtime code loads when declared dependencies are incomplete."""


def declared_runtime_requirements(
    *,
    distribution_name: str = _DISTRIBUTION_NAME,
    pyproject_path: Path | None = None,
) -> tuple[str, ...]:
    """Read base runtime requirements from one authoritative declaration.

    ``pyproject_path`` is an explicit source/declaration seam used by build and
    contract verification.  Productive installed runs omit it and read the
    ``Requires-Dist`` fields of the installed artifact, which are generated
    from ``project.dependencies`` by the build backend.

    Args:
        distribution_name: Installed distribution whose metadata owns the
            runtime requirements.
        pyproject_path: Optional source ``pyproject.toml`` declaration.

    Returns:
        Runtime requirement strings in declaration order.

    Raises:
        DependencyDeclarationError: If the declaration is missing or invalid.
    """
    if pyproject_path is not None:
        return _requirements_from_pyproject(pyproject_path)
    try:
        requirements = importlib.metadata.requires(distribution_name)
    except importlib.metadata.PackageNotFoundError as exc:
        raise DependencyDeclarationError(
            f"Installed distribution metadata for {distribution_name!r} is missing."
        ) from exc
    except Exception as exc:  # noqa: BLE001 - every metadata fault is fail-closed
        raise DependencyDeclarationError(
            f"Cannot read Requires-Dist metadata for {distribution_name!r}: "
            f"{type(exc).__name__}: {exc}"
        ) from exc
    if requirements is None:
        raise DependencyDeclarationError(
            f"Installed distribution metadata for {distribution_name!r} has no Requires-Dist declaration."
        )
    return tuple(requirement for requirement in requirements if not _is_extra_requirement(requirement))


def check_runtime_dependencies(
    *,
    distribution_name: str = _DISTRIBUTION_NAME,
    pyproject_path: Path | None = None,
) -> DependencyPreflightReport:
    """Check every declared base dependency in the current interpreter.

    A dependency passes only when its distribution is installed, its exported
    top-level modules can be derived from distribution metadata, and every such
    module imports successfully.  The install command is derived from the same
    requirement string; no second dependency list or import-name mapping exists.

    Args:
        distribution_name: Installed artifact whose dependencies are checked.
        pyproject_path: Optional source declaration for contract verification.

    Returns:
        A complete report containing every failure, not merely the first one.
    """
    started_at = monotonic()
    try:
        requirements = declared_runtime_requirements(
            distribution_name=distribution_name,
            pyproject_path=pyproject_path,
        )
    except DependencyDeclarationError as exc:
        raise DependencyDeclarationError(
            str(exc),
            duration_ms=_elapsed_ms(started_at),
        ) from exc
    package_owners = importlib.metadata.packages_distributions()
    failures: list[DependencyFailure] = []
    for requirement in requirements:
        distribution = _distribution_name(requirement)
        failure = _check_dependency(requirement, distribution, package_owners)
        if failure is not None:
            failures.append(failure)
    return DependencyPreflightReport(
        declared_count=len(requirements),
        failures=tuple(failures),
        duration_ms=_elapsed_ms(started_at),
    )


def format_dependency_failures(report: DependencyPreflightReport) -> str:
    """Render an actionable, deterministic failure detail for CP 1."""
    lines = [
        "AgentKit runtime dependency preflight failed; installation did not start."
    ]
    for failure in report.failures:
        lines.extend(
            (
                f"- {failure.distribution}: {failure.detail}",
                f"  Install with: {failure.install_command}",
            )
        )
    return "\n".join(lines)


def require_runtime_dependencies() -> DependencyPreflightReport:
    """Return the complete report or raise an actionable bootstrap error.

    This function and its module use only the Python standard library so public
    entry points can call it before importing any declared third-party package.

    Returns:
        The passing declaration-owned dependency report.

    Raises:
        RuntimeDependencyError: If the declaration is unusable or a declared
            dependency is unavailable.
    """
    try:
        report = check_runtime_dependencies()
    except DependencyDeclarationError as exc:
        raise RuntimeDependencyError(
            f"AgentKit runtime dependency declaration is unavailable: {exc}"
        ) from exc
    if not report.passed:
        raise RuntimeDependencyError(format_dependency_failures(report))
    return report


def _requirements_from_pyproject(path: Path) -> tuple[str, ...]:
    try:
        document = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise DependencyDeclarationError(
            f"Cannot read dependency declaration {path}: {exc}"
        ) from exc
    project = document.get("project")
    dependencies = project.get("dependencies") if isinstance(project, dict) else None
    if not isinstance(dependencies, list) or not all(
        isinstance(item, str) for item in dependencies
    ):
        raise DependencyDeclarationError(
            f"{path} must define project.dependencies as a list of strings."
        )
    return tuple(dependencies)


def _is_extra_requirement(requirement: str) -> bool:
    marker = requirement.partition(";")[2]
    return bool(marker and re.search(r"\bextra\s*==", marker))


def _distribution_name(requirement: str) -> str:
    match = _REQUIREMENT_NAME.match(requirement)
    if match is None:
        raise DependencyDeclarationError(
            f"Cannot derive a distribution name from requirement {requirement!r}."
        )
    return match.group(1)


def _check_dependency(
    requirement: str,
    distribution_name: str,
    package_owners: Mapping[str, list[str]],
) -> DependencyFailure | None:
    try:
        importlib.metadata.distribution(distribution_name)
    except importlib.metadata.PackageNotFoundError:
        return _failure(
            requirement,
            distribution_name,
            "declared distribution is not installed in this interpreter",
        )

    normalized_distribution = _normalize_distribution_name(distribution_name)
    discovered_modules = sorted(
        package
        for package, owners in package_owners.items()
        if any(
            _normalize_distribution_name(owner) == normalized_distribution
            for owner in owners
        )
    )
    public_modules = [module for module in discovered_modules if not module.startswith("_")]
    modules = public_modules or discovered_modules
    if not modules:
        return _failure(
            requirement,
            distribution_name,
            "distribution metadata exposes no importable top-level module",
        )
    for module in modules:
        try:
            importlib.import_module(module)
        except Exception as exc:  # noqa: BLE001 - any import fault is incomplete
            return _failure(
                requirement,
                distribution_name,
                f"top-level module {module!r} is not importable ({type(exc).__name__}: {exc})",
            )
    return None


def _failure(
    requirement: str,
    distribution_name: str,
    detail: str,
) -> DependencyFailure:
    return DependencyFailure(
        requirement=requirement,
        distribution=distribution_name,
        detail=detail,
        install_command=_install_command(requirement),
    )


def _install_command(requirement: str) -> str:
    arguments = [sys.executable, "-m", "pip", "install", requirement]
    if sys.platform == "win32":
        return subprocess.list2cmdline(arguments)
    return shlex.join(arguments)


def _normalize_distribution_name(name: str) -> str:
    return _NORMALIZED_NAME_SEPARATOR.sub("-", name).lower()


def _elapsed_ms(started_at: float) -> int:
    return int((monotonic() - started_at) * 1000)


__all__ = [
    "DependencyDeclarationError",
    "DependencyFailure",
    "DependencyPreflightReport",
    "RuntimeDependencyError",
    "check_runtime_dependencies",
    "declared_runtime_requirements",
    "format_dependency_failures",
    "require_runtime_dependencies",
]
