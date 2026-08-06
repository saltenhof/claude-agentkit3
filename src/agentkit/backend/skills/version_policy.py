"""Productive version policy for immutable skill bundles."""

from __future__ import annotations

from typing import NamedTuple

from packaging.version import InvalidVersion, Version

from agentkit.backend.skills.errors import SkillBindingFailedError

# Lowest immutable bundle version that may be bound productively. Agent-skills
# owns bundle versioning and pin verification; installer and CI are consumers.
# A floor exists only when an older bundle executes a path the norm abolished.
MINIMUM_CONFORM_SKILL_BUNDLE_VERSIONS: dict[str, str] = {
    "concept-incubation-core": "4.1.0",
    "create-userstory-core": "4.2.0",
    "execute-userstory-core": "4.1.0",
    "lookup-userstory-core": "4.1.0",
    "llm-discussion-core": "4.1.0",
}


class BundleVersionAssessment(NamedTuple):
    """Result of comparing one immutable bundle version with its floor."""

    minimum_version: str | None
    is_comparable: bool
    is_conform: bool


class BundleVersionPolicyError(ValueError):
    """Raised when the owner itself declares an invalid version floor."""


def assess_bundle_version(
    bundle_id: str,
    bundle_version: str,
) -> BundleVersionAssessment:
    """Assess a bundle version against the single productive floor policy.

    A bundle without a declared floor is conform. A candidate that cannot be
    compared with a declared floor is explicitly non-conform and
    non-comparable. An invalid owner-declared floor is a policy error rather
    than a candidate finding.
    """
    minimum_version = MINIMUM_CONFORM_SKILL_BUNDLE_VERSIONS.get(bundle_id)
    if minimum_version is None:
        return BundleVersionAssessment(None, True, True)
    try:
        floor = Version(minimum_version)
    except InvalidVersion as exc:
        raise BundleVersionPolicyError(
            f"Invalid minimum conform version {bundle_id}@{minimum_version}",
        ) from exc
    try:
        candidate = Version(bundle_version)
    except InvalidVersion:
        return BundleVersionAssessment(minimum_version, False, False)
    return BundleVersionAssessment(
        minimum_version,
        True,
        candidate >= floor,
    )


def _reject_norm_violating_bundle_version(
    skill_name: str,
    bundle_id: str,
    bundle_version: str,
) -> None:
    """Reject a productive binding below its agent-skills-owned version floor."""
    assessment = assess_bundle_version(bundle_id, bundle_version)
    floor = assessment.minimum_version
    if floor is None:
        return
    if not assessment.is_comparable:
        raise SkillBindingFailedError(
            f"Skill {skill_name!r} pin {bundle_version!r} is not a comparable version",
        )
    if not assessment.is_conform:
        raise SkillBindingFailedError(
            f"Skill {skill_name!r} is pinned to {bundle_id}@{bundle_version}, "
            f"which is below the minimum conform version {floor}: that bundle still carries a "
            "path the norm abolished. Rebind the skill to pick up the conform bundle.",
        )


__all__ = [
    "BundleVersionAssessment",
    "BundleVersionPolicyError",
    "MINIMUM_CONFORM_SKILL_BUNDLE_VERSIONS",
    "assess_bundle_version",
]
