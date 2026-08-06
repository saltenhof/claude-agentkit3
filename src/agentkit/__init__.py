"""AgentKit --- Deterministic orchestration engine for AI-driven story execution."""

from __future__ import annotations

import json
from importlib.metadata import Distribution, distributions
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit
from urllib.request import url2pathname


def _same_file(left: Path, right: Path) -> bool:
    """Return whether two possibly non-existent paths identify one location."""
    return left.resolve() == right.resolve()


def _recorded_package_path(candidate: Distribution) -> Path | None:
    """Return this distribution's installed ``agentkit/__init__.py`` path."""
    for entry in candidate.files or ():
        parts = PurePosixPath(str(entry).replace("\\", "/")).parts
        if parts[-2:] == ("agentkit", "__init__.py"):
            return Path(str(candidate.locate_file(entry)))
    return None


def _editable_source_root(candidate: Distribution) -> Path | None:
    """Return the source root declared by a standards-based editable install."""
    try:
        raw = candidate.read_text("direct_url.json")
        payload = json.loads(raw) if raw is not None else None
        if not isinstance(payload, dict):
            return None
        directory = payload.get("dir_info")
        url = payload.get("url")
        if (
            not isinstance(directory, dict)
            or directory.get("editable") is not True
            or not isinstance(url, str)
        ):
            return None
        parsed = urlsplit(url)
        if parsed.scheme != "file" or parsed.query or parsed.fragment:
            return None
        path = url2pathname(unquote(parsed.path))
        if parsed.netloc:
            path = f"//{parsed.netloc}{path}"
        return Path(path)
    except (json.JSONDecodeError, OSError, TypeError, ValueError):
        return None


def _distribution_owns_current_package(candidate: Distribution) -> bool:
    """Prove that distribution metadata belongs to this imported package."""
    package_file = Path(__file__)
    recorded = _recorded_package_path(candidate)
    if recorded is not None and _same_file(recorded, package_file):
        return True
    source_root = _editable_source_root(candidate)
    if source_root is None:
        return False
    return any(
        _same_file(package_file, expected)
        for expected in (
            source_root / "src" / "agentkit" / "__init__.py",
            source_root / "agentkit" / "__init__.py",
        )
    )


def _current_package_is_installed() -> bool:
    """Return whether installed metadata proves ownership of this package."""
    return any(
        _distribution_owns_current_package(candidate)
        for candidate in distributions(name="agentkit")
    )


def _enforce_installed_runtime_isolation() -> None:
    """Reject an installed AgentKit distribution outside a virtual environment.

    A source tree must remain importable by the in-tree PEP-517 backend before
    installation metadata exists. Once the distribution is installed, this
    package boundary covers wheels and source installs alike.
    """
    if not _current_package_is_installed():
        return
    from agentkit.backend.installer.interpreter import resolve_ak3_interpreter

    resolve_ak3_interpreter()


_enforce_installed_runtime_isolation()

__version__ = "0.1.0"
