"""Project binding from authoritative ProjectConfig (AG3-174 R01/R15).

``project_key``, ``wiki_stories_dir`` and ``concepts_dir`` come exclusively
from the loaded project configuration. Config errors are start failures —
no directory-name inventing, no silent ``concept/`` fallback.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from agentkit.backend.config.loader import load_project_config
from agentkit.backend.exceptions import AgentKitError

if TYPE_CHECKING:
    from agentkit.backend.config.models import ProjectConfig


class ProjectBindingError(Exception):
    """Raised when project binding validation fails (fail-closed)."""


@dataclass(frozen=True)
class ProjectBinding:
    """Authoritative project scope for VectorDB read/write operations."""

    project_root: Path
    project_id: str
    concepts_dir: Path
    stories_dir: Path
    config: ProjectConfig

    def resolve_contained(self, path: str | Path) -> Path:
        """Resolve ``path`` and ensure it stays inside ``project_root``."""
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = self.project_root / candidate
        try:
            resolved = candidate.resolve(strict=False)
            root = self.project_root.resolve(strict=False)
        except OSError as exc:
            raise ProjectBindingError(f"Cannot resolve path {path!r}: {exc}") from exc
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise ProjectBindingError(
                f"Path {resolved} escapes project_root {root} (fail-closed)."
            ) from exc
        return resolved

    def relative_posix(self, path: Path) -> str:
        """Return ``path`` relative to ``project_root`` as a POSIX string."""
        resolved = self.resolve_contained(path)
        return PurePosixPath(resolved.relative_to(self.project_root.resolve())).as_posix()


def bind_project(
    project_root: str | Path,
    *,
    project_id: str | None = None,
    concepts_dir: str | Path | None = None,
    stories_dir: str | Path | None = None,
    config: ProjectConfig | None = None,
) -> ProjectBinding:
    """Build a :class:`ProjectBinding` from authoritative project config.

    Args:
        project_root: Project root directory (must exist).
        project_id: Optional override; when omitted uses ``ProjectConfig.project_key``.
        concepts_dir: Optional override; when omitted uses ``ProjectConfig.concepts_dir``.
        stories_dir: Optional override; when omitted uses ``ProjectConfig.wiki_stories_dir``.
        config: Optional pre-loaded config; when omitted loaded fail-closed.

    Raises:
        ProjectBindingError: On missing root, config load failure, or empty identity.
    """
    root = Path(project_root)
    if not root.is_dir():
        raise ProjectBindingError(
            f"project_root does not exist or is not a directory: {root}"
        )
    try:
        resolved_root = root.resolve(strict=True)
    except OSError as exc:
        raise ProjectBindingError(f"Cannot resolve project_root {root}: {exc}") from exc

    if config is None:
        try:
            config = load_project_config(resolved_root)
        except (AgentKitError, OSError, ValueError, TypeError) as exc:
            raise ProjectBindingError(
                f"failed to load ProjectConfig from {resolved_root}: {exc} "
                "(fail-closed: config errors are start failures, R15)."
            ) from exc

    resolved_id = (project_id or "").strip() if project_id is not None else ""
    if not resolved_id:
        resolved_id = (config.project_key or "").strip()
    if not resolved_id:
        raise ProjectBindingError(
            "project_id/project_key is empty after config resolution (fail-closed)."
        )

    concepts_rel = (
        str(concepts_dir) if concepts_dir is not None else config.concepts_dir
    )
    stories_rel = str(stories_dir) if stories_dir is not None else config.wiki_stories_dir
    if not concepts_rel or not stories_rel:
        raise ProjectBindingError(
            "concepts_dir and wiki_stories_dir must be non-empty (fail-closed)."
        )

    concepts_path = Path(concepts_rel)
    stories_path = Path(stories_rel)
    if not concepts_path.is_absolute():
        concepts_path = resolved_root / concepts_path
    if not stories_path.is_absolute():
        stories_path = resolved_root / stories_path

    binding = ProjectBinding(
        project_root=resolved_root,
        project_id=resolved_id,
        concepts_dir=concepts_path,
        stories_dir=stories_path,
        config=config,
    )
    binding.resolve_contained(binding.concepts_dir)
    binding.resolve_contained(binding.stories_dir)
    return binding


__all__ = [
    "ProjectBinding",
    "ProjectBindingError",
    "bind_project",
]
