"""PlaceholderSubstitutor for skill content (AG3-027, FK-43 §43.4.2).

This substitutor handles the four mandatory placeholders that may appear
in skill template content. It is an internal service for materialised or
substituted harness variants and future read-time resolution.

IMPORTANT: ``PlaceholderSubstitutor`` is NOT called by ``bind_skill``.
Symlink-based binding (invariant ``project_binding_is_symlink_only``)
copies nothing — placeholders are resolved at read-time by skill consumers.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from agentkit.skills.errors import UnknownPlaceholderError

if TYPE_CHECKING:
    from agentkit.config.models import ProjectConfig

# Regex that matches any {{...}} placeholder token.
_PLACEHOLDER_RE = re.compile(r"\{\{(\w+)\}\}")

# The four mandatory placeholders defined in FK-43 §43.4.2.
_MANDATORY_PLACEHOLDERS: frozenset[str] = frozenset(
    {
        "gh_owner",
        "gh_repo",
        "project_prefix",
        "project_key",
    }
)


class PlaceholderSubstitutor:
    """Substitutes FK-43 §43.4.2 placeholder tokens in skill content.

    Supports exactly four mandatory placeholders:

    * ``{{gh_owner}}``      — ``project_config.github_owner``
    * ``{{gh_repo}}``       — ``project_config.github_repo``
    * ``{{project_prefix}}`` — ``project_config.project_key`` prefix (used as
      ``story_id_prefix``; in this model equal to ``project_key`` since
      ``PipelineConfig`` does not carry ``story_id_prefix``). If the concept
      requires a distinct field this must be supplied via a follow-up story.
    * ``{{project_key}}``   — ``project_config.project_key``

    Raises ``UnknownPlaceholderError`` on any unrecognised token (fail-closed
    per FK-43 §43.4.2).

    Args:
        None — stateless; ``substitute`` receives the config at call time.
    """

    def substitute(self, content: str, project_config: ProjectConfig) -> str:
        """Replace all placeholder tokens in *content*.

        Args:
            content: Raw text that may contain ``{{...}}`` tokens.
            project_config: The project configuration used to resolve values.

        Returns:
            The content with all recognised placeholders replaced.

        Raises:
            UnknownPlaceholderError: When an unrecognised placeholder is found.
        """
        placeholder_values: dict[str, str] = {
            "gh_owner": project_config.github_owner or "",
            "gh_repo": project_config.github_repo or "",
            # story_id_prefix is not a PipelineConfig field; using project_key
            # as the canonical prefix until a follow-up story extends the model.
            "project_prefix": project_config.project_key,
            "project_key": project_config.project_key,
        }

        def _replace(match: re.Match[str]) -> str:
            name = match.group(1)
            if name not in placeholder_values:
                raise UnknownPlaceholderError(
                    f"Unknown placeholder '{{{{{name}}}}}' in skill content",
                    detail={
                        "placeholder": f"{{{{{name}}}}}",
                        "supported": sorted(_MANDATORY_PLACEHOLDERS),
                    },
                )
            return placeholder_values[name]

        return _PLACEHOLDER_RE.sub(_replace, content)
