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

    Supports exactly four mandatory placeholders (FK-43 §43.4.2 table):

    * ``{{gh_owner}}``       — ``config.github_owner``
    * ``{{gh_repo}}``        — ``config.repositories[0].name``
      (deterministic first repository; single-repo: the only one)
    * ``{{project_prefix}}`` — ``config.project_prefix``
      (FK-03 §3.2 / defaulted from ``project_key.upper()`` when absent)
    * ``{{project_key}}``    — ``config.project_key``

    The accepted config type is the top-level ``ProjectConfig`` (which
    aggregates ``PipelineConfig`` and carries all FK-03 §3.2 fields).
    Read-only access — no mutation, no state held.

    Raises ``UnknownPlaceholderError`` on any unrecognised token
    (fail-closed per FK-43 §43.4.2).

    Args:
        None — stateless; ``substitute`` receives the config at call time.
    """

    def substitute(self, content: str, config: ProjectConfig) -> str:
        """Replace all placeholder tokens in *content* (FK-43 §43.4.2).

        Args:
            content: Raw text that may contain ``{{...}}`` tokens.
            config: The project configuration used to resolve values.

        Returns:
            The content with all recognised placeholders replaced.

        Raises:
            UnknownPlaceholderError: When an unrecognised placeholder is found.
            ValueError: When ``config.repositories`` is empty
                (``{{gh_repo}}`` has no canonical source).
        """
        if not config.repositories:
            msg = (
                "PlaceholderSubstitutor requires at least one repository in "
                "config.repositories to resolve {{gh_repo}} (FK-43 §43.4.2)"
            )
            raise ValueError(msg)
        # project_prefix is FK-03 §3.2 Pflichtfeld; ProjectConfig defaults it
        # to project_key.upper() when not provided.
        assert config.project_prefix is not None  # noqa: S101 -- enforced by validator
        placeholder_values: dict[str, str] = {
            "gh_owner": config.github_owner or "",
            "gh_repo": config.repositories[0].name,
            "project_prefix": config.project_prefix,
            "project_key": config.project_key,
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
