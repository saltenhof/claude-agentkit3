"""Tests for GuardRunner -- orchestration of governance guards."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.governance.guard_evaluation import HookEvent
from agentkit.backend.governance.guards.artifact_guard import ArtifactGuard
from agentkit.backend.governance.guards.branch_guard import BranchGuard
from agentkit.backend.governance.guards.scope_guard import ScopeGuard
from agentkit.backend.governance.protocols import GuardVerdict, ViolationType
from agentkit.backend.governance.runner import (
    GuardRunner,
    _authoritative_required_roles,
    _event_tool,
    _is_code_producing_story,
    _resolve_local_story_type,
)
from agentkit.backend.state_backend.store import reset_backend_cache_for_tests
from agentkit.backend.state_backend.store.story_repository import StateBackendStoryRepository
from agentkit.backend.story_context_manager.story_model import Story, WireStoryType

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from agentkit.backend.governance.guard_system.records import GuardDecision

_TYPE_TO_WIRE = {
    "implementation": WireStoryType.IMPLEMENTATION,
    "bugfix": WireStoryType.BUGFIX,
    "concept": WireStoryType.CONCEPT,
    "research": WireStoryType.RESEARCH,
}


class _AlwaysAllowGuard:
    """Test guard that always allows."""

    @property
    def name(self) -> str:
        return "always_allow"

    def evaluate(self, operation: str, context: dict[str, object]) -> GuardVerdict:
        return GuardVerdict.allow(self.name)


class _AlwaysBlockGuard:
    """Test guard that always blocks."""

    @property
    def name(self) -> str:
        return "always_block"

    def evaluate(self, operation: str, context: dict[str, object]) -> GuardVerdict:
        return GuardVerdict.block(
            self.name, ViolationType.POLICY_VIOLATION, "blocked",
        )


class _DecisionSink:
    def __init__(self) -> None:
        self.decisions: list[GuardDecision] = []

    def append(self, decision: GuardDecision) -> None:
        self.decisions.append(decision)


class TestGuardRunnerAllAllow:
    """All guards allow -- operation is allowed."""

    def test_all_allow(self) -> None:
        runner = GuardRunner(guards=[_AlwaysAllowGuard(), _AlwaysAllowGuard()])
        allowed, verdicts = runner.is_allowed("any_op", {})
        assert allowed is True
        assert len(verdicts) == 2
        assert all(v.allowed for v in verdicts)


class TestGuardRunnerOneBlocks:
    """One guard blocks -- operation is blocked."""

    def test_one_block(self) -> None:
        runner = GuardRunner(guards=[_AlwaysAllowGuard(), _AlwaysBlockGuard()])
        allowed, verdicts = runner.is_allowed("any_op", {})
        assert allowed is False
        assert len(verdicts) == 2

    def test_block_first_still_runs_all(self) -> None:
        """All guards must run even when the first one blocks."""
        runner = GuardRunner(guards=[_AlwaysBlockGuard(), _AlwaysAllowGuard()])
        allowed, verdicts = runner.is_allowed("any_op", {})
        assert allowed is False
        assert len(verdicts) == 2
        # Second guard must have run and produced an ALLOW.
        assert verdicts[1].allowed is True


class TestGuardRunnerCollectAll:
    """Multiple blocking guards -- all violations collected."""

    def test_two_blocks(self) -> None:
        runner = GuardRunner(guards=[_AlwaysBlockGuard(), _AlwaysBlockGuard()])
        allowed, verdicts = runner.is_allowed("any_op", {})
        assert allowed is False
        assert len(verdicts) == 2
        assert all(not v.allowed for v in verdicts)

    def test_guard_decisions_are_appended_when_scope_is_present(self) -> None:
        sink = _DecisionSink()
        runner = GuardRunner(
            guards=[_AlwaysAllowGuard(), _AlwaysBlockGuard()],
            decision_repo=sink,
        )
        runner.is_allowed(
            "any_op",
            {
                "project_key": "proj",
                "active_story_id": "AG3-087",
                "run_id": "run-1",
                "flow_id": "flow-1",
            },
        )

        assert [d.guard_key for d in sink.decisions] == [
            "always_allow",
            "always_block",
        ]
        assert {d.project_key for d in sink.decisions} == {"proj"}


class TestGuardRunnerEmpty:
    """Empty runner -- no guards, everything allowed."""

    def test_empty_runner(self) -> None:
        runner = GuardRunner()
        allowed, verdicts = runner.is_allowed("any_op", {})
        assert allowed is True
        assert len(verdicts) == 0

    def test_empty_runner_evaluate(self) -> None:
        runner = GuardRunner()
        verdicts = runner.evaluate("any_op", {})
        assert verdicts == []


class TestGuardRunnerRegister:
    """Dynamic guard registration."""

    def test_register_adds_guard(self) -> None:
        runner = GuardRunner()
        runner.register(_AlwaysBlockGuard())
        allowed, verdicts = runner.is_allowed("any_op", {})
        assert allowed is False
        assert len(verdicts) == 1


class TestGuardRunnerWithRealGuards:
    """Integration-like test with real guard implementations."""

    def test_branch_and_artifact_guards(self) -> None:
        runner = GuardRunner(guards=[BranchGuard(), ArtifactGuard()])
        # Force push: BranchGuard blocks, ArtifactGuard allows.
        allowed, verdicts = runner.is_allowed(
            "bash_command", {"command": "git push --force"},
        )
        assert allowed is False
        assert verdicts[0].allowed is False
        assert verdicts[1].allowed is True

    def test_scope_guard_integration(self) -> None:
        runner = GuardRunner(guards=[ScopeGuard(allowed_paths=["/project"])])
        allowed, verdicts = runner.is_allowed(
            "file_write", {"file_path": "/etc/passwd"},
        )
        assert allowed is False


# ---------------------------------------------------------------------------
# AG3-036 FIX-2/FIX-3: authoritative story-type + required-roles resolution
# ---------------------------------------------------------------------------


@pytest.fixture()
def _sqlite_backend(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
    monkeypatch.delenv("AGENTKIT_STATE_DATABASE_URL", raising=False)
    reset_backend_cache_for_tests()
    yield
    reset_backend_cache_for_tests()


_STORY_ID = "AK3-300"


def _save_story(project_root: Path, story_type: str) -> None:
    """Persist a canonical Story record (the authoritative story-type source)."""
    StateBackendStoryRepository(project_root).save(
        Story(
            project_key="p",
            story_number=300,
            story_display_id=_STORY_ID,
            title="t",
            story_type=_TYPE_TO_WIRE[story_type],
            participating_repos=["repo-a"],
            created_at=datetime.now(UTC),
        ),
    )


class TestEventTool:
    """``_event_tool`` derives the canonical tool name (FIX-3)."""

    def test_explicit_tool_name_wins(self) -> None:
        event = HookEvent.model_validate(
            {
                "operation": "unknown_tool",
                "freshness_class": "guarded_read",
                "operation_args": {"tool_name": "WebFetch"},
            }
        )
        assert _event_tool(event) == "WebFetch"

    def test_operation_mapped_to_tool(self) -> None:
        event = HookEvent.model_validate(
            {"operation": "bash_command", "freshness_class": "guarded_read"}
        )
        assert _event_tool(event) == "Bash"


class TestResolveLocalStoryType:
    """``_resolve_local_story_type`` is a TYPED outcome (AG3-036 FIX-A)."""

    def test_research_story_resolves(
        self, tmp_path: Path, _sqlite_backend: None
    ) -> None:
        _save_story(tmp_path, "research")
        resolution = _resolve_local_story_type(_STORY_ID, store_dir=tmp_path)
        assert resolution.resolved is True
        assert resolution.story_type == "research"
        assert resolution.is_code_producing is False

    def test_implementation_is_code_producing_resolution(
        self, tmp_path: Path, _sqlite_backend: None
    ) -> None:
        _save_story(tmp_path, "implementation")
        resolution = _resolve_local_story_type(_STORY_ID, store_dir=tmp_path)
        assert resolution.resolved is True
        assert resolution.is_code_producing is True

    def test_missing_record_is_unresolved(
        self, tmp_path: Path, _sqlite_backend: None
    ) -> None:
        # FIX-A: a missing record is UNRESOLVED, NOT an empty story-type string.
        resolution = _resolve_local_story_type("AK3-999", store_dir=tmp_path)
        assert resolution.resolved is False
        assert resolution.story_type == ""
        assert resolution.is_code_producing is False

    def test_backend_fault_is_unresolved(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # FIX-A: a backend fault is UNRESOLVED (fail-closed downstream), never a
        # silently-downgraded story type. Force the repository read to raise.
        import agentkit.backend.state_backend.store.story_repository as story_repo_mod

        def _boom(self: object, display_id: str) -> object:
            raise RuntimeError("backend down")

        monkeypatch.setattr(
            story_repo_mod.StateBackendStoryRepository,
            "get_by_display_id",
            _boom,
        )
        resolution = _resolve_local_story_type(_STORY_ID, store_dir=tmp_path)
        assert resolution.resolved is False
        assert resolution.is_code_producing is False


class TestIsCodeProducingStory:
    """``_is_code_producing_story`` (FIX-2 fail-closed gate)."""

    def test_implementation_is_code_producing(
        self, tmp_path: Path, _sqlite_backend: None
    ) -> None:
        _save_story(tmp_path, "implementation")
        assert _is_code_producing_story(_STORY_ID, store_dir=tmp_path) is True

    def test_research_is_not_code_producing(
        self, tmp_path: Path, _sqlite_backend: None
    ) -> None:
        _save_story(tmp_path, "research")
        assert _is_code_producing_story(_STORY_ID, store_dir=tmp_path) is False


class TestAuthoritativeRequiredRoles:
    """``_authoritative_required_roles`` (FIX-2)."""

    def _write_config(
        self, project_root: Path, *, required_roles: list[str]
    ) -> None:
        import yaml

        config_dir = project_root / ".agentkit" / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "project.yaml").write_text(
            yaml.safe_dump(
                {
                    "project_key": "p",
                    "project_name": "P",
                    "repositories": [
                        {"name": "r", "path": str(project_root / "r")}
                    ],
                    "story_types": ["concept"],
                    "pipeline": {
                        "config_version": "3.0",
                        "features": {"multi_llm": False},
                        "review": {"required_roles": required_roles},
                    },
                }
            ),
            encoding="utf-8",
        )

    def test_roles_from_config(
        self, tmp_path: Path, _sqlite_backend: None
    ) -> None:
        # A RESOLVED code-producing story yields the configured roles.
        _save_story(tmp_path, "implementation")
        self._write_config(tmp_path, required_roles=["qa", "security"])
        outcome = _authoritative_required_roles(
            project_root=tmp_path, story_id=_STORY_ID
        )
        assert outcome.block is None
        assert outcome.non_code_story is False
        assert outcome.roles == ("qa", "security")

    def test_missing_config_code_story_fails_closed(
        self, tmp_path: Path, _sqlite_backend: None
    ) -> None:
        # Code-producing story + no project.yaml -> fail-closed DENY.
        _save_story(tmp_path, "implementation")
        outcome = _authoritative_required_roles(
            project_root=tmp_path, story_id=_STORY_ID
        )
        assert outcome.block is not None
        assert outcome.block.allowed is False
        assert "review_config_unavailable" in (outcome.block.message or "")

    def test_non_code_story_allows_via_non_code_signal(
        self, tmp_path: Path, _sqlite_backend: None
    ) -> None:
        # RESOLVED research story -> non_code_story allow (ReviewGuard N/A),
        # distinct from the UNRESOLVED block path. Config is never even consulted.
        _save_story(tmp_path, "research")
        outcome = _authoritative_required_roles(
            project_root=tmp_path, story_id=_STORY_ID
        )
        assert outcome.block is None
        assert outcome.non_code_story is True
        assert outcome.roles == ()

    def test_unresolved_story_fails_closed(
        self, tmp_path: Path, _sqlite_backend: None
    ) -> None:
        # FIX-C: a missing record (UNRESOLVED) must fail-closed, NOT downgrade to
        # the non-code allow path.
        outcome = _authoritative_required_roles(
            project_root=tmp_path, story_id="AK3-999"
        )
        assert outcome.non_code_story is False
        assert outcome.block is not None
        assert outcome.block.allowed is False
        assert "story_type_unresolved" in (outcome.block.message or "")

    def test_code_story_empty_required_roles_fails_closed(
        self, tmp_path: Path, _sqlite_backend: None
    ) -> None:
        # FIX-C: a RESOLVED code story with EMPTY required_roles is a fail-closed
        # block (empty coverage is NOT "fully compliant").
        _save_story(tmp_path, "implementation")
        self._write_config(tmp_path, required_roles=[])
        outcome = _authoritative_required_roles(
            project_root=tmp_path, story_id=_STORY_ID
        )
        assert outcome.block is not None
        assert outcome.block.allowed is False
        assert "review_required_roles_empty" in (outcome.block.message or "")

    def test_code_story_with_roles_resolves(
        self, tmp_path: Path, _sqlite_backend: None
    ) -> None:
        # RESOLVED code story + non-empty roles -> the authoritative roles.
        _save_story(tmp_path, "implementation")
        self._write_config(tmp_path, required_roles=["qa"])
        outcome = _authoritative_required_roles(
            project_root=tmp_path, story_id=_STORY_ID
        )
        assert outcome.block is None
        assert outcome.non_code_story is False
        assert outcome.roles == ("qa",)
