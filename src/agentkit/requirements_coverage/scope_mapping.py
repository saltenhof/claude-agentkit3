"""BC-internal scope resolver for ARE requests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agentkit.story_context_manager.models import StoryContext


@dataclass(frozen=True)
class ScopeResolution:
    """Resolved ARE scope and story type for one story."""

    scope: str
    story_type: str


class ScopeMapping:
    """Resolve ARE scope from authoritative story context fields."""

    def resolve(self, context: StoryContext, project_key: str) -> ScopeResolution:
        """Derive scope and story type from the current story context.

        Participating repositories are the primary runtime signal. When none are
        present, the project key is the deterministic fallback.
        """

        repos = tuple(repo.strip() for repo in context.participating_repos if repo.strip())
        scope = ",".join(repos) if repos else project_key
        return ScopeResolution(scope=scope, story_type=context.story_type.value)


__all__ = ["ScopeMapping", "ScopeResolution"]
