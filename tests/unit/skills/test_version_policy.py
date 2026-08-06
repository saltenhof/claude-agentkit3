"""Unit proofs for the agent-skills-owned productive bundle floors."""

from __future__ import annotations

import pytest

from agentkit.backend.skills.version_policy import (
    MINIMUM_CONFORM_SKILL_BUNDLE_VERSIONS,
    assess_bundle_version,
)


@pytest.mark.parametrize(
    ("bundle_id", "old_version", "minimum_version"),
    [
        ("concept-incubation-core", "4.0.0", "4.1.0"),
        ("create-userstory-core", "4.1.0", "4.2.0"),
        ("execute-userstory-core", "4.0.0", "4.1.0"),
        ("lookup-userstory-core", "4.0.0", "4.1.0"),
        ("llm-discussion-core", "4.0.0", "4.1.0"),
    ],
)
def test_productive_floor_assessment_is_owned_by_agent_skills(
    bundle_id: str,
    old_version: str,
    minimum_version: str,
) -> None:
    assert MINIMUM_CONFORM_SKILL_BUNDLE_VERSIONS[bundle_id] == minimum_version
    assert assess_bundle_version(bundle_id, old_version) == (
        minimum_version,
        True,
        False,
    )
    assert assess_bundle_version(bundle_id, minimum_version) == (
        minimum_version,
        True,
        True,
    )


def test_productive_floor_assessment_rejects_non_comparable_pin() -> None:
    assert assess_bundle_version("create-userstory-core", "not-a-version") == (
        "4.2.0",
        False,
        False,
    )


def test_bundle_without_floor_is_conform() -> None:
    assert assess_bundle_version("component-architecture-core", "arbitrary") == (
        None,
        True,
        True,
    )
