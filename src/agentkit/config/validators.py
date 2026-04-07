"""Semantic validation for AgentKit project configuration.

Pydantic handles structural validation (types, required fields).  This
module performs *semantic* checks that go beyond schema correctness ---
for example, warning when no repositories are defined or GitHub
integration is unconfigured.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.config.defaults import DEFAULT_VERIFY_LAYERS

if TYPE_CHECKING:
    from agentkit.config.models import ProjectConfig


def validate_project_config(config: ProjectConfig) -> list[str]:
    """Run semantic validations on a :class:`ProjectConfig`.

    Returns a list of human-readable warning strings.  An empty list
    means no warnings were detected.

    Args:
        config: A structurally valid ``ProjectConfig`` instance.

    Returns:
        A list of warning messages (may be empty).
    """
    warnings: list[str] = []

    # --- Repository checks ---------------------------------------------------
    if not config.repositories:
        warnings.append(
            "No repositories defined. At least one repository is expected "
            "for pipeline execution."
        )

    for repo in config.repositories:
        if repo.test_command is None:
            warnings.append(
                f"Repository '{repo.name}' has no test_command configured. "
                f"Structural verification (Layer 1) will be limited."
            )
        if repo.language is None:
            warnings.append(
                f"Repository '{repo.name}' has no language configured. "
                f"Language-specific analysis may be unavailable."
            )

    # --- GitHub integration ---------------------------------------------------
    if config.github_owner is None or config.github_repo is None:
        warnings.append(
            "GitHub integration is not fully configured (missing github_owner "
            "or github_repo). Issue tracking and closure will be unavailable."
        )

    # --- Pipeline checks ------------------------------------------------------
    if config.pipeline.max_feedback_rounds < 1:
        warnings.append(
            f"max_feedback_rounds is {config.pipeline.max_feedback_rounds}. "
            f"At least 1 round is required for meaningful quality assurance."
        )

    if not config.pipeline.verify_layers:
        warnings.append(
            "No verify_layers configured. The Verify phase will be a no-op."
        )

    unknown_layers = set(config.pipeline.verify_layers) - set(DEFAULT_VERIFY_LAYERS)
    if unknown_layers:
        warnings.append(
            f"Unknown verify layers: {sorted(unknown_layers)}. "
            f"Known layers: {DEFAULT_VERIFY_LAYERS}."
        )

    # --- Story type checks ----------------------------------------------------
    if not config.story_types:
        warnings.append(
            "No story_types configured. The pipeline will reject all stories."
        )

    return warnings
