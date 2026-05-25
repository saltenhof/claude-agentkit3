"""Unit tests for Governance.register_hooks (AG3-031 §2.1.4).

Uses a Recording-Repository test double (not MagicMock) per project rules.

AG3-031 Pass-2 FK-30-Korrektur 2026-05-24:
  HookDefinition fields updated to FK-30 §30.3.1 (hook_event_name, matcher,
  command).  HookId updated to 11 FK-30 §30.5.1 values.

AG3-031 Pass-3 FK-30-Korrektur 2026-05-24:
  Fix E1: project_key removed from register_hooks signature.
  Fix E2: settings materialisation — tests pass tmp_path as project_root.
  Fix E3: UPSERT semantics in recording double + new overwrite test.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from agentkit.governance.hook_registration import (
    HookDefinition,
    HookEventName,
    HookId,
    RegistrationResult,
)

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.governance.locks import LockRecordId

# ---------------------------------------------------------------------------
# Recording test doubles (no MagicMock per project rules)
# ---------------------------------------------------------------------------


class _RecordingHookRepo:
    """In-memory recording double for HookRegistrationRepository."""

    def __init__(self) -> None:
        # Key: (project_key, hook_event_name, matcher, command).
        # AG3-031 Hotfix 2026-05-25: command is part of the identity, mirroring
        # the StateBackendHookRegistrationRepository PK. FK-30 §30.3.1 registers
        # several hooks under one matcher (e.g. "Bash" hosts branch_guard AND
        # story_creation_guard); a matcher-only key collapsed them.
        self._registered: dict[tuple[str, str, str, str], HookDefinition] = {}
        self.register_calls: list[tuple[str, list[HookDefinition]]] = []

    def register(
        self,
        project_key: str,
        hook_definitions: list[HookDefinition],
    ) -> RegistrationResult:
        self.register_calls.append((project_key, hook_definitions))
        registered: list[str] = []
        skipped: list[str] = []

        for defn in hook_definitions:
            key = (
                project_key,
                defn.hook_event_name.value,
                defn.matcher,
                defn.command,
            )
            if key in self._registered:
                # Identical 4-tuple — skip (idempotent)
                skipped.append(defn.matcher)
            else:
                # New (matcher, command) combination — register
                self._registered[key] = defn
                registered.append(defn.matcher)

        return RegistrationResult(
            registered=registered,
            skipped=skipped,
            errors=[],
        )

    def list_for_project(self, project_key: str) -> list[HookDefinition]:
        return [
            v for (pk, _, _, _), v in self._registered.items() if pk == project_key
        ]

    def clear_for_project(self, project_key: str) -> None:
        keys_to_remove = [k for k in self._registered if k[0] == project_key]
        for k in keys_to_remove:
            del self._registered[k]


class _RecordingLockRepo:
    """Stub lock repo (unused in register_hooks tests)."""

    def deactivate_locks_for_story(self, story_id: str) -> list[LockRecordId]:
        return []


class _StubWorktreeRepo:
    """Stub worktree repo (unused in register_hooks tests — E9 AG3-031 Pass-5).

    Required because Governance.worktree_repo is now mandatory.
    """

    def list_worktree_paths(self, story_id: str) -> list:
        return []


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _all_hooks_pre_tool_use() -> list[HookDefinition]:
    """Build a PreToolUse HookDefinition for every HookId."""
    return [
        HookDefinition(
            hook_event_name=HookEventName.PRE_TOOL_USE,
            matcher="Bash",
            command=f"agentkit-hook-claude pre {hid}",
        )
        # Use unique matchers by embedding hook_id to avoid collisions
        # since matcher is the unique key alongside hook_event_name.
        # Actually, matchers can repeat; we need distinct (hook_event_name, matcher)
        # combos. Use unique command-based matchers per hook.
        for hid in HookId
    ]


def _sample_hooks() -> list[HookDefinition]:
    """Build one HookDefinition per HookId with distinct matchers."""
    return [
        HookDefinition(
            hook_event_name=HookEventName.PRE_TOOL_USE,
            matcher=hid.value,  # use hook_id string as matcher to guarantee uniqueness
            command=f"agentkit-hook-claude pre {hid.value}",
        )
        for hid in HookId
    ]


def _make_governance(
    hook_repo: _RecordingHookRepo | None = None,
    project_root: Path | None = None,
) -> object:
    """Return a Governance instance with recording doubles."""
    from pathlib import Path

    from agentkit.governance.runner import Governance

    repo = hook_repo or _RecordingHookRepo()
    return Governance(
        hook_repo=repo,
        lock_repo=_RecordingLockRepo(),  # type: ignore[arg-type]
        project_key="test-project",
        project_root=project_root or Path("."),
        worktree_repo=_StubWorktreeRepo(),  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# Tests: happy path
# ---------------------------------------------------------------------------


class TestRegisterHooksHappyPath:
    """register_hooks with all 11 hook IDs succeeds."""

    def test_all_hook_ids_registered(self, tmp_path: Path) -> None:
        repo = _RecordingHookRepo()
        gov = _make_governance(repo, project_root=tmp_path)
        definitions = _sample_hooks()

        result = gov.register_hooks(definitions)  # type: ignore[union-attr]

        assert len(result.registered) == len(HookId)
        assert result.skipped == []
        assert result.errors == []

    def test_register_calls_repo_once(self, tmp_path: Path) -> None:
        repo = _RecordingHookRepo()
        gov = _make_governance(repo, project_root=tmp_path)
        definitions = _sample_hooks()

        gov.register_hooks(definitions)  # type: ignore[union-attr]

        assert len(repo.register_calls) == 1

    def test_project_key_passed_to_repo(self, tmp_path: Path) -> None:
        repo = _RecordingHookRepo()
        gov = _make_governance(repo, project_root=tmp_path)
        definitions = _sample_hooks()

        gov.register_hooks(definitions)  # type: ignore[union-attr]

        project_key_used, _ = repo.register_calls[0]
        assert project_key_used == "test-project"

    def test_project_key_comes_from_init(self, tmp_path: Path) -> None:
        """FK-30 §30.3.1 Fix E1: no project_key parameter on register_hooks.

        The project_key must be supplied at Governance.__init__ time;
        register_hooks(hook_definitions) takes no project_key argument.
        """
        repo = _RecordingHookRepo()
        gov = _make_governance(repo, project_root=tmp_path)
        definitions = _sample_hooks()

        gov.register_hooks(definitions)  # type: ignore[union-attr]

        project_key_used, _ = repo.register_calls[0]
        assert project_key_used == "test-project"


# ---------------------------------------------------------------------------
# Tests: idempotency
# ---------------------------------------------------------------------------


class TestRegisterHooksIdempotency:
    """Duplicate registration reports skipped, not error."""

    def test_idempotent_second_call_all_skipped(self, tmp_path: Path) -> None:
        repo = _RecordingHookRepo()
        gov = _make_governance(repo, project_root=tmp_path)
        definitions = _sample_hooks()

        gov.register_hooks(definitions)  # type: ignore[union-attr]
        result2 = gov.register_hooks(definitions)  # type: ignore[union-attr]

        assert len(result2.skipped) == len(HookId)
        assert result2.registered == []
        assert result2.errors == []

    def test_partial_re_registration(self, tmp_path: Path) -> None:
        """Only new definitions are registered; identical existing ones are skipped."""
        repo = _RecordingHookRepo()
        gov = _make_governance(repo, project_root=tmp_path)
        first_batch = [
            HookDefinition(
                hook_event_name=HookEventName.PRE_TOOL_USE,
                matcher="Bash",
                command="agentkit-hook-claude pre branch_guard",
            )
        ]
        second_batch = [
            HookDefinition(
                hook_event_name=HookEventName.PRE_TOOL_USE,
                matcher="Bash",
                command="agentkit-hook-claude pre branch_guard",
            ),
            HookDefinition(
                hook_event_name=HookEventName.PRE_TOOL_USE,
                matcher="Bash|Write|Edit|Read|Grep|Glob|Agent",
                command="agentkit-hook-claude pre health_monitor",
            ),
        ]

        gov.register_hooks(first_batch)  # type: ignore[union-attr]
        result = gov.register_hooks(second_batch)  # type: ignore[union-attr]

        assert "Bash" in result.skipped
        assert "Bash|Write|Edit|Read|Grep|Glob|Agent" in result.registered

    def test_changed_command_overwrites_not_skips(self, tmp_path: Path) -> None:
        """Changed command on same matcher → registered (overwrite), not skipped.

        Fix E3 (AG3-031 Pass-3 FK-30 §30.3.1): UPSERT semantics.
        """
        repo = _RecordingHookRepo()
        gov = _make_governance(repo, project_root=tmp_path)

        first = [
            HookDefinition(
                hook_event_name=HookEventName.PRE_TOOL_USE,
                matcher="Bash",
                command="agentkit-hook-claude pre branch_guard",
            )
        ]
        updated = [
            HookDefinition(
                hook_event_name=HookEventName.PRE_TOOL_USE,
                matcher="Bash",
                command="agentkit-hook-claude pre branch_guard --verbose",  # changed
            )
        ]

        gov.register_hooks(first)  # type: ignore[union-attr]
        result = gov.register_hooks(updated)  # type: ignore[union-attr]

        assert "Bash" in result.registered, "Changed command must be registered (overwrite)"
        assert result.skipped == [], "Changed command must NOT be skipped"


# ---------------------------------------------------------------------------
# Tests: settings materialisation (Fix E2 — FK-30 §30.3.1)
# ---------------------------------------------------------------------------


class TestRegisterHooksSettingsMaterialisation:
    """register_hooks writes .claude/settings.json after backend persist (Fix E2)."""

    def test_settings_json_created_after_register(self, tmp_path: Path) -> None:
        """After register_hooks, .claude/settings.json exists with hooks section."""
        import json

        repo = _RecordingHookRepo()
        gov = _make_governance(repo, project_root=tmp_path)
        definitions = [
            HookDefinition(
                hook_event_name=HookEventName.PRE_TOOL_USE,
                matcher="Bash",
                command="agentkit-hook-claude pre branch_guard",
            )
        ]

        gov.register_hooks(definitions)  # type: ignore[union-attr]

        settings_path = tmp_path / ".claude" / "settings.json"
        assert settings_path.exists(), ".claude/settings.json must be created"
        data = json.loads(settings_path.read_text(encoding="utf-8"))
        assert "hooks" in data
        assert "PreToolUse" in data["hooks"]
        entries = data["hooks"]["PreToolUse"]
        assert any(
            e["matcher"] == "Bash" and "branch_guard" in e["command"]
            for e in entries
        )

    def test_settings_json_schema_correct(self, tmp_path: Path) -> None:
        """Written settings.json has the FK-30 §30.3.1 schema."""
        import json

        repo = _RecordingHookRepo()
        gov = _make_governance(repo, project_root=tmp_path)
        definitions = [
            HookDefinition(
                hook_event_name=HookEventName.PRE_TOOL_USE,
                matcher="Bash",
                command="agentkit-hook-claude pre branch_guard",
            ),
            HookDefinition(
                hook_event_name=HookEventName.POST_TOOL_USE,
                matcher="Agent|Bash|*_send",
                command="agentkit-hook-claude post telemetry",
            ),
        ]

        gov.register_hooks(definitions)  # type: ignore[union-attr]

        data = json.loads(
            (tmp_path / ".claude" / "settings.json").read_text(encoding="utf-8")
        )
        # FK-30 §30.3.1 schema: {hooks: {PreToolUse: [{matcher, command}], ...}}
        pre_entries = data["hooks"]["PreToolUse"]
        post_entries = data["hooks"]["PostToolUse"]
        assert all("matcher" in e and "command" in e for e in pre_entries)
        assert all("matcher" in e and "command" in e for e in post_entries)

    def test_broken_settings_json_raises(self, tmp_path: Path) -> None:
        """Broken existing .claude/settings.json raises (fail-closed FK-30 §30.3.1 Z.339)."""
        settings_path = tmp_path / ".claude" / "settings.json"
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_path.write_text("{ invalid json {{", encoding="utf-8")

        repo = _RecordingHookRepo()
        gov = _make_governance(repo, project_root=tmp_path)
        definitions = [
            HookDefinition(
                hook_event_name=HookEventName.PRE_TOOL_USE,
                matcher="Bash",
                command="agentkit-hook-claude pre branch_guard",
            )
        ]

        with pytest.raises(ValueError, match="Invalid JSON|broken"):
            gov.register_hooks(definitions)  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Tests: validation errors (Pydantic)
# ---------------------------------------------------------------------------


class TestHookDefinitionValidation:
    """HookDefinition rejects invalid hook_event_name values and extra fields."""

    def test_unknown_hook_event_name_raises(self) -> None:
        import pydantic

        with pytest.raises(pydantic.ValidationError):
            HookDefinition(
                hook_event_name="UnknownEvent",  # type: ignore[arg-type]
                matcher="Bash",
                command="cmd",
            )

    def test_extra_fields_forbidden(self) -> None:
        import pydantic

        with pytest.raises(pydantic.ValidationError):
            HookDefinition(
                hook_event_name=HookEventName.PRE_TOOL_USE,
                matcher="Bash",
                command="cmd",
                extra_field="not_allowed",  # type: ignore[call-arg]
            )

    def test_frozen_model_immutable(self) -> None:
        import pydantic

        defn = HookDefinition(
            hook_event_name=HookEventName.PRE_TOOL_USE,
            matcher="Bash",
            command="cmd",
        )
        with pytest.raises(pydantic.ValidationError):
            defn.hook_event_name = HookEventName.POST_TOOL_USE  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Tests: HookId enum has exactly 11 values (FK-30 §30.5.1)
# ---------------------------------------------------------------------------


class TestHookIdEnum:
    """HookId has the canonical 11 hook IDs from FK-30 §30.5.1."""

    def test_all_eleven_hook_ids_present(self) -> None:
        expected = {
            "branch_guard",
            "orchestrator_guard",
            "integrity",
            "qa_agent_guard",
            "adversarial_guard",
            "self_protection",
            "story_creation_guard",
            "budget",
            "skill_usage_check",
            "health_monitor",
            "ccag_gatekeeper",
        }
        actual = {hid.value for hid in HookId}
        assert actual == expected

    def test_hook_id_count(self) -> None:
        assert len(HookId) == 11

    def test_ccag_gatekeeper_present(self) -> None:
        assert HookId.CCAG_GATEKEEPER in HookId
        assert HookId.CCAG_GATEKEEPER.value == "ccag_gatekeeper"

    def test_integrity_wortgleich(self) -> None:
        """FK-30 §30.5.1 uses 'integrity' not 'integrity_guard'."""
        assert HookId.INTEGRITY.value == "integrity"

    def test_self_protection_wortgleich(self) -> None:
        """FK-30 §30.5.1 uses 'self_protection' not 'self_protection_guard'."""
        assert HookId.SELF_PROTECTION.value == "self_protection"

    def test_budget_wortgleich(self) -> None:
        """FK-30 §30.5.1 uses 'budget' not 'budget_guard'."""
        assert HookId.BUDGET.value == "budget"

    def test_skill_usage_check_present(self) -> None:
        """skill_usage_check was missing in Pass-1; must be present now."""
        assert HookId.SKILL_USAGE_CHECK in HookId
        assert HookId.SKILL_USAGE_CHECK.value == "skill_usage_check"


# ---------------------------------------------------------------------------
# Tests: shared-matcher governance hole (AG3-031 Hotfix 2026-05-25)
# ---------------------------------------------------------------------------


class TestRegisterHooksSharedMatcherGovernanceHole:
    """Hooks sharing a matcher must not collapse into one.

    FK-30 §30.3.1 registers multiple distinct hooks under the same matcher:
    ``Bash`` hosts both branch_guard and story_creation_guard;
    ``Write|Edit`` hosts qa_agent_guard and adversarial_guard; etc.
    The pre-hotfix UPSERT keyed on matcher alone silently overwrote one with
    the other, leaving 4 of 11 guards unregistered (governance hole).
    Identity is now (event, matcher, command).
    """

    @staticmethod
    def _shared_matcher_hooks() -> list[HookDefinition]:
        # Three matcher groups each hosting two distinct guards (FK-30 §30.3.1).
        pairs = [
            ("Bash", "branch_guard", "story_creation_guard"),
            ("Write|Edit", "qa_agent_guard", "adversarial_guard"),
            (
                "Bash|Write|Edit|Read|Grep|Glob|Agent",
                "health_monitor",
                "ccag_gatekeeper",
            ),
        ]
        defs: list[HookDefinition] = []
        for matcher, guard_a, guard_b in pairs:
            defs.append(
                HookDefinition(
                    hook_event_name=HookEventName.PRE_TOOL_USE,
                    matcher=matcher,
                    command=f"agentkit-hook-claude pre {guard_a}",
                )
            )
            defs.append(
                HookDefinition(
                    hook_event_name=HookEventName.PRE_TOOL_USE,
                    matcher=matcher,
                    command=f"agentkit-hook-claude pre {guard_b}",
                )
            )
        return defs

    def test_shared_matcher_hooks_all_persisted_in_settings(
        self, tmp_path: Path
    ) -> None:
        """All six shared-matcher hooks survive in .claude/settings.json."""
        import json

        repo = _RecordingHookRepo()
        gov = _make_governance(repo, project_root=tmp_path)

        gov.register_hooks(self._shared_matcher_hooks())  # type: ignore[union-attr]

        data = json.loads(
            (tmp_path / ".claude" / "settings.json").read_text(encoding="utf-8")
        )
        commands = {e["command"] for e in data["hooks"]["PreToolUse"]}
        for guard in (
            "branch_guard",
            "story_creation_guard",
            "qa_agent_guard",
            "adversarial_guard",
            "health_monitor",
            "ccag_gatekeeper",
        ):
            assert f"agentkit-hook-claude pre {guard}" in commands, (
                f"{guard} must survive — shared-matcher collapse is the hole"
            )
        # Two distinct Bash entries, not one (collapse would leave one).
        bash_entries = [
            e for e in data["hooks"]["PreToolUse"] if e["matcher"] == "Bash"
        ]
        assert len(bash_entries) == 2

    def test_shared_matcher_hooks_all_registered_in_repo(
        self, tmp_path: Path
    ) -> None:
        """The recording repo keeps all six (4-tuple identity)."""
        repo = _RecordingHookRepo()
        gov = _make_governance(repo, project_root=tmp_path)

        result = gov.register_hooks(self._shared_matcher_hooks())  # type: ignore[union-attr]

        assert len(result.registered) == 6
        assert result.skipped == []
        listed = repo.list_for_project("test-project")
        assert len(listed) == 6
