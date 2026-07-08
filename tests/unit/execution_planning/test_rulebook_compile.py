"""Rulebook compile + admin-only mutation tests (AC4).

AC4: rulebook compile translates raw syntax into the canonical model
(``rulebook_compile_result``), increments ``rulebook_revision`` and triggers a
re-plan (not a hot-reload); a rulebook update is only possible via the
admin/control-plane path (negative test for free mutation). The rulebook DSL is
distinct from the FK-20 FlowDefinition DSL (§70.7d).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.bootstrap.composition_root import build_planning_projection_accessor
from agentkit.backend.execution_planning.audit import PlanningAuditEmitter
from agentkit.backend.execution_planning.persistence.filter import PlanningProjectionFilter
from agentkit.backend.execution_planning.persistence.schema_kind import PlanningSchemaKind
from agentkit.backend.execution_planning.planning_model.rulebook import (
    RulebookCompileStatus,
    RulebookRevision,
)
from agentkit.backend.execution_planning.rulebook_compile import (
    RulebookMutationNotAuthorizedError,
    compile_rulebook,
    update_rulebook_revision,
)
from agentkit.backend.state_backend.config import ALLOW_SQLITE_ENV, STATE_BACKEND_ENV
from agentkit.backend.state_backend.persistence_test_support import reset_backend_cache_for_tests
from agentkit.backend.telemetry.emitters import MemoryEmitter
from agentkit.backend.telemetry.events import EventType

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from agentkit.backend.execution_planning.persistence.accessor import (
        PlanningProjectionAccessor,
    )

_PROJECT = "PROJ-RB"


@pytest.fixture(autouse=True)
def sqlite_env(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    monkeypatch.setenv(STATE_BACKEND_ENV, "sqlite")
    monkeypatch.setenv(ALLOW_SQLITE_ENV, "1")
    reset_backend_cache_for_tests()
    yield
    reset_backend_cache_for_tests()


@pytest.fixture()
def accessor(tmp_path: Path) -> PlanningProjectionAccessor:
    story_dir = tmp_path / "stories" / "AG3-099"
    story_dir.mkdir(parents=True, exist_ok=True)
    return build_planning_projection_accessor(story_dir)


def _revision(raw: str, revision: int = 1) -> RulebookRevision:
    return RulebookRevision(
        project_key=_PROJECT,
        rulebook_id="RB-1",
        revision=revision,
        raw_syntax=raw,
        updated_by_principal="admin:alice",
        created_at=datetime.now(UTC),
    )


def test_compile_raw_to_canonical() -> None:
    """AC4: compile translates raw syntax into the canonical compiled model."""
    result = compile_rulebook(_revision("parallelize S1 S2\nserialize S3 # after S2"))
    assert result.status is RulebookCompileStatus.COMPILED
    assert result.compiled is not None
    assert len(result.compiled.rules) == 2
    assert result.compiled.rules[0].rule_kind == "parallelize"
    assert result.compiled.rules[0].story_ids == ("S1", "S2")
    assert result.compiled.rules[1].detail == "after S2"


def test_compile_skips_blank_and_comment_lines() -> None:
    """AC4: blank lines and full-line ``#`` comments are skipped, not errors.

    Only the two real rule lines compile; the empty line and the comment-only
    line must be ignored (no spurious error, no spurious rule).
    """
    raw = "parallelize S1 S2\n\n   \n# this is a comment line\nserialize S3"
    result = compile_rulebook(_revision(raw))
    assert result.status is RulebookCompileStatus.COMPILED
    assert result.compiled is not None
    assert len(result.compiled.rules) == 2
    assert result.errors == ()


def test_compile_rejects_invalid_syntax_fail_closed() -> None:
    """AC4: invalid syntax yields REJECTED with errors and no compiled form."""
    result = compile_rulebook(_revision("frobnicate S1\nparallelize"))
    assert result.status is RulebookCompileStatus.REJECTED
    assert result.compiled is None
    assert len(result.errors) == 2
    assert result.triggers_replan is False


def test_compile_triggers_replan_not_hot_reload() -> None:
    """AC4: a successful compile mandates a re-plan (not a hot-reload)."""
    result = compile_rulebook(_revision("priority S1"))
    assert result.status is RulebookCompileStatus.COMPILED
    assert result.triggers_replan is True


def test_update_increments_revision_and_triggers_replan(
    accessor: PlanningProjectionAccessor,
) -> None:
    """AC4: an admin update increments rulebook_revision and triggers a re-plan."""
    outcome = update_rulebook_revision(
        project_key=_PROJECT,
        rulebook_id="RB-1",
        raw_syntax="parallelize S1 S2",
        principal="admin:alice",
        accessor=accessor,
        current_revision=4,
    )
    assert outcome.revision.revision == 5
    assert outcome.triggers_replan is True

    revisions = accessor.read_projection(
        PlanningSchemaKind.RULEBOOK_REVISION,
        PlanningProjectionFilter(project_key=_PROJECT, rulebook_id="RB-1"),
    )
    compile_results = accessor.read_projection(
        PlanningSchemaKind.RULEBOOK_COMPILE_RESULT,
        PlanningProjectionFilter(project_key=_PROJECT, rulebook_id="RB-1"),
    )
    assert any(r.revision == 5 for r in revisions)  # type: ignore[attr-defined]
    assert any(c.revision == 5 for c in compile_results)  # type: ignore[attr-defined]


def test_admin_update_emits_rulebook_compiled_and_plan_revised(
    accessor: PlanningProjectionAccessor,
) -> None:
    """AC7: a successful rulebook update emits ``rulebook_compiled`` AND the

    AG3-099 re-plan trigger ``plan_revised`` (FK-70 §70.6.2a: a rulebook change
    mandates a re-plan, not a hot-reload). ``plan_revised.trigger`` records the
    re-plan cause.
    """
    emitter = MemoryEmitter()
    audit = PlanningAuditEmitter(emitter)
    update_rulebook_revision(
        project_key=_PROJECT,
        rulebook_id="RB-1",
        raw_syntax="parallelize S1 S2",
        principal="admin:alice",
        accessor=accessor,
        current_revision=0,
        audit=audit,
        audit_story_id="S1",
    )
    by_type = {event.event_type: event for event in emitter.all_events}
    assert EventType.RULEBOOK_COMPILED in by_type
    assert EventType.PLAN_REVISED in by_type
    assert by_type[EventType.PLAN_REVISED].payload["trigger"] == "rulebook_compiled"


def test_rejected_rulebook_update_does_not_emit_plan_revised(
    accessor: PlanningProjectionAccessor,
) -> None:
    """A REJECTED compile must NOT trigger a re-plan (no ``plan_revised``).

    The re-plan trigger is bound to ``triggers_replan``; a rejected (never
    runtime-truth) rulebook does not revise the plan.
    """
    emitter = MemoryEmitter()
    audit = PlanningAuditEmitter(emitter)
    update_rulebook_revision(
        project_key=_PROJECT,
        rulebook_id="RB-1",
        raw_syntax="frobnicate S1",  # invalid -> REJECTED
        principal="admin:alice",
        accessor=accessor,
        current_revision=0,
        audit=audit,
        audit_story_id="S1",
    )
    emitted = {event.event_type for event in emitter.all_events}
    assert EventType.RULEBOOK_COMPILED in emitted
    assert EventType.PLAN_REVISED not in emitted


def test_free_agent_mutation_rejected(
    accessor: PlanningProjectionAccessor,
) -> None:
    """AC4 negative test: a non-admin principal cannot mutate the rulebook."""
    with pytest.raises(RulebookMutationNotAuthorizedError):
        update_rulebook_revision(
            project_key=_PROJECT,
            rulebook_id="RB-1",
            raw_syntax="parallelize S1 S2",
            principal="agent:rogue",
            accessor=accessor,
            current_revision=0,
        )

    # FAIL-CLOSED: nothing was persisted by the rejected mutation.
    revisions = accessor.read_projection(
        PlanningSchemaKind.RULEBOOK_REVISION,
        PlanningProjectionFilter(project_key=_PROJECT, rulebook_id="RB-1"),
    )
    assert revisions == []
