"""Tests for GuardRunner -- orchestration of governance guards."""

from __future__ import annotations

from typing import TYPE_CHECKING

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

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

    from agentkit.backend.governance.guard_system.records import GuardDecision


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


_STORY_ID = "AK3-300"
_PROJECT_KEY = "p"


def _patch_story_type(
    monkeypatch: pytest.MonkeyPatch,
    *,
    story_type: str | None = None,
    fault: bool = False,
) -> None:
    """Route the story-type read seam to a first-class fake client (AG3-129).

    ``_resolve_local_story_type`` reads the story type over REST via
    ``rest_edge.governance_edge_client`` (FK-10 §10.1.0 I1), so these unit tests
    patch that seam with a fake returning a story type, ``None`` (missing record)
    or raising (transport/core fault) instead of opening a database.
    """
    from agentkit.backend.governance import rest_edge

    class _FakeClient:
        def get_story_type(
            self, *, project_key: str, story_id: str
        ) -> str | None:
            _ = project_key, story_id
            if fault:
                raise RuntimeError("core unreachable")
            return story_type

    monkeypatch.setattr(
        rest_edge, "governance_edge_client", lambda project_root: _FakeClient()
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
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_story_type(monkeypatch, story_type="research")
        resolution = _resolve_local_story_type(
            _STORY_ID, project_key=_PROJECT_KEY, project_root=tmp_path
        )
        assert resolution.resolved is True
        assert resolution.story_type == "research"
        assert resolution.is_code_producing is False

    def test_implementation_is_code_producing_resolution(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_story_type(monkeypatch, story_type="implementation")
        resolution = _resolve_local_story_type(
            _STORY_ID, project_key=_PROJECT_KEY, project_root=tmp_path
        )
        assert resolution.resolved is True
        assert resolution.is_code_producing is True

    def test_missing_record_is_unresolved(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # FIX-A: a missing record is UNRESOLVED, NOT an empty story-type string.
        _patch_story_type(monkeypatch, story_type=None)
        resolution = _resolve_local_story_type(
            "AK3-999", project_key=_PROJECT_KEY, project_root=tmp_path
        )
        assert resolution.resolved is False
        assert resolution.story_type == ""
        assert resolution.is_code_producing is False

    def test_backend_fault_is_unresolved(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A core/transport fault is UNRESOLVED (fail-closed downstream), never a
        # silently-downgraded story type. Force the REST read to raise (AG3-129).
        _patch_story_type(monkeypatch, fault=True)
        resolution = _resolve_local_story_type(
            _STORY_ID, project_key=_PROJECT_KEY, project_root=tmp_path
        )
        assert resolution.resolved is False
        assert resolution.is_code_producing is False


class TestIsCodeProducingStory:
    """``_is_code_producing_story`` (FIX-2 fail-closed gate)."""

    def test_implementation_is_code_producing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_story_type(monkeypatch, story_type="implementation")
        assert (
            _is_code_producing_story(
                _STORY_ID, project_key=_PROJECT_KEY, project_root=tmp_path
            )
            is True
        )

    def test_research_is_not_code_producing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_story_type(monkeypatch, story_type="research")
        assert (
            _is_code_producing_story(
                _STORY_ID, project_key=_PROJECT_KEY, project_root=tmp_path
            )
            is False
        )


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
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A RESOLVED code-producing story yields the configured roles.
        _patch_story_type(monkeypatch, story_type="implementation")
        self._write_config(tmp_path, required_roles=["qa", "security"])
        outcome = _authoritative_required_roles(
            project_root=tmp_path, project_key=_PROJECT_KEY, story_id=_STORY_ID
        )
        assert outcome.block is None
        assert outcome.non_code_story is False
        assert outcome.roles == ("qa", "security")

    def test_missing_config_code_story_fails_closed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Code-producing story + no project.yaml -> fail-closed DENY.
        _patch_story_type(monkeypatch, story_type="implementation")
        outcome = _authoritative_required_roles(
            project_root=tmp_path, project_key=_PROJECT_KEY, story_id=_STORY_ID
        )
        assert outcome.block is not None
        assert outcome.block.allowed is False
        assert "review_config_unavailable" in (outcome.block.message or "")

    def test_non_code_story_allows_via_non_code_signal(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # RESOLVED research story -> non_code_story allow (ReviewGuard N/A),
        # distinct from the UNRESOLVED block path. Config is never even consulted.
        _patch_story_type(monkeypatch, story_type="research")
        outcome = _authoritative_required_roles(
            project_root=tmp_path, project_key=_PROJECT_KEY, story_id=_STORY_ID
        )
        assert outcome.block is None
        assert outcome.non_code_story is True
        assert outcome.roles == ()

    def test_unresolved_story_fails_closed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # FIX-C: a missing record (UNRESOLVED) must fail-closed, NOT downgrade to
        # the non-code allow path.
        _patch_story_type(monkeypatch, story_type=None)
        outcome = _authoritative_required_roles(
            project_root=tmp_path, project_key=_PROJECT_KEY, story_id="AK3-999"
        )
        assert outcome.non_code_story is False
        assert outcome.block is not None
        assert outcome.block.allowed is False
        assert "story_type_unresolved" in (outcome.block.message or "")

    def test_code_story_empty_required_roles_fails_closed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # FIX-C: a RESOLVED code story with EMPTY required_roles is a fail-closed
        # block (empty coverage is NOT "fully compliant").
        _patch_story_type(monkeypatch, story_type="implementation")
        self._write_config(tmp_path, required_roles=[])
        outcome = _authoritative_required_roles(
            project_root=tmp_path, project_key=_PROJECT_KEY, story_id=_STORY_ID
        )
        assert outcome.block is not None
        assert outcome.block.allowed is False
        assert "review_required_roles_empty" in (outcome.block.message or "")

    def test_code_story_with_roles_resolves(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # RESOLVED code story + non-empty roles -> the authoritative roles.
        _patch_story_type(monkeypatch, story_type="implementation")
        self._write_config(tmp_path, required_roles=["qa"])
        outcome = _authoritative_required_roles(
            project_root=tmp_path, project_key=_PROJECT_KEY, story_id=_STORY_ID
        )
        assert outcome.block is None
        assert outcome.non_code_story is False
        assert outcome.roles == ("qa",)
