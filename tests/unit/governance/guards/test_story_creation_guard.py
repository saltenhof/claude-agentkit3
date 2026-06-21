"""Unit tests for :class:`StoryCreationGuard` (FK-31 §31.5 / FK-21 §21.13).

Drives the guard via real :class:`HookEvent`s and the real PrincipalResolver /
OperationClassifier (no fabricated pipeline state, no mocks).
"""

from __future__ import annotations

import pytest

from agentkit.backend.governance.guard_evaluation import HookEvent
from agentkit.backend.governance.guards.story_creation_guard import (
    BLOCK_REASON,
    RULE_ID,
    SKILL_MARKER_VALUE,
    StoryCreationGuard,
)
from agentkit.backend.governance.principal_capabilities import (
    OperationClassifier,
    PrincipalResolver,
)


def _guard() -> StoryCreationGuard:
    return StoryCreationGuard(
        principal_resolver=PrincipalResolver(),
        op_classifier=OperationClassifier(),
    )


def _event(
    *,
    operation: str,
    operation_args: dict[str, object],
    principal_kind: str = "subagent",
    attest: str | None = None,
    extra_cli: list[str] | None = None,
) -> HookEvent:
    cli_args: list[str] = []
    if attest is not None:
        cli_args.extend(["--ak3-principal-attest", attest])
    if extra_cli is not None:
        cli_args.extend(extra_cli)
    return HookEvent.model_validate(
        {
            "operation": operation,
            "operation_args": operation_args,
            "freshness_class": "mutation",
            "cwd": "/proj",
            "principal_kind": principal_kind,
            "cli_args": cli_args or None,
        }
    )


class TestStoryCreationDeny:
    """Direct story-service mutations bypassing the skill are denied.

    These exercise the production-reachable paths (CLI verb, direct DB write).
    The HTTP POST ``/v1/stories`` path is the structural contract for the future
    server/BFF surface and is NOT reachable through a production harness adapter
    today (AG3-033 ERROR C, branch 2) — its detection is pinned in the contract
    test ``tests/contract/governance/test_guard_dispatch.py``, not fabricated
    here as a unit test pretending production coverage.
    """

    def test_cli_story_create_without_marker_denied(self) -> None:
        verdict = _guard().evaluate(
            _event(
                operation="bash_command",
                operation_args={"command": "agentkit story create --title Foo"},
                attest="worker",
            )
        )
        assert verdict.allowed is False

    def test_direct_story_db_insert_via_structured_write_denied(self) -> None:
        # A structured write tool targeting the story-backend SQLite DB under
        # .agentkit (a direct DB mutation bypassing the skill).
        verdict = _guard().evaluate(
            _event(
                operation="file_write",
                operation_args={"file_path": ".agentkit/state.sqlite3"},
                attest="worker",
            )
        )
        assert verdict.allowed is False

    def test_direct_story_db_insert_via_shell_redirect_denied(self) -> None:
        # A shell file mutation (redirect) onto the story-backend SQLite DB is
        # surfaced by bash_mutation_targets and recognised as a direct DB write.
        verdict = _guard().evaluate(
            _event(
                operation="bash_command",
                operation_args={"command": "echo x > .agentkit/state.sqlite3"},
                attest="worker",
            )
        )
        assert verdict.allowed is False

    def test_human_cli_direct_create_denied(self) -> None:
        # AG3-033 ERROR B: human_cli is NOT a direct-create principal. A human
        # creates stories through the create-userstory skill (FK-21 §21.1), not
        # via a raw `agentkit story create` bypass. Without the skill marker the
        # human_cli call is denied.
        verdict = _guard().evaluate(
            _event(
                operation="bash_command",
                operation_args={"command": "agentkit story create --title Foo"},
                principal_kind="main",
                attest="human_cli",
            )
        )
        assert verdict.allowed is False
        assert verdict.detail is not None
        assert verdict.detail["principal"] == "human_cli"

    def test_worker_db_insert_denied_message_and_rule(self) -> None:
        # Pin the opaque block reason + rule id on a production-reachable path.
        verdict = _guard().evaluate(
            _event(
                operation="file_write",
                operation_args={"file_path": ".agentkit/state.sqlite3"},
                attest="worker",
            )
        )
        assert verdict.allowed is False
        assert verdict.guard_name == "story_creation_guard"
        assert verdict.message == BLOCK_REASON
        assert verdict.detail is not None
        assert verdict.detail["rule_id"] == RULE_ID


class TestStoryCreationAllow:
    """Skill marker, direct-create principals and non-story mutations are allowed."""

    def test_cli_story_create_with_skill_flag_allowed(self) -> None:
        verdict = _guard().evaluate(
            _event(
                operation="bash_command",
                operation_args={"command": "agentkit story create --title Foo"},
                attest="worker",
                extra_cli=[f"--via-skill={SKILL_MARKER_VALUE}"],
            )
        )
        assert verdict.allowed is True

    @pytest.mark.parametrize(
        "principal",
        ["pipeline_deterministic", "admin_service"],
    )
    def test_direct_create_principal_cli_create_allowed(self, principal: str) -> None:
        # FK-31 §31.5.4: ONLY Zone-2 pipeline + official admin (split/reset).
        verdict = _guard().evaluate(
            _event(
                operation="bash_command",
                operation_args={"command": "agentkit story create --title Foo"},
                principal_kind="main",
                attest=principal,
            )
        )
        assert verdict.allowed is True

    def test_unrelated_write_allowed(self) -> None:
        verdict = _guard().evaluate(
            _event(
                operation="file_write",
                operation_args={"file_path": "src/agentkit/backend/module.py"},
                attest="worker",
            )
        )
        assert verdict.allowed is True
