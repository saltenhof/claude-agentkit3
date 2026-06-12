"""PlaceholderSubstitutor for skill content (AG3-027 / AG3-110, FK-43 §43.4.2).

This substitutor handles the four mandatory FK-03 placeholders that may appear in
skill template content, PLUS one manifest-fed placeholder (``AGENT_SPAWN_SKILL_PROOF``,
AG3-110). It is the FK-43 §43.4.2 read-time substitution service for the skill
consumer.

IMPORTANT: ``PlaceholderSubstitutor`` is NOT called by ``bind_skill``.
Link-based binding (invariant ``project_binding_is_link_only``) copies nothing —
placeholders are resolved at read-time by skill consumers.

AG3-110 (FK-31 §31.7.1/§31.7.2/§31.7.4): the ``story_execution`` spawn header in
``SKILL.md`` carries ``skill_proof={{AGENT_SPAWN_SKILL_PROOF}}``. That fifth
placeholder is resolved from the INSTALLED MANIFEST (``.installed-manifest.json`` ->
``agent_spawn_skill_proof``), NOT from ``project.yaml`` — hence it is modelled
separately from the four FK-03 placeholders, with its own manifest-fed source.
FAIL-CLOSED: when no manifest / no token is installed, the placeholder is NOT
substituted with a dummy or empty value — :meth:`substitute_spawn_header` raises so
the header stays unresolved and the AG3-086 guard blocks the spawn fail-closed.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from agentkit.skills.errors import UnknownPlaceholderError

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.config.models import ProjectConfig

# Regex that matches any {{...}} placeholder token.
_PLACEHOLDER_RE = re.compile(r"\{\{(\w+)\}\}")

# The FK-43 §43.4.2 config-fed placeholder vocabulary (lowercase, snake_case).
# Four mandatory identity tokens plus the surviving layout token
# ``wiki_stories_dir``. This set is authoritative and closed: any token not
# listed here (and not the manifest-fed proof) breaks fail-closed.
_MANDATORY_PLACEHOLDERS: frozenset[str] = frozenset(
    {
        "gh_owner",
        "gh_repo",
        "project_prefix",
        "project_key",
        "wiki_stories_dir",
    }
)

#: The manifest-fed spawn skill-proof placeholder (AG3-110, FK-31 §31.7.4). Its source
#: is the installed manifest's ``agent_spawn_skill_proof`` token, NOT ``project.yaml``.
SPAWN_SKILL_PROOF_PLACEHOLDER = "AGENT_SPAWN_SKILL_PROOF"


class PlaceholderSubstitutor:
    """Substitutes FK-43 §43.4.2 placeholder tokens in skill content.

    Supports exactly the FK-43 §43.4.2 config-fed placeholder table
    (lowercase, snake_case):

    * ``{{gh_owner}}``          — ``config.github_owner``
    * ``{{gh_repo}}``           — ``config.repositories[0].name``
      (deterministic first repository; single-repo: the only one)
    * ``{{project_prefix}}``    — ``config.project_prefix``
      (FK-03 §3.2 / defaulted from ``project_key.upper()`` when absent)
    * ``{{project_key}}``       — ``config.project_key``
    * ``{{wiki_stories_dir}}``  — ``config.wiki_stories_dir``
      (FK-03 §3.1 project-relative wiki-stories directory; default ``stories``)

    The accepted config type is the top-level ``ProjectConfig`` (which
    aggregates ``PipelineConfig`` and carries all FK-03 §3.2 fields).
    Read-only access — no mutation, no state held.

    The fifth placeholder ``{{AGENT_SPAWN_SKILL_PROOF}}`` (AG3-110) is resolved by
    :meth:`substitute_spawn_header` ONLY — its source is the installed manifest, not
    the config. :meth:`substitute` alone (config-only) treats it as unknown.

    Raises ``UnknownPlaceholderError`` on any unrecognised token
    (fail-closed per FK-43 §43.4.2).

    Args:
        None — stateless; ``substitute`` receives the config at call time.
    """

    def substitute(self, content: str, config: ProjectConfig) -> str:
        """Replace the four FK-03 placeholder tokens in *content* (FK-43 §43.4.2).

        This is the config-only path: it resolves exactly the four FK-03 placeholders
        and treats every other token — including the manifest-fed
        ``{{AGENT_SPAWN_SKILL_PROOF}}`` — as unknown (fail-closed). Use
        :meth:`substitute_spawn_header` to additionally resolve the manifest-fed
        spawn-proof placeholder.

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
        return self._apply(content, self._config_values(config))

    def substitute_spawn_header(
        self, content: str, config: ProjectConfig, project_root: Path
    ) -> str:
        """Resolve all five read-time placeholders incl. the manifest-fed proof.

        AG3-110 (FK-31 §31.7.4 / FK-43 §43.4.2): the read-time substitution path for
        the ``story_execution`` spawn header. It resolves the four FK-03 placeholders
        from *config* AND ``{{AGENT_SPAWN_SKILL_PROOF}}`` from the installed manifest
        (``.installed-manifest.json`` -> ``agent_spawn_skill_proof``) read from
        *project_root*.

        FAIL-CLOSED (story §5, AC3 negative): when no manifest / no token is installed,
        the spawn-proof placeholder has NO authoritative value and is NOT replaced with
        a dummy/empty token — this method raises ``UnknownPlaceholderError`` so the
        header is delivered with the literal placeholder unresolved and the AG3-086
        guard blocks the spawn fail-closed. There is no soft fallback to a placeholder
        string acting as a token (NO ERROR BYPASSING).

        Args:
            content: Raw skill content carrying ``{{...}}`` tokens (e.g. SKILL.md).
            config: The project configuration (resolves the four FK-03 placeholders).
            project_root: The target-project root whose ``.installed-manifest.json``
                carries the authoritative ``agent_spawn_skill_proof`` token.

        Returns:
            The content with all five placeholders resolved.

        Raises:
            UnknownPlaceholderError: When an unrecognised placeholder is found, OR when
                ``{{AGENT_SPAWN_SKILL_PROOF}}`` is present but no authoritative token is
                installed (fail-closed — no dummy token).
            ValueError: When ``config.repositories`` is empty.
        """
        values = self._config_values(config)
        token = self._installed_skill_proof(project_root)
        if token:
            values[SPAWN_SKILL_PROOF_PLACEHOLDER] = token
        # When the token is missing/empty we deliberately do NOT add it to ``values``;
        # a present ``{{AGENT_SPAWN_SKILL_PROOF}}`` then raises UnknownPlaceholderError
        # in ``_apply`` (fail-closed). Content WITHOUT the placeholder still resolves.
        return self._apply(content, values)

    @staticmethod
    def _config_values(config: ProjectConfig) -> dict[str, str]:
        """Return the FK-43 §43.4.2 config-fed placeholder values from *config*."""
        if not config.repositories:
            msg = (
                "PlaceholderSubstitutor requires at least one repository in "
                "config.repositories to resolve {{gh_repo}} (FK-43 §43.4.2)"
            )
            raise ValueError(msg)
        # project_prefix is FK-03 §3.2 Pflichtfeld; ProjectConfig defaults it
        # to project_key.upper() when not provided.
        assert config.project_prefix is not None  # noqa: S101 -- enforced by validator
        return {
            "gh_owner": config.github_owner or "",
            "gh_repo": config.repositories[0].name,
            "project_prefix": config.project_prefix,
            "project_key": config.project_key,
            "wiki_stories_dir": config.wiki_stories_dir,
        }

    @staticmethod
    def _installed_skill_proof(project_root: Path) -> str:
        """Read the install-manifest ``agent_spawn_skill_proof`` token (AG3-110).

        Reads ``.installed-manifest.json`` under the SAME top-level key
        (``AGENT_SPAWN_SKILL_PROOF_KEY``) the AG3-110 producer writes and the AG3-086
        consumer reads, through the ``utils.io`` truth-boundary helper. The filename +
        key come from the BC-neutral ``core_types`` contract — the agent-skills BC does
        NOT depend on the installer BC (no BC back-edge / cycle). Returns ``""`` when no
        manifest / token is installed — the caller then leaves the header placeholder
        unresolved (fail-closed). It NEVER generates a token (generation is the
        installer producer's job; the read-time path only reads).
        """
        from agentkit.core_types.plane_artifact_names import (
            AGENT_SPAWN_SKILL_PROOF_KEY,
            INSTALLED_MANIFEST_FILENAME,
        )
        from agentkit.utils.io import read_json_object

        data = read_json_object(project_root / INSTALLED_MANIFEST_FILENAME)
        token = data.get(AGENT_SPAWN_SKILL_PROOF_KEY)
        return token if isinstance(token, str) else ""

    @staticmethod
    def _apply(content: str, placeholder_values: dict[str, str]) -> str:
        """Replace ``{{...}}`` tokens from *placeholder_values* (fail-closed)."""

        def _replace(match: re.Match[str]) -> str:
            name = match.group(1)
            if name not in placeholder_values:
                raise UnknownPlaceholderError(
                    f"Unknown placeholder '{{{{{name}}}}}' in skill content",
                    detail={
                        "placeholder": f"{{{{{name}}}}}",
                        "supported": sorted(placeholder_values),
                    },
                )
            return placeholder_values[name]

        return _PLACEHOLDER_RE.sub(_replace, content)
