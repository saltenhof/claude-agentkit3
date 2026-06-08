from __future__ import annotations

from agentkit.governance.principal_capabilities.operations import (
    OperationClass,
    OperationClassifier,
    _GitVerbs,
)


def test_exit_story_is_admin_subcommand() -> None:
    assert "exit-story" in _GitVerbs.ADMIN_SUBCOMMANDS


def test_agentkit_exit_story_classifies_as_admin_transition() -> None:
    classifier = OperationClassifier()

    result = classifier.classify(
        "bash",
        {
            "command": (
                "agentkit exit-story --story AG3-073 --reason "
                "solution_viability_requires_human_design"
            )
        },
    )

    assert result is OperationClass.ADMIN_TRANSITION
