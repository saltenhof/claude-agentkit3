"""AG3-081 AC4: the telemetry projection union is typed on the AG3-059 record.

The ``phase_state_projection`` variant of the telemetry-side ``ProjectionRecord``
union references the AG3-059-owned typed ``PhaseState`` record (FK-69 §69.3 /
FK-39 §39.7) instead of ``dict[str, object]``. AG3-081 does NOT define the record
type (Schema-Owner ``pipeline_engine.phase_executor``) and does NOT migrate the
accessor ownership (Write-Owner ``pipeline_engine.PhaseExecutor``; the
ProjectionAccessor keeps refusing ``PHASE_STATE_PROJECTION`` fail-closed).
"""

from __future__ import annotations

import sys
import typing

import pytest

from agentkit.backend.telemetry import projection_records
from agentkit.backend.telemetry.errors import ProjectionKindNotAccessorOwnedError
from agentkit.backend.telemetry.projection_accessor import (
    ProjectionFilter,
    ProjectionKind,
)


def test_projection_union_resolves_phase_state_to_ag3_059_record() -> None:
    # The operative surface is TYPED: the union resolves to the AG3-059-owned
    # PhaseState record (Schema-Owner pipeline_engine.phase_executor), not a
    # local re-definition.
    from agentkit.backend.pipeline_engine.phase_executor import PhaseState as OwnedPhaseState

    assert projection_records.PhaseState is OwnedPhaseState
    union_args = typing.get_args(projection_records.ProjectionRecord)
    assert OwnedPhaseState in union_args


def test_projection_union_is_not_dict_object() -> None:
    # AC4(a): the operative projection surface is no longer ``dict[str, object]``.
    union_args = typing.get_args(projection_records.ProjectionRecord)
    assert dict not in union_args
    assert all(isinstance(member, type) for member in union_args)


def test_telemetry_does_not_import_pipeline_engine_at_module_init() -> None:
    # AC4 anti-circular-import: importing the telemetry projection module must NOT
    # pull pipeline_engine at module init (the typed record is resolved lazily).
    #
    # AG3-081 AC9 test-isolation fix: this probe must mutate ``sys.modules`` (it
    # has to force a fresh module init to observe the lazy import boundary), but it
    # MUST restore every evicted module afterwards. Leaving ``agentkit.pipeline_
    # engine.*`` removed re-imports the package on next access and mints a NEW
    # ``PhaseState`` / ``ClosurePayload`` class identity, which poisons later
    # closure / phase-executor tests that rely on ``is`` / ``isinstance`` against
    # the originally-cached classes. The snapshot/restore keeps the global module
    # state untouched for the rest of the session.
    evicted: dict[str, object] = {
        name: module
        for name, module in sys.modules.items()
        if name.startswith("agentkit.backend.pipeline_engine")
        or name == "agentkit.backend.telemetry.projection_records"
    }
    for name in evicted:
        del sys.modules[name]
    try:
        import agentkit.backend.telemetry.projection_records as fresh  # noqa: F401

        assert "agentkit.backend.pipeline_engine.phase_executor" not in sys.modules
    finally:
        # Restore the original module identities so no later test observes a
        # re-minted class (global sys.modules state stays as it was on entry).
        for name in list(sys.modules):
            if (
                name.startswith("agentkit.backend.pipeline_engine")
                or name == "agentkit.backend.telemetry.projection_records"
            ):
                del sys.modules[name]
        sys.modules.update(evicted)


def test_accessor_still_refuses_phase_state_write_fail_closed() -> None:
    # AC4(b): the Write-Owner stays pipeline_engine.PhaseExecutor — the accessor
    # refuses PHASE_STATE_PROJECTION writes fail-closed (no ownership migration).
    from agentkit.backend.pipeline_engine.phase_executor import PhaseState as OwnedPhaseState

    # A real PhaseState record is still refused on the write path (external owner).
    record = object.__new__(OwnedPhaseState)
    accessor = _accessor_with_no_repos()
    with pytest.raises(ProjectionKindNotAccessorOwnedError) as exc:
        accessor.write_projection(ProjectionKind.PHASE_STATE_PROJECTION, record)  # type: ignore[arg-type]
    assert exc.value.kind is ProjectionKind.PHASE_STATE_PROJECTION
    assert "PhaseExecutor" in str(exc.value)


def test_accessor_still_refuses_phase_state_read_fail_closed() -> None:
    # AC4(b): the Read path also stays fail-closed for the external kind.
    accessor = _accessor_with_no_repos()
    with pytest.raises(ProjectionKindNotAccessorOwnedError) as exc:
        accessor.read_projection(
            ProjectionKind.PHASE_STATE_PROJECTION, ProjectionFilter(story_id="AG3-001")
        )
    assert exc.value.kind is ProjectionKind.PHASE_STATE_PROJECTION


def _accessor_with_no_repos() -> object:
    from agentkit.backend.telemetry.projection_accessor import ProjectionAccessor

    # The refusal is decided BEFORE any repo dispatch, so a bare accessor suffices.
    return ProjectionAccessor.__new__(ProjectionAccessor)
