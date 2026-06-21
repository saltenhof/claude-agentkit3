"""Unit tests for StateBackendHookRegistrationRepository (AG3-031 §2.1.4).

SQLite-only (AGENTKIT_ALLOW_SQLITE=1); Postgres tests are opt-in and
skipped when AGENTKIT_STATE_DATABASE_URL is not set.

AG3-031 Pass-2 FK-30-Korrektur 2026-05-24:
  Schema updated to (project_key, hook_event_name, matcher, command)
  per FK-30 §30.3.1.  Tests use new HookDefinition fields.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from agentkit.backend.governance.hook_registration import (
    HookDefinition,
    HookEventName,
    HookId,
)
from agentkit.backend.state_backend.config import (
    ALLOW_SQLITE_ENV,
    STATE_BACKEND_ENV,
    STATE_DATABASE_URL_ENV,
)
from agentkit.backend.state_backend.store.governance_hook_repository import (
    StateBackendHookRegistrationRepository,
)

if TYPE_CHECKING:
    from collections.abc import Generator

import os

_PROJECT_KEY = "test-gov-proj"


def _sample_definition(
    hook_event_name: HookEventName = HookEventName.PRE_TOOL_USE,
    matcher: str = "Bash",
    command: str = "agentkit-hook-claude pre branch_guard",
) -> HookDefinition:
    return HookDefinition(
        hook_event_name=hook_event_name,
        matcher=matcher,
        command=command,
    )


def _all_hook_definitions() -> list[HookDefinition]:
    """Build one HookDefinition per HookId with distinct matchers."""
    return [
        HookDefinition(
            hook_event_name=HookEventName.PRE_TOOL_USE,
            matcher=hid.value,  # use hook_id string as matcher for uniqueness
            command=f"agentkit-hook-claude pre {hid.value}",
        )
        for hid in HookId
    ]


# ---------------------------------------------------------------------------
# SQLite fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def sqlite_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Generator[Path, None, None]:
    monkeypatch.setenv(STATE_BACKEND_ENV, "sqlite")
    monkeypatch.setenv(ALLOW_SQLITE_ENV, "1")
    yield tmp_path


@pytest.fixture()
def sqlite_repo(sqlite_env: Path) -> StateBackendHookRegistrationRepository:
    return StateBackendHookRegistrationRepository(store_dir=sqlite_env)


# ---------------------------------------------------------------------------
# Postgres fixtures
# ---------------------------------------------------------------------------


def _has_postgres_url() -> bool:
    return bool(os.environ.get(STATE_DATABASE_URL_ENV, ""))


@pytest.fixture()
def postgres_env(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    if not _has_postgres_url():
        pytest.skip("AGENTKIT_STATE_DATABASE_URL not set — Postgres test skipped")
    monkeypatch.setenv(STATE_BACKEND_ENV, "postgres")
    yield


@pytest.fixture()
def postgres_repo(postgres_env: None) -> StateBackendHookRegistrationRepository:
    return StateBackendHookRegistrationRepository()


# ---------------------------------------------------------------------------
# Parametrize over both backends
# ---------------------------------------------------------------------------


@pytest.fixture(params=["sqlite", "postgres"])
def repo(
    request: pytest.FixtureRequest,
    sqlite_repo: StateBackendHookRegistrationRepository,
) -> Generator[StateBackendHookRegistrationRepository, None, None]:
    if request.param == "postgres":
        if not _has_postgres_url():
            pytest.skip("AGENTKIT_STATE_DATABASE_URL not set")
        postgres_r = StateBackendHookRegistrationRepository()
        postgres_r.clear_for_project(_PROJECT_KEY)
        yield postgres_r
        postgres_r.clear_for_project(_PROJECT_KEY)
    else:
        sqlite_repo.clear_for_project(_PROJECT_KEY)
        yield sqlite_repo
        sqlite_repo.clear_for_project(_PROJECT_KEY)


# ---------------------------------------------------------------------------
# Tests: happy-path roundtrip
# ---------------------------------------------------------------------------


class TestGovernanceHookRepositoryRoundtrip:
    """Roundtrip: register then list returns same definitions."""

    def test_register_and_list_single(
        self,
        repo: StateBackendHookRegistrationRepository,
    ) -> None:
        defn = _sample_definition()
        result = repo.register(_PROJECT_KEY, [defn])

        assert "Bash" in result.registered
        assert result.skipped == []
        assert result.errors == []

        listed = repo.list_for_project(_PROJECT_KEY)
        assert len(listed) == 1
        assert listed[0].hook_event_name == HookEventName.PRE_TOOL_USE
        assert listed[0].matcher == "Bash"
        assert listed[0].command == "agentkit-hook-claude pre branch_guard"

    def test_register_all_hooks(
        self,
        repo: StateBackendHookRegistrationRepository,
    ) -> None:
        definitions = _all_hook_definitions()
        result = repo.register(_PROJECT_KEY, definitions)

        assert len(result.registered) == len(HookId)
        assert result.skipped == []
        assert result.errors == []

        listed = repo.list_for_project(_PROJECT_KEY)
        assert len(listed) == len(HookId)

    def test_schema_fields_preserved(
        self,
        repo: StateBackendHookRegistrationRepository,
    ) -> None:
        """FK-30 §30.3.1 fields hook_event_name, matcher, command roundtrip correctly."""
        defn = HookDefinition(
            hook_event_name=HookEventName.POST_TOOL_USE,
            matcher="Agent|Bash|*_send",
            command="agentkit-hook-claude post telemetry",
        )
        repo.register(_PROJECT_KEY, [defn])
        listed = repo.list_for_project(_PROJECT_KEY)

        assert len(listed) == 1
        assert listed[0].hook_event_name == HookEventName.POST_TOOL_USE
        assert listed[0].matcher == "Agent|Bash|*_send"
        assert listed[0].command == "agentkit-hook-claude post telemetry"

    def test_post_tool_use_failure_event_roundtrips(
        self,
        repo: StateBackendHookRegistrationRepository,
    ) -> None:
        defn = HookDefinition(
            hook_event_name=HookEventName.POST_TOOL_USE_FAILURE,
            matcher="Bash",
            command="agentkit-hook-claude post health_monitor",
        )

        result = repo.register(_PROJECT_KEY, [defn])
        listed = repo.list_for_project(_PROJECT_KEY)

        assert result.errors == []
        assert listed[0].hook_event_name == HookEventName.POST_TOOL_USE_FAILURE
        assert listed[0].matcher == "Bash"
        assert listed[0].command == "agentkit-hook-claude post health_monitor"


# ---------------------------------------------------------------------------
# Tests: idempotency / UNIQUE constraint on (project_key, hook_event_name, matcher)
# ---------------------------------------------------------------------------


class TestGovernanceHookRepositoryIdempotency:
    """Second register of same (project_key, hook_event_name, matcher) -> skipped."""

    def test_second_register_skips_unchanged(
        self,
        repo: StateBackendHookRegistrationRepository,
    ) -> None:
        defn = _sample_definition()
        repo.register(_PROJECT_KEY, [defn])
        result2 = repo.register(_PROJECT_KEY, [defn])

        assert result2.registered == []
        assert "Bash" in result2.skipped
        assert result2.errors == []

    def test_no_duplicate_rows_in_db(
        self,
        repo: StateBackendHookRegistrationRepository,
    ) -> None:
        defn = _sample_definition()
        repo.register(_PROJECT_KEY, [defn])
        repo.register(_PROJECT_KEY, [defn])
        repo.register(_PROJECT_KEY, [defn])

        listed = repo.list_for_project(_PROJECT_KEY)
        assert len(listed) == 1

    def test_same_matcher_different_event_type_not_skipped(
        self,
        repo: StateBackendHookRegistrationRepository,
    ) -> None:
        """(hook_event_name, matcher) pair is the key — same matcher, different event is new row."""
        pre = _sample_definition(
            hook_event_name=HookEventName.PRE_TOOL_USE,
            matcher="Bash",
            command="agentkit-hook-claude pre branch_guard",
        )
        post = _sample_definition(
            hook_event_name=HookEventName.POST_TOOL_USE,
            matcher="Bash",
            command="agentkit-hook-claude post telemetry",
        )
        result = repo.register(_PROJECT_KEY, [pre, post])

        assert len(result.registered) == 2
        assert result.skipped == []


# ---------------------------------------------------------------------------
# Tests: clear_for_project (test helper)
# ---------------------------------------------------------------------------


class TestGovernanceHookRepositoryClear:
    """clear_for_project removes all registrations for a project."""

    def test_clear_removes_all(
        self,
        repo: StateBackendHookRegistrationRepository,
    ) -> None:
        definitions = _all_hook_definitions()[:3]
        repo.register(_PROJECT_KEY, definitions)

        repo.clear_for_project(_PROJECT_KEY)

        listed = repo.list_for_project(_PROJECT_KEY)
        assert listed == []

    def test_clear_does_not_affect_other_project(
        self,
        repo: StateBackendHookRegistrationRepository,
    ) -> None:
        other_key = "other-project-isolated"
        repo.register(_PROJECT_KEY, [_sample_definition(matcher="Bash")])
        repo.register(other_key, [_sample_definition(matcher="Write|Edit")])

        repo.clear_for_project(_PROJECT_KEY)

        other_listed = repo.list_for_project(other_key)
        own_listed = repo.list_for_project(_PROJECT_KEY)

        assert len(other_listed) == 1
        assert other_listed[0].matcher == "Write|Edit"
        assert own_listed == []

        # Cleanup
        repo.clear_for_project(other_key)


# ---------------------------------------------------------------------------
# Tests: SQLite-only schema bootstrap
# ---------------------------------------------------------------------------


class TestGovernanceHookRepositorySharedMatcher:
    """AG3-031 Hotfix 2026-05-25: shared-matcher hooks must both persist.

    FK-30 §30.3.1 registers branch_guard and story_creation_guard both on
    matcher ``Bash``. The pre-hotfix PK (project_key, hook_event_name, matcher)
    collided on the second insert and overwrote the first, dropping a guard.
    The PK now includes ``command`` (4-tuple), so both rows persist.
    """

    def test_shared_matcher_distinct_command_both_persist(
        self,
        repo: StateBackendHookRegistrationRepository,
    ) -> None:
        branch = _sample_definition(
            matcher="Bash",
            command="agentkit-hook-claude pre branch_guard",
        )
        story = _sample_definition(
            matcher="Bash",
            command="agentkit-hook-claude pre story_creation_guard",
        )

        result = repo.register(_PROJECT_KEY, [branch, story])

        assert len(result.registered) == 2
        assert result.skipped == []
        assert result.errors == []

        listed = repo.list_for_project(_PROJECT_KEY)
        bash = [d for d in listed if d.matcher == "Bash"]
        assert len(bash) == 2, "Both Bash hooks must persist (governance hole closed)"
        assert {d.command for d in bash} == {
            "agentkit-hook-claude pre branch_guard",
            "agentkit-hook-claude pre story_creation_guard",
        }

    def test_shared_matcher_idempotent_reregistration(
        self,
        repo: StateBackendHookRegistrationRepository,
    ) -> None:
        """Re-registering the exact 4-tuple set is fully skipped (idempotent)."""
        branch = _sample_definition(
            matcher="Bash",
            command="agentkit-hook-claude pre branch_guard",
        )
        story = _sample_definition(
            matcher="Bash",
            command="agentkit-hook-claude pre story_creation_guard",
        )

        repo.register(_PROJECT_KEY, [branch, story])
        result2 = repo.register(_PROJECT_KEY, [branch, story])

        assert result2.registered == []
        assert len(result2.skipped) == 2
        assert len(repo.list_for_project(_PROJECT_KEY)) == 2


class TestGovernanceHookRepositorySqliteBootstrap:
    """SQLite schema is created idempotently on every connect."""

    @pytest.mark.usefixtures("sqlite_env")
    def test_double_bootstrap_no_error(self, tmp_path: Path) -> None:
        r1 = StateBackendHookRegistrationRepository(store_dir=tmp_path)
        r2 = StateBackendHookRegistrationRepository(store_dir=tmp_path)

        r1.register("boot-proj", [_sample_definition()])
        r2.register("boot-proj", [_sample_definition()])

        listed = r2.list_for_project("boot-proj")
        assert len(listed) == 1
